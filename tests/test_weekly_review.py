"""週次振り返り（採点・画像・自動投稿）のテスト。"""

import io
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.api.routes import JST
from app.services.weekly_image import create_weekly_image
from app.services.weekly_review import MIN_RECORDED_DAYS, score_week

# 2026-09-07(月) 〜 2026-09-13(日)
WEEK_START = "2026-09-07"
WEEK_END = "2026-09-13"
GOAL = 1800.0

FULL_DAY_MEALS = [
    {"time": "08:00", "tags": [], "description": "バナナとヨーグルト", "calories": 250},
    {"time": "12:30", "tags": [], "description": "サラダチキン", "calories": 600},
    {"time": "19:00", "tags": [], "description": "豚しゃぶ定食", "calories": 900},
]


def _day(index: int, calories: float, protein: float | None, meals: list | None = None) -> dict:
    date_str = (datetime.fromisoformat(WEEK_START) + timedelta(days=index)).date().isoformat()
    return {
        "date": date_str,
        "total_calories": calories,
        "nutrients": {"protein_g": protein, "fat_g": 50, "carbs_g": 180},
        "calorie_goal": GOAL,
        "calories_remaining": GOAL - calories,
        "meals": meals if meals is not None else (FULL_DAY_MEALS if calories else []),
    }


def _week(days: list[dict], start: str = WEEK_START, end: str = WEEK_END) -> dict:
    total = sum(d["total_calories"] for d in days)
    return {
        "start_date": start,
        "end_date": end,
        "daily": days,
        "week_total_calories": total,
        "week_nutrients": {"protein_g": 900, "fat_g": 350, "carbs_g": 1200},
        "week_calorie_goal": GOAL * 7,
        "week_calories_remaining": GOAL * 7 - total,
    }


SAMPLE_WEEK = _week(
    [
        _day(0, 1750, 140),
        _day(1, 1920, 120),
        _day(2, 1680, 150),
        _day(3, 2250, 90),
        _day(4, 1810, 138),
        _day(5, 0, None),
        _day(6, 1600, 145),
    ]
)


# ---- 採点 ----


def test_perfect_week_scores_100():
    week = _week([_day(i, 1700, 140) for i in range(7)])
    score = score_week(week)
    assert score.total == 100
    assert score.grade == "S"
    assert score.recorded_days == 7
    assert score.complete_days == 7


def test_sample_week_score_and_diff():
    score = score_week(SAMPLE_WEEK)
    assert score.recorded_days == 6
    assert score.complete_days == 6
    assert score.within_goal_days == 3  # 1750 / 1680 / 1600
    assert round(score.average_calories) == 1835
    assert round(score.average_diff) == 35  # 目標より1日あたり35kcalオーバー
    assert score.week_goal_calories == GOAL * 7
    assert 0 < score.total < 100
    assert score.grade in {"S", "A", "B", "C", "D"}


def test_incomplete_days_cost_points():
    """3食そろっていない日は記録スコアが下がる。"""
    partial = [_day(i, 1700, 140, meals=FULL_DAY_MEALS[:2]) for i in range(7)]
    record_item = next(i for i in score_week(_week(partial)).items if i.key == "record")
    assert record_item.points == 0
    assert record_item.detail == "3食そろった日 0/7日"


def test_empty_week_scores_zero():
    score = score_week(_week([_day(i, 0, None) for i in range(7)]))
    assert score.total == 0
    assert score.grade == "D"
    assert score.average_calories is None
    assert score.average_diff is None


def test_week_without_calorie_goal_is_rescaled_to_100():
    days = [
        {**_day(i, 1700, 140), "calorie_goal": None, "calories_remaining": None}
        for i in range(7)
    ]
    week = {**_week(days), "week_calorie_goal": None}
    score = score_week(week)
    assert score.calorie_goal is None
    assert [i.key for i in score.items] == ["record", "protein"]
    assert score.total == 100  # 満点項目が2つでも100点満点に換算する


