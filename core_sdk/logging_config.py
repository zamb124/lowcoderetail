# core_sdk/logging_config.py
import logging
import sys

# Определяем имя базового логгера для всего SDK
SDK_LOGGER_NAME = "core_sdk"


def setup_sdk_logging(
    level=logging.INFO,
    log_format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
):
    """Настраивает базовый логгер SDK."""
    logger = logging.getLogger(SDK_LOGGER_NAME)

    # Предотвращаем дублирование обработчиков, если функция вызывается несколько раз
    if logger.hasHandlers():
        # Можно очистить существующих обработчиков или просто выйти
        # logger.handlers.clear()
        print(f"Logger '{SDK_LOGGER_NAME}' already has handlers. Skipping setup.")
        return logger

    logger.setLevel(level)

    # Обработчик для вывода в консоль
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # Форматтер
    formatter = logging.Formatter(log_format)
    handler.setFormatter(formatter)

    # Добавляем обработчик к логгеру
    logger.addHandler(handler)

    # Опционально: Запретить логам распространяться к корневому логгеру Python,
    # если вы хотите полностью контролировать вывод SDK логов.
    # logger.propagate = False

    print(
        f"SDK Logging setup complete for '{SDK_LOGGER_NAME}' at level {logging.getLevelName(level)}"
    )
    return logger


# --- Вариант 1: Вызвать настройку при импорте logging_config ---
# setup_sdk_logging()
# --- Вариант 2: Предоставить функцию setup_sdk_logging для вызова извне ---
# (предпочтительнее, чтобы приложение могло контролировать момент настройки)


# --- Получение логгера для использования внутри SDK ---
# Можно также предоставить функцию для удобства
def get_sdk_logger(name: str = SDK_LOGGER_NAME) -> logging.Logger:
    """Возвращает экземпляр логгера SDK (или его дочерний)."""
    # Убедимся, что базовый логгер настроен, если еще нет
    # if not logging.getLogger(SDK_LOGGER_NAME).hasHandlers():
    #     print(f"Warning: SDK logger '{SDK_LOGGER_NAME}' accessed before setup. Performing default setup.")
    #     setup_sdk_logging() # Настройка по умолчанию, если не вызвали явно
    return logging.getLogger(name)
