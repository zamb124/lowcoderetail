# Настройка приложения (`core_sdk.app_setup`)

Модуль `core_sdk.app_setup` предоставляет инструменты для быстрой инициализации и конфигурации FastAPI приложений в рамках фреймворка.

## Основная фабрика `create_app_with_sdk_setup`

Эта функция является центральной точкой для создания экземпляра `FastAPI` с уже подключенными стандартными компонентами SDK.

::: core_sdk.app_setup.create_app_with_sdk_setup
    handler: python
    options:
      show_signature_annotations: true
      show_docstring_parameters: true
      show_docstring_description: true
      show_docstring_returns: true
      heading_level: 3

## Менеджер жизненного цикла `sdk_lifespan_manager`

Асинхронный контекстный менеджер, управляющий инициализацией и освобождением общих ресурсов SDK (база данных, HTTP-клиент, брокер задач) в рамках жизненного цикла FastAPI приложения.

::: core_sdk.app_setup.sdk_lifespan_manager
    handler: python
    options:
      show_signature_annotations: true
      show_docstring_parameters: true
      heading_level: 3

## Встроенные Middleware

При использовании `create_app_with_sdk_setup` автоматически (или по опциям) подключаются следующие middleware:

### `DBSessionMiddleware`
Управляет сессией базы данных для каждого запроса. Оборачивает запрос в контекстный менеджер `core_sdk.db.session.managed_session`.

::: core_sdk.middleware.middleware.DBSessionMiddleware
    handler: python
    options:
      heading_level: 4
      show_docstring_parameters: false # Конструктор простой, параметры не нужны
      members: # Показать только dispatch, если конструктор не интересен
        - dispatch

### `AuthMiddleware`
Проверяет JWT токен в заголовке `Authorization` и устанавливает `request.user`.
Конфигурируется через параметры `secret_key`, `algorithm`, `allowed_paths`, `api_prefix` в `create_app_with_sdk_setup` (если `enable_auth_middleware=True`).

::: core_sdk.middleware.auth.AuthMiddleware
    handler: python
    options:
      heading_level: 4
      show_docstring_parameters: true # Показать параметры конструктора
      members: # Показать конструктор и dispatch
        - __init__
        - dispatch

### `CORSMiddleware`
Стандартный middleware FastAPI для настройки CORS. Конфигурируется через параметр `BACKEND_CORS_ORIGINS` в настройках приложения (`BaseAppSettings`).