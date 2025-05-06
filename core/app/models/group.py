# core/app/models/group.py
import logging
import uuid
from typing import Optional, List, TYPE_CHECKING

from sqlmodel import Field, Relationship
from sqlalchemy import Column, ForeignKey, UniqueConstraint # Убраны неиспользуемые импорты SQLAlchemy
from sqlalchemy.dialects.postgresql import UUID as PG_UUID # Оставляем PG_UUID для ForeignKey

# Импорт базовой модели и фильтра из SDK
from core_sdk.db import BaseModelWithMeta
from core_sdk.filters.base import DefaultFilter

# Относительные импорты для связующих моделей и моделей для TYPE_CHECKING
from .link_models import UserGroupLink, GroupPermissionLink

if TYPE_CHECKING:
    from .user import User
    from .permission import Permission
    from .company import Company

logger = logging.getLogger("app.models.group") # Логгер для этого модуля

class Group(BaseModelWithMeta, table=True):
    """
    Модель Группы пользователей.
    Группы используются для объединения пользователей и назначения им прав доступа.
    """
    __tablename__ = "groups"
    # Уникальность имени группы в рамках одной компании
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_group_company_id_name"),)

    name: str = Field(
        index=True,
        max_length=100,
        description="Название группы (уникальное в пределах компании)."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Описание группы."
    )

    # --- Связи ---
    company_id: uuid.UUID = Field(
        # Используем sa_column для явного определения ForeignKey и других параметров колонки
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("companies.id", ondelete="CASCADE"), # При удалении компании удаляются и ее группы
            nullable=False,
            index=True
        ),
        description="Идентификатор компании, к которой принадлежит группа."
    )
    company: "Company" = Relationship(
        back_populates="groups",
        sa_relationship_kwargs={"lazy": "selectin"} # Пример настройки загрузки
    )

    users: List["User"] = Relationship(
        back_populates="groups",
        link_model=UserGroupLink,
        sa_relationship_kwargs={"lazy": "selectin"} # Пример настройки загрузки
    )
    permissions: List["Permission"] = Relationship(
        back_populates="groups",
        link_model=GroupPermissionLink,
        sa_relationship_kwargs={"lazy": "selectin"} # Пример настройки загрузки
    )

class GroupFilter(DefaultFilter):
    """
    Фильтр для запросов списка групп.
    Наследует стандартные поля (id__in, company_id__in, created_at, etc.) от DefaultFilter.
    """
    name: Optional[str] = Field(default=None, description="Фильтр по точному названию группы.")
    name__like: Optional[str] = Field(default=None, description="Фильтр по части названия группы (регистрозависимый).")
    # Можно добавить фильтры по связанным моделям, если необходимо
    # users__id: Optional[uuid.UUID] = Field(default=None, description="Фильтр по ID пользователя в группе.")

    class Constants(DefaultFilter.Constants):
        model = Group
        # Поля для полнотекстового поиска (параметр ?search=...)
        search_model_fields = ["name", "description"]
