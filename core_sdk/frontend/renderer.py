# core_sdk/frontend/renderer.py
import uuid
import logging
from typing import Optional, Any, Dict, List, Type, Tuple

from fastapi import Request, HTTPException
from pydantic import BaseModel, Field as PydanticField, ValidationError, create_model

from core_sdk.data_access import DataAccessManagerFactory
from core_sdk.registry import ModelRegistry, ModelInfo
from core_sdk.exceptions import ConfigurationError, RenderingError
from core_sdk.frontend.templating import get_templates, Jinja2Templates
from core_sdk.schemas.auth_user import AuthenticatedUser

from .field import SDKField, FieldRenderContext
from .types import RenderMode
from .config import DEFAULT_EXCLUDED_FIELDS, STATIC_URL_PATH
from fastapi_filter.contrib.sqlalchemy import Filter as BaseSQLAlchemyFilter # Для проверки типа фильтра

logger = logging.getLogger("core_sdk.frontend.renderer")

class RenderContext(BaseModel): # Без изменений
    model_name: str
    mode: RenderMode
    item_id: Optional[uuid.UUID] = None
    item: Optional[Any] = None
    items: Optional[List[Any]] = None
    pagination: Optional[Dict[str, Any]] = None
    fields: List[FieldRenderContext] = []
    actions: List[Dict[str, Any]] = PydanticField(default_factory=list)
    errors: Optional[Dict[str, Any]] = None
    html_id: str
    title: str
    can_edit: bool = True
    can_create: bool = True
    can_delete: bool = True
    extra: Dict[str, Any] = PydanticField(default_factory=dict)
    table_key: Optional[str] = None
    # --- Новые поля для контекста фильтра ---
    filter_form_id: Optional[str] = None
    table_target_id: Optional[str] = None
    list_view_url: Optional[str] = None


    class Config:
        arbitrary_types_allowed = True


