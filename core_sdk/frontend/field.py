# core_sdk/frontend/field.py
import uuid
import inspect
from typing import Any, Optional, Dict, TYPE_CHECKING, List, Tuple
from pydantic.fields import FieldInfo as PydanticFieldInfo
from pydantic import BaseModel, ConfigDict
from enum import Enum

from .config import (
    DEFAULT_FIELD_TYPE_MAPPING,
    DEFAULT_FIELD_TEMPLATES, # Мы все еще используем это для определения пути к единому шаблону
    DEFAULT_READONLY_FIELDS_IN_EDIT,
)
from .utils import (
    get_base_type,
    is_list_type,
    get_list_item_type,
    is_relation,
    get_relation_model_name,
)
from .types import ComponentMode, FieldState
import logging

logger = logging.getLogger("core_sdk.frontend.field")

if TYPE_CHECKING:
    from .renderer import ViewRenderer


class FieldRenderContext(BaseModel):
    name: str
    value: Any
    label: str
    description: Optional[str] = None
    field_type: str
    template_path: str # Путь к единому шаблону поля (например, fields/text_field.html)
    state: FieldState
    html_id: str
    html_name: str
    is_readonly: bool = False
    is_required: bool = False
    errors: Optional[List[str]] = None
    options: Optional[List[Tuple[Any, str]]] = None
    related_model_name: Optional[str] = None
    extra_attrs: Dict[str, Any] = {}
    is_editable_context: bool = False # НОВЫЙ ФЛАГ

    model_config = ConfigDict(arbitrary_types_allowed=True)


# core_sdk/frontend/field.py
# ... (импорты FieldState, ComponentMode, FieldRenderContext как были) ...

if TYPE_CHECKING:
    from .renderer import RenderContext # Изменили импорт

