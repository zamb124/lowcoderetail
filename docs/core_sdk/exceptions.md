# Исключения (`core_sdk.exceptions`)

Модуль `core_sdk.exceptions` определяет базовые классы исключений, используемые в SDK.
Это позволяет централизованно обрабатывать ошибки, специфичные для SDK.

## `CoreSDKError`
Базовый класс для всех пользовательских исключений, возникающих в `core_sdk`.

::: core_sdk.exceptions.CoreSDKError
    handler: python
    options:
      heading_level: 3

## `ConfigurationError`
Исключение, возникающее при ошибках конфигурации SDK или связанных компонентов (например, `ModelRegistry` не настроен).

::: core_sdk.exceptions.ConfigurationError
    handler: python
    options:
      heading_level: 3

## `ServiceCommunicationError`
Исключение, возникающее при ошибках связи с удаленным сервисом через HTTP-клиент.

::: core_sdk.exceptions.ServiceCommunicationError
    handler: python
    options:
      heading_level: 3
      members: # Показать атрибуты
        - message
        - status_code
        - url

## `DetailException`
Простое исключение для передачи конкретного сообщения об ошибке в `HTTPException(400)` из валидаторов Pydantic.

::: core_sdk.exceptions.DetailException
    handler: python
    options:
      heading_level: 3