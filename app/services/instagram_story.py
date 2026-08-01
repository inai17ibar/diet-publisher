"""Instagram公式Graph API（Instagram API with Instagram Login）でストーリーを投稿する。

非公式ライブラリ(instagrapi)はアカウント制限リスクがあるため使わない。
プロアカウント（クリエイター/ビジネス）と長期アクセストークンが前提。
トークンは60日で失効するが、投稿成功のたびにrefresh_access_tokenで
更新してDBに保存するため、毎日投稿している限り失効しない。
"""

import asyncio

import httpx

GRAPH_BASE = "https://graph.instagram.com/v23.0"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"


class InstagramStoryError(Exception):
    """ストーリー投稿に失敗した"""


async def publish_story(user_id: str, access_token: str, image_url: str) -> str:
    """画像URLをストーリーとして投稿し、メディアIDを返す。

    Graph APIの手順: コンテナ作成 → media_publish の2段階。
    コンテナの処理完了前にpublishすると失敗するため数回リトライする。
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        creation = await client.post(
            f"{GRAPH_BASE}/{user_id}/media",
            data={
                "media_type": "STORIES",
                "image_url": image_url,
                "access_token": access_token,
            },
        )
        if creation.status_code != 200:
            raise InstagramStoryError(f"コンテナ作成に失敗: {creation.text}")
        creation_id = creation.json().get("id")
        if not creation_id:
            raise InstagramStoryError(f"コンテナIDが取得できません: {creation.text}")

        last_error = ""
        for _ in range(5):
            publish = await client.post(
                f"{GRAPH_BASE}/{user_id}/media_publish",
                data={"creation_id": creation_id, "access_token": access_token},
            )
            if publish.status_code == 200 and publish.json().get("id"):
                return publish.json()["id"]
            last_error = publish.text
            await asyncio.sleep(3)

    raise InstagramStoryError(f"media_publishに失敗: {last_error}")


async def refresh_access_token(access_token: str) -> str | None:
    """長期トークンを更新して新しいトークンを返す。失敗したらNone（致命的ではない）。

    発行から24時間未満のトークンは更新できない仕様のため、失敗は握りつぶす。
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                REFRESH_URL,
                params={"grant_type": "ig_refresh_token", "access_token": access_token},
            )
        except httpx.HTTPError:
            return None
    if response.status_code != 200:
        return None
    return response.json().get("access_token")
