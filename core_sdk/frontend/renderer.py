# core_sdk/frontend/renderer.py
import uuid
import logging
from typing import Optional, Any, Dict, List, Type, Tuple, cast

from fastapi import Request, HTTPException
from pydantic import (
    BaseModel as PydanticBaseModel,
    ConfigDict,
    Field as PydanticField,
    ValidationError,
    create_model,
)

from core_sdk.data_access import DataAccessManagerFactory
from core_sdk.registry import ModelRegistry, ModelInfo
from core_sdk.exceptions import ConfigurationError, RenderingError
from core_sdk.frontend.templating import get_templates, Jinja2Templates
from core_sdk.schemas.auth_user import AuthenticatedUser

from .field import SDKField, FieldRenderContext
from .types import ComponentMode, FieldState
from .config import DEFAULT_EXCLUDED_FIELDS, STATIC_URL_PATH
import inspect # Для Enum в _load_options SDKField (если переносим)
from enum import Enum # Для Enum в _load_options SDKField (если переносим)

from .utils import get_base_type

logger = logging.getLogger("core_sdk.frontend.renderer")


class RenderContext(PydanticBaseModel):
    model_name: str
    component_mode: ComponentMode
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
    filter_form_id: Optional[str] = None
    table_target_id: Optional[str] = None
    list_view_url: Optional[str] = None
    model_config = ConfigDict(arbitrary_types_allowed=True)


