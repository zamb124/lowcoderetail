# apps/frontend/app/config.py
import os
import logging
from typing import List, Optional, Union
from core_sdk.config import (
    BaseAppSettings,
    SettingsConfigDict,
)  # Используем базовые настройки SDK
from pydantic import RedisDsn, Field, field_validator, HttpUrl

logger = logging.getLogger("app.config")

# Определяем пути относительно текущего файла config.py
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
# Путь к корню сервиса frontend (apps/frontend)
SERVICE_ROOT = os.path.dirname(CONFIG_DIR)
# Путь к корню всего проекта (где лежит apps/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(SERVICE_ROOT))

ENV_FILE_PATH = os.path.join(SERVICE_ROOT, ".env")
ENV_TEST_FILE_PATH = os.path.join(SERVICE_ROOT, ".env.test")

_CURRENT_ENV_VAR_LOCAL = os.getenv("ENV", "dev").lower()
_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL = (
    ENV_TEST_FILE_PATH if _CURRENT_ENV_VAR_LOCAL == "test" else ENV_FILE_PATH
)

logger.info("Current environment (ENV): %s for Frontend", _CURRENT_ENV_VAR_LOCAL)
logger.info(
    "Effective .env file path for Frontend: %s", _EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL
)
if not os.path.exists(_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL):
    logger.warning(
        ".env file for Frontend not found at %s. Using environment variables only.",
        _EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL,
    )


class FrontendSettings(BaseAppSettings):
    """Настройки для Frontend Service."""

    # Переопределяем базовые или добавляем свои
    PROJECT_NAME: str = "FrontendService"
    # DATABASE_URL: Optional[PostgresDsn] = Field(None, description="URL для PostgreSQL (если нужен SDK).") # Скорее всего не нужен
    REDIS_URL: Optional[RedisDsn] = Field(
        None, description="URL для Redis (для WebSocket/Taskiq)."
    )
    ALGORITHM: str = Field(
        "HS256", description="Алгоритм подписи JWT токенов."
    )  # Нужен для middleware

    # --- URLs других сервисов ---
    # Важно: Это базовые URL сервисов, без /api/v1
    CORE_SERVICE_URL: HttpUrl = Field(
        ..., description="Базовый URL к Core сервису (e.g., http://core:8000)."
    )
    # Добавьте URL других сервисов по необходимости
    # ORDER_SERVICE_URL: Optional[HttpUrl] = Field(None, description="Базовый URL к Order сервису.")

    # Настройки самого Frontend сервиса
    FRONTEND_PORT: int = Field(8080, description="Порт для Frontend сервиса")
    API_V1_STR: str = "/"  # Путь к API (можно переопределить, если нужно)

    # Пути к статике и шаблонам SDK (для информации, используются напрямую из SDK)
    SDK_STATIC_URL_PATH: str = "/sdk-static"
    SDK_TEMPLATES_DIR: str = "core_sdk/frontend/templates"  # Информационно

    # Настройки CORS (из BaseAppSettings)
    # BACKEND_CORS_ORIGINS: List[str] = []

    model_config = SettingsConfigDict(
        env_file=_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Игнорировать лишние переменные
    )

    # Валидатор CORS остается полезным
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Optional[Union[str, List[str]]]) -> List[str]:
        if isinstance(v, str) and v:
            return [o.strip() for o in v.split(",") if o.strip()]
        if isinstance(v, list):
            return [str(o).strip() for o in v if str(o).strip()]
        return []


try:
    settings = FrontendSettings()
    logger.info(
        "Settings loaded for %s (ENV='%s').", settings.PROJECT_NAME, settings.ENV
    )
    logger.info("Core Service URL: %s", settings.CORE_SERVICE_URL)
    # Логгирование других URL...
except Exception as e:
    logger.critical(
        "Failed to load settings for Frontend from '%s'.",
        _EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL,
        exc_info=True,
    )
    raise RuntimeError(f"Could not load Frontend settings: {e}") from e
