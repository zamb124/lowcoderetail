# core_sdk/exceptions.py


class CoreSDKError(Exception):
    """
    Базовый класс для всех пользовательских исключений, возникающих в core_sdk.
    Это позволяет ловить все ошибки SDK одним блоком except CoreSDKError, если нужно.
    """

    pass


class ConfigurationError(CoreSDKError):
    """
    Исключение, возникающее при ошибках конфигурации SDK или связанных компонентов.
    Например, если ModelRegistry не настроен, или в нем не найдена модель.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"Configuration Error: {self.message}"


class ServiceCommunicationError(CoreSDKError):
    """
    Исключение, возникающее при ошибках связи с удаленным сервисом через HTTP-клиент.
    Включает информацию об URL, статус-коде (если есть) и деталях ошибки.
    """

    def __init__(
        self, message: str, status_code: int | None = None, url: str | None = None
    ):
        """
        Инициализирует исключение ошибки связи.

        :param message: Основное сообщение об ошибке.
        :param status_code: HTTP статус-код ответа, если применимо (например, 404, 500).
        :param url: URL, при обращении к которому произошла ошибка.
        """
        self.message = message
        self.status_code = status_code
        self.url = url
        # Формируем полное сообщение для вывода
        full_message = "Service Communication Error"
        if self.url:
            full_message += f" accessing {self.url}"
        if self.status_code:
            full_message += f" (Status Code: {self.status_code})"
        full_message += f": {self.message}"
        super().__init__(full_message)

    def __str__(self) -> str:
        # super().__str__() уже содержит отформатированное сообщение
        return super().__str__()


class DetailException(Exception):
    """
    Простое исключение, которое можно использовать в валидаторах Pydantic
    для передачи конкретного сообщения об ошибке в HTTPException(400).
    Полезно, если стандартных сообщений Pydantic недостаточно.
    """

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


# Можно добавить другие специфичные исключения SDK по мере необходимости,
# например, AuthenticationError, AuthorizationError и т.д., наследуя их от CoreSDKError.

# class AuthenticationError(CoreSDKError):
#     """Ошибка аутентификации."""
#     pass


# class AuthorizationError(CoreSDKError):
#     """Ошибка авторизации (недостаточно прав)."""
#     pass
class RenderingError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)
