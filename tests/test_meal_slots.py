"""3食そろっているかの判定（自動投稿の門番）のテスト。"""

from app.services.meal_slots import (
    classify_meal,
    has_all_meals,
    missing_label,
    missing_meal_slots,
    recorded_slots,
)


def _meal(time, tags=None):
    return {"time": time, "tags": tags or [], "description": "食事", "calories": 500}


def test_classify_by_time():
    assert classify_meal(_meal("08:00")) == "breakfast"
    assert classify_meal(_meal("12:30")) == "lunch"
    assert classify_meal(_meal("19:00")) == "dinner"
    assert classify_meal(_meal("02:00")) == "dinner"  # 深夜も夜扱い


def test_tags_win_over_time():
    """15時のプロテインバーを「昼食」に数えないよう、tagsを優先する。"""
    assert classify_meal(_meal("15:00", ["間食"])) == "snack"
    assert classify_meal(_meal("11:00", ["朝食"])) == "breakfast"
    assert classify_meal(_meal("21:00", ["dinner"])) == "dinner"


def test_unreadable_time_is_unclassified():
    assert classify_meal(_meal("")) is None
    assert classify_meal(_meal("あさ")) is None
    assert classify_meal({"description": "時刻なし"}) is None


def test_missing_slots_for_partial_day():
    assert missing_meal_slots([_meal("08:00")]) == ["lunch", "dinner"]
    assert missing_meal_slots([_meal("08:00"), _meal("12:30")]) == ["dinner"]
    assert missing_meal_slots([]) == ["breakfast", "lunch", "dinner"]


def test_full_day_has_all_meals():
    meals = [_meal("08:00"), _meal("12:30"), _meal("19:00")]
    assert missing_meal_slots(meals) == []
    assert has_all_meals(meals) is True
    assert recorded_slots(meals) == {"breakfast", "lunch", "dinner"}


def test_snacks_do_not_fill_a_slot():
    """間食をいくら記録しても3食そろったことにはならない。"""
    meals = [_meal("08:00"), _meal("12:30"), _meal("15:00", ["おやつ"])]
    assert missing_meal_slots(meals) == ["dinner"]
    assert has_all_meals(meals) is False


def test_missing_label_is_human_readable():
    assert missing_label(["breakfast", "dinner"]) == "朝・夜"
    assert missing_label([]) == ""
