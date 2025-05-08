# core_sdk/frontend/types.py
from enum import Enum

class RenderMode(str, Enum):
    """Режим рендеринга компонента."""
    VIEW = "view"
    EDIT = "edit"
    CREATE = "create"
    LIST = "list" # Для отображения в виде таблицы/списка
    TABLE_CELL = "table" # Для рендеринга отдельной ячейки таблицы