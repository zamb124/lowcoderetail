# core_sdk/broker/tasks.py
import logging
from typing import Dict, Any, List, TYPE_CHECKING
from uuid import UUID


# --- SDK Импорты ---
from core_sdk.db.session import managed_session  # Контекстный менеджер для сессий БД
from core_sdk.registry import ModelRegistry
from core_sdk.exceptions import CoreSDKError, ConfigurationError

# Импортируем настроенный брокер из setup.py
from .setup import broker  # Объект брокера (InMemoryBroker или RedisStreamBroker)
# --------------------

# --- Type Hinting ---
if TYPE_CHECKING:
    # Используется для статического анализа, не вызывает циклического импорта
    from core_sdk.data_access import BaseDataAccessManager

# Получаем логгер для этого модуля
logger = logging.getLogger("core_sdk.broker.tasks")


# --- Вспомогательная функция для десериализации аргументов ---
def _deserialize_arg(arg: Any) -> Any:
    """
    Преобразует аргумент, полученный задачей, в нужный тип.
    Например, строку UUID обратно в объект UUID.
    """
    if isinstance(arg, str):
        try:
            # Простая проверка на формат UUID
            if len(arg) == 36 and arg.count("-") == 4:
                return UUID(arg)
        except ValueError:
            # Если не удалось преобразовать в UUID, оставляем как есть (строку)
            pass
    elif isinstance(arg, list):
        return [_deserialize_arg(item) for item in arg]
    elif isinstance(arg, dict):
        # Для словарей предполагается, что если нужен Pydantic объект,
        # метод DAM сам его создаст из словаря.
        return {key: _deserialize_arg(value) for key, value in arg.items()}
    return arg


# --- Вспомогательная функция для сериализации результата ---
def _serialize_arg(arg: Any) -> Any:
    """
    Преобразует результат выполнения задачи в JSON-совместимый формат
    для отправки обратно через брокер.
    """
    # Импорты Pydantic и UUID внутри функции, чтобы избежать циклических зависимостей
    # на уровне модуля и уменьшить область видимости.
    from pydantic import BaseModel
    from uuid import UUID

    if isinstance(arg, BaseModel):
        # Сериализуем Pydantic/SQLModel модели
        return arg.model_dump(mode="json")
    elif isinstance(arg, UUID):
        # Преобразуем UUID в строку
        return str(arg)
    elif isinstance(arg, (list, tuple)):
        # Рекурсивно сериализуем элементы списка/кортежа
        return [_serialize_arg(item) for item in arg]
    elif isinstance(arg, dict):
        # Рекурсивно сериализуем значения словаря
        return {key: _serialize_arg(value) for key, value in arg.items()}
    # Простые типы (int, str, float, bool, None) возвращаются как есть
    return arg


# -----------------------------------------------------------


