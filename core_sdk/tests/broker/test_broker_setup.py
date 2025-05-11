# core_sdk/tests/broker/test_broker_setup.py
import pytest
import os
import sys
import importlib
from unittest import mock
import logging

from taskiq import InMemoryBroker
from taskiq.abc import AsyncBroker
from taskiq_redis import RedisStreamBroker, RedisAsyncResultBackend

# Импортируем модуль как псевдоним для перезагрузки
import core_sdk.broker.setup as broker_setup_module


# --- Вспомогательные функции ---
def reload_broker_setup_module():
    # logger перед перезагрузкой, чтобы убедиться, что он существует
    # и мы можем на него ссылаться для caplog.at_level
    _ = logging.getLogger("core_sdk.broker.setup")

    importlib.reload(broker_setup_module)

    return broker_setup_module.broker


# --- Тесты ---


def test_broker_is_inmemory_when_env_is_test(monkeypatch: pytest.MonkeyPatch, caplog):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("REDIS_URL", "redis://some-redis-that-might-not-exist:6379/0")

    # Используем caplog.at_level как контекстный менеджер
    with caplog.at_level(logging.INFO, logger="core_sdk.broker.setup"):
        broker = reload_broker_setup_module()

    assert isinstance(broker, InMemoryBroker)
    print(f"CAPLOG TEXT for ENV=test: {caplog.text}")
    assert "Using InMemoryBroker for 'test' environment." in caplog.text
    # Проверим, что другие сообщения тоже есть, если они были
    assert "Initializing InMemoryBroker as a potential broker." in caplog.text


def test_broker_is_inmemory_when_env_is_not_set(
    monkeypatch: pytest.MonkeyPatch, caplog
):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    with caplog.at_level(logging.INFO, logger="core_sdk.broker.setup"):
        broker = reload_broker_setup_module()

    assert isinstance(broker, InMemoryBroker)
    print(f"CAPLOG TEXT for ENV not set: {caplog.text}")
    assert "Using InMemoryBroker (ENV not set or not 'prod')." in caplog.text


def test_broker_is_inmemory_when_env_is_dev(monkeypatch: pytest.MonkeyPatch, caplog):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("REDIS_URL", "redis://some-redis-that-might-not-exist:6379/0")

    with caplog.at_level(logging.INFO, logger="core_sdk.broker.setup"):
        broker = reload_broker_setup_module()

    assert isinstance(broker, InMemoryBroker)
    print(f"CAPLOG TEXT for ENV=dev: {caplog.text}")
    assert "Using InMemoryBroker for 'dev' environment." in caplog.text


@mock.patch("taskiq_redis.RedisStreamBroker")
@mock.patch("taskiq_redis.RedisAsyncResultBackend")
def test_broker_is_redis_when_env_is_prod_and_redis_available(
    mock_redis_backend_cls: mock.MagicMock,
    mock_redis_broker_cls: mock.MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog,
):
    monkeypatch.setenv("ENV", "prod")
    test_redis_url = "redis://mocked-redis:1234/1"
    monkeypatch.setenv("REDIS_URL", test_redis_url)

    mock_backend_instance = mock.Mock(spec=RedisAsyncResultBackend)
    mock_redis_backend_cls.return_value = mock_backend_instance
    mock_base_broker_instance = mock.Mock(spec=RedisStreamBroker)
    mock_broker_with_backend = mock.Mock(spec=AsyncBroker)
    mock_base_broker_instance.with_result_backend.return_value = (
        mock_broker_with_backend
    )
    mock_redis_broker_cls.return_value = mock_base_broker_instance

    with caplog.at_level(logging.INFO, logger="core_sdk.broker.setup"):
        broker = reload_broker_setup_module()

    mock_redis_backend_cls.assert_called_once_with(redis_url=test_redis_url)
    mock_redis_broker_cls.assert_called_once_with(url=test_redis_url)
    mock_base_broker_instance.with_result_backend.assert_called_once_with(
        mock_backend_instance
    )

    assert broker is mock_broker_with_backend
    print(f"CAPLOG TEXT for ENV=prod, Redis OK: {caplog.text}")
    assert "Using Redis Broker for 'prod' environment." in caplog.text
    assert "Redis broker configured successfully." in caplog.text


@mock.patch(
    "taskiq_redis.RedisStreamBroker", side_effect=Exception("Redis connection failed")
)
@mock.patch("taskiq_redis.RedisAsyncResultBackend")
def test_broker_fallbacks_to_inmemory_if_redis_fails_on_prod(
    mock_redis_backend_cls: mock.MagicMock,
    mock_redis_broker_cls_with_error: mock.MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog,
):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("REDIS_URL", "redis://unreachable-redis:6379/0")

    # Устанавливаем уровень захвата для caplog на ERROR, чтобы поймать и CRITICAL, и ERROR
    with caplog.at_level(
        logging.ERROR, logger="core_sdk.broker.setup"
    ):  # <--- ИЗМЕНЕНИЕ УРОВНЯ
        broker = reload_broker_setup_module()

    assert isinstance(broker, InMemoryBroker)

    # Выведем все записи для отладки
    print("Captured log records for ENV=prod, Redis Fail:")
    for record in caplog.records:
        print(f"  {record.levelname}: {record.message}")

    # Проверяем критическое сообщение об ошибке
    assert any(
        "FAILED to initialize Redis Broker" in record.message
        and record.levelname == "CRITICAL"
        for record in caplog.records
    ), "CRITICAL 'FAILED to initialize' message not found"

    # Проверяем сообщение об ошибке из side_effect (оно будет частью CRITICAL сообщения)
    assert any(
        "Redis connection failed" in record.message for record in caplog.records
    ), "Specific 'Redis connection failed' message not found"

    # Проверяем сообщение о fallback (уровень ERROR)
    assert any(
        "Falling back to InMemoryBroker" in record.message
        and record.levelname == "ERROR"
        for record in caplog.records
    ), "ERROR 'Falling back to InMemoryBroker' message not found"


@mock.patch("taskiq_redis.RedisStreamBroker")
@mock.patch("taskiq_redis.RedisAsyncResultBackend")
def test_broker_fallbacks_if_redis_url_not_set_on_prod(
    mock_redis_backend_cls: mock.MagicMock,
    mock_redis_broker_cls: mock.MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog,
):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.delenv("REDIS_URL", raising=False)

    mock_redis_broker_cls.side_effect = Exception(
        "Cannot connect to default localhost Redis"
    )

    with caplog.at_level(
        logging.INFO, logger="core_sdk.broker.setup"
    ):  # Ловим INFO и выше
        broker = reload_broker_setup_module()

    assert isinstance(broker, InMemoryBroker)
    print(f"CAPLOG TEXT for ENV=prod, REDIS_URL not set: {caplog.text}")
    assert "FAILED to initialize Redis Broker" in caplog.text
    assert "redis://localhost:6379/0" in caplog.text
    assert "Cannot connect to default localhost Redis" in caplog.text
    assert "Falling back to InMemoryBroker" in caplog.text
