# core_sdk/tests/data_access/test_broker_proxy.py
import pytest
import uuid
import json
from typing import List, Dict, Any, Optional, Union, Literal, Mapping # Добавлены Union, Literal, Mapping
from pydantic import BaseModel as PydanticBaseModel, Field as PydanticField
from sqlmodel import SQLModel, Field as SQLModelField
from unittest import mock

from taskiq import TaskiqResult, TaskiqError, TaskiqResultTimeoutError
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter # Для list

from core_sdk.data_access.broker_proxy import (
    _serialize_arg,
    _deserialize_broker_result,
    BrokerTaskProxy,
)
from core_sdk.broker.tasks import execute_dam_operation
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.registry import ModelRegistry
from core_sdk.exceptions import CoreSDKError

from core_sdk.tests.conftest import Item, ItemCreate, ItemUpdate, ItemRead

pytestmark = pytest.mark.asyncio

# --- Тесты для _serialize_arg (без изменений) ---
def test_serialize_arg_primitives():
    assert _serialize_arg(123) == 123
    assert _serialize_arg("hello") == "hello"
    assert _serialize_arg(True) is True
    assert _serialize_arg(None) is None
    assert _serialize_arg(12.34) == 12.34

def test_serialize_arg_uuid():
    uid = uuid.uuid4()
    assert _serialize_arg(uid) == str(uid)

class SimplePydantic(PydanticBaseModel):
    name: str
    age: int

def test_serialize_arg_pydantic_model():
    model = SimplePydantic(name="Test", age=30)
    assert _serialize_arg(model) == {"name": "Test", "age": 30}

def test_serialize_arg_list():
    uid = uuid.uuid4()
    model = SimplePydantic(name="InList", age=25)
    serialized_list = _serialize_arg([1, uid, model, None])
    assert serialized_list == [1, str(uid), {"name": "InList", "age": 25}, None]

def test_serialize_arg_dict():
    uid = uuid.uuid4()
    model = SimplePydantic(name="InDict", age=20)
    serialized_dict = _serialize_arg({"key1": uid, "key2": model, "key3": "simple"})
    assert serialized_dict == {
        "key1": str(uid),
        "key2": {"name": "InDict", "age": 20},
        "key3": "simple",
    }

# --- Тесты для _deserialize_broker_result ---
class MockDamForDeserialize(BaseDataAccessManager[ItemRead, ItemCreate, ItemUpdate]):
    # model_cls в BaseDataAccessManager - это ReadSchema
    # db_model_cls (если бы это был LocalManager) - это SQLModel
    def __init__(self):
        # Для BaseDataAccessManager model_cls должен быть ReadSchema
        super().__init__(model_name="ItemDeserializeTest", model_cls=ItemRead)
        # read_schema здесь не нужен, так как он уже model_cls в BaseManager

    # --- Реализация абстрактных методов ---
    async def list(self, *, cursor: Optional[int] = None, limit: int = 50,
                   filters: Optional[Union[BaseSQLAlchemyFilter, Mapping[str, Any]]] = None,
                   direction: Literal["asc", "desc"] = "asc") -> Dict[str, Any]:
        raise NotImplementedError # pragma: no cover

    async def get(self, item_id: uuid.UUID) -> Optional[ItemRead]:
        raise NotImplementedError # pragma: no cover

    async def create(self, data: Union[ItemCreate, Dict[str, Any]]) -> ItemRead:
        raise NotImplementedError # pragma: no cover

    async def update(self, item_id: uuid.UUID, data: Union[ItemUpdate, Dict[str, Any]]) -> ItemRead:
        raise NotImplementedError # pragma: no cover

    async def delete(self, item_id: uuid.UUID) -> bool:
        raise NotImplementedError # pragma: no cover



def test_deserialize_broker_result_uuid_string():
    dam_instance = MockDamForDeserialize()
    uid_str = str(uuid.uuid4())
    result = _deserialize_broker_result(uid_str, dam_instance)
    assert isinstance(result, uuid.UUID)
    assert result == uuid.UUID(uid_str)

