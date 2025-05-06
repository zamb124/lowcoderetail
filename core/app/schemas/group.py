# core/app/schemas/group.py
import logging
import uuid
from typing import Optional, List # Убираем TYPE_CHECKING, если импорт прямой

from sqlmodel import SQLModel, Field

# Абсолютный импорт схемы пользователя из SDK
from core_sdk.schemas.user import UserRead

# --- ИСПРАВЛЕНИЕ: Прямой импорт PermissionRead ---
# Импортируем класс напрямую, чтобы он был доступен во время выполнения model_rebuild()
from .permission import PermissionRead
# -------------------------------------------------

logger = logging.getLogger("app.schemas.group")

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
    pass

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
    users: List[UserRead] = Field(
        default=[],
        description="Список пользователей, входящих в эту группу."
    )
    # --- ИСПРАВЛЕНИЕ: Можно убрать кавычки, если нет цикла импорта ---
    # Если есть цикл импорта (permission.py импортирует group.py),
    # то кавычки нужно оставить: List["PermissionRead"]
    # Но прямой импорт выше все равно необходим для model_rebuild.
    permissions: List[PermissionRead] = Field(
        default=[],
        description="Список прав доступа, назначенных этой группе."
    )
    # -------------------------------------------------------------

logger.debug("Group schemas defined: GroupBase, GroupCreate, GroupUpdate, GroupRead, GroupReadWithDetails")
