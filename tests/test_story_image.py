"""Tests for the story image generator and endpoint."""

import io
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.services.story_image import create_story_image


@pytest.fixture(autouse=True)
def _mock_advice():
    """AIコーチの一言はOpenAIを呼ぶため、このモジュールでは常にモックする。"""
    with patch(
        "app.api.routes.generate_story_advice",
        new_callable=AsyncMock,
        return_value="サラダチキン2日連続、タンパク質の勝ちパターンできてる！",
    ) as mock:
        yield mock


def _meal(time, description, calories, protein=None, fat=None, carbs=None):
    return {
        "id": f"{time}-{description}",
        "date": "2026-07-26",
        "time": time,
        "description": description,
        "calories": calories,
        "tags": [],
        "protein_g": protein,
        "fat_g": fat,
        "carbs_g": carbs,
    }


SAMPLE_SUMMARY = {
    "date": "2026-07-26",
    "total_calories": 1450.0,
    "nutrients": {"protein_g": 95.0, "fat_g": 40.0, "carbs_g": 160.0},
    "calorie_goal": 1800.0,
    "calories_remaining": 350.0,
    "meals": [
        _meal("08:00", "バナナとヨーグルト", 250.0, 10, 5, 40),
        _meal("12:30", "サラダチキンと玄米おにぎり", 500.0, 45, 10, 60),
        _meal("19:00", "豚しゃぶと野菜たっぷり味噌汁の定食セット", 700.0, 40, 25, 60),
    ],
}


def test_create_story_image_dimensions():
    data = create_story_image(SAMPLE_SUMMARY, day_number=402)
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (1080, 1920)
        assert img.format == "JPEG"


def test_create_story_image_without_goal_or_nutrients():
    """目標・栄養素なし、食事多数（省略行あり）でも落ちない。"""
    summary = {
        "date": "2026-07-26",
        "total_calories": 2300.0,
        "nutrients": {"protein_g": None, "fat_g": None, "carbs_g": None},
        "meals": [_meal(f"{h:02d}:00", f"食事{h}", 300.0) for h in range(8, 16)],
    }
    data = create_story_image(summary, day_number=None)
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (1080, 1920)


def test_pfc_targets_derived_from_calorie_goal():
    from app.services.story_image import _pfc_targets

    targets = _pfc_targets(2000)
    assert targets["protein_g"] == 135  # 90kg x 1.5g
    assert round(targets["fat_g"]) == 56  # 2000 x 25% / 9
    assert round(targets["carbs_g"]) == 240  # 残りカロリー / 4
    assert _pfc_targets(None) is None


def test_create_story_image_over_goal():
    summary = {**SAMPLE_SUMMARY, "total_calories": 2100.0, "calories_remaining": -300.0}
    data = create_story_image(summary, day_number=402)
    assert len(data) > 0


@pytest.mark.asyncio
async def test_story_image_endpoint(client, api_headers):
    with patch(
        "app.api.routes.fetch_daily_summary",
        new_callable=AsyncMock,
        return_value=SAMPLE_SUMMARY,
    ):
        response = await client.get("/api/v1/story/image", headers=api_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(response.content)) as img:
        assert img.size == (1080, 1920)


