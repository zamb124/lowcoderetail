# core_sdk/config.py
import os

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)
from pydantic import Field # Убрали PostgresDsn из этого импорта
from typing import List, Optional # Добавили Optional для RedisDsn в apps/core


class BaseAppSettings(BaseSettings):
    PROJECT_NAME: str = "BaseService"
    API_V1_STR: str = "/api/v1"
    LOGGING_LEVEL: str = Field(
        "INFO",
        # Если это не вызывает проблем, можно оставить для OpenAPI
        json_schema_extra={"examples": ["DEBUG", "INFO", "WARNING", "ERROR"]}
    )
    BACKEND_CORS_ORIGINS: List[str] = []
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    ENV: str = os.getenv("ENV", "PROD")
    SECRET_KEY: str = "changethis"
    # ИЗМЕНЕНИЕ: PostgresDsn -> str, убрали Field(...) если default нет
    DATABASE_URL: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        60 * 24, description="Время жизни access токена в минутах (1 день)."
    )
    REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(
        60 * 24 * 7, description="Время жизни refresh токена в минутах (7 дней)."
    )

    model_config = SettingsConfigDict(
        extra='ignore',
    )