# ---- 画像 ----


def test_weekly_image_dimensions():
    data = create_weekly_image(SAMPLE_WEEK, score_week(SAMPLE_WEEK), comment="来週は夕食を絞ろう。")
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (1080, 1920)
        assert img.format == "JPEG"


def test_weekly_image_without_comment_or_goal():
    days = [
        {**_day(i, 1700 if i < 3 else 0, 140), "calorie_goal": None} for i in range(7)
    ]
    week = {**_week(days), "week_calorie_goal": None}
    data = create_weekly_image(week, score_week(week))
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (1080, 1920)


def test_weekly_image_with_emoji_comment():
    """絵文字は描画できないので除去される（豆腐にならない）。"""
    data = create_weekly_image(SAMPLE_WEEK, score_week(SAMPLE_WEEK), comment="いい流れ🔥続けよう💪")
    assert len(data) > 0


# ---- エンドポイント ----


@pytest.fixture(autouse=True)
def _mock_weekly_comment():
    with patch(
        "app.api.routes.generate_weekly_review",
        new_callable=AsyncMock,
        return_value="木曜の2250kcalが唯一の穴。来週は金土の夕食だけ600kcal以内に決めよう。",
    ) as mock:
        yield mock


def _publish_mocks(tmp_path, user_id="12345", token="long-lived-token"):
    mock_settings = MagicMock()
    mock_settings.secret_key = "test-secret"
    mock_settings.images_dir = tmp_path
    mock_settings.public_base_url = "http://testserver"
    mock_settings.instagram_user_id = user_id
    mock_settings.instagram_access_token = token
    return mock_settings


def _fixed_now(date_str: str, hour: int):
    fixed = datetime.fromisoformat(date_str).replace(hour=hour, tzinfo=JST)
    return lambda: fixed


def _week_fetch_factory(weeks: dict):
    """週の月曜日をキーに週次サマリを返す fetch_week_summary のモック。"""

    async def fake(date_str=None):
        if date_str in weeks:
            return weeks[date_str]
        start = datetime.fromisoformat(date_str).date()
        return _week(
            [_day(i, 0, None) for i in range(7)],
            start=start.isoformat(),
            end=(start + timedelta(days=6)).isoformat(),
        )

    return fake


@pytest.mark.asyncio
async def test_weekly_image_endpoint(client, api_headers):
    with patch(
        "app.api.routes.fetch_week_summary",
        side_effect=_week_fetch_factory({WEEK_START: SAMPLE_WEEK}),
    ):
        response = await client.get(
            "/api/v1/story/weekly-image?date=2026-09-10", headers=api_headers
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-week-start"] == WEEK_START
    assert response.headers["x-week-end"] == WEEK_END
    assert int(response.headers["x-week-score"]) > 0
    with Image.open(io.BytesIO(response.content)) as img:
        assert img.size == (1080, 1920)


@pytest.mark.asyncio
async def test_weekly_image_endpoint_without_records(client, api_headers):
    with patch("app.api.routes.fetch_week_summary", side_effect=_week_fetch_factory({})):
        response = await client.get(
            "/api/v1/story/weekly-image?date=2026-09-10", headers=api_headers
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_weekly_image_endpoint_requires_api_key(client):
    response = await client.get("/api/v1/story/weekly-image", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_publish_weekly_on_sunday_night_and_is_idempotent(
    client, api_headers, tmp_path
):
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(WEEK_END, 22)),
        patch(
            "app.api.routes.fetch_week_summary",
            side_effect=_week_fetch_factory({WEEK_START: SAMPLE_WEEK}),
        ),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="w-1"
        ) as mock_publish,
        patch("app.api.routes.refresh_access_token", new_callable=AsyncMock, return_value=None),
    ):
        first = await client.post("/api/v1/story/publish-weekly", headers=api_headers)
        second = await client.post("/api/v1/story/publish-weekly", headers=api_headers)

    body = first.json()
    assert body["status"] == "posted"
    assert body["week_start"] == WEEK_START
    assert body["media_id"] == "w-1"
    assert body["score"] > 0
    assert body["comment"]

    saved = list(tmp_path.glob("weekly_*.jpg"))
    assert len(saved) == 1
    assert saved[0].name in mock_publish.call_args.args[2]

    assert second.json()["status"] == "nothing_to_post"
    assert mock_publish.call_count == 1


