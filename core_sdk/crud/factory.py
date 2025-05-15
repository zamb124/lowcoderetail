# core_sdk/crud/factory.py
import logging
from typing import Type, List, Optional, TypeVar, cast, ClassVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from pydantic import BaseModel, ValidationError, ConfigDict
from sqlmodel import SQLModel

from core_sdk.registry import ModelRegistry, ModelInfo
from core_sdk.data_access import (
    DataAccessManagerFactory,
    get_dam_factory,
    BaseDataAccessManager,
)
from core_sdk.exceptions import ConfigurationError
from core_sdk.filters.base import DefaultFilter
from core_sdk.schemas.pagination import PaginatedResponse  # Для типизации ответа list
from fastapi_filter.contrib.sqlalchemy import (
    Filter as BaseSQLAlchemyFilter,
)  # Базовый класс фильтра

logger = logging.getLogger("core_sdk.crud.factory")

# Общие типы для схем
ReadSchemaType = TypeVar("ReadSchemaType", bound=SQLModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDRouterFactory:
    model_name: str
    model_info: ModelInfo
    model_cls: Type[SQLModel]
    create_schema_cls: Optional[Type[CreateSchemaType]]
    update_schema_cls: Optional[Type[UpdateSchemaType]]
    read_schema_cls: Type[ReadSchemaType]
    filter_cls: Type[
        BaseSQLAlchemyFilter
    ]  # Тип класса фильтра (кастомный или DefaultFilter)

    router: APIRouter

    def __init__(
        self,
        model_name: str,
        prefix: str,
        get_deps: Optional[List[Depends]] = None,
        list_deps: Optional[List[Depends]] = None,
        create_deps: Optional[List[Depends]] = None,
        update_deps: Optional[List[Depends]] = None,
        delete_deps: Optional[List[Depends]] = None,
        tags: Optional[List[str]] = None,
    ):
        self.model_name = model_name
        try:
            self.model_info = ModelRegistry.get_model_info(model_name)
        except ConfigurationError as e:
            logger.error(
                f"CRUDRouterFactory: Failed to get ModelInfo for '{model_name}': {e}"
            )
            raise e

        # Убедимся, что model_cls это SQLModel, если DefaultFilter ожидает это
        if not issubclass(self.model_info.model_cls, SQLModel):
            logger.warning(
                f"Model class {self.model_info.model_cls.__name__} for "
                f"{model_name} is not SQLModel. DefaultFilter might not work as expected."
            )

        self.model_cls = (
            self.model_info.model_cls
        )  # Это может быть PydanticBaseModel или SQLModel
        self.create_schema_cls = self.model_info.create_schema_cls
        self.update_schema_cls = self.model_info.update_schema_cls
        self.read_schema_cls = cast(
            Type[ReadSchemaType], self.model_info.read_schema_cls or self.model_cls
        )

        registered_filter_cls = self.model_info.filter_cls
        if registered_filter_cls and issubclass(
            registered_filter_cls, BaseSQLAlchemyFilter
        ):
            self.filter_cls = registered_filter_cls
            logger.debug(
                f"CRUDRouterFactory for '{model_name}': Using registered filter {self.filter_cls.__name__}"
            )
            if not hasattr(self.filter_cls, "Constants") or not hasattr(
                self.filter_cls.Constants, "model"
            ):
                logger.warning(
                    f"Registered filter {self.filter_cls.__name__} is missing 'Constants.model'. Dynamically adding."
                )

                class TempConstants(
                    self.filter_cls.Constants
                    if hasattr(self.filter_cls, "Constants")
                    else object
                ):
                    model = (
                        self.model_cls
                    )  # Используем self.model_cls, который может быть Pydantic

                self.filter_cls = type(
                    f"{self.filter_cls.__name__}WithModel",
                    (self.filter_cls,),
                    {"Constants": TempConstants},
                )
                try:
                    if hasattr(self.filter_cls, "model_rebuild"):
                        self.filter_cls.model_rebuild(force=True)  # type: ignore
                except Exception:
                    pass
        else:
            if registered_filter_cls:
                logger.warning(
                    f"CRUDRouterFactory for '{model_name}': Registered filter_cls ... Falling back."
                )
            logger.debug(
                f"CRUDRouterFactory for '{model_name}': No valid filter registered, creating DefaultFilter derivative."
            )

            # Убедимся, что self.model_cls для DefaultFilter является SQLModel
            model_for_filter_constants = self.model_cls
            if not issubclass(self.model_cls, SQLModel):
                logger.warning(
                    f"DefaultFilter requires an SQLModel for its Constants.model, but got {self.model_cls.__name__}. DefaultFilter might not work correctly."
                )
                # В этом случае DefaultFilter не сможет построить запросы SQLAlchemy.
                # Можно создать "пустой" SQLModel для Constants, но это не решит проблему фильтрации.
                # Либо DefaultFilter должен быть более гибким или нужен другой базовый фильтр для не-SQLModel.
                # Пока оставляем как есть, но это потенциальная проблема для remote моделей.
                # Для локальных моделей self.model_cls всегда SQLModel.

            search_fields = [
                name
                for name, field_info in model_for_filter_constants.model_fields.items()
                if hasattr(field_info, "annotation")
                and (
                    field_info.annotation is str
                    or field_info.annotation is Optional[str]
                )
            ]

            # 1. Создаем класс Constants "на лету"
            runtime_constants_class_name = f"{self.model_name}RuntimeFilterConstants"
            RuntimeConstantsClass = type(
                runtime_constants_class_name,
                (DefaultFilter.Constants,),
                {
                    "model": model_for_filter_constants,
                    "search_model_fields": search_fields,
                    "__module__": DefaultFilter.Constants.__module__,
                    "__qualname__": f"{DefaultFilter.Constants.__qualname__}.{runtime_constants_class_name}",
                },
            )

            # 2. Создаем класс фильтра "на лету"
            filter_class_name = f"{self.model_name}DefaultCRUDFilter"

            # Определяем атрибуты для нового класса фильтра
            filter_attrs = {
                "Constants": RuntimeConstantsClass,  # Передаем класс Constants
                "__module__": DefaultFilter.__module__,
                "__qualname__": f"{DefaultFilter.__qualname__}.{filter_class_name}",
                "model_config": ConfigDict(
                    populate_by_name=True, extra="allow", arbitrary_types_allowed=True
                ),  # Добавил arbitrary_types_allowed
            }

            # Аннотируем Constants как ClassVar, чтобы Pydantic его не считал полем
            # Это делается путем добавления в __annotations__
            filter_attrs["__annotations__"] = {
                "Constants": ClassVar[Type[RuntimeConstantsClass]]
            }  # type: ignore

            self.filter_cls = type(filter_class_name, (DefaultFilter,), filter_attrs)

            try:
                if hasattr(self.filter_cls, "model_rebuild"):
                    self.filter_cls.model_rebuild(force=True)
            except Exception as e_rebuild:
                logger.warning(
                    f"Could not rebuild dynamically created filter class {self.filter_cls.__name__}: {e_rebuild}"
                )

        # --- Инициализация роутера и добавление маршрутов ---
        self.router = APIRouter(
            prefix=prefix, tags=tags or [model_name.capitalize().replace("_", " ")]
        )

        # Добавляем маршруты, только если для них предоставлены зависимости
        # (None означает, что маршрут не должен быть создан)
        if list_deps is not None:
            self._add_list_route(dependencies=list_deps)
        if get_deps is not None:
            self._add_get_route(dependencies=get_deps)
        if create_deps is not None and self.create_schema_cls:
            self._add_create_route(dependencies=create_deps)
        if update_deps is not None and self.update_schema_cls:
            self._add_update_route(dependencies=update_deps)
        if delete_deps is not None:
            self._add_delete_route(dependencies=delete_deps)

        logger.info(
            f"CRUDRouter for '{self.model_name}' initialized with prefix '{prefix}' and filter '{self.filter_cls.__name__}'."
        )

    def _add_list_route(self, dependencies: List[Depends]):
        # Создаем типизированный PaginatedResponse для response_model
        PaginatedReadSchema = PaginatedResponse[self.read_schema_cls]  # type: ignore

        async def list_items_endpoint(
            dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
            # FastAPI автоматически создаст экземпляр self.filter_cls,
            # заполнив его поля из query-параметров запроса.
            filter_instance: self.filter_cls = Depends(self.filter_cls),  # type: ignore
            cursor: Optional[int] = Query(
                None,
                description="LSN for pagination (for 'asc' next page or 'desc' prev page)",
            ),
            limit: int = Query(
                50, ge=1, le=200, description="Number of items to return"
            ),
            direction: str = Query(
                "asc",
                pattern="^(asc|desc)$",
                description="Pagination direction ('asc' or 'desc')",
            ),
        ):
            logger.debug(
                f"List endpoint for {self.model_name}: Filters received: {filter_instance.model_dump(exclude_none=True)}"
            )
            manager: BaseDataAccessManager = dam_factory.get_manager(self.model_name)
            try:
                # BaseDataAccessManager.list ожидает объект фильтра или словарь
                # Мы передаем объект фильтра, созданный FastAPI
                result_dict = await manager.list(
                    cursor=cursor,
                    limit=limit,
                    filters=filter_instance,  # Передаем объект фильтра
                    direction=direction,  # type: ignore
                )
                return result_dict
            except ValidationError as ve:  # Ошибка валидации фильтра (если Depends(self.filter_cls) не отловил)
                logger.warning(
                    f"Filter validation error for {self.model_name}: {ve.errors()}"
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ve.errors()
                )
            except HTTPException:  # Пробрасываем HTTPException из DAM (например, 422 из-за плохих фильтров)
                raise
            except Exception as e:
                logger.exception(f"Error listing {self.model_name} items: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Internal server error",
                )

        self.router.add_api_route(
            path="",  # Корень относительно префикса роутера
            endpoint=list_items_endpoint,
            methods=["GET"],
            response_model=PaginatedReadSchema,
            summary=f"List {self.model_name} Items",
            description=f"Retrieves a paginated list of {self.model_name} items. "
            f"Supports cursor-based pagination and filtering.",
            dependencies=dependencies,
        )

    def _add_get_route(self, dependencies: List[Depends]):
        async def get_item_endpoint(
            item_id: UUID = Path(
                ..., description=f"The ID of the {self.model_name} to retrieve"
            ),
            dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
        ):
            manager: BaseDataAccessManager = dam_factory.get_manager(self.model_name)
            db_item = await manager.get(item_id)
            if not db_item:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"{self.model_name} not found",
                )
            return db_item

        self.router.add_api_route(
            path="/{item_id}",
            endpoint=get_item_endpoint,
            methods=["GET"],
            response_model=self.read_schema_cls,
            summary=f"Get {self.model_name} by ID",
            dependencies=dependencies,
        )

    def _add_create_route(self, dependencies: List[Depends]):
        if not self.create_schema_cls:  # Проверка, что схема создания определена
            logger.warning(
                f"CRUDRouterFactory: Create route for {self.model_name} skipped (create_schema_cls not defined)."
            )
            return

        async def create_item_endpoint(
            # Тело запроса будет валидироваться по self.create_schema_cls
            data: self.create_schema_cls,  # type: ignore
            dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
        ):
            manager: BaseDataAccessManager = dam_factory.get_manager(self.model_name)
            try:
                # BaseDataAccessManager.create принимает Pydantic схему или словарь
                db_item = await manager.create(data)
                return db_item
            except (
                HTTPException
            ) as e:  # Пробрасываем ошибки из DAM (409 Conflict, 422 Validation)
                raise e
            except Exception as e:
                logger.exception(f"Error creating {self.model_name}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Internal server error during creation.",
                )

        self.router.add_api_route(
            path="",
            endpoint=create_item_endpoint,
            methods=["POST"],
            response_model=self.read_schema_cls,  # Обычно возвращаем Read схему созданного объекта
            status_code=status.HTTP_201_CREATED,
            summary=f"Create New {self.model_name}",
            dependencies=dependencies,
        )

    def _add_update_route(self, dependencies: List[Depends]):
        if not self.update_schema_cls:  # Проверка, что схема обновления определена
            logger.warning(
                f"CRUDRouterFactory: Update route for {self.model_name} skipped (update_schema_cls not defined)."
            )
            return

        async def update_item_endpoint(
            item_id: UUID = Path(
                ..., description=f"The ID of the {self.model_name} to update"
            ),
            data: self.update_schema_cls = None,  # type: ignore
            dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
        ):
            manager: BaseDataAccessManager = dam_factory.get_manager(self.model_name)
            try:
                # BaseDataAccessManager.update принимает ID и Pydantic схему/словарь
                updated_item = await manager.update(item_id, data)
                # manager.update должен выбросить 404, если объект не найден
                return updated_item
            except (
                HTTPException
            ) as e:  # Пробрасываем ошибки из DAM (404 Not Found, 422 Validation)
                raise e
            except Exception as e:
                logger.exception(f"Error updating {self.model_name} {item_id}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Internal server error during update.",
                )

        self.router.add_api_route(
            path="/{item_id}",
            endpoint=update_item_endpoint,
            methods=["PUT"],
            response_model=self.read_schema_cls,  # Возвращаем Read схему обновленного объекта
            summary=f"Update {self.model_name}",
            dependencies=dependencies,
        )

    def _add_delete_route(self, dependencies: List[Depends]):
        async def delete_item_endpoint(
            item_id: UUID = Path(
                ..., description=f"The ID of the {self.model_name} to delete"
            ),
            dam_factory: DataAccessManagerFactory = Depends(get_dam_factory),
        ):
            manager: BaseDataAccessManager = dam_factory.get_manager(self.model_name)
            try:
                success = await manager.delete(item_id)
                # manager.delete должен выбросить 404, если объект не найден, и вернуть bool
                if (
                    not success
                ):  # Это условие может быть избыточным, если DAM всегда выбрасывает 404
                    # Однако, если DAM может вернуть False без исключения при неудаче (не 404), это нужно
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to delete {self.model_name}",
                    )
                # При успешном удалении (success=True), FastAPI автоматически вернет 204 No Content,
                # если функция-обработчик не возвращает тело ответа (None).
                return  # Возврат None или отсутствие return приведет к 204
            except HTTPException as e:  # Пробрасываем 404 из DAM
                raise e
            except Exception as e:
                logger.exception(f"Error deleting {self.model_name} {item_id}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Internal server error during deletion.",
                )

        self.router.add_api_route(
            path="/{item_id}",
            endpoint=delete_item_endpoint,
            methods=["DELETE"],
            status_code=status.HTTP_204_NO_CONTENT,  # Явно указываем статус
            summary=f"Delete {self.model_name}",
            dependencies=dependencies,
            # response_model=None не нужен и не должен быть для 204
        )


# --- Для глобальных настроек из settings (пагинация) ---
# Это должно быть доступно для Query параметров
# Лучше импортировать settings напрямую или передавать значения
# Здесь предполагаем, что settings импортированы в этом модуле (если нужны)
# import core.app.config # Пример, если настройки нужны здесь
# settings_instance = core.app.config.settings
# Если settings не импортированы, используйте значения по умолчанию или сделайте их обязательными параметрами