@pytest.mark.asyncio
async def test_story_image_endpoint_no_meals(client, api_headers):
    empty = {"date": "2026-07-26", "total_calories": 0, "nutrients": {}, "meals": []}
    with patch(
        "app.api.routes.fetch_daily_summary", new_callable=AsyncMock, return_value=empty
    ):
        response = await client.get("/api/v1/story/image", headers=api_headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_story_image_endpoint_diet_mcp_error(client, api_headers):
    from app.services.diet_mcp_client import DietMcpError

    with patch(
        "app.api.routes.fetch_daily_summary",
        new_callable=AsyncMock,
        side_effect=DietMcpError("接続失敗"),
    ):
        response = await client.get("/api/v1/story/image", headers=api_headers)

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_story_image_endpoint_requires_api_key(client):
    response = await client.get("/api/v1/story/image", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def _fake_fetch_factory(meal_dates: set[str]):
    """指定した日付だけ食事がある fetch_daily_summary のモックを作る。"""

    async def fake(date_str=None):
        if date_str in meal_dates:
            return {**SAMPLE_SUMMARY, "date": date_str}
        return {"date": date_str or "2026-01-01", "total_calories": 0, "nutrients": {}, "meals": []}

    return fake


def _yesterday_jst() -> str:
    from app.api.routes import JST

    return (datetime.now(JST).date() - timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_story_next_generates_latest_ungenerated_day(client, api_headers):
    """今日に記録がなければ昨日の画像が生成され、2回目は案内画像になる。"""
    yesterday = _yesterday_jst()
    with patch(
        "app.api.routes.fetch_daily_summary", side_effect=_fake_fetch_factory({yesterday})
    ):
        r1 = await client.get("/api/v1/story/next", headers=api_headers)
        r2 = await client.get("/api/v1/story/next", headers=api_headers)

    assert r1.status_code == 200
    assert r1.headers["x-story-status"] == "generated"
    assert r1.headers["x-story-date"] == yesterday
    with Image.open(io.BytesIO(r1.content)) as img:
        assert img.size == (1080, 1920)

    assert r2.status_code == 200
    assert r2.headers["x-story-status"] == "none"
    with Image.open(io.BytesIO(r2.content)) as img:
        assert img.size == (1080, 1920)


@pytest.mark.asyncio
async def test_story_next_always_regenerates_today(client, api_headers):
    """今日に記録があれば、生成済みでも常に今日を最新データで作り直す。"""
    from app.api.routes import JST

    today = datetime.now(JST).date().isoformat()
    yesterday = _yesterday_jst()
    with patch(
        "app.api.routes.fetch_daily_summary",
        side_effect=_fake_fetch_factory({today, yesterday}),
    ):
        r1 = await client.get("/api/v1/story/next", headers=api_headers)
        r2 = await client.get("/api/v1/story/next", headers=api_headers)

    assert r1.headers["x-story-date"] == today
    assert r2.headers["x-story-date"] == today
    assert r2.headers["x-story-status"] == "generated"


@pytest.mark.asyncio
async def test_story_next_does_not_dig_past_yesterday(client, api_headers):
    """一昨日以前に未生成の記録があっても掘り返さない。"""
    from app.api.routes import JST

    two_days_ago = (datetime.now(JST).date() - timedelta(days=2)).isoformat()
    with patch(
        "app.api.routes.fetch_daily_summary",
        side_effect=_fake_fetch_factory({two_days_ago}),
    ):
        response = await client.get("/api/v1/story/next", headers=api_headers)

    assert response.headers["x-story-status"] == "none"


@pytest.mark.asyncio
async def test_explicit_story_image_marks_date_generated(client, api_headers):
    """/story/image で明示生成した日は /story/next でスキップされる。"""
    yesterday = _yesterday_jst()
    with patch(
        "app.api.routes.fetch_daily_summary", side_effect=_fake_fetch_factory({yesterday})
    ):
        r1 = await client.get(f"/api/v1/story/image?date={yesterday}", headers=api_headers)
        r2 = await client.get("/api/v1/story/next", headers=api_headers)

    assert r1.status_code == 200
    assert r1.headers["x-story-status"] == "generated"
    assert r2.headers["x-story-status"] == "none"


def test_create_story_image_with_advice():
    """AIコーチの一言カード付きでも正しいサイズで描画できる。"""
    data = create_story_image(
        SAMPLE_SUMMARY,
        day_number=402,
        advice="サラダチキン2日連続、タンパク質の勝ちパターンできてる！明日は脂質をあと10gだけ絞ろう",
    )
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (1080, 1920)


def _publish_mocks(tmp_path, user_id="12345", token="long-lived-token"):
    """story/publishテスト用のsettingsモックを作る。"""
    from unittest.mock import MagicMock

    mock_settings = MagicMock()
    mock_settings.secret_key = "test-secret"
    mock_settings.images_dir = tmp_path
    mock_settings.public_base_url = "http://testserver"
    mock_settings.instagram_user_id = user_id
    mock_settings.instagram_access_token = token
    return mock_settings


def _fixed_now(hour: int):
    """JSTの今日のhour時に固定した _now_jst のモックを返す。"""
    from app.api.routes import JST

    fixed = datetime.now(JST).replace(hour=hour, minute=0, second=0, microsecond=0)
    return lambda: fixed


@pytest.mark.asyncio
async def test_story_publish_posts_today_at_night_and_is_idempotent(
    client, api_headers, tmp_path
):
    from app.api.routes import JST

    today = datetime.now(JST).date().isoformat()
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(22)),
        patch(
            "app.api.routes.fetch_daily_summary",
            side_effect=_fake_fetch_factory({today}),
        ),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="998877"
        ) as mock_publish,
        patch("app.api.routes.refresh_access_token", new_callable=AsyncMock, return_value=None),
    ):
        r1 = await client.post("/api/v1/story/publish", headers=api_headers)
        r2 = await client.post("/api/v1/story/publish", headers=api_headers)

    assert r1.status_code == 200
    body = r1.json()
    assert body["status"] == "posted"
    assert body["date"] == today
    assert body["media_id"] == "998877"
    assert body["advice"]

    # 画像が公開ディレクトリに保存され、そのURLがGraph APIに渡っている
    saved = list(tmp_path.glob("story_*.jpg"))
    assert len(saved) == 1
    called_url = mock_publish.call_args.args[2]
    assert saved[0].name in called_url

    # 2回目は投稿しない
    assert r2.json()["status"] == "nothing_to_post"
    assert mock_publish.call_count == 1


