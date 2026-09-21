"""Instagramストーリー用（1080x1920）の週次振り返り画像を生成する。

データはdiet-mcpの /api/summary/week のレスポンス(dict)と、
weekly_review.score_week() の採点結果を受け取る。
配色・フォント・セーフエリアは日次のストーリー画像に合わせるため、
story_image の描画プリミティブをそのまま使う（同じ見た目のシリーズにする）。
"""

import io
from datetime import date

from PIL import ImageDraw

from app.services.story_image import (
    ACCENT_NEUTRAL,
    ACCENT_OK,
    ACCENT_OVER,
    BG_TOP,
    MARGIN_X,
    SAFE_BOTTOM,
    SAFE_TOP,
    TEXT_MAIN,
    TEXT_SUB,
    TRACK,
    WEEKDAYS,
    WIDTH,
    _clean_text,
    _font,
    _gradient_background,
    _wrap_text,
)
from app.services.weekly_review import WeekScore

CARD_BG = (42, 56, 78)
CHART_HEIGHT = 250
# 棒の上に数値ラベルを置くぶん、棒自体はグラフ枠より少し低くする
CHART_LABEL_SPACE = 34
BAR_WIDTH = 100


def _accent_for(score: WeekScore) -> tuple[int, int, int]:
    """点数帯で基調色を変える（good=グリーン / まずまず=ティール / 要改善=アンバー）。"""
    if score.total >= 80:
        return ACCENT_OK
    if score.total >= 60:
        return ACCENT_NEUTRAL
    return ACCENT_OVER


def _date_range_label(week: dict) -> str:
    start = date.fromisoformat(week["start_date"])
    end = date.fromisoformat(week["end_date"])
    return f"{start.strftime('%Y.%m.%d')} - {end.strftime('%m.%d')}"


def _draw_calorie_chart(
    draw: ImageDraw.ImageDraw, days: list[dict], goal: float | None, top: int, accent
) -> int:
    """7日分のカロリー棒グラフを描き、描画後のyを返す。"""
    content_width = WIDTH - 2 * MARGIN_X
    slot = content_width / 7
    baseline = top + CHART_HEIGHT
    bar_area = CHART_HEIGHT - CHART_LABEL_SPACE
    values = [float(d.get("total_calories") or 0) for d in days]
    # 目標線がグラフに収まるように、目標の1.15倍も上限の候補に入れる
    ceiling = max([*values, (goal or 0) * 1.15, 1.0])

    if goal:
        # 目標ライン。数値は見出し行に出しているのでここにラベルは置かない
        goal_y = baseline - bar_area * (goal / ceiling)
        for x in range(MARGIN_X, WIDTH - MARGIN_X, 24):
            draw.line([(x, goal_y), (x + 12, goal_y)], fill=TEXT_SUB, width=3)

    for i, day in enumerate(days):
        value = values[i]
        center_x = MARGIN_X + slot * (i + 0.5)
        left = center_x - BAR_WIDTH / 2
        right = center_x + BAR_WIDTH / 2
        if value <= 0:
            # 記録が無い日は薄いプレースホルダーだけ置く
            draw.rounded_rectangle(
                [(left, baseline - 8), (right, baseline)], radius=4, fill=TRACK
            )
        else:
            height = max(bar_area * (value / ceiling), 12)
            color = ACCENT_OVER if (goal and value > goal) else accent
            draw.rounded_rectangle(
                [(left, baseline - height), (right, baseline)], radius=12, fill=color
            )
            # 数値は棒の中に書く。棒の上に置くと目標の点線と重なって読めなくなる
            if height >= 52:
                draw.text(
                    (center_x, baseline - height + 10),
                    f"{int(value):,}",
                    font=_font(26),
                    fill=BG_TOP,
                    anchor="ma",
                )
            else:
                draw.text(
                    (center_x, baseline - height - 8),
                    f"{int(value):,}",
                    font=_font(26),
                    fill=TEXT_SUB,
                    anchor="ms",
                )
        draw.text(
            (center_x, baseline + 14), WEEKDAYS[i], font=_font(30), fill=TEXT_SUB, anchor="ma"
        )

    draw.line([(MARGIN_X, baseline), (WIDTH - MARGIN_X, baseline)], fill=TRACK, width=2)
    return baseline + 70


