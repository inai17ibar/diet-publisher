from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MealType(str, Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class PFCData(BaseModel):
    protein: float = Field(..., description="タンパク質 (g)")
    fat: float = Field(..., description="脂質 (g)")
    carbs: float = Field(..., description="炭水化物 (g)")
    calories: float = Field(..., description="カロリー (kcal)")
    comment: str = Field(default="", description="AIからのコメント")


class MealInput(BaseModel):
    """食事入力（写真またはテキスト）"""

    meal_type: MealType = Field(default=MealType.LUNCH, description="食事タイプ")
    description: str | None = Field(default=None, description="食事の説明テキスト")
    image_base64: str | None = Field(default=None, description="食事写真（Base64）")

    def has_image(self) -> bool:
        return self.image_base64 is not None and len(self.image_base64) > 0


class DailyMealInput(BaseModel):
    """1日分の食事入力"""

    date: datetime = Field(default_factory=datetime.now)
    meals: list[MealInput] = Field(default_factory=list)
    total_description: str | None = Field(
        default=None, description="1日の食事をまとめて説明（簡易モード用）"
    )


class MealPFCResult(BaseModel):
    """個別食事のPFC結果"""

    meal_type: MealType
    description: str | None = None
    pfc: PFCData


class PostResult(BaseModel):
    """投稿結果"""

    success: bool
    post_id: str | None = None
    image_url: str | None = None
    image_base64: str | None = Field(default=None, description="生成画像（Base64 JPEG）")
    caption: str | None = None
    pfc: PFCData | None = None
    meal_details: list[MealPFCResult] = Field(default_factory=list, description="各食事ごとのPFC")
    error: str | None = None


class MealLogResponse(BaseModel):
    """食事ログのレスポンス"""

    id: int
    date: str
    protein: float
    fat: float
    carbs: float
    calories: float
    meal_description: str | None = None
    ai_comment: str | None = None
    mode: str = "text_only"


class DailySummaryResponse(BaseModel):
    """日別サマリーのレスポンス"""

    date: str
    total_protein: float
    total_fat: float
    total_carbs: float
    total_calories: float
    meal_count: int


class HealthCheckResponse(BaseModel):
    status: str
    version: str = "0.1.0"
