"""Tests for Pydantic schemas and data models."""

from app.models.schemas import (
    DailySummaryResponse,
    MealInput,
    MealLogResponse,
    MealPFCResult,
    MealType,
    PFCData,
    PostResult,
)


def test_pfc_data_creation():
    pfc = PFCData(protein=20.0, fat=10.0, carbs=30.0, calories=300.0)
    assert pfc.protein == 20.0
    assert pfc.fat == 10.0
    assert pfc.carbs == 30.0
    assert pfc.calories == 300.0
    assert pfc.comment == ""


def test_pfc_data_with_comment():
    pfc = PFCData(protein=20.0, fat=10.0, carbs=30.0, calories=300.0, comment="Good job!")
    assert pfc.comment == "Good job!"


def test_meal_input_has_image():
    meal = MealInput(meal_type=MealType.LUNCH, description="salad", image_base64="abc123")
    assert meal.has_image() is True


def test_meal_input_no_image():
    meal = MealInput(meal_type=MealType.LUNCH, description="salad")
    assert meal.has_image() is False


def test_meal_input_empty_image():
    meal = MealInput(meal_type=MealType.LUNCH, description="salad", image_base64="")
    assert meal.has_image() is False


def test_meal_pfc_result():
    pfc = PFCData(protein=20.0, fat=10.0, carbs=30.0, calories=300.0)
    result = MealPFCResult(meal_type=MealType.BREAKFAST, description="toast", pfc=pfc)
    assert result.meal_type == MealType.BREAKFAST
    assert result.description == "toast"
    assert result.pfc.protein == 20.0


def test_post_result_with_meal_details():
    pfc = PFCData(protein=40.0, fat=20.0, carbs=60.0, calories=600.0)
    detail = MealPFCResult(meal_type=MealType.LUNCH, description="chicken", pfc=pfc)
    result = PostResult(success=True, pfc=pfc, meal_details=[detail])
    assert len(result.meal_details) == 1
    assert result.meal_details[0].meal_type == MealType.LUNCH


def test_post_result_default_empty_details():
    pfc = PFCData(protein=40.0, fat=20.0, carbs=60.0, calories=600.0)
    result = PostResult(success=True, pfc=pfc)
    assert result.meal_details == []


def test_meal_log_response():
    resp = MealLogResponse(
        id=1, date="2024-01-01", protein=20.0, fat=10.0, carbs=30.0, calories=300.0
    )
    assert resp.id == 1
    assert resp.meal_description is None
    assert resp.mode == "text_only"


def test_daily_summary_response():
    resp = DailySummaryResponse(
        date="2024-01-01",
        total_protein=60.0,
        total_fat=30.0,
        total_carbs=90.0,
        total_calories=900.0,
        meal_count=3,
    )
    assert resp.meal_count == 3
    assert resp.total_calories == 900.0
