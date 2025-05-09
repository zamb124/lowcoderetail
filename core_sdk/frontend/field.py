# core_sdk/frontend/field.py
import uuid
import inspect # Для проверки Enum
from typing import Any, Optional, Dict, TYPE_CHECKING, Type, List, Tuple
from pydantic.fields import FieldInfo as PydanticFieldInfo
from pydantic import BaseModel
from enum import Enum

from .config import DEFAULT_FIELD_TYPE_MAPPING, DEFAULT_FIELD_TEMPLATES, DEFAULT_READONLY_FIELDS_IN_EDIT
from .exceptions import FieldTypeError
from .utils import get_base_type, is_list_type, get_list_item_type, is_relation, get_relation_model_name
import logging # Добавим логгирование

logger = logging.getLogger(__name__) # Логгер для этого модуля

if TYPE_CHECKING:
    from .renderer import ViewRenderer

class FieldRenderContext(BaseModel):
    name: str
    value: Any
    label: str
    description: Optional[str] = None
    field_type: str
    template_path: str
    mode: str
    is_readonly: bool = False
    is_required: bool = False
    options: Optional[List[Tuple[Any, str]]] = None
    errors: Optional[List[str]] = None
    html_id: str
    html_name: str
    extra: Dict[str, Any] = {}
    parent_context: Optional[Dict[str, Any]] = None

