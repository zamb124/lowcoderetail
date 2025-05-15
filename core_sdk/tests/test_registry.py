# core_sdk/tests/registry/test_registry.py
import pytest
from unittest import mock
from typing import Optional, Any, ClassVar, Dict

from pydantic import (
    BaseModel as PydanticBaseModel,
    HttpUrl,
    ConfigDict,
)
from sqlmodel import SQLModel, Field as SQLModelField
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter

from core_sdk.registry import ModelRegistry, ModelInfo, RemoteConfig
from core_sdk.exceptions import ConfigurationError
# Используем новые имена дженериков
from core_sdk.data_access import LocalDataAccessManager
from core_sdk.data_access import RemoteDataAccessManager


# --- Вспомогательные классы для тестов ---
class RegTestModel(SQLModel, table=True): # Это DM_SQLModelType
    __tablename__ = "reg_test_model_sdk_registry_v4" # Обновил имя
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    name: str

class RegTestPydanticSchema(PydanticBaseModel): # Это DM_ReadSchemaType
    name: str
    value: int
    model_config = ConfigDict(extra="allow")

class RegTestCreateSchema(RegTestPydanticSchema): # Это DM_CreateSchemaType
    pass

class RegTestUpdateSchema(PydanticBaseModel): # Это DM_UpdateSchemaType
    name: Optional[str] = None
    model_config = ConfigDict(extra="allow")

# RegTestReadSchema теперь должна быть Pydantic моделью, а не SQLModel
class RegTestReadSchema(PydanticBaseModel): # Это DM_ReadSchemaType
    id: Optional[int] = None # Если id есть в SQLModel
    name: str
    model_config = ConfigDict(from_attributes=True) # Для SQLModel -> Pydantic

class RegTestFilter(BaseSQLAlchemyFilter):
    name: Optional[str] = None
    class Constants:
        model = RegTestModel

# RegTestManager теперь должен быть типизирован правильно
class RegTestManager(LocalDataAccessManager[RegTestModel, RegTestCreateSchema, RegTestUpdateSchema, RegTestReadSchema]):
    # Заглушки для абстрактных методов, если они не реализованы в LocalDataAccessManager (хотя должны быть)
    async def get(self, item_id: Any) -> Optional[RegTestModel]: return None # type: ignore
    async def list(self, *args: Any, **kwargs: Any) -> Dict[str, Any]: return {"items":[]}
    async def create(self, data: Any) -> RegTestModel: return RegTestModel(name="created") # type: ignore
    async def update(self, item_id: Any, data: Any) -> RegTestModel: return RegTestModel(id=item_id, name="updated") # type: ignore
    async def delete(self, item_id: Any) -> bool: return True

class AnotherManager(LocalDataAccessManager[RegTestModel, RegTestCreateSchema, RegTestUpdateSchema, RegTestReadSchema]):
    async def get(self, item_id: Any) -> Optional[RegTestModel]: return None # type: ignore
    async def list(self, *args: Any, **kwargs: Any) -> Dict[str, Any]: return {"items":[]}
    async def create(self, data: Any) -> RegTestModel: return RegTestModel(name="created") # type: ignore
    async def update(self, item_id: Any, data: Any) -> RegTestModel: return RegTestModel(id=item_id, name="updated") # type: ignore
    async def delete(self, item_id: Any) -> bool: return True


@pytest.fixture(autouse=True)
def clear_registry_fixture():
    ModelRegistry.clear()
    yield
    ModelRegistry.clear()

def test_registry_initial_state():
    assert not ModelRegistry._registry
    assert ModelRegistry._is_configured is False
    assert ModelRegistry.is_configured() is False

def test_register_sets_configured_flag():
    # ИЗМЕНЕНИЕ: Добавляем read_schema_cls
    ModelRegistry.register_local(model_cls=RegTestModel, read_schema_cls=RegTestReadSchema, manager_cls=RegTestManager)
    assert ModelRegistry.is_configured() is True

