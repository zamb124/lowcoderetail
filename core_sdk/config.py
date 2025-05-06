# core_sdk/config.py
import os

from pydantic_settings import BaseSettings, SettingsConfigDict # Импортируем SettingsConfigDict для v2
from pydantic import Field
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

    # Используем model_config для Pydantic v2
    model_config = SettingsConfigDict(
        # Указываем стандартное имя файла .env
        env_file=".env",
        env_file_encoding='utf-8',
        case_sensitive=True,
        # extra='ignore' # Игнорировать лишние переменные в .env (опционально)
    )
    # Для Pydantic v1 использовался вложенный класс Config:
    # class Config:
    #     env_file = ".env"
    #     env_file_encoding = 'utf-8'
    #     case_sensitive = True