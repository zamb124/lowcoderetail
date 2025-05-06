from fastapi import APIRouter
from core_sdk.crud.factory import CRUDRouterFactory # Импорт генератора
from core_sdk.db.session import get_session # Импорт зависимости сессии
from ...models.product import Product, ProductCreate, ProductUpdate # Модели WMS

# Используем фабрику для создания стандартных CRUD роутов
router = CRUDRouterFactory(
    model=Product,
    create_schema=ProductCreate,
    update_schema=ProductUpdate,
    read_schema=Product, # Можно явно указать схему для чтения
    prefix="/products",
    tags=["Products"]
).router

# Здесь можно добавить кастомные эндпоинты для специфичной логики WMS
@router.post("/{product_id}/custom_action")
async def custom_product_action(product_id: UUID):
    # ... какая-то логика ...
    return {"message": "Custom action performed"}