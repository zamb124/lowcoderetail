# core_sdk/broker/setup.py
import os
import logging
from typing import Any # Для type hinting брокера

from taskiq import InMemoryBroker
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

# Получаем логгер для этого модуля
logger = logging.getLogger("core_sdk.broker.setup")

# --- Получаем URL Redis ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# ---------------------------

# --- Определяем, используется ли тестовый режим ---
# Это влияет на выбор брокера: InMemoryBroker для тестов, Redis для разработки/продакшена.
IS_TEST_MODE_ENV = os.environ.get("ENV", "false").lower() == "test"
# ---------------------------------------------------------

# Переменная для хранения сконфигурированного брокера
broker: Any # Используем Any, т.к. тип будет разным в зависимости от режима

# --- Инициализация InMemoryBroker для возможного использования ---
logger.info("Initializing InMemoryBroker as a potential broker.")
in_memory_broker = InMemoryBroker()
logger.info("InMemoryBroker initialized.")
# ----------------------------------------------------------------

# --- Попытка инициализации Redis брокера ---
# Этот брокер будет использоваться, если окружение не определено как 'prod' -> 'test'
# или если переменная ENV явно указывает на использование Redis (например, 'prod').
redis_broker_instance: Any = None
logger.info(f"Attempting to initialize Redis Broker with REDIS_URL: {REDIS_URL}")
try:
    # 1. Создаем бэкенд результатов для Redis
    logger.debug("Creating RedisAsyncResultBackend...")
    result_backend = RedisAsyncResultBackend(
        redis_url=REDIS_URL,
        # result_ex_time=60 * 5, # Время жизни результата задачи в секундах (опционально)
    )
    logger.debug("RedisAsyncResultBackend created successfully.")

    # 2. Создаем базовый Redis брокер
    logger.debug("Initializing RedisStreamBroker...")
    base_broker = RedisStreamBroker(
        url=REDIS_URL, # URL для подключения к Redis
        # stream_name="taskiq_stream", # Имя стрима в Redis (опционально, по умолчанию 'taskiq')
        # group_name="taskiq_group",   # Имя группы консьюмеров (опционально, по умолчанию 'workers')
    )
    logger.debug("Base RedisStreamBroker initialized.")

    # 3. Добавляем бэкенд результатов к базовому брокеру
    logger.debug("Adding result backend to RedisStreamBroker...")
    redis_broker_instance = base_broker.with_result_backend(result_backend)
    logger.info("Redis broker configured successfully.")
except Exception as e:
    logger.critical(f"FAILED to initialize Redis Broker: {e}", exc_info=True)
    # В случае ошибки инициализации Redis брокера, приложение или воркер не смогут использовать его.
    # Дальнейшее поведение зависит от требований: можно перевыбросить ошибку,
    # или попытаться использовать InMemoryBroker как fallback (но это может быть нежелательно для продакшена).
    # Пока что просто логируем и не прерываем выполнение, выбор брокера произойдет ниже.
    # raise # Раскомментируйте, если ошибка конфигурации Redis должна останавливать запуск
# --------------------------------------------------

# --- Финальный выбор брокера в зависимости от окружения ---
# Если ENV=prod, используется redis_broker_instance (если он успешно создан).
# В противном случае (включая ENV=test, ENV=dev, или если ENV не задана,
# или если redis_broker_instance не был создан из-за ошибки) используется in_memory_broker.
current_env = os.getenv('ENV')
if current_env == 'prod':
    if redis_broker_instance:
        broker = redis_broker_instance
        logger.info("Using Redis Broker for 'prod' environment.")
    else:
        logger.error("Requested 'prod' environment, but Redis Broker failed to initialize. Falling back to InMemoryBroker. THIS IS LIKELY A MISCONFIGURATION FOR PRODUCTION.")
        broker = in_memory_broker # Нежелательный fallback для продакшена
else:
    broker = in_memory_broker
    if IS_TEST_MODE_ENV:
        logger.info("Using InMemoryBroker for 'test' environment.")
    elif current_env:
        logger.info(f"Using InMemoryBroker for '{current_env}' environment.")
    else:
        logger.info("Using InMemoryBroker (ENV not set or not 'prod').")
# ---------------------------------------------------------