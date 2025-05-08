# core_sdk/frontend/field.py
import uuid
from typing import Any, Optional, Dict, TYPE_CHECKING, Type, List, Tuple
from pydantic.fields import FieldInfo
from pydantic import BaseModel
from enum import Enum

from .config import DEFAULT_FIELD_TYPE_MAPPING, DEFAULT_FIELD_TEMPLATES, DEFAULT_READONLY_FIELDS_IN_EDIT
from .exceptions import FieldTypeError
from .utils import get_base_type, is_list_type, get_list_item_type, is_relation, get_relation_model_name # Нужны хелперы

if TYPE_CHECKING:
    from .renderer import ViewRenderer

class FieldRenderContext(BaseModel):
    """Контекст для передачи в Jinja шаблон поля."""
    name: str
    value: Any
    label: str
    description: Optional[str] = None
    field_type: str # Определенный тип для рендеринга ('text', 'select', 'relation', etc.)
    template_path: str # Путь к Jinja шаблону для этого поля и режима
    mode: str # 'view', 'edit', 'create', 'table'
    is_readonly: bool = False
    is_required: bool = False
    options: Optional[List[Tuple[Any, str]]] = None # [(value, label), ...] for selects/enums
    errors: Optional[List[str]] = None
    html_id: str
    html_name: str # Для имен в HTML формах
    extra: Dict[str, Any] = {} # Дополнительные данные (конфиг, связанные модели и т.д.)
    # Контекст родительского рендерера (для доступа к общим данным)
    parent_context: Optional[Dict[str, Any]] = None

