#!/usr/bin/env python3
"""Regression checks for aTrust route switches during QR login."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.api import login as login_api  # noqa: E402
from app.core.auth_adapter import AuthAdapter, LoginResult  # noqa: E402


def test_cas_session_retries_after_route_switch() -> None:
    adapter = AuthAdapter.__new__(AuthAdapter)
    calls: list[dict] = []

    async def fake_get(url: str, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise httpx.ConnectError("route changed", request=httpx.Request("GET", url))
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None)

    adapter._get = fake_get  # type: ignore[method-assign]
    ready = asyncio.run(adapter._prepare_cas_session("https://matrix.example/"))
    assert ready is True
    assert len(calls) == 2
    assert calls[0]["follow_redirects"] is False


def test_status_recovers_persisted_success() -> None:
    original_store = login_api.cookie_store

    class FakeStore:
        @staticmethod
        def load(session_id: str):
            return {"user": {"name": "tester"}}

    login_api.cookie_store = FakeStore()  # type: ignore[assignment]
    try:
        result = asyncio.run(login_api.login_status("session", "ticket"))
    finally:
        login_api.cookie_store = original_store

    assert result.status == "success"
    assert result.user == {"name": "tester"}


def test_status_does_not_leak_save_failure_as_http_500() -> None:
    original_store = login_api.cookie_store
    original_adapter = login_api.auth_adapter

    class FakeStore:
        @staticmethod
        def load(session_id: str):
            return None

        @staticmethod
        def save(session_id: str, cookies: dict, user: dict):
            raise OSError("disk temporarily unavailable")

    class FakeAdapter:
        @staticmethod
        async def poll_status(ticket: str):
            return LoginResult(True, cookies={"example": {}}, user={"name": "tester"})

    login_api.cookie_store = FakeStore()  # type: ignore[assignment]
    login_api.auth_adapter = FakeAdapter()  # type: ignore[assignment]
    try:
        result = asyncio.run(login_api.login_status("session", "ticket"))
    finally:
        login_api.cookie_store = original_store
        login_api.auth_adapter = original_adapter

    assert result.status == "waiting"


if __name__ == "__main__":
    test_cas_session_retries_after_route_switch()
    test_status_recovers_persisted_success()
    test_status_does_not_leak_save_failure_as_http_500()
    print("login resilience: all checks passed")
