"""1週間の記録を採点して、振り返り画像に載せる数字を組み立てる。

点数をAIに付けさせると同じ週でも呼ぶたびにブレるので、点数と目標差分は
実データから決定的に計算する。AIに任せるのは「改善点のコメント」だけ。

採点の考え方:
- 基準点から始めて、カロリーが目標を下回った分は加点・超えた分は減点する
- タンパク質の達成は加点のみ
- 「記録できたか」は採点しない。週が締まったか（日曜の3食がそろったか）は
  is_week_ready で門番として見るので、点数には含めない
"""

from dataclasses import dataclass

from app.services.meal_slots import has_all_meals, missing_meal_slots
from app.services.story_image import PROTEIN_TARGET_G

DAYS_IN_WEEK = 7


# 目標ちょうど・タンパク質0点のときの点数
BASE_POINTS = 35.0
# カロリーの増減幅。目標を下回れば最大+35、超えれば最大-35
CALORIE_SWING = 35.0
# 目標のこの割合ぶん下回る／超過すると増減が振り切れる
CALORIE_FULL_SWING_RATIO = 0.20
# タンパク質は加点のみ
POINTS_PROTEIN = 30.0


@dataclass
class ScoreItem:
    """採点項目1つ分。画像の内訳表示にそのまま使う。"""

    key: str
    label: str
    points: float
    max_points: float
    detail: str
    # 加点にも減点にもなる項目（カロリー）。画像では中央から左右に伸ばす
    signed: bool = False

    @property
    def ratio(self) -> float:
        """max_pointsに対する割合。signedの場合は -1.0〜+1.0。"""
        return self.points / self.max_points if self.max_points else 0.0


@dataclass
class WeekScore:
    """1週間の採点結果と、画像に出す集計値。"""

    total: int
    grade: str
    items: list[ScoreItem]
    recorded_days: int
    complete_days: int
    within_goal_days: int
    week_total_calories: float
    calorie_goal: float | None
    average_calories: float | None  # 記録がある日の1日平均
    average_diff: float | None  # 1日平均 - 目標（プラス=オーバー）
    week_goal_calories: float | None  # 目標 x 7日


def _grade(total: int) -> str:
    if total >= 90:
        return "S"
    if total >= 80:
        return "A"
    if total >= 70:
        return "B"
    if total >= 60:
        return "C"
    return "D"


def _day_protein(day: dict) -> float | None:
    return (day.get("nutrients") or {}).get("protein_g")


def _calorie_goal(week: dict, days: list[dict]) -> float | None:
    """週の目標カロリー（1日あたり）を取り出す。設定していない週はNone。"""
    for day in days:
        goal = day.get("calorie_goal")
        if goal:
            return float(goal)
    week_goal = week.get("week_calorie_goal")
    return float(week_goal) / DAYS_IN_WEEK if week_goal else None


def _sunday(week: dict) -> dict | None:
    """週の最終日（日曜）のエントリ。"""
    days = week.get("daily") or []
    if not days:
        return None
    end_date = week.get("end_date")
    for day in days:
        if day.get("date") == end_date:
            return day
    return days[-1]


def sunday_missing_meals(week: dict) -> list[str]:
    """日曜に記録が無い食事区分。そろっていれば空。"""
    sunday = _sunday(week)
    return missing_meal_slots((sunday or {}).get("meals") or [])


def is_week_ready(week: dict) -> bool:
    """その週を投稿してよいか（自動投稿の門番）。

    日曜の3食がそろったことを「週が締まった」合図とする。週の途中は
    日曜がまだ空なので、フライング投稿もこれで防げる。
    """
    return _sunday(week) is not None and not sunday_missing_meals(week)


def _calorie_points(average: float | None, goal: float | None) -> float:
    """目標を下回った分を加点、超えた分を減点する（-CALORIE_SWING〜+CALORIE_SWING）。"""
    if average is None or not goal:
        return 0.0
    # 目標より低ければプラスになる向き
    under_ratio = (goal - average) / goal
    scaled = under_ratio / CALORIE_FULL_SWING_RATIO
    return CALORIE_SWING * max(-1.0, min(1.0, scaled))


def score_week(week: dict) -> WeekScore:
    """diet-mcpの週次サマリ（/api/summary/week）を採点する。"""
    days = week.get("daily") or []
    goal = _calorie_goal(week, days)

    recorded = [d for d in days if d.get("meals")]
    recorded_days = len(recorded)
    complete_days = sum(1 for d in recorded if has_all_meals(d["meals"]))
    within_goal_days = (
        sum(1 for d in recorded if (d.get("total_calories") or 0) <= goal) if goal else 0
    )
    protein_ok_days = sum(1 for d in recorded if (_day_protein(d) or 0) >= PROTEIN_TARGET_G)

    week_total = float(week.get("week_total_calories") or 0)
    average = week_total / recorded_days if recorded_days else None
    average_diff = (average - goal) if (average is not None and goal) else None

    items: list[ScoreItem] = []
    calorie_points = 0.0
    if goal:
        calorie_points = _calorie_points(average, goal)
        diff_label = f"{average_diff:+,.0f} kcal/日" if average_diff is not None else "記録なし"
        items.append(
            ScoreItem(
                key="calorie",
                label="カロリー",
                points=calorie_points,
                max_points=CALORIE_SWING,
                detail=f"{diff_label} → {calorie_points:+.0f}点",
                signed=True,
            )
        )

    protein_points = POINTS_PROTEIN * protein_ok_days / recorded_days if recorded_days else 0.0
    items.append(
        ScoreItem(
            key="protein",
            label="タンパク質",
            points=protein_points,
            max_points=POINTS_PROTEIN,
            detail=f"{round(PROTEIN_TARGET_G)}g達成 {protein_ok_days}/{recorded_days or 0}日",
        )
    )

    # 記録が1日も無い週に基準点だけ付くのは紛らわしいので0点にする
    raw = BASE_POINTS + calorie_points + protein_points if recorded_days else 0.0
    total = int(round(max(0.0, min(100.0, raw))))

    return WeekScore(
        total=total,
        grade=_grade(total),
        items=items,
        recorded_days=recorded_days,
        complete_days=complete_days,
        within_goal_days=within_goal_days,
        week_total_calories=week_total,
        calorie_goal=goal,
        average_calories=average,
        average_diff=average_diff,
        week_goal_calories=goal * DAYS_IN_WEEK if goal else None,
    )
