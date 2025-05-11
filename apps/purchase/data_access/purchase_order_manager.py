# purchase/app/data_access/purchase_order_manager.py
import logging
from core_sdk.data_access import BaseDataAccessManager
from ..models.purchase_order import PurchaseOrder
from ..schemas.purchase_order_schema import PurchaseOrderCreate, PurchaseOrderUpdate

logger = logging.getLogger("app.data_access.purchase_order_manager")


class PurchaseOrderManager(BaseDataAccessManager[PurchaseOrder, PurchaseOrderCreate, PurchaseOrderUpdate]):
    model = PurchaseOrder
    create_schema = PurchaseOrderCreate
    update_schema = PurchaseOrderUpdate
    # read_schema будет по умолчанию PurchaseOrder (модель SQLModel),
    # CRUDRouterFactory будет использовать PurchaseOrderRead из registry_config

    # Пример переопределения для специфичной логики
    # async def _prepare_for_create(self, validated_data: PurchaseOrderCreate) -> PurchaseOrder:
    #     logger.info(f"Creating purchase order: {validated_data.order_number}")
    #     # Какая-то логика перед созданием, например, проверка уникальности order_number,
    #     # хотя это лучше делать на уровне БД или валидатора Pydantic.
    #     # Или установка company_id из текущего пользователя, если не передано.
    #     db_item = await super()._prepare_for_create(validated_data)
    #     return db_item
    pass


logger.debug("PurchaseOrderManager defined.")
