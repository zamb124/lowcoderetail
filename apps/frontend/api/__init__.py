# apps/frontend/app/api/__init__.py
from fastapi import APIRouter

from .auth import router as auth_router
from .ui import router as ui_router
from core_sdk.frontend import router as sdk_crud_router # CRUD UI из SDK

# Главный роутер API для BFF
# Префикс API_V1_STR для BFF теперь пустой, поэтому роуты будут доступны по /auth, /ui и т.д.
# sdk_crud_router уже имеет свой префикс /ui, поэтому его можно включить без дополнительного префикса
# или с префиксом, если нужно отделить его от UI фрагментов BFF.
# Для ясности, можно дать ему префикс, например, /sdk-ui
bff_api_router = APIRouter()

bff_api_router.include_router(auth_router) # Будет /auth/...
bff_api_router.include_router(ui_router)   # Будет / (root), /login, /ui/header, /ui/dashboard и т.д.
# sdk_crud_router отвечает за /ui/view/{model}/{id}, /ui/form/{model} и т.д.
# Если ui_router уже имеет /ui префикс для фрагментов, то для sdk_crud_router можно оставить его префикс /ui
# или изменить, чтобы избежать конфликтов, если они есть.
# В данном случае ui_router имеет /ui/dashboard, а sdk_crud_router /ui/view/... - они не конфликтуют.
bff_api_router.include_router(sdk_crud_router) # Будет /sdk/view, /sdk/form и т.д.

__all__ = ["bff_api_router"]