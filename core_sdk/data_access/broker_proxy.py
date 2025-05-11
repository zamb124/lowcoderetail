# core_sdk/data_access/broker_proxy.py
import functools
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, TypeVar, List, Type
from uuid import UUID
from pydantic import BaseModel

from core_sdk.broker.setup import broker
from core_sdk.broker.tasks import execute_dam_operation
from core_sdk.exceptions import ConfigurationError, CoreSDKError
from taskiq import TaskiqResult, TaskiqError, TaskiqResultTimeoutError

if TYPE_CHECKING:
    from core_sdk.data_access.base_manager import BaseDataAccessManager
    from taskiq import (
        AsyncTaskiqDecoratedTask,
    )  # Оставляем, т.к. TaskiqResult может его содержать

logger = logging.getLogger(__name__)  # Имя будет core_sdk.data_access.broker_proxy


def _serialize_arg(arg: Any) -> Any:
    """Преобразует аргумент в JSON-совместимый формат для передачи через брокер."""
    if isinstance(arg, BaseModel):
        return arg.model_dump(mode="json")
    elif isinstance(arg, UUID):
        return str(arg)
    elif isinstance(arg, (list, tuple)):
        return [_serialize_arg(item) for item in arg]
    elif isinstance(arg, dict):
        return {key: _serialize_arg(value) for key, value in arg.items()}
    return arg


def _deserialize_broker_result(data: Any, dam_instance: "BaseDataAccessManager") -> Any:
    """
    Пытается десериализовать результат, полученный от воркера,
    используя read_schema менеджера, если это возможно.
    """
    read_schema: Optional[Type[BaseModel]] = getattr(dam_instance, "read_schema", None)

    if read_schema and isinstance(data, dict):
        try:
            return read_schema.model_validate(data)
        except Exception as e:
            logger.warning(
                f"Failed to deserialize broker result into {read_schema.__name__}: {e}. Returning raw data: {data}"
            )
            return data
    elif isinstance(data, str):
        try:
            # Простая проверка на формат UUID
            if len(data) == 36 and data.count("-") == 4:
                return UUID(data)
        except ValueError:
            pass  # Не UUID, возвращаем как строку
        return data
    return data


