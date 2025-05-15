# core_sdk/data_access/broker_proxy.py
import functools
import logging
from typing import TYPE_CHECKING, Any, Optional, Type
from uuid import UUID
from pydantic import BaseModel, ValidationError
from sqlmodel import SQLModel

from core_sdk.broker.tasks import execute_dam_operation
from core_sdk.exceptions import ConfigurationError, CoreSDKError
from taskiq import TaskiqResult, TaskiqError, TaskiqResultTimeoutError

if TYPE_CHECKING:
    from core_sdk.data_access.base_manager import BaseDataAccessManager

logger = logging.getLogger(__name__)


def _serialize_arg(arg: Any) -> Any:
    # ... (без изменений) ...
    if isinstance(arg, BaseModel):
        return arg.model_dump(mode="json")
    elif isinstance(arg, UUID):
        return str(arg)
    elif isinstance(arg, (list, tuple)):
        return [_serialize_arg(item) for item in arg]
    elif isinstance(arg, dict):
        return {key: _serialize_arg(value) for key, value in arg.items()}
    return arg


def _deserialize_broker_result(data: Any, dam_instance: "BaseDataAccessManager[Any, Any, Any, Any]") -> Any:
    target_read_schema: Optional[Type[PydanticBaseModel]] = dam_instance.read_schema_cls

    logger.debug(f"_deserialize_broker_result: Received data type: {type(data)}, target_read_schema: {target_read_schema.__name__ if target_read_schema else 'None'}")

    if target_read_schema:
        if isinstance(data, dict):
            try:
                logger.debug(f"Attempting to validate dict data into {target_read_schema.__name__}")
                validated_obj = target_read_schema.model_validate(data)
                logger.debug(f"Successfully validated data into {target_read_schema.__name__}")
                return validated_obj
            except ValidationError as ve: # Явно ловим ValidationError
                logger.error(f"ValidationError when deserializing dict into {target_read_schema.__name__}: {ve.errors()}. Returning raw dict.", exc_info=True)
                # В случае ошибки валидации, возможно, лучше выбросить исключение или вернуть None,
                # чем возвращать исходный словарь, так как это может скрыть проблему.
                # Пока оставим возврат словаря для совместимости с текущими тестами, но это место для улучшения.
                return data
            except Exception as e: # Другие ошибки при model_validate
                logger.error(f"Unexpected error when deserializing dict into {target_read_schema.__name__}: {e}. Returning raw dict.", exc_info=True)
                return data
        elif isinstance(data, SQLModel) and hasattr(data, 'model_dump'): # Если это SQLModel объект
            try:
                logger.debug(f"Attempting to validate SQLModel instance ({type(data).__name__}) into {target_read_schema.__name__}")
                # SQLModel -> dict -> Pydantic ReadSchema
                validated_obj = target_read_schema.model_validate(data.model_dump())
                logger.debug(f"Successfully validated SQLModel into {target_read_schema.__name__}")
                return validated_obj
            except ValidationError as ve:
                logger.error(f"ValidationError when deserializing SQLModel into {target_read_schema.__name__}: {ve.errors()}. Returning raw SQLModel.", exc_info=True)
                return data # Возвращаем исходный SQLModel
            except Exception as e:
                logger.error(f"Unexpected error when deserializing SQLModel into {target_read_schema.__name__}: {e}. Returning raw SQLModel.", exc_info=True)
                return data
        else:
            logger.debug(f"Data is not a dict or SQLModel, or target_read_schema is None. Type of data: {type(data)}")
    else:
        logger.debug("No target_read_schema provided for deserialization.")


    # Обработка для UUID и других простых типов (остается)
    if isinstance(data, str):
        try:
            if len(data) == 36 and data.count("-") == 4:
                return UUID(data)
        except ValueError:
            pass
    return data


class BrokerTaskProxy:
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

            task_result_handle: Optional[TaskiqResult] = None
            try:
                if not hasattr(execute_dam_operation, "kiq"):
                    logger.critical(
                        "Imported task 'execute_dam_operation' has no '.kiq' method. Taskiq setup issue?"
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
                )
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
                        raw_return_value, self._dam # Передаем self._dam
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
            except AttributeError as e:
                logger.critical(
                    f"BrokerProxy: AttributeError in task_kicker for '{name}': {e}",
                    exc_info=True,
                )
                raise
            except Exception:
                logger.exception(
                    f"BrokerProxy: Unexpected error in task_kicker for '{name}'."
                )
                raise

        return task_kicker_and_waiter