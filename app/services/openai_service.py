import base64
import json
import re

from openai import AsyncOpenAI

from app.config import settings
from app.models.schemas import PFCData

def _get_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY が未設定です")
    return AsyncOpenAI(api_key=settings.openai_api_key)


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
    response = await _get_client().chat.completions.create(
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

    response = await _get_client().chat.completions.create(
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


CAPTION_TEMPLATE = """以下の情報からダイエット記録用の投稿文を1つだけ作成してください。
重複する内容は絶対に含めないでください。

記録日: {record_date}
継続日数: {day_label}
食事内容: {description}
P(タンパク質): {protein}g / F(脂質): {fat}g / C(炭水化物): {carbs}g / {calories}kcal

以下の形式で出力してください（---は含めない）：
食事に関する一言（絵文字OK、1行）

{day_label}
P {protein} / F {fat} / C {carbs} / {calories} kcal

ハッシュタグは含めないでください。PFC数値は上記の1行だけにしてください。
"""


async def generate_caption(
    pfc: PFCData,
    description: str = "",
    has_photo: bool = True,
    day_number: int | None = None,
    record_date: str = "",
) -> str:
    """共有用の投稿文を生成"""
    prompt = CAPTION_TEMPLATE.format(
        record_date=record_date,
        day_label=f"Day {day_number}" if day_number else "Diet record",
        description=description or "本日の食事",
        protein=pfc.protein,
        fat=pfc.fat,
        carbs=pfc.carbs,
        calories=pfc.calories,
    )

    response = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
    )

    caption = response.choices[0].message.content.strip()
    # Remove --- markers if present
    caption = re.sub(r"^---\n?", "", caption)
    caption = re.sub(r"\n?---$", "", caption)

    return caption