class BrokerTaskProxy:
    """
    Динамический прокси для отправки операций DataAccessManager (DAM) в Taskiq.
    Перехватывает вызовы методов DAM и делегирует их выполнение асинхронной задаче.
    Вызов метода через этот прокси блокирует выполнение до получения результата
    от воркера или истечения таймаута.
    """

    def __init__(
        self,
        dam_instance: "BaseDataAccessManager",
        model_name: str,
    ):
        self._dam = dam_instance
        self._model_name = model_name
        logger.debug(
            f"BrokerTaskProxy initialized for DAM '{dam_instance.__class__.__name__}' and model '{model_name}'."
        )

    def __getattr__(self, name: str) -> Any:
        """
        Перехватывает доступ к атрибуту (методу) экземпляра DAM.
        Возвращает обертку, которая отправляет задачу в Taskiq, ожидает
        результат и возвращает его.
        """
        try:
            original_method = getattr(self._dam, name)
        except AttributeError:
            logger.error(
                f"Attribute '{name}' not found on DAM '{self._dam.__class__.__name__}'."
            )
            raise AttributeError(
                f"Attribute '{name}' not found on '{self._dam.__class__.__name__}'"
            )

        if not callable(original_method):
            logger.error(
                f"Attribute '{name}' on DAM '{self._dam.__class__.__name__}' is not callable."
            )
            raise AttributeError(
                f"Attribute '{name}' on '{self._dam.__class__.__name__}' is not callable"
            )

        logger.debug(
            f"BrokerProxy: Accessed method '{name}' for model '{self._model_name}'. Returning task kicker and waiter."
        )

        @functools.wraps(original_method)
        async def task_kicker_and_waiter(
            *args: Any, _broker_timeout: int = 30, **kwargs: Any
        ) -> Any:
            """
            Обертка для метода DAM: отправляет задачу, ожидает результат и возвращает его.
            Параметр `_broker_timeout` (в секундах) контролирует время ожидания результата задачи.
            """
            logger.info(
                f"BrokerProxy: Kicking task for DAM method '{self._model_name}.{name}' and waiting (timeout: {_broker_timeout}s)."
            )

            try:
                serialized_args = [_serialize_arg(arg) for arg in args]
                serialized_kwargs = {
                    key: _serialize_arg(value) for key, value in kwargs.items()
                }
            except Exception as e:
                logger.exception(
                    f"BrokerProxy: Error serializing arguments for method '{name}'."
                )
                raise TypeError(
                    f"Failed to serialize arguments for broker task: {e}"
                ) from e

            task_result_handle: Optional[TaskiqResult] = (
                None  # Используем более описательное имя
            )
            try:
                if not hasattr(execute_dam_operation, "kiq"):
                    logger.critical(
                        f"Imported task 'execute_dam_operation' has no '.kiq' method. Taskiq setup issue?"
                    )
                    raise AttributeError(
                        "Imported task 'execute_dam_operation' has no '.kiq' method. Taskiq might not be configured correctly."
                    )

                task_result_handle = await execute_dam_operation.kiq(
                    model_name=self._model_name,
                    method_name=name,
                    serialized_args=serialized_args,
                    serialized_kwargs=serialized_kwargs,
                )
                task_id_str = (
                    task_result_handle.task_id if task_result_handle else "N/A"
                )
                logger.debug(
                    f"BrokerProxy: Task {task_id_str} for '{name}' kicked via .kiq()."
                )

                if not task_result_handle:
                    logger.error(
                        "Broker failed to kick task (task_result_handle is None). This indicates a problem with the broker or task setup."
                    )
                    raise ConfigurationError(
                        "Broker failed to kick task (task_result_handle is None)."
                    )

                logger.debug(
                    f"BrokerProxy: Waiting for result of task {task_result_handle.task_id}..."
                )
                worker_response: TaskiqResult = await task_result_handle.wait_result(
                    timeout=_broker_timeout
                )  # Имя переменной изменено
                logger.debug(
                    f"BrokerProxy: Result received for task {task_result_handle.task_id}."
                )

                if worker_response.is_err:
                    worker_exception = worker_response.error
                    logger.error(
                        f"BrokerProxy: Worker task {task_result_handle.task_id} for '{name}' failed with error: {worker_exception}",
                        exc_info=isinstance(worker_exception, Exception),
                    )
                    if isinstance(worker_exception, Exception):
                        raise CoreSDKError(
                            f"Async task '{name}' execution failed in worker."
                        ) from worker_exception
                    else:
                        raise CoreSDKError(
                            f"Async task '{name}' execution failed in worker with non-exception error: {worker_exception}"
                        )
                else:
                    raw_return_value = worker_response.return_value
                    logger.debug(
                        f"BrokerProxy: Worker task '{name}' successful. Raw return value type: {type(raw_return_value)}"
                    )
                    final_result = _deserialize_broker_result(
                        raw_return_value, self._dam
                    )
                    logger.debug(
                        f"BrokerProxy: Deserialized result type for '{name}': {type(final_result)}"
                    )
                    return final_result

            except TaskiqResultTimeoutError:
                task_id_str = (
                    task_result_handle.task_id if task_result_handle else "N/A"
                )
                logger.error(
                    f"BrokerProxy: Timeout waiting for result for task {task_id_str} (method '{name}')."
                )
                raise TimeoutError(
                    f"Async task '{name}' did not complete within {_broker_timeout} seconds."
                ) from None
            except TaskiqError as e:
                logger.error(
                    f"BrokerProxy: TaskiqError during execution of method '{name}': {e}",
                    exc_info=True,
                )
                raise CoreSDKError(
                    f"Taskiq error during async execution of '{name}': {e}"
                ) from e
            except AttributeError as e:  # Если нет .kiq() или другая ошибка атрибута
                logger.critical(
                    f"BrokerProxy: AttributeError in task_kicker for '{name}': {e}",
                    exc_info=True,
                )
                raise  # Перевыбрасываем, это серьезная ошибка конфигурации
            except Exception as e:
                logger.exception(
                    f"BrokerProxy: Unexpected error in task_kicker for '{name}'."
                )
                raise  # Перевыбрасываем другие неожиданные ошибки

        return task_kicker_and_waiter
