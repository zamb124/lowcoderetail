# apps/core/schemas/user.py
import logging
import uuid
from typing import Optional, List

from pydantic import EmailStr, Field, BaseModel

from core_sdk.schemas.base import BaseSchema
from .group import GroupRead

logger = logging.getLogger("app.schemas.user")

class UserBase(BaseSchema):
    email: EmailStr = Field(description="Email адрес пользователя (уникальный).")
    first_name: Optional[str] = Field(default=None, description="Имя пользователя.")
    last_name: Optional[str] = Field(default=None, description="Фамилия пользователя.")
    is_active: Optional[bool] = Field(
        default=True,
        description="Флаг активности пользователя.",
    )
    is_superuser: Optional[bool] = Field(
        default=False, description="Флаг суперпользователя."
    )
    # company_id наследуется из BaseSchema как Optional[uuid.UUID]

class UserCreate(UserBase):
    id: Optional[uuid.UUID] = Field(default=None) # Явное переопределение для гарантии
    password: str = Field(description="Пароль пользователя.")
    company_id: uuid.UUID # Переопределяем как обязательное для User

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = Field(default=None)
    first_name: Optional[str] = Field(default=None)
    last_name: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)
    is_superuser: Optional[bool] = Field(default=None)
    password: Optional[str] = Field(default=None)
    company_id: Optional[uuid.UUID] = Field(default=None)

class UserRead(UserBase):
    pass

class UserReadWithGroups(UserRead):
    groups: List[GroupRead] = Field(default_factory=list)

logger.debug(
    "User schemas defined: UserBase, UserCreate, UserUpdate, UserRead, UserReadWithGroups"
)