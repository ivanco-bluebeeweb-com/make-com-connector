"""Plausible Scenario Testing (PST) for Make.com Connector.

Method: Docs/session-notes/SCENARIO_TESTING_STANDARD.md. Persona used
throughout: the Make account owner (PREPARATION.md section 3) -- the same
person who connects Imperal, sees/runs her own scenarios, and wires an
outgoing webhook from Imperal into Make. Single functional role; scenario
variety comes from DATA classes (empty/typical/boundary/invalid/exotic
account states -- multi-zone discovery, missing scopes, router-branch
blueprints, concurrent blueprint edits) and the 5 required branches.

Every test calls the REAL handlers.py chat functions with REAL params
models, through imperal_sdk.testing.MockContext -- not a re-implementation
of the logic under a different name.
"""
from __future__ import annotations

import pytest

import handlers as h
from schemas import (
    ConnectMakeParams, NoParams, SelectTeamParams,
    ListScenariosParams, RunScenarioParams, SetScenarioActiveParams,
    SetOutgoingWebhookParams, SendWebhookEventParams,
    GetScenarioBlueprintParams,
    ListConnectionsParams, DeleteConnectionParams, RenameConnectionParams,
    VerifyConnectionParams,
    ListDataStoresParams, CreateDataStoreParams, DeleteDataStoreParams,
    ListHooksParams, SetHookEnabledParams, DeleteHookParams, CreateHookParams,
    ListIncompleteExecutionsParams, RetryIncompleteExecutionParams,
    DeleteIncompleteExecutionsParams,
    BulkSetScenarioActiveParams, BulkRunScenariosParams,
    BulkDeleteConnectionsParams, BulkDeleteHooksParams,
    PreviewUpdateBlueprintModuleParams, ApplyUpdateBlueprintModuleParams,
    CreateScenarioParams, DeleteScenarioParams, RestoreScenarioParams,
    CloneScenarioParams, UpdateSchedulingParams,
    ListBuildtimeVariablesParams, SetBuildtimeVariableParams,
    DeleteBuildtimeVariableParams, GetScenarioUsageParams,
    ListScenarioLogsParams, GetExecutionDetailsParams, StopExecutionParams,
    PreviewAddBlueprintModuleParams, ApplyAddBlueprintModuleParams,
    PreviewDeleteBlueprintModuleParams, ApplyDeleteBlueprintModuleParams,
    ListOrganizationsParams, ListTeamMembersParams,
    ListApiTokensParams, CreateApiTokenParams, DeleteApiTokenParams,
)


# ═══════════════════════════════════════════════════════════════════════
# BRANCH 1 -- HAPPY PATH (connection + zone discovery)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_connect_happy_path_first_zone_tried(ctx):
    """Given a valid token that eu1 (the first probed zone) accepts,
    connect_make must save that zone and not probe the others."""
    ctx.http.mock_get("eu1.make.com/api/v2/users/me", {"authUser": {"name": "Marina", "email": "marina@agency.test"}}, status=200)
    result = await h.connect_make(ctx, ConnectMakeParams(api_token="tok-good"))
    assert result.error is None
    assert await ctx.secrets.get("make_api_token") == "tok-good"
    assert await ctx.secrets.get("make_zone") == "eu1.make.com"


@pytest.mark.asyncio
async def test_connect_zone_discovery_falls_through_to_us1(ctx):
    """Given a token that eu1/eu2/us1 all reject (401) but us2 accepts,
    discover_zone must keep probing and land on the actual zone -- not
    give up after the first rejection."""
    ctx.http.mock_get("eu1.make.com/api/v2/users/me", {}, status=401)
    ctx.http.mock_get("eu2.make.com/api/v2/users/me", {}, status=401)
    ctx.http.mock_get("us1.make.com/api/v2/users/me", {}, status=401)
    ctx.http.mock_get("us2.make.com/api/v2/users/me", {"authUser": {"name": "Marina"}}, status=200)
    result = await h.connect_make(ctx, ConnectMakeParams(api_token="tok-us2-only"))
    assert result.error is None
    assert await ctx.secrets.get("make_zone") == "us2.make.com"


