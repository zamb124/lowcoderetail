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

        self.manager = self.dam_factory.get_manager(model_name, request)
        self.item: Optional[BaseModel] = None
        self.items: Optional[List[BaseModel]] = None
        self.pagination: Optional[Dict[str, Any]] = None
        self._fields: List[SDKField] = []

        # Уникальный ID для этого экземпляра рендерера
        instance_uuid = uuid.uuid4().hex[:8]
        id_part = str(item_id) if item_id else 'new' if mode == RenderMode.CREATE else 'list'
        self.html_id = f"vf-{model_name}-{id_part}-{instance_uuid}"
        logger.debug(f"ViewRenderer initialized for {model_name} (ID: {item_id}, Mode: {mode}, HTML_ID: {self.html_id})")

    async def _load_data(self):
        """Загружает данные с помощью DAM."""
        logger.debug(f"Loading data for {self.model_name} (ID: {self.item_id}, Mode: {self.mode})")
        if self.mode in [RenderMode.VIEW, RenderMode.EDIT, RenderMode.TABLE_CELL]: # Добавил TABLE_CELL
            if not self.item_id:
                raise RenderingError(f"Item ID is required for mode '{self.mode}'.")
            self.item = await self.manager.get(self.item_id)
            if not self.item:
                raise RenderingError(f"{self.model_name} with ID {self.item_id} not found.", status_code=404)
        elif self.mode == RenderMode.CREATE:
            schema = self._get_schema_for_mode()
            try: self.item = schema()
            except Exception as e:
                logger.error(f"Failed to instantiate schema {schema.__name__} for create mode: {e}")
                self.item = self.model_info.model_cls()
        elif self.mode == RenderMode.LIST:
            # ... (логика получения filters, cursor, limit, direction из self.query_params) ...
            dam_filters = { k: v for k, v in self.query_params.items() if k not in ["cursor", "limit", "direction"] }
            cursor_str = self.query_params.get("cursor")
            cursor = int(cursor_str) if cursor_str and cursor_str.isdigit() else None
            limit_str = self.query_params.get("limit", "50")
            limit = int(limit_str) if limit_str.isdigit() else 50
            direction = self.query_params.get("direction", "asc")
            if direction not in ["asc", "desc"]: direction = "asc"

            result_dict = await self.manager.list(
                cursor=cursor, limit=limit, filters=dam_filters, direction=direction # type: ignore
            )
            self.items = result_dict.get("items", [])
            self.pagination = {
                "next_cursor": result_dict.get("next_cursor"),
                "prev_cursor": result_dict.get("prev_cursor"),
                "limit": result_dict.get("limit"),
                "count": result_dict.get("count"),
                "total_count": result_dict.get("total_count")
            }
        logger.debug("Data loaded successfully.")

    def _prepare_fields(self):
        """Создает экземпляры SDKField для данных объекта или для прототипов полей списка."""
        self._fields = []
        schema = self._get_schema_for_mode() # Схема для текущего основного режима (VIEW, EDIT, CREATE, LIST)

        if self.mode == RenderMode.LIST:
            # Для режима LIST, self.item не используется для полей.
            # Мы создаем "прототипы" SDKField на основе схемы,
            # а фактические значения будут подставляться в шаблоне _table_row.html.
            # Важно: SDKField для этих прототипов должен быть создан с режимом RenderMode.TABLE_CELL.
            for name, field_info_from_schema in schema.model_fields.items():
                if name in DEFAULT_EXCLUDED_FIELDS: # Общие исключения
                    if name in ["created_at", "updated_at"]:
                        pass # Не пропускаем, если явно указано показывать
                    else:
                        continue
                # Создаем SDKField с режимом TABLE_CELL для корректного template_path
                # value здесь будет None, т.к. это прототип для заголовков/структуры таблицы
                self._fields.append(SDKField(name, field_info_from_schema, None, self, RenderMode.TABLE_CELL))
        elif self.item: # Для режимов VIEW, EDIT, CREATE, TABLE_CELL (когда item_id есть)
            for name, field_info_from_schema in schema.model_fields.items():
                if name in DEFAULT_EXCLUDED_FIELDS and self.mode != RenderMode.CREATE:
                    continue
                value = getattr(self.item, name, None)
                # Для TABLE_CELL (инлайн-редактирование) используем режим TABLE_CELL
                current_field_mode = RenderMode.TABLE_CELL if self.mode == RenderMode.TABLE_CELL else self.mode
                self._fields.append(SDKField(name, field_info_from_schema, value, self, current_field_mode))
        else:
            logger.warning(f"No data source (item) available to prepare fields for {self.model_name} in mode {self.mode}")

    async def get_render_context(self) -> RenderContext:
        try:
            await self._load_data()
            self._prepare_fields() # Этот метод теперь корректно устанавливает режим для полей списка

            field_contexts = []
            for sdk_field in self._fields:
                field_contexts.append(await sdk_field.get_render_context())
            # ... (остальная часть get_render_context как была) ...
            title = f"{self.mode.value.capitalize()} {self.model_name}"
            if self.mode == RenderMode.VIEW and self.item:
                 display_name = getattr(self.item, 'title', None) or getattr(self.item, 'name', None) or str(self.item_id)
                 title = f"{self.model_name}: {display_name}"
            elif self.mode == RenderMode.LIST:
                 title = f"Список: {self.model_name}" # Изменил заголовок для списка

            can_edit = True
            can_create = True
            can_delete = bool(self.item_id and self.mode != RenderMode.CREATE)

            context = RenderContext(
                model_name=self.model_name,
                mode=self.mode,
                item_id=self.item_id,
                item=self.item,
                items=self.items,
                pagination=self.pagination,
                fields=field_contexts, # Теперь эти field_contexts будут иметь правильный template_path для режима LIST (т.е. для ячеек)
                actions=[],
                errors=None,
                html_id=self.html_id,
                title=title,
                can_edit=can_edit,
                can_create=can_create,
                can_delete=can_delete,
                extra={},
            )
            return context
        # ... (обработка ошибок) ...
        except RenderingError as e:
            logger.error(f"RenderingError for {self.model_name} (ID: {self.item_id}, Mode: {self.mode}): {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error generating render context for {self.model_name} (ID: {self.item_id}, Mode: {self.mode})")
            raise RenderingError(f"Internal error preparing view for {self.model_name}.")

    def _get_schema_for_mode(self, mode: Optional[RenderMode] = None) -> Type[BaseModel]:
        current_mode = mode or self.mode
        if current_mode == RenderMode.CREATE and self.model_info.create_schema_cls:
            return self.model_info.create_schema_cls
        if current_mode == RenderMode.EDIT and self.model_info.update_schema_cls:
            return self.model_info.update_schema_cls
        # Для VIEW, LIST, TABLE_CELL используем read_schema или основную модель
        # Для LIST мы будем использовать read_schema для определения полей,
        # но каждый SDKField будет создан с режимом TABLE_CELL.
        return self.model_info.read_schema_cls or self.model_info.model_cls


    def get_base_context(self) -> Dict[str, Any]:
         """Возвращает базовый контекст, который может быть полезен дочерним полям."""
         return {
             "model_name": self.model_name,
             "mode": self.mode.value,
             "item_id": self.item_id,
             "parent_html_id": self.html_id,
             # ... другие общие данные ...
         }

    async def get_render_context_for_field(self, field_name: str) -> Optional[FieldRenderContext]:
        """
        Возвращает FieldRenderContext для конкретного поля в текущем режиме рендерера.
        Если данные для self.item еще не загружены, они будут загружены.
        """
        if not self.item and self.item_id and self.mode in [RenderMode.EDIT, RenderMode.VIEW, RenderMode.TABLE_CELL]:
            await self._load_data() # Загружаем self.item
        elif not self.item and self.mode == RenderMode.CREATE:
            await self._load_data() # Создаст пустой self.item

        if not self.item:
            logger.warning(f"Cannot get field context: item data not loaded for {self.model_name}/{self.item_id}")
            return None

        schema = self._get_schema_for_mode() # Схема для текущего режима рендерера
        if field_name not in schema.model_fields:
            logger.warning(f"Field '{field_name}' not found in schema for mode {self.mode}")
            return None

        field_info_from_schema = schema.model_fields[field_name]
        value = getattr(self.item, field_name, None)

        # Создаем SDKField с текущим режимом рендерера
        sdk_field = SDKField(field_name, field_info_from_schema, value, self, self.mode)
        return await sdk_field.get_render_context()