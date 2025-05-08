# core_sdk/frontend/exceptions.py
from core_sdk.exceptions import CoreSDKError

class FrontendError(CoreSDKError):
    """Базовый класс для ошибок фронтенд-движка SDK."""
    pass

class RenderingError(FrontendError):
    """Ошибка во время рендеринга шаблона или подготовки контекста."""
    pass

class FieldTypeError(FrontendError):
    """Ошибка определения или обработки типа поля."""
    pass