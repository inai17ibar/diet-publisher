import base64
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import (
    AppSetting,
    MealLog,
    StoryImageLog,
    StoryPostLog,
    get_session,
)
from app.models.schemas import (
    DailyMealInput,
    DailySummaryResponse,
    HealthCheckResponse,
    MealInput,
    MealLogResponse,
    MealType,
    PostResult,
)
from app.services.day_counter import calculate_day_number
from app.services.diet_mcp_client import DietMcpError, fetch_daily_summary
from app.services.instagram_story import (
    InstagramStoryError,
    publish_story,
    refresh_access_token,
)
from app.services.meal_processor import create_and_post, process_single_meal
from app.services.openai_service import generate_story_advice
from app.services.story_image import create_notice_image, create_story_image

router = APIRouter()

JST = timezone(timedelta(hours=9))


def _now_jst() -> datetime:
    """現在時刻（JST）。テストで差し替えられるよう関数にしている"""
    return datetime.now(JST)


async def verify_api_key(x_api_key: Annotated[str | None, Header()] = None):
    """APIキー認証"""
    if x_api_key != settings.secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """ヘルスチェック"""
    return HealthCheckResponse(status="ok")


@router.get("/meal/day-number")
async def get_day_number(
    date: str | None = Query(None, description="対象日 (YYYY-MM-DD)"),
    _: None = Depends(verify_api_key),
):
    """指定日または今日のDay数を返す。"""
    target_date = datetime.fromisoformat(date).date() if date else datetime.now().date()
    return {"date": target_date.isoformat(), "day_number": calculate_day_number(target_date)}


