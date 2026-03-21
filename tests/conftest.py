import os
import sys
from unittest.mock import MagicMock

# Mock instagrapi before any app imports (it has a heavy moviepy dependency)
instagrapi_mock = MagicMock()
sys.modules["instagrapi"] = instagrapi_mock
sys.modules["instagrapi.exceptions"] = MagicMock()

# Set required env vars before any app imports
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_diet_app.db")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.models.database import Base, get_session

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_diet_app.db"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_session():
    async with test_session() as session:
        yield session


app.dependency_overrides[get_session] = override_get_session


@pytest.fixture(autouse=True)
async def setup_db():
    """Create tables before each test and drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def api_headers():
    """Standard API headers with auth key."""
    return {
        "X-API-Key": os.environ["SECRET_KEY"],
        "Content-Type": "application/json",
    }
