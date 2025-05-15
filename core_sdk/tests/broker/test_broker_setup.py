# core_sdk/tests/data_access/test_broker_proxy.py
import pytest
import uuid
from typing import Dict, Any, Optional # Добавил TypeVar
from pydantic import BaseModel as PydanticBaseModel
from unittest import mock
from uuid import UUID
from taskiq import TaskiqError, TaskiqResultTimeoutError

from core_sdk.data_access.broker_proxy import (
    _serialize_arg,
    _deserialize_broker_result,
    BrokerTaskProxy,
)
from core_sdk.broker.tasks import execute_dam_operation
# Используем новые имена дженериков из BaseDataAccessManager
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.exceptions import CoreSDKError

from core_sdk.tests.conftest import Item, ItemCreate, ItemUpdate, ItemRead # Item - SQLModel, ItemRead - Pydantic

pytestmark = pytest.mark.asyncio

# --- Тесты для _serialize_arg (без изменений) ---
# ... (код _serialize_arg тестов) ...
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
# MockDamForDeserialize теперь должен быть типизирован всеми 4 параметрами
# WorkingModelType для него будет ItemRead (Pydantic), так как он имитирует DAM,
# который мог бы быть и Remote, и Local (но для десериализации важен ReadSchema)
class MockDamForDeserialize(BaseDataAccessManager[ItemRead, ItemCreate, ItemUpdate, ItemRead]):
    def __init__(self):
        super().__init__(
            model_name="ItemDeserializeTest",
            model_cls=ItemRead, # WorkingModelType = ItemRead (Pydantic)
            read_schema_cls=ItemRead, # ReadSchemaType = ItemRead (Pydantic)
            create_schema_cls=ItemCreate,
            update_schema_cls=ItemUpdate
        )
    # Заглушки абстрактных методов
    async def list(self, *, cursor: Optional[int] = None, limit: int = 50, filters: Any = None, direction: Any = "asc") -> Dict[str, Any]: return {"items": []} # pragma: no cover
    async def get(self, item_id: UUID) -> Optional[ItemRead]: return None # pragma: no cover
    async def create(self, data: Any) -> ItemRead: return ItemRead(id=uuid.uuid4(), name=getattr(data, "name", "test"), lsn=1) # pragma: no cover
    async def update(self, item_id: UUID, data: Any) -> ItemRead: return ItemRead(id=item_id, name=getattr(data, "name", "updated"), lsn=1) # pragma: no cover
    async def delete(self, item_id: UUID) -> bool: return True # pragma: no cover

# ... (тесты _deserialize_broker_result без изменений, они используют MockDamForDeserialize) ...
def test_deserialize_broker_result_pydantic_sqlmodel(): # Название теста может быть неточным, теперь это Pydantic -> Pydantic
    dam_instance = MockDamForDeserialize()
    item_id_uuid = uuid.uuid4()
    data = {"id": str(item_id_uuid), "name": "Deserialized ItemRead", "lsn": 100, "description": "Test Pydantic"}
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
# MockDamForProxyLocal (если он имитирует Local DAM)
class MockDamForProxyLocal(BaseDataAccessManager[Item, ItemCreate, ItemUpdate, ItemRead]): # WorkingModel = Item (SQLModel), ReadSchema = ItemRead
    def __init__(self, model_name="ProxyTestItemLocal"):
        super().__init__(
            model_name=model_name,
            model_cls=Item, # SQLModel
            read_schema_cls=ItemRead, # Pydantic
            create_schema_cls=ItemCreate,
            update_schema_cls=ItemUpdate
        )
    # Заглушки методов, возвращающие SQLModel (Item)
    async def get(self, item_id: UUID, some_kwarg: str = "default") -> Optional[Item]: return None # pragma: no cover
    async def create(self, data: ItemCreate) -> Item: return Item(id=uuid.uuid4(), name=data.name, lsn=1) # pragma: no cover
    async def list(self, *, cursor: Optional[int] = None, limit: int = 50, filters: Any = None, direction: Any = "asc") -> Dict[str, Any]: return {"items": []} # pragma: no cover
    async def update(self, item_id: UUID, data: Any) -> Item: return Item(id=item_id, name=getattr(data, "name", "updated"), lsn=2) # pragma: no cover
    async def delete(self, item_id: UUID) -> bool: return True # pragma: no cover

@pytest.fixture
def mock_dam_instance_for_proxy_local() -> MockDamForProxyLocal:
    return MockDamForProxyLocal()

@pytest.fixture
def broker_proxy_local(mock_dam_instance_for_proxy_local: MockDamForProxyLocal) -> BrokerTaskProxy:
    return BrokerTaskProxy(
        dam_instance=mock_dam_instance_for_proxy_local, model_name="ProxyTestItemLocal"
    )

# ... (фикстура mock_taskiq_result_factory без изменений) ...
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
            if timeout == 0: raise TaskiqResultTimeoutError()
            if self.is_err:
                if isinstance(self.error, str) and self.error == "TaskiqError": raise TaskiqError()
            return self
    return MockTaskResult

