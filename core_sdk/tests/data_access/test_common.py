# core_sdk/tests/data_access/test_common.py
from typing import Optional

import pytest
import httpx
from unittest import mock  # Для мокирования Request и App

from fastapi import FastAPI, Request as FastAPIRequest  # Для создания мок-объектов
from starlette.datastructures import Headers  # Для создания мок-заголовков

from core_sdk.data_access.common import (
    get_optional_token,
    app_http_client_lifespan,
    get_http_client_from_state,
    # get_global_http_client # Это просто алиас для get_http_client_from_state
)

pytestmark = pytest.mark.asyncio

# --- Тесты для get_optional_token ---


@pytest.mark.parametrize(
    "auth_header_value, expected_token",
    [
        ("Bearer testtoken123", "testtoken123"),
        ("bearer testtoken456", "testtoken456"),  # Нижний регистр
        ("Token testtoken789", None),  # Не Bearer схема
        ("Bearer", None),  # Bearer без токена
        (None, None),  # Нет заголовка
        ("", None),  # Пустой заголовок
        ("InvalidToken", None),  # Неправильный формат
    ],
)
async def test_get_optional_token(
    auth_header_value: Optional[str], expected_token: Optional[str]
):
    mock_request = mock.Mock(spec=FastAPIRequest)
    if auth_header_value is not None:
        mock_request.headers = Headers({"Authorization": auth_header_value})
    else:
        mock_request.headers = Headers({})  # Пустые заголовки

    token = await get_optional_token(mock_request)  # get_optional_token теперь async
    assert token == expected_token


# --- Тесты для app_http_client_lifespan и get_http_client_from_state ---


@pytest.fixture
def mock_app() -> FastAPI:
    """Создает мок-экземпляр FastAPI приложения."""
    app = FastAPI()
    # Убедимся, что app.state существует и является словарем или объектом с атрибутами
    if not hasattr(app, "state"):
        app.state = (
            mock.Mock()
        )  # Простой мок, если FastAPI не создает state по умолчанию
        app.state.http_client = None  # Инициализируем атрибут
    elif not isinstance(app.state, dict) and not hasattr(app.state, "http_client"):
        # Если app.state есть, но это не словарь и нет атрибута, пытаемся установить
        try:
            app.state.http_client = None
        except AttributeError:  # Если app.state не позволяет устанавливать атрибуты (например, простой объект)
            # Заменяем на мок, который позволяет
            original_state = app.state
            app.state = mock.Mock()
            app.state.http_client = None
            # Копируем другие атрибуты, если они были
            for attr_name, attr_value in original_state.__dict__.items():
                if not hasattr(app.state, attr_name):
                    setattr(app.state, attr_name, attr_value)

    return app


async def test_app_http_client_lifespan_manages_client(mock_app: FastAPI):
    assert getattr(mock_app.state, "http_client", None) is None

    async with app_http_client_lifespan(mock_app):
        client_in_state = getattr(mock_app.state, "http_client", None)
        assert client_in_state is not None
        assert isinstance(client_in_state, httpx.AsyncClient)
        assert not client_in_state.is_closed

    # После выхода из контекста
    client_after_lifespan = getattr(mock_app.state, "http_client", None)
    assert client_after_lifespan is None  # Должен быть очищен

    # Проверяем, что клиент, который был в state, действительно закрыт
    # Это можно сделать, если бы мы сохранили ссылку на client_in_state,
    # но app_http_client_lifespan не возвращает его.
    # Мы можем проверить, что он был закрыт, если бы мокировали httpx.AsyncClient.aclose()
    # Но для простоты пока достаточно проверки, что он удален из app.state.


async def test_get_http_client_from_state_success(mock_app: FastAPI):
    # Имитируем, что клиент уже в app.state (например, после app_http_client_lifespan)
    real_client = httpx.AsyncClient()
    mock_app.state.http_client = real_client

    mock_request = mock.Mock(spec=FastAPIRequest)
    mock_request.app = mock_app  # Привязываем мок-приложение к мок-запросу

    retrieved_client = await get_http_client_from_state(mock_request)
    assert retrieved_client is real_client
    await real_client.aclose()  # Закрываем созданный клиент


async def test_get_http_client_from_state_not_found(mock_app: FastAPI):
    # Убедимся, что клиента нет в app.state
    if hasattr(mock_app.state, "http_client"):
        mock_app.state.http_client = None

    mock_request = mock.Mock(spec=FastAPIRequest)
    mock_request.app = mock_app

    retrieved_client = await get_http_client_from_state(mock_request)
    assert retrieved_client is None


async def test_app_http_client_lifespan_handles_no_initial_state_attr(
    mock_app: FastAPI,
):
    # Проверяем случай, когда у app.state изначально нет атрибута http_client
    if hasattr(mock_app.state, "http_client"):
        del mock_app.state.http_client  # Удаляем, если есть

    async with app_http_client_lifespan(mock_app):
        assert hasattr(mock_app.state, "http_client")
        assert isinstance(mock_app.state.http_client, httpx.AsyncClient)

    assert (
        getattr(mock_app.state, "http_client", "AttributeMissing") is None
    )  # Должен быть None или отсутствовать
