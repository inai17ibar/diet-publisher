"""Instagramストーリー用（1080x1920）の1日サマリ画像を生成する。

データはdiet-mcpの /api/summary/daily のレスポンス(dict)をそのまま受け取る。
ストーリーの上下約250pxはInstagramのUI（アイコン・返信欄）と重なるため、
セーフエリア内にだけ情報を配置する。
"""

import io
import os
from datetime import date
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
HEIGHT = 1920
MARGIN_X = 84
SAFE_TOP = 260
SAFE_BOTTOM = HEIGHT - 260

BG_TOP = (15, 23, 42)  # slate-900
BG_BOTTOM = (30, 41, 59)  # slate-800
TEXT_MAIN = (248, 250, 252)
TEXT_SUB = (148, 163, 184)
TRACK = (51, 65, 85)
ACCENT_OK = (74, 222, 128)  # 目標内: グリーン
ACCENT_OVER = (245, 158, 11)  # 目標超過: アンバー
ACCENT_NEUTRAL = (45, 212, 191)  # 目標未設定: ティール
PFC_COLORS = {
    "protein_g": ("P", (96, 165, 250)),
    "fat_g": ("F", (251, 191, 36)),
    "carbs_g": ("C", (244, 114, 182)),
}
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# PFC目標の逆算パラメータ
PROTEIN_TARGET_G = 135.0  # 体重90kg × 1.5g/kg 程度
FAT_KCAL_RATIO = 0.25  # 脂質は目標カロリーの25%


def _pfc_targets(goal_kcal: float | None) -> dict[str, float] | None:
    """目標カロリーからPFCの目標グラム数を逆算する。

    P: 固定(PROTEIN_TARGET_G)、F: 目標カロリーの25%、C: 残りのカロリー。
    """
    if goal_kcal is None or goal_kcal <= 0:
        return None
    protein = PROTEIN_TARGET_G
    fat = goal_kcal * FAT_KCAL_RATIO / 9
    carbs = max((goal_kcal - protein * 4 - fat * 9) / 4, 0)
    return {"protein_g": protein, "fat_g": fat, "carbs_g": carbs}

_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",  # Docker (fonts-noto-cjk)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",  # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
]


@lru_cache(maxsize=None)
def _font_path() -> str | None:
    override = os.environ.get("STORY_FONT_PATH")
    for path in [override, *_FONT_CANDIDATES]:
        if path and os.path.exists(path):
            return path
    return None


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _font_path()
    if path:
        return ImageFont.truetype(path, size=size)
    return ImageFont.load_default(size=size)


