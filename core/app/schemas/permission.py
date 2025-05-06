# core/app/schemas/permission.py
import logging
import uuid
from typing import Optional

from sqlmodel import SQLModel, Field

logger = logging.getLogger("app.schemas.permission") # Логгер для этого модуля

# Базовая схема для общих полей права доступа
class PermissionBase(SQLModel):
    codename: str = Field(
        max_length=100,
        description='Кодовое имя права доступа (уникальное, например, "users.create").'
    )
    name: str = Field(
        max_length=255,
        description="Человекочитаемое имя права доступа (для отображения в UI)."
    )
    description: Optional[str] = Field(
        default=None,
        description="Подробное описание того, что разрешает это право доступа."
    )
    # company_id добавлен, так как он есть в модели и позволяет делать права
    # либо глобальными (NULL), либо привязанными к компании.
    company_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Идентификатор компании, к которой относится право (если NULL - право глобальное)."
    )

# Схема для создания нового права доступа
class PermissionCreate(PermissionBase):
    """Схема для создания нового права доступа."""
    pass # Наследует все поля из PermissionBase

# Схема для обновления существующего права доступа
class PermissionUpdate(SQLModel):
    """Схема для обновления права доступа. Все поля опциональны."""
    name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Новое человекочитаемое имя права доступа."
    )
    description: Optional[str] = Field(
        default=None,
        description="Новое описание права доступа."
    )
    # codename обычно не изменяется после создания
    # company_id также обычно не изменяется

# Схема для чтения данных права доступа
class PermissionRead(PermissionBase):
    """Схема для чтения информации о праве доступа."""
    id: uuid.UUID = Field(description="Уникальный идентификатор права доступа.")
    lsn: int = Field(description="Последовательный номер записи (LSN) для отслеживания порядка изменений.")

logger.debug("Permission schemas defined: PermissionBase, PermissionCreate, PermissionUpdate, PermissionRead")