@pytest.mark.asyncio
async def test_publish_weekly_does_not_post_before_sunday_night(
    client, api_headers, tmp_path
):
    """週の途中（土曜）に今週分をフライングで投稿しない。"""
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now("2026-09-12", 22)),
        patch(
            "app.api.routes.fetch_week_summary",
            side_effect=_week_fetch_factory({WEEK_START: SAMPLE_WEEK}),
        ),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="x"
        ) as mock_publish,
    ):
        response = await client.post("/api/v1/story/publish-weekly", headers=api_headers)

    assert response.json()["status"] == "nothing_to_post"
    assert mock_publish.call_count == 0


@pytest.mark.asyncio
async def test_publish_weekly_catches_up_last_week_on_monday(client, api_headers, tmp_path):
    """日曜夜の投稿を取りこぼしても、月曜のcronで先週分が投稿される。"""
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now("2026-09-14", 7)),
        patch(
            "app.api.routes.fetch_week_summary",
            side_effect=_week_fetch_factory({WEEK_START: SAMPLE_WEEK}),
        ),
        patch("app.api.routes.publish_story", new_callable=AsyncMock, return_value="w-2"),
        patch("app.api.routes.refresh_access_token", new_callable=AsyncMock, return_value=None),
    ):
        response = await client.post("/api/v1/story/publish-weekly", headers=api_headers)

    body = response.json()
    assert body["status"] == "posted"
    assert body["week_start"] == WEEK_START


@pytest.mark.asyncio
async def test_publish_weekly_skips_week_with_too_few_records(client, api_headers, tmp_path):
    sparse = _week(
        [_day(0, 1700, 140), _day(1, 1650, 130)] + [_day(i, 0, None) for i in range(2, 7)]
    )
    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(WEEK_END, 22)),
        patch(
            "app.api.routes.fetch_week_summary",
            side_effect=_week_fetch_factory({WEEK_START: sparse}),
        ),
        patch(
            "app.api.routes.publish_story", new_callable=AsyncMock, return_value="x"
        ) as mock_publish,
    ):
        response = await client.post("/api/v1/story/publish-weekly", headers=api_headers)

    body = response.json()
    assert body["status"] == "too_few_records"
    assert body["skipped"][0]["recorded_days"] == 2 < MIN_RECORDED_DAYS
    assert mock_publish.call_count == 0


@pytest.mark.asyncio
async def test_publish_weekly_not_configured_is_not_an_error(client, api_headers, tmp_path):
    """cronが失敗扱いにならないよう、未設定でも200で返す。"""
    with patch("app.api.routes.settings", _publish_mocks(tmp_path, user_id="", token="")):
        response = await client.post("/api/v1/story/publish-weekly", headers=api_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"


@pytest.mark.asyncio
async def test_publish_weekly_diet_mcp_error(client, api_headers, tmp_path):
    from app.services.diet_mcp_client import DietMcpError

    with (
        patch("app.api.routes.settings", _publish_mocks(tmp_path)),
        patch("app.api.routes._now_jst", _fixed_now(WEEK_END, 22)),
        patch(
            "app.api.routes.fetch_week_summary",
            new_callable=AsyncMock,
            side_effect=DietMcpError("接続失敗"),
        ),
    ):
        response = await client.post("/api/v1/story/publish-weekly", headers=api_headers)

    assert response.status_code == 502