def test_deserialize_broker_result_other_string():
    dam_instance = MockDamForDeserialize()
    result = _deserialize_broker_result("simple_string", dam_instance)
    assert result == "simple_string"

def test_deserialize_broker_result_primitive():
    dam_instance = MockDamForDeserialize()
    assert _deserialize_broker_result(123, dam_instance) == 123
    assert _deserialize_broker_result(None, dam_instance) is None

# --- Тесты для BrokerTaskProxy ---
class MockDamForProxy(BaseDataAccessManager[ItemRead, ItemCreate, ItemUpdate]):
    def __init__(self, model_name="ProxyTestItem"):
        # model_cls для BaseDataAccessManager - это схема чтения
        super().__init__(model_name=model_name, model_cls=ItemRead,
                         create_schema_cls=ItemCreate, update_schema_cls=ItemUpdate)

    # --- Реализация абстрактных методов ---
    async def list(self, *, cursor: Optional[int] = None, limit: int = 50,
                   filters: Optional[Union[BaseSQLAlchemyFilter, Mapping[str, Any]]] = None,
                   direction: Literal["asc", "desc"] = "asc") -> Dict[str, Any]:
        # Этот метод не будет вызван напрямую в юнит-тестах BrokerTaskProxy,
        # но должен быть реализован.
        # Возвращаем структуру, совместимую с PaginatedResponse
        return {"items": [], "next_cursor": None, "limit": limit, "count": 0} # pragma: no cover

    async def get(
        self, item_id: uuid.UUID, some_kwarg: str = "default" # Добавляем some_kwarg для теста
    ) -> Optional[ItemRead]:
        # Этот метод не будет вызван напрямую в юнит-тестах BrokerTaskProxy
        return None # pragma: no cover

    async def create(self, data: Union[ItemCreate, Dict[str, Any]]) -> ItemRead:
        # Этот метод не будет вызван напрямую в юнит-тестах BrokerTaskProxy
        # Убедимся, что data имеет нужный тип для model_dump
        name_val = data.name if isinstance(data, ItemCreate) else data.get("name", "Default Name")
        desc_val = data.description if isinstance(data, ItemCreate) else data.get("description")
        value_val = data.value if isinstance(data, ItemCreate) else data.get("value")

        return ItemRead(
            id=uuid.uuid4(),
            name=name_val, # type: ignore
            description=desc_val, # type: ignore
            value=value_val, # type: ignore
            lsn=2,
        ) # pragma: no cover

    async def update(self, item_id: uuid.UUID, data: Union[ItemUpdate, Dict[str, Any]]) -> ItemRead:
        # Этот метод не будет вызван напрямую в юнит-тестах BrokerTaskProxy
        name_val = data.name if isinstance(data, ItemUpdate) else data.get("name", "Updated Name")
        desc_val = data.description if isinstance(data, ItemUpdate) else data.get("description")
        value_val = data.value if isinstance(data, ItemUpdate) else data.get("value")
        return ItemRead(
            id=item_id,
            name=name_val, # type: ignore
            description=desc_val, # type: ignore
            value=value_val, # type: ignore
            lsn=3
        ) # pragma: no cover

    async def delete(self, item_id: uuid.UUID) -> bool:
        # Этот метод не будет вызван напрямую в юнит-тестах BrokerTaskProxy
        return True # pragma: no cover


@pytest.fixture
def mock_dam_instance_for_proxy() -> MockDamForProxy:
    return MockDamForProxy()

@pytest.fixture
def broker_proxy(mock_dam_instance_for_proxy: MockDamForProxy) -> BrokerTaskProxy:
    return BrokerTaskProxy(
        dam_instance=mock_dam_instance_for_proxy, model_name="ProxyTestItem"
    )

@pytest.fixture
def mock_taskiq_result_factory() -> type:
    class MockTaskResult:
        def __init__(self, return_value=None, is_err=False, error=None, task_id=None):
            self.return_value = return_value
            self.is_err = is_err
            self.error = error
            self.task_id = task_id or str(uuid.uuid4())
            self._wait_result_called = False

        async def wait_result(self, timeout: int = 30):
            self._wait_result_called = True
            if timeout == 0:
                raise TaskiqResultTimeoutError()
            if self.is_err:
                if isinstance(self.error, str) and self.error == "TaskiqError":
                    raise TaskiqError # Добавил сообщение
            return self

    return MockTaskResult