class SDKField:
    def __init__(
        self,
        name: str,
        field_info: PydanticFieldInfo,
        value: Any,
        # --- ИЗМЕНЕНИЕ: Принимаем готовый RenderContext родителя ---
        parent_render_context: "RenderContext",
        # ----------------------------------------------------------
        component_mode: ComponentMode, # Все еще нужен для определения _determined_template_path
        field_state: FieldState,
    ):
        self.name = name
        self.field_info = field_info
        self.value = value
        # --- ИЗМЕНЕНИЕ ---
        self.parent_render_context = parent_render_context
        # -----------------
        self.component_mode = component_mode # Для _determine_field_type_and_template
        self.field_state = field_state

        self.config: Dict[str, Any] = {}
        self._determined_field_type: Optional[str] = None
        self._determined_template_path: Optional[str] = None
        self._loaded_options: Optional[List[Tuple[Any, str]]] = None

        self._prepare()

    def _extract_config(self):
        json_schema_extra_data = {}
        if self.field_info.json_schema_extra:
            if callable(self.field_info.json_schema_extra):
                try: json_schema_extra_data = self.field_info.json_schema_extra()
                except Exception: pass
            elif isinstance(self.field_info.json_schema_extra, dict):
                json_schema_extra_data = self.field_info.json_schema_extra.copy()

        # Используем html_id родительского компонента из parent_render_context
        field_html_id = f"{self.parent_render_context.html_id}__{self.name}"
        field_html_name = self.name
        ui_config = json_schema_extra_data.pop('ui_config', {})

        self.config = {
            "label": self.field_info.title or self.name.replace("_", " ").capitalize(),
            "description": self.field_info.description,
            "is_required": self.field_info.is_required() and self.field_state == FieldState.EDIT,
            "is_readonly": False, # Определится ниже
            "html_id": field_html_id,
            "html_name": field_html_name,
            "extra_attrs": ui_config,
            "related_model_name": json_schema_extra_data.get("rel"),
        }

        is_readonly_from_schema = json_schema_extra_data.get("readonly", False)
        is_default_readonly_in_edit = (
            self.field_state == FieldState.EDIT and self.name in DEFAULT_READONLY_FIELDS_IN_EDIT
        )
        self.config["is_readonly"] = (self.field_state == FieldState.VIEW) or is_readonly_from_schema or is_default_readonly_in_edit

        if self.config["is_readonly"] and self.field_state == FieldState.EDIT:
            self.config["is_required"] = False

    def _prepare(self):
        self._extract_config()
        self._determine_field_type_and_template() # component_mode используется здесь

    def _determine_field_type_and_template(self):
        # ... (логика определения self._determined_field_type как была)
        annotation = self.field_info.annotation
        base_type = get_base_type(annotation)
        type_name_for_mapping = getattr(base_type, "__name__", str(base_type))
        related_model_name = self.config.get("related_model_name")
        explicit_render_type = self.config["extra_attrs"].get("render_type")
        determined_field_type = "default"

        if explicit_render_type:
            determined_field_type = explicit_render_type
            if determined_field_type in ["relation", "list_relation"] and not related_model_name:
                self.config["related_model_name"] = get_relation_model_name(annotation)
        elif base_type is bool: determined_field_type = "switch"
        elif related_model_name:
            if base_type is uuid.UUID or type_name_for_mapping == "UUID": determined_field_type = "relation"
            elif is_list_type(annotation):
                list_item_b_type = get_list_item_type(annotation)
                if list_item_b_type is uuid.UUID or getattr(list_item_b_type, "__name__", "") == "UUID":
                    if self.name not in ["id", "id__in"]: determined_field_type = "list_relation"
                    else: determined_field_type = "list_simple"
                else: determined_field_type = "list_simple"
        if determined_field_type == "default":
            if is_relation(annotation):
                if is_list_type(annotation): determined_field_type = "list_relation"
                else: determined_field_type = "relation"
                self.config["related_model_name"] = get_relation_model_name(annotation)
            elif is_list_type(annotation): determined_field_type = "list_simple"
            elif inspect.isclass(base_type) and issubclass(base_type, Enum): determined_field_type = "select"
            else:
                determined_field_type = DEFAULT_FIELD_TYPE_MAPPING.get(type_name_for_mapping, DEFAULT_FIELD_TYPE_MAPPING.get(base_type, "text"))
        if determined_field_type == "default": determined_field_type = "text"
        self._determined_field_type = determined_field_type
        # ... (конец определения self._determined_field_type)

        template_path_for_type = DEFAULT_FIELD_TEMPLATES.get(self._determined_field_type, DEFAULT_FIELD_TEMPLATES["default"])
        if not template_path_for_type or not isinstance(template_path_for_type, str):
            logger.error(f"Invalid template path for field_type '{self._determined_field_type}'. Defaulting.")
            self._determined_template_path = DEFAULT_FIELD_TEMPLATES["default"]
        else:
            self._determined_template_path = template_path_for_type

        # Логирование без f-строки со сложными объектами
        logger.info(
            "Field '%s': Determined field_type='%s', template_path='%s' (state='%s', component_mode_of_parent='%s')",
            str(self.name), str(self._determined_field_type), str(self._determined_template_path),
            str(self.field_state.value), str(self.component_mode.value) # component_mode здесь - это режим родителя
        )


    async def _load_options(self):
        # ... (логика _load_options как была, но self.parent_renderer.dam_factory заменяется на прямой доступ к DAM)
        # Это изменение требует, чтобы SDKField имел доступ к DAM factory,
        # что можно передать через parent_render_context.extra или напрямую в конструктор SDKField.
        # Пока оставим как было, предполагая, что dam_factory доступен через self.parent_render_context.dam_factory (если мы его туда добавим)
        # или что ViewRenderer передаст его в SDKField.
        # Для упрощения, ViewRenderer должен будет передать dam_factory в SDKField.
        # Либо, SDKField._load_options должен быть вызван из ViewRenderer, который имеет доступ к dam_factory.
        # Давайте пока оставим вызов self.parent_renderer.dam_factory, но это нужно будет исправить.
        # ЛУЧШЕ: ViewRenderer будет вызывать _load_options для SDKField, если это нужно.
        # Тогда SDKField не нужен прямой доступ к dam_factory.
        # В get_render_context мы просто будем использовать self._loaded_options.
        pass # Загрузка опций будет управляться ViewRenderer


    async def get_render_context(self) -> FieldRenderContext:
        # self._loaded_options теперь должен быть установлен ViewRenderer перед вызовом этого метода, если они нужны
        # (т.е. если field_state == EDIT и тип поля требует опций)

        # is_readonly текущего состояния поля
        is_readonly_for_current_state = self.config["is_readonly"]

        # Определяем, можно ли в принципе кликнуть по этому полю для перехода в режим EDIT
        # (если оно сейчас в состоянии VIEW)
        parent_allows_overall_edit = self.parent_render_context.can_edit
        field_is_schematically_editable = not (
            self.config["extra_attrs"].get("readonly", False) or \
            (self.name in DEFAULT_READONLY_FIELDS_IN_EDIT)
        )

        # Для ячеек таблицы, редактируемость определяется 'editable_in_table'
        if self.parent_render_context.component_mode == ComponentMode.TABLE_CELL:
            contextual_edit_permission = self.config["extra_attrs"].get('editable_in_table', self.config["extra_attrs"].get('editable', True))
        else: # Для форм (VIEW_FORM, EDIT_FORM, CREATE_FORM)
            contextual_edit_permission = parent_allows_overall_edit

        # Поле можно перевести в режим редактирования, если оно не readonly по схеме
        # И если контекст компонента это позволяет
        is_editable_in_this_context = field_is_schematically_editable and contextual_edit_permission

        return FieldRenderContext(
            name=self.name,
            value=self.value,
            label=self.config["label"],
            description=self.config["description"],
            field_type=self._determined_field_type,
            template_path=self._determined_template_path,
            state=self.field_state,
            is_readonly=is_readonly_for_current_state, # Это is_readonly для текущего field_state
            is_required=self.config["is_required"],
            errors=None, # Ошибки будут добавлены в ViewRenderer
            options=self._loaded_options, # Заполняется ViewRenderer
            related_model_name=self.config.get("related_model_name"),
            html_id=self.config["html_id"],
            html_name=self.config["html_name"],
            extra_attrs=self.config["extra_attrs"],
            is_editable_context=is_editable_in_this_context,
        )