@pytest.mark.asyncio
async def test_story_publish_catches_up_yesterday_in_the_morning(
    client, api_headers, tmp_path
):
    """翌朝に前日分を入力するパターン: 朝のcronで昨日の分が投稿される。"""
    yesterday = _yesterday_jst()
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(7)),
        patch(
            "app.api.routes.fetch_daily_summary",
            side_effect=_fake_fetch_factory({yesterday}),
        ),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="777"
        ),
        patch("app.api.routes.refresh_access_token", new_callable=AsyncMock, return_value=None),
    ):
        response = await client.post("/api/v1/story/publish", headers=api_headers)

    body = response.json()
    assert body["status"] == "posted"
    assert body["date"] == yesterday


@pytest.mark.asyncio
async def test_story_publish_does_not_post_today_before_evening(
    client, api_headers, tmp_path
):
    """昼間は今日の分をまだ投稿しない（夜に記録が増えるため）。"""
    from app.api.routes import JST

    today = datetime.now(JST).date().isoformat()
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(13)),
        patch(
            "app.api.routes.fetch_daily_summary",
            side_effect=_fake_fetch_factory({today}),
        ),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="x"
        ) as mock_publish,
    ):
        response = await client.post("/api/v1/story/publish", headers=api_headers)

    assert response.json()["status"] == "nothing_to_post"
    assert mock_publish.call_count == 0


def _partial_day_fetch_factory(date_to_meals: dict):
    """日付ごとに好きな食事リストを返す fetch_daily_summary のモック。"""

    async def fake(date_str=None):
        meals = date_to_meals.get(date_str)
        if meals:
            return {**SAMPLE_SUMMARY, "date": date_str, "meals": meals}
        return {"date": date_str or "2026-01-01", "total_calories": 0, "nutrients": {}, "meals": []}

    return fake


@pytest.mark.asyncio
async def test_story_publish_skips_day_missing_meals(client, api_headers, tmp_path):
    """朝昼だけの日はストーリーに投稿しない（1日の記録として不完全なため）。"""
    from app.api.routes import JST

    today = datetime.now(JST).date().isoformat()
    breakfast_and_lunch = [
        _meal("08:00", "バナナとヨーグルト", 250.0, 10, 5, 40),
        _meal("12:30", "サラダチキンと玄米おにぎり", 500.0, 45, 10, 60),
    ]
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(22)),
        patch(
            "app.api.routes.fetch_daily_summary",
            side_effect=_partial_day_fetch_factory({today: breakfast_and_lunch}),
        ),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="x"
        ) as mock_publish,
    ):
        response = await client.post("/api/v1/story/publish", headers=api_headers)

    body = response.json()
    assert body["status"] == "incomplete"
    assert body["skipped"][0]["date"] == today
    assert body["skipped"][0]["missing"] == ["dinner"]
    assert body["skipped"][0]["missing_label"] == "夜"
    assert mock_publish.call_count == 0


