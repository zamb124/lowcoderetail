# core_sdk/tests/registry/test_registry.py
import pytest
from unittest import mock
from typing import Type, Optional, Any, ClassVar

from pydantic import (
    BaseModel as PydanticBaseModel,
    HttpUrl,
    Field as PydanticField,
    ValidationError,
    ConfigDict,
)
from sqlmodel import SQLModel, Field as SQLModelField
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter

from core_sdk.registry import ModelRegistry, ModelInfo, RemoteConfig
from core_sdk.exceptions import ConfigurationError
from core_sdk.data_access.base_manager import BaseDataAccessManager
from core_sdk.data_access import LocalDataAccessManager
from core_sdk.data_access import RemoteDataAccessManager


# --- Вспомогательные классы для тестов ---


class RegTestModel(SQLModel, table=True):
    __tablename__ = "reg_test_model_sdk_registry_v3"
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    name: str


class RegTestPydanticSchema(PydanticBaseModel):
    name: str
    value: int
    model_config = ConfigDict(extra="allow")


class RegTestCreateSchema(RegTestPydanticSchema):
    pass


class RegTestUpdateSchema(PydanticBaseModel):
    name: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class RegTestReadSchema(RegTestModel):
    pass


class RegTestFilter(BaseSQLAlchemyFilter):
    name: Optional[str] = None

    class Constants:
        model = RegTestModel


class RegTestManager(BaseDataAccessManager):
    pass  # type: ignore


class AnotherManager(BaseDataAccessManager):
    pass  # type: ignore


# --- Фикстура для очистки реестра ---
@pytest.fixture(autouse=True)
def clear_registry_fixture():
    ModelRegistry.clear()
    yield
    ModelRegistry.clear()


# --- Тесты ---


def test_registry_initial_state():
    assert not ModelRegistry._registry
    assert ModelRegistry._is_configured is False
    assert ModelRegistry.is_configured() is False


def test_register_sets_configured_flag():
    ModelRegistry.register_local(model_cls=RegTestModel, manager_cls=RegTestManager)
    assert ModelRegistry.is_configured() is True


def test_register_local_success_with_all_params():
    ModelRegistry.register_local(
        model_name="MyItem",
        model_cls=RegTestModel,
        manager_cls=RegTestManager,
        create_schema_cls=RegTestCreateSchema,
        update_schema_cls=RegTestUpdateSchema,
        read_schema_cls=RegTestReadSchema,
        filter_cls=RegTestFilter,
    )
    info = ModelRegistry.get_model_info("MyItem")
    assert isinstance(info, ModelInfo)
    assert info.model_cls is RegTestModel
    assert info.manager_cls is RegTestManager
    assert info.create_schema_cls is RegTestCreateSchema
    assert info.update_schema_cls is RegTestUpdateSchema
    assert info.read_schema_cls is RegTestReadSchema
    assert info.filter_cls is RegTestFilter
    assert info.access_config == "local"


def test_register_local_defaults():
    ModelRegistry.register_local(model_cls=RegTestModel)
    model_key_for_get = RegTestModel.__name__
    info = ModelRegistry.get_model_info(model_key_for_get)
    assert info.model_cls is RegTestModel
    assert info.manager_cls is LocalDataAccessManager
    assert info.read_schema_cls is RegTestModel
    assert info.create_schema_cls is None
    assert info.update_schema_cls is None
    assert info.filter_cls is None


def test_register_remote_success():
    remote_conf = RemoteConfig(
        service_url=HttpUrl("http://test.com"), model_endpoint="/api/items"
    )
    ModelRegistry.register_remote(
        model_name="MyRemoteItem",
        model_cls=RegTestPydanticSchema,
        config=remote_conf,
        create_schema_cls=RegTestCreateSchema,
        update_schema_cls=RegTestUpdateSchema,
        read_schema_cls=RegTestPydanticSchema,
    )
    info = ModelRegistry.get_model_info("MyRemoteItem")
    assert info.model_cls is RegTestPydanticSchema
    assert info.manager_cls is RemoteDataAccessManager
    assert info.access_config is remote_conf
    assert info.read_schema_cls is RegTestPydanticSchema


