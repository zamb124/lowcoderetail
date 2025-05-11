# core_sdk/schemas/pagination.py (НОВЫЙ ФАЙЛ)

from typing import Generic, TypeVar, List, Optional
from pydantic import BaseModel, Field

# Определяем TypeVar для типа данных в списке items
DataType = TypeVar("DataType")


class PaginatedResponse(BaseModel, Generic[DataType]):
    """
    Стандартная схема ответа для пагинированных списков.
    """

    items: List[DataType] = Field(..., description="Список возвращенных элементов.")
    next_cursor: Optional[int] = Field(
        None,
        description="LSN для запроса следующей страницы. "
        "Если null, значит, это последняя страница в данном направлении.",
    )
    limit: int = Field(
        ..., description="Лимит записей, использованный для этого запроса."
    )
    count: int = Field(
        ..., description="Количество элементов, возвращенных в этом ответе."
    )
    # Можно добавить total_count, если он нужен и его легко посчитать,
    # но для cursor-based пагинации это обычно не делается.
    # total_count: Optional[int] = Field(None, description="Общее количество записей (если доступно)")

    model_config = {
        "arbitrary_types_allowed": True  # Если DataType может быть сложным
    }


# Добавить в core_sdk/schemas/__init__.py
# from .pagination import PaginatedResponse
