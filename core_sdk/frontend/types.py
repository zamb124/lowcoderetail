# core_sdk/frontend/types.py
from enum import Enum

class RenderMode(str, Enum):
    VIEW = "view"
    EDIT = "edit"
    CREATE = "create"
    LIST = "list"
    TABLE_CELL = "table"
    LIST_ROWS = "list_rows"
    FILTER_FORM = "filter_form" # <--- НОВЫЙ РЕЖИМ