@pytest.mark.asyncio
async def test_story_publish_posts_once_the_missing_meal_arrives(
    client, api_headers, tmp_path
):
    """見送った日でも台帳には残らないので、夜を記録すれば次のcronで投稿される。"""
    from app.api.routes import JST

    today = datetime.now(JST).date().isoformat()
    meals = [
        _meal("08:00", "バナナとヨーグルト", 250.0, 10, 5, 40),
        _meal("12:30", "サラダチキンと玄米おにぎり", 500.0, 45, 10, 60),
    ]
    fetch = _partial_day_fetch_factory({today: meals})
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(22)),
        patch("app.api.routes.fetch_daily_summary", side_effect=fetch),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="555"
        ) as mock_publish,
        patch("app.api.routes.refresh_access_token", new_callable=AsyncMock, return_value=None),
    ):
        first = await client.post("/api/v1/story/publish", headers=api_headers)
        meals.append(_meal("19:00", "豚しゃぶ定食", 700.0, 40, 25, 60))
        second = await client.post("/api/v1/story/publish", headers=api_headers)

    assert first.json()["status"] == "incomplete"
    assert second.json()["status"] == "posted"
    assert second.json()["date"] == today
    assert mock_publish.call_count == 1


@pytest.mark.asyncio
async def test_story_next_still_generates_for_incomplete_day(client, api_headers):
    """手動生成（iOSショートカット）は3食そろっていなくても画像を返す。"""
    from app.api.routes import JST

    today = datetime.now(JST).date().isoformat()
    with patch(
        "app.api.routes.fetch_daily_summary",
        side_effect=_partial_day_fetch_factory(
            {today: [_meal("08:00", "バナナとヨーグルト", 250.0)]}
        ),
    ):
        response = await client.get("/api/v1/story/next", headers=api_headers)

    assert response.headers["x-story-status"] == "generated"
    assert response.headers["x-story-date"] == today


@pytest.mark.asyncio
async def test_story_publish_nothing_without_meals(client, api_headers, tmp_path):
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(22)),
        patch(
            "app.api.routes.fetch_daily_summary",
            side_effect=_fake_fetch_factory(set()),
        ),
    ):
        response = await client.post("/api/v1/story/publish", headers=api_headers)

    assert response.json()["status"] == "nothing_to_post"


