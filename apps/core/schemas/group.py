# core/app/schemas/group.py
import logging
import uuid
from typing import Optional, List  # Убираем TYPE_CHECKING, если импорт прямой

from sqlmodel import SQLModel
from pydantic import Field

# Абсолютный импорт схемы пользователя из SDK
from core_sdk.schemas.user import UserRead

# -------------------------------------------------

logger = logging.getLogger("app.schemas.group")


# Базовая схема для общих полей группы
class GroupBase(SQLModel):
    name: str = Field(
        max_length=100,
        description="Название группы (должно быть уникальным в пределах компании).",
    )
    description: Optional[str] = Field(
        default=None, max_length=255, description="Описание группы."
    )
    company_id: uuid.UUID = Field(
        description="Идентификатор компании, к которой принадлежит группа."
    )

    permissions: List[str] = Field(
        default_factory=list,  # Для Pydantic, чтобы по умолчанию был пустой список
        description="Список коднаймов прав доступа, назначенных этой группе.",
    )


# Схема для создания новой группы
class GroupCreate(GroupBase):
    """Схема для создания новой группы."""

    pass


# Схема для обновления существующей группы
class GroupUpdate(SQLModel):
    """Схема для обновления данных группы. Все поля опциональны."""

    name: Optional[str] = Field(
        default=None, max_length=100, description="Новое название группы."
    )
    description: Optional[str] = Field(
        default=None, max_length=255, description="Новое описание группы."
    )
    permissions: Optional[List[str]] = Field(
        default=None,
        description="Новый список коднаймов прав доступа для группы (полностью заменяет старый).",
    )


# Схема для чтения данных группы (без связей)
class GroupRead(GroupBase):
    """Схема для чтения основной информации о группе."""

    id: uuid.UUID = Field(description="Уникальный идентификатор группы.")
    lsn: int = Field(
        description="Последовательный номер записи (LSN) для отслеживания порядка изменений."
    )


# Схема для чтения данных группы со связанными пользователями и правами
class GroupReadWithDetails(GroupRead):
    users: List[UserRead] = Field(...)
    permissions: List[str] = Field(  # <--- Изменено на List[str]
        default=[],
        description="Список коднаймов прав доступа, назначенных этой группе.",
    )
    # -------------------------------------------------------------


logger.debug(
    "Group schemas defined: GroupBase, GroupCreate, GroupUpdate, GroupRead, GroupReadWithDetails"
)
