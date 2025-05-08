# core_sdk/frontend/__init__.py
from .router import router as frontend_router
from .static import mount_static_files
from .templating import templates, get_templates, initialize_templates

# Можно экспортировать и другие полезные компоненты, если нужно
# from .renderer import ViewRenderer

__all__ = [
    "frontend_router",
    "mount_static_files",
    "templates",
    # "ViewRenderer",
]