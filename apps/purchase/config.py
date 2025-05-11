# purchase/app/config.py
import os
import logging
from typing import List, Optional, Union

from dotenv import load_dotenv

from core_sdk.config import BaseAppSettings, SettingsConfigDict
from pydantic import PostgresDsn, RedisDsn, Field, field_validator

logger = logging.getLogger("app.config")
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CONFIG_DIR, ".."))  # Директория purchase/
ENV_FILE_PATH = os.path.join(PROJECT_ROOT, ".env")
ENV_TEST_FILE_PATH = os.path.join(PROJECT_ROOT, ".env.test")

_CURRENT_ENV_VAR_LOCAL = os.getenv("ENV", "prod").lower()
_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL = ENV_TEST_FILE_PATH if _CURRENT_ENV_VAR_LOCAL == "test" else ENV_FILE_PATH
logger.info("Current environment (ENV): %s for PurchaseService", _CURRENT_ENV_VAR_LOCAL)
logger.info("Effective .env file path for PurchaseService: %s", _EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL)
load_dotenv(_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL)


class Settings(BaseAppSettings):
    PROJECT_NAME: str = "PurchaseService"
    DATABASE_URL: PostgresDsn = Field(..., description="URL для подключения к PostgreSQL для сервиса Purchase.")
    REDIS_URL: Optional[RedisDsn] = Field(None, description="URL для Redis (если используется Taskiq или кэш).")
    SECRET_KEY: str = Field(
        ..., description="Секретный ключ для сервиса Purchase (например, для подписи чего-либо специфичного)."
    )

    # URL других сервисов, от которых может зависеть Purchase
    CORE_SERVICE_URL: Optional[str] = Field(
        "http://core:8000", description="URL к Core сервису."
    )  # Убедимся, что есть значение
    # CATALOG_SERVICE_URL: Optional[str] = Field(None, description="URL к Catalog сервису.")

    ENV: str = Field(_CURRENT_ENV_VAR_LOCAL, description="Текущее окружение.")
    API_V1_STR: str = "/api/purchase"
    PORT_PURCHASE: int = Field(8002, description="Порт, на котором будет работать сервис Purchase.")

    model_config = SettingsConfigDict(
        env_file=_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL, env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
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
    logger.info("Settings loaded for %s (ENV='%s').", settings.PROJECT_NAME, settings.ENV)
except Exception as e:
    logger.critical(
        "Failed to load settings for PurchaseService from '%s'.", _EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL, exc_info=True
    )
    raise RuntimeError(f"Could not load PurchaseService settings: {e}") from e

if not os.path.exists(_EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL):
    logger.warning(".env file for PurchaseService not found at %s.", _EFFECTIVE_ENV_FILE_PATH_VAR_LOCAL)