# --- Остальные тесты для BrokerTaskProxy (без изменений) ---
async def test_broker_proxy_method_call_success(
    broker_proxy: BrokerTaskProxy,
    mock_taskiq_result_factory: type,
    monkeypatch: pytest.MonkeyPatch,
):
    item_id_to_get = uuid.UUID("11111111-1111-1111-1111-111111111111")
    expected_name = "Proxy Get Item from Worker"
    worker_raw_return_value = {
        "id": str(item_id_to_get),
        "name": expected_name,
        "lsn": 1,
        "description": None,
        "value": None,
    }
    mock_result_handle = mock_taskiq_result_factory(
        return_value=worker_raw_return_value
    )
    mock_kiq = mock.AsyncMock(return_value=mock_result_handle)
    monkeypatch.setattr(execute_dam_operation, "kiq", mock_kiq)

    result = await broker_proxy.get(
        item_id_to_get, some_kwarg="via_proxy", _broker_timeout=5 # type: ignore
    )

    mock_kiq.assert_called_once()
    call_args_kwargs = mock_kiq.call_args.kwargs
    assert call_args_kwargs["model_name"] == "ProxyTestItem"
    assert call_args_kwargs["method_name"] == "get"
    assert call_args_kwargs["serialized_args"] == [_serialize_arg(item_id_to_get)]
    assert call_args_kwargs["serialized_kwargs"] == {"some_kwarg": "via_proxy"}
    assert mock_result_handle._wait_result_called


async def test_broker_proxy_timeout(
    broker_proxy: BrokerTaskProxy,
    mock_taskiq_result_factory: type,
    monkeypatch: pytest.MonkeyPatch,
):
    item_id_to_get = uuid.uuid4()
    mock_result_handle = mock_taskiq_result_factory()
    mock_kiq = mock.AsyncMock(return_value=mock_result_handle)
    monkeypatch.setattr(execute_dam_operation, "kiq", mock_kiq)

    with pytest.raises(TimeoutError) as exc_info:
        await broker_proxy.get(item_id_to_get, _broker_timeout=0) # type: ignore
    assert "did not complete within 0 seconds" in str(exc_info.value)
    assert mock_result_handle._wait_result_called

async def test_broker_proxy_worker_returns_error_object(
    broker_proxy: BrokerTaskProxy,
    mock_taskiq_result_factory: type,
    monkeypatch: pytest.MonkeyPatch,
):
    item_id_to_get = uuid.uuid4()
    worker_exception = ValueError("Worker failed processing!")
    mock_result_handle = mock_taskiq_result_factory(is_err=True, error=worker_exception)
    mock_kiq = mock.AsyncMock(return_value=mock_result_handle)
    monkeypatch.setattr(execute_dam_operation, "kiq", mock_kiq)

    with pytest.raises(CoreSDKError) as exc_info:
        await broker_proxy.get(item_id_to_get) # type: ignore
    assert "execution failed in worker" in str(exc_info.value)
    assert exc_info.value.__cause__ is worker_exception
    assert mock_result_handle._wait_result_called

async def test_broker_proxy_wait_result_raises_taskiq_error(
    broker_proxy: BrokerTaskProxy,
    mock_taskiq_result_factory: type,
    monkeypatch: pytest.MonkeyPatch,
):
    item_id_to_get = uuid.uuid4()
    mock_result_handle = mock_taskiq_result_factory(is_err=True, error="TaskiqError")
    mock_kiq = mock.AsyncMock(return_value=mock_result_handle)
    monkeypatch.setattr(execute_dam_operation, "kiq", mock_kiq)

    with pytest.raises(CoreSDKError) as exc_info:
        await broker_proxy.get(item_id_to_get) # type: ignore
    assert "Taskiq error during async execution" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, TaskiqError)
    assert mock_result_handle._wait_result_called