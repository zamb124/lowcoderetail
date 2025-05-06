
# База данных (`core_sdk.db`)

Модуль `core_sdk.db` предоставляет инструменты для работы с базой данных PostgreSQL
с использованием SQLModel и SQLAlchemy.

## Ключевые компоненты

### `BaseModelWithMeta`
Базовый класс для всех моделей таблиц. Автоматически добавляет поля `id`, `lsn`, `created_at`, `updated_at`, `vars`, `company_id`.

::: core_sdk.db.base_model.BaseModelWithMeta
    handler: python
    options:
      heading_level: 3
      members_order: source
      # Можно скрыть некоторые унаследованные поля Pydantic, если они мешают
      # inherited_members: false
      # Или явно перечислить нужные поля
      members:
        - id
        - vars
        - created_at
        - updated_at
        - company_id
        - lsn
        - __init_subclass__ # Показать метод, если это важно

### Управление сессиями (`core_sdk.db.session`)

#### `init_db()`
Инициализирует движок базы данных и фабрику сессий. Должна вызываться один раз при старте приложения.

::: core_sdk.db.session.init_db
    handler: python
    options:
      heading_level: 4

#### `managed_session()`
Асинхронный контекстный менеджер для управления сессиями SQLAlchemy. Обеспечивает создание, предоставление и закрытие сессии, а также откат транзакции при ошибках.

::: core_sdk.db.session.managed_session
    handler: python
    options:
      heading_level: 4

#### `get_current_session()`
Возвращает текущую активную сессию SQLAlchemy из асинхронного контекста. Используется внутри блока `async with managed_session():`.

::: core_sdk.db.session.get_current_session
    handler: python
    options:
      heading_level: 4

#### `get_session_dependency()`
FastAPI зависимость для предоставления сессии SQLAlchemy в обработчиках запросов.

::: core_sdk.db.session.get_session_dependency
    handler: python
    options:
      heading_level: 4

#### `close_db()`
Корректно закрывает (disposes) глобальный движок SQLAlchemy. Должна вызываться при завершении работы приложения.

::: core_sdk.db.session.close_db
    handler: python
    options:
      heading_level: 4

#### `create_db_and_tables()`
Создает все таблицы в базе данных, определенные в метаданных SQLModel. Используется для инициализации или в тестовых окружениях.

::: core_sdk.db.session.create_db_and_tables
    handler: python
    options:
      heading_level: 4