class SDKField:
    """Представляет поле модели данных для рендеринга."""

    def __init__(self, name: str, field_info: FieldInfo, value: Any, parent: 'ViewRenderer', mode: str):
        self.name = name
        self.field_info = field_info
        self.value = value
        self.parent = parent # Ссылка на родительский ViewRenderer
        self.mode = mode
        self._config: Dict[str, Any] = {}
        self._field_type: Optional[str] = None
        self._template_path: Optional[str] = None
        self._options: Optional[List[Tuple[Any, str]]] = None

        self._prepare()

    def _prepare(self):
        """Извлекает конфигурацию и определяет тип поля."""
        self._extract_config()
        self._determine_field_type_and_template()

    def _extract_config(self):
        """Извлекает конфигурацию из FieldInfo."""
        self.config = {
            "label": self.field_info.title or self.name.replace("_", " ").capitalize(),
            "description": self.field_info.description,
            "is_required": self.field_info.is_required() and self.mode in ['edit', 'create'],
            "is_readonly": False,
            "html_id": f"{self.parent.html_id}__{self.name}",
            # Имя для формы: может быть простым или вложенным
            "html_name": f"{self.parent.html_name_prefix}[{self.name}]" if self.parent.html_name_prefix else self.name,
            "extra_json": self.field_info.json_schema_extra or {},
        }
        self.config["is_readonly"] = self.config["extra_json"].get("readonly", False)
        # Поля только для чтения в режиме редактирования
        if self.mode == 'edit' and self.name in DEFAULT_READONLY_FIELDS_IN_EDIT:
            self.config["is_readonly"] = True

    def _determine_field_type_and_template(self):
        """Определяет тип поля и путь к шаблону на основе аннотации типа."""
        annotation = self.field_info.annotation
        base_type = get_base_type(annotation) # Хелпер для извлечения основного типа (убирает Optional, Union и т.д.)
        type_name = getattr(base_type, '__name__', str(base_type))

        field_render_type = "default" # Тип по умолчанию

        if is_relation(annotation): # Хелпер для проверки, является ли тип моделью SQLModel/Pydantic
             field_render_type = "relation"
             self.config["relation_model_name"] = get_relation_model_name(annotation) # Хелпер для извлечения имени связанной модели
        elif is_list_type(annotation):
             list_item_type = get_list_item_type(annotation) # Хелпер
             if is_relation(list_item_type):
                 field_render_type = "list_relation"
                 self.config["relation_model_name"] = get_relation_model_name(list_item_type)
             else:
                 # Обработка списков простых типов (e.g., List[str]) - можно сделать отдельный тип "list_simple"
                 field_render_type = "list_simple" # Или использовать json/text
        elif issubclass(base_type, Enum):
            field_render_type = "select"
            # Опции будут загружены позже асинхронно
        else:
            # Ищем тип в карте по имени или по самому типу
            field_render_type = DEFAULT_FIELD_TYPE_MAPPING.get(type_name,
                                DEFAULT_FIELD_TYPE_MAPPING.get(base_type, "default"))


        if field_render_type == "default":
             field_render_type = "text" # Запасной вариант - текстовое поле

        self._field_type = field_render_type

        # Определяем шаблон
        template_config = DEFAULT_FIELD_TEMPLATES.get(self._field_type, DEFAULT_FIELD_TEMPLATES["default"])
        self._template_path = template_config.get(self.mode, template_config.get("view")) # Фоллбэк на view

    async def _load_options(self):
        """Асинхронно загружает опции для select и relation полей."""
        if self._field_type == "select" and issubclass(get_base_type(self.field_info.annotation), Enum):
            enum_cls = get_base_type(self.field_info.annotation)
            self._options = [(member.value, member.name) for member in enum_cls]
        elif self._field_type in ["relation", "list_relation"]:
            relation_model_name = self.config.get("relation_model_name")
            if relation_model_name:
                try:
                    # Используем родительский рендерер для доступа к DAM Factory
                    manager = self.parent.dam_factory.get_manager(relation_model_name)
                    # TODO: Добавить обработку фильтров для опций, если нужно
                    # TODO: Нужна пагинация для больших списков? Пока грузим все (опасно)
                    # Используем list, т.к. get не подходит для получения списка опций
                    results_dict = await manager.list(limit=1000) # Ограничение!
                    items = results_dict.get("items", [])
                    # Формируем опции (value, label)
                    self._options = []
                    for item in items:
                        item_id = getattr(item, 'id', None)
                        # Пытаемся найти поле для отображения (title, name, email, ...)
                        label = getattr(item, 'title', None) or \
                                getattr(item, 'name', None) or \
                                getattr(item, 'email', None) or \
                                str(item_id) # Фоллбэк на ID
                        if item_id:
                            self._options.append((str(item_id), label)) # Значение - строка UUID

                except Exception as e:
                    logger.error(f"Failed to load options for relation field '{self.name}' (model: {relation_model_name}): {e}", exc_info=True)
                    self._options = [] # Пустой список при ошибке

    async def get_render_context(self) -> FieldRenderContext:
        """Готовит и возвращает полный контекст для рендеринга поля."""
        if self._options is None and self._field_type in ["select", "relation", "list_relation"]:
            await self._load_options()

        # Преобразование значения для отображения (особенно для связей)
        display_value = self.value
        if self._field_type == "relation" and self.value and isinstance(self.value, BaseModel):
             # Для связанных объектов показываем ID или другое поле
             display_value = getattr(self.value, 'id', str(self.value))
        elif self._field_type == "list_relation" and isinstance(self.value, list):
             # Для списков связанных объектов показываем количество или ID
             display_value = f"{len(self.value)} items" # Пример

        return FieldRenderContext(
            name=self.name,
            value=self.value, # Передаем оригинальное значение
            display_value=display_value, # Добавляем значение для простого отображения
            label=self.config["label"],
            description=self.config["description"],
            field_type=self._field_type,
            template_path=self._template_path,
            mode=self.mode,
            is_readonly=self.config["is_readonly"],
            is_required=self.config["is_required"],
            options=self._options,
            errors=None, # Ошибки валидации будут добавляться позже
            html_id=self.config["html_id"],
            html_name=self.config["html_name"],
            extra=self.config["extra_json"],
            parent_context=self.parent.get_base_context() # Базовый контекст родителя
        )