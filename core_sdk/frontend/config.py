# core_sdk/frontend/config.py
import os
from typing import List, Dict, Any

# Пути относительно директории frontend внутри SDK
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(_CURRENT_DIR, "templates")
STATIC_DIR = os.path.join(_CURRENT_DIR, "static")
STATIC_URL_PATH = "/sdk-static" # Префикс URL для статики SDK

# Поля, которые обычно не нужно показывать или редактировать напрямую
DEFAULT_EXCLUDED_FIELDS: List[str] = [
    "hashed_password",
    "vars", # Часто служебное поле
    "lsn", # Обычно не редактируется
]

DEFAULT_READONLY_FIELDS_IN_EDIT: List[str] = [
    "id",
    "created_at",
    "updated_at",
    "company_id", # Часто определяется контекстом
]

# Карта базовых типов Python/Pydantic на типы полей для рендеринга
# Можно расширять для кастомных типов
DEFAULT_FIELD_TYPE_MAPPING: Dict[type | str, str] = {
    str: "text",
    int: "number",
    float: "number",
    bool: "switch",
    Any: "text", # По умолчанию для Any
    "UUID": "text", # UUID часто отображается как текст (иногда ссылка)
    "datetime": "datetime",
    "date": "date",
    "time": "time",
    "EmailStr": "email",
    "HttpUrl": "url",
    "Enum": "select",
    "List": "list", # Базовый тип для списков
    "Dict": "json",
    "Relation": "relation", # Специальный тип для связей
    "ListRelation": "list_relation", # Специальный тип для связей "многие"
}

# Шаблоны по умолчанию для разных типов полей
DEFAULT_FIELD_TEMPLATES: Dict[str, Dict[str, str]] = {
    # field_type: { mode: template_path }
    "text": {
        "view": "fields/text_view.html",
        "edit": "fields/text_input.html",
        "create": "fields/text_input.html",
        "table": "fields/text_table.html",
    },
    "number": {
        "view": "fields/text_view.html", # Можно использовать тот же, что и для text
        "edit": "fields/number_input.html",
        "create": "fields/number_input.html",
        "table": "fields/text_table.html",
    },
     "switch": { # <--- НОВЫЙ/ОБНОВЛЕННЫЙ ТИП
        "view": "fields/switch_view.html",
        "edit": "fields/switch_input.html",
        "create": "fields/switch_input.html",
        "table": "fields/switch_table.html",
    },
    "select": { # Для Enum или Choices
        "view": "fields/text_view.html", # Отображаем выбранное значение
        "edit": "fields/select.html",
        "create": "fields/select.html",
        "table": "fields/text_table.html",
    },
    "relation": { # Связь один-к-одному/многим
        "view": "fields/relation_view.html", # Может быть ссылкой
        "edit": "fields/relation_select.html", # Асинхронный селект
        "create": "fields/relation_select.html",
        "table": "fields/relation_table.html", # Может быть ссылкой
    },
    "list_relation": { # Связь один-ко-многим / многие-ко-многим
        "view": "fields/list_relation_view.html",
        "edit": "fields/list_relation_select.html",
        "create": "fields/list_relation_select.html",
        "table": "fields/list_relation_table.html",
    },
    # --- НОВЫЕ ТИПЫ ДЛЯ ДАТЫ/ВРЕМЕНИ ---
    "datetime": {
        "view": "fields/datetime_view.html",
        "edit": "fields/datetime_input.html",
        "create": "fields/datetime_input.html",
        "table": "fields/datetime_table.html",
    },
    "date": {
        "view": "fields/date_view.html",
        "edit": "fields/date_input.html",
        "create": "fields/date_input.html",
        "table": "fields/date_table.html",
    },
    "time": {
        "view": "fields/time_view.html",
        "edit": "fields/time_input.html",
        "create": "fields/time_input.html",
        "table": "fields/time_table.html",
    },
    # ... другие типы ...
    "default": { # Шаблон по умолчанию, если тип не найден
        "view": "fields/text_view.html",
        "edit": "fields/text_input.html",
        "create": "fields/text_input.html",
        "table": "fields/text_table.html",
    }
}

# Настройки WebSocket
WS_EVENT_MODEL_UPDATED = "MODEL_UPDATED"
WS_EVENT_MODEL_DELETED = "MODEL_DELETED"
WS_EVENT_MODEL_CREATED = "MODEL_CREATED"
WS_EVENT_NOTIFICATION = "NOTIFICATION"
WS_EVENT_RELOAD_VIEW = "RELOAD_VIEW"
WS_EVENT_AUTH_REFRESH = "AUTH_REFRESH_REQUIRED"
WS_EVENT_AUTH_LOGOUT = "AUTH_LOGOUT"