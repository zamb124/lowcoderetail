# CRUD Роутеры (`core_sdk.crud.factory`)

Модуль `core_sdk.crud.factory` предоставляет `CRUDRouterFactory` для автоматической генерации стандартных CRUD (Create, Read, Update, Delete) эндпоинтов для ваших моделей.

## `CRUDRouterFactory`

Этот класс позволяет быстро создавать FastAPI `APIRouter` с эндпоинтами для:
*   Получения списка объектов с пагинацией и фильтрацией (`GET /`)
*   Создания нового объекта (`POST /`)
*   Получения объекта по ID (`GET /{item_id}`)
*   Обновления объекта по ID (`PUT /{item_id}`)
*   Удаления объекта по ID (`DELETE /{item_id}`)

Фабрика интегрируется с `ModelRegistry` для получения информации о модели, схемах и менеджере данных, а также с `fastapi-filter` для поддержки фильтрации.

::: core_sdk.crud.factory.CRUDRouterFactory
    handler: python
    options:
      heading_level: 3
      # Показать конструктор и основные методы добавления роутов
      members:
        - __init__
        - router # property
        - _add_list_route
        - _add_get_route
        - _add_create_route
        - _add_update_route
        - _add_delete_route

## Использование

В файле эндпоинтов вашего сервиса (например, `my_service/app/api/endpoints/products_api.py`):

```python
from fastapi import Depends
from core_sdk.crud.factory import CRUDRouterFactory
from core_sdk.dependencies.auth import get_current_user # Пример зависимости

product_router_factory = CRUDRouterFactory(
    model_name="Product", # Имя, под которым модель зарегистрирована в ModelRegistry
    prefix="/products",
    tags=["Products"],
    # Зависимости для защиты эндпоинтов
    get_deps=[Depends(get_current_user)],
    list_deps=[Depends(get_current_user)],
    create_deps=[Depends(get_current_user)], # Возможно, нужны более строгие права
    update_deps=[Depends(get_current_user)],
    delete_deps=[Depends(get_current_user)],
)
```

### Роутер доступен как product_router_factory.router
### Его нужно подключить в main.py вашего сервиса:
### app.include_router(product_router_factory.router)
