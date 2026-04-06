from pydantic_settings import BaseSettings
from pydantic import model_validator
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
    SMTP_ENCRYPTION_KEY: str | None = None

    @model_validator(mode="after")
    def validate_smtp_key_in_production(self):
        if self.ENVIRONMENT == "production" and not self.SMTP_ENCRYPTION_KEY:
            raise ValueError("SMTP_ENCRYPTION_KEY is required in production environment")
        return self

    class Config:
        env_file = str(env_file_path)
        case_sensitive = False


settings = Settings()

# Log which environment is being used
print(f"🚀 Backend running in {settings.ENVIRONMENT} mode (loaded from {env_file_path})")
