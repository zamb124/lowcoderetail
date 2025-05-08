# apps/frontend/app/api/__init__.py
# Если у BFF будут свои API эндпоинты (кроме UI из SDK), их роутеры импортируются сюда
# Например:
# from .auth import router as auth_router

# Пока оставляем пустым или только с импортом базового роутера SDK
from core_sdk.frontend import frontend_router as sdk_frontend_router

# Можно создать главный роутер и включить в него SDK роутер, если нужны и свои
# from fastapi import APIRouter
# base_router = APIRouter()
# base_router.include_router(sdk_frontend_router, prefix="/ui")
# base_router.include_router(auth_router, prefix="/auth") # Пример своего роутера

# Напрямую экспортируем роутер SDK, если своих нет
base_router = sdk_frontend_router

__all__ = ["base_router"]