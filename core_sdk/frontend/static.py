# core_sdk/frontend/static.py
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR, STATIC_URL_PATH

logger = logging.getLogger("core_sdk.frontend.static")


def mount_static_files(app: FastAPI):
    """
    Монтирует директорию со статическими файлами SDK к приложению FastAPI.

    :param app: Экземпляр FastAPI приложения.
    """
    try:
        app.mount(STATIC_URL_PATH, StaticFiles(directory=STATIC_DIR), name="sdk_static")
        logger.info(
            f"SDK static files mounted at '{STATIC_URL_PATH}' from directory '{STATIC_DIR}'."
        )
    except Exception:
        logger.exception(
            f"Failed to mount SDK static files from '{STATIC_DIR}' at '{STATIC_URL_PATH}'."
        )
        # Решите, является ли это критической ошибкой