# --- Основная задача Taskiq ---
@broker.task(task_name="execute_dam_operation")
async def execute_dam_operation(
    model_name: str,
    method_name: str,
    serialized_args: List[Any],
    serialized_kwargs: Dict[str, Any],
) -> Any:
    """
    Taskiq задача для выполнения метода Data Access Manager (DAM).

    Эта задача получает имя модели, имя метода и сериализованные аргументы.
    Затем она:
    1. Получает экземпляр соответствующего DAM через фабрику.
    2. Управляет сессией базы данных с помощью `managed_session`.
    3. Десериализует аргументы.
    4. Вызывает указанный метод DAM.
    5. Сериализует и возвращает результат выполнения метода.

    :param model_name: Имя модели, зарегистрированное в ModelRegistry.
    :param method_name: Имя метода DAM, который нужно вызвать.
    :param serialized_args: Список сериализованных позиционных аргументов.
    :param serialized_kwargs: Словарь сериализованных именованных аргументов.
    :return: Сериализованный результат выполнения метода DAM.
    :raises ConfigurationError: Если ModelRegistry не сконфигурирован или менеджер/метод не найден.
    :raises AttributeError: Если у менеджера нет запрошенного метода.
    :raises TypeError: Если найденный атрибут не является вызываемым.
    :raises CoreSDKError: При других ошибках выполнения задачи.
    :raises Exception: Перевыбрасывает исключения, возникшие внутри метода DAM
                       (включая HTTPException, ValidationError и другие ошибки бизнес-логики).
    """
    # Импортируем фабрику DAM внутри задачи, чтобы избежать возможных циклических импортов
    # и гарантировать, что она импортируется в контексте воркера.
    from core_sdk.data_access import DataAccessManagerFactory

    logger.info(f"Worker Task Received: model='{model_name}', method='{method_name}'")
    logger.debug(f"  Serialized Args: {serialized_args}")
    logger.debug(f"  Serialized Kwargs: {serialized_kwargs}")

    # Контекстный менеджер сессии `managed_session` обеспечивает, что сессия
    # будет правильно открыта, и закрыта (с rollback в случае ошибки) после выполнения.
    # Если DAM-методы сами управляют коммитами, то здесь явный коммит не нужен.
    # Если DAM-методы не коммитят, то коммит должен быть здесь, после успешного вызова actual_method.
    async with (
        managed_session()
    ):  # Сессия управляется здесь, но не передается явно в DAM
        try:
            # Проверка конфигурации ModelRegistry (важно для воркеров)
            if not ModelRegistry.is_configured():
                logger.error("ModelRegistry not configured in worker!")
                raise ConfigurationError(
                    "ModelRegistry not configured in worker environment."
                )

            # Создание фабрики DAM. Сессия будет получена DAM-ом через get_current_session().
            # HTTP клиент и токен обычно не нужны для операций DAM, выполняемых воркером.
            dam_factory = DataAccessManagerFactory(registry=ModelRegistry)

            # Получение нужного менеджера
            manager: "BaseDataAccessManager" = dam_factory.get_manager(model_name)
            logger.debug(
                f"Worker Task: Obtained manager '{manager.__class__.__name__}' for model '{model_name}'."
            )

            # Поиск метода на менеджере
            if not hasattr(manager, method_name):
                logger.error(
                    f"Manager for model '{model_name}' has no method '{method_name}'"
                )
                raise AttributeError(
                    f"Manager for model '{model_name}' has no method '{method_name}'"
                )
            actual_method = getattr(manager, method_name)
            if not callable(actual_method):
                logger.error(
                    f"Attribute '{method_name}' on manager for '{model_name}' is not callable"
                )
                raise TypeError(
                    f"Attribute '{method_name}' on manager for '{model_name}' is not callable"
                )

            # Десериализация аргументов
            try:
                deserialized_args = [_deserialize_arg(arg) for arg in serialized_args]
                deserialized_kwargs = {
                    key: _deserialize_arg(value)
                    for key, value in serialized_kwargs.items()
                }
                logger.debug(f"Worker Task: Deserialized Args: {deserialized_args}")
                logger.debug(f"Worker Task: Deserialized Kwargs: {deserialized_kwargs}")
            except Exception as e:
                logger.exception("Error deserializing task arguments.")
                raise CoreSDKError(
                    "Failed to deserialize task arguments for broker task"
                ) from e

            # Выполнение метода DAM
            logger.info(
                f"Worker Task: Executing method '{actual_method.__name__}' on '{manager.__class__.__name__}'..."
            )
            result = await actual_method(*deserialized_args, **deserialized_kwargs)
            logger.info(f"Worker Task: Method '{method_name}' executed successfully.")
            logger.debug(f"  Result type from DAM method: {type(result)}")

            # Сериализация результата для отправки обратно
            try:
                serialized_result = _serialize_arg(result)
                logger.debug(
                    f"  Returning serialized result. Type after serialization: {type(serialized_result)}"
                )
                return serialized_result
            except Exception as e:
                logger.exception("Error serializing task result.")
                raise CoreSDKError(
                    "Failed to serialize task result after DAM execution"
                ) from e

        except (ConfigurationError, AttributeError, TypeError) as e:
            # Ошибки, связанные с получением менеджера или метода
            logger.error(f"Setup error in worker task: {e}", exc_info=True)
            raise  # Перевыбрасываем, чтобы Taskiq пометил задачу как ошибочную
        except Exception:
            # Все остальные исключения, включая те, что пришли из actual_method (DAM)
            # (например, HTTPException, ValidationError, IntegrityError из DAM).
            # Taskiq должен обработать их как ошибку задачи.
            logger.exception(
                f"Worker Task FAILED during execution of '{model_name}.{method_name}'."
            )
            raise  # Перевыбрасываем для корректной обработки Taskiq
