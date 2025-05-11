# core_sdk/tests/dependencies/test_auth_dependencies.py
from typing import Optional, Any

import pytest
import uuid
from unittest import mock

from fastapi import Request, HTTPException, Depends
from starlette.datastructures import Headers

from core_sdk.dependencies.auth import (
    get_optional_current_user,
    get_current_user,
    get_current_active_user,
    get_current_superuser,
    require_permission,
)
from core_sdk.schemas.auth_user import AuthenticatedUser

pytestmark = pytest.mark.asyncio

# --- Вспомогательные функции и фикстуры (без изменений) ---
def create_mock_request(user_in_scope: Optional[AuthenticatedUser] = None, other_in_scope: Optional[Any] = None) -> Request:
    scope = {"type": "http", "headers": Headers().raw, "user": user_in_scope}
    if other_in_scope is not None:
        scope["user"] = other_in_scope
    mock_req = mock.Mock(spec=Request)
    mock_req.user = scope["user"]
    mock_req.scope = scope
    return mock_req

@pytest.fixture
def active_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid.uuid4(),
        email="active@example.com",
        is_active=True,
        is_superuser=False,
        permissions=["orders:view", "products:edit"]
    )

@pytest.fixture
def inactive_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid.uuid4(),
        email="inactive@example.com",
        is_active=False,
        is_superuser=False,
        permissions=[]
    )

@pytest.fixture
def super_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid.uuid4(),
        email="super@example.com",
        is_active=True,
        is_superuser=True,
        permissions=[]
    )

@pytest.fixture
def active_user_no_perms() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid.uuid4(),
        email="noperms@example.com",
        is_active=True,
        is_superuser=False,
        permissions=[]
    )

# --- Тесты для get_optional_current_user (без изменений) ---
def test_get_optional_current_user_returns_user(active_user: AuthenticatedUser):
    request = create_mock_request(user_in_scope=active_user)
    user = get_optional_current_user(request)
    assert user == active_user

def test_get_optional_current_user_returns_none_if_no_user():
    request = create_mock_request(user_in_scope=None)
    user = get_optional_current_user(request)
    assert user is None

def test_get_optional_current_user_invalid_type_in_scope(caplog):
    request = create_mock_request(other_in_scope={"id": "not_a_user_object"})
    user = get_optional_current_user(request)
    assert user is None
    assert "Invalid object type found in request.user" in caplog.text

# --- Тесты для get_current_user (без изменений) ---
def test_get_current_user_returns_user(active_user: AuthenticatedUser):
    with mock.patch("core_sdk.dependencies.auth.get_optional_current_user", return_value=active_user):
        # При прямом вызове функции, которая ожидает аргумент от Depends,
        # мы должны передать этот аргумент явно.
        user_result = get_current_user(user=active_user)
        assert user_result == active_user

def test_get_current_user_raises_401_if_no_user():
    with mock.patch("core_sdk.dependencies.auth.get_optional_current_user", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(user=None)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Not authenticated"

# --- Тесты для get_current_active_user ---
def test_get_current_active_user_returns_user(active_user: AuthenticatedUser):
    with mock.patch("core_sdk.dependencies.auth.get_current_user", return_value=active_user):
        user_result = get_current_active_user(user=active_user)
        assert user_result == active_user

def test_get_current_active_user_raises_400_if_inactive(inactive_user: AuthenticatedUser):
    with mock.patch("core_sdk.dependencies.auth.get_current_user", return_value=inactive_user):
        with pytest.raises(HTTPException) as exc_info:
            get_current_active_user(user=inactive_user)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Inactive user"


# --- Тесты для get_current_superuser ---
def test_get_current_superuser_returns_user(super_user: AuthenticatedUser):
    with mock.patch("core_sdk.dependencies.auth.get_current_active_user", return_value=super_user):
        user_result = get_current_superuser(user=super_user)
        assert user_result == super_user

def test_get_current_superuser_raises_403_if_not_superuser(active_user: AuthenticatedUser):
    with mock.patch("core_sdk.dependencies.auth.get_current_active_user", return_value=active_user):
        with pytest.raises(HTTPException) as exc_info:
            get_current_superuser(user=active_user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "The user doesn't have enough privileges"

# --- Тесты для require_permission ---
async def test_require_permission_grants_access_if_has_permission(active_user: AuthenticatedUser):
    permission_checker_func = require_permission("orders:view")
    with mock.patch("core_sdk.dependencies.auth.get_current_active_user", return_value=active_user):
        user_result = await permission_checker_func(user=active_user)
        assert user_result == active_user

async def test_require_permission_grants_access_if_superuser(super_user: AuthenticatedUser):
    permission_checker_func = require_permission("some:specific:permission")
    with mock.patch("core_sdk.dependencies.auth.get_current_active_user", return_value=super_user):
        user_result = await permission_checker_func(user=super_user)
        assert user_result == super_user

async def test_require_permission_denies_access_if_no_permission(active_user_no_perms: AuthenticatedUser):
    permission_checker_func = require_permission("orders:delete")
    with mock.patch("core_sdk.dependencies.auth.get_current_active_user", return_value=active_user_no_perms):
        with pytest.raises(HTTPException) as exc_info:
            await permission_checker_func(user=active_user_no_perms)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Insufficient permissions"