"""Test configuration — SQLite in-memory engine + mocked weasyprint."""
import json, os, sys, types
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ["DATABASE_URL"] = "sqlite://"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# ---------------------------------------------------------------------------
# Mock weasyprint (C libs not available)
# ---------------------------------------------------------------------------
_ws = types.ModuleType("weasyprint")
class _MockHTML:
    def __init__(self, *args, **kwargs): pass
    def write_pdf(self, *args, **kwargs):
        return b"%PDF-1.4 fake pdf content for tests"

_ws.HTML = _MockHTML
sys.modules["weasyprint"] = _ws

# ---------------------------------------------------------------------------
# SQLite-compatible JSONB — transparently store as TEXT under SQLite
# ---------------------------------------------------------------------------
from sqlalchemy import TypeDecorator, Text as SA_Text

class _SqliteJSONB(TypeDecorator):
    impl = SA_Text; cache_ok = True
    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(SA_Text())
        from sqlalchemy.dialects.postgresql import JSONB as _r
        return dialect.type_descriptor(_r())
    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name == "sqlite":
            return json.dumps(value)
        return value
    def process_result_value(self, value, dialect):
        if value is not None and dialect.name == "sqlite":
            try: return json.loads(value)
            except (json.JSONDecodeError, TypeError): return value
        return value

import sqlalchemy.dialects.postgresql as _pg
_pg.JSONB = _SqliteJSONB

# ---------------------------------------------------------------------------
# SQLite engine
# ---------------------------------------------------------------------------
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_test_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
_test_SessionLocal = sessionmaker(bind=_test_engine)

import src.db.session
src.db.session.engine = _test_engine
src.db.session.SessionLocal = _test_SessionLocal

# ---------------------------------------------------------------------------
# Import app_main (safe now — migrations skip non-Postgres)
# ---------------------------------------------------------------------------
import app_main

app = app_main.app

# ---------------------------------------------------------------------------
# Dependency overrides for tests
# ---------------------------------------------------------------------------
from src.api.deps import get_current_user
from src.db.base import Base
from src.db.session import get_db
from src.models.user import User, UserRole
import pytest

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def override_get_current_user():
    return User(id=1, email="test@example.com", role=UserRole.admin)

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(app)

@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
