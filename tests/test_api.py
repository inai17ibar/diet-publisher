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
    assert "Diet Publisher API" in data["message"]


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


@pytest.mark.asyncio
async def test_shortcut_double_tap_returns_conflict(client, api_headers):
    """ダブルタップ: 同時2リクエストは1件だけ記録され、もう1件は409になる。"""
    import asyncio

    from app.models.schemas import PFCData

    async def slow_analyze(description):
        await asyncio.sleep(0.3)
        return PFCData(protein=30, fat=20, carbs=50, calories=500, comment="test")

    async def fake_caption(pfc, **kwargs):
        return "caption"

    with (
        patch("app.services.meal_processor.analyze_meal_from_text", side_effect=slow_analyze),
        patch("app.services.meal_processor.generate_caption", side_effect=fake_caption),
    ):
        url = "/api/v1/shortcut/meal?meal_type=lunch&description=サラダチキン"
        r1, r2 = await asyncio.gather(
            client.post(url, headers=api_headers),
            client.post(url, headers=api_headers),
        )

    assert sorted([r1.status_code, r2.status_code]) == [200, 409]

    response = await client.get("/api/v1/meal/history", headers=api_headers)
    data = response.json()
    assert len(data) == 1
    assert data[0]["calories"] == 500.0


@pytest.mark.asyncio
async def test_duplicate_meal_within_window_conflict(client, api_headers):
    """5分以内に同じ説明の記録があれば409になり、OpenAIは呼ばれない。"""
    from tests.conftest import test_session

    async with test_session() as session:
        session.add(
            MealLog(
                date=datetime.now(),
                protein=30.0, fat=20.0, carbs=50.0, calories=500.0,
                meal_description="サラダチキン", mode="text_only",
            )
        )
        await session.commit()

    with patch(
        "app.services.meal_processor.analyze_meal_from_text", new_callable=AsyncMock
    ) as mock_analyze:
        response = await client.post(
            "/api/v1/shortcut/meal?meal_type=lunch&description=サラダチキン",
            headers=api_headers,
        )

    assert response.status_code == 409
    mock_analyze.assert_not_called()


@pytest.mark.asyncio
async def test_delete_meal_log(client, api_headers):
    """食事ログを削除できる。"""
    from tests.conftest import test_session

    async with test_session() as session:
        log = MealLog(
            date=datetime(2024, 3, 15),
            protein=25.0, fat=12.0, carbs=40.0, calories=350.0,
            meal_description="chicken salad", mode="text_only",
        )
        session.add(log)
        await session.commit()
        log_id = log.id

    response = await client.delete(f"/api/v1/meal/log/{log_id}", headers=api_headers)
    assert response.status_code == 200
    assert response.json() == {"success": True, "deleted_id": log_id}

    history = await client.get("/api/v1/meal/history", headers=api_headers)
    assert history.json() == []


@pytest.mark.asyncio
async def test_delete_meal_log_not_found(client, api_headers):
    """存在しないIDの削除は404。"""
    response = await client.delete("/api/v1/meal/log/9999", headers=api_headers)
    assert response.status_code == 404
