from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


class MealLog(Base):
    """食事ログのDBモデル"""

    __tablename__ = "meal_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    date = Column(DateTime, nullable=False)

    # PFC データ
    protein = Column(Float, nullable=False)
    fat = Column(Float, nullable=False)
    carbs = Column(Float, nullable=False)
    calories = Column(Float, nullable=False)

    # 食事情報
    meal_description = Column(Text, nullable=True)
    ai_comment = Column(Text, nullable=True)

    # 投稿用出力
    instagram_post_id = Column(String(100), nullable=True)
    caption = Column(Text, nullable=True)
    image_path = Column(String(500), nullable=True)

    # モード（photo / text_only）
    mode = Column(String(20), default="text_only")


class StoryImageLog(Base):
    """ストーリー画像の生成台帳。同じ日の画像を二度作らないための記録"""

    __tablename__ = "story_image_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(10), unique=True, nullable=False)  # YYYY-MM-DD
    created_at = Column(DateTime, default=datetime.utcnow)


class StoryPostLog(Base):
    """Instagramストーリーへの自動投稿の台帳。同じ日に二度投稿しないための記録"""

    __tablename__ = "story_post_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(10), unique=True, nullable=False)  # YYYY-MM-DD
    media_id = Column(String(100), nullable=True)
    advice = Column(Text, nullable=True)  # 画像に載せたAIコーチの一言
    created_at = Column(DateTime, default=datetime.utcnow)


class WeeklyPostLog(Base):
    """週次振り返り投稿の台帳。同じ週に二度投稿しないための記録"""

    __tablename__ = "weekly_post_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(String(10), unique=True, nullable=False)  # 週の月曜 YYYY-MM-DD
    media_id = Column(String(100), nullable=True)
    score = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)  # 画像に載せた改善ポイント
    created_at = Column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    """キーバリューの設定保存（Instagramアクセストークンの自動更新用など）"""

    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Database engine and session
engine = create_async_engine(settings.db_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """データベースを初期化"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """セッションを取得"""
    async with async_session() as session:
        yield session
