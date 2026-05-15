import base64
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import MealLog
from app.models.schemas import DailyMealInput, MealInput, MealPFCResult, PFCData, PostResult
from app.services.day_counter import calculate_day_number
from app.services.image_editor import create_share_image
from app.services.openai_service import (
    analyze_meal_from_image,
    analyze_meal_from_text,
    generate_caption,
)


async def process_single_meal(meal: MealInput) -> PFCData:
    """単一の食事を処理してPFCを計算"""
    if meal.description:
        return await analyze_meal_from_text(meal.description)
    elif meal.has_image():
        return await analyze_meal_from_image(
            meal.image_base64, additional_info=""
        )
    else:
        raise ValueError("食事の写真または説明が必要です")


async def process_daily_meals(
    daily_input: DailyMealInput,
) -> tuple[PFCData, list[MealPFCResult]]:
    """1日分の食事を処理して合計PFCと個別PFCを計算"""
    # Simple mode: total_description only
    if daily_input.total_description:
        pfc = await analyze_meal_from_text(daily_input.total_description)
        return pfc, []

    # Process each meal and sum up
    if not daily_input.meals:
        raise ValueError("食事情報がありません")

    total_pfc = PFCData(protein=0, fat=0, carbs=0, calories=0, comment="")
    comments = []
    meal_details = []

    for meal in daily_input.meals:
        pfc = await process_single_meal(meal)
        total_pfc.protein += pfc.protein
        total_pfc.fat += pfc.fat
        total_pfc.carbs += pfc.carbs
        total_pfc.calories += pfc.calories
        if pfc.comment:
            comments.append(pfc.comment)
        meal_details.append(
            MealPFCResult(
                meal_type=meal.meal_type,
                description=meal.description,
                pfc=pfc,
            )
        )

    # Round values
    total_pfc.protein = round(total_pfc.protein, 1)
    total_pfc.fat = round(total_pfc.fat, 1)
    total_pfc.carbs = round(total_pfc.carbs, 1)
    total_pfc.calories = round(total_pfc.calories, 0)

    # Combine comments
    if comments:
        total_pfc.comment = comments[-1]  # Use last comment

    return total_pfc, meal_details


async def create_and_post(
    daily_input: DailyMealInput, session: AsyncSession, auto_post: bool = True
) -> PostResult:
    """食事を処理して、共有用の画像と投稿文を作る。"""

    # Meal photos are for nutrition estimation; the share image is edited separately.
    has_photo = daily_input.share_image_base64 is not None

    # Calculate PFC
    pfc, meal_details = await process_daily_meals(daily_input)

    # Get description for caption
    if daily_input.total_description:
        description = daily_input.total_description
    else:
        descriptions = [m.description for m in daily_input.meals if m.description]
        description = "、".join(descriptions) if descriptions else "本日の食事"

    # Generate caption
    day_number = calculate_day_number(daily_input.date)
    caption = await generate_caption(
        pfc,
        description=description,
        has_photo=has_photo,
        day_number=day_number,
        record_date=daily_input.date.strftime("%Y.%m.%d"),
    )

    # Prepare image
    if daily_input.share_image_base64:
        original_image_data = base64.b64decode(daily_input.share_image_base64)
        image_data = create_share_image(
            original_image_data,
            record_date=daily_input.date,
            day_number=day_number,
            pfc=pfc,
        )
        mode = "photo"
    else:
        image_data = None
        mode = "text_only"

    # Save image locally
    image_path = None
    if image_data is not None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_filename = f"meal_{timestamp}.jpg"
        image_path = settings.images_dir / image_filename
        image_path.write_bytes(image_data)

    # Save to database
    meal_log = MealLog(
        date=daily_input.date,
        protein=pfc.protein,
        fat=pfc.fat,
        carbs=pfc.carbs,
        calories=pfc.calories,
        meal_description=description,
        ai_comment=pfc.comment,
        instagram_post_id=None,
        caption=caption,
        image_path=str(image_path) if image_path else None,
        mode=mode,
    )
    session.add(meal_log)
    await session.commit()

    image_base64 = base64.b64encode(image_data).decode("utf-8") if image_data else None

    return PostResult(
        success=True,
        day_number=day_number,
        post_id=None,
        image_url=str(image_path) if image_path else None,
        image_base64=image_base64,
        caption=caption,
        pfc=pfc,
        meal_details=meal_details,
        error=None,
    )
