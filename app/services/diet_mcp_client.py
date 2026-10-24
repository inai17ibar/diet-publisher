"""diet-mcp（食事記録の本体サービス）からデータを取得するクライアント。"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class DietMcpError(Exception):
    """diet-mcpからのデータ取得に失敗した"""


async def _fetch(path: str, date_str: str | None) -> dict:
    """diet-mcpの読み取り専用APIを叩く。何度呼んでもdiet-mcp側の状態は変わらない。"""
    if not settings.diet_mcp_api_key:
        raise DietMcpError("DIET_MCP_API_KEYが設定されていません")

    url = f"{settings.diet_mcp_url.rstrip('/')}{path}"
    params = {"date": date_str} if date_str else {}
    headers = {"Authorization": f"Bearer {settings.diet_mcp_api_key}"}

    # Fly.ioはアイドル時に停止しているためコールドスタートを見込んで長めのタイムアウト
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(3):
            try:
                response = await client.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt < 2:
                    logger.warning(
                        "diet_mcp_retry path=%s attempt=%s error_type=%s",
                        path,
                        attempt + 1,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(2**attempt)
                    continue
                raise DietMcpError(f"diet-mcp transport failure: {type(exc).__name__}") from exc

            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                logger.warning(
                    "diet_mcp_retry path=%s attempt=%s upstream_status=%s",
                    path,
                    attempt + 1,
                    response.status_code,
                )
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code != 200:
                logger.error(
                    "diet_mcp_failed path=%s upstream_status=%s", path, response.status_code
                )
                raise DietMcpError(f"diet-mcpからの取得に失敗: HTTP {response.status_code}")
            try:
                data = response.json()
            except ValueError as exc:
                raise DietMcpError("diet-mcp returned invalid JSON") from exc
            if not isinstance(data, dict):
                raise DietMcpError("diet-mcp returned a non-object summary")
            return data


async def fetch_daily_summary(date_str: str | None = None) -> dict:
    """指定日（省略時はJSTの今日）の食事サマリをdiet-mcpから取得する。"""
    return await _fetch("/api/summary/daily", date_str)


async def fetch_week_summary(date_str: str | None = None) -> dict:
    """指定日を含む週（月曜始まり7日間）のサマリをdiet-mcpから取得する。

    日別内訳・週合計・目標との比較が入っており、週次振り返り画像の元データになる。
    """
    return await _fetch("/api/summary/week", date_str)
