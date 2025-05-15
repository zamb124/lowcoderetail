# apps/core/schemas/company.py
import logging
import uuid
from typing import Optional, List

from pydantic import Field, BaseModel

from core_sdk.schemas.base import BaseSchema
from .user import UserRead
from .group import GroupRead

logger = logging.getLogger("app.schemas.company")

class CompanyBase(BaseSchema):
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

class CompanyCreate(CompanyBase):
    id: Optional[uuid.UUID] = Field(default=None) # Явное переопределение для гарантии
    # company_id остается Optional[uuid.UUID] из BaseSchema, что корректно,
    # так как CompanyDataAccessManager установит его равным id новой компании.
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=150)
    description: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)
    address: Optional[str] = Field(default=None)
    vat_id: Optional[str] = Field(default=None, max_length=50)
    # company_id: Optional[uuid.UUID] = Field(default=None) # Обычно не меняется так

class CompanyRead(CompanyBase):
    pass

class CompanyReadWithDetails(CompanyRead):
    users: List[UserRead] = Field(default_factory=list)
    groups: List[GroupRead] = Field(default_factory=list)

logger.debug(
    "Company schemas defined: CompanyBase, CompanyCreate, CompanyUpdate, CompanyRead, CompanyReadWithDetails"
)