def test_register_local_success_with_all_params():
    ModelRegistry.register_local(
        model_name="MyItem",
        model_cls=RegTestModel, # SQLModel
        read_schema_cls=RegTestReadSchema, # Pydantic ReadSchema
        manager_cls=RegTestManager,
        create_schema_cls=RegTestCreateSchema,
        update_schema_cls=RegTestUpdateSchema,
        filter_cls=RegTestFilter,
    )
    info = ModelRegistry.get_model_info("MyItem")
    assert isinstance(info, ModelInfo)
    assert info.model_cls is RegTestModel
    assert info.read_schema_cls is RegTestReadSchema
    assert info.manager_cls is RegTestManager
    assert info.create_schema_cls is RegTestCreateSchema
    assert info.update_schema_cls is RegTestUpdateSchema
    assert info.filter_cls is RegTestFilter
    assert info.access_config == "local"

def test_register_local_defaults():
    # ИЗМЕНЕНИЕ: Добавляем read_schema_cls
    ModelRegistry.register_local(model_cls=RegTestModel, read_schema_cls=RegTestReadSchema)
    model_key_for_get = RegTestModel.__name__
    info = ModelRegistry.get_model_info(model_key_for_get)
    assert info.model_cls is RegTestModel
    assert info.read_schema_cls is RegTestReadSchema # Должна быть RegTestReadSchema
    assert info.manager_cls is LocalDataAccessManager # По умолчанию
    assert info.create_schema_cls is None
    assert info.update_schema_cls is None
    assert info.filter_cls is None

def test_register_remote_success():
    remote_conf = RemoteConfig(
        service_url=HttpUrl("http://test.com"), model_endpoint="/api/items"
    )
    # ИЗМЕНЕНИЕ: Убираем read_schema_cls из вызова register_remote,
    # так как model_cls для remote это и есть read_schema_cls.
    ModelRegistry.register_remote(
        model_name="MyRemoteItem",
        model_cls=RegTestPydanticSchema, # Это Pydantic схема (используется как ReadSchema)
        config=remote_conf,
        create_schema_cls=RegTestCreateSchema,
        update_schema_cls=RegTestUpdateSchema,
        # filter_cls можно оставить, если он совместим
    )
    info = ModelRegistry.get_model_info("MyRemoteItem")
    assert info.model_cls is RegTestPydanticSchema
    assert info.read_schema_cls is RegTestPydanticSchema # Должен быть таким же, как model_cls
    assert info.manager_cls is RemoteDataAccessManager # По умолчанию
    assert info.access_config is remote_conf

def test_register_overwrites_existing_with_warning(caplog):
    # ИЗМЕНЕНИЕ: Добавляем read_schema_cls
    ModelRegistry.register_local(
        model_name="Item", model_cls=RegTestModel, read_schema_cls=RegTestReadSchema, manager_cls=RegTestManager
    )
    ModelRegistry.register_local(
        model_name="Item", model_cls=RegTestModel, read_schema_cls=RegTestReadSchema, manager_cls=AnotherManager
    )

    assert " is already registered" in caplog.text.lower()
    info = ModelRegistry.get_model_info("Item")
    assert info.manager_cls is AnotherManager

def test_get_model_info_success():
    # ИЗМЕНЕНИЕ: Добавляем read_schema_cls
    ModelRegistry.register_local(model_name="TestGet", model_cls=RegTestModel, read_schema_cls=RegTestReadSchema)
    info_orig_case = ModelRegistry.get_model_info("TestGet")
    assert info_orig_case is not None
    assert info_orig_case.model_cls is RegTestModel

    info_lower_case = ModelRegistry.get_model_info("testget")
    assert info_lower_case is info_orig_case

def test_get_model_info_not_configured_raises_error():
    ModelRegistry.clear()
    with pytest.raises(
        ConfigurationError, match="ModelRegistry has not been configured"
    ):
        ModelRegistry.get_model_info("AnyModel")

# --- Тесты для rebuild_models ---
# RebuildableSQLModel и RebuildableFilter должны быть Pydantic моделями для model_rebuild
class RebuildablePydanticForRebuild(PydanticBaseModel):
    model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="PydanticRebuildMockForRebuild")
    model_config = ConfigDict(extra="allow")

class RebuildableSQLModelForRebuild(SQLModel, RebuildablePydanticForRebuild): # Наследуем от Pydantic с моком
    model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="SQLModelRebuildMockForRebuild")
    id: Optional[int] = None

