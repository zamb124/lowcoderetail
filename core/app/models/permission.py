# core/app/models/permission.py
import logging
import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship # Убран SQLModel, т.к. наследуемся от BaseModelWithMeta
from sqlalchemy import Column # Убран Filter, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# Импорт базовой модели и фильтра из SDK
from core_sdk.db import BaseModelWithMeta
# Используем UUID из SDK или стандартный
# from core_sdk.db import UUID as SDK_UUID
from core_sdk.filters.base import DefaultFilter

# Относительные импорты для связующих моделей и TYPE_CHECKING
# GroupPermissionLink импортируется из link_models
from .link_models import GroupPermissionLink

if TYPE_CHECKING:
    from .group import Group

logger = logging.getLogger("app.models.permission") # Логгер для этого модуля

class Permission(BaseModelWithMeta, table=True):
    """
    Модель права доступа (пермишена).
    Представляет собой атомарное разрешение на выполнение действия в системе.
    """
    __tablename__ = "permissions"

    codename: str = Field(
        index=True,
        unique=True,
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

    # --- Связи ---
    groups: List["Group"] = Relationship(
        back_populates="permissions",
        link_model=GroupPermissionLink,
        sa_relationship_kwargs={"lazy": "selectin"} # Пример настройки загрузки
    )

    # Поле company_id в BaseModelWithMeta уже есть.
    # Здесь оно переопределено с nullable=True. Это означает, что права могут быть
    # либо глобальными (company_id=NULL), либо принадлежать конкретной компании.
    # Если права всегда глобальны, это поле можно убрать.
    # Если права всегда принадлежат компании, нужно ForeignKey и nullable=False.
    company_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column("company_id", PG_UUID(as_uuid=True), index=True, nullable=True), # nullable=True позволяет глобальные права
        description="Идентификатор компании, к которой относится право (если NULL - право глобальное)."
    )


class PermissionFilter(DefaultFilter):
    """
    Фильтр для запросов списка прав доступа.
    Наследует стандартные поля от DefaultFilter.
    """
    codename: Optional[str] = Field(default=None, description="Фильтр по точному кодовому имени.")
    codename__like: Optional[str] = Field(default=None, description="Фильтр по части кодового имени (регистрозависимый).")
    name: Optional[str] = Field(default=None, description="Фильтр по точному имени.")
    name__like: Optional[str] = Field(default=None, description="Фильтр по части имени (регистрозависимый).")
    # company_id__isnull: Optional[bool] = Field(default=None, description="Фильтр глобальных (true) или компанейских (false) прав.")

    class Constants(DefaultFilter.Constants):
        model = Permission
        # Поля для полнотекстового поиска (параметр ?search=...)
        search_model_fields = ["codename", "name", "description"]
