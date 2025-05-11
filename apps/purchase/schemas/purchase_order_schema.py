# purchase/app/schemas/purchase_order_schema.py
import logging
import uuid
from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime  # Для created_at, updated_at
from ..models.purchase_order import PurchaseOrderStatus  # Импортируем Enum статуса

logger = logging.getLogger("app.schemas.purchase_order_schema")


class PurchaseOrderBase(SQLModel):
    order_number: str = Field(description="Номер заказа на закупку")
    supplier_id: Optional[uuid.UUID] = Field(default=None, description="ID поставщика")
    company_id: uuid.UUID  # ID компании, к которой относится заказ
    status: Optional[PurchaseOrderStatus] = Field(default=PurchaseOrderStatus.DRAFT, description="Статус заказа")
    expected_delivery_date: Optional[str] = Field(default=None, description="Ожидаемая дата поставки")
    total_amount: Optional[float] = Field(default=None, description="Общая сумма")


class PurchaseOrderCreate(PurchaseOrderBase):
    # При создании статус может быть установлен или иметь значение по умолчанию
    status: PurchaseOrderStatus = Field(default=PurchaseOrderStatus.DRAFT, description="Начальный статус заказа")


class PurchaseOrderUpdate(SQLModel):
    order_number: Optional[str] = Field(default=None)
    supplier_id: Optional[uuid.UUID] = Field(default=None)
    # company_id обычно не меняется при обновлении
    status: Optional[PurchaseOrderStatus] = Field(default=None)
    expected_delivery_date: Optional[str] = Field(default=None)
    total_amount: Optional[float] = Field(default=None)


class PurchaseOrderRead(PurchaseOrderBase):
    id: uuid.UUID
    lsn: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    # company_id уже есть в PurchaseOrderBase


# Можно добавить схему с деталями, если будут связанные сущности (например, позиции заказа)
# class PurchaseOrderReadWithLines(PurchaseOrderRead):
#     lines: List[PurchaseOrderLineRead] = []

logger.debug("PurchaseOrder schemas defined.")
