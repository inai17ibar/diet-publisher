"""Tests for the story image generator and endpoint."""

import io
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