# Тесты для BrokerTaskProxy (test_broker_proxy_method_call_success и др.)
# теперь должны использовать broker_proxy_local, если тестируется вызов локального DAM.
# _deserialize_broker_result будет ожидать словарь (сериализованный SQLModel) от воркера
# и преобразовывать его в ItemRead (Pydantic).

async def test_broker_proxy_local_dam_method_call_success(
        broker_proxy_local: BrokerTaskProxy,
        mock_taskiq_result_factory: type,
        monkeypatch: pytest.MonkeyPatch,
):
    item_id_to_get = uuid.UUID("11111111-1111-1111-1111-111111111111")
    expected_name = "Proxy Get Item from Worker"
    # Воркер выполнит метод DAM (который вернет SQLModel),
    # затем _serialize_arg в execute_dam_operation преобразует SQLModel в dict.
    worker_raw_return_value_dict = {
        "id": str(item_id_to_get), "name": expected_name, "lsn": 1,
        "description": None, "value": None
    }
    mock_result_handle = mock_taskiq_result_factory(return_value=worker_raw_return_value_dict)
    mock_kiq = mock.AsyncMock(return_value=mock_result_handle)
    monkeypatch.setattr(execute_dam_operation, "kiq", mock_kiq)

    # broker_proxy.get вызовет _deserialize_broker_result.
    # _deserialize_broker_result получит worker_raw_return_value_dict и
    # использует read_schema_cls из dam_instance (это ItemRead для MockDamForProxyLocal)
    # для преобразования dict -> ItemRead.
    result_read_schema = await broker_proxy_local.get(item_id_to_get, some_kwarg="via_proxy", _broker_timeout=5) # type: ignore

    mock_kiq.assert_called_once()
    call_args_kwargs = mock_kiq.call_args.kwargs
    assert call_args_kwargs["model_name"] == "ProxyTestItemLocal"
    assert call_args_kwargs["method_name"] == "get"
    assert call_args_kwargs["serialized_args"] == [_serialize_arg(item_id_to_get)]
    assert call_args_kwargs["serialized_kwargs"] == {"some_kwarg": "via_proxy"}
    assert mock_result_handle._wait_result_called

    assert isinstance(result_read_schema, ItemRead)
    assert result_read_schema.name == expected_name
    assert result_read_schema.id == item_id_to_get

# Тесты test_broker_proxy_timeout, test_broker_proxy_worker_returns_error_object,
# test_broker_proxy_wait_result_raises_taskiq_error можно оставить, используя broker_proxy_local.
async def test_broker_proxy_timeout(
        broker_proxy_local: BrokerTaskProxy,
        mock_taskiq_result_factory: type,
        monkeypatch: pytest.MonkeyPatch,
):
    item_id_to_get = uuid.uuid4()
    mock_result_handle = mock_taskiq_result_factory()
    mock_kiq = mock.AsyncMock(return_value=mock_result_handle)
    monkeypatch.setattr(execute_dam_operation, "kiq", mock_kiq)
    with pytest.raises(TimeoutError) as exc_info:
        await broker_proxy_local.get(item_id_to_get, _broker_timeout=0) # type: ignore
    assert "did not complete within 0 seconds" in str(exc_info.value)
    assert mock_result_handle._wait_result_called

async def test_broker_proxy_worker_returns_error_object(
        broker_proxy_local: BrokerTaskProxy,
        mock_taskiq_result_factory: type,
        monkeypatch: pytest.MonkeyPatch,
):
    item_id_to_get = uuid.uuid4()
    worker_exception = ValueError("Worker failed processing!")
    mock_result_handle = mock_taskiq_result_factory(is_err=True, error=worker_exception)
    mock_kiq = mock.AsyncMock(return_value=mock_result_handle)
    monkeypatch.setattr(execute_dam_operation, "kiq", mock_kiq)
    with pytest.raises(CoreSDKError) as exc_info:
        await broker_proxy_local.get(item_id_to_get) # type: ignore
    assert "execution failed in worker" in str(exc_info.value)
    assert exc_info.value.__cause__ is worker_exception
    assert mock_result_handle._wait_result_called

async def test_broker_proxy_wait_result_raises_taskiq_error(
        broker_proxy_local: BrokerTaskProxy,
        mock_taskiq_result_factory: type,
        monkeypatch: pytest.MonkeyPatch,
):
    item_id_to_get = uuid.uuid4()
    mock_result_handle = mock_taskiq_result_factory(is_err=True, error="TaskiqError")
    mock_kiq = mock.AsyncMock(return_value=mock_result_handle)
    monkeypatch.setattr(execute_dam_operation, "kiq", mock_kiq)
    with pytest.raises(CoreSDKError) as exc_info:
        await broker_proxy_local.get(item_id_to_get) # type: ignore
    assert "Taskiq error during async execution" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, TaskiqError)
    assert mock_result_handle._wait_result_called