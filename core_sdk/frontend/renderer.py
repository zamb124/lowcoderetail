# core_sdk/frontend/renderer.py
import uuid
import logging
from typing import Optional, Any, Dict, List, Type, Tuple

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
from .types import RenderMode
from .config import DEFAULT_EXCLUDED_FIELDS, STATIC_URL_PATH

logger = logging.getLogger("core_sdk.frontend.renderer")

# FallbackFormDataModel БОЛЬШЕ НЕ НУЖЕН
# class FallbackFormDataModel(PydanticBaseModel):
#     model_config = ConfigDict(extra='allow')


class RenderContext(PydanticBaseModel):
    model_name: str
    mode: RenderMode
    item_id: Optional[uuid.UUID] = None
    item: Optional[Any] = (
        None  # Теперь это всегда будет экземпляр схемы режима или None
    )
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
        mode: RenderMode = RenderMode.VIEW,
        query_params: Optional[Dict[str, Any]] = None,
        field_to_focus: Optional[str] = None,
    ):
        self.request = request
        self.model_name = model_name
        self.dam_factory = dam_factory
        self.user = user
        self.item_id = item_id
        self.mode = mode
        self.query_params: Dict[str, Any] = (
            query_params if query_params is not None else dict(request.query_params)
        )
        self.field_to_focus = field_to_focus

        self.templates: Jinja2Templates = get_templates()

        try:
            self.model_info: ModelInfo = ModelRegistry.get_model_info(model_name)
        except ConfigurationError as e:
            raise RenderingError(f"Model '{model_name}' not found in registry.") from e

        self.manager = self.dam_factory.get_manager(model_name, request=self.request)

        self.item: Optional[PydanticBaseModel] = (
            None  # Всегда будет экземпляр схемы режима или None
        )
        self.items: Optional[List[PydanticBaseModel]] = None
        self.pagination: Optional[Dict[str, Any]] = None
        self._fields: List[SDKField] = []
        self.errors: Optional[Dict[str, Any]] = None
        self.extra: Dict[str, Any] = {}

        instance_uuid = uuid.uuid4().hex[:8]
        id_mode_part = self.mode.value.lower()
        id_item_part = (
            str(item_id)
            if item_id
            else ("new" if mode == RenderMode.CREATE else id_mode_part)
        )
        self.html_id = (
            f"sdk-{model_name.lower()}-{id_item_part}-{id_mode_part}-{instance_uuid}"
        )

        logger.debug(
            f"ViewRenderer initialized for {model_name} "
            f"(ID: {item_id}, Mode: {mode}, HTML_ID: {self.html_id}, "
            f"FocusField: {field_to_focus}, QueryParams: {self.query_params})"
        )

    def _get_schema_for_mode(
        self, mode: Optional[RenderMode] = None
    ) -> Type[PydanticBaseModel]:
        current_mode = mode or self.mode
        target_schema: Optional[Type[PydanticBaseModel]] = None

        if current_mode == RenderMode.CREATE:
            target_schema = self.model_info.create_schema_cls
        elif current_mode == RenderMode.EDIT:
            target_schema = self.model_info.update_schema_cls
        elif current_mode == RenderMode.FILTER_FORM:
            filter_schema = self.model_info.filter_cls
            if filter_schema and issubclass(filter_schema, PydanticBaseModel):
                target_schema = filter_schema

        if (
            not target_schema
        ):  # Для VIEW, LIST, TABLE_CELL или если специфичная схема не найдена
            target_schema = self.model_info.read_schema_cls or self.model_info.model_cls

        if not target_schema or not issubclass(target_schema, PydanticBaseModel):
            logger.error(
                f"Could not determine a valid Pydantic schema for model '{self.model_name}' in mode '{current_mode.value}'. Falling back to basic BaseModel."
            )
            # Это крайний случай, если даже model_cls не Pydantic модель (что не должно быть для SQLModel)
            return create_model(
                f"{self.model_name}ErrorFallbackSchema", __base__=PydanticBaseModel
            )

        return target_schema

    async def _load_data(self):
        # Этот метод вызывается ТОЛЬКО если self.item (или self.items) ЕЩЕ НЕ УСТАНОВЛЕН.
        # Ручки FastAPI сами установят self.item данными из формы при ошибке валидации.
        if self.item is not None and self.mode not in [
            RenderMode.LIST,
            RenderMode.LIST_ROWS,
        ]:
            logger.debug(
                f"Data already present in self.item for mode {self.mode.value}, skipping _load_data."
            )
            return
        if self.items is not None and self.mode in [
            RenderMode.LIST,
            RenderMode.LIST_ROWS,
        ]:
            logger.debug(
                f"Data already present in self.items for mode {self.mode.value}, skipping _load_data."
            )
            return

        logger.debug(
            f"Loading data via _load_data for {self.model_name} (Mode: {self.mode.value})"
        )

        if self.mode in [RenderMode.VIEW, RenderMode.EDIT, RenderMode.TABLE_CELL]:
            if not self.item_id:
                raise RenderingError(f"Item ID required for mode '{self.mode.value}'.")
            self.item = await self.manager.get(self.item_id)
            if not self.item:
                raise RenderingError(
                    f"{self.model_name} with ID {self.item_id} not found.",
                    status_code=404,
                )

        elif self.mode == RenderMode.CREATE:
            schema = self._get_schema_for_mode()
            try:
                self.item = schema()  # Создаем пустой экземпляр
            except Exception as e:
                logger.error(
                    f"Failed to instantiate schema {schema.__name__} for CREATE mode: {e}"
                )
                # Если не удалось создать даже пустой экземпляр (очень редкий случай для Pydantic)
                # self.item останется None, _prepare_fields обработает это.
                self.item = None

        elif self.mode == RenderMode.FILTER_FORM:
            filter_schema_cls = self._get_schema_for_mode()
            filter_instance_data = {}
            if hasattr(filter_schema_cls, "model_fields"):
                for field_name in filter_schema_cls.model_fields.keys():
                    if field_name in self.query_params:
                        param_values = self.request.query_params.getlist(field_name)
                        # ... (логика извлечения param_values как была) ...
                        field_type_info = filter_schema_cls.model_fields[
                            field_name
                        ].annotation
                        origin_type = getattr(field_type_info, "__origin__", None)
                        if origin_type is list or origin_type is List:
                            filter_instance_data[field_name] = param_values
                        elif param_values:
                            filter_instance_data[field_name] = param_values[0]
            try:
                self.item = filter_schema_cls(**filter_instance_data)
            except ValidationError as ve:
                self.errors = {
                    "_form": [
                        f"Invalid filter params: {err['msg']}" for err in ve.errors()
                    ]
                }
                self.item = (
                    filter_schema_cls()
                )  # Пустой экземпляр при ошибке валидации фильтра

        elif self.mode == RenderMode.LIST or self.mode == RenderMode.LIST_ROWS:
            # ... (логика загрузки self.items и self.pagination как была, с сохранением direction) ...
            dam_filters = {
                k: v
                for k, v in self.query_params.items()
                if k not in ["cursor", "limit", "direction"]
            }
            cursor_str = self.query_params.get("cursor")
            cursor = int(cursor_str) if cursor_str and cursor_str.isdigit() else None
            default_limit = 10 if self.mode == RenderMode.LIST_ROWS else 20
            limit_str = self.query_params.get("limit", str(default_limit))
            limit = int(limit_str) if limit_str.isdigit() else default_limit
            direction = self.query_params.get("direction", "asc")
            if direction not in ["asc", "desc"]:
                direction = "asc"
            _pagination_items = await self.manager.list(
                cursor=cursor, limit=limit, filters=dam_filters, direction=direction
            )
            self.items = _pagination_items.get("items", [])
            return _pagination_items
        logger.debug(
            f"Data loaded by _load_data: item={self.item is not None}, items_count={len(self.items) if self.items else 'N/A'}"
        )

    async def _prepare_fields(self):
        self._fields = []
        # schema_to_get_field_info - это схема, из которой мы берем метаданные полей
        # (title, json_schema_extra, тип аннотации).
        schema_for_field_metadata = self._get_schema_for_mode()

        if self.mode in [RenderMode.LIST, RenderMode.LIST_ROWS]:
            schema_for_columns = (
                self.model_info.read_schema_cls or self.model_info.model_cls
            )
            for name, field_info_obj in schema_for_columns.model_fields.items():
                if name in DEFAULT_EXCLUDED_FIELDS and name not in [
                    "created_at",
                    "updated_at",
                ]:
                    continue
                self._fields.append(
                    SDKField(name, field_info_obj, None, self, RenderMode.TABLE_CELL)
                )

        elif self.mode == RenderMode.TABLE_CELL:
            if self.item and self.field_to_focus:
                # Для ячейки метаданные поля берем из read_schema
                schema_for_cell_metadata = (
                    self.model_info.read_schema_cls or self.model_info.model_cls
                )
                if self.field_to_focus in schema_for_cell_metadata.model_fields:
                    field_info_obj = schema_for_cell_metadata.model_fields[
                        self.field_to_focus
                    ]
                    value = getattr(self.item, self.field_to_focus, None)
                    self._fields.append(
                        SDKField(
                            self.field_to_focus,
                            field_info_obj,
                            value,
                            self,
                            RenderMode.TABLE_CELL,
                        )
                    )
                else:
                    logger.warning(
                        f"Field to focus '{self.field_to_focus}' not in schema for TABLE_CELL."
                    )
            else:
                logger.warning(
                    "Cannot prepare field for TABLE_CELL: item or field_to_focus missing."
                )

        elif self.item:  # Для VIEW, EDIT, CREATE, FILTER_FORM
            # self.item теперь всегда экземпляр schema_for_field_metadata (или None)
            if not hasattr(
                self.item, "model_fields"
            ):  # Проверка, что item это Pydantic-like объект
                logger.warning(
                    f"Item for mode {self.mode.value} (type: {type(self.item)}) has no model_fields. Cannot prepare fields."
                )
                return

            # Итерируемся по полям схемы, которая соответствует текущему режиму (schema_for_field_metadata)
            for name, field_info_obj in schema_for_field_metadata.model_fields.items():
                # ... (пропуск DEFAULT_EXCLUDED_FIELDS и логика ui_visible для FILTER_FORM как была) ...
                if self.mode == RenderMode.FILTER_FORM:
                    is_standard = name in ["order_by", "search"]
                    ui_visible = (field_info_obj.json_schema_extra or {}).get(
                        "ui_visible", name == "search" if is_standard else True
                    )
                    if not ui_visible:
                        continue
                elif name in DEFAULT_EXCLUDED_FIELDS and self.mode != RenderMode.CREATE:
                    continue

                # Значение берем из self.item (который содержит данные от пользователя при ошибке,
                # или данные из БД, или пустые значения для CREATE/FILTER_FORM)
                value = getattr(self.item, name, None)
                current_field_render_mode = (
                    RenderMode.EDIT
                    if self.mode == RenderMode.FILTER_FORM
                    else self.mode
                )

                self._fields.append(
                    SDKField(
                        name, field_info_obj, value, self, current_field_render_mode
                    )
                )
        else:
            logger.warning(
                f"No item to prepare fields for {self.model_name} in mode {self.mode.value}"
            )
        logger.debug(
            f"Prepared {len(self._fields)} SDKFields for mode {self.mode.value}. Fields: {[f.name for f in self._fields]}"
        )

    async def get_render_context(self) -> RenderContext:
        # Гарантируем, что данные загружены или инициализированы перед подготовкой полей
        if self.mode in [
            RenderMode.VIEW,
            RenderMode.EDIT,
            RenderMode.CREATE,
            RenderMode.FILTER_FORM,
            RenderMode.TABLE_CELL,
        ]:
            if self.item is None:
                await self._load_data()
        elif self.mode in [RenderMode.LIST, RenderMode.LIST_ROWS]:
            if self.items is None:
                await self._load_data()

        await self._prepare_fields()

        field_contexts: List[FieldRenderContext] = []
        for sdk_field in self._fields:
            field_contexts.append(await sdk_field.get_render_context())

        # ... (формирование title, processed_errors, filter_form_id_val и т.д. как было) ...
        title_map = {  # ... как было ...
            RenderMode.VIEW: f"{self.model_info.model_cls.__name__}: {getattr(self.item, 'name', None) or getattr(self.item, 'title', None) or self.item_id or 'Детали'}",
            RenderMode.EDIT: f"Редактирование: {self.model_info.model_cls.__name__} ({self.item_id})",
            RenderMode.CREATE: f"Создание: {self.model_info.model_cls.__name__}",
            RenderMode.LIST: f"Список: {self.model_info.model_cls.__name__}",
            RenderMode.FILTER_FORM: f"Фильтры: {self.model_info.model_cls.__name__}",
            RenderMode.TABLE_CELL: f"Поле: {self.field_to_focus}"
            if self.field_to_focus
            else "Ячейка таблицы",
        }
        title = title_map.get(
            self.mode, f"{self.mode.value.capitalize()} {self.model_name}"
        )
        processed_errors = None  # Логика обработки self.errors как была
        if self.errors:
            if (
                isinstance(self.errors, list)
                and self.errors
                and isinstance(self.errors[0], dict)
                and "loc" in self.errors[0]
                and "msg" in self.errors[0]
            ):
                processed_errors = {}
                for error_item in self.errors:
                    loc = error_item.get("loc", [])
                    field_name_key = "_form"
                    if len(loc) > 0:
                        if len(loc) == 1 and loc[0] != "body":
                            field_name_key = str(loc[0])
                        elif len(loc) > 1:
                            field_name_key = str(loc[-1])
                    if field_name_key not in processed_errors:
                        processed_errors[field_name_key] = []
                    processed_errors[field_name_key].append(
                        error_item.get("msg", "Validation error")
                    )
            elif isinstance(self.errors, dict):
                processed_errors = self.errors
            elif isinstance(self.errors, str):
                processed_errors = {"_form": [self.errors]}
            elif isinstance(self.errors, list):
                processed_errors = {"_form": [str(e) for e in self.errors]}
            else:
                processed_errors = {"_form": ["An unknown error occurred."]}
        filter_form_id_val, list_view_url_val, table_target_id_val = (
            None,
            None,
            None,
        )  # Логика как была
        if self.mode == RenderMode.LIST or self.mode == RenderMode.FILTER_FORM:
            filter_form_id_val = f"filter--{self.model_name.lower()}"
            table_target_id_val = f"#table-placeholder-{self.model_name.lower()}"
            try:
                list_view_url_val = str(
                    self.request.url_for("get_list_view", model_name=self.model_name)
                )
            except Exception:
                pass

        return RenderContext(
            model_name=self.model_name,
            mode=self.mode,
            item_id=self.item_id,
            item=self.item,
            items=self.items,
            pagination=self.pagination,
            fields=field_contexts,
            errors=processed_errors,
            html_id=self.html_id,
            title=title,
            can_edit=True,
            can_create=True,
            can_delete=bool(self.item_id),
            extra=self.extra,
            table_key=self.model_name.lower(),
            filter_form_id=filter_form_id_val,
            table_target_id=table_target_id_val,
            list_view_url=list_view_url_val,
        )

    async def get_render_context_for_field(
        self, field_name: str
    ) -> Optional[FieldRenderContext]:
        # Гарантируем, что self.item загружен или инициализирован
        if not self.item:
            if self.item_id and self.mode in [
                RenderMode.EDIT,
                RenderMode.VIEW,
                RenderMode.TABLE_CELL,
            ]:
                await self._load_data()
            elif self.mode == RenderMode.CREATE or self.mode == RenderMode.FILTER_FORM:
                await self._load_data()
        if not self.item:
            return None

        schema_for_field_metadata = self._get_schema_for_mode()
        if self.mode == RenderMode.TABLE_CELL:
            schema_for_field_metadata = (
                self.model_info.read_schema_cls or self.model_info.model_cls
            )

        if field_name not in schema_for_field_metadata.model_fields:
            return None

        field_info_obj = schema_for_field_metadata.model_fields[field_name]
        value = getattr(self.item, field_name, None)

        current_field_render_mode = self.mode
        # Для инлайн-редактирования поле всегда рендерится в режиме EDIT (для _inline_input_wrapper)
        if self.mode == RenderMode.EDIT and self.field_to_focus == field_name:
            pass  # current_field_render_mode уже EDIT
        # Для ячейки таблицы режим TABLE_CELL
        elif self.mode == RenderMode.TABLE_CELL and self.field_to_focus == field_name:
            current_field_render_mode = RenderMode.TABLE_CELL

        sdk_field = SDKField(
            field_name, field_info_obj, value, self, current_field_render_mode
        )
        field_render_ctx = await sdk_field.get_render_context()

        if self.errors and isinstance(self.errors, dict) and field_name in self.errors:
            field_render_ctx.errors = self.errors[field_name]

        return field_render_ctx

    def get_base_context(self) -> Dict[str, Any]:
        return {
            "request": self.request,
            "model_name": self.model_name,
            "mode": self.mode.value,
            "item_id": self.item_id,
            "parent_html_id": self.html_id,
            "user": self.user,
        }

    async def prepare_response_data(self) -> Tuple[str, Dict[str, Any]]:
        # ... (логика выбора final_template_name и context_dict как в предыдущем ответе) ...
        # Важно, что self.item теперь всегда будет экземпляром нужной схемы (или None)
        render_context_instance = await self.get_render_context()
        content_template_map = {
            RenderMode.VIEW: "components/view.html",
            RenderMode.EDIT: "components/form.html",
            RenderMode.CREATE: "components/form.html",
            RenderMode.DELETE: "components/_confirm_delete_modal.html",
            RenderMode.LIST: "components/table.html",
            RenderMode.LIST_ROWS: "components/_table_rows_fragment.html",
            RenderMode.TABLE_CELL: (
                render_context_instance.fields[0].template_path
                if render_context_instance.fields
                and render_context_instance.fields[0].template_path
                else "fields/text_table.html"
            ),
            RenderMode.FILTER_FORM: "components/_filter_form.html",
        }
        template_name_for_content = content_template_map.get(self.mode)
        if not template_name_for_content:
            raise RenderingError(f"Content template for mode {self.mode} not defined.")
        final_template_name = template_name_for_content
        if self.mode not in [RenderMode.TABLE_CELL, RenderMode.LIST_ROWS]:
            clean_name = template_name_for_content.split("/")[-1]
            model_specific_template = (
                f"components/{self.model_name.lower()}/{clean_name}"
            )
            try:
                self.templates.env.get_template(model_specific_template)
                final_template_name = model_specific_template
            except Exception:
                pass
        logger.debug(
            f"Renderer for {self.model_name}/{self.mode.value}: using template '{final_template_name}'"
        )
        context_dict = {
            "request": self.request,
            "user": self.user,
            "SDK_STATIC_URL": STATIC_URL_PATH,
            "url_for": self.request.url_for,
            "ctx": render_context_instance,
        }
        if self.mode == RenderMode.TABLE_CELL:
            context_dict["field_ctx"] = (
                render_context_instance.fields[0]
                if render_context_instance.fields
                else None
            )
            context_dict["item"] = render_context_instance.item
        elif self.mode == RenderMode.LIST_ROWS:
            context_dict["items"] = render_context_instance.items
        return final_template_name, context_dict

    async def render_to_response(self, status_code: int = 200):
        # ... (как было) ...
        try:
            template_name, context_dict = await self.prepare_response_data()
            return self.templates.TemplateResponse(
                template_name, context_dict, status_code=status_code
            )
        except RenderingError as e:
            raise HTTPException(
                status_code=getattr(e, "status_code", 500), detail=str(e)
            )
        except Exception as e:
            logger.exception(
                f"Error in render_to_response for {self.model_name}, mode {self.mode.value}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"Internal server error during rendering: {str(e)}",
            )

    async def render_field_to_response(self, field_name: str, status_code: int = 200):
        # ... (как было, но self.item теперь всегда нужного типа или None) ...
        try:
            field_render_ctx = await self.get_render_context_for_field(field_name)
            if not field_render_ctx:
                raise RenderingError(
                    f"Field '{field_name}' not found for rendering.", status_code=404
                )
            template_name = field_render_ctx.template_path
            if (
                self.mode == RenderMode.EDIT
                and field_render_ctx.mode == RenderMode.EDIT
            ):  # mode поля тоже EDIT
                template_name = "fields/_inline_input_wrapper.html"
            full_render_ctx = (
                await self.get_render_context()
            )  # Получаем полный RenderContext
            context_dict = {
                "request": self.request,
                "user": self.user,
                "SDK_STATIC_URL": STATIC_URL_PATH,
                "url_for": self.request.url_for,
                "field_ctx": field_render_ctx,
                "item_id": self.item_id,
                "model_name": self.model_name,
                "item": self.item,
                "ctx": full_render_ctx,
            }
            return self.templates.TemplateResponse(
                template_name, context_dict, status_code=status_code
            )
        except RenderingError as e:
            raise HTTPException(
                status_code=getattr(e, "status_code", 500), detail=str(e)
            )
        except Exception as e:
            logger.exception(
                f"Error in render_field_to_response for {self.model_name}.{field_name}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"Internal server error rendering field: {str(e)}",
            )
