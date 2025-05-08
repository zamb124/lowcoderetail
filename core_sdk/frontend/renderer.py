# core_sdk/frontend/renderer.py
import uuid
import logging
from typing import Optional, Any, Dict, List, Type
from pydantic import BaseModel, Field as PydanticField

from core_sdk.data_access import DataAccessManagerFactory
from core_sdk.registry import ModelRegistry, ModelInfo
from core_sdk.exceptions import ConfigurationError
from core_sdk.schemas.pagination import PaginatedResponse # Для пагинации

from .field import SDKField, FieldRenderContext
from .types import RenderMode
from .config import DEFAULT_EXCLUDED_FIELDS
from .exceptions import RenderingError

logger = logging.getLogger("core_sdk.frontend.renderer")

class RenderContext(BaseModel):
    """Общий контекст для передачи в Jinja шаблон представления."""
    model_name: str
    mode: RenderMode
    item_id: Optional[uuid.UUID] = None
    item: Optional[Any] = None # Pydantic/SQLModel объект
    items: Optional[List[Any]] = None # Список объектов для list mode
    pagination: Optional[Dict[str, Any]] = None # next_cursor, limit, count
    fields: List[FieldRenderContext] = [] # Контексты полей для рендеринга
    actions: List[Dict[str, Any]] = [] # Доступные действия (если есть)
    errors: Optional[Dict] = None
    html_id: str # Уникальный ID для корневого элемента рендера
    title: str # Заголовок для страницы/компонента
    can_edit: bool = True # Пример флага прав доступа
    can_create: bool = True
    can_delete: bool = True
    extra: Dict[str, Any] = {}

    class Config:
        arbitrary_types_allowed = True


