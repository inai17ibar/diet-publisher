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


CAPTION_TEMPLATE = """以下の情報からInstagram投稿用のキャプションを1つだけ作成してください。
重複する内容は絶対に含めないでください。

食事内容: {description}
P(タンパク質): {protein}g / F(脂質): {fat}g / C(炭水化物): {carbs}g / {calories}kcal

以下の形式で出力してください（---は含めない）：
食事に関する一言（絵文字OK、1行）

P {protein} / F {fat} / C {carbs} / {calories} kcal

ハッシュタグは含めないでください。PFC数値は上記の1行だけにしてください。
"""


async def generate_caption(pfc: PFCData, description: str = "", has_photo: bool = True) -> str:
    """Instagram用キャプションを生成"""
    prompt = CAPTION_TEMPLATE.format(
        description=description or "本日の食事",
        protein=pfc.protein,
        fat=pfc.fat,
        carbs=pfc.carbs,
        calories=pfc.calories,
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
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