def _draw_score_breakdown(
    draw: ImageDraw.ImageDraw, score: WeekScore, top: int, accent
) -> int:
    """スコアの内訳を細いバーで並べる。

    カロリーは加点にも減点にもなるので、中央を0点としてプラスは右（グリーン）、
    マイナスは左（アンバー）へ伸ばす。加点のみの項目は左端から伸ばす。
    """
    y = top
    row_h = 70
    bar_x = MARGIN_X + 230
    bar_right = MARGIN_X + 520
    bar_h = 14
    for item in score.items:
        cy = y + row_h // 2
        draw.text((MARGIN_X, cy), item.label, font=_font(38), fill=TEXT_MAIN, anchor="lm")
        draw.rounded_rectangle(
            [(bar_x, cy - bar_h // 2), (bar_right, cy + bar_h // 2)], radius=bar_h // 2, fill=TRACK
        )
        if item.signed:
            center = (bar_x + bar_right) / 2
            half = (bar_right - bar_x) / 2
            draw.line([(center, cy - 16), (center, cy + 16)], fill=TEXT_SUB, width=2)
            if item.ratio:
                end = center + half * max(-1.0, min(1.0, item.ratio))
                left, right = sorted((center, end))
                draw.rounded_rectangle(
                    [(left, cy - bar_h // 2), (max(right, left + bar_h), cy + bar_h // 2)],
                    radius=bar_h // 2,
                    fill=ACCENT_OK if item.points > 0 else ACCENT_OVER,
                )
        elif item.ratio > 0:
            fill_w = max((bar_right - bar_x) * item.ratio, bar_h)
            draw.rounded_rectangle(
                [(bar_x, cy - bar_h // 2), (bar_x + fill_w, cy + bar_h // 2)],
                radius=bar_h // 2,
                fill=accent,
            )
        draw.text(
            (WIDTH - MARGIN_X, cy), item.detail, font=_font(30), fill=TEXT_SUB, anchor="rm"
        )
        y += row_h
    return y


def create_weekly_image(week: dict, score: WeekScore, comment: str | None = None) -> bytes:
    """週次振り返りのストーリー画像（1080x1920 JPEG）を作る。"""
    accent = _accent_for(score)
    days = week.get("daily") or []
    image = _gradient_background()
    draw = ImageDraw.Draw(image)
    content_width = WIDTH - 2 * MARGIN_X

    # ---- ヘッダー ----
    y = SAFE_TOP
    draw.text((MARGIN_X, y), "WEEKLY REVIEW", font=_font(72), fill=accent)
    y += 92
    draw.text((MARGIN_X, y), _date_range_label(week), font=_font(34), fill=TEXT_SUB)
    y += 62

    # ---- 点数 + グレード ----
    # 行送りを固定pxにすると、フォント（ローカルのヒラギノ / 本番のNoto CJK）で
    # 字面の高さが違うぶん次の行と重なる。数字の実寸を測って配置する
    score_text = str(score.total)
    score_font = _font(150)
    ink = draw.textbbox((0, 0), score_text, font=score_font)
    score_h = ink[3] - ink[1]
    draw.text((MARGIN_X, y - ink[1]), score_text, font=score_font, fill=TEXT_MAIN)
    unit_x = MARGIN_X + (ink[2] - ink[0]) + 20
    draw.text((unit_x, y + score_h), "/ 100", font=_font(48), fill=TEXT_SUB, anchor="ls")
    badge_r = 66
    badge_cx = WIDTH - MARGIN_X - badge_r
    badge_cy = y + score_h // 2
    draw.ellipse(
        [(badge_cx - badge_r, badge_cy - badge_r), (badge_cx + badge_r, badge_cy + badge_r)],
        fill=accent,
    )
    draw.text((badge_cx, badge_cy), score.grade, font=_font(80), fill=BG_TOP, anchor="mm")
    y += score_h + 50

    # ---- 目標との差分 ----
    if score.average_calories is not None:
        draw.text((MARGIN_X, y), "1日平均", font=_font(32), fill=TEXT_SUB)
        y += 46
        avg_text = f"{int(score.average_calories):,} kcal"
        draw.text((MARGIN_X, y), avg_text, font=_font(60), fill=TEXT_MAIN)
        if score.average_diff is not None:
            sign = "+" if score.average_diff >= 0 else "-"
            diff_color = ACCENT_OVER if score.average_diff > 0 else ACCENT_OK
            draw.text(
                (WIDTH - MARGIN_X, y + 60),
                f"目標比 {sign}{abs(int(score.average_diff)):,} kcal/日",
                font=_font(40),
                fill=diff_color,
                anchor="rs",
            )
        y += 78
    else:
        draw.text((MARGIN_X, y), "記録なし", font=_font(60), fill=TEXT_SUB)
        y += 78

    week_line = f"週合計 {int(score.week_total_calories):,} kcal"
    if score.week_goal_calories:
        week_diff = score.week_total_calories - score.week_goal_calories
        sign = "+" if week_diff >= 0 else "-"
        week_line += (
            f"（週の目標 {int(score.week_goal_calories):,}"
            f" / {sign}{abs(int(week_diff)):,}）"
        )
    draw.text((MARGIN_X, y), week_line, font=_font(32), fill=TEXT_SUB)
    y += 66

    # ---- カロリー推移グラフ ----
    draw.text((MARGIN_X, y), "カロリー推移", font=_font(34), fill=TEXT_SUB)
    chart_note = f"記録 {score.recorded_days}/7日"
    if score.calorie_goal:
        chart_note = f"点線 = 目標 {int(score.calorie_goal):,} kcal ・ " + chart_note
    draw.text((WIDTH - MARGIN_X, y + 30), chart_note, font=_font(30), fill=TEXT_SUB, anchor="rs")
    y += 66
    y = _draw_calorie_chart(draw, days, score.calorie_goal, y, accent)

    # ---- スコア内訳 ----
    draw.text((MARGIN_X, y), "スコア内訳", font=_font(34), fill=TEXT_SUB)
    y += 58
    y = _draw_score_breakdown(draw, score, y, accent)
    y += 30

    # ---- 改善ポイント（AIコーチ）----
    comment = _clean_text(comment)
    inner_pad = 32
    available_lines = int((SAFE_BOTTOM - y - 80) // 46)
    if comment and available_lines >= 1:
        card_font = _font(34)
        lines = _wrap_text(
            draw,
            comment,
            card_font,
            content_width - inner_pad * 2,
            max_lines=min(3, available_lines),
        )
        card_h = 20 + 40 + len(lines) * 46 + 20
        draw.rounded_rectangle(
            [(MARGIN_X, y), (WIDTH - MARGIN_X, y + card_h)], radius=24, fill=CARD_BG
        )
        draw.text((MARGIN_X + inner_pad, y + 18), "来週の改善ポイント", font=_font(30), fill=accent)
        ty = y + 20 + 40
        for line in lines:
            draw.text((MARGIN_X + inner_pad, ty), line, font=card_font, fill=TEXT_MAIN)
            ty += 46

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()
