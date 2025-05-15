# apps/core/config.py
import os
import logging
from typing import List, Optional, Union

# ИЗМЕНЕНИЕ: Импортируем Field из pydantic, если он нужен для обязательных полей без значения по умолчанию.
# Убираем RedisDsn, EmailStr (оставим EmailStr, он стандартный).
from pydantic import Field, EmailStr, field_validator  # RedisDsn убран

# Импортируем BaseAppSettings из SDK
from core_sdk.config import BaseAppSettings, SettingsConfigDict

logger = logging.getLogger("app.config")


class Settings(BaseAppSettings):
    PROJECT_NAME: str = "CoreService"

    # ИЗМЕНЕНИЕ: PostgresDsn -> str
    DATABASE_URL: str = Field(
        ..., description="URL для подключения к основной базе данных PostgreSQL."
    )
    # ИЗМЕНЕНИЕ: RedisDsn -> Optional[str]
    REDIS_URL: Optional[str] = Field(
        None, description="URL для подключения к Redis (для Taskiq или кэширования)."
    )
    ALGORITHM: str = Field("HS256", description="Алгоритм подписи JWT токенов.")
    # Поля ACCESS_TOKEN_EXPIRE_MINUTES и REFRESH_TOKEN_EXPIRE_MINUTES переопределяют базовые.
    # Это нормально.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        60 * 24, description="Время жизни access токена в минутах (1 день)."
    )
    REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(
        60 * 24 * 7, description="Время жизни refresh токена в минутах (7 дней)."
    )

    FIRST_SUPERUSER_EMAIL: EmailStr = Field(
        "admin@example.com", description="Email для первого суперпользователя."
    )
    FIRST_SUPERUSER_PASSWORD: str = Field(
        "changethis",
        description="Пароль для первого суперпользователя (рекомендуется изменить).",
    )

    ENV: str = Field(
        ...,
        description="Текущее окружение (например, 'dev', 'test', 'prod'). Влияет на загрузку .env файла.",
    )

    model_config = SettingsConfigDict(
        env_file=".env" if os.getenv("ENV") != "test" else ".env.test",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Optional[Union[str, List[str]]]) -> List[str]:
        if isinstance(v, str) and v:
            return [o.strip() for o in v.split(",") if o.strip()]
        if isinstance(v, list):
            return [str(o).strip() for o in v if str(o).strip()]
        return []

try:
    settings = Settings()
    logger.info(f"Settings loaded successfully for ENV='{settings.ENV}'.")
    logger.info(f"Project Name: {settings.PROJECT_NAME}")
    # ... (остальные логгирования)
except Exception as e:
    raise RuntimeError(f"Could not load application settings: {e}") from e