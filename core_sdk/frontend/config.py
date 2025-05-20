# core_sdk/frontend/config.py
import os
from typing import List, Dict, Any

# Пути относительно директории frontend внутри SDK
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(_CURRENT_DIR, "templates")
STATIC_DIR = os.path.join(_CURRENT_DIR, "static")
STATIC_URL_PATH = "/sdk-static"  # Префикс URL для статики SDK

# Поля, которые обычно не нужно показывать или редактировать напрямую
DEFAULT_EXCLUDED_FIELDS: List[str] = [
    "hashed_password",
    "vars",
    "lsn",
]

DEFAULT_READONLY_FIELDS_IN_EDIT: List[str] = [
    "id",
    "created_at",
    "updated_at",
    "company_id",
]

# Карта базовых типов Python/Pydantic на типы полей для рендеринга
DEFAULT_FIELD_TYPE_MAPPING: Dict[type | str, str] = {
    str: "text",
    int: "number",
    float: "number",
    bool: "switch", # Был checkbox, стал switch
    Any: "text",
    "UUID": "text",
    "datetime": "datetime",
    "date": "date",
    "time": "time",
    "EmailStr": "email",
    "HttpUrl": "url",
    "Enum": "select",
    "List": "list_simple", # Изменил на list_simple для ясности
    "Dict": "json", # Для отображения JSON-словарей
    # "Relation" и "ListRelation" больше не нужны здесь, они определяются логикой в SDKField
}

# Шаблоны по умолчанию для разных типов полей и их состояний (FieldState)
# Ключи теперь "view" и "edit"
DEFAULT_FIELD_TEMPLATES: Dict[str, str] = {
    "text": "fields/text_field.html",
    "number": "fields/text_field.html", # Использует text_field, который умеет type="number"
    "switch": "fields/switch_field.html",
    "select": "fields/select_field.html", # Для Enum
    "relation": "fields/relation_select_field.html", # Для одиночной связи
    "list_relation": "fields/list_relation_select_field.html", # Для множественной связи
    "datetime": "fields/datetime_field.html", # Единый шаблон для datetime
    "date": "fields/date_field.html",         # Единый шаблон для date
    "time": "fields/time_field.html",         # Единый шаблон для time
    "email": "fields/text_field.html",    # Использует text_field
    "url": "fields/text_field.html",      # Использует text_field
    "list_simple": "fields/list_simple_field.html",
    "json": "fields/json_field.html",
    "default": "fields/text_field.html", # Шаблон по умолчанию
}

# Настройки WebSocket (остаются без изменений)
WS_EVENT_MODEL_UPDATED = "MODEL_UPDATED"
WS_EVENT_MODEL_DELETED = "MODEL_DELETED"
WS_EVENT_MODEL_CREATED = "MODEL_CREATED"
WS_EVENT_NOTIFICATION = "NOTIFICATION"
WS_EVENT_RELOAD_VIEW = "RELOAD_VIEW"
WS_EVENT_AUTH_REFRESH = "AUTH_REFRESH_REQUIRED"
WS_EVENT_AUTH_LOGOUT = "AUTH_LOGOUT"