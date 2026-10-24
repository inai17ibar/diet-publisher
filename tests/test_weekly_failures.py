from unittest.mock import AsyncMock

import httpx
import pytest

from app.api import routes
from app.services import diet_mcp_client as diet
from app.services.instagram_story import InstagramStoryError
from tests.test_weekly_review import COMPLETE_WEEK


@pytest.mark.parametrize("stage", ["fetch_week", "build_image", "publish", "record_post"])
async def test_failure_reports_stage_without_leaking_or_reposting(
    client, api_headers, monkeypatch, caplog, tmp_path, stage
):
    monkeypatch.setattr(routes.settings, "instagram_user_id", "test-user")
    monkeypatch.setattr(routes.settings, "instagram_access_token", "test-token")
    monkeypatch.setattr(routes.settings, "images_dir", tmp_path)
    fetch = AsyncMock(return_value=COMPLETE_WEEK)
    build = AsyncMock(return_value=(b"image", routes.score_week(COMPLETE_WEEK), None, {}))
    publish = AsyncMock(return_value="media-id")
    refresh = AsyncMock(return_value=None)
    monkeypatch.setattr(routes, "fetch_week_summary", fetch)
    monkeypatch.setattr(routes, "_build_weekly_story", build)
    monkeypatch.setattr(routes, "publish_story", publish)
    monkeypatch.setattr(routes, "refresh_access_token", refresh)
    error = "secret-token meal-private"
    if stage == "fetch_week":
        fetch.side_effect = diet.DietMcpError(error)
    elif stage == "build_image":
        build.side_effect = ValueError(error)
    elif stage == "publish":
        publish.side_effect = InstagramStoryError(error)
    else:
        monkeypatch.setattr(
            routes.AsyncSession, "commit", AsyncMock(side_effect=RuntimeError(error))
        )

    response = await client.post("/api/v1/story/publish-weekly", headers=api_headers)
    assert response.status_code == (502 if stage in {"fetch_week", "publish"} else 500)
    detail = response.json()["detail"]
    assert detail["stage"] == stage
    assert detail["request_id"]
    assert detail["week_start"]
    assert error not in response.text + caplog.text
    assert f"stage={stage}" in caplog.text
    assert publish.await_count == (1 if stage in {"publish", "record_post"} else 0)
    refresh.assert_not_awaited()


@pytest.mark.parametrize(
    "statuses,expected_calls,success",
    [
        ([502, 503, 200], 3, True),
        ([401], 1, False),
        ([502, 502, 502], 3, False),
    ],
)
async def test_read_only_retries(monkeypatch, statuses, expected_calls, success):
    monkeypatch.setattr(diet.settings, "diet_mcp_api_key", "test")
    responses = iter(statuses)
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(next(responses), json={"daily": []})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        diet.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setattr(diet.asyncio, "sleep", AsyncMock())
    if success:
        assert await diet.fetch_week_summary("2026-10-19") == {"daily": []}
    else:
        with pytest.raises(diet.DietMcpError):
            await diet.fetch_week_summary("2026-10-19")
    assert len(calls) == expected_calls
    assert all(r.method == "GET" for r in calls)


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
async def test_invalid_summary_is_controlled_error(monkeypatch, body):
    monkeypatch.setattr(diet.settings, "diet_mcp_api_key", "test")
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        diet.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)), **kwargs
        ),
    )
    with pytest.raises(diet.DietMcpError):
        await diet.fetch_week_summary("2026-10-19")