class ViewRenderer:
    def __init__(
            self,
            request: Request,
            model_name: str,
            dam_factory: DataAccessManagerFactory,
            user: Optional[AuthenticatedUser],
            item_id: Optional[uuid.UUID] = None,
            mode: RenderMode = RenderMode.VIEW,
            query_params: Optional[Dict[str, Any]] = None,
            parent_html_id: Optional[str] = None,
            html_name_prefix: Optional[str] = None,
            field_to_focus: Optional[str] = None
    ):
        self.request = request
        self.model_name = model_name
        self.dam_factory = dam_factory
        self.user = user
        self.item_id = item_id # Для FILTER_FORM item_id не используется
        self.mode = mode
        self.query_params: Dict[str, Any] = query_params if query_params is not None else dict(request.query_params)
        self.parent_html_id = parent_html_id
        self.html_name_prefix = html_name_prefix
        self.field_to_focus = field_to_focus
        self.templates: Jinja2Templates = get_templates()

        try:
            self.model_info: ModelInfo = ModelRegistry.get_model_info(model_name)
        except ConfigurationError as e:
            logger.error(f"Failed to initialize ViewRenderer for '{model_name}': {e}")
            raise RenderingError(f"Model '{model_name}' not found in registry.") from e

        # Менеджер основной модели (для LIST, VIEW и т.д.)
        # Для FILTER_FORM он может не использоваться напрямую, но нужен для ModelInfo
        self.manager = self.dam_factory.get_manager(model_name, request=self.request)

        self.item: Optional[BaseModel] = None # Для FILTER_FORM это будет экземпляр схемы фильтра
        self.items: Optional[List[BaseModel]] = None
        self.pagination: Optional[Dict[str, Any]] = None
        self._fields: List[SDKField] = []
        self.errors: Optional[Dict[str, Any]] = None

        instance_uuid = uuid.uuid4().hex[:8]
        id_part = 'filter' if mode == RenderMode.FILTER_FORM else (str(item_id) if item_id else ('new' if mode == RenderMode.CREATE else ('rows' if mode == RenderMode.LIST_ROWS else 'list')))
        self.html_id = f"vf-{model_name}-{id_part}-{instance_uuid}"
        logger.debug(f"ViewRenderer initialized for {model_name} (ID: {item_id}, Mode: {mode}, HTML_ID: {self.html_id}, QueryParams: {self.query_params})")

    def _get_schema_for_mode(self, mode: Optional[RenderMode] = None) -> Type[BaseModel]:
        current_mode = mode or self.mode
        if current_mode == RenderMode.CREATE and self.model_info.create_schema_cls:
            return self.model_info.create_schema_cls
        if current_mode == RenderMode.EDIT and self.model_info.update_schema_cls:
            return self.model_info.update_schema_cls
        if current_mode == RenderMode.FILTER_FORM: # <--- НОВАЯ ЛОГИКА
            filter_schema = self.model_info.filter_cls
            if not filter_schema or not issubclass(filter_schema, BaseModel):
                logger.warning(f"No valid Pydantic filter schema for {self.model_name} in FILTER_FORM mode. Using empty model.")
                # Возвращаем пустую Pydantic модель, чтобы _prepare_fields не упал
                return create_model(f"{self.model_name}EmptyFilter", __base__=BaseModel)
            return filter_schema
        return self.model_info.read_schema_cls or self.model_info.model_cls


    async def _load_data(self):
        logger.debug(f"Loading data for {self.model_name} (ID: {self.item_id}, Mode: {self.mode}) with query_params: {self.query_params}")
        if self.mode in [RenderMode.VIEW, RenderMode.EDIT, RenderMode.TABLE_CELL]:
            # ... (без изменений) ...
            if not self.item_id: raise RenderingError(f"Item ID required for mode '{self.mode}'.")
            if self.item is None: self.item = await self.manager.get(self.item_id)
            if not self.item: raise RenderingError(f"{self.model_name} with ID {self.item_id} not found.", status_code=404)
        elif self.mode == RenderMode.CREATE:
            # ... (без изменений) ...
            if self.item is None:
                schema = self._get_schema_for_mode()
                try: self.item = schema()
                except Exception as e: logger.error(f"Failed to instantiate schema {schema.__name__} for create: {e}"); self.item = self.model_info.model_cls()
        elif self.mode == RenderMode.FILTER_FORM: # <--- НОВАЯ ЛОГИКА
            filter_schema_cls = self._get_schema_for_mode()
            filter_instance_data = {}
            if filter_schema_cls and hasattr(filter_schema_cls, 'model_fields'): # Убедимся, что это Pydantic модель
                for field_name in filter_schema_cls.model_fields.keys():
                    if field_name in self.query_params:
                        param_values = self.request.query_params.getlist(field_name)
                        field_type_info = filter_schema_cls.model_fields[field_name].annotation
                        origin_type = getattr(field_type_info, '__origin__', None)
                        if origin_type is list or origin_type is List:
                            filter_instance_data[field_name] = param_values
                        elif param_values:
                            filter_instance_data[field_name] = param_values[0]
            try:
                self.item = filter_schema_cls(**filter_instance_data) # self.item теперь экземпляр фильтра
            except ValidationError as ve:
                logger.warning(f"Validation error instantiating filter schema {filter_schema_cls.__name__} with query params: {ve.errors()}")
                self.errors = {"_form": [f"Invalid filter parameters: {err['msg']}" for err in ve.errors()]}
                self.item = filter_schema_cls() # Пустой экземпляр при ошибке
            except Exception as e:
                logger.error(f"Error instantiating filter schema {filter_schema_cls.__name__}: {e}")
                self.item = filter_schema_cls() # Пустой экземпляр при ошибке
            logger.debug(f"Filter form instance created: {self.item.model_dump(exclude_none=True) if self.item else 'None'}")

        elif self.mode == RenderMode.LIST or self.mode == RenderMode.LIST_ROWS:
            # ... (без изменений) ...
            dam_filters = { k: v for k, v in self.query_params.items() if k not in ["cursor", "limit", "direction"] }
            cursor_str = self.query_params.get("cursor")
            cursor = int(cursor_str) if cursor_str and cursor_str.isdigit() else None
            default_limit = 10 if self.mode == RenderMode.LIST_ROWS else 50
            limit_str = self.query_params.get("limit", str(default_limit))
            limit = int(limit_str) if limit_str.isdigit() else default_limit
            direction = self.query_params.get("direction", "asc")
            if direction not in ["asc", "desc"]: direction = "asc"
            result_dict = await self.manager.list(cursor=cursor, limit=limit, filters=dam_filters, direction=direction)
            self.items = result_dict.get("items", [])
            next_page_url_for_list_mode = None
            next_cursor_val = result_dict.get("next_cursor")
            if self.mode == RenderMode.LIST and next_cursor_val and self.items:
                try:
                    base_query_params_for_next_page = { "cursor": str(next_cursor_val), "limit": str(limit) }
                    next_page_url_for_list_mode = str(self.request.url_for('get_list_rows', model_name=self.model_name).include_query_params(**base_query_params_for_next_page))
                except Exception as e_url: logger.error(f"Error generating next_page_url for {self.model_name} (LIST mode): {e_url}")
            self.pagination = { "next_cursor": next_cursor_val, "prev_cursor": result_dict.get("prev_cursor"), "limit": result_dict.get("limit", limit), "count": result_dict.get("count", len(self.items) if self.items else 0), "total_count": result_dict.get("total_count"), "next_page_url": next_page_url_for_list_mode, }
        logger.debug(f"Data loaded for {self.mode}: {len(self.items) if self.items else 0} items. Pagination: {self.pagination}")


    def _prepare_fields(self):
        self._fields = []
        schema_to_iterate = self._get_schema_for_mode()

        if self.mode in [RenderMode.LIST, RenderMode.LIST_ROWS]:
            # ... (без изменений) ...
            schema_for_columns = self.model_info.read_schema_cls or self.model_info.model_cls
            for name, field_info_from_schema in schema_for_columns.model_fields.items():
                if name in DEFAULT_EXCLUDED_FIELDS:
                    if name in ["created_at", "updated_at"]: pass
                    else: continue
                self._fields.append(SDKField(name, field_info_from_schema, None, self, RenderMode.TABLE_CELL))
        elif self.mode == RenderMode.FILTER_FORM: # <--- НОВАЯ ЛОГИКА
            if self.item and hasattr(self.item, 'model_fields'): # self.item это экземпляр схемы фильтра
                for name, field_model_info in self.item.model_fields.items():
                    # Пропускаем стандартные поля fastapi-filter, если они не нужны в UI
                    # или если они не помечены как ui_visible
                    is_standard_filter_field = name in ["order_by", "search"]
                    ui_visible = field_model_info.json_schema_extra.get("ui_visible", False) if field_model_info.json_schema_extra else False

                    if is_standard_filter_field and not ui_visible:
                        # Для 'search' делаем исключение, если нет явного ui_visible, считаем его видимым
                        if name == "search" and not field_model_info.json_schema_extra:
                            pass # Показываем search по умолчанию
                        else:
                            continue

                    # Для полей фильтра всегда используем RenderMode.EDIT
                    self._fields.append(SDKField(name, field_model_info, getattr(self.item, name, None), self, RenderMode.EDIT))
            else:
                logger.warning(f"No item (filter schema instance) or model_fields to prepare fields for {self.model_name} in mode {self.mode}")

        elif self.item: # Для VIEW, EDIT, CREATE
            # ... (без изменений) ...
            for name, field_info_from_schema in schema_to_iterate.model_fields.items():
                if name in DEFAULT_EXCLUDED_FIELDS and self.mode != RenderMode.CREATE: continue
                value = getattr(self.item, name, None)
                current_field_mode = RenderMode.TABLE_CELL if self.mode == RenderMode.TABLE_CELL else self.mode
                self._fields.append(SDKField(name, field_info_from_schema, value, self, current_field_mode))
        else:
            logger.warning(f"No data source (item) to prepare fields for {self.model_name} in mode {self.mode}")


    async def get_render_context(self) -> RenderContext: # Без изменений в сигнатуре
        # ... (логика как была, но теперь обрабатывает и FILTER_FORM) ...
        try:
            await self._load_data()
            self._prepare_fields()
            field_contexts_for_main_render = []
            if self.mode != RenderMode.LIST_ROWS: # Для LIST_ROWS поля не нужны в основном контексте
                for sdk_field in self._fields:
                    field_contexts_for_main_render.append(await sdk_field.get_render_context())

            title = f"{self.mode.value.capitalize()} {self.model_name}"
            if self.mode == RenderMode.VIEW and self.item:
                display_name = getattr(self.item, 'title', None) or getattr(self.item, 'name', None) or str(self.item_id)
                title = f"{self.model_name}: {display_name}"
            elif self.mode in [RenderMode.LIST, RenderMode.LIST_ROWS]:
                title = f"Список: {self.model_name}"
            elif self.mode == RenderMode.FILTER_FORM:
                title = f"Фильтры для: {self.model_name}"

            can_edit, can_create, can_delete = True, True, bool(self.item_id and self.mode != RenderMode.CREATE)

            render_ctx_errors = self.errors
            if self.errors and isinstance(self.errors, list) and self.errors and isinstance(self.errors[0], dict):
                processed_errors = {}
                for error_item in self.errors:
                    loc = error_item.get("loc", ["_form"])
                    field_name = loc[-1] if len(loc) > 1 else "_form"
                    if field_name not in processed_errors: processed_errors[field_name] = []
                    processed_errors[field_name].append(error_item.get("msg", "Validation error"))
                render_ctx_errors = processed_errors
            elif self.errors and not isinstance(self.errors, dict):
                render_ctx_errors = {"_form": [str(self.errors)] if isinstance(self.errors, str) else self.errors}

            # --- Дополнительные данные для контекста фильтра ---
            filter_form_id = None
            table_target_id = None
            list_view_url = None
            if self.mode == RenderMode.FILTER_FORM:
                filter_form_id = f"filter--{self.model_name.lower()}"
                table_target_id = f"#table-placeholder-{self.model_name.lower()}"
                try:
                    list_view_url = str(self.request.url_for('get_list_view', model_name=self.model_name))
                except Exception as e_url_filter:
                    logger.error(f"Error generating list_view_url for filter form ({self.model_name}): {e_url_filter}")


            return RenderContext(
                model_name=self.model_name,
                mode=self.mode,
                item_id=self.item_id, item=self.item,
                items=self.items, pagination=self.pagination, fields=field_contexts_for_main_render,
                actions=[], errors=render_ctx_errors, html_id=self.html_id, title=title,
                can_edit=can_edit, can_create=can_create, can_delete=can_delete,
                extra={}, table_key=self.model_name.lower(),
                filter_form_id=filter_form_id, # <--- НОВОЕ
                table_target_id=table_target_id, # <--- НОВОЕ
                list_view_url=list_view_url # <--- НОВОЕ
            )
        except Exception as e:
            logger.exception(f"Unexpected error in get_render_context")
            raise e

    async def get_render_context_for_field(self, field_name: str) -> Optional[FieldRenderContext]: # Без изменений
        # ...
        if not self.item and self.item_id and self.mode in [RenderMode.EDIT, RenderMode.VIEW, RenderMode.TABLE_CELL]: await self._load_data()
        elif not self.item and self.mode == RenderMode.CREATE: await self._load_data()
        # Для FILTER_FORM self.item (экземпляр фильтра) уже должен быть загружен в get_render_context -> _load_data
        elif self.mode == RenderMode.FILTER_FORM and not self.item : await self._load_data()

        if not self.item: return None

        schema = self._get_schema_for_mode(self.mode) # schema будет схемой фильтра для FILTER_FORM
        if field_name not in schema.model_fields: return None

        field_info_from_schema = schema.model_fields[field_name]
        value = getattr(self.item, field_name, None)

        # Для полей фильтра всегда используем RenderMode.EDIT, чтобы получить инпуты
        current_field_mode = RenderMode.EDIT if self.mode == RenderMode.FILTER_FORM else self.mode

        sdk_field = SDKField(field_name, field_info_from_schema, value, self, current_field_mode)
        field_render_ctx = await sdk_field.get_render_context()

        if self.errors and isinstance(self.errors, dict) and field_name in self.errors:
            field_render_ctx.errors = self.errors[field_name]

        return field_render_ctx


    def get_base_context(self) -> Dict[str, Any]: # Без изменений
        return { "request": self.request, "model_name": self.model_name, "mode": self.mode.value, "item_id": self.item_id, "parent_html_id": self.html_id, }

    async def prepare_response_data(self) -> Tuple[str, Dict[str, Any]]:
        render_context_instance = await self.get_render_context()

        base_template_paths = {
            RenderMode.VIEW: "view.html", # Базовый шаблон для просмотра
            RenderMode.EDIT: "_modal_form_wrapper.html",
            RenderMode.CREATE: "_modal_form_wrapper.html",
            RenderMode.LIST: "table.html",
            RenderMode.LIST_ROWS: "_table_rows_fragment.html",
            RenderMode.TABLE_CELL: render_context_instance.fields[0].template_path if render_context_instance.fields else "fields/text_table.html",
            RenderMode.FILTER_FORM: "_filter_form.html",
        }

        base_mode_template_name = base_template_paths.get(self.mode)
        if not base_mode_template_name:
            logger.error(f"No base template defined for mode {self.mode}")
            raise RenderingError(f"Base template for mode {self.mode} not defined.")

        # --- Логика выбора шаблона с учетом модального окна для VIEW ---
        final_template_name = ""
        is_modal_request = self.request.headers.get("HX-Target") == "modal-placeholder"

        if self.mode == RenderMode.VIEW and is_modal_request:
            # Если режим VIEW и запрос на модалку, используем обертку
            # Можно создать отдельный _modal_view_wrapper.html, если он отличается от _modal_form_wrapper.html
            # Для простоты пока используем тот же, что и для форм, но это может потребовать адаптации form.html
            # или создания _view_content_for_modal.html, который будет включаться в _modal_wrapper.html
            # Предположим, что view.html сам по себе подходит для тела модалки.
            # Тогда нам нужен _modal_wrapper.html, который будет включать view.html
            # Давайте создадим _modal_view_wrapper.html для ясности

            # Проверяем специфичный для модели шаблон обертки
            model_specific_modal_view_wrapper = f"components/{self.model_name.lower()}/_modal_view_wrapper.html"
            generic_modal_view_wrapper = "components/_modal_view_wrapper.html" # Новый шаблон
            try:
                self.templates.env.get_template(model_specific_modal_view_wrapper)
                final_template_name = model_specific_modal_view_wrapper
            except Exception:
                final_template_name = generic_modal_view_wrapper
            logger.debug(f"Using modal view wrapper: {final_template_name} for model {self.model_name}, mode {self.mode}")

        elif self.mode == RenderMode.TABLE_CELL:
            final_template_name = base_mode_template_name # Уже полный путь
        else:
            # Стандартная логика выбора (специфичный для модели или общий)
            model_specific_template = f"components/{self.model_name.lower()}/{base_mode_template_name}"
            generic_component_template = f"components/{base_mode_template_name}"
            try:
                self.templates.env.get_template(model_specific_template)
                final_template_name = model_specific_template
            except Exception:
                final_template_name = generic_component_template
            logger.debug(f"Using template: {final_template_name} for model {self.model_name}, mode {self.mode} (specific not found: {model_specific_template if final_template_name == generic_component_template else ''})")

        # ... (остальная часть метода prepare_response_data без изменений) ...
        context_dict = {
            "request": self.request, "user": self.user,
            "SDK_STATIC_URL": STATIC_URL_PATH, "url_for": self.request.url_for
        }
        # ...
        if self.mode == RenderMode.TABLE_CELL:
            # ...
            context_dict.update({
                "field_ctx": render_context_instance.fields[0] if render_context_instance.fields else None,
                "item": render_context_instance.item,
                "model_name": render_context_instance.model_name
            })
        elif self.mode == RenderMode.LIST_ROWS:
            # ...
            context_dict.update({
                "items": render_context_instance.items,
                "model_name": render_context_instance.model_name,
                "ctx": render_context_instance,
                "table_key": render_context_instance.table_key or render_context_instance.model_name.lower()
            })
        else: # VIEW, EDIT, CREATE, LIST, FILTER_FORM
            context_dict["ctx"] = render_context_instance

        return final_template_name, context_dict

    async def render_to_response(self, status_code: int = 200): # Без изменений
        # ...
        try:
            template_name, context_dict = await self.prepare_response_data()
            return self.templates.TemplateResponse(template_name, context_dict, status_code=status_code)
        except RenderingError as e:
            raise HTTPException(status_code=getattr(e, 'status_code', 500), detail=str(e))
        except Exception as e:
            logger.exception(f"Error in render_to_response for {self.model_name}, mode {self.mode}")
            raise HTTPException(status_code=500, detail=f"Internal server error during rendering: {str(e)}")


    async def render_field_to_response(self, field_name: str, status_code: int = 200): # Без изменений
        # ...
        try:
            field_render_ctx = await self.get_render_context_for_field(field_name)
            if not field_render_ctx:
                raise RenderingError(f"Field '{field_name}' not found for rendering.", status_code=404)

            template_name = field_render_ctx.template_path
            if self.mode == RenderMode.EDIT: # Если мы в режиме редактирования поля (inline)
                template_name = "fields/_inline_input_wrapper.html"

            context_dict = {
                "request": self.request, "user": self.user, "SDK_STATIC_URL": STATIC_URL_PATH,
                "url_for": self.request.url_for, "field_ctx": field_render_ctx,
                "item_id": self.item_id, "model_name": self.model_name, "item": self.item
            }
            return self.templates.TemplateResponse(template_name, context_dict, status_code=status_code)
        except RenderingError as e:
            raise HTTPException(status_code=getattr(e, 'status_code', 500), detail=str(e))
        except Exception as e:
            logger.exception(f"Error in render_field_to_response for {self.model_name}.{field_name}")
            raise HTTPException(status_code=500, detail=f"Internal server error rendering field: {str(e)}")