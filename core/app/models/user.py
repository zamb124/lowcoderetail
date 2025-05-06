# core/app/models/user.py
import logging
import uuid
# datetime, Dict, Any не используются напрямую
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import Field, SQLModel, Relationship # Убран SQLModel, т.к. наследуемся от BaseModelWithMeta
# Убраны неиспользуемые импорты SQLAlchemy
from sqlalchemy import Column, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# Импорт базовой модели и фильтра из SDK
from core_sdk.db import BaseModelWithMeta
from core_sdk.filters.base import DefaultFilter

# Относительные импорты для связующих моделей и TYPE_CHECKING
from .link_models import UserGroupLink

if TYPE_CHECKING:
    from .company import Company
    from .group import Group

logger = logging.getLogger("app.models.user") # Логгер для этого модуля

class User(BaseModelWithMeta, table=True):
    """
    Модель Пользователя системы.
    """
    __tablename__ = "users"

    # company_id определен в BaseModelWithMeta.
    # Здесь мы переопределяем его, чтобы добавить ForeignKey и изменить nullable.
    company_id: Optional[uuid.UUID] = Field( # Тип Optional, так как ondelete="SET NULL"
        sa_column=Column(
            PG_UUID(as_uuid=True),
            # ForeignKey к таблице companies.
            # ondelete="SET NULL": если компания удаляется, у пользователя company_id станет NULL.
            # Альтернативы: "CASCADE" (удалить пользователя), "RESTRICT" (запретить удаление компании).
            ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True, # Разрешаем NULL в БД (соответствует ondelete="SET NULL")
            index=True
        ),
        default=None, # Значение по умолчанию для Python
        description="Идентификатор компании, к которой принадлежит пользователь (может быть NULL)."
    )

    email: str = Field(
        index=True,
        unique=True,
        max_length=255, # Максимальная длина email
        description="Email адрес пользователя (уникальный)."
    )
    # Храним хеш пароля, а не сам пароль
    hashed_password: str = Field(
        sa_column=Column(Text, nullable=False), # Используем Text для длинных хешей
        description="Хешированный пароль пользователя."
    )
    first_name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Имя пользователя."
    )
    last_name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Фамилия пользователя."
    )
    is_active: bool = Field(
        default=True,
        nullable=False,
        description="Флаг активности пользователя (может ли пользователь войти в систему)."
    )
    is_superuser: bool = Field(
        default=False,
        nullable=False,
        description="Флаг суперпользователя (обладает всеми правами)."
    )

    # --- Связи ---
    company: Optional["Company"] = Relationship( # Optional, т.к. company_id может быть NULL
        back_populates="users",
        sa_relationship_kwargs={"lazy": "selectin"} # Пример настройки загрузки
    )
    groups: List["Group"] = Relationship(
        back_populates="users",
        link_model=UserGroupLink,
        sa_relationship_kwargs={"lazy": "selectin"} # Пример настройки загрузки
    )

class UserFilter(DefaultFilter):
    """
    Фильтр для запросов списка пользователей.
    Наследует стандартные поля от DefaultFilter.
    """
    email: Optional[str] = Field(default=None, description="Фильтр по точному email адресу.")
    email__in: Optional[List[str]] = Field(default=None, description="Фильтр по списку email адресов.")
    email__like: Optional[str] = Field(default=None, description="Фильтр по части email адреса (регистрозависимый).")
    first_name__like: Optional[str] = Field(default=None, description="Фильтр по части имени.")
    last_name__like: Optional[str] = Field(default=None, description="Фильтр по части фамилии.")
    is_active: Optional[bool] = Field(default=None, description="Фильтр по статусу активности (true/false).")
    is_superuser: Optional[bool] = Field(default=None, description="Фильтр по статусу суперпользователя (true/false).")
    # company_id и company_id__in уже есть в DefaultFilter
    # company_id__isnull: Optional[bool] = Field(default=None, description="Фильтр пользователей без компании (true) или с компанией (false).")

    class Constants(DefaultFilter.Constants):
        model = User
        # Поля для полнотекстового поиска (параметр ?search=...)
        search_model_fields = ["email", "first_name", "last_name"]