class ViewRenderer:
    def __init__(
        self,
        request: Request,
        model_name: str,
        dam_factory: DataAccessManagerFactory,
        user: Optional[AuthenticatedUser],
        item_id: Optional[uuid.UUID] = None,
        component_mode: ComponentMode = ComponentMode.VIEW_FORM,
        query_params: Optional[Dict[str, Any]] = None,
        field_to_focus: Optional[str] = None,
    ):
        self.request = request
        self.model_name = model_name
        self.dam_factory = dam_factory
        self.user = user
        self.item_id = item_id
        self.component_mode = component_mode
        self.query_params: Dict[str, Any] = (
            query_params if query_params is not None else dict(request.query_params)
        )
        self.field_to_focus = field_to_focus

        self.templates: Jinja2Templates = get_templates()

        try:
            self.model_info: ModelInfo = ModelRegistry.get_model_info(model_name)
        except ConfigurationError as e:
            logger.error(f"ViewRenderer: Model '{model_name}' not found in registry.", exc_info=True)
            raise RenderingError(f"Model '{model_name}' not found in registry.") from e

        self.manager = self.dam_factory.get_manager(model_name, request=self.request)

        self.item_data: Optional[PydanticBaseModel] = None
        self.items_data: Optional[List[PydanticBaseModel]] = None
        self.pagination_info: Optional[Dict[str, Any]] = None
        self.validation_errors: Optional[Dict[str, Any]] = None
        self.extra_context_data: Dict[str, Any] = {}
        self._current_render_context_cache: Optional[RenderContext] = None

        self.effective_can_edit: bool = True
        if self.component_mode == ComponentMode.VIEW_FORM:
            # TODO: user_has_general_edit_permission(self.user, self.model_name, self.item_id)
            pass
        elif self.component_mode == ComponentMode.DELETE_CONFIRM:
            self.effective_can_edit = False

        # TODO: effective_can_create, effective_can_delete - на основе прав
        self.effective_can_create: bool = True
        self.effective_can_delete: bool = bool(self.item_id)


        instance_uuid = uuid.uuid4().hex[:8]
        id_mode_part = self.component_mode.value.lower().replace("_", "-")
        id_item_part = str(item_id) if item_id else ("new" if component_mode == ComponentMode.CREATE_FORM else id_mode_part)
        self.html_id = f"sdk-{model_name.lower()}-{id_item_part}-{id_mode_part}-{instance_uuid}"

        logger.debug(
            f"ViewRenderer initialized for {model_name} "
            f"(ID: {item_id}, ComponentMode: {component_mode.value}, HTML_ID: {self.html_id}, "
            f"FocusField: {field_to_focus}, QueryParams: {self.query_params})"
        )

    @property
    async def current_render_context(self) -> RenderContext:
        if self._current_render_context_cache is None:
            if self.item_data is None and self.component_mode not in [ComponentMode.LIST_TABLE, ComponentMode.LIST_TABLE_ROWS_FRAGMENT, ComponentMode.CREATE_FORM, ComponentMode.FILTER_FORM]:
                await self._load_data()
            elif self.items_data is None and self.component_mode in [ComponentMode.LIST_TABLE, ComponentMode.LIST_TABLE_ROWS_FRAGMENT]:
                await self._load_data()
            elif (self.item_data is None and self.component_mode in [ComponentMode.CREATE_FORM, ComponentMode.FILTER_FORM]):
                await self._load_data()
            self._current_render_context_cache = await self._build_render_context()
        return self._current_render_context_cache

    def _get_schema_for_data_loading(self) -> Type[PydanticBaseModel]:
        current_mode = self.component_mode
        target_schema: Optional[Type[PydanticBaseModel]] = None

        if current_mode == ComponentMode.CREATE_FORM:
            # Для формы создания, self.item_data будет экземпляром create_schema_cls
            target_schema = self.model_info.create_schema_cls
        elif current_mode == ComponentMode.EDIT_FORM:
            # Для формы редактирования, self.item_data должен быть read_schema_cls,
            # так как мы загружаем существующий объект для отображения.
            # Поля для редактирования будут браться из update_schema_cls в _prepare_sdk_fields.
            target_schema = self.model_info.read_schema_cls # <--- ИЗМЕНЕНИЕ
        elif current_mode == ComponentMode.FILTER_FORM:
            filter_schema = self.model_info.filter_cls
            if filter_schema and issubclass(filter_schema, PydanticBaseModel):
                target_schema = filter_schema
        # Для VIEW_FORM, TABLE_CELL, DELETE_CONFIRM и LIST_TABLE* используется read_schema_cls
        if not target_schema:
            target_schema = self.model_info.read_schema_cls

        if not target_schema or not issubclass(target_schema, PydanticBaseModel):
            logger.error(f"Could not determine a valid Pydantic schema for data loading (model '{self.model_name}', mode '{current_mode.value}'). Falling back.")
            # Возвращаем базовую Pydantic модель, чтобы избежать AttributeError, но это признак проблемы.
            return create_model(f"{self.model_name}ErrorFallbackSchema_{current_mode.value}", __base__=PydanticBaseModel)
        return target_schema

    async def _load_data(self):
        if self.item_data is not None and self.component_mode not in [ComponentMode.LIST_TABLE, ComponentMode.LIST_TABLE_ROWS_FRAGMENT]: return
        if self.items_data is not None and self.component_mode in [ComponentMode.LIST_TABLE, ComponentMode.LIST_TABLE_ROWS_FRAGMENT]: return

        logger.debug(f"Loading data via _load_data for {self.model_name} (Mode: {self.component_mode.value})")
        target_schema_for_item_data = self._get_schema_for_data_loading()

        if self.component_mode in [ComponentMode.VIEW_FORM, ComponentMode.EDIT_FORM, ComponentMode.TABLE_CELL, ComponentMode.DELETE_CONFIRM]:
            if not self.item_id: raise RenderingError(f"Item ID required for mode '{self.component_mode.value}'.")
            db_item_sqlmodel = await self.manager.get(self.item_id)
            if not db_item_sqlmodel: raise RenderingError(f"{self.model_name} with ID {self.item_id} not found.", status_code=404)
            try: self.item_data = target_schema_for_item_data.model_validate(db_item_sqlmodel)
            except ValidationError as ve:
                logger.error(f"Failed to validate DB item into {target_schema_for_item_data.__name__} for {self.component_mode.value}: {ve.errors()}", exc_info=True)
                raise RenderingError(f"Data for {self.model_name} could not be prepared.") from ve
        elif self.component_mode == ComponentMode.CREATE_FORM:
            try: self.item_data = target_schema_for_item_data()
            except Exception as e: logger.error(f"Failed to instantiate {target_schema_for_item_data.__name__} for CREATE: {e}", exc_info=True); self.item_data = None
        elif self.component_mode == ComponentMode.FILTER_FORM:
            filter_schema_cls = target_schema_for_item_data
            filter_instance_data = {}
            if hasattr(filter_schema_cls, "model_fields"):
                for field_name in filter_schema_cls.model_fields.keys():
                    if field_name in self.query_params:
                        param_values = self.request.query_params.getlist(field_name)
                        field_type_info = filter_schema_cls.model_fields[field_name].annotation
                        origin_type = getattr(field_type_info, "__origin__", None)
                        if origin_type is list or origin_type is List: filter_instance_data[field_name] = param_values
                        elif param_values: filter_instance_data[field_name] = param_values[0]
            try: self.item_data = filter_schema_cls(**filter_instance_data)
            except ValidationError as ve:
                self.validation_errors = {"_form": [f"Invalid filter params: {err['msg']}" for err in ve.errors()]}
                self.item_data = filter_schema_cls()
        elif self.component_mode in [ComponentMode.LIST_TABLE, ComponentMode.LIST_TABLE_ROWS_FRAGMENT]:
            dam_filters = {k: v for k, v in self.query_params.items() if k not in ["cursor", "limit", "direction"]}
            cursor_str = self.query_params.get("cursor"); cursor = int(cursor_str) if cursor_str and cursor_str.isdigit() else None
            default_limit = 10 if self.component_mode == ComponentMode.LIST_TABLE_ROWS_FRAGMENT else 20
            limit_str = self.query_params.get("limit", str(default_limit)); limit = int(limit_str) if limit_str.isdigit() else default_limit
            direction = self.query_params.get("direction", "asc")
            if direction not in ["asc", "desc"]: direction = "asc"
            pagination_result_from_dam = await self.manager.list(cursor=cursor, limit=limit, filters=dam_filters, direction=direction)
            db_items_sqlmodel_list = pagination_result_from_dam.get("items", [])
            read_schema_for_list = self.model_info.read_schema_cls
            self.items_data = [read_schema_for_list.model_validate(db_item) for db_item in db_items_sqlmodel_list]
            self.pagination_info = {"next_cursor": pagination_result_from_dam.get("next_cursor"), "limit": pagination_result_from_dam.get("limit", limit), "count": pagination_result_from_dam.get("count", len(self.items_data)), "direction": direction}
        logger.debug(f"Data loaded by _load_data: item_data={self.item_data is not None}, items_data_count={len(self.items_data) if self.items_data else 'N/A'}")

    async def _prepare_sdk_fields(self,
                                  parent_ctx_for_sdk_field: "RenderContext",
                                  field_state_override: Optional[FieldState] = None
                                  ) -> List[SDKField]:
        sdk_fields_list: List[SDKField] = []

        # Схема, из которой берем МЕТАДАННЫЕ полей (типы, описания, ui_config)
        schema_for_field_metadata: Type[PydanticBaseModel]

        if self.component_mode in [ComponentMode.LIST_TABLE, ComponentMode.LIST_TABLE_ROWS_FRAGMENT, ComponentMode.VIEW_FORM, ComponentMode.TABLE_CELL, ComponentMode.DELETE_CONFIRM]:
            schema_for_field_metadata = self.model_info.read_schema_cls
        elif self.component_mode == ComponentMode.CREATE_FORM:
            schema_for_field_metadata = self.model_info.create_schema_cls or self.model_info.read_schema_cls
        elif self.component_mode == ComponentMode.EDIT_FORM:
            # Для формы редактирования, поля берем из update_schema_cls
            schema_for_field_metadata = self.model_info.update_schema_cls or self.model_info.read_schema_cls
        elif self.component_mode == ComponentMode.FILTER_FORM:
            schema_for_field_metadata = self.model_info.filter_cls or self.model_info.read_schema_cls # FilterSchema
        else:
            schema_for_field_metadata = self.model_info.read_schema_cls # Fallback

        if not schema_for_field_metadata or not hasattr(schema_for_field_metadata, 'model_fields'):
            logger.error(f"Schema for field metadata is invalid or missing for {self.model_name}, mode {self.component_mode.value}. Schema: {schema_for_field_metadata}")
            return []

        default_field_state_for_component: FieldState
        if self.component_mode in [ComponentMode.EDIT_FORM, ComponentMode.CREATE_FORM, ComponentMode.FILTER_FORM]:
            default_field_state_for_component = FieldState.EDIT
        else:
            default_field_state_for_component = FieldState.VIEW

        # Объект, из которого берем ЗНАЧЕНИЯ полей
        # self.item_data уже должен быть загружен и быть правильного типа (например, ItemRead для EDIT_FORM)
        source_data_object_for_values = self.item_data
        if self.component_mode in [ComponentMode.LIST_TABLE, ComponentMode.LIST_TABLE_ROWS_FRAGMENT]:
            source_data_object_for_values = None # Для списков значения берутся из items в цикле

        if self.component_mode in [ComponentMode.LIST_TABLE, ComponentMode.LIST_TABLE_ROWS_FRAGMENT]:
            # Для списков, source_data_object_for_values не используется здесь,
            # значения будут браться из каждого item в цикле в шаблоне.
            # Мы создаем "прототипы" SDKField на основе read_schema_cls.
            for name, field_info_obj in self.model_info.read_schema_cls.model_fields.items(): # Всегда read_schema_cls для колонок таблицы
                if name in DEFAULT_EXCLUDED_FIELDS and name not in ["created_at", "updated_at"]: continue
                sdk_fields_list.append(SDKField(name, field_info_obj, None, parent_ctx_for_sdk_field, self.component_mode, FieldState.VIEW))

        elif source_data_object_for_values or self.component_mode == ComponentMode.CREATE_FORM:
            current_data_item_for_values = source_data_object_for_values
            if self.component_mode == ComponentMode.CREATE_FORM and not current_data_item_for_values:
                # Если это форма создания и нет item_data (например, при первой загрузке),
                # создаем пустой экземпляр create_schema_cls для получения default значений.
                # schema_for_field_metadata здесь будет create_schema_cls.
                try: current_data_item_for_values = schema_for_field_metadata()
                except Exception: return []

            if not hasattr(current_data_item_for_values, "__dict__") and not isinstance(current_data_item_for_values, PydanticBaseModel):
                logger.warning(f"current_data_item_for_values is not a Pydantic model or dict-like for {self.model_name}, mode {self.component_mode.value}. Type: {type(current_data_item_for_values)}")
                return []


            # Итерируемся по полям схемы, определенной для МЕТАДАННЫХ
            for name, field_info_obj in schema_for_field_metadata.model_fields.items():
                if self.component_mode == ComponentMode.FILTER_FORM:
                    ui_visible = (field_info_obj.json_schema_extra or {}).get("ui_visible", True)
                    if not ui_visible: continue
                elif name in DEFAULT_EXCLUDED_FIELDS and self.component_mode != ComponentMode.CREATE_FORM:
                    # Для CREATE_FORM, если поле есть в create_schema_cls, оно должно быть включено
                    if self.component_mode == ComponentMode.CREATE_FORM and self.model_info.create_schema_cls and name in self.model_info.create_schema_cls.model_fields:
                        pass # Включаем
                    else:
                        continue # Исключаем

                # Получаем значение из current_data_item_for_values
                # current_data_item_for_values это Pydantic модель (например, ItemRead для EDIT_FORM, или ItemCreate для CREATE_FORM)
                value = getattr(current_data_item_for_values, name, field_info_obj.default)

                current_sdk_field_state = field_state_override or default_field_state_for_component
                if self.component_mode == ComponentMode.TABLE_CELL and self.field_to_focus == name and not field_state_override:
                    current_sdk_field_state = FieldState.EDIT

                sdk_fields_list.append(SDKField(name, field_info_obj, value, parent_ctx_for_sdk_field, self.component_mode, current_sdk_field_state))
        else:
            logger.warning(f"No source_data_object_for_values to prepare fields for {self.model_name} in mode {self.component_mode.value}")

        logger.debug(f"Prepared {len(sdk_fields_list)} SDKFields for {self.component_mode.value}. Fields: {[(f.name, f.field_state.value) for f in sdk_fields_list]}")
        return sdk_fields_list

    async def _build_render_context(self, field_state_override: Optional[FieldState] = None) -> RenderContext:
        # Данные (item_data/items_data) должны быть уже загружены через self.current_render_context -> _load_data()

        title_map = {
            ComponentMode.VIEW_FORM: f"{self.model_info.read_schema_cls.__name__}: {getattr(self.item_data, 'name', None) or getattr(self.item_data, 'title', None) or self.item_id or 'Детали'}",
            ComponentMode.EDIT_FORM: f"Редактирование: {self.model_info.read_schema_cls.__name__} ({self.item_id})",
            ComponentMode.CREATE_FORM: f"Создание: {self.model_info.read_schema_cls.__name__}",
            ComponentMode.LIST_TABLE: f"Список: {self.model_info.read_schema_cls.__name__}",
            ComponentMode.FILTER_FORM: f"Фильтры: {self.model_info.read_schema_cls.__name__}",
            ComponentMode.TABLE_CELL: f"Поле: {self.field_to_focus}" if self.field_to_focus else "Ячейка таблицы",
            ComponentMode.DELETE_CONFIRM: f"Удаление: {self.model_info.read_schema_cls.__name__} ({self.item_id})",
        }
        title = title_map.get(self.component_mode, f"{self.component_mode.value.replace('_', ' ').capitalize()} {self.model_name}")

        processed_errors = None
        if self.validation_errors:
            if isinstance(self.validation_errors, list) and self.validation_errors and isinstance(self.validation_errors[0], dict) and "loc" in self.validation_errors[0] and "msg" in self.validation_errors[0]:
                processed_errors = {}
                for error_item in self.validation_errors:
                    loc = error_item.get("loc", []); field_name_key = "_form"
                    if len(loc) > 0:
                        if len(loc) == 1 and loc[0] != "body": field_name_key = str(loc[0])
                        elif len(loc) > 1: field_name_key = str(loc[-1])
                    if field_name_key not in processed_errors: processed_errors[field_name_key] = []
                    processed_errors[field_name_key].append(error_item.get("msg", "Validation error"))
            elif isinstance(self.validation_errors, dict): processed_errors = self.validation_errors
            elif isinstance(self.validation_errors, str): processed_errors = {"_form": [self.validation_errors]}
            elif isinstance(self.validation_errors, list): processed_errors = {"_form": [str(e) for e in self.validation_errors]}
            else: processed_errors = {"_form": ["An unknown error occurred."]}

        filter_form_id_val, list_view_url_val, table_target_id_val = None, None, None
        if self.component_mode in [ComponentMode.LIST_TABLE, ComponentMode.FILTER_FORM, ComponentMode.LIST_TABLE_ROWS_FRAGMENT]:
            filter_form_id_val = f"filter--{self.model_name.lower()}"
            table_target_id_val = f"#table-placeholder-{self.model_name.lower()}"
            try: list_view_url_val = str(self.request.url_for("get_list_table", model_name=self.model_name))
            except Exception: pass

        # Создаем предварительный RenderContext БЕЗ полей
        preliminary_render_ctx = RenderContext(
            model_name=self.model_name,
            component_mode=self.component_mode,
            item_id=self.item_id,
            item=self.item_data,
            items=self.items_data,
            pagination=self.pagination_info,
            fields=[], # Поля будут добавлены ниже
            errors=processed_errors,
            html_id=self.html_id,
            title=title,
            can_edit=self.effective_can_edit,
            can_create=self.effective_can_create,
            can_delete=self.effective_can_delete,
            extra=self.extra_context_data,
            table_key=self.model_name.lower(),
            filter_form_id=filter_form_id_val,
            table_target_id=table_target_id_val,
            list_view_url=list_view_url_val,
        )

        # Готовим SDKField объекты, передавая им preliminary_render_ctx
        sdk_fields = await self._prepare_sdk_fields(
            parent_ctx_for_sdk_field=preliminary_render_ctx,
            field_state_override=field_state_override
        )

        # Преобразуем SDKField в FieldRenderContext и загружаем опции, если нужно
        field_contexts: List[FieldRenderContext] = []
        for sdk_field_instance in sdk_fields:
            if sdk_field_instance.field_state == FieldState.EDIT and \
               sdk_field_instance._determined_field_type in ["select", "relation", "list_relation"]:
                # Эта логика была в SDKField._load_options, теперь она здесь
                if (sdk_field_instance._determined_field_type == "select" and
                        inspect.isclass(get_base_type(sdk_field_instance.field_info.annotation)) and
                        issubclass(get_base_type(sdk_field_instance.field_info.annotation), Enum)):
                    enum_cls = get_base_type(sdk_field_instance.field_info.annotation)
                    sdk_field_instance._loaded_options = [(member.value, member.name) for member in enum_cls]
                elif sdk_field_instance._determined_field_type in ["relation", "list_relation"]:
                    related_model_name = sdk_field_instance.config.get("related_model_name")
                    if related_model_name:
                        try:
                            manager = self.dam_factory.get_manager(related_model_name, request=self.request)
                            results_dict = await manager.list(limit=1000) # TODO: Сделать более умную загрузку
                            items = results_dict.get("items", [])
                            sdk_field_instance._loaded_options = []
                            for item_val_loop in items:
                                item_id_val = getattr(item_val_loop, 'id', None)
                                label = (getattr(item_val_loop, 'title', None) or
                                         getattr(item_val_loop, 'name', None) or
                                         getattr(item_val_loop, 'email', None) or
                                         str(item_id_val))
                                if item_id_val:
                                    sdk_field_instance._loaded_options.append((str(item_id_val), label))
                        except Exception as e:
                            logger.error(f"Failed to load options for {sdk_field_instance.name}: {e}", exc_info=True)
                            sdk_field_instance._loaded_options = []
            field_contexts.append(await sdk_field_instance.get_render_context())

        preliminary_render_ctx.fields = field_contexts
        return preliminary_render_ctx

    async def get_render_context_for_field(self, field_name: str, field_state: FieldState) -> Optional[FieldRenderContext]:
        parent_ctx = await self.current_render_context
        if not self.item_data:
            logger.warning(f"get_render_context_for_field: item_data is None for field {field_name}")
            return None

        schema_for_field_metadata: Type[PydanticBaseModel]
        # Определяем схему для метаданных поля в зависимости от field_state, в котором мы хотим его отрендерить
        if field_state == FieldState.VIEW:
            schema_for_field_metadata = self.model_info.read_schema_cls
        elif field_state == FieldState.EDIT:
            if self.component_mode == ComponentMode.CREATE_FORM:
                schema_for_field_metadata = self.model_info.create_schema_cls or self.model_info.read_schema_cls
            elif self.component_mode == ComponentMode.EDIT_FORM or self.component_mode == ComponentMode.TABLE_CELL: # TABLE_CELL в режиме инлайн-редактирования
                schema_for_field_metadata = self.model_info.update_schema_cls or self.model_info.read_schema_cls
            elif self.component_mode == ComponentMode.FILTER_FORM:
                 schema_for_field_metadata = self.model_info.filter_cls or self.model_info.read_schema_cls # FilterSchema
            else: # VIEW_FORM (если вдруг запросили EDIT состояние для поля в VIEW_FORM)
                schema_for_field_metadata = self.model_info.read_schema_cls
        else: # Неизвестное состояние
             schema_for_field_metadata = self.model_info.read_schema_cls


        if not schema_for_field_metadata or field_name not in schema_for_field_metadata.model_fields:
            logger.warning(f"Field '{field_name}' not found in schema {schema_for_field_metadata.__name__ if schema_for_field_metadata else 'N/A'} for field rendering.")
            return None

        field_info_obj = schema_for_field_metadata.model_fields[field_name]
        # Значение берем из self.item_data, которое соответствует component_mode
        # Если self.item_data это, например, UpdateSchema, а мы рендерим поле, которого нет в UpdateSchema,
        # то getattr вернет default.
        value = getattr(self.item_data, field_name, field_info_obj.default if field_info_obj else None)

        # Создаем SDKField, передавая ему родительский RenderContext (parent_ctx)
        sdk_field = SDKField(field_name, field_info_obj, value, parent_ctx, self.component_mode, field_state)

        # Загружаем опции, если это поле будет в состоянии EDIT и требует их
        if field_state == FieldState.EDIT and sdk_field._determined_field_type in ["select", "relation", "list_relation"]:
            if (sdk_field._determined_field_type == "select" and
                    inspect.isclass(get_base_type(sdk_field.field_info.annotation)) and
                    issubclass(get_base_type(sdk_field.field_info.annotation), Enum)):
                enum_cls = get_base_type(sdk_field.field_info.annotation)
                sdk_field._loaded_options = [(member.value, member.name) for member in enum_cls]
            elif sdk_field._determined_field_type in ["relation", "list_relation"]:
                related_model_name = sdk_field.config.get("related_model_name")
                if related_model_name:
                    try:
                        manager = self.dam_factory.get_manager(related_model_name, request=self.request)
                        results_dict = await manager.list(limit=1000)
                        items = results_dict.get("items", [])
                        sdk_field._loaded_options = []
                        for item_val_loop in items:
                            item_id_val = getattr(item_val_loop, 'id', None)
                            label = (getattr(item_val_loop, 'title', None) or getattr(item_val_loop, 'name', None) or getattr(item_val_loop, 'email', None) or str(item_id_val))
                            if item_id_val: sdk_field._loaded_options.append((str(item_id_val), label))
                    except Exception as e:
                        logger.error(f"Failed to load options for {sdk_field.name} in get_render_context_for_field: {e}", exc_info=True)
                        sdk_field._loaded_options = []

        field_render_ctx = await sdk_field.get_render_context()

        # Добавляем ошибки валидации, если они есть для этого поля
        if self.validation_errors and isinstance(self.validation_errors, dict) and field_name in self.validation_errors:
            field_render_ctx.errors = self.validation_errors[field_name]
        return field_render_ctx

    def get_base_context_for_template(self) -> Dict[str, Any]:
        return {
            "request": self.request,
            "user": self.user,
            "SDK_STATIC_URL": STATIC_URL_PATH,
            "url_for": self.request.url_for,
        }

    async def prepare_response_data(self, field_to_render_name: Optional[str] = None, field_to_render_state: Optional[FieldState] = None) -> Tuple[str, Dict[str, Any]]:
        final_template_name: str
        context_dict: Dict[str, Any] = self.get_base_context_for_template()
        parent_component_render_ctx = await self.current_render_context # Получаем основной RenderContext

        if field_to_render_name and field_to_render_state:
            field_render_ctx = await self.get_render_context_for_field(field_to_render_name, field_to_render_state)
            if not field_render_ctx:
                raise RenderingError(f"Field '{field_to_render_name}' not found for rendering.")
            final_template_name = "components/_field_layout_wrapper.html"
            context_dict["field_ctx"] = field_render_ctx
            context_dict["component_ctx"] = parent_component_render_ctx # Передаем полный RenderContext как component_ctx
            if self.component_mode == ComponentMode.TABLE_CELL: # Контекст родителя - ячейка
                 context_dict["item"] = self.item_data # item_data из рендерера
                 context_dict["model_name"] = self.model_name
        else:
            component_template_map = {
                ComponentMode.VIEW_FORM: "components/view.html",
                ComponentMode.EDIT_FORM: "components/form.html",
                ComponentMode.CREATE_FORM: "components/form.html",
                ComponentMode.DELETE_CONFIRM: "components/_confirm_delete_modal.html",
                ComponentMode.LIST_TABLE: "components/table.html",
                ComponentMode.LIST_TABLE_ROWS_FRAGMENT: "components/_table_rows_fragment.html",
                ComponentMode.FILTER_FORM: "components/_filter_form.html",
            }
            template_name_for_component = component_template_map.get(self.component_mode)
            if not template_name_for_component:
                raise RenderingError(f"Content template for component mode {self.component_mode.value} not defined.")
            final_template_name = template_name_for_component
            if self.component_mode not in [ComponentMode.TABLE_CELL, ComponentMode.LIST_TABLE_ROWS_FRAGMENT]:
                clean_component_template_name = template_name_for_component.split("/")[-1]
                model_specific_template_path = f"components/{self.model_name.lower()}/{clean_component_template_name}"
                try:
                    self.templates.env.get_template(model_specific_template_path)
                    final_template_name = model_specific_template_path
                except Exception: pass
            context_dict["ctx"] = parent_component_render_ctx # ctx это и есть parent_component_render_ctx
            if self.component_mode == ComponentMode.LIST_TABLE_ROWS_FRAGMENT:
                context_dict["items"] = parent_component_render_ctx.items
                context_dict["model_name"] = parent_component_render_ctx.model_name
                context_dict["fields_protos"] = parent_component_render_ctx.fields
            elif self.component_mode == ComponentMode.LIST_TABLE:
                context_dict["items"] = parent_component_render_ctx.items
                context_dict["fields_protos"] = parent_component_render_ctx.fields

        logger.info(f"Renderer for {self.model_name}/{self.component_mode.value}{f' (field: {field_to_render_name}, state: {field_to_render_state.value if field_to_render_state else Nones})' if field_to_render_name else ''}: using template '{final_template_name}'")
        return final_template_name, context_dict

    async def render_to_response(self, status_code: int = 200):
        try:
            template_name, context_dict = await self.prepare_response_data()
            return self.templates.TemplateResponse(template_name, context_dict, status_code=status_code)
        except RenderingError as e:
            logger.error(f"RenderingError in render_to_response for {self.model_name}, mode {self.component_mode.value}: {e}", exc_info=True)
            raise HTTPException(status_code=getattr(e, "status_code", 500), detail=str(e))
        except Exception as e:
            logger.exception(f"Error in render_to_response for {self.model_name}, mode {self.component_mode.value}")
            raise HTTPException(status_code=500, detail=f"Internal server error during rendering: {str(e)}")

    async def render_field_fragment_response(self, field_name: str, field_state: FieldState, status_code: int = 200):
        try:
            template_name, context_dict = await self.prepare_response_data(
                field_to_render_name=field_name,
                field_to_render_state=field_state
            )
            return self.templates.TemplateResponse(template_name, context_dict, status_code=status_code)
        except RenderingError as e:
            logger.error(f"RenderingError in render_field_fragment for {self.model_name}.{field_name} (state: {field_state.value}): {e}", exc_info=True)
            raise HTTPException(status_code=getattr(e, "status_code", 500), detail=str(e))
        except Exception as e:
            logger.exception(f"Error in render_field_fragment for {self.model_name}.{field_name} (state: {field_state.value})")
            raise HTTPException(status_code=500, detail=f"Internal server error rendering field fragment: {str(e)}")