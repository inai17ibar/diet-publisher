import base64
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import MealLog, StoryImageLog, get_session
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
from app.services.meal_processor import create_and_post, process_single_meal
from app.services.story_image import create_notice_image, create_story_image

router = APIRouter()

JST = timezone(timedelta(hours=9))
STORY_LOOKBACK_DAYS = 7


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
    image_bytes = create_story_image(summary, day_number)
    await _record_story_generated(session, summary["date"])
    return Response(
        content=image_bytes,
        media_type="image/jpeg",
        headers={"X-Story-Date": summary["date"], "X-Story-Status": "generated"},
    )


@router.get("/story/next")
async def story_next(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_api_key),
):
    """まだ画像を作っていない直近日のストーリー画像を返す。

    今日から過去7日を新しい順に見て「食事記録があり、生成台帳に無い日」を
    最初に見つけたらその画像を生成して返す。全て生成済みまたは記録なしの
    場合は案内画像を返す（ショートカットが常に画像を保存できるように、
    エラーJSONではなく画像で返す）。
    """
    today = datetime.now(JST).date()
    candidates = [today - timedelta(days=i) for i in range(STORY_LOOKBACK_DAYS)]
    result = await session.execute(
        select(StoryImageLog.date).where(
            StoryImageLog.date.in_([d.isoformat() for d in candidates])
        )
    )
    generated = set(result.scalars().all())

    for candidate in candidates:
        date_str = candidate.isoformat()
        if date_str in generated:
            continue
        try:
            summary = await fetch_daily_summary(date_str)
        except DietMcpError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
        if not summary.get("meals"):
            continue
        day_number = calculate_day_number(candidate)
        image_bytes = create_story_image(summary, day_number)
        await _record_story_generated(session, date_str)
        return Response(
            content=image_bytes,
            media_type="image/jpeg",
            headers={"X-Story-Date": date_str, "X-Story-Status": "generated"},
        )

    notice = create_notice_image(
        ["新しく作る画像はありません", f"（直近{STORY_LOOKBACK_DAYS}日は生成済みか記録なし）"]
    )
    return Response(
        content=notice,
        media_type="image/jpeg",
        headers={"X-Story-Status": "none"},
    )


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
