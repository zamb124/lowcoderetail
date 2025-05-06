# Общие схемы (`core_sdk.schemas`)

Модуль `core_sdk.schemas` содержит Pydantic/SQLModel схемы, которые являются общими для различных частей SDK или могут использоваться для межсервисного взаимодействия.

## Аутентификация и Токены

*   `core_sdk.schemas.auth_user.AuthenticatedUser`: Описана в разделе [Аутентификация и Авторизация](./auth_security.md).
*   `core_sdk.schemas.token.Token`: Описана в разделе [Аутентификация и Авторизация](./auth_security.md).
*   `core_sdk.schemas.token.TokenPayload`: Описана в разделе [Аутентификация и Авторизация](./auth_security.md).

## Пагинация

### `PaginatedResponse`
Стандартная схема ответа для пагинированных списков, используемых, например, в `BaseDataAccessManager.list()` и `CRUDRouterFactory`.

::: core_sdk.schemas.pagination.PaginatedResponse
    handler: python
    options:
      heading_level: 3
      members_order: source
      # Показать поля
      members:
        - items
        - next_cursor
        - limit
        - count

## Пользователь (для межсервисного взаимодействия)

### `UserRead` (из `core_sdk.schemas.user`)
Базовая схема для представления данных пользователя, безопасная для передачи между сервисами.
Не содержит хеш пароля или другую чувствительную информацию.

::: core_sdk.schemas.user.UserRead
    handler: python
    options:
      heading_level: 3
      members_order: source

## I18n (Интернационализация)

Схемы для представления языков, стран и валют, используемые `core_sdk.services.i18n_service`.

::: core_sdk.schemas.i18n.Language
    handler: python
    options:
      heading_level: 3
::: core_sdk.schemas.i18n.Country
    handler: python
    options:
      heading_level: 3
::: core_sdk.schemas.i18n.Currency
    handler: python
    options:
      heading_level: 3