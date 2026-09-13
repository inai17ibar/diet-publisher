import base64
import json
import re

from openai import AsyncOpenAI

from app.config import settings
from app.models.schemas import PFCData
from app.services.meal_slots import missing_label, missing_meal_slots
from app.services.weekly_review import WeekScore

def _get_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY が未設定です")
    return AsyncOpenAI(api_key=settings.openai_api_key)


WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]

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


ADVICE_SYSTEM_PROMPT = """あなたはダイエット記録アプリの専属AIコーチです。
1日の食事記録を見て、ストーリー画像に載せる「今日のひとこと」を1つ作ります。

ルール:
- 日本語で1文、最大42文字。改行しない
- 絵文字・特殊記号は使わない（画像のフォントで表示できず文字化けするため）
- 今日の実際の食事内容や数値（品名・kcal・PFC）に必ず具体的に触れる
- ありきたりな一般論（「バランスよく食べましょう」等）は禁止
- 口調は日替わりで変える: 褒める / 軽くツッコむ / 豆知識 / 明日への提案 など
- 「過去のひとこと」と似た表現・切り口は避けて、毎日違う角度で書く
- ひとことの本文だけを出力する（カギ括弧や前置きは不要）
"""


async def generate_story_advice(
    summary: dict,
    day_number: int | None,
    previous_advices: list[str] | None = None,
) -> str:
    """ストーリー画像に載せるAIコーチの一言を生成する。"""
    meals_text = "\n".join(
        f"- {m.get('time', '')} {m.get('description', '')} ({int(m.get('calories') or 0)}kcal)"
        for m in summary.get("meals", [])
    )
    nutrients = summary.get("nutrients") or {}
    goal = summary.get("calorie_goal")
    lines = [
        f"Day {day_number}" if day_number else "",
        f"合計 {int(summary.get('total_calories') or 0)}kcal"
        + (f"（目標 {int(goal)}kcal）" if goal else ""),
        f"P {nutrients.get('protein_g')}g / F {nutrients.get('fat_g')}g"
        f" / C {nutrients.get('carbs_g')}g",
        "今日の食事:",
        meals_text,
    ]
    if previous_advices:
        lines.append("\n過去のひとこと（これらと被らないこと）:")
        lines.extend(f"- {a}" for a in previous_advices)

    response = await _get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": ADVICE_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(filter(None, lines))},
        ],
        max_tokens=100,
        temperature=1.1,
    )
    advice = response.choices[0].message.content.strip()
    return advice.strip("「」\"'").splitlines()[0][:60]


WEEKLY_REVIEW_SYSTEM_PROMPT = """あなたはダイエット記録アプリの専属AIコーチです。
1週間の記録を見て、Instagramに載せる週次振り返り画像の「来週の改善ポイント」を書きます。

ルール:
- 日本語で2文。合計70文字以内。改行しない
- 絵文字・特殊記号は使わない（画像のフォントで表示できず文字化けするため）
- 1文目はその週で一番効いた問題（または良かった点）、2文目は来週すぐ実行できる具体的な改善策
- 曜日の傾向・数値・記録が抜けた日など、その週の実データに必ず触れる
- ありきたりな一般論（「バランスよく食べましょう」等）は禁止
- 「過去の改善ポイント」と同じ切り口の繰り返しは避ける
- 本文だけを出力する（カギ括弧や前置きは不要）
"""


async def generate_weekly_review(
    week: dict,
    score: WeekScore,
    previous_comments: list[str] | None = None,
) -> str:
    """週次振り返り画像に載せる「来週の改善ポイント」を生成する。

    点数や差分はweekly_review側で決定的に計算済みなので、AIには
    その結果を渡して講評だけを書かせる（数字をAIに作らせない）。
    """
    day_lines = []
    for i, day in enumerate(week.get("daily") or []):
        label = WEEKDAY_LABELS[i] if i < len(WEEKDAY_LABELS) else day.get("date", "")
        if not day.get("meals"):
            day_lines.append(f"- {label} 記録なし")
            continue
        nutrients = day.get("nutrients") or {}
        missing = missing_meal_slots(day["meals"])
        slot_note = f" / {missing_label(missing)}の記録なし" if missing else " / 3食記録"
        day_lines.append(
            f"- {label} {int(day.get('total_calories') or 0)}kcal"
            f" (P{nutrients.get('protein_g')}g){slot_note}"
        )

    lines = [
        f"期間: {week.get('start_date')} 〜 {week.get('end_date')}",
        f"今週のスコア: {score.total}点 ({score.grade})",
        *[f"- {item.label}: {item.detail}" for item in score.items],
    ]
    if score.average_calories is not None:
        goal_note = (
            f"（目標 {int(score.calorie_goal)}kcal / 差 {int(score.average_diff):+d}kcal）"
            if score.average_diff is not None
            else ""
        )
        lines.append(f"1日平均: {int(score.average_calories)}kcal{goal_note}")
    lines.append("日別:")
    lines.extend(day_lines)
    if previous_comments:
        lines.append("\n過去の改善ポイント（同じ切り口を繰り返さないこと）:")
        lines.extend(f"- {c}" for c in previous_comments)

    response = await _get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": WEEKLY_REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ],
        max_tokens=200,
        temperature=1.0,
    )
    comment = response.choices[0].message.content.strip()
    # 画像のカードは3行（約72文字）まで。それを超える分は描画時に省略される
    return comment.strip("「」\"'").replace("\n", " ")[:72]
