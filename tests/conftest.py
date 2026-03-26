"""Shared test fixtures."""
import os
import sys
import pytest

# Ensure project root is on sys.path so `src` and root modules are importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment before importing anything
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def test_db(tmp_path):
    """Temporary file-based SQLite database for testing.
    Uses a temp file instead of :memory: because each aiosqlite.connect(':memory:')
    creates an isolated DB, so repos wouldn't see tables created by init_db().
    """
    from src.database.database import Database
    db_path = str(tmp_path / "test.db")
    db = Database(db_path=db_path)
    await db.init_db()
    return db


@pytest.fixture
async def user_repo(test_db):
    """UserRepository backed by in-memory DB."""
    from src.database.user_repo import UserRepository
    return UserRepository(test_db)


@pytest.fixture
async def template_repo(test_db):
    """TemplateRepository backed by in-memory DB."""
    from src.database.template_repo import TemplateRepository
    return TemplateRepository(test_db)