def _gradient_background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / HEIGHT
        color = tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
        draw.line([(0, y), (WIDTH, y)], fill=color)
    return image


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def create_notice_image(lines: list[str]) -> bytes:
    """データが無いときなどに返す案内用の画像（本編と同じデザイントーン）。"""
    image = _gradient_background()
    draw = ImageDraw.Draw(image)
    font = _font(52)
    line_h = 84
    start_y = HEIGHT // 2 - line_h * (len(lines) - 1) // 2
    for i, line in enumerate(lines):
        draw.text((WIDTH // 2, start_y + i * line_h), line, font=font, fill=TEXT_SUB, anchor="mm")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


def create_story_image(summary: dict, day_number: int | None) -> bytes:
    total = float(summary.get("total_calories") or 0)
    goal = summary.get("calorie_goal")
    meals = summary.get("meals") or []
    nutrients = summary.get("nutrients") or {}

    if goal is None:
        accent = ACCENT_NEUTRAL
    elif total <= goal:
        accent = ACCENT_OK
    else:
        accent = ACCENT_OVER

    image = _gradient_background()
    draw = ImageDraw.Draw(image)
    content_width = WIDTH - 2 * MARGIN_X

    # ---- ヘッダー: Day数 + 日付 ----
    y = SAFE_TOP
    day_label = f"DAY {day_number}" if day_number else "DIET RECORD"
    draw.text((MARGIN_X, y), day_label, font=_font(96), fill=accent)
    target_date = date.fromisoformat(summary["date"])
    date_label = f"{target_date.strftime('%Y.%m.%d')} {WEEKDAYS[target_date.weekday()]}"
    draw.text((WIDTH - MARGIN_X, y + 92), date_label, font=_font(40), fill=TEXT_SUB, anchor="rs")
    y += 160

    # ---- 摂取カロリー ----
    calories_text = f"{int(total):,}"
    big_font = _font(190)
    draw.text((MARGIN_X, y), calories_text, font=big_font, fill=TEXT_MAIN)
    unit_x = MARGIN_X + draw.textlength(calories_text, font=big_font) + 24
    draw.text((unit_x, y + 190 - 76), "kcal", font=_font(56), fill=TEXT_SUB)
    y += 264

    # ---- 目標との比較 + 達成バー ----
    if goal is not None:
        remaining = goal - total
        if remaining >= 0:
            goal_label = f"目標 {int(goal):,} kcal ・ 残り {int(remaining):,} kcal"
        else:
            goal_label = f"目標 {int(goal):,} kcal ・ {int(-remaining):,} kcal オーバー"
        draw.text((MARGIN_X, y), goal_label, font=_font(44), fill=TEXT_SUB)
        y += 78
        bar_h = 20
        draw.rounded_rectangle(
            [(MARGIN_X, y), (WIDTH - MARGIN_X, y + bar_h)], radius=bar_h // 2, fill=TRACK
        )
        ratio = min(total / goal, 1.0) if goal > 0 else 0
        if ratio > 0.02:
            draw.rounded_rectangle(
                [(MARGIN_X, y), (MARGIN_X + content_width * ratio, y + bar_h)],
                radius=bar_h // 2,
                fill=accent,
            )
        y += bar_h + 60
    else:
        y += 20

    # ---- PFC ----
    targets = _pfc_targets(goal)
    draw.text((MARGIN_X, y), "PFC", font=_font(40), fill=TEXT_SUB)
    if targets:
        draw.text(
            (WIDTH - MARGIN_X, y + 40), "実績 / 目標", font=_font(36), fill=TEXT_SUB, anchor="rs"
        )
    y += 66
    macro_kcal = {
        "protein_g": (nutrients.get("protein_g") or 0) * 4,
        "fat_g": (nutrients.get("fat_g") or 0) * 9,
        "carbs_g": (nutrients.get("carbs_g") or 0) * 4,
    }
    macro_total = sum(macro_kcal.values())
    bar_x = MARGIN_X + 400
    for key, (letter, color) in PFC_COLORS.items():
        badge_r = 30
        cy = y + badge_r
        draw.ellipse(
            [(MARGIN_X, cy - badge_r), (MARGIN_X + badge_r * 2, cy + badge_r)], fill=color
        )
        draw.text((MARGIN_X + badge_r, cy), letter, font=_font(38), fill=BG_TOP, anchor="mm")
        value = nutrients.get(key)
        value_label = f"{value:g}" if value is not None else "—"
        bar_h = 16
        draw.rounded_rectangle(
            [(bar_x, cy - bar_h // 2), (WIDTH - MARGIN_X, cy + bar_h // 2)],
            radius=bar_h // 2,
            fill=TRACK,
        )
        bar_full = WIDTH - MARGIN_X - bar_x
        if targets:
            # 目標値をバーの全長とし、実績で埋める。超過はアンバーで示す
            target = targets[key]
            over = value is not None and target > 0 and value > target
            grams_label = f"{value_label} / {round(target)} g"
            label_fill = ACCENT_OVER if over else TEXT_MAIN
            draw.text(
                (MARGIN_X + 84, cy), grams_label, font=_font(42), fill=label_fill, anchor="lm"
            )
            if value and target > 0:
                ratio = min(value / target, 1.0)
                fill_w = max(bar_full * ratio, bar_h)
                draw.rounded_rectangle(
                    [(bar_x, cy - bar_h // 2), (bar_x + fill_w, cy + bar_h // 2)],
                    radius=bar_h // 2,
                    fill=ACCENT_OVER if over else color,
                )
        else:
            # 目標カロリー未設定時はカロリー寄与比で表示
            draw.text(
                (MARGIN_X + 84, cy), f"{value_label} g", font=_font(46), fill=TEXT_MAIN, anchor="lm"
            )
            if macro_total > 0 and macro_kcal[key] > 0:
                share = macro_kcal[key] / macro_total
                fill_w = max(bar_full * share, bar_h)
                draw.rounded_rectangle(
                    [(bar_x, cy - bar_h // 2), (bar_x + fill_w, cy + bar_h // 2)],
                    radius=bar_h // 2,
                    fill=color,
                )
        y += 92
    y += 50

    # ---- 食事リスト ----
    draw.text((MARGIN_X, y), "今日の食事", font=_font(40), fill=TEXT_SUB)
    draw.text(
        (WIDTH - MARGIN_X, y + 40), f"{len(meals)}件", font=_font(40), fill=TEXT_SUB, anchor="rs"
    )
    y += 76
    row_h = 78
    max_rows = max((SAFE_BOTTOM - y) // row_h, 1)
    visible = meals if len(meals) <= max_rows else meals[: max_rows - 1]
    desc_x = MARGIN_X + 150
    for meal in visible:
        cy = y + row_h // 2
        draw.text((MARGIN_X, cy), meal.get("time", ""), font=_font(38), fill=TEXT_SUB, anchor="lm")
        calories_label = f"{int(meal.get('calories') or 0):,} kcal"
        cal_font = _font(38)
        cal_w = draw.textlength(calories_label, font=cal_font)
        draw.text((WIDTH - MARGIN_X, cy), calories_label, font=cal_font, fill=TEXT_SUB, anchor="rm")
        desc_font = _font(44)
        desc_max_w = (WIDTH - MARGIN_X - cal_w - 40) - desc_x
        description = _truncate(draw, meal.get("description", ""), desc_font, desc_max_w)
        draw.text((desc_x, cy), description, font=desc_font, fill=TEXT_MAIN, anchor="lm")
        y += row_h
    if len(meals) > len(visible):
        draw.text(
            (MARGIN_X, y + row_h // 2),
            f"ほか {len(meals) - len(visible)} 件",
            font=_font(38),
            fill=TEXT_SUB,
            anchor="lm",
        )

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()
