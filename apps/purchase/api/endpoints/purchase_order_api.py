# purchase/app/api/endpoints/purchase_order_api.py
import logging
from fastapi import Depends
from core_sdk.crud.factory import CRUDRouterFactory
from core_sdk.dependencies.auth import get_current_user  # Для защиты эндпоинтов

logger = logging.getLogger("app.api.endpoints.purchase_order_api")

# Имя "PurchaseOrder" должно совпадать с тем, как модель зарегистрирована в ModelRegistry
purchase_order_router_factory = CRUDRouterFactory(
    model_name="PurchaseOrder",
    prefix="/purchase-orders",
    tags=["Purchase Orders"],
    # Определяем зависимости для защиты CRUD операций
    # TODO: Замените get_current_user на более специфичные права, если нужно
    get_deps=[Depends(get_current_user)],
    list_deps=[Depends(get_current_user)],
    create_deps=[Depends(get_current_user)],
    update_deps=[Depends(get_current_user)],
    delete_deps=[Depends(get_current_user)],
)

# Здесь можно добавлять кастомные эндпоинты к purchase_order_router_factory.router
# Например:
# @purchase_order_router_factory.router.post("/{order_id}/approve", response_model=PurchaseOrderRead)
# async def approve_purchase_order(order_id: uuid.UUID, user: AuthenticatedUser = Depends(get_current_user)):
#     # Логика утверждения заказа
#     pass

logger.debug("CRUDRouterFactory for PurchaseOrder initialized.")
