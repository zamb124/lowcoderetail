# Аутентификация и Авторизация

Компоненты SDK для аутентификации и авторизации обеспечивают защиту API с использованием JWT токенов и проверку прав доступа.

## Middleware (`core_sdk.middleware.auth`)

### `AuthMiddleware`
FastAPI middleware, которое проверяет JWT Bearer токен в заголовке `Authorization`.
Если токен валиден, из него извлекается информация о пользователе и помещается в `request.scope["user"]` (доступно как `request.user`).

::: core_sdk.middleware.auth.AuthMiddleware
    handler: python
    options:
      heading_level: 3
      show_docstring_parameters: true # Показать параметры конструктора
      members: # Явно указываем, что хотим видеть конструктор и dispatch
        - __init__
        - dispatch

## Зависимости (`core_sdk.dependencies.auth`)
Эти FastAPI зависимости используются в эндпоинтах для получения информации об аутентифицированном пользователе и проверки прав.

### `get_optional_current_user`
Возвращает `AuthenticatedUser` или `None`, не вызывая ошибку.

::: core_sdk.dependencies.auth.get_optional_current_user
    handler: python
    options:
      heading_level: 4

### `get_current_user`
Возвращает `AuthenticatedUser`, вызывает ошибку 401, если пользователь не аутентифицирован.

::: core_sdk.dependencies.auth.get_current_user
    handler: python
    options:
      heading_level: 4

### `get_current_active_user`
Возвращает `AuthenticatedUser`, если он активен, иначе ошибка 400.

::: core_sdk.dependencies.auth.get_current_active_user
    handler: python
    options:
      heading_level: 4

### `get_current_superuser`
Возвращает `AuthenticatedUser`, если он активный суперпользователь, иначе ошибка 403.

::: core_sdk.dependencies.auth.get_current_superuser
    handler: python
    options:
      heading_level: 4

### `require_permission`
Фабрика зависимостей для проверки наличия у пользователя конкретного права доступа.

::: core_sdk.dependencies.auth.require_permission
    handler: python
    options:
      heading_level: 4

## Безопасность и JWT (`core_sdk.security`)
Модуль для работы с паролями и JWT токенами.

### `get_password_hash`
Хеширует пароль с использованием bcrypt.

::: core_sdk.security.get_password_hash
    handler: python
    options:
      heading_level: 4

### `verify_password`
Проверяет соответствие пароля хешу.

::: core_sdk.security.verify_password
    handler: python
    options:
      heading_level: 4

### `create_access_token`
Создает JWT access токен.

::: core_sdk.security.create_access_token
    handler: python
    options:
      heading_level: 4

### `create_refresh_token`
Создает JWT refresh токен.

::: core_sdk.security.create_refresh_token
    handler: python
    options:
      heading_level: 4

### `verify_token`
Декодирует и валидирует JWT токен.

::: core_sdk.security.verify_token
    handler: python
    options:
      heading_level: 4

## Схемы (`core_sdk.schemas.auth_user`, `core_sdk.schemas.token`)

### `AuthenticatedUser`
Pydantic схема, представляющая аутентифицированного пользователя, извлеченного из токена.

::: core_sdk.schemas.auth_user.AuthenticatedUser
    handler: python
    options:
      heading_level: 3
      members_order: source # Порядок полей как в коде
      members: # Явно перечисляем поля и методы для отображения
        - id
        - company_id
        - email
        - is_active
        - is_superuser
        - permissions
        - has_permission

### `Token`
Схема ответа API при успешной аутентификации (содержит access и refresh токены).

::: core_sdk.schemas.token.Token
    handler: python
    options:
      heading_level: 3
      members_order: source

### `TokenPayload`
Схема данных (claims), содержащихся внутри JWT токена.

::: core_sdk.schemas.token.TokenPayload
    handler: python
    options:
      heading_level: 3
      members_order: source