@pytest.mark.asyncio
async def test_list_scenarios_typical_team_with_router_scenario(ctx_scoped):
    """Given a team with 2 scenarios (one plain, one with a router branch),
    list_scenarios must report both without needing the blueprint itself."""
    ctx_scoped.http.mock_get("/api/v2/scenarios", {
        "scenarios": [
            {"id": 100, "name": "Lead Sync", "teamId": 555, "isActive": True, "isPaused": False, "isinvalid": False, "lastEdit": "2026-08-01T10:00:00Z"},
            {"id": 101, "name": "Router Demo", "teamId": 555, "isActive": False, "isPaused": True, "isinvalid": False, "lastEdit": "2026-08-02T10:00:00Z"},
        ],
        "pg": {},
    }, status=200)
    result = await h.list_scenarios(ctx_scoped, ListScenariosParams(limit=100, offset=0))
    assert result.error is None
    assert result.data.total == 2
    assert result.data.items[0].scenario_id == 100
    assert result.data.items[1].is_paused is True


# ═══════════════════════════════════════════════════════════════════════
# BRANCH 2 -- ERROR PATH (auth/scope failures, malformed input)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_connect_rejects_empty_token(ctx):
    result = await h.connect_make(ctx, ConnectMakeParams(api_token=""))
    assert result.error is not None
    assert result.error_code == "MAKE_TOKEN_MISSING"


@pytest.mark.asyncio
async def test_connect_all_zones_401_reports_auth_error_not_scope(ctx):
    """Every known zone rejects the token outright (401) -- must be
    reported as MAKE_AUTH_ERROR, never MAKE_SCOPE_ERROR."""
    for zone in ("eu1.make.com", "eu2.make.com", "us1.make.com", "us2.make.com"):
        ctx.http.mock_get(f"{zone}/api/v2/users/me", {}, status=401)
    result = await h.connect_make(ctx, ConnectMakeParams(api_token="tok-bad"))
    assert result.error is not None
    assert result.error_code == "MAKE_AUTH_ERROR"
    assert await ctx.secrets.get("make_api_token") is None


@pytest.mark.asyncio
async def test_connect_recognised_zone_missing_scope_reports_scope_error(ctx):
    """eu1 recognises the token (403, not 401) but it lacks
    organizations:read -- must be reported as the specific, fixable
    MAKE_SCOPE_ERROR, never conflated with 'wrong token'."""
    ctx.http.mock_get("eu1.make.com/api/v2/users/me", {"detail": "missing scope", "code": "SC403"}, status=403)
    result = await h.connect_make(ctx, ConnectMakeParams(api_token="tok-no-scope"))
    assert result.error is not None
    assert result.error_code == "MAKE_SCOPE_ERROR"
    assert await ctx.secrets.get("make_api_token") is None


@pytest.mark.asyncio
async def test_list_scenarios_without_team_scope_blocked(ctx_connected):
    """Connected but no team selected yet -- must block with the specific
    MAKE_NO_TEAM_SCOPE code, not a generic error."""
    result = await h.list_scenarios(ctx_connected, ListScenariosParams(limit=50, offset=0))
    assert result.error is not None
    assert result.error_code == "MAKE_NO_TEAM_SCOPE"


@pytest.mark.asyncio
async def test_delete_incomplete_executions_requires_ids_or_all(ctx_scoped):
    """Neither dlq_ids nor all=true given -- must reject before even
    reaching the network, not silently delete nothing or everything."""
    result = await h.delete_incomplete_executions(
        ctx_scoped, DeleteIncompleteExecutionsParams(scenario_id=1, dlq_ids=[], all=False),
    )
    assert result.error is not None
    assert result.error_code == "MAKE_MISSING_IDS"


# ═══════════════════════════════════════════════════════════════════════
# BRANCH 3 -- BLOCKED STATE (not connected, module not found, state drift)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("fn,params", [
    (h.list_scenarios, ListScenariosParams(limit=10, offset=0)),
    (h.run_scenario, RunScenarioParams(scenario_id=1)),
    (h.list_connections, ListConnectionsParams()),
    (h.list_data_stores, ListDataStoresParams()),
    (h.list_hooks, ListHooksParams()),
    (h.list_organizations, ListOrganizationsParams()),
    (h.list_api_tokens, ListApiTokensParams()),
    (h.get_scenario_blueprint, GetScenarioBlueprintParams(scenario_id=1)),
])
@pytest.mark.asyncio
async def test_every_function_blocks_when_not_connected(ctx, fn, params):
    result = await fn(ctx, params)
    assert result.error is not None
    assert result.error_code in ("MAKE_NOT_CONNECTED",)


