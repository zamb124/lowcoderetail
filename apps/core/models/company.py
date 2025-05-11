# core/app/models/company.py
import logging
import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlmodel import (
    Field,
    Relationship,
)  # Убран SQLModel, т.к. наследуемся от BaseModelWithMeta
from sqlalchemy import Column  # Убран Filter, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# Импорт базовой модели и фильтра из SDK
from core_sdk.db import BaseModelWithMeta

# Используем UUID из SDK или стандартный
# from core_sdk.db import UUID as SDK_UUID
from core_sdk.filters.base import DefaultFilter

# Относительные импорты для TYPE_CHECKING
if TYPE_CHECKING:
    from .user import User
    from .group import Group

logger = logging.getLogger("app.models.company")  # Логгер для этого модуля


class Company(BaseModelWithMeta, table=True):
    """
    Модель Компании в системе. Представляет собой организацию или клиента.
    """

    __tablename__ = "companies"

    name: str = Field(
        index=True,
        unique=True,
        max_length=150,
        description="Название компании (уникальное).",
    )
    description: Optional[str] = Field(default=None, description="Описание компании.")
    is_active: bool = Field(
        default=True, index=True, description="Флаг активности компании."
    )

    # Дополнительные поля
    address: Optional[str] = Field(
        default=None, description="Юридический или фактический адрес компании."
    )
    vat_id: Optional[str] = Field(
        default=None,
        index=True,
        max_length=50,
        description="Идентификационный номер налогоплательщика (ИНН, VAT ID и т.п.).",
    )

    # --- Связи ---
    # Связь с пользователями (один ко многим)
    users: List["User"] = Relationship(
        back_populates="company",
        sa_relationship_kwargs={"lazy": "selectin"},  # Пример настройки загрузки
    )
    # Связь с группами (один ко многим)
    groups: List["Group"] = Relationship(
        back_populates="company",
        sa_relationship_kwargs={"lazy": "selectin"},  # Пример настройки загрузки
    )

    # Поле company_id в BaseModelWithMeta уже есть.
    # Здесь оно переопределено с nullable=True, что может быть неверно,
    # если компания не может ссылаться сама на себя или на другую компанию таким образом.
    # Если это поле не нужно для Company, его можно не переопределять.
    # Если оно нужно и должно быть nullable, то оставляем.
    # Если оно должно быть NOT NULL и ссылаться на что-то другое, нужна ForeignKey.
    # Оставляю как в вашем коде, но с комментарием.
    company_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            "company_id", PG_UUID(as_uuid=True), index=True, nullable=True
        ),  # nullable=True может быть неверным для Company
        description="Идентификатор родительской компании (если используется иерархия).",  # Уточнил описание
    )


class CompanyFilter(DefaultFilter):
    """
    Фильтр для запросов списка компаний.
    Наследует стандартные поля от DefaultFilter.
    """

    name: Optional[str] = Field(
        default=None, description="Фильтр по точному названию компании."
    )
    name__like: Optional[str] = Field(
        default=None,
        description="Фильтр по части названия компании (регистрозависимый).",
    )
    name__in: Optional[List[str]] = Field(
        default=None, description="Фильтр по списку точных названий компаний."
    )
    is_active: Optional[bool] = Field(
        default=None, description="Фильтр по статусу активности (true/false)."
    )
    vat_id: Optional[str] = Field(
        default=None, description="Фильтр по точному ИНН/VAT ID."
    )
    vat_id__isnull: Optional[bool] = Field(
        default=None,
        description="Фильтр по наличию ИНН/VAT ID (true - IS NULL, false - IS NOT NULL).",
    )

    class Constants(DefaultFilter.Constants):
        model = Company
        # Поля для полнотекстового поиска (параметр ?search=...)
        search_model_fields = ["name", "description", "vat_id", "address"]
