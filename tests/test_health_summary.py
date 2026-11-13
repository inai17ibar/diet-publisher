from unittest.mock import AsyncMock

import pytest

from app.services import diet_mcp_client as diet


@pytest.mark.asyncio
async def test_private_health_summary_uses_separate_endpoint(monkeypatch):
    response = {'weight_kg': {'average': 95, 'recorded_days': 3}}
    fetch = AsyncMock(return_value=response)
    monkeypatch.setattr(diet, '_fetch', fetch)
    assert await diet.fetch_health_week_summary('2026-11-13') == response
    fetch.assert_awaited_once_with('/api/health/week', '2026-11-13')