def test_register_overwrites_existing_with_warning(caplog):
    ModelRegistry.register_local(
        model_name="Item", model_cls=RegTestModel, manager_cls=RegTestManager
    )
    ModelRegistry.register_local(
        model_name="Item", model_cls=RegTestModel, manager_cls=AnotherManager
    )

    assert " is already registered" in caplog.text.lower()
    info = ModelRegistry.get_model_info("Item")
    assert info.manager_cls is AnotherManager


def test_get_model_info_success():
    ModelRegistry.register_local(model_name="TestGet", model_cls=RegTestModel)
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


class RebuildablePydantic(PydanticBaseModel):
    # У каждого класса свой мок, чтобы вызовы не смешивались
    model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="PydanticRebuildMock")
    model_config = ConfigDict(extra="allow")


class RebuildableSQLModel(
    SQLModel, RebuildablePydantic
):  # Наследуем от Pydantic с моком
    model_rebuild: ClassVar[mock.Mock] = mock.Mock(
        name="SQLModelRebuildMock"
    )  # <--- СВОЙ МОК
    id: Optional[int] = None


class RebuildableFilter(
    BaseSQLAlchemyFilter, RebuildablePydantic
):  # Фильтр тоже Pydantic
    model_rebuild: ClassVar[mock.Mock] = mock.Mock(
        name="FilterRebuildMock"
    )  # <--- СВОЙ МОК

    class Constants:
        model = RebuildableSQLModel


def test_rebuild_models_calls_model_rebuild_on_schemas():
    # Сбрасываем моки перед использованием
    RebuildableSQLModel.model_rebuild.reset_mock()

    # Создаем отдельные Pydantic классы для create/update/read, чтобы у каждого был свой мок
    class RebuildCreateSchema(PydanticBaseModel):
        model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="CreateRebuildMock")

    class RebuildUpdateSchema(PydanticBaseModel):
        model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="UpdateRebuildMock")

    class RebuildReadSchema(PydanticBaseModel):
        model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="ReadRebuildMock")

    RebuildableFilter.model_rebuild.reset_mock()

    ModelRegistry.register(
        model_name="RebuildTest",
        model_cls=RebuildableSQLModel,
        access_config="local",
        manager_cls=RegTestManager,
        create_schema_cls=RebuildCreateSchema,
        update_schema_cls=RebuildUpdateSchema,
        read_schema_cls=RebuildReadSchema,
        filter_cls=RebuildableFilter,
    )
    ModelRegistry.rebuild_models(force=True)

    RebuildableSQLModel.model_rebuild.assert_called_once_with(force=True)
    RebuildCreateSchema.model_rebuild.assert_called_once_with(force=True)
    RebuildUpdateSchema.model_rebuild.assert_called_once_with(force=True)
    RebuildReadSchema.model_rebuild.assert_called_once_with(force=True)
    RebuildableFilter.model_rebuild.assert_called_once_with(force=True)


def test_rebuild_models_handles_none_schemas():
    RebuildableSQLModel.model_rebuild.reset_mock()

    # Создадим еще один Pydantic класс, чтобы убедиться, что он не вызывается
    class UnusedPydantic(PydanticBaseModel):
        model_rebuild: ClassVar[mock.Mock] = mock.Mock(name="UnusedPydanticMock")

    UnusedPydantic.model_rebuild.reset_mock()

    ModelRegistry.register_local(
        model_name="RebuildNone", model_cls=RebuildableSQLModel
    )

    ModelRegistry.rebuild_models(force=True)
    RebuildableSQLModel.model_rebuild.assert_called_once_with(force=True)
    UnusedPydantic.model_rebuild.assert_not_called()


def test_rebuild_models_not_configured_logs_warning(caplog):
    ModelRegistry.clear()
    ModelRegistry.rebuild_models()
    assert "Cannot rebuild models: ModelRegistry is not configured" in caplog.text


def test_clear_registry():
    ModelRegistry.register_local(model_cls=RegTestModel)
    assert ModelRegistry.is_configured() is True
    assert len(ModelRegistry._registry) > 0
    ModelRegistry.clear()
    assert ModelRegistry.is_configured() is False
    assert not ModelRegistry._registry


def test_is_configured():
    assert ModelRegistry.is_configured() is False
    ModelRegistry.register_local(model_cls=RegTestModel)
    assert ModelRegistry.is_configured() is True
