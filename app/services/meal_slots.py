"""1日の記録が「3食そろっているか」を判定する。

diet-mcpの食事レコードには食事区分のフィールドが無いので、`tags`
（"朝食" などが入ることがある）を優先し、無ければ `time` から推定する。
自動投稿はこの判定を門番にして、朝だけ・朝昼だけの日をストーリーに
出さないようにしている（1日の記録として不完全なものは発信しない）。
"""

BREAKFAST = "breakfast"
LUNCH = "lunch"
DINNER = "dinner"
SNACK = "snack"

# この3つが揃って初めて「1日分の記録」とみなす（間食は数えない）
REQUIRED_SLOTS = (BREAKFAST, LUNCH, DINNER)

SLOT_LABELS_JA = {BREAKFAST: "朝", LUNCH: "昼", DINNER: "夜", SNACK: "間食"}

# tagsに入っていたら時刻より優先する表記ゆれの一覧
_TAG_SLOTS = {
    "朝": BREAKFAST,
    "朝食": BREAKFAST,
    "朝ごはん": BREAKFAST,
    "breakfast": BREAKFAST,
    "昼": LUNCH,
    "昼食": LUNCH,
    "昼ごはん": LUNCH,
    "ランチ": LUNCH,
    "lunch": LUNCH,
    "夜": DINNER,
    "夕": DINNER,
    "夕食": DINNER,
    "夜食": DINNER,
    "晩ごはん": DINNER,
    "夜ごはん": DINNER,
    "dinner": DINNER,
    "間食": SNACK,
    "おやつ": SNACK,
    "スナック": SNACK,
    "snack": SNACK,
}

# 時刻から推定する区分。(開始時, 終了時(含まない), 区分)
_TIME_SLOTS = (
    (4, 11, BREAKFAST),  # 04:00-10:59
    (11, 16, LUNCH),  # 11:00-15:59
    (16, 24, DINNER),  # 16:00-23:59
    (0, 4, DINNER),  # 00:00-03:59（深夜の食事も夜の扱い）
)


def _slot_from_time(time_str: str | None) -> str | None:
    """"HH:MM" から食事区分を推定する。読めない値はNone。"""
    if not time_str:
        return None
    try:
        hour = int(str(time_str).split(":")[0])
    except (ValueError, IndexError):
        return None
    for start, end, slot in _TIME_SLOTS:
        if start <= hour < end:
            return slot
    return None


def classify_meal(meal: dict) -> str | None:
    """食事1件を breakfast / lunch / dinner / snack に分類する。"""
    for tag in meal.get("tags") or []:
        slot = _TAG_SLOTS.get(str(tag).strip().lower())
        if slot:
            return slot
    return _slot_from_time(meal.get("time"))


def recorded_slots(meals: list[dict]) -> set[str]:
    """その日に記録されている食事区分の集合。"""
    return {slot for slot in (classify_meal(m) for m in meals or []) if slot}


def missing_meal_slots(meals: list[dict]) -> list[str]:
    """3食のうち記録が無い区分を REQUIRED_SLOTS の順で返す。"""
    present = recorded_slots(meals)
    return [slot for slot in REQUIRED_SLOTS if slot not in present]


def has_all_meals(meals: list[dict]) -> bool:
    """朝・昼・夜がすべて記録されているか。"""
    return not missing_meal_slots(meals)


def missing_label(missing: list[str]) -> str:
    """未記録の区分を「朝・夜」のような表示用の文字列にする。"""
    return "・".join(SLOT_LABELS_JA.get(slot, slot) for slot in missing)
