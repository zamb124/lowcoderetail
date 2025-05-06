# Доступ к данным (`core_sdk.data_access`)

Модуль `core_sdk.data_access` предоставляет абстракции для унифицированного доступа к данным, независимо от их местоположения (локальная БД или удаленный сервис).

## `ModelRegistry`
Центральный реестр для регистрации моделей данных и связанной с ними информации (менеджеры, схемы, конфигурация доступа).

::: core_sdk.registry.ModelRegistry
    handler: python
    options:
      heading_level: 3
      members_order: source
      # Показать только публичные методы
      members:
        - register
        - register_local
        - register_remote
        - get_model_info
        - rebuild_models
        - clear
        - is_configured

### `RemoteConfig`
Pydantic модель для конфигурации доступа к удаленной модели.

::: core_sdk.registry.RemoteConfig
    handler: python
    options:
      heading_level: 4

### `ModelInfo`
Pydantic модель, хранящая информацию о зарегистрированной модели.

::: core_sdk.registry.ModelInfo
    handler: python
    options:
      heading_level: 4

## `BaseDataAccessManager`
Базовый класс для менеджеров доступа к локальным данным (в БД текущего сервиса). Предоставляет стандартные CRUD операции.

::: core_sdk.data_access.base_manager.BaseDataAccessManager
    handler: python
    options:
      heading_level: 3
      # Показать основные CRUD методы и хуки
      members:
        - list
        - get
        - create
        - update
        - delete
        - session # property
        - broker # property
        - _get_filter_class
        - _prepare_for_create
        - _prepare_for_update
        - _prepare_for_delete
        - _handle_integrity_error

## `RemoteDataAccessManager`
Менеджер для доступа к данным, расположенным в удаленных сервисах. Использует `RemoteServiceClient`.

::: core_sdk.data_access.remote_manager.RemoteDataAccessManager
    handler: python
    options:
      heading_level: 3
      members: # Основные CRUD
        - get
        - list
        - create
        - update
        - delete

## `DataAccessManagerFactory` и `get_dam_factory`
Фабрика для создания и предоставления экземпляров `DataAccessManager` (локальных или удаленных) на основе конфигурации в `ModelRegistry`.

::: core_sdk.data_access.manager_factory.DataAccessManagerFactory
    handler: python
    options:
      heading_level: 3
      members:
        - get_manager

::: core_sdk.data_access.manager_factory.get_dam_factory
    handler: python
    options:
      heading_level: 3

## `BrokerTaskProxy`
Прокси для асинхронного выполнения операций DAM через брокер задач Taskiq.

::: core_sdk.data_access.broker_proxy.BrokerTaskProxy
    handler: python
    options:
      heading_level: 3
      # __getattr__ и task_kicker_and_waiter являются ключевыми
      members:
        - __getattr__

## HTTP Клиенты и утилиты (`core_sdk.data_access.common`, `core_sdk.clients`)

### `RemoteServiceClient`
Базовый HTTP-клиент для взаимодействия с удаленными CRUD API.

::: core_sdk.clients.base.RemoteServiceClient
    handler: python
    options:
      heading_level: 3
      members: # Основные CRUD и управление клиентом
        - get
        - list
        - create
        - update
        - delete
        - close
        - _request
        - _get_auth_headers

### `global_http_client_lifespan`
Менеджер жизненного цикла для глобального `httpx.AsyncClient`.

::: core_sdk.data_access.common.global_http_client_lifespan
    handler: python
    options:
      heading_level: 3

### `get_global_http_client`
Возвращает глобальный экземпляр `httpx.AsyncClient`.

::: core_sdk.data_access.common.get_global_http_client
    handler: python
    options:
      heading_level: 3

### `get_optional_token`
FastAPI зависимость для извлечения Bearer токена из запроса.

::: core_sdk.data_access.common.get_optional_token
    handler: python
    options:
      heading_level: 3