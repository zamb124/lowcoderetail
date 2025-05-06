# Конфигурация (`core_sdk.config`)

Модуль `core_sdk.config` отвечает за управление конфигурацией приложений.
Он предоставляет базовый класс `BaseAppSettings` для создания типизированных настроек,
которые загружаются из переменных окружения и `.env` файлов с использованием Pydantic.

## Основные компоненты

### `BaseAppSettings`
Базовый класс для всех настроек сервисов. Сервис-специфичные настройки должны наследоваться от этого класса.

::: core_sdk.config.BaseAppSettings
    handler: python
    options:
      heading_level: 3
      show_bases: false
      show_root_full_path: false
      members_order: source
      # Явно указываем, какие члены показывать, если нужно
      members:
        - PROJECT_NAME
        - API_V1_STR
        - LOGGING_LEVEL
        - BACKEND_CORS_ORIGINS
        - DB_POOL_SIZE
        - DB_MAX_OVERFLOW
        - ENV
        - model_config # Для Pydantic v2
        # - Config # Для Pydantic v1

## Использование

В каждом микросервисе создается свой класс настроек, наследуемый от `BaseAppSettings`:

```python
# my_service/app/config.py
from core_sdk.config import BaseAppSettings, SettingsConfigDict
from pydantic import PostgresDsn, Field

class Settings(BaseAppSettings):
    PROJECT_NAME: str = "MySpecificService"
    DATABASE_URL: PostgresDsn
    MY_CUSTOM_SETTING: str = Field("default_value", description="Моя кастомная настройка")

    model_config = SettingsConfigDict(
        env_file=".env", # Путь к .env файлу сервиса
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='ignore'
    )
```
settings = Settings()
Значения будут автоматически загружены из переменных окружения или из файла .env, указанного в model_config.