@pytest.mark.asyncio
async def test_preview_update_blueprint_module_not_found(ctx_connected):
    """Blueprint exists but the module id given doesn't -- must report
    MAKE_MODULE_NOT_FOUND, not crash on a None lookup."""
    ctx_connected.http.mock_get(
        "/api/v2/scenarios/1/blueprint",
        {"response": {"blueprint": {"name": "Test", "flow": [{"id": 1, "module": "builtin:BasicRouter", "mapper": {}}]}}},
        status=200,
    )
    result = await h.preview_update_blueprint_module(
        ctx_connected, PreviewUpdateBlueprintModuleParams(scenario_id=1, module_id=999, field="prompt", value="x"),
    )
    assert result.error is not None
    assert result.error_code == "MAKE_MODULE_NOT_FOUND"


@pytest.mark.asyncio
async def test_apply_update_blueprint_module_refuses_on_state_drift(ctx_connected):
    """Given a blueprint that changed since preview (someone edited it in
    the Make UI), apply must refuse with MAKE_STATE_CHANGED rather than
    silently overwriting the newer edit."""
    ctx_connected.http.mock_get(
        "/api/v2/scenarios/1/blueprint",
        {"response": {"blueprint": {"name": "Test", "flow": [{"id": 1, "module": "ai:createCompletion", "mapper": {"prompt": "NEW EDITED VALUE"}}]}}},
        status=200,
    )
    result = await h.apply_update_blueprint_module(
        ctx_connected, ApplyUpdateBlueprintModuleParams(
            scenario_id=1, module_id=1, field="prompt", value="my new prompt",
            expected_state_token="deliberately-stale-token-from-an-old-preview",
        ),
    )
    assert result.error is not None
    assert result.error_code == "MAKE_STATE_CHANGED"


# ═══════════════════════════════════════════════════════════════════════
# BRANCH 4 -- RECOVERY (retry after failure succeeds cleanly)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_run_scenario_fails_then_succeeds_on_retry(ctx_connected):
    """Given a transient 500 from Make, retrying the same run must
    succeed cleanly with no leftover state blocking it."""
    ctx_connected.http.mock_post("/api/v2/scenarios/42/run", {"detail": "internal error"}, status=500)
    r1 = await h.run_scenario(ctx_connected, RunScenarioParams(scenario_id=42))
    assert r1.error is not None
    assert r1.error_code == "MAKE_BACKEND_ERROR"

    ctx_connected.http._mocks.clear()
    ctx_connected.http.mock_post("/api/v2/scenarios/42/run", {"executions": [{"id": 999, "status": 1}]}, status=200)
    r2 = await h.run_scenario(ctx_connected, RunScenarioParams(scenario_id=42))
    assert r2.error is None
    assert r2.data.execution_id == "999"
    assert r2.data.status == "1"


@pytest.mark.asyncio
async def test_apply_add_blueprint_module_succeeds_after_fresh_preview(ctx_connected):
    """Given a state token from a FRESH preview (not stale), apply must
    succeed -- the recovery path after a state-drift rejection is simply
    re-previewing and re-applying with the new token."""
    blueprint_body = {"response": {"blueprint": {"name": "Test", "flow": [{"id": 1, "module": "builtin:Filter", "mapper": {}}]}}}
    ctx_connected.http.mock_get("/api/v2/scenarios/1/blueprint", blueprint_body, status=200)
    preview = await h.preview_add_blueprint_module(
        ctx_connected, PreviewAddBlueprintModuleParams(scenario_id=1, app_module="gmail:SendEmail", after_module_id=1, mapper={}),
    )
    assert preview.error is None
    token = preview.data.expected_state_token

    ctx_connected.http.mock_patch = getattr(ctx_connected.http, "mock_patch", None)
    ctx_connected.http._mocks.append(("PATCH", "/api/v2/scenarios/1", {"scenario": {"id": 1, "name": "Test"}}, 200, {}))
    apply_result = await h.apply_add_blueprint_module(
        ctx_connected, ApplyAddBlueprintModuleParams(
            scenario_id=1, app_module="gmail:SendEmail", after_module_id=1, mapper={"to": "x@y.com"},
            expected_state_token=token,
        ),
    )
    assert apply_result.error is None
    assert apply_result.data.total_modules == 2


