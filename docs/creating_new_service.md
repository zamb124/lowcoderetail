# Руководство: Создание нового микросервиса

Это пошаговое руководство описывает процесс создания нового микросервиса с использованием LowCodeRetail Framework.

## Шаг 0: Генерация бойлерплейта

Воспользуйтесь скриптом `create_microservice.py` для генерации базовой структуры вашего нового сервиса:

```bash
python create_microservice.py
# Введите имя сервиса (PascalCase): MyNewService
# Введите имя директории (snake_case, по умолчанию my_new_service): my_new_service
```

Скрипт создаст директорию `my_new_service` со структурой, основанной на сервисе `core`, и базовыми файлами, включая модель `SomeModel` и CRUD API для нее.

## Шаг 1: Настройка окружения и `.env`

1.  Перейдите в директорию нового сервиса: `cd my_new_service`.
2.  Создайте файл `.env` на основе `.env_example`.
3.  **Обязательно** заполните `DATABASE_URL`, если ваш сервис будет использовать собственную базу данных. Например:
    ```env
    DATABASE_URL=postgresql+asyncpg://main_user:main_password@db:5432/my_new_service_db
    ```
4.  Укажите `SECRET_KEY` (уже сгенерирован скриптом, но можете заменить).
5.  Настройте `REDIS_URL`, если сервис использует Taskiq для фоновых задач (например, `redis://redis:6379/2` - используйте номер БД Redis, отличный от других сервисов).
6.  Укажите `PORT_MY_NEW_SERVICE` (например, `PORT_MY_NEW_SERVICE=8002`). Это значение будет использовано в `main.py` и `Dockerfile`.
7.  Заполните остальные переменные при необходимости (например, `CORE_SERVICE_URL`).

## Шаг 2: Определение моделей (`app/models/`)

Скрипт уже создал `app/models/some_model.py` с примером `SomeModel`.

*   Переименуйте `some_model.py` и класс `SomeModel` в соответствии с вашей основной сущностью (например, `product.py` и `Product`).
*   Определите поля вашей модели, наследуясь от `core_sdk.db.BaseModelWithMeta`.
*   Определите связи `Relationship` с другими моделями (если есть).
*   Создайте класс фильтра (например, `ProductFilter`), наследуясь от `core_sdk.filters.base.DefaultFilter`.

**Пример (`app/models/product.py`):**
```python
# my_new_service/app/models/product.py
import logging
from typing import Optional
from sqlmodel import Field
from core_sdk.db import BaseModelWithMeta
from core_sdk.filters.base import DefaultFilter

logger = logging.getLogger("app.models.product")

class Product(BaseModelWithMeta, table=True):
    __tablename__ = "products" # Имя таблицы для вашего сервиса

    name: str = Field(index=True, max_length=200)
    sku: str = Field(index=True, unique=True, max_length=100)
    price: float = Field(default=0.0)
    # company_id уже есть в BaseModelWithMeta

class ProductFilter(DefaultFilter):
    name__like: Optional[str] = Field(default=None)
    sku: Optional[str] = Field(default=None)
    price__gte: Optional[float] = Field(default=None)

    class Constants(DefaultFilter.Constants):
        model = Product
        search_model_fields = ["name", "sku"]
```
Не забудьте обновить `app/models/__init__.py`.

## Шаг 3: Определение схем (`app/schemas/`)

Скрипт создал `app/schemas/some_model_schema.py`.

*   Переименуйте файл и классы схем (`SomeModelBase`, `SomeModelCreate`, `SomeModelUpdate`, `SomeModelRead`) в соответствии с вашей моделью (например, `product_schema.py`, `ProductBase`, `ProductRead`).
*   Определите поля для каждой схемы.

**Пример (`app/schemas/product_schema.py`):**
```python
# my_new_service/app/schemas/product_schema.py
import logging
import uuid
from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

logger = logging.getLogger("app.schemas.product_schema")

class ProductBase(SQLModel):
    name: str
    sku: str
    price: float = 0.0
    company_id: uuid.UUID

class ProductCreate(ProductBase):
    pass

class ProductUpdate(SQLModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[float] = None
    company_id: Optional[uuid.UUID] = None

class ProductRead(ProductBase):
    id: uuid.UUID
    lsn: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
```
Обновите `app/schemas/__init__.py`.

## Шаг 4: Менеджер доступа к данным (DAM) (`app/data_access/`)

Скрипт создал `app/data_access/some_model_manager.py`.

*   Переименуйте файл и класс `SomeModelManager` (например, `product_manager.py`, `ProductManager`).
*   Укажите правильные `model`, `create_schema`, `update_schema` в классе менеджера.
*   При необходимости переопределите методы `_prepare_for_create`, `_prepare_for_update` или добавьте кастомные методы.

**Пример (`app/data_access/product_manager.py`):**
```python
# my_new_service/app/data_access/product_manager.py
import logging
from core_sdk.data_access import BaseDataAccessManager
from ..models.product import Product
from ..schemas.product_schema import ProductCreate, ProductUpdate

logger = logging.getLogger("app.data_access.product_manager")

class ProductManager(BaseDataAccessManager[Product, ProductCreate, ProductUpdate]):
    model = Product
    create_schema = ProductCreate
    update_schema = ProductUpdate
```
Обновите `app/data_access/__init__.py`.

