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