# ═══════════════════════════════════════════════════════════════════════
# BRANCH 5 -- ADVERSARIAL (bulk partial failure, double-click, exotic data)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bulk_set_scenario_active_partial_failure_reports_both(ctx_connected):
    """3 scenario ids: 2 succeed, 1 (deleted/invalid) fails -- the bulk
    result must report BOTH succeeded and failed, never silently drop
    the failure or abort the whole batch."""
    ctx_connected.http.mock_post("/api/v2/scenarios/1/start", {"scenario": {"id": 1, "isActive": True}}, status=200)
    ctx_connected.http.mock_post("/api/v2/scenarios/2/start", {"scenario": {"id": 2, "isActive": True}}, status=200)
    ctx_connected.http.mock_post("/api/v2/scenarios/3/start", {"detail": "not found"}, status=404)
    result = await h.bulk_set_scenario_active(
        ctx_connected, BulkSetScenarioActiveParams(scenario_ids=[1, 2, 3], active=True),
    )
    assert result.error is None
    assert result.data.succeeded == [1, 2]
    assert "3" in result.data.failed


@pytest.mark.asyncio
async def test_delete_hook_twice_second_call_is_not_found(ctx_connected):
    """Soap-opera class: delete the same hook twice (double-click). First
    succeeds; second must report a real not-found error, never silently
    report deleted=true again with no real effect."""
    ctx_connected.http._mocks.append(("DELETE", "/api/v2/hooks/77", {"hook": 77}, 200, {}))
    r1 = await h.delete_hook(ctx_connected, DeleteHookParams(hook_id=77))
    assert r1.error is None
    assert r1.data.deleted is True

    ctx_connected.http._mocks.clear()
    ctx_connected.http._mocks.append(("DELETE", "/api/v2/hooks/77", {"detail": "hook not found"}, 404, {}))
    r2 = await h.delete_hook(ctx_connected, DeleteHookParams(hook_id=77))
    assert r2.error is not None
    assert r2.error_code == "MAKE_HTTP_ERROR"


@pytest.mark.asyncio
async def test_get_scenario_blueprint_router_branches_numbered_like_editor(ctx_connected):
    """Exotic-but-real shape: a router with 2 branches, each containing a
    module -- get_scenario_blueprint must flatten depth-first so 'module 3'
    matches what the user sees in Make's own editor numbering, and
    branch_count must reflect the router's actual route count."""
    ctx_connected.http.mock_get("/api/v2/scenarios/1/blueprint", {
        "response": {"blueprint": {
            "name": "Router Demo",
            "flow": [
                {"id": 1, "module": "builtin:BasicRouter", "routes": [
                    {"flow": [{"id": 2, "module": "gmail:SendEmail", "mapper": {}}]},
                    {"flow": [{"id": 3, "module": "slack:PostMessage", "mapper": {}}]},
                ]},
            ],
        }}
    }, status=200)
    result = await h.get_scenario_blueprint(ctx_connected, GetScenarioBlueprintParams(scenario_id=1))
    assert result.error is None
    assert result.data.total == 3
    assert result.data.items[0].is_router is True
    assert result.data.items[0].branch_count == 2
    assert result.data.items[1].module == "SendEmail"
    assert result.data.items[2].module == "PostMessage"