@pytest.mark.asyncio
async def test_story_publish_not_configured_is_not_an_error(client, api_headers, tmp_path):
    """認証情報が未設定でもcronが失敗扱いにならないよう200で返す。"""
    with patch("app.api.routes.settings", _publish_mocks(tmp_path, user_id="", token="")):
        response = await client.post("/api/v1/story/publish", headers=api_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"


@pytest.mark.asyncio
async def test_public_story_serving(client, api_headers, tmp_path):
    (tmp_path / "story_test_abc.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")
    with patch("app.api.routes.settings", _publish_mocks(tmp_path)):
        ok = await client.get("/api/v1/public/story/story_test_abc.jpg")
        bad_name = await client.get("/api/v1/public/story/..%2Fsecret.txt")
        missing = await client.get("/api/v1/public/story/story_nope.jpg")

    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/jpeg"
    assert bad_name.status_code == 404
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_set_instagram_token(client, api_headers):
    response = await client.post(
        "/api/v1/instagram/token",
        headers=api_headers,
        json={"access_token": "new-token"},
    )
    assert response.status_code == 200

    from app.api.routes import _get_app_setting
    from tests.conftest import test_session

    async with test_session() as session:
        stored = await _get_app_setting(session, "instagram_access_token")
    assert stored == "new-token"


def test_wrap_text_does_not_start_a_line_with_punctuation():
    """禁則処理: 句読点や閉じ括弧だけが次の行の頭に送られない。"""
    from PIL import Image, ImageDraw

    from app.services.story_image import _font, _wrap_text

    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = _font(36)
    text = "火木の外食で2000kcal超え。土曜は記録も抜けた。来週は昼を固定しよう。"
    width = draw.textlength("あ" * 12, font=font)
    lines = _wrap_text(draw, text, font, width, max_lines=4)

    assert len(lines) > 1
    assert all(line[0] not in "。、）」" for line in lines)


def test_wrap_text_keeps_alphanumeric_words_together():
    """"600kcal" のような英数字のまとまりが行またぎで割れない。"""
    from PIL import Image, ImageDraw

    from app.services.story_image import _font, _wrap_text

    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = _font(34)
    text = "来週は外食の日だけ昼を600kcalに固定しよう。木曜は2250kcalだった。"
    width = draw.textlength("あ" * 10, font=font)
    lines = _wrap_text(draw, text, font, width, max_lines=6)

    assert len(lines) > 1
    assert all("kcal" in line for line in lines if "kca" in line)
    assert "600kcal" in "".join(lines)


def test_clean_text_strips_emoji():
    """フォントで描画できない絵文字・記号は除去される。"""
    from app.services.story_image import _clean_text

    assert _clean_text("今日もいい感じ🔥💪") == "今日もいい感じ"
    assert _clean_text("鶏むね⭐️と野菜🥗のスープ") == "鶏むねと野菜のスープ"
    assert _clean_text("👨‍👩‍👧 家族で外食") == "家族で外食"
    assert _clean_text("普通のテキスト。P95g!") == "普通のテキスト。P95g!"
    assert _clean_text(None) == ""


def test_create_story_image_with_emoji_advice_and_meals():
    """絵文字入りの一言・食事名でも文字化けせず描画できる（除去される）。"""
    summary = {
        **SAMPLE_SUMMARY,
        "meals": [_meal("08:00", "オイコス🍨とバナナ🍌", 250.0)],
    }
    data = create_story_image(summary, day_number=410, advice="タンパク質順調🔥その調子💪")
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (1080, 1920)


@pytest.mark.asyncio
async def test_story_mark_posted_makes_cron_skip(client, api_headers, tmp_path):
    """手動投稿済みの日をマークすると、cronはその日を投稿しない。"""
    yesterday = _yesterday_jst()
    r1 = await client.post(
        f"/api/v1/story/mark-posted?date={yesterday}", headers=api_headers
    )
    assert r1.json()["status"] == "marked"

    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(7)),
        patch(
            "app.api.routes.fetch_daily_summary",
            side_effect=_fake_fetch_factory({yesterday}),
        ),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="x"
        ) as mock_publish,
    ):
        r2 = await client.post("/api/v1/story/publish", headers=api_headers)

    assert r2.json()["status"] == "nothing_to_post"
    assert mock_publish.call_count == 0


@pytest.mark.asyncio
async def test_story_publish_test_mode_posts_without_ledger(client, api_headers, tmp_path):
    """test=trueは特別画像を投稿するが台帳には記録しない。"""
    yesterday = _yesterday_jst()
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(7)),
        patch(
            "app.api.routes.fetch_daily_summary",
            side_effect=_fake_fetch_factory({yesterday}),
        ),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="t-1"
        ) as mock_publish,
        patch("app.api.routes.refresh_access_token", new_callable=AsyncMock, return_value=None),
    ):
        r1 = await client.post("/api/v1/story/publish?test=true", headers=api_headers)
        r2 = await client.post("/api/v1/story/publish", headers=api_headers)

    assert r1.json()["status"] == "test_posted"
    # テスト投稿は台帳に残らないので、通常のcronは昨日分をそのまま投稿できる
    assert r2.json()["status"] == "posted"
    assert mock_publish.call_count == 2