class RebuildableFilterForRebuild(BaseSQLAlchemyFilter, RebuildablePydanticForRebuild):
    model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="FilterRebuildMockForRebuild")
    class Constants:
        model = RebuildableSQLModelForRebuild

def test_rebuild_models_calls_model_rebuild_on_schemas():
    RebuildableSQLModelForRebuild.model_rebuild.reset_mock()
    class RebuildCreateSchemaForRebuild(PydanticBaseModel): model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="CreateRebuildMock")
    class RebuildUpdateSchemaForRebuild(PydanticBaseModel): model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="UpdateRebuildMock")
    class RebuildReadSchemaForRebuild(PydanticBaseModel): model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="ReadRebuildMock") # Это должна быть Pydantic модель
    RebuildableFilterForRebuild.model_rebuild.reset_mock()

    ModelRegistry.register( # Используем базовый register для гибкости
        model_name="RebuildTest",
        model_cls=RebuildableSQLModelForRebuild, # SQLModel
        read_schema_cls=RebuildReadSchemaForRebuild, # Pydantic
        access_config="local",
        manager_cls=RegTestManager, # Любой подходящий менеджер
        create_schema_cls=RebuildCreateSchemaForRebuild,
        update_schema_cls=RebuildUpdateSchemaForRebuild,
        filter_cls=RebuildableFilterForRebuild,
    )
    ModelRegistry.rebuild_models(force=True)

    # model_cls (SQLModel) не должен иметь model_rebuild, если он не Pydantic
    # RebuildableSQLModelForRebuild у нас наследуется от Pydantic, поэтому model_rebuild будет вызван
    RebuildableSQLModelForRebuild.model_rebuild.assert_called_once_with(force=True)
    RebuildCreateSchemaForRebuild.model_rebuild.assert_called_once_with(force=True)
    RebuildUpdateSchemaForRebuild.model_rebuild.assert_called_once_with(force=True)
    RebuildReadSchemaForRebuild.model_rebuild.assert_called_once_with(force=True)
    RebuildableFilterForRebuild.model_rebuild.assert_called_once_with(force=True)

def test_rebuild_models_handles_none_schemas():
    RebuildableSQLModelForRebuild.model_rebuild.reset_mock()
    class UnusedPydanticForRebuild(PydanticBaseModel): model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="UnusedPydanticMock")
    UnusedPydanticForRebuild.model_rebuild.reset_mock()

    # ИЗМЕНЕНИЕ: Добавляем read_schema_cls
    ModelRegistry.register_local(
        model_name="RebuildNone",
        model_cls=RebuildableSQLModelForRebuild, # SQLModel
        read_schema_cls=RebuildablePydanticForRebuild # Любая Pydantic схема для чтения
    )

    ModelRegistry.rebuild_models(force=True)
    RebuildableSQLModelForRebuild.model_rebuild.assert_called_once_with(force=True) # Вызывается, т.к. он Pydantic-совместим
    RebuildablePydanticForRebuild.model_rebuild.assert_called_once_with(force=True) # Вызывается для read_schema_cls
    UnusedPydanticForRebuild.model_rebuild.assert_not_called()

def test_rebuild_models_not_configured_logs_warning(caplog):
    ModelRegistry.clear()
    ModelRegistry.rebuild_models()
    assert "Cannot rebuild models: ModelRegistry is not configured" in caplog.text

def test_clear_registry():
    # ИЗМЕНЕНИЕ: Добавляем read_schema_cls
    ModelRegistry.register_local(model_cls=RegTestModel, read_schema_cls=RegTestReadSchema)
    assert ModelRegistry.is_configured() is True
    assert len(ModelRegistry._registry) > 0
    ModelRegistry.clear()
    assert ModelRegistry.is_configured() is False
    assert not ModelRegistry._registry

def test_is_configured():
    assert ModelRegistry.is_configured() is False
    # ИЗМЕНЕНИЕ: Добавляем read_schema_cls
    ModelRegistry.register_local(model_cls=RegTestModel, read_schema_cls=RegTestReadSchema)
    assert ModelRegistry.is_configured() is True