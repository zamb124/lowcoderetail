# core/app/schemas/company.py
import logging
import uuid
from typing import Optional, List

from sqlmodel import SQLModel
from pydantic import Field

# Относительные импорты схем связанных моделей из текущего приложения
from .user import UserRead
from .group import GroupRead

logger = logging.getLogger("app.schemas.company")  # Логгер для этого модуля


# Базовая схема для общих полей компании
class CompanyBase(SQLModel):
    name: str = Field(max_length=150, description="Название компании (уникальное).")
    description: Optional[str] = Field(default=None, description="Описание компании.")
    is_active: bool = Field(default=True, description="Флаг активности компании.")
    address: Optional[str] = Field(
        default=None, description="Юридический или фактический адрес компании."
    )
    vat_id: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Идентификационный номер налогоплательщика (ИНН, VAT ID и т.п.).",
    )


# Схема для создания новой компании
class CompanyCreate(CompanyBase):
    """Схема для создания новой компании."""

    pass  # Наследует все поля из CompanyBase


# Схема для обновления существующей компании
class CompanyUpdate(SQLModel):
    """Схема для обновления данных компании. Все поля опциональны."""

    name: Optional[str] = Field(
        default=None, max_length=150, description="Новое название компании."
    )
    description: Optional[str] = Field(
        default=None, description="Новое описание компании."
    )
    is_active: Optional[bool] = Field(
        default=None, description="Новый статус активности компании."
    )
    address: Optional[str] = Field(default=None, description="Новый адрес компании.")
    vat_id: Optional[str] = Field(
        default=None, max_length=50, description="Новый ИНН/VAT ID компании."
    )


# Схема для чтения основной информации о компании
class CompanyRead(CompanyBase):
    """Схема для чтения основной информации о компании."""

    id: uuid.UUID = Field(description="Уникальный идентификатор компании.")
    lsn: int = Field(
        description="Последовательный номер записи (LSN) для отслеживания порядка изменений."
    )
    # Связанные пользователи и группы не включаются в базовую схему чтения


# Схема для чтения компании с деталями (пользователи и группы)
class CompanyReadWithDetails(CompanyRead):
    """Схема для чтения компании с информацией о связанных пользователях и группах."""

    users: List[UserRead] = Field(
        default=[], description="Список пользователей, принадлежащих этой компании."
    )
    groups: List[GroupRead] = Field(
        default=[], description="Список групп, принадлежащих этой компании."
    )


logger.debug(
    "Company schemas defined: CompanyBase, CompanyCreate, CompanyUpdate, CompanyRead, CompanyReadWithDetails"
)
