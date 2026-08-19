"""Shared fixtures for Make.com Connector PST (Plausible Scenario Testing).

Mirrors n8n Connector's tests/conftest.py: imperal_sdk.testing.MockContext +
MockSecretStore give us the REAL handlers.py / make_client.py code path
(real HTTP call construction, real header/auth scheme, real zone URLs,
real error mapping) against a controlled fake HTTP backend.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def ctx():
    from imperal_sdk.testing import MockContext, MockSecretStore

    mock = MockContext()
    mock.secrets = MockSecretStore({})
    return mock


@pytest.fixture
def ctx_connected(ctx):
    """Same as `ctx` but with Make credentials already saved (token + the
    zone discover_zone would have found)."""
    from imperal_sdk.testing import MockSecretStore
    ctx.secrets = MockSecretStore({
        "make_api_token": "test-make-token-9f21",
        "make_zone": "eu1.make.com",
    })
    return ctx


@pytest.fixture
def ctx_scoped(ctx_connected):
    """Same as `ctx_connected` but with a team already selected -- the
    state most list_*/data_store/hook functions require (they error with
    MAKE_NO_TEAM_SCOPE otherwise). Seeds MockStore._data directly (a plain
    sync dict) rather than awaiting store.create from a sync fixture --
    avoids fighting pytest-asyncio's own event loop for the actual test."""
    ctx_connected.store._data.setdefault("app_settings", {})["seed-team-scope"] = {
        "kind": "team_scope_setting", "team_id": 555,
    }
    return ctx_connected
