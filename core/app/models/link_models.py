# core/app/models/link_models.py
import logging
from typing import Optional

from sqlmodel import SQLModel, Field
# Используем UUID из SDK для единообразия, если он там определен и экспортируется
# Если нет, можно использовать стандартный uuid.UUID
from core_sdk.db import UUID as SDK_UUID # Предполагаем, что SDK экспортирует UUID


logger = logging.getLogger("app.models.link_models") # Логгер для этого модуля


class UserGroupLink(SQLModel, table=True):
    """
    Связующая модель (таблица) для отношения многие-ко-многим
    между пользователями (User) и группами (Group).
    """
    user_id: Optional[SDK_UUID] = Field(
        default=None,
        foreign_key="users.id", # Внешний ключ к таблице users
        primary_key=True,
        description="Идентификатор пользователя (внешний ключ)"
    )
    group_id: Optional[SDK_UUID] = Field(
        default=None,
        foreign_key="groups.id", # Внешний ключ к таблице groups
        primary_key=True,
        description="Идентификатор группы (внешний ключ)"
    )


class GroupPermissionLink(SQLModel, table=True):
    """
    Связующая модель (таблица) для отношения многие-ко-многим
    между группами (Group) и правами доступа (Permission).
    """
    group_id: Optional[SDK_UUID] = Field(
        default=None,
        foreign_key="groups.id", # Внешний ключ к таблице groups
        primary_key=True,
        description="Идентификатор группы (внешний ключ)"
    )
    permission_id: Optional[SDK_UUID] = Field(
        default=None,
        foreign_key="permissions.id", # Внешний ключ к таблице permissions
        primary_key=True,
        description="Идентификатор права доступа (внешний ключ)"
    )
