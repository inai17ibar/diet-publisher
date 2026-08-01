from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import settings
from app.models.database import init_db
from app.services.meal_processor import DuplicateMealError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションのライフサイクル管理"""
    # Startup
    await init_db()
    yield
    # Shutdown
    pass


app = FastAPI(
    title="Diet Publisher",
    description="Diet record rendering and Instagram story publishing API",
    version="0.2.0",
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

@app.exception_handler(DuplicateMealError)
async def duplicate_meal_handler(request: Request, exc: DuplicateMealError):
    """重複リクエストは409で返す（ショートカット側はエラー時にヘルスケア記録をスキップ）"""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# ルーター登録
app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    """APIサーバー情報（フロントエンドは廃止済み）"""
    return {
        "message": "Diet Publisher API",
        "docs": "/docs",
        "version": "0.2.0",
    }


@app.get("/api")
async def api_info():
    return {
        "message": "Diet Publisher API",
        "docs": "/docs",
        "version": "0.2.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
