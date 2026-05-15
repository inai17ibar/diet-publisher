from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routes import router
from app.config import settings
from app.models.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションのライフサイクル管理"""
    # Startup
    await init_db()
    yield
    # Shutdown
    pass


app = FastAPI(
    title="ChatGPT Diet App",
    description="AI-powered diet tracking with share-ready image and post text creation",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS設定（iPhoneショートカットからのアクセス用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーター登録
app.include_router(router, prefix="/api/v1")

# 静的ファイルのディレクトリ
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def root():
    """フロントエンドページを表示"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api")
async def api_info():
    return {
        "message": "ChatGPT Diet App API",
        "docs": "/docs",
        "version": "0.1.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
