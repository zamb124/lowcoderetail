# core_sdk/config.py
import os

from pydantic_settings import BaseSettings, SettingsConfigDict # Импортируем SettingsConfigDict для v2
from pydantic import Field, PostgresDsn
from typing import List

class BaseAppSettings(BaseSettings):
    """
    Базовый класс для настроек приложения.
    Сервис-специфичные настройки должны наследоваться от этого класса
    и добавлять свои поля (DATABASE_URL, REDIS_URL, SECRET_KEY и т.д.).
    """
    PROJECT_NAME: str = "BaseService"
    API_V1_STR: str = "/api/v1"
    LOGGING_LEVEL: str = Field("INFO", examples=["DEBUG", "INFO", "WARNING", "ERROR"])
    BACKEND_CORS_ORIGINS: List[str] = []
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    ENV: str = os.getenv('ENV', 'PROD')
    SECRET_KEY: str = "changethis"
    DATABASE_URL: PostgresDsn = Field(..., description="URL для подключения к основной базе данных PostgreSQL.")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24, description="Время жизни access токена в минутах (1 день).")
    REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24 * 7, description="Время жизни refresh токена в минутах (7 дней).")
