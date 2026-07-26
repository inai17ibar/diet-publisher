from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .envに残った旧設定キー（INSTAGRAM_*等）を無視する
    )

    # OpenAI
    openai_api_key: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "change-me-in-production"
    diet_start_date: date = date(2025, 6, 20)

    # diet-mcp連携（ストーリー画像の記録データ取得元）
    diet_mcp_url: str = "https://diet-mcp.fly.dev"
    diet_mcp_api_key: str = ""

    # Paths
    project_root: Path = Path(__file__).resolve().parent.parent
    images_dir: Path | None = None
    data_dir: Path = Path("/data")  # Railway Volume用（本番）
    database_url: str | None = None  # 環境変数で上書き可能

    @property
    def db_url(self) -> str:
        """データベースURLを取得（環境変数 > data_dir > デフォルト）"""
        if self.database_url:
            return self.database_url
        # /data ディレクトリが存在する場合はそちらを使用（Railway Volume）
        if self.data_dir.exists():
            return f"sqlite+aiosqlite:///{self.data_dir}/diet_app.db"
        # ローカル開発用
        return f"sqlite+aiosqlite:///{self.project_root / 'diet_app.db'}"

settings = Settings()

# Ensure images directory exists
if settings.images_dir is None:
    settings.images_dir = settings.project_root / "images"
elif not settings.images_dir.is_absolute():
    settings.images_dir = settings.project_root / settings.images_dir
settings.images_dir.mkdir(parents=True, exist_ok=True)
