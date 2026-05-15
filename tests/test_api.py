"""Tests for API endpoints."""

import base64
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.database import MealLog


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_get_day_number(client, api_headers):
    response = await client.get("/api/v1/meal/day-number?date=2026-05-14", headers=api_headers)
    assert response.status_code == 200
    assert response.json() == {"date": "2026-05-14", "day_number": 329}


@pytest.mark.asyncio
async def test_api_info(client):
    response = await client.get("/api")
    assert response.status_code == 200
    data = response.json()
    assert "ChatGPT Diet App API" in data["message"]


@pytest.mark.asyncio
async def test_unauthorized_request(client):
    response = await client.get(
        "/api/v1/meal/history",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_meal_history_empty(client, api_headers):
    response = await client.get("/api/v1/meal/history", headers=api_headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_daily_summary_empty(client, api_headers):
    response = await client.get("/api/v1/meal/daily-summary", headers=api_headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_meal_history_with_data(client, api_headers):
    """Test meal history returns saved records."""
    from tests.conftest import test_session

    async with test_session() as session:
        log = MealLog(
            date=datetime(2024, 3, 15),
            protein=25.0,
            fat=12.0,
            carbs=40.0,
            calories=350.0,
            meal_description="chicken salad",
            ai_comment="Nice protein intake!",
            mode="text_only",
        )
        session.add(log)
        await session.commit()

    response = await client.get("/api/v1/meal/history", headers=api_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["protein"] == 25.0
    assert data[0]["meal_description"] == "chicken salad"
    assert data[0]["date"] == "2024-03-15"
    assert data[0]["day_number"] is None


@pytest.mark.asyncio
async def test_get_meal_history_date_filter(client, api_headers):
    """Test date filtering on meal history."""
    from tests.conftest import test_session

    async with test_session() as session:
        for day, desc in [(10, "early"), (20, "late")]:
            log = MealLog(
                date=datetime(2024, 3, day),
                protein=20.0, fat=10.0, carbs=30.0, calories=300.0,
                meal_description=desc, mode="text_only",
            )
            session.add(log)
        await session.commit()

    response = await client.get(
        "/api/v1/meal/history?start_date=2024-03-15&end_date=2024-03-25",
        headers=api_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["meal_description"] == "late"


@pytest.mark.asyncio
async def test_get_daily_summary_with_data(client, api_headers):
    """Test daily summary aggregation."""
    from tests.conftest import test_session

    async with test_session() as session:
        # Two meals on the same day
        for desc in ["breakfast", "lunch"]:
            log = MealLog(
                date=datetime(2024, 3, 15),
                protein=20.0, fat=10.0, carbs=30.0, calories=300.0,
                meal_description=desc, mode="text_only",
            )
            session.add(log)
        await session.commit()

    response = await client.get("/api/v1/meal/daily-summary?days=30", headers=api_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["total_protein"] == 40.0
    assert data[0]["total_calories"] == 600.0
    assert data[0]["meal_count"] == 2
    assert data[0]["day_number"] is None


@pytest.mark.asyncio
async def test_upload_image_no_records(client, api_headers):
    """Test image upload fails when no records exist for the date."""
    fake_image = base64.b64encode(b"fake-image-data").decode()
    response = await client.post(
        "/api/v1/meal/upload-image",
        headers=api_headers,
        json={"date": "2024-01-01", "image_base64": fake_image},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_image_success(client, api_headers, tmp_path):
    """Test successful custom image upload."""
    from tests.conftest import test_session

    async with test_session() as session:
        log = MealLog(
            date=datetime(2024, 3, 15),
            protein=20.0, fat=10.0, carbs=30.0, calories=300.0,
            meal_description="test", mode="text_only",
        )
        session.add(log)
        await session.commit()

    fake_image = base64.b64encode(b"fake-image-data").decode()

    with patch("app.api.routes.settings") as mock_settings:
        mock_settings.images_dir = tmp_path
        mock_settings.secret_key = "test-secret"

        response = await client.post(
            "/api/v1/meal/upload-image",
            headers=api_headers,
            json={"date": "2024-03-15", "image_base64": fake_image},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True


@pytest.mark.asyncio
async def test_post_meal_with_mock(client, api_headers, tmp_path):
    """Test meal posting endpoint with mocked AI services."""
    from app.models.schemas import PFCData, PostResult, MealPFCResult, MealType

    mock_result = PostResult(
        success=True,
        day_number=329,
        image_base64=base64.b64encode(b"test").decode(),
        caption="Great meal!",
        pfc=PFCData(protein=25.0, fat=12.0, carbs=40.0, calories=350.0, comment="Nice!"),
        meal_details=[
            MealPFCResult(
                meal_type=MealType.LUNCH,
                description="chicken",
                pfc=PFCData(protein=25.0, fat=12.0, carbs=40.0, calories=350.0, comment="Nice!"),
            )
        ],
    )

    with patch("app.api.routes.create_and_post", new_callable=AsyncMock, return_value=mock_result):
        response = await client.post(
            "/api/v1/meal/post?auto_post=false",
            headers=api_headers,
            json={
                "date": "2024-03-15T00:00:00",
                "meals": [{"meal_type": "lunch", "description": "chicken salad"}],
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["day_number"] == 329
    assert data["pfc"]["protein"] == 25.0
    assert len(data["meal_details"]) == 1
    assert data["meal_details"][0]["pfc"]["protein"] == 25.0
