# core/app/schemas/user.py
import logging
import uuid
from typing import Optional, List

from pydantic import EmailStr # EmailStr используется для валидации email
from sqlmodel import SQLModel, Field

# Относительный импорт схемы группы из текущего приложения
from .group import GroupRead
# CompanyRead не используется в этих схемах, убран импорт

logger = logging.getLogger("app.schemas.user") # Логгер для этого модуля

# Базовая схема с общими полями пользователя
class UserBase(SQLModel):
    email: EmailStr = Field(
        index=True, # Хотя index здесь больше для модели, оставляем для информации
        unique=True, # Аналогично
        description="Email адрес пользователя (уникальный)."
    )
    first_name: Optional[str] = Field(
        default=None,
        description="Имя пользователя."
    )
    last_name: Optional[str] = Field(
        default=None,
        description="Фамилия пользователя."
    )
    is_active: Optional[bool] = Field(
        default=True,
        description="Флаг активности пользователя (может ли войти в систему)."
    )
    is_superuser: Optional[bool] = Field(
        default=False,
        description="Флаг суперпользователя (обладает всеми правами)."
    )
    company_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Идентификатор компании, к которой принадлежит пользователь (может быть NULL)."
    )

# Схема для создания нового пользователя
class UserCreate(UserBase):
    """Схема для создания нового пользователя (требует пароль)."""
    password: str = Field(description="Пароль пользователя (будет хеширован перед сохранением).")

# Схема для обновления существующего пользователя
class UserUpdate(SQLModel):
    """Схема для обновления данных пользователя. Все поля опциональны."""
    email: Optional[EmailStr] = Field(
        default=None,
        description="Новый email адрес пользователя."
    )
    first_name: Optional[str] = Field(
        default=None,
        description="Новое имя пользователя."
    )
    last_name: Optional[str] = Field(
        default=None,
        description="Новая фамилия пользователя."
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Новый статус активности пользователя."
    )
    is_superuser: Optional[bool] = Field(
        default=None,
        description="Новый статус суперпользователя."
    )
    password: Optional[str] = Field(
        default=None,
        description="Новый пароль пользователя (если требуется изменить)."
    )
    company_id: Optional[uuid.UUID] = Field( # Добавлено поле для возможности смены компании
        default=None,
        description="Новый идентификатор компании пользователя."
    )


# Схема для чтения данных пользователя (возвращается API) - без пароля
class UserRead(UserBase):
    """Схема для чтения основной информации о пользователе (без пароля)."""
    id: uuid.UUID = Field(description="Уникальный идентификатор пользователя.")
    lsn: int = Field(description="Последовательный номер записи (LSN) для отслеживания порядка изменений.")
    # Связанные данные (company, groups) не включаются в базовую схему чтения

# Схема для чтения пользователя с информацией о его группах
class UserReadWithGroups(UserRead):
    """Схема для чтения пользователя с информацией о группах, в которых он состоит."""
    groups: List[GroupRead] = Field(
        default=[],
        description="Список групп, в которых состоит пользователь."
    )

logger.debug("User schemas defined: UserBase, UserCreate, UserUpdate, UserRead, UserReadWithGroups")