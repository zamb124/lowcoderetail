# core_sdk/frontend/types.py
from enum import Enum

class ComponentMode(str, Enum):
    """
    Определяет тип основного UI-компонента или фрагмента, который рендерится.
    """
    VIEW_FORM = "view_form"                # Форма для просмотра одного объекта (карточка)
    EDIT_FORM = "edit_form"                # Форма для редактирования одного объекта
    CREATE_FORM = "create_form"              # Форма для создания нового объекта
    DELETE_CONFIRM = "delete_confirm"        # Модальное окно подтверждения удаления
    LIST_TABLE = "list_table"              # Таблица для отображения списка объектов (полная)
    LIST_TABLE_ROWS_FRAGMENT = "list_table_rows_fragment" # Фрагмент с рядами таблицы (для HTMX подгрузки)
    TABLE_CELL = "table_cell"                # Отдельная ячейка таблицы (для инлайн-редактирования)
    FILTER_FORM = "filter_form"              # Форма фильтрации для списка

class FieldState(str, Enum):
    """
    Определяет состояние (режим отображения) отдельного поля внутри компонента.
    """
    VIEW = "view"    # Поле в режиме только для чтения
    EDIT = "edit"    # Поле в режиме редактирования (input, select, etc.)
    # Можно добавить HIDDEN, если понадобится явное управление скрытием через состояние,
    # а не просто отсутствием поля в списке рендеринга.
    # HIDDEN = "hidden"