class ViewRenderer:
    """
    Отвечает за получение данных модели и подготовку контекста
    для рендеринга HTML представлений (просмотр, форма, список).
    """

    def __init__(
        self,
        request: Any, # FastAPI Request object
        model_name: str,
        dam_factory: DataAccessManagerFactory,
        item_id: Optional[uuid.UUID] = None,
        mode: RenderMode = RenderMode.VIEW,
        query_params: Optional[Dict[str, Any]] = None,
        parent_html_id: Optional[str] = None, # ID родителя для вложенности
        html_name_prefix: Optional[str] = None, # Префикс для имен полей формы
    ):
        self.request = request
        self.model_name = model_name
        self.dam_factory = dam_factory
        self.item_id = item_id
        self.mode = mode
        self.query_params = query_params or {}
        self.parent_html_id = parent_html_id
        self.html_name_prefix = html_name_prefix # e.g., "parent_model[0]"

        try:
            self.model_info: ModelInfo = ModelRegistry.get_model_info(model_name)
        except ConfigurationError as e:
            logger.error(f"Failed to initialize ViewRenderer: {e}")
            raise RenderingError(f"Model '{model_name}' not found in registry.") from e

        self.manager = self.dam_factory.get_manager(model_name)
        self.item: Optional[BaseModel] = None
        self.items: Optional[List[BaseModel]] = None
        self.pagination: Optional[Dict[str, Any]] = None
        self._fields: List[SDKField] = []

        # Уникальный ID для этого экземпляра рендерера
        instance_uuid = uuid.uuid4().hex[:8]
        id_part = str(item_id) if item_id else 'new' if mode == RenderMode.CREATE else 'list'
        self.html_id = f"vf-{model_name}-{id_part}-{instance_uuid}"
        logger.debug(f"ViewRenderer initialized for {model_name} (ID: {item_id}, Mode: {mode}, HTML_ID: {self.html_id})")

    def _get_schema_for_mode(self) -> Type[BaseModel]:
        """Возвращает подходящую схему Pydantic/SQLModel для текущего режима."""
        if self.mode == RenderMode.CREATE and self.model_info.create_schema_cls:
            return self.model_info.create_schema_cls
        if self.mode == RenderMode.EDIT and self.model_info.update_schema_cls:
            return self.model_info.update_schema_cls
        # Для VIEW, LIST, TABLE_CELL используем read_schema или основную модель
        return self.model_info.read_schema_cls or self.model_info.model_cls

    async def _load_data(self):
        """Загружает данные с помощью DAM."""
        logger.debug(f"Loading data for {self.model_name} (ID: {self.item_id}, Mode: {self.mode})")
        if self.mode in [RenderMode.VIEW, RenderMode.EDIT]:
            if not self.item_id:
                raise RenderingError(f"Item ID is required for mode '{self.mode}'.")
            self.item = await self.manager.get(self.item_id)
            if not self.item:
                raise RenderingError(f"{self.model_name} with ID {self.item_id} not found.", status_code=404)
        elif self.mode == RenderMode.CREATE:
            # Создаем пустой экземпляр схемы для формы создания
            schema = self._get_schema_for_mode()
            try:
                self.item = schema() # Вызываем конструктор без аргументов
            except Exception as e:
                 logger.error(f"Failed to instantiate schema {schema.__name__} for create mode: {e}")
                 # Фоллбэк на базовую модель, если схема создания не может быть инстанциирована
                 self.item = self.model_info.model_cls()

        elif self.mode == RenderMode.LIST:
            # TODO: Преобразовать query_params в объект Filter
            filters = self.query_params.get("filters", {}) # Пример
            cursor = self.query_params.get("cursor")
            limit = int(self.query_params.get("limit", 50))
            direction = self.query_params.get("direction", "asc")

            result_dict = await self.manager.list(
                cursor=cursor, limit=limit, filters=filters, direction=direction
            )
            self.items = result_dict.get("items", [])
            self.pagination = {
                "next_cursor": result_dict.get("next_cursor"),
                "limit": result_dict.get("limit"),
                "count": result_dict.get("count"),
            }
        logger.debug("Data loaded successfully.")

    def _prepare_fields(self):
        """Создает экземпляры SDKField для данных объекта."""
        self._fields = []
        schema = self._get_schema_for_mode()
        data_source = self.item # Используем item для VIEW, EDIT, CREATE

        if not data_source:
            logger.warning(f"No data source (item) available to prepare fields for {self.model_name} in mode {self.mode}")
            return

        for name, field_info in schema.model_fields.items():
            if name in DEFAULT_EXCLUDED_FIELDS:
                continue
            # Пропускаем поля, не предназначенные для текущего режима (если есть такая логика)
            # ...

            value = getattr(data_source, name, None)
            self._fields.append(SDKField(name, field_info, value, self, self.mode))

        # TODO: Добавить сортировку полей, если нужно

    async def get_render_context(self) -> RenderContext:
        """Основной метод: загружает данные и возвращает полный контекст для Jinja."""
        try:
            await self._load_data()
            self._prepare_fields()

            field_contexts = []
            for sdk_field in self._fields:
                field_contexts.append(await sdk_field.get_render_context())

            title = f"{self.mode.value.capitalize()} {self.model_name}"
            if self.mode == RenderMode.VIEW and self.item:
                 # Пытаемся получить более осмысленный заголовок из полей объекта
                 display_name = getattr(self.item, 'title', None) or getattr(self.item, 'name', None) or str(self.item_id)
                 title = f"{self.model_name}: {display_name}"
            elif self.mode == RenderMode.LIST:
                 title = f"{self.model_name} List"

            context = RenderContext(
                model_name=self.model_name,
                mode=self.mode,
                item_id=self.item_id,
                item=self.item,
                items=self.items,
                pagination=self.pagination,
                fields=field_contexts,
                actions=[], # TODO: Добавить логику получения действий
                errors=None, # TODO: Добавить передачу ошибок валидации
                html_id=self.html_id,
                title=title,
                can_edit=True, # TODO: Заменить на реальную проверку прав
                can_create=True,
                can_delete=bool(self.item_id and self.mode != RenderMode.CREATE),
                extra={}, # Можно добавить доп. данные
            )
            return context
        except RenderingError as e:
            logger.error(f"RenderingError for {self.model_name} (ID: {self.item_id}, Mode: {self.mode}): {e}")
            raise # Передаем ошибку выше (например, в FastAPI обработчик)
        except Exception as e:
            logger.exception(f"Unexpected error generating render context for {self.model_name} (ID: {self.item_id}, Mode: {self.mode})")
            raise RenderingError(f"Internal error preparing view for {self.model_name}.")

    def get_base_context(self) -> Dict[str, Any]:
         """Возвращает базовый контекст, который может быть полезен дочерним полям."""
         return {
             "model_name": self.model_name,
             "mode": self.mode.value,
             "item_id": self.item_id,
             "parent_html_id": self.html_id,
             # ... другие общие данные ...
         }