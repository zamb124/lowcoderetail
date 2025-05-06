# core_sdk/schemas/__init__.py

# Импортируем и ре-экспортируем модули или классы

# Пример ре-экспорта модулей:
from . import token
from . import user # Если UserRead переехал в SDK
from . import i18n # <--- ДОБАВЬТЕ ЭТУ СТРОКУ
# from . import group # Если GroupRead переехал в SDK
# from . import permission # Если PermissionRead переехал в SDK
# from . import company # Если CompanyRead переехал в SDK

# Пример ре-экспорта конкретных классов:
# from .token import Token, TokenPayload
# from .user import UserRead
# from .i18n import Language, Country, Currency # <--- Или так