@pytest.mark.asyncio
async def test_send_webhook_event_network_failure_not_raised_as_exception(ctx):
    """Adversarial: outgoing webhook URL is unreachable at the network
    level (DNS/timeout) -- post_webhook's own try/except must convert this
    to a reported delivery failure, never let an exception escape to crash
    the handler."""
    await ctx.secrets.set("make_webhook_url", "https://this-domain-does-not-resolve.invalid/hook")

    class _BoomHTTP:
        async def post(self, *a, **kw):
            raise ConnectionError("could not resolve host")
        async def get(self, *a, **kw):
            raise ConnectionError("could not resolve host")
        async def put(self, *a, **kw):
            raise ConnectionError("could not resolve host")
        async def patch(self, *a, **kw):
            raise ConnectionError("could not resolve host")
        async def delete(self, *a, **kw):
            raise ConnectionError("could not resolve host")

    ctx.http = _BoomHTTP()
    result = await h.send_webhook_event(ctx, SendWebhookEventParams(payload={"event": "test"}))
    assert result.error is not None
    assert result.error_code == "MAKE_WEBHOOK_DELIVERY_FAILED"


# ── Part D2 (SCENARIO_TESTING_STANDARD.md): idempotency / double-invocation ─

@pytest.mark.asyncio
async def test_d2_delete_connection_twice_second_call_is_not_found(ctx_connected):
    """Same double-click class as test_delete_hook_twice_second_call_is_not_found:
    delete the same connection twice -- first succeeds, second must report a
    real not-found/HTTP error, never silently repeat deleted=true."""
    ctx_connected.http._mocks.append(("DELETE", "/api/v2/connections/42", {"connection": 42}, 200, {}))
    r1 = await h.delete_connection(ctx_connected, DeleteConnectionParams(connection_id=42))
    assert r1.error is None
    assert r1.data.deleted is True

    ctx_connected.http._mocks.clear()
    ctx_connected.http._mocks.append(("DELETE", "/api/v2/connections/42", {"detail": "connection not found"}, 404, {}))
    r2 = await h.delete_connection(ctx_connected, DeleteConnectionParams(connection_id=42))
    assert r2.error is not None
    assert r2.error_code == "MAKE_HTTP_ERROR"


@pytest.mark.asyncio
async def test_d2_delete_data_store_twice_second_call_is_not_found(ctx_connected):
    """Same double-click class -- delete the same data store twice."""
    ctx_connected.http._mocks.append(("DELETE", "/api/v2/data-stores/9", {"dataStore": 9}, 200, {}))
    r1 = await h.delete_data_store(ctx_connected, DeleteDataStoreParams(data_store_id=9))
    assert r1.error is None
    assert r1.data.deleted is True

    ctx_connected.http._mocks.clear()
    ctx_connected.http._mocks.append(("DELETE", "/api/v2/data-stores/9", {"detail": "data store not found"}, 404, {}))
    r2 = await h.delete_data_store(ctx_connected, DeleteDataStoreParams(data_store_id=9))
    assert r2.error is not None
    assert r2.error_code == "MAKE_HTTP_ERROR"


# ── Part D3 (SCENARIO_TESTING_STANDARD.md): security / SSRF surface -------

@pytest.mark.asyncio
async def test_d3_outgoing_webhook_is_reviewed_intentional_ssrf_surface(ctx):
    """Unlike every other connector in this portfolio, Make.com Connector
    DOES let a user configure an arbitrary outgoing URL (set_outgoing_webhook)
    that this app's own code later POSTs to (send_webhook_event ->
    mc.post_webhook). This is reviewed and accepted as intentional, not a
    bug: it is the documented mechanism for other Imperal apps/automations
    to trigger a Make scenario via a Custom Webhook trigger, exactly like
    Slack/Discord-style outgoing webhooks. Safeguards already in place:
    (1) explicit opt-in -- nothing is sent until the user runs
    set_outgoing_webhook themselves; (2) scheme validation rejects anything
    that doesn't start with http(s)://; (3) network failures are caught and
    reported, never raised as an unhandled exception (see
    test_send_webhook_event_network_failure_not_raised_as_exception).
    This test is the regression trip-wire: if scheme validation is ever
    weakened, this must be revisited alongside a real SSRF fix."""
    result = await h.set_outgoing_webhook(ctx, SetOutgoingWebhookParams(webhook_url="not-a-url"))
    assert result.error is not None
    assert result.error_code == "MAKE_WEBHOOK_URL_INVALID"
