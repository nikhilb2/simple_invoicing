import os


def pytest_configure(config):
    """Set required env vars before any test module is imported."""
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
    os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
    os.environ.setdefault("ENVIRONMENT", "development")