@router.post("/meal/analyze", response_model=PostResult)
async def analyze_meal(
    meal: MealInput,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """単一の食事を分析（投稿なし）"""
    pfc = await process_single_meal(meal)
    return PostResult(success=True, pfc=pfc)


@router.post("/meal/post", response_model=PostResult)
async def post_meal(
    daily_input: DailyMealInput,
    auto_post: bool = True,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """食事を処理して共有用の画像と投稿文を作成"""
    result = await create_and_post(daily_input, session, auto_post=auto_post)
    return result


@router.post("/meal/quick", response_model=PostResult)
async def quick_post(
    description: str,
    auto_post: bool = True,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """
    簡易モード：テキストだけで記録

    例: "昼：サラダチキン、夜：豚しゃぶ"
    """
    daily_input = DailyMealInput(
        date=datetime.now(),
        total_description=description,
    )
    result = await create_and_post(daily_input, session, auto_post=auto_post)
    return result


@router.post("/shortcut/meal", response_model=PostResult)
async def shortcut_endpoint(
    meal_type: MealType = MealType.LUNCH,
    description: str | None = None,
    image_base64: str | None = None,
    auto_post: bool = True,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """
    iPhoneショートカット用エンドポイント

    - meal_type: breakfast/lunch/dinner/snack
    - description: 食事の説明（任意）
    - image_base64: 写真のBase64（任意）
    - auto_post: 互換性のため残しているが現在は使用しない
    """
    meal = MealInput(
        meal_type=meal_type,
        description=description,
        image_base64=image_base64,
    )
    daily_input = DailyMealInput(
        date=datetime.now(),
        meals=[meal],
    )
    result = await create_and_post(daily_input, session, auto_post=auto_post)
    return result


async def _record_story_generated(session: AsyncSession, date_str: str) -> None:
    """ストーリー画像の生成台帳に日付を記録する（記録済みなら何もしない）"""
    result = await session.execute(
        select(StoryImageLog.id).where(StoryImageLog.date == date_str)
    )
    if result.scalar_one_or_none() is None:
        session.add(StoryImageLog(date=date_str))
        await session.commit()


@router.get("/story/image")
async def story_image(
    date: str | None = Query(None, description="対象日 (YYYY-MM-DD、省略時はJSTの今日)"),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """指定日のストーリー画像（1080x1920 JPEG）を返す。

    生成済みでも常に作り直す明示指定用。生成台帳には記録するので、
    /story/next はこの日をスキップするようになる。
    """
    try:
        summary = await fetch_daily_summary(date)
    except DietMcpError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    if not summary.get("meals"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="この日の食事記録がありません",
        )

    target_date = datetime.fromisoformat(summary["date"]).date()
    day_number = calculate_day_number(target_date)
    advice = await _generate_advice_safe(session, summary, day_number)
    image_bytes = create_story_image(summary, day_number, advice=advice)
    await _record_story_generated(session, summary["date"])
    return Response(
        content=image_bytes,
        media_type="image/jpeg",
        headers={"X-Story-Date": summary["date"], "X-Story-Status": "generated"},
    )


async def _get_app_setting(session: AsyncSession, key: str) -> str | None:
    setting = await session.get(AppSetting, key)
    return setting.value if setting else None


async def _set_app_setting(session: AsyncSession, key: str, value: str) -> None:
    setting = await session.get(AppSetting, key)
    if setting is None:
        session.add(AppSetting(key=key, value=value))
    else:
        setting.value = value
    await session.commit()


async def _recent_advices(session: AsyncSession, limit: int = 7) -> list[str]:
    result = await session.execute(
        select(StoryPostLog.advice).order_by(StoryPostLog.date.desc()).limit(limit)
    )
    return [a for a in result.scalars().all() if a]


async def _generate_advice_safe(
    session: AsyncSession, summary: dict, day_number: int | None
) -> str | None:
    """AIコーチの一言を生成する。失敗しても画像生成は止めない。"""
    try:
        previous = await _recent_advices(session)
        return await generate_story_advice(summary, day_number, previous)
    except Exception:
        return None


async def _build_story(session: AsyncSession, target: str) -> tuple[bytes, str | None] | None:
    """対象日の画像とAIコーチの一言を作る。記録が無い日はNone。"""
    summary = await fetch_daily_summary(target)
    if not summary.get("meals"):
        return None
    day_number = calculate_day_number(datetime.fromisoformat(target).date())
    advice = await _generate_advice_safe(session, summary, day_number)
    image_bytes = create_story_image(summary, day_number, advice=advice)
    await _record_story_generated(session, target)
    return image_bytes, advice


async def _render_story(session: AsyncSession, target: str) -> Response:
    built = await _build_story(session, target)
    if built is None:
        return None
    image_bytes, _ = built
    return Response(
        content=image_bytes,
        media_type="image/jpeg",
        headers={"X-Story-Date": target, "X-Story-Status": "generated"},
    )


@router.get("/story/next")
async def story_next(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """今日（または昨日）のストーリー画像を返す。

    1. 今日に食事記録があれば、常に最新データで今日の画像を生成する
       （日中に記録が増えるため、生成済みでも作り直す）
    2. 今日がまだ空なら、昨日に記録があり未生成の場合だけ昨日を生成する
       （前日の作り忘れ救済。それより過去へはさかのぼらない）
    3. どちらも無ければ案内画像を返す（ショートカットが常に画像を
       保存できるように、エラーJSONではなく画像で返す）
    """
    today = datetime.now(JST).date()
    try:
        response = await _render_story(session, today.isoformat())
        if response is not None:
            return response

        yesterday = (today - timedelta(days=1)).isoformat()
        result = await session.execute(
            select(StoryImageLog.id).where(StoryImageLog.date == yesterday)
        )
        if result.scalar_one_or_none() is None:
            response = await _render_story(session, yesterday)
            if response is not None:
                return response
    except DietMcpError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    notice = create_notice_image(
        ["新しく作る画像はありません", "（今日の記録がまだ無いか、昨日の分は生成済みです）"]
    )
    return Response(
        content=notice,
        media_type="image/jpeg",
        headers={"X-Story-Status": "none"},
    )


@router.post("/story/mark-posted")
async def story_mark_posted(
    date: str = Query(..., description="投稿済みにする日付 (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """指定日を投稿済みとして台帳に記録する（実際の投稿はしない）。

    手動でストーリーに上げてしまった日をcronにスキップさせるための管理用。
    """
    try:
        datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="日付はYYYY-MM-DD形式で指定"
        )
    existing = await session.execute(select(StoryPostLog.id).where(StoryPostLog.date == date))
    if existing.scalar_one_or_none() is not None:
        return {"status": "already_posted", "date": date}
    session.add(StoryPostLog(date=date, media_id=None, advice=None))
    await session.commit()
    return {"status": "marked", "date": date}


@router.post("/story/publish")
async def story_publish(
    test: bool = Query(False, description="接続テスト用の特別画像を投稿する（台帳に記録しない）"),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """記録の状態を見て「投稿すべき日」を選び、ストーリーに自動投稿する（cron用）。

    食事の入力時刻がまちまち（当日夜のことも翌朝のことも）でも取りこぼさない
    よう、cronは1日に数回動き、毎回この優先順位で判断する:
    1. 今日: JSTで21時以降、今日に記録があり未投稿なら投稿（当日夜パターン）
    2. 昨日: 記録があり未投稿なら投稿（翌朝に前日分を入力するパターンの救済）
    同じ日に二度は投稿しない（冪等）。投稿成功のたびにアクセストークンを
    更新してDBに保存するので、投稿が動いている限りトークンは失効しない。
    """
    now = _now_jst()
    candidates = []
    if now.hour >= 21:
        candidates.append(now.date().isoformat())
    candidates.append((now.date() - timedelta(days=1)).isoformat())

    user_id = settings.instagram_user_id
    token = (
        await _get_app_setting(session, "instagram_access_token")
        or settings.instagram_access_token
    )
    if not user_id or not token:
        # cronから叩かれるため、セットアップ前でもエラーにはしない
        return {
            "status": "not_configured",
            "detail": "INSTAGRAM_USER_ID / INSTAGRAM_ACCESS_TOKEN が未設定です",
        }

    if test:
        # 接続テスト: 台帳に記録せず、日次画像とは別のテスト画像を投稿する
        image_bytes = create_notice_image(
            [
                "AUTO-POST TEST",
                now.strftime("%Y.%m.%d %H:%M"),
                "diet-publisher → Instagram 接続確認",
            ]
        )
        filename = f"story_test_{secrets.token_urlsafe(12)}.jpg"
        (settings.images_dir / filename).write_bytes(image_bytes)
        image_url = f"{settings.public_base_url.rstrip('/')}/api/v1/public/story/{filename}"
        try:
            media_id = await publish_story(user_id, token, image_url)
        except InstagramStoryError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
        return {"status": "test_posted", "media_id": media_id}

    for target in candidates:
        # media_idではなく行の存在で判定する（手動マーク行はmedia_idがNULLのため）
        existing = await session.execute(
            select(StoryPostLog.id).where(StoryPostLog.date == target)
        )
        if existing.scalar_one_or_none() is not None:
            continue

        try:
            built = await _build_story(session, target)
        except DietMcpError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
        if built is None:
            continue
        image_bytes, advice = built

        # Graph APIは公開URLから画像を取得するため、推測不能な名前で配信する
        filename = f"story_{target.replace('-', '')}_{secrets.token_urlsafe(12)}.jpg"
        (settings.images_dir / filename).write_bytes(image_bytes)
        image_url = f"{settings.public_base_url.rstrip('/')}/api/v1/public/story/{filename}"

        try:
            media_id = await publish_story(user_id, token, image_url)
        except InstagramStoryError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

        session.add(StoryPostLog(date=target, media_id=media_id, advice=advice))
        await session.commit()

        # トークンの延命（失敗しても投稿自体には影響しない）
        new_token = await refresh_access_token(token)
        if new_token:
            await _set_app_setting(session, "instagram_access_token", new_token)

        return {"status": "posted", "date": target, "media_id": media_id, "advice": advice}

    return {"status": "nothing_to_post", "date": now.date().isoformat()}


@router.get("/public/story/{filename}")
async def public_story_image(filename: str):
    """Graph APIが画像を取得するための公開配信（推測不能なファイル名で保護）"""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.jpg", filename):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    path = settings.images_dir / filename
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(path, media_type="image/jpeg")


class InstagramTokenRequest(BaseModel):
    """Instagram長期アクセストークンの登録リクエスト"""

    access_token: str


@router.post("/instagram/token")
async def set_instagram_token(
    req: InstagramTokenRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """Instagramの長期アクセストークンを保存する（初回セットアップ・手動更新用）"""
    await _set_app_setting(session, "instagram_access_token", req.access_token)
    return {"success": True}


@router.get("/meal/history", response_model=list[MealLogResponse])
async def get_meal_history(
    start_date: str | None = Query(None, description="開始日 (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="終了日 (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """食事ログの履歴を取得"""
    query = select(MealLog).order_by(MealLog.date.desc())

    if start_date:
        query = query.where(MealLog.date >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.where(
            MealLog.date <= datetime.fromisoformat(end_date + "T23:59:59")
        )

    result = await session.execute(query)
    logs = result.scalars().all()

    return [
        MealLogResponse(
            id=log.id,
            date=log.date.strftime("%Y-%m-%d"),
            day_number=calculate_day_number(log.date),
            protein=log.protein,
            fat=log.fat,
            carbs=log.carbs,
            calories=log.calories,
            meal_description=log.meal_description,
            ai_comment=log.ai_comment,
            mode=log.mode or "text_only",
        )
        for log in logs
    ]


@router.delete("/meal/log/{log_id}")
async def delete_meal_log(
    log_id: int,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """食事ログを削除（重複記録の修正用）"""
    log = await session.get(MealLog, log_id)
    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal log not found",
        )
    await session.delete(log)
    await session.commit()
    return {"success": True, "deleted_id": log_id}


@router.get("/meal/daily-summary", response_model=list[DailySummaryResponse])
async def get_daily_summary(
    days: int = Query(30, description="取得する日数"),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """日別のPFCサマリーを取得"""
    query = (
        select(
            func.date(MealLog.date).label("date"),
            func.sum(MealLog.protein).label("total_protein"),
            func.sum(MealLog.fat).label("total_fat"),
            func.sum(MealLog.carbs).label("total_carbs"),
            func.sum(MealLog.calories).label("total_calories"),
            func.count(MealLog.id).label("meal_count"),
        )
        .group_by(func.date(MealLog.date))
        .order_by(func.date(MealLog.date).desc())
        .limit(days)
    )

    result = await session.execute(query)
    rows = result.all()

    return [
        DailySummaryResponse(
            date=str(row.date),
            day_number=calculate_day_number(datetime.fromisoformat(str(row.date))),
            total_protein=row.total_protein or 0,
            total_fat=row.total_fat or 0,
            total_carbs=row.total_carbs or 0,
            total_calories=row.total_calories or 0,
            meal_count=row.meal_count,
        )
        for row in rows
    ]


class ImageUploadRequest(BaseModel):
    """代表画像アップロードリクエスト"""

    date: str
    image_base64: str


@router.post("/meal/upload-image")
async def upload_daily_image(
    req: ImageUploadRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """1日の代表画像をアップロード。"""
    target_date = datetime.fromisoformat(req.date)

    # Find meal logs for this date
    query = select(MealLog).where(
        func.date(MealLog.date) == target_date.date()
    )
    result = await session.execute(query)
    logs = result.scalars().all()

    if not logs:
        raise HTTPException(status_code=404, detail="この日の食事記録が見つかりません")

    # Save image
    image_data = base64.b64decode(req.image_base64)
    date_str = target_date.strftime("%Y%m%d")
    image_filename = f"meal_{date_str}_custom.jpg"
    image_path = settings.images_dir / image_filename
    image_path.write_bytes(image_data)

    # Update all logs for this date
    for log in logs:
        log.image_path = str(image_path)
        log.mode = "photo"
    await session.commit()

    return {"success": True, "image_path": str(image_path)}
