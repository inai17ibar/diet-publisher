"""1週間の記録を採点して、振り返り画像に載せる数字を組み立てる。

点数をAIに付けさせると同じ週でも呼ぶたびにブレるので、点数と目標差分は
実データから決定的に計算する。AIに任せるのは「改善点のコメント」だけ。
"""

from dataclasses import dataclass

from app.services.meal_slots import has_all_meals
from app.services.story_image import PROTEIN_TARGET_G

DAYS_IN_WEEK = 7

# 記録がこれ未満の週は振り返りとして成立しないので自動投稿しない
MIN_RECORDED_DAYS = 3

# 各項目の配点（目標カロリー未設定の週はcalorieを除いて100点に換算し直す）
POINTS_RECORD = 40.0
POINTS_CALORIE = 35.0
POINTS_PROTEIN = 25.0


@dataclass
class ScoreItem:
    """採点項目1つ分。画像の内訳表示にそのまま使う。"""

    key: str
    label: str
    points: float
    max_points: float
    detail: str

    @property
    def ratio(self) -> float:
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

    items = [
        ScoreItem(
            key="record",
            label="記録",
            points=POINTS_RECORD * complete_days / DAYS_IN_WEEK,
            max_points=POINTS_RECORD,
            detail=f"3食そろった日 {complete_days}/{DAYS_IN_WEEK}日",
        )
    ]
    if goal:
        items.append(
            ScoreItem(
                key="calorie",
                label="目標カロリー",
                points=POINTS_CALORIE * within_goal_days / recorded_days if recorded_days else 0.0,
                max_points=POINTS_CALORIE,
                detail=f"目標内 {within_goal_days}/{recorded_days or 0}日",
            )
        )
    items.append(
        ScoreItem(
            key="protein",
            label="タンパク質",
            points=POINTS_PROTEIN * protein_ok_days / recorded_days if recorded_days else 0.0,
            max_points=POINTS_PROTEIN,
            detail=f"{round(PROTEIN_TARGET_G)}g達成 {protein_ok_days}/{recorded_days or 0}日",
        )
    )

    # 目標カロリー未設定の週は満点が100にならないので100点満点に換算する
    max_total = sum(i.max_points for i in items)
    total = round(sum(i.points for i in items) * 100 / max_total) if max_total else 0

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
        average_diff=(average - goal) if (average is not None and goal) else None,
        week_goal_calories=goal * DAYS_IN_WEEK if goal else None,
    )
