# core_sdk/frontend/templating.py
import json
import logging
import os
from datetime import datetime
from typing import List, Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.templating import Jinja2Templates

# Путь к шаблонам внутри SDK остается как базовый
SDK_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "templates"
)

logger = logging.getLogger("core_sdk.frontend.templating")

# Глобальная переменная для хранения экземпляра Jinja2Templates
# Это позволит инициализировать его один раз при старте приложения
templates: Optional[Jinja2Templates] = None


def setup_jinja_env(template_dirs: List[str]) -> Environment:
    """
    Создает и настраивает окружение Jinja2 с поддержкой
    нескольких директорий для переопределения.
    Директории в начале списка имеют приоритет.
    """
    if not template_dirs:
        raise ValueError("At least one template directory must be provided.")

    logger.debug(f"Setting up Jinja2 environment with loaders for: {template_dirs}")
    # FileSystemLoader принимает список путей
    env = Environment(
        loader=FileSystemLoader(template_dirs),  # Сервис-директория должна быть первой!
        autoescape=select_autoescape(["html", "xml"]),
        enable_async=False,
    )

    # --- Добавьте ваши кастомные фильтры/глобальные функции Jinja здесь ---
    # Пример фильтра (может быть в отдельном файле и импортирован)
    def get_field_type(field_ctx):
        # Простая заглушка, реальная логика может быть сложнее
        return field_ctx.get("field_type", "text")

    env.filters["get_field_type"] = get_field_type
    env.filters["tovals"] = json.dumps
    env.filters["hasattr"] = hasattr
    # --------------------------------------------------------------------

    logger.info(
        f"Jinja2 environment configured successfully with search path: {template_dirs}"
    )
    return env


def initialize_templates(service_template_dir: str):
    """
    Инициализирует глобальный объект `templates`, настраивая пути поиска.
    Вызывается при старте приложения frontend.

    :param service_template_dir: Путь к директории шаблонов сервиса (e.g., 'apps/frontend/app/templates')
    """
    global templates
    if templates is not None:
        logger.warning("Templates already initialized. Skipping re-initialization.")
        return

    # Убедимся, что директория сервиса существует
    if not os.path.isdir(service_template_dir):
        logger.warning(
            f"Service template directory '{service_template_dir}' not found. Only SDK templates will be available."
        )
        search_paths = [SDK_TEMPLATES_DIR]
    else:
        # Директория сервиса имеет приоритет
        search_paths = [service_template_dir, SDK_TEMPLATES_DIR]

    try:
        jinja_env = setup_jinja_env(search_paths)
        templates = Jinja2Templates(env=jinja_env)
        templates.env.globals["now"] = datetime.now
        logger.info("Global Jinja2Templates instance initialized.")
    except Exception as e:
        logger.critical("Failed to initialize Jinja2Templates.", exc_info=True)
        raise RuntimeError("Failed to initialize templates") from e


# Функция для получения инициализированного объекта templates
def get_templates() -> Jinja2Templates:
    if templates is None:
        # Это не должно происходить при правильной инициализации приложения
        logger.error("Templates accessed before initialization!")
        raise RuntimeError(
            "Templates not initialized. Call initialize_templates() during app startup."
        )
    return templates
