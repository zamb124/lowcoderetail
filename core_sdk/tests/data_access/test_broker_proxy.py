# core_sdk/tests/data_access/test_broker_proxy.py
import pytest
import uuid
import json  # Добавили для json.loads, если понадобится для проверки request.content
from typing import List, Dict, Any, Optional
from pydantic import BaseModel as PydanticBaseModel, Field as PydanticField
from sqlmodel import SQLModel, Field as SQLModelField
from unittest import mock

from taskiq import TaskiqResult, TaskiqError, TaskiqResultTimeoutError

from core_sdk.data_access.broker_proxy import (
    _serialize_arg,
    _deserialize_broker_result,
    BrokerTaskProxy,
)
from core_sdk.broker.tasks import execute_dam_operation
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.registry import (
    ModelRegistry,
)  # Не используется напрямую в этих юнит-тестах, но может быть нужен для интеграционных
from core_sdk.exceptions import CoreSDKError

# Используем тестовые модели из conftest основного data_access
# Убедитесь, что Item.id теперь uuid.UUID в conftest.py
from core_sdk.tests.conftest import Item, ItemCreate, ItemUpdate, ItemRead

pytestmark = pytest.mark.asyncio

# --- Тесты для _serialize_arg ---


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


class MockDamForDeserialize(BaseDataAccessManager):  # type: ignore
    model = Item
    read_schema = ItemRead

    def __init__(self):
        super().__init__(model_name="Item")


def test_deserialize_broker_result_pydantic_sqlmodel():
    dam_instance = MockDamForDeserialize()
    item_id_uuid = uuid.uuid4()
    # Данные, которые приходят от воркера (уже после _serialize_arg там)
    data = {
        "id": str(item_id_uuid),
        "name": "Deserialized ItemRead",
        "lsn": 100,
        "description": "Test SQLModel",
    }
    result = _deserialize_broker_result(data, dam_instance)
    assert isinstance(result, ItemRead)
    assert result.name == "Deserialized ItemRead"
    assert result.id == item_id_uuid


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


# --- Тесты для BrokerTaskProxy ---
class MockDamForProxy(BaseDataAccessManager[Item, ItemCreate, ItemUpdate]):
    model = Item
    create_schema = ItemCreate
    update_schema = ItemUpdate
    read_schema = ItemRead

    def __init__(self, model_name="ProxyTestItem"):
        super().__init__(model_name=model_name)

    async def get(
        self, item_id: uuid.UUID, some_kwarg: str = "default"
    ) -> Optional[ItemRead]:  # pragma: no cover
        # Этот метод не будет вызван напрямую в юнит-тестах BrokerTaskProxy
        return None

    async def create(self, data: ItemCreate) -> ItemRead:  # pragma: no cover
        # Этот метод не будет вызван напрямую в юнит-тестах BrokerTaskProxy
        return ItemRead(
            id=uuid.uuid4(),
            name=data.name,
            description=data.description,
            value=data.value,
            lsn=2,
        )


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
                raise TaskiqResultTimeoutError()  # <--- ИЗМЕНЕНИЕ: без аргумента
            if self.is_err:
                if isinstance(self.error, str) and self.error == "TaskiqError":
                    raise TaskiqError()  # <--- ИЗМЕНЕНИЕ: без аргумента
            return self

    return MockTaskResult


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
        item_id_to_get, some_kwarg="via_proxy", _broker_timeout=5
    )  # type: ignore

    mock_kiq.assert_called_once()
    call_args_kwargs = mock_kiq.call_args.kwargs
    assert call_args_kwargs["model_name"] == "ProxyTestItem"
    assert call_args_kwargs["method_name"] == "get"
    assert call_args_kwargs["serialized_args"] == [_serialize_arg(item_id_to_get)]
    assert call_args_kwargs["serialized_kwargs"] == {"some_kwarg": "via_proxy"}
    assert mock_result_handle._wait_result_called

    assert isinstance(result, ItemRead)
    assert result.name == expected_name
    assert result.id == item_id_to_get


async def test_broker_proxy_timeout(
    broker_proxy: BrokerTaskProxy,
    mock_taskiq_result_factory: type,
    monkeypatch: pytest.MonkeyPatch,
):
    item_id_to_get = uuid.uuid4()
    mock_result_handle = mock_taskiq_result_factory()
    mock_kiq = mock.AsyncMock(return_value=mock_result_handle)
    monkeypatch.setattr(execute_dam_operation, "kiq", mock_kiq)

    with (
        pytest.raises(TimeoutError) as exc_info
    ):  # BrokerTaskProxy преобразует TaskiqResultTimeoutError в TimeoutError
        await broker_proxy.get(item_id_to_get, _broker_timeout=0)  # type: ignore
    assert "did not complete within 0 seconds" in str(
        exc_info.value
    )  # Проверяем сообщение из BrokerTaskProxy
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
        await broker_proxy.get(item_id_to_get)  # type: ignore
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
        await broker_proxy.get(item_id_to_get)  # type: ignore
    assert "Taskiq error during async execution" in str(
        exc_info.value
    )  # Сообщение из BrokerTaskProxy
    assert isinstance(exc_info.value.__cause__, TaskiqError)
    assert mock_result_handle._wait_result_called
