from core_sdk.broker.setup import broker # Импорт брокера из SDK
from core_sdk.db.session import async_session_maker # Импорт сессии для доступа к БД в задаче
from ..models.product import Product # Модели WMS

@broker.task()
async def update_stock_level(product_id: UUID, change: int):
    async with async_session_maker() as session:
        # Пример доступа к БД внутри задачи
        product = await session.get(Product, product_id)
        if product:
            print(f"Updating stock for {product.name} (ID: {product_id}) by {change}")
            # ... логика обновления стока ...
            await session.commit()
        else:
            print(f"Product {product_id} not found for stock update.")