class SDKField:
    def __init__(self, name: str, field_info: PydanticFieldInfo, value: Any, parent: 'ViewRenderer', mode: str):
        self.name = name
        self.field_info = field_info
        self.value = value
        self.parent = parent
        self.mode = mode
        self.config: Dict[str, Any] = {}
        self._field_type: Optional[str] = None
        self._template_path: Optional[str] = None
        self._options: Optional[List[Tuple[Any, str]]] = None

        self._prepare()

    def _extract_config(self):
        json_schema_extra_data = {}
        if self.field_info.json_schema_extra:
            if callable(self.field_info.json_schema_extra):
                try:
                    json_schema_extra_data = self.field_info.json_schema_extra()
                except Exception: pass
            elif isinstance(self.field_info.json_schema_extra, dict):
                json_schema_extra_data = self.field_info.json_schema_extra

        self.config = {
            "label": self.field_info.title or self.name.replace("_", " ").capitalize(),
            "description": self.field_info.description,
            "is_required": self.field_info.is_required() and self.mode in ['edit', 'create'],
            "is_readonly": False,
            "html_id": f"{self.parent.html_id}__{self.name}",
            "html_name": f"{self.parent.html_name_prefix}[{self.name}]" if self.parent.html_name_prefix else self.name,
            "extra_json": json_schema_extra_data,
        }
        self.config["is_readonly"] = self.config["extra_json"].get("readonly", False)
        if self.mode == 'edit' and self.name in DEFAULT_READONLY_FIELDS_IN_EDIT:
            self.config["is_readonly"] = True

    def _prepare(self):
        self._extract_config()
        self._determine_field_type_and_template()

    def _determine_field_type_and_template(self):
        annotation = self.field_info.annotation
        base_type = get_base_type(annotation) # Хелпер: Optional[T] -> T, Union[T, None] -> T
        type_name_for_mapping = getattr(base_type, '__name__', str(base_type)) # Имя типа для карты

        field_render_type = "default" # Тип по умолчанию

        # Получаем значение 'rel' и 'render_type' из json_schema_extra
        # self.config уже содержит extra_json
        related_model_for_id_resolution = self.config["extra_json"].get("rel")
        explicit_render_type = self.config["extra_json"].get("render_type")

        logger.debug(
            f"Determining field type for '{self.name}': "
            f"Annotation='{annotation}', BaseType='{base_type}', "
            f"Rel='{related_model_for_id_resolution}', ExplicitRenderType='{explicit_render_type}'"
        )

        if explicit_render_type:
            field_render_type = explicit_render_type
            logger.debug(f"  Using explicit render_type: '{field_render_type}'")
            # Если тип явно указан, также можем захотеть получить имя связанной модели, если это реляция
            if field_render_type in ["relation", "list_relation", "uuid_with_title_resolution", "list_uuid_with_title_resolution"]:
                # Если 'rel' есть в extra_json, используем его, иначе пытаемся извлечь из типа аннотации
                self.config["relation_model_name"] = related_model_for_id_resolution or get_relation_model_name(annotation)
                logger.debug(f"    relation_model_name set to: '{self.config['relation_model_name']}'")

        # Логика для полей-идентификаторов, требующих подгрузки title
        elif related_model_for_id_resolution:
            if base_type is uuid.UUID or type_name_for_mapping == "UUID":
                field_render_type = "relation"
                self.config["relation_model_name"] = related_model_for_id_resolution.lower()
                logger.debug(f"  Type set to 'uuid_with_title_resolution' for model '{related_model_for_id_resolution}'")
            elif is_list_type(annotation):
                list_item_b_type = get_list_item_type(annotation) # Получаем базовый тип элемента списка
                if list_item_b_type is uuid.UUID or getattr(list_item_b_type, '__name__', '') == "UUID":
                    field_render_type = "list_relation"
                    self.config["relation_model_name"] = related_model_for_id_resolution.lower()
                    logger.debug(f"  Type set to 'list_uuid_with_title_resolution' for model '{related_model_for_id_resolution}'")
                else:
                    logger.warning(f"  Field '{self.name}' has 'rel' but is a list of non-UUIDs ('{list_item_b_type}'). Treating as 'list_simple'.")
                    field_render_type = "list_simple" # Или другая обработка для списков не-UUID с 'rel'
            else:
                logger.warning(f"  Field '{self.name}' has 'rel' but is not UUID or List[UUID] (type: '{base_type}'). Defaulting type.")
                # Переходим к стандартной логике определения типа ниже
                pass # Позволит следующей логике определить тип

        # Логика для "объектных" реляций (когда тип поля - это другая Pydantic/SQLModel модель)
        if field_render_type == "default": # Если тип еще не определен предыдущими условиями
            if is_relation(annotation): # Хелпер проверяет, является ли тип Pydantic/SQLModel
                field_render_type = "relation"
                self.config["relation_model_name"] = get_relation_model_name(annotation)
                logger.debug(f"  Type set to 'relation' for model '{self.config['relation_model_name']}'")
            elif is_list_type(annotation):
                list_item_b_type = get_list_item_type(annotation)
                if is_relation(list_item_b_type):
                    field_render_type = "list_relation"
                    self.config["relation_model_name"] = get_relation_model_name(list_item_b_type)
                    logger.debug(f"  Type set to 'list_relation' for model '{self.config['relation_model_name']}'")
                else:
                    # Это список простых типов (str, int, etc.)
                    field_render_type = "list_simple"
                    logger.debug(f"  Type set to 'list_simple' (list of '{list_item_b_type}')")
            elif inspect.isclass(base_type) and issubclass(base_type, Enum):
                field_render_type = "select"
                logger.debug(f"  Type set to 'select' for Enum '{base_type.__name__}'")
            else:
                # Используем карту типов по умолчанию
                field_render_type = DEFAULT_FIELD_TYPE_MAPPING.get(type_name_for_mapping,
                                                                   DEFAULT_FIELD_TYPE_MAPPING.get(base_type, "text")) # Фоллбэк на "text"
                logger.debug(f"  Type set from DEFAULT_FIELD_TYPE_MAPPING: '{field_render_type}' for base_type '{type_name_for_mapping}'")

        if field_render_type == "default": # Если все еще "default"
            field_render_type = "text" # Финальный фоллбэк
            logger.debug(f"  Final fallback type set to 'text'")


        self._field_type = field_render_type
        template_config = DEFAULT_FIELD_TEMPLATES.get(self._field_type, DEFAULT_FIELD_TEMPLATES["default"])
        self._template_path = template_config.get(self.mode, template_config.get("view")) # Фоллбэк на view режим шаблона

        logger.info(f"Field '{self.name}': Determined field_type='{self._field_type}', template_path='{self._template_path}'")

        # Дополнительная проверка: если это тип для TitleResolver, но нет relation_model_name
        if self._field_type in ["uuid_with_title_resolution", "list_uuid_with_title_resolution"] and \
                not self.config.get("relation_model_name"):
            logger.warning(
                f"Field '{self.name}' is of type '{self._field_type}' but 'relation_model_name' "
                f"(expected from json_schema_extra['rel']) is missing. Title resolution might not work."
            )

    async def _load_options(self):
        if self._field_type == "select" and inspect.isclass(get_base_type(self.field_info.annotation)) and issubclass(get_base_type(self.field_info.annotation), Enum):
            enum_cls = get_base_type(self.field_info.annotation)
            self._options = [(member.value, member.name) for member in enum_cls]
        elif self._field_type in ["relation", "list_relation", "uuid_with_title_resolution", "list_uuid_with_title_resolution"]:
            relation_model_name = self.config.get("relation_model_name")
            if relation_model_name:
                try:
                    manager = self.parent.dam_factory.get_manager(relation_model_name)
                    results_dict = await manager.list(limit=1000)
                    items = results_dict.get("items", [])
                    self._options = []
                    for item in items:
                        item_id = getattr(item, 'id', None)
                        label = getattr(item, 'title', None) or \
                                getattr(item, 'name', None) or \
                                getattr(item, 'email', None) or \
                                str(item_id)
                        if item_id:
                            self._options.append((str(item_id), label))
                except Exception as e:
                    logger.error(f"Failed to load options for relation field '{self.name}' (model: {relation_model_name}): {e}", exc_info=True)
                    self._options = []

    async def get_render_context(self) -> FieldRenderContext:
        if self._options is None and self._field_type in ["select", "relation", "list_relation", "uuid_with_title_resolution", "list_uuid_with_title_resolution"]:
            pass # TODO: что это и зачем?!
            #await self._load_options()

        return FieldRenderContext(
            name=self.name,
            value=self.value,
            label=self.config["label"],
            description=self.config["description"],
            field_type=self._field_type,
            template_path=self._template_path,
            mode=self.mode,
            is_readonly=self.config["is_readonly"],
            is_required=self.config["is_required"],
            options=self._options,
            errors=None,
            html_id=self.config["html_id"],
            html_name=self.config["html_name"],
            extra=self.config, # Передаем весь self.config, включая extra_json и relation_model_name
            parent_context=self.parent.get_base_context()
        )