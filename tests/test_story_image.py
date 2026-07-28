"""Tests for the story image generator and endpoint."""

import io
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.services.story_image import create_story_image


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
