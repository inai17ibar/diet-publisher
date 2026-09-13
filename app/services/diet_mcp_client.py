"""diet-mcp（食事記録の本体サービス）からデータを取得するクライアント。"""

import httpx

from app.config import settings


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
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise DietMcpError(f"diet-mcpに接続できません: {exc}") from exc

    if response.status_code != 200:
        raise DietMcpError(f"diet-mcpからの取得に失敗: HTTP {response.status_code}")
    return response.json()


async def fetch_daily_summary(date_str: str | None = None) -> dict:
    """指定日（省略時はJSTの今日）の食事サマリをdiet-mcpから取得する。"""
    return await _fetch("/api/summary/daily", date_str)


async def fetch_week_summary(date_str: str | None = None) -> dict:
    """指定日を含む週（月曜始まり7日間）のサマリをdiet-mcpから取得する。

    日別内訳・週合計・目標との比較が入っており、週次振り返り画像の元データになる。
    """
    return await _fetch("/api/summary/week", date_str)
