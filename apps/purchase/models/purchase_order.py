# purchase/app/models/purchase_order.py
import logging
import uuid
from typing import Optional, List  # List может понадобиться для связей в будущем
from sqlmodel import Field  # Relationship для будущих связей
from core_sdk.db import BaseModelWithMeta
from core_sdk.filters.base import DefaultFilter
from enum import Enum

logger = logging.getLogger("app.models.purchase_order")


class PurchaseOrderStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ORDERED = "ordered"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class PurchaseOrder(BaseModelWithMeta, table=True):
    __tablename__ = "purchase_orders"

    order_number: str = Field(index=True, unique=True, description="Уникальный номер заказа на закупку")
    supplier_id: Optional[uuid.UUID] = Field(default=None, index=True, description="ID поставщика (может быть внешним)")
    # company_id уже есть в BaseModelWithMeta и будет ID компании, создавшей заказ

    status: PurchaseOrderStatus = Field(
        default=PurchaseOrderStatus.DRAFT, index=True, description="Текущий статус заказа на закупку"
    )

    # Пример дополнительных полей
    expected_delivery_date: Optional[str] = Field(
        default=None, description="Ожидаемая дата поставки (в ISO формате)"
    )  # Используем str для простоты, можно datetime
    total_amount: Optional[float] = Field(default=None, description="Общая сумма заказа")

    # В будущем здесь могут быть связи, например, с позициями заказа (PurchaseOrderLine)
    # lines: List["PurchaseOrderLine"] = Relationship(back_populates="purchase_order")


class PurchaseOrderFilter(DefaultFilter):
    order_number: Optional[str] = Field(default=None, description="Фильтр по точному номеру заказа")
    order_number__like: Optional[str] = Field(default=None, description="Фильтр по части номера заказа")
    supplier_id: Optional[uuid.UUID] = Field(default=None, description="Фильтр по ID поставщика")
    status: Optional[PurchaseOrderStatus] = Field(default=None, description="Фильтр по статусу заказа")
    status__in: Optional[List[PurchaseOrderStatus]] = Field(default=None, description="Фильтр по списку статусов")

    class Constants(DefaultFilter.Constants):
        model = PurchaseOrder
        search_model_fields = ["order_number"]


logger.debug("PurchaseOrder model and PurchaseOrderFilter defined.")