## Шаг 5: Регистрация моделей (`app/registry_config.py`)

Отредактируйте `app/registry_config.py`, чтобы зарегистрировать вашу модель (например, `Product`) с ее менеджером, схемами и фильтром.

```python
# my_new_service/app/registry_config.py
# ... импорты ...
from .models.product import Product, ProductFilter # Пример
from .schemas.product_schema import ProductCreate, ProductUpdate, ProductRead # Пример
from .data_access.product_manager import ProductManager # Пример

def configure_my_new_service_registry():
    # ...
    ModelRegistry.register_local(
        model_cls=Product,
        manager_cls=ProductManager,
        filter_cls=ProductFilter,
        create_schema_cls=ProductCreate,
        update_schema_cls=ProductUpdate,
        read_schema_cls=ProductRead,
        model_name="Product" # Имя для регистрации
    )
    # ...
```

## Шаг 6: API Эндпоинты (`app/api/endpoints/`)

Скрипт создал `app/api/endpoints/some_model_api.py`.

*   Переименуйте файл и объект `some_model_router_factory` (например, `products_api.py`, `product_router_factory`).
*   Убедитесь, что `model_name` в `CRUDRouterFactory` совпадает с именем, под которым модель зарегистрирована в `registry_config.py` (например, `"Product"`).
*   Настройте префикс, теги и зависимости для защиты эндпоинтов.

Обновите `app/api/endpoints/__init__.py`.

## Шаг 7: Главный файл приложения (`app/main.py`)

Отредактируйте `app/main.py`:
*   Импортируйте вашу фабрику роутеров (например, `from .api.endpoints.products_api import product_router_factory`).
*   Добавьте `.router` от вашей фабрики в список `api_routers_to_include`.
*   Убедитесь, что порт в `uvicorn.run` соответствует тому, что указан в `.env` и `Dockerfile`.

## Шаг 8: Воркер Taskiq (`app/worker.py`)

Файл `app/worker.py` уже должен быть настроен скриптом. Главное, чтобы `registry_config_module` указывал на ваш `app/registry_config.py`.

## Шаг 9: Миграции Alembic

1.  **Настройте `alembic.ini`**:
    *   Установите `sqlalchemy.url` равным вашему `DATABASE_URL` из `.env`.
    *   Убедитесь, что `script_location = %(here)s/alembic`.
2.  **Настройте `alembic/env.py`**:
    *   Импортируйте вашу базовую модель (например, `from my_new_service.app.models.product import Product`) и другие модели.
    *   Установите `target_metadata = Product.metadata` (или `BaseModelWithMeta.metadata`, если все ваши модели наследуются от нее и импортированы).
3.  **Создайте первую миграцию**:
    ```bash
    alembic -c my_new_service/alembic.ini revision -m "create product table"
    ```
    Отредактируйте сгенерированный файл миграции, чтобы он создавал нужные таблицы.
4.  **Примените миграцию** (после запуска БД):
    ```bash
    docker-compose exec my_new_service alembic -c /app/alembic.ini upgrade head
    ```

## Шаг 10: Docker

1.  **`Dockerfile`**: Скрипт уже создал базовый `Dockerfile` в директории сервиса. Убедитесь, что `EXPOSE` и `CMD` соответствуют порту вашего сервиса.
2.  **`docker-compose.yml` (корневой)**: Добавьте секцию для вашего нового сервиса:
    ```yaml
    services:
      # ... другие сервисы ...

      my_new_service: # Имя сервиса (snake_case)
        build:
          context: ./my_new_service # Путь к директории сервиса
          dockerfile: Dockerfile
        container_name: egrocery_my_new_service # Имя контейнера
        env_file:
          - ./my_new_service/.env
        volumes:
          - ./my_new_service:/app # Для разработки с live reload
        ports:
          - "8002:8002" # TODO: Замените на порт вашего сервиса (host:container)
        networks:
          - egrocery-net
        depends_on:
          db:
            condition: service_healthy
          redis: # Если нужен
            condition: service_healthy
          core: # Если зависит от core
            condition: service_started
        command: uvicorn my_new_service.app.main:app --host 0.0.0.0 --port 8002 --reload # TODO: Замените порт
        restart: unless-stopped
    ```

## Шаг 11: Тесты (`app/tests/`)

Скрипт создал `app/tests/conftest.py` и `app/tests/api/test_some_model_api.py`.
*   Доработайте `conftest.py`:
    *   Убедитесь, что `test_settings` корректно загружают `.env.test` вашего сервиса.
    *   Настройте фикстуру `manage_service_db_for_tests` для корректной инициализации БД и применения миграций (если у сервиса своя БД).
    *   Добавьте фикстуры для аутентификации, если ваши API эндпоинты защищены.
*   Напишите тесты для ваших API эндпоинтов в `test_some_model_api.py` (или переименуйте его).

После выполнения этих шагов ваш новый микросервис должен быть готов к запуску и дальнейшей разработке.