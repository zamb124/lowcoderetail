# Логирование (`core_sdk.logging_config`)

Модуль `core_sdk.logging_config` предоставляет утилиты для настройки стандартного логирования в рамках SDK.

## `setup_sdk_logging()`
Настраивает базовый логгер SDK (`core_sdk`). Позволяет установить уровень логирования и формат сообщений.
Обычно вызывается при инициализации приложения или воркера.

::: core_sdk.logging_config.setup_sdk_logging
    handler: python
    options:
      heading_level: 3

## `get_sdk_logger()`
Вспомогательная функция для получения экземпляра логгера SDK (или его дочернего логгера).

::: core_sdk.logging_config.get_sdk_logger
    handler: python
    options:
      heading_level: 3

## Использование

В модулях SDK логгер получается стандартным образом:

```python
import logging
logger = logging.getLogger(__name__) # Например, core_sdk.data_access.base_manager
# или
# from core_sdk.logging_config import get_sdk_logger
# logger = get_sdk_logger("core_sdk.data_access.base_manager")

logger.info("Сообщение от компонента SDK")
```
Приложение, использующее SDK, может вызвать setup_sdk_logging() на раннем этапе инициализации, чтобы настроить вывод логов SDK. Если этого не сделать, логи SDK могут выводиться с настройками корневого логгера Python по умолчанию.
---