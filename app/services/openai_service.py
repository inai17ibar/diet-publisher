import base64
import json
import re

from openai import AsyncOpenAI

from app.config import settings
from app.models.schemas import PFCData

client = AsyncOpenAI(api_key=settings.openai_api_key)


SYSTEM_PROMPT_PFC = """あなたは栄養管理の専門家です。
ユーザーが提供する食事情報からPFC（タンパク質・脂質・炭水化物）とカロリーを推定してください。

必ず以下のJSON形式で回答してください：
{
    "protein": <数値>,
    "fat": <数値>,
    "carbs": <数値>,
    "calories": <数値>,
    "comment": "<短いアドバイスやコメント>"
}

推定のポイント：
- 一般的な1人前の量を基準に計算
- 不明な場合は控えめに見積もる
- commentは栄養バランスの評価、改善提案、励ましを含めて80-120文字程度で具体的に
"""


async def analyze_meal_from_text(description: str) -> PFCData:
    """テキストから食事のPFCを分析"""
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_PFC},
            {
                "role": "user",
                "content": f"以下の食事のPFCとカロリーを推定してください：\n\n{description}",
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=500,
    )

    result = json.loads(response.choices[0].message.content)
    return PFCData(**result)


async def analyze_meal_from_image(image_base64: str, additional_info: str = "") -> PFCData:
    """画像から食事のPFCを分析（Vision API）"""
    user_content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}", "detail": "high"},
        },
        {
            "type": "text",
            "text": f"この食事写真からPFCとカロリーを推定してください。{additional_info}",
        },
    ]

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_PFC},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_tokens=500,
    )

    result = json.loads(response.choices[0].message.content)
    return PFCData(**result)


CAPTION_TEMPLATE_WITH_PHOTO = """以下の情報からInstagram投稿用のキャプションを作成してください。

PFC情報:
- タンパク質: {protein}g
- 脂質: {fat}g
- 炭水化物: {carbs}g
- カロリー: {calories}kcal

AIコメント: {comment}

以下の形式で、改行を含めて出力してください：
---
（食事に関する一言、絵文字OK）

P {protein} / F {fat} / C {carbs} / {calories} kcal

AIコメント：{comment}
---

最後にハッシュタグは含めないでください（別途追加します）。
"""

CAPTION_TEMPLATE_NO_PHOTO = """以下の情報からInstagram投稿用のキャプションを作成してください。
写真が撮れなかった日用の投稿です。

食事内容: {description}

PFC情報:
- タンパク質: {protein}g
- 脂質: {fat}g
- 炭水化物: {carbs}g
- カロリー: {calories}kcal

AIコメント: {comment}

以下の形式で、改行を含めて出力してください：
---
今日は写真を撮れなかったので、AIで記録だけ残しました

{description}

P {protein} / F {fat} / C {carbs} / {calories} kcal

AIコメント：{comment}
---

最後にハッシュタグは含めないでください（別途追加します）。
"""


async def generate_caption(pfc: PFCData, description: str = "", has_photo: bool = True) -> str:
    """Instagram用キャプションを生成"""
    if has_photo:
        prompt = CAPTION_TEMPLATE_WITH_PHOTO.format(
            protein=pfc.protein,
            fat=pfc.fat,
            carbs=pfc.carbs,
            calories=pfc.calories,
            comment=pfc.comment,
        )
    else:
        prompt = CAPTION_TEMPLATE_NO_PHOTO.format(
            description=description,
            protein=pfc.protein,
            fat=pfc.fat,
            carbs=pfc.carbs,
            calories=pfc.calories,
            comment=pfc.comment,
        )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
    )

    caption = response.choices[0].message.content.strip()
    # Remove --- markers if present
    caption = re.sub(r"^---\n?", "", caption)
    caption = re.sub(r"\n?---$", "", caption)

    return caption


IMAGE_PROMPT_TEMPLATE = """A beautiful Instagram-style food photography flat lay composition.
Top-down view of an elegant marble or wooden table surface.
In the center, artistic illustration of healthy meals: {food_description}.
The food is arranged beautifully with garnishes and small decorative elements.
On the side, a stylish nutrition info card showing:
"P {protein}g / F {fat}g / C {carbs}g"
"{calories} kcal"
Soft natural lighting from the side, creating gentle shadows.
Warm, inviting color palette with fresh greens, appetizing food colors.
Professional food styling, clean aesthetic, Instagram-worthy composition.
Minimalist design with plenty of white space.
NO text other than the nutrition numbers. Photorealistic food illustration style."""


async def generate_placeholder_image(pfc: PFCData, description: str = "") -> bytes:
    """写真がない場合の代替画像を生成（DALL-E）"""
    # 食事の説明がなければデフォルトを使用
    food_desc = description if description else "a balanced healthy meal with protein, vegetables, and whole grains"

    prompt = IMAGE_PROMPT_TEMPLATE.format(
        food_description=food_desc,
        protein=int(pfc.protein),
        fat=int(pfc.fat),
        carbs=int(pfc.carbs),
        calories=int(pfc.calories),
    )

    response = await client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1,
        response_format="b64_json",
    )

    image_b64 = response.data[0].b64_json
    return base64.b64decode(image_b64)
