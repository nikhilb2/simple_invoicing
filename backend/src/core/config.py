from pydantic_settings import BaseSettings
import os
from pathlib import Path


# Detect environment from ENVIRONMENT variable, default to development
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Build path to the appropriate .env file
env_file_path = Path(f".env.{ENVIRONMENT}")
if not env_file_path.exists():
    # Fallback to .env if environment-specific file doesn't exist
    env_file_path = Path(".env")


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    DEBUG: bool = False
    ENVIRONMENT: str = ENVIRONMENT
    N8N_EMAIL_WEBHOOK_URL: str = "https://n8n.nikhilbhatia.com/webhook/mail"
    N8N_EMAIL_WEBHOOK_USER: str = ""
    N8N_EMAIL_WEBHOOK_PASS: str = ""
    SMTP_ENCRYPTION_KEY: str | None = None

    class Config:
        env_file = str(env_file_path)
        case_sensitive = False


settings = Settings()

if settings.ENVIRONMENT == "production" and not settings.SMTP_ENCRYPTION_KEY:
    raise ValueError("SMTP_ENCRYPTION_KEY is required in production environment")

# Log which environment is being used
print(f"🚀 Backend running in {settings.ENVIRONMENT} mode (loaded from {env_file_path})")
