# core/app/config.py
import os
import logging
from typing import List, Optional, Union  # Optional может понадобиться для полей без значения по умолчанию

# Импортируем базовый класс и конфигурацию из SDK
from core_sdk.config import BaseAppSettings, SettingsConfigDict
# Импортируем типы Pydantic для валидации
from pydantic import PostgresDsn, RedisDsn, Field, EmailStr, field_validator

# Настройка логгера для этого модуля
logger = logging.getLogger("app.config") # Имя логгера соответствует пути модуля

# --- Определение путей ---
# Абсолютный путь к директории, где находится этот файл (core/app/)
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
# Абсолютный путь к корневой директории проекта (предполагается, что core/ находится в корне)
# Если структура другая, этот путь нужно скорректировать.
# Например, если корень это директория, содержащая core/
PROJECT_ROOT = os.path.abspath(os.path.join(CONFIG_DIR, '..'))
# Абсолютный путь к файлу .env в корне проекта
ENV_FILE_PATH = os.path.join(PROJECT_ROOT, '.env')
# Абсолютный путь к файлу .env.test (если используется для тестов)
ENV_TEST_FILE_PATH = os.path.join(PROJECT_ROOT, '.env.test')

# --- Определение текущего окружения ---
# Используем переменную окружения ENV. По умолчанию 'prod'.
# Важно: Значение ENV влияет на то, какой .env файл будет загружен.
CURRENT_ENV = os.getenv('ENV', 'prod').lower()
logger.info(f"Current environment (ENV): {CURRENT_ENV}")

# Выбираем путь к .env файлу в зависимости от окружения
# Для тестов используем .env.test, для остальных - .env
effective_env_file_path = ENV_TEST_FILE_PATH if CURRENT_ENV == 'test' else ENV_FILE_PATH
logger.info(f"Effective .env file path selected: {effective_env_file_path}")

class Settings(BaseAppSettings):
    """
    Конфигурация для сервиса Core.
    Наследует базовые настройки из `core_sdk.config.BaseAppSettings`
    и добавляет/переопределяет специфичные для Core параметры.
    Загружает значения из переменных окружения и .env файла.
    """
    # --- Переопределение базовых настроек ---
    PROJECT_NAME: str = "CoreService"
    # LOGGING_LEVEL: str = Field("INFO", examples=["DEBUG", "INFO", "WARNING", "ERROR"]) # Наследуется из BaseAppSettings
    # BACKEND_CORS_ORIGINS: List[str] = [] # Наследуется из BaseAppSettings
    # DB_POOL_SIZE: int = 10 # Наследуется из BaseAppSettings
    # DB_MAX_OVERFLOW: int = 5 # Наследуется из BaseAppSettings

    # --- Специфичные настройки Core ---
    DATABASE_URL: PostgresDsn = Field(..., description="URL для подключения к основной базе данных PostgreSQL.")
    REDIS_URL: RedisDsn = Field(..., description="URL для подключения к Redis (для Taskiq или кэширования).")
    SECRET_KEY: str = Field(..., description="Секретный ключ для подписи JWT токенов и других нужд безопасности.")
    ALGORITHM: str = Field("HS256", description="Алгоритм подписи JWT токенов.")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24, description="Время жизни access токена в минутах (1 день).")
    REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24 * 7, description="Время жизни refresh токена в минутах (7 дней).")

    # Настройки для создания первого суперпользователя (если используется)
    FIRST_SUPERUSER_EMAIL: EmailStr = Field("admin@example.com", description="Email для первого суперпользователя.")
    FIRST_SUPERUSER_PASSWORD: str = Field("changethis", description="Пароль для первого суперпользователя (рекомендуется изменить).")

    # Переопределяем ENV из BaseAppSettings, чтобы он был здесь явно виден
    ENV: str = Field(CURRENT_ENV, description="Текущее окружение (например, 'dev', 'test', 'prod'). Влияет на загрузку .env файла.")

    # --- Конфигурация Pydantic Settings ---
    model_config = SettingsConfigDict(
        # Указываем путь к .env файлу, который был выбран ранее
        env_file=effective_env_file_path,
        env_file_encoding='utf-8',
        case_sensitive=True, # Имена переменных окружения чувствительны к регистру
        extra='ignore' # Игнорировать лишние переменные в .env файле или окружении
    )

    # --- Валидаторы (пример) ---
    @field_validator('BACKEND_CORS_ORIGINS', mode='before')
    @classmethod
    def assemble_cors_origins(cls, v: Optional[Union[str, List[str]]]) -> List[str]:
        """
        Позволяет задавать BACKEND_CORS_ORIGINS в .env как строку через запятую
        или как список строк.
        """
        if isinstance(v, str) and v:
            # Разделяем строку по запятым и удаляем пробелы
            return [origin.strip() for origin in v.split(',') if origin.strip()]
        elif isinstance(v, list):
            # Удаляем пустые строки и пробелы из списка
            return [str(origin).strip() for origin in v if str(origin).strip()]
        # Если значение None или пустая строка/список, возвращаем пустой список
        return []


# --- Создание и проверка экземпляра настроек ---
try:
    settings = Settings()
    # Логируем некоторые НЕ СЕКРЕТНЫЕ настройки для проверки
    logger.info(f"Settings loaded successfully for ENV='{settings.ENV}'.")
    logger.info(f"Project Name: {settings.PROJECT_NAME}")
    logger.info(f"Logging Level: {settings.LOGGING_LEVEL}")
    logger.info(f"DB Pool Size: {settings.DB_POOL_SIZE}")
    logger.info(f"CORS Origins: {settings.BACKEND_CORS_ORIGINS}")
    # НЕ ЛОГИРУЙТЕ СЕКРЕТЫ!
    # logger.debug(f"Database URL: {settings.DATABASE_URL}") # Небезопасно
    # logger.debug(f"Redis URL: {settings.REDIS_URL}") # Небезопасно
    # logger.debug(f"Secret Key: {'*' * len(settings.SECRET_KEY) if settings.SECRET_KEY else 'Not Set'}") # Частично безопасно

except Exception as e:
    logger.critical(f"Failed to load or validate settings from '{effective_env_file_path}' and environment variables.", exc_info=True)
    # Выбрасываем исключение, так как без настроек приложение не сможет работать корректно
    raise RuntimeError(f"Could not load application settings: {e}") from e

# --- Проверка существования .env файла (информационное сообщение) ---
if not os.path.exists(effective_env_file_path):
    logger.warning(f".env file not found at the expected path: {effective_env_file_path}. Relying solely on environment variables.")
else:
    logger.debug(f".env file found and loaded from: {effective_env_file_path}")

# --- КОНЕЦ ФАЙЛА core/app/config.py ---