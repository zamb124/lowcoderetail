# core/app/schemas/group.py
import logging
import uuid
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import SQLModel, Field

# Абсолютный импорт схемы пользователя из SDK
from core_sdk.schemas.user import UserRead

# Относительный импорт схемы права доступа из текущего приложения
# Используем TYPE_CHECKING для избежания циклического импорта, если PermissionRead импортирует GroupRead
if TYPE_CHECKING:
    from .permission import PermissionRead

logger = logging.getLogger("app.schemas.group") # Логгер для этого модуля

# Базовая схема для общих полей группы
class GroupBase(SQLModel):
    name: str = Field(
        max_length=100,
        description="Название группы (должно быть уникальным в пределах компании)."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Описание группы."
    )
    company_id: uuid.UUID = Field(description="Идентификатор компании, к которой принадлежит группа.")

# Схема для создания новой группы
class GroupCreate(GroupBase):
    """Схема для создания новой группы."""
    pass # Наследует все поля из GroupBase

# Схема для обновления существующей группы
class GroupUpdate(SQLModel):
    """Схема для обновления данных группы. Все поля опциональны."""
    name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Новое название группы."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Новое описание группы."
    )

# Схема для чтения данных группы (без связей)
class GroupRead(GroupBase):
    """Схема для чтения основной информации о группе."""
    id: uuid.UUID = Field(description="Уникальный идентификатор группы.")
    lsn: int = Field(description="Последовательный номер записи (LSN) для отслеживания порядка изменений.")

# Схема для чтения данных группы со связанными пользователями и правами
class GroupReadWithDetails(GroupRead):
    """Схема для чтения группы с детальной информацией о пользователях и правах."""
    # Используем UserRead из SDK
    users: List[UserRead] = Field(
        default=[],
        description="Список пользователей, входящих в эту группу."
    )
    # Используем PermissionRead из локальных схем
    permissions: List["PermissionRead"] = Field(
        default=[],
        description="Список прав доступа, назначенных этой группе."
    )

# Логгируем факт определения схем (пример использования логгера в файле схем)
logger.debug("Group schemas defined: GroupBase, GroupCreate, GroupUpdate, GroupRead, GroupReadWithDetails")