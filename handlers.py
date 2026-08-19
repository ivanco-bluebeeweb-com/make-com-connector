"""Chat functions for Make.com Connector -- Срез 1 (connection) only.

Scenario list/run/activate land in Срез 2+ per PREPARATION.md's Срез
table -- this file intentionally stops at connect/disconnect/status so
each slice stays live-verifiable on its own before the next is built.
"""
from __future__ import annotations

from imperal_sdk import ActionResult

import make_client as mc
from app import ext, chat
from schemas import (
    NoParams, ConnectMakeParams, ProviderConnection,
    MakeTeam, MakeTeamList, SelectTeamParams,
    ListScenariosParams, MakeScenario, MakeScenarioList,
    RunScenarioParams, ScenarioRunResult,
    SetScenarioActiveParams, ScenarioStateResult,
    SetOutgoingWebhookParams, OutgoingWebhookStatus,
    SendWebhookEventParams, WebhookDeliveryResult,
    GetScenarioBlueprintParams, BlueprintModule, BlueprintModuleList,
    ListConnectionsParams, MakeConnection, MakeConnectionList,
    DeleteConnectionParams, RenameConnectionParams,
    VerifyConnectionParams, ConnectionVerifyResult, DeleteResult,
    ListDataStoresParams, MakeDataStore, MakeDataStoreList,
    CreateDataStoreParams, DeleteDataStoreParams,
    ListHooksParams, MakeHook, MakeHookList,
    SetHookEnabledParams, DeleteHookParams,
    ListIncompleteExecutionsParams, IncompleteExecution, IncompleteExecutionList,
    RetryIncompleteExecutionParams, DeleteIncompleteExecutionsParams, BulkDeleteResult,
    BulkSetScenarioActiveParams, BulkScenarioStateResult,
    BulkRunScenariosParams, BulkRunResult,
    BulkDeleteConnectionsParams, BulkDeleteHooksParams,
    PreviewUpdateBlueprintModuleParams, BlueprintModuleFieldPreview,
    ApplyUpdateBlueprintModuleParams, BlueprintModuleUpdateResult,
    CreateScenarioParams, DeleteScenarioParams, RestoreScenarioParams,
    CloneScenarioParams, UpdateSchedulingParams, SchedulingResult,
    ListBuildtimeVariablesParams, BuildtimeVariable, BuildtimeVariableList,
    SetBuildtimeVariableParams, DeleteBuildtimeVariableParams,
    GetScenarioUsageParams, UsageDay, ScenarioUsageReport,
    ListScenarioLogsParams, ScenarioExecutionLog, ScenarioExecutionLogList,
    GetExecutionDetailsParams, ExecutionDetails, StopExecutionParams,
    PreviewAddBlueprintModuleParams, BlueprintModuleAddPreview,
    ApplyAddBlueprintModuleParams, BlueprintModuleAddResult,
    PreviewDeleteBlueprintModuleParams, BlueprintModuleDeletePreview,
    ApplyDeleteBlueprintModuleParams, BlueprintModuleDeleteResult,
    ListOrganizationsParams, MakeOrganization, MakeOrganizationList,
    ListTeamMembersParams, TeamMember, TeamMemberList,
    ListApiTokensParams, MakeApiToken, MakeApiTokenList,
    CreateApiTokenParams, CreatedApiToken, DeleteApiTokenParams,
    CreateHookParams,
)
from schemas import MakeScenario as _MakeScenario  # reused for create/clone/restore results

_TEAM_SCOPE_MARKER = "team_scope_setting"


async def _get_credentials(ctx) -> tuple[str, str]:
    """Returns (api_token, zone). Both empty means "not connected"."""
    token = await ctx.secrets.get("make_api_token")
    zone = await ctx.secrets.get("make_zone")
    return token or "", zone or ""


async def _get_team_scope(ctx) -> int | None:
    """team_id isn't sensitive (just an account-scoped integer, same
    sensitivity class as a project id), so it lives in ctx.store like
    DataForSEO's sandbox-mode marker -- not in ctx.secrets."""
    page = await ctx.store.query("app_settings", where={"kind": _TEAM_SCOPE_MARKER}, limit=1)
    if page.data:
        team_id = page.data[0].data.get("team_id")
        return int(team_id) if team_id else None
    return None


async def _set_team_scope(ctx, team_id: int) -> None:
    payload = {"kind": _TEAM_SCOPE_MARKER, "team_id": team_id}
    page = await ctx.store.query("app_settings", where={"kind": _TEAM_SCOPE_MARKER}, limit=1)
    if page.data:
        await ctx.store.update("app_settings", page.data[0].id, payload)
    else:
        await ctx.store.create("app_settings", payload)


# ──────────────────────────────────────────────────────────────────────────
# Connection / account management
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "connect_make",
    "Connect Make.com by saving your own API token, after checking it "
    "actually works. Create the token in Make: avatar (bottom-left) -> "
    "Profile -> API tab -> Add token. The account's zone (eu1/eu2/us1/us2) "
    "is auto-detected -- you don't need to know it.",
    action_type="write",
    chain_callable=True,
    data_model=ProviderConnection,
    event="make-com-connector.connect_make",
    effects=["make.provider.connected"],
)
async def connect_make(ctx, params: ConnectMakeParams) -> ActionResult:
    """Validate-then-store: a token Make rejects (or a zone it isn't valid
    in) is never written, so the stored pair can never be one we already
    know is bad. Zone is discovered by probing known zones with a cheap,
    side-effect-free GET /users/me -- see make_client.discover_zone."""
    token = params.api_token.strip()
    if not token:
        return ActionResult.error(
            "An API token is required. Create one in Make: avatar -> "
            "Profile -> API tab -> Add token.",
            code="MAKE_TOKEN_MISSING",
        )

    try:
        zone, who = await mc.discover_zone(ctx, token)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)

    await ctx.secrets.set("make_api_token", token)
    await ctx.secrets.set("make_zone", zone)

    label = who.get("name") or who.get("email") or "your Make account"
    return ActionResult.success(
        ProviderConnection(connected=True, detail=f"Connected as {label} ({zone})"),
        summary=f"Make.com connected as {label}.",
        refresh_panels=["make_connect"],
    )


@chat.function(
    "disconnect_make",
    "Disconnect Make.com: deletes the saved API token and zone. Existing "
    "scenarios in your Make account are never touched.",
    action_type="write",
    chain_callable=True,
    data_model=ProviderConnection,
    event="make-com-connector.disconnect_make",
    effects=["make.provider.disconnected"],
)
async def disconnect_make(ctx, params: NoParams) -> ActionResult:
    """Deletes both stored secrets -- token and its discovered zone --
    together, so a stale zone can never be paired with no token (or vice
    versa) on the next connect attempt."""
    await ctx.secrets.delete("make_api_token")
    await ctx.secrets.delete("make_zone")
    return ActionResult.success(
        ProviderConnection(connected=False, detail="Not connected"),
        summary="Make.com disconnected.",
        refresh_panels=["make_connect"],
    )


@chat.function(
    "get_make_connection",
    "Check whether Make.com is currently connected (does not reveal the "
    "saved token).",
    action_type="read",
    data_model=ProviderConnection,
)
async def get_make_connection(ctx, params: NoParams) -> ActionResult:
    """Read-only status check -- never returns the saved token/zone values,
    only whether a token+zone pair is currently stored."""
    token, zone = await _get_credentials(ctx)
    connected = bool(token and zone)
    return ActionResult.success(
        ProviderConnection(
            connected=connected,
            detail=f"Connected ({zone})" if connected else "Not connected -- run connect_make",
        ),
        summary="Make.com is connected." if connected else "Make.com is not connected.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 2: scenarios (list) -- team scope resolution + listing
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_make_teams",
    "List the Make.com teams your connected account belongs to. Needed "
    "once to pick which team's scenarios to show -- Make requires a "
    "specific team (or organization) scope, it has no single global "
    "scenario list.",
    action_type="read",
    chain_callable=True,
    data_model=MakeTeamList,
)
async def list_make_teams(ctx, params: NoParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not (token and zone):
        return ActionResult.error(
            "Make.com isn't connected yet. Run connect_make first.",
            code="MAKE_NOT_CONNECTED",
        )
    try:
        orgs = await mc.list_organizations(ctx, token, zone)
        teams: list[dict] = []
        for org in orgs:
            org_id = org.get("id")
            if org_id is None:
                continue
            org_teams = await mc.list_teams(ctx, token, zone, org_id)
            for t in org_teams:
                t["organizationId"] = org_id
            teams.extend(org_teams)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)

    items = [
        MakeTeam(
            id=str(t.get("id", "")),
            title=t.get("name", ""),
            organization_id=t.get("organizationId", 0),
        )
        for t in teams
    ]
    return ActionResult.success(
        MakeTeamList(items=items, total=len(items)),
        summary=f"Found {len(items)} Make team(s).",
    )


@chat.function(
    "select_team",
    "Pick which Make.com team's scenarios to show. Run list_make_teams "
    "first to see the available team ids. This is a standing choice -- "
    "it stays selected until changed again.",
    action_type="write",
    chain_callable=True,
    data_model=ProviderConnection,
    event="make-com-connector.select_team",
    effects=["make.team_scope.changed"],
)
async def select_team(ctx, params: SelectTeamParams) -> ActionResult:
    await _set_team_scope(ctx, params.team_id)
    return ActionResult.success(
        ProviderConnection(connected=True, detail=f"Scoped to team {params.team_id}"),
        summary=f"Now showing scenarios for team {params.team_id}.",
        refresh_panels=["make_connect"],
    )


@chat.function(
    "list_scenarios",
    "List your Make.com scenarios for the selected team -- name, active/ "
    "paused/invalid state, and last edit time. Run connect_make and "
    "select_team first if you haven't yet.",
    action_type="read",
    chain_callable=True,
    data_model=MakeScenarioList,
)
async def list_scenarios(ctx, params: ListScenariosParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not (token and zone):
        return ActionResult.error(
            "Make.com isn't connected yet. Run connect_make first.",
            code="MAKE_NOT_CONNECTED",
        )
    team_id = await _get_team_scope(ctx)
    if not team_id:
        return ActionResult.error(
            "No team selected yet. Run list_make_teams then select_team first.",
            code="MAKE_NO_TEAM_SCOPE",
        )
    try:
        rows, _pg = await mc.list_scenarios(
            ctx, token, zone, team_id=team_id, organization_id=None,
            limit=params.limit, offset=params.offset,
        )
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)

    items = [
        MakeScenario(
            id=str(s.get("id", "")),
            title=s.get("name", ""),
            scenario_id=s.get("id", 0),
            team_id=s.get("teamId", 0),
            is_active=bool(s.get("isActive")),
            is_paused=bool(s.get("isPaused")),
            is_invalid=bool(s.get("isinvalid")),
            folder_id=s.get("folderId"),
            last_edit=s.get("lastEdit", ""),
            scheduling_type=(s.get("scheduling") or {}).get("type", ""),
        )
        for s in rows
    ]
    return ActionResult.success(
        MakeScenarioList(items=items, total=len(items)),
        summary=f"Found {len(items)} scenario(s).",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 3: run_scenario -- explicit confirmation, real side effects in Make.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "run_scenario",
    "Run one of your Make.com scenarios right now, by scenario_id (see "
    "list_scenarios). This executes the scenario's real actions in Make "
    "immediately -- sending emails, writing to connected apps, etc. There "
    "is no dry-run or undo, so this always asks for confirm=true first.",
    action_type="destructive",
    chain_callable=True,
    data_model=ScenarioRunResult,
    event="make-com-connector.run_scenario",
    effects=["make.scenario.run"],
)
async def run_scenario(ctx, params: RunScenarioParams) -> ActionResult:
    """Declared `action_type="destructive"` per Imperal's action-type doctrine:
    a scenario run is a real, irreversible action in a real external system
    (Make), with whatever side effects that scenario is built to have -- there
    is no way for this connector to know if those are reversible, so it never
    assumes they are. The web-kernel's KAV confirmation card handles asking the
    user before dispatch; this handler must NOT re-prompt (double-prompting
    breaks the platform's "what you saw is what runs" guarantee)."""
    token, zone = await _get_credentials(ctx)
    if not (token and zone):
        return ActionResult.error(
            "Make.com isn't connected yet. Run connect_make first.",
            code="MAKE_NOT_CONNECTED",
        )

    try:
        result = await mc.run_scenario(ctx, token, zone, params.scenario_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)

    execution = result.get("executions") or [{}]
    first = execution[0] if execution else {}
    status = first.get("status", "") or result.get("status", "")
    execution_id = str(first.get("id", "") or result.get("executionId", ""))

    return ActionResult.success(
        ScenarioRunResult(
            scenario_id=params.scenario_id,
            execution_id=execution_id,
            status=str(status),
        ),
        summary=f"Ran scenario {params.scenario_id} (status: {status or 'submitted'}).",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 4: activate/deactivate scenario -- reversible toggle, no confirm gate.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "set_scenario_active",
    "Activate (turn on/schedule) or deactivate (pause) a Make.com scenario "
    "by scenario_id (see list_scenarios). Reversible -- flip it back any "
    "time -- so unlike run_scenario this needs no confirmation.",
    action_type="write",
    chain_callable=True,
    data_model=ScenarioStateResult,
    event="make-com-connector.set_scenario_active",
    effects=["make.scenario.state_changed"],
)
async def set_scenario_active(ctx, params: SetScenarioActiveParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not (token and zone):
        return ActionResult.error(
            "Make.com isn't connected yet. Run connect_make first.",
            code="MAKE_NOT_CONNECTED",
        )

    try:
        if params.active:
            scenario = await mc.start_scenario(ctx, token, zone, params.scenario_id)
        else:
            scenario = await mc.stop_scenario(ctx, token, zone, params.scenario_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)

    is_active = bool(scenario.get("isActive", params.active))
    verb = "activated" if is_active else "deactivated"
    return ActionResult.success(
        ScenarioStateResult(
            id=str(params.scenario_id),
            title=scenario.get("name", ""),
            scenario_id=params.scenario_id,
            is_active=is_active,
        ),
        summary=f"Scenario {params.scenario_id} {verb}.",
        refresh_panels=["make_connect"],
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 5: outgoing webhook Imperal -> Make.
# ──────────────────────────────────────────────────────────────────────────

_WEBHOOK_SECRET_NAME = "make_webhook_url"


@chat.function(
    "set_outgoing_webhook",
    "Save (or clear, with an empty webhook_url) the Make Custom Webhook "
    "trigger URL that send_webhook_event will POST to. Get this URL by "
    "adding a 'Custom Webhook' module as the first step of a Make "
    "scenario and copying its URL. This is independent of connect_make.",
    action_type="write",
    chain_callable=True,
    data_model=OutgoingWebhookStatus,
    event="make-com-connector.set_outgoing_webhook",
    effects=["make.webhook.configured"],
)
async def set_outgoing_webhook(ctx, params: SetOutgoingWebhookParams) -> ActionResult:
    """The URL itself is the credential (Make authenticates by knowing it,
    not via a header), so it lives in ctx.secrets -- same tier as
    make_api_token, not the non-sensitive ctx.store team_id marker."""
    url = params.webhook_url.strip()
    if not url:
        await ctx.secrets.delete(_WEBHOOK_SECRET_NAME)
        return ActionResult.success(
            OutgoingWebhookStatus(configured=False, detail="No webhook configured"),
            summary="Outgoing Make webhook cleared.",
            refresh_panels=["make_connect"],
        )
    if not (url.startswith("https://") or url.startswith("http://")):
        return ActionResult.error(
            "That doesn't look like a URL. Paste the Custom Webhook trigger "
            "URL from Make (add a 'Custom Webhook' module, copy its URL).",
            code="MAKE_WEBHOOK_URL_INVALID",
        )
    await ctx.secrets.set(_WEBHOOK_SECRET_NAME, url)
    return ActionResult.success(
        OutgoingWebhookStatus(configured=True, detail="Webhook configured"),
        summary="Outgoing Make webhook saved.",
        refresh_panels=["make_connect"],
    )


@chat.function(
    "get_outgoing_webhook_status",
    "Check whether an outgoing Make webhook URL is configured (does not "
    "reveal the URL itself).",
    action_type="read",
    chain_callable=True,
    data_model=OutgoingWebhookStatus,
)
async def get_outgoing_webhook_status(ctx, params: NoParams) -> ActionResult:
    url = await ctx.secrets.get(_WEBHOOK_SECRET_NAME)
    configured = bool(url)
    return ActionResult.success(
        OutgoingWebhookStatus(
            configured=configured,
            detail="Webhook configured" if configured else "No webhook configured",
        ),
    )


@chat.function(
    "send_webhook_event",
    "Send an event payload to the configured Make webhook right now -- "
    "for other Imperal apps/automations to trigger a Make scenario. Run "
    "set_outgoing_webhook first if you haven't configured one yet.",
    action_type="write",
    chain_callable=True,
    data_model=WebhookDeliveryResult,
    event="make-com-connector.send_webhook_event",
    effects=["make.webhook.sent"],
)
async def send_webhook_event(ctx, params: SendWebhookEventParams) -> ActionResult:
    url = await ctx.secrets.get(_WEBHOOK_SECRET_NAME)
    if not url:
        return ActionResult.error(
            "No outgoing webhook is configured yet. Run set_outgoing_webhook first.",
            code="MAKE_WEBHOOK_NOT_CONFIGURED",
        )
    delivered, status_code, detail = await mc.post_webhook(ctx, url, params.payload)
    result = WebhookDeliveryResult(delivered=delivered, status_code=status_code, detail=detail)
    if not delivered:
        return ActionResult.error(detail, code="MAKE_WEBHOOK_DELIVERY_FAILED")
    return ActionResult.success(result, summary=f"Webhook delivered (HTTP {status_code}).")


# ──────────────────────────────────────────────────────────────────────────
# Срез 6: scenario blueprint -- what module N actually is/does.
# ──────────────────────────────────────────────────────────────────────────

_APP_LABELS = {
    "builtin:BasicRouter": "Router",
    "builtin:BasicFeeder": "Iterator",
    "builtin:BasicAggregator": "Aggregator",
    "builtin:Filter": "Filter",
    "builtin:Sleep": "Sleep",
    "builtin:SetVariable": "Set variable",
    "builtin:SetVariable2": "Set multiple variables",
}


def _describe_module(raw: dict, position: int) -> BlueprintModule:
    module_full = raw.get("module") or ""
    app, _, module_name = module_full.partition(":")
    label = _APP_LABELS.get(module_full, "")
    routes = raw.get("routes") or []
    return BlueprintModule(
        id=str(raw.get("id", position)),
        title=raw.get("label") or label or module_name or module_full or f"Module {position}",
        position=position,
        module_id=int(raw.get("id") or 0),
        app=app or ("router" if module_full == "builtin:BasicRouter" else ""),
        module=module_name or module_full,
        label=label,
        is_router=module_full == "builtin:BasicRouter",
        branch_count=len(routes) if routes else 0,
        # The module's own settings -- for AI modules (messageAssistantAdvanced,
        # createCompletion, etc.) this IS where the prompt text, assistant/model
        # id and generation params live. Make stores it under "mapper" in the
        # blueprint; passed through untouched, not reshaped.
        raw_config=raw.get("mapper") or {},
    )


def _flatten_blueprint_modules(flow: list) -> list[BlueprintModule]:
    """Make numbers modules in editor order, including inside router
    branches, depth-first -- so this walks flow[] the same way, flattening
    router routes[] in place so 'module 7' matches what the user sees in
    the Make editor's own module numbering."""
    out: list[BlueprintModule] = []
    position = 0

    def walk(nodes: list):
        nonlocal position
        for node in nodes:
            position += 1
            out.append(_describe_module(node, position))
            routes = node.get("routes") or []
            for route in routes:
                walk(route.get("flow") or [])

    walk(flow)
    return out


@chat.function(
    "get_scenario_blueprint",
    "Read a scenario's actual module list (blueprint) -- what each "
    "numbered step in the flow is and does, in the same order the Make "
    "editor numbers them. This is how to answer 'what is module N' or "
    "'what does the Nth step do'.",
    action_type="read",
    chain_callable=True,
    data_model=BlueprintModuleList,
)
async def get_scenario_blueprint(ctx, params: GetScenarioBlueprintParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        blueprint = await mc.get_scenario_blueprint(ctx, token, zone, params.scenario_id, draft=params.draft)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    flow = blueprint.get("flow") or []
    modules = _flatten_blueprint_modules(flow)
    scenario_name = blueprint.get("name") or ""
    result = BlueprintModuleList(
        items=modules, total=len(modules),
        scenario_id=params.scenario_id, scenario_name=scenario_name,
    )
    return ActionResult.success(
        result,
        summary=f"Scenario has {len(modules)} module(s).",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 7: connections.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_connections",
    "List the app connections in your Make team -- what a scenario's "
    "modules actually authenticate as (which account/app each connection "
    "is for, and whether it's about to expire).",
    action_type="read",
    chain_callable=True,
    data_model=MakeConnectionList,
)
async def list_connections(ctx, params: ListConnectionsParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    team_id = await _get_team_scope(ctx)
    if not team_id:
        return ActionResult.error(
            "No team selected yet. Run select_team first.", code="MAKE_NO_TEAM_SCOPE",
        )
    try:
        raw = await mc.list_connections(ctx, token, zone, team_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [
        MakeConnection(
            id=str(c.get("id", "")), title=c.get("name") or c.get("accountName") or f"Connection {c.get('id')}",
            connection_id=int(c.get("id") or 0), account_type=c.get("accountType") or "",
            account_label=c.get("accountLabel") or "", expires=c.get("expire") or "",
            editable=c.get("editable", True),
        )
        for c in raw
    ]
    return ActionResult.success(MakeConnectionList(items=items, total=len(items)))


@chat.function(
    "delete_connection",
    "Permanently delete a Make connection. Any scenario using it will "
    "stop working once it's gone.",
    action_type="destructive",
    chain_callable=True,
    data_model=DeleteResult,
)
async def delete_connection(ctx, params: DeleteConnectionParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        deleted_id = await mc.delete_connection(ctx, token, zone, params.connection_id, confirmed=True)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        DeleteResult(id=str(deleted_id), deleted=True),
        summary=f"Connection {deleted_id} deleted.",
    )


@chat.function(
    "rename_connection",
    "Rename a Make connection's display name.",
    action_type="write",
    chain_callable=True,
    data_model=MakeConnection,
)
async def rename_connection(ctx, params: RenameConnectionParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        c = await mc.rename_connection(ctx, token, zone, params.connection_id, params.name)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        MakeConnection(
            id=str(c.get("id", params.connection_id)), title=c.get("name") or params.name,
            connection_id=params.connection_id,
        ),
        summary="Connection renamed.",
    )


@chat.function(
    "verify_connection",
    "Test whether a Make connection's credentials still work.",
    action_type="read",
    chain_callable=True,
    data_model=ConnectionVerifyResult,
)
async def verify_connection(ctx, params: VerifyConnectionParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        ok = await mc.verify_connection(ctx, token, zone, params.connection_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        ConnectionVerifyResult(connection_id=params.connection_id, verified=ok),
        summary="Connection is valid." if ok else "Connection failed verification.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 8: data stores.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_data_stores",
    "List the data stores (Make's own key/value storage) in your team, "
    "with record counts and size.",
    action_type="read",
    chain_callable=True,
    data_model=MakeDataStoreList,
)
async def list_data_stores(ctx, params: ListDataStoresParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    team_id = await _get_team_scope(ctx)
    if not team_id:
        return ActionResult.error("No team selected yet. Run select_team first.", code="MAKE_NO_TEAM_SCOPE")
    try:
        raw = await mc.list_data_stores(ctx, token, zone, team_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [
        MakeDataStore(
            id=str(d.get("id", "")), title=d.get("name", ""), data_store_id=int(d.get("id") or 0),
            records=d.get("records", 0), size=d.get("size", 0), max_size=d.get("maxSize", 0),
        )
        for d in raw
    ]
    return ActionResult.success(MakeDataStoreList(items=items, total=len(items)))


@chat.function(
    "create_data_store",
    "Create a new Make data store (key/value storage a scenario can read/write).",
    action_type="write",
    chain_callable=True,
    data_model=MakeDataStore,
)
async def create_data_store(ctx, params: CreateDataStoreParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    team_id = await _get_team_scope(ctx)
    if not team_id:
        return ActionResult.error("No team selected yet. Run select_team first.", code="MAKE_NO_TEAM_SCOPE")
    try:
        d = await mc.create_data_store(
            ctx, token, zone, team_id, params.name,
            max_size_mb=params.max_size_mb, data_structure_id=params.data_structure_id,
        )
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        MakeDataStore(
            id=str(d.get("id", "")), title=d.get("name", params.name),
            data_store_id=int(d.get("id") or 0), max_size=d.get("maxSize", 0),
        ),
        summary=f"Data store '{params.name}' created.",
    )


@chat.function(
    "delete_data_store",
    "Permanently delete a Make data store and all of its records.",
    action_type="destructive",
    chain_callable=True,
    data_model=DeleteResult,
)
async def delete_data_store(ctx, params: DeleteDataStoreParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        deleted_id = await mc.delete_data_store(ctx, token, zone, params.data_store_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        DeleteResult(id=str(deleted_id), deleted=True),
        summary=f"Data store {deleted_id} deleted.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 9: hooks (Make's incoming webhooks/mailhooks -- triggers scenarios
# listen on; distinct from Срез 5's OUTGOING webhook).
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_hooks",
    "List the incoming webhooks/mailhooks (Make 'hooks') in your team -- "
    "the triggers scenarios listen on, with their URL and whether they're "
    "enabled.",
    action_type="read",
    chain_callable=True,
    data_model=MakeHookList,
)
async def list_hooks(ctx, params: ListHooksParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    team_id = await _get_team_scope(ctx)
    if not team_id:
        return ActionResult.error("No team selected yet. Run select_team first.", code="MAKE_NO_TEAM_SCOPE")
    try:
        raw = await mc.list_hooks(ctx, token, zone, team_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [
        MakeHook(
            id=str(h.get("id", "")), title=h.get("name", ""), hook_id=int(h.get("id") or 0),
            type_name=h.get("typeName") or h.get("type") or "", url=h.get("url", ""),
            enabled=h.get("enabled", True), scenario_id=h.get("scenarioId"),
            queue_count=h.get("queueCount", 0),
        )
        for h in raw
    ]
    return ActionResult.success(MakeHookList(items=items, total=len(items)))


@chat.function(
    "set_hook_enabled",
    "Enable or disable a Make hook (incoming webhook/mailhook) without "
    "deleting it.",
    action_type="write",
    chain_callable=True,
    data_model=MakeHook,
)
async def set_hook_enabled(ctx, params: SetHookEnabledParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        ok = await mc.set_hook_enabled(ctx, token, zone, params.hook_id, params.enabled)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    verb = "enabled" if params.enabled else "disabled"
    return ActionResult.success(
        MakeHook(id=str(params.hook_id), hook_id=params.hook_id, enabled=params.enabled),
        summary=f"Hook {params.hook_id} {verb}." if ok else f"Hook {params.hook_id} {verb} (unconfirmed).",
    )


@chat.function(
    "delete_hook",
    "Permanently remove a Make hook. Any scenario using it will stop "
    "working once it's gone.",
    action_type="destructive",
    chain_callable=True,
    data_model=DeleteResult,
)
async def delete_hook(ctx, params: DeleteHookParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        deleted_id = await mc.delete_hook(ctx, token, zone, params.hook_id, confirmed=True)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        DeleteResult(id=str(deleted_id), deleted=True),
        summary=f"Hook {deleted_id} deleted.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 10: incomplete executions (DLQ) -- failed runs held for manual fix.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_incomplete_executions",
    "List a scenario's incomplete executions (failed runs held for manual "
    "resolution instead of being discarded) -- what failed, when, and "
    "whether it's already resolved.",
    action_type="read",
    chain_callable=True,
    data_model=IncompleteExecutionList,
)
async def list_incomplete_executions(ctx, params: ListIncompleteExecutionsParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.list_incomplete_executions(ctx, token, zone, params.scenario_id, status=params.status)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [
        IncompleteExecution(
            id=str(e.get("id", "")), title=e.get("reason") or f"Execution {e.get('id')}",
            reason=e.get("reason", ""), created=e.get("created", ""), size=e.get("size", 0),
            resolved=bool(e.get("resolved")), retry=bool(e.get("retry")), attempts=e.get("attempts", 0),
        )
        for e in raw
    ]
    return ActionResult.success(IncompleteExecutionList(items=items, total=len(items)))


@chat.function(
    "retry_incomplete_execution",
    "Retry one incomplete (failed) scenario execution after fixing the "
    "underlying issue.",
    action_type="write",
    chain_callable=True,
    data_model=IncompleteExecution,
)
async def retry_incomplete_execution(ctx, params: RetryIncompleteExecutionParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        await mc.retry_incomplete_execution(ctx, token, zone, params.dlq_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        IncompleteExecution(id=params.dlq_id, retry=True),
        summary=f"Retry requested for incomplete execution {params.dlq_id}.",
    )


@chat.function(
    "delete_incomplete_executions",
    "Permanently delete one scenario's incomplete executions -- explicit "
    "ids, or all=true to clear every one.",
    action_type="destructive",
    chain_callable=True,
    data_model=BulkDeleteResult,
)
async def delete_incomplete_executions(ctx, params: DeleteIncompleteExecutionsParams) -> ActionResult:
    if not params.all and not params.dlq_ids:
        return ActionResult.error(
            "Pass explicit dlq_ids, or all=true to delete every incomplete execution.",
            code="MAKE_MISSING_IDS",
        )
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        deleted = await mc.delete_incomplete_executions(
            ctx, token, zone, params.scenario_id,
            ids=params.dlq_ids or None, all_=params.all, confirmed=True,
        )
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    ids = [str(d) for d in deleted] if isinstance(deleted, list) else params.dlq_ids
    return ActionResult.success(
        BulkDeleteResult(deleted_count=len(ids), ids=ids),
        summary=f"Deleted {len(ids)} incomplete execution(s).",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 11: bulk operations -- batched versions of the single-item write
# tools, targeted by explicit id lists (never inferred), same federal
# convention as the platform's other bulk_* tools.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "bulk_set_scenario_active",
    "Activate or deactivate SEVERAL Make scenarios in one call by "
    "explicit scenario ids.",
    action_type="write",
    chain_callable=True,
    data_model=BulkScenarioStateResult,
    event="make-com-connector.bulk_set_scenario_active",
    effects=["make.scenario.bulk_state_changed"],
)
async def bulk_set_scenario_active(ctx, params: BulkSetScenarioActiveParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    succeeded: list[int] = []
    failed: list[dict] = []
    for sid in params.scenario_ids:
        try:
            if params.active:
                await mc.start_scenario(ctx, token, zone, sid)
            else:
                await mc.stop_scenario(ctx, token, zone, sid)
            succeeded.append(sid)
        except mc.ProviderError as exc:
            failed.append({"scenario_id": sid, "error": str(exc)})
    verb = "activated" if params.active else "deactivated"
    failed_map = {str(f["scenario_id"]): f["error"] for f in failed}
    return ActionResult.success(
        BulkScenarioStateResult(succeeded=succeeded, failed=failed_map, active=params.active),
        summary=f"{len(succeeded)} scenario(s) {verb}, {len(failed)} failed.",
        refresh_panels=["make_connect"],
    )


@chat.function(
    "bulk_run_scenarios",
    "Run SEVERAL Make scenarios right now, by explicit scenario ids. "
    "Executes real actions in each scenario immediately -- no dry-run.",
    action_type="destructive",
    chain_callable=True,
    data_model=BulkRunResult,
    event="make-com-connector.bulk_run_scenarios",
    effects=["make.scenario.bulk_run"],
)
async def bulk_run_scenarios(ctx, params: BulkRunScenariosParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    succeeded: list[dict] = []
    failed: list[dict] = []
    for sid in params.scenario_ids:
        try:
            result = await mc.run_scenario(ctx, token, zone, sid)
            execs = result.get("executions") or [{}]
            first = execs[0] if execs else {}
            succeeded.append({
                "scenario_id": sid,
                "execution_id": str(first.get("id", "") or result.get("executionId", "")),
                "status": str(first.get("status", "") or result.get("status", "")),
            })
        except mc.ProviderError as exc:
            failed.append({"scenario_id": sid, "error": str(exc)})
    return ActionResult.success(
        BulkRunResult(succeeded=succeeded, failed=failed),
        summary=f"{len(succeeded)} scenario(s) run, {len(failed)} failed.",
    )


@chat.function(
    "bulk_delete_connections",
    "Permanently delete SEVERAL Make connections at once, by explicit "
    "connection ids. Any scenario using one will stop working once it's "
    "gone.",
    action_type="destructive",
    chain_callable=True,
    data_model=BulkDeleteResult,
)
async def bulk_delete_connections(ctx, params: BulkDeleteConnectionsParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    deleted: list[str] = []
    failed: list[dict] = []
    for cid in params.connection_ids:
        try:
            did = await mc.delete_connection(ctx, token, zone, cid, confirmed=True)
            deleted.append(str(did))
        except mc.ProviderError as exc:
            failed.append({"connection_id": cid, "error": str(exc)})
    return ActionResult.success(
        BulkDeleteResult(deleted_count=len(deleted), ids=deleted, failed=failed),
        summary=f"{len(deleted)} connection(s) deleted, {len(failed)} failed.",
    )


@chat.function(
    "bulk_delete_hooks",
    "Permanently remove SEVERAL Make hooks at once, by explicit hook "
    "ids. Any scenario using one will stop working once it's gone.",
    action_type="destructive",
    chain_callable=True,
    data_model=BulkDeleteResult,
)
async def bulk_delete_hooks(ctx, params: BulkDeleteHooksParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    deleted: list[str] = []
    failed: list[dict] = []
    for hid in params.hook_ids:
        try:
            did = await mc.delete_hook(ctx, token, zone, hid, confirmed=True)
            deleted.append(str(did))
        except mc.ProviderError as exc:
            failed.append({"hook_id": hid, "error": str(exc)})
    return ActionResult.success(
        BulkDeleteResult(deleted_count=len(deleted), ids=deleted, failed=failed),
        summary=f"{len(deleted)} hook(s) deleted, {len(failed)} failed.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 12: full control -- safe blueprint module field editing.
#
# Make's PATCH /scenarios/{id} only accepts the WHOLE blueprint document
# (per Make's own docs, sent as a JSON string) -- there is no endpoint to
# patch a single module field server-side. So "safely edit one field" is
# built here as: fetch the live blueprint, locate the module by its own
# id, read/replace exactly that one key inside its mapper, and PATCH the
# whole document back -- gated by a state token (hash of the blueprint at
# preview time) so a concurrent edit (e.g. in the Make UI) is refused
# instead of silently overwritten, same discipline as every other
# preview/apply pair on this platform.
# ──────────────────────────────────────────────────────────────────────────


def _find_module_in_flow(flow: list, module_id: int) -> dict | None:
    for node in flow:
        if int(node.get("id") or -1) == module_id:
            return node
        for route in (node.get("routes") or []):
            found = _find_module_in_flow(route.get("flow") or [], module_id)
            if found is not None:
                return found
    return None


@chat.function(
    "preview_update_blueprint_module",
    "Preview changing ONE field inside a module's own settings (its "
    "mapper -- e.g. an AI module's prompt text) without writing anything. "
    "Shows the current value, the proposed value, and a state token that "
    "apply_update_blueprint_module must be given unchanged. Use "
    "get_scenario_blueprint's raw_config on the module first to see the "
    "exact field names available.",
    action_type="read",
    chain_callable=True,
    data_model=BlueprintModuleFieldPreview,
)
async def preview_update_blueprint_module(ctx, params: PreviewUpdateBlueprintModuleParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        blueprint = await mc.get_scenario_blueprint(ctx, token, zone, params.scenario_id, draft=params.draft)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    flow = blueprint.get("flow") or []
    module = _find_module_in_flow(flow, params.module_id)
    if module is None:
        return ActionResult.error(
            f"No module with id {params.module_id} found in this scenario's blueprint.",
            code="MAKE_MODULE_NOT_FOUND",
        )
    mapper = module.get("mapper") or {}
    current = mapper.get(params.field)
    token_hash = mc.blueprint_state_hash(blueprint)
    result = BlueprintModuleFieldPreview(
        scenario_id=params.scenario_id, module_id=params.module_id, field=params.field,
        current_value=str(current) if current is not None else "",
        proposed_value=params.value,
        field_exists=params.field in mapper,
        expected_state_token=token_hash,
    )
    note = "" if result.field_exists else " (this field does not exist yet on this module -- it will be added)"
    return ActionResult.success(
        result,
        summary=f"Module {params.module_id}, field '{params.field}': "
                f"'{result.current_value}' -> '{params.value}'{note}. "
                f"Pass expected_state_token to apply_update_blueprint_module to confirm.",
    )


@chat.function(
    "apply_update_blueprint_module",
    "Apply a previously previewed change to ONE field inside a module's "
    "own settings (e.g. an AI module's prompt text). Re-reads the exact "
    "scenario blueprint and refuses to write if it changed since preview.",
    action_type="write",
    chain_callable=True,
    data_model=BlueprintModuleUpdateResult,
    event="make-com-connector.apply_update_blueprint_module",
    effects=["make.scenario.blueprint_module_updated"],
)
async def apply_update_blueprint_module(ctx, params: ApplyUpdateBlueprintModuleParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        blueprint = await mc.get_scenario_blueprint(ctx, token, zone, params.scenario_id, draft=params.draft)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    current_hash = mc.blueprint_state_hash(blueprint)
    if current_hash != params.expected_state_token:
        return ActionResult.error(
            "This scenario's blueprint changed since you previewed this edit "
            "(e.g. someone edited it in Make). Run preview_update_blueprint_module "
            "again and re-apply with the new token to avoid overwriting that change.",
            code="MAKE_STATE_CHANGED",
        )
    flow = blueprint.get("flow") or []
    module = _find_module_in_flow(flow, params.module_id)
    if module is None:
        return ActionResult.error(
            f"No module with id {params.module_id} found in this scenario's blueprint.",
            code="MAKE_MODULE_NOT_FOUND",
        )
    mapper = module.setdefault("mapper", {})
    mapper[params.field] = params.value
    try:
        await mc.update_scenario(
            ctx, token, zone, params.scenario_id, blueprint=blueprint, confirmed=params.confirmed,
        )
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        BlueprintModuleUpdateResult(
            scenario_id=params.scenario_id, module_id=params.module_id,
            field=params.field, new_value=params.value, applied=True,
        ),
        summary=f"Module {params.module_id}, field '{params.field}' updated.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 13: scenario lifecycle -- create/delete/restore/clone, scheduling.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "create_scenario",
    "Create a brand-new, empty Make scenario in a team. You'll still need "
    "to add modules via preview_update_blueprint_module/apply_update_blueprint_module "
    "or the Make editor -- this just creates the container.",
    action_type="write",
    chain_callable=True,
    data_model=MakeScenario,
    event="make-com-connector.create_scenario",
    effects=["make.scenario.created"],
)
async def create_scenario(ctx, params: CreateScenarioParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    blueprint = {"name": params.name, "flow": [], "metadata": {"instant": False}}
    try:
        raw = await mc.create_scenario(
            ctx, token, zone, blueprint=blueprint, team_id=params.team_id,
            folder_id=params.folder_id, description=params.description,
            confirmed=params.confirmed,
        )
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    result = MakeScenario(
        id=str(raw.get("id", "")), title=raw.get("name", params.name),
        scenario_id=int(raw.get("id") or 0), is_active=bool(raw.get("isActive")),
        team_id=int(raw.get("teamId") or params.team_id),
    )
    return ActionResult.success(result, summary=f"Scenario '{params.name}' created.", refresh_panels=["make_connect"])


@chat.function(
    "delete_scenario",
    "Delete a Make scenario. Make keeps it recoverable in Trash for 30 "
    "days -- use restore_scenario to bring it back within that window.",
    action_type="write",
    chain_callable=True,
    data_model=DeleteResult,
    event="make-com-connector.delete_scenario",
    effects=["make.scenario.deleted"],
)
async def delete_scenario(ctx, params: DeleteScenarioParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        did = await mc.delete_scenario(ctx, token, zone, params.scenario_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        DeleteResult(deleted=True, id=str(did)),
        summary=f"Scenario {params.scenario_id} moved to Trash (recoverable for 30 days).",
        refresh_panels=["make_connect"],
    )


@chat.function(
    "restore_scenario",
    "Restore a deleted Make scenario from Trash, within Make's 30-day recovery window.",
    action_type="write",
    chain_callable=True,
    data_model=MakeScenario,
    event="make-com-connector.restore_scenario",
    effects=["make.scenario.restored"],
)
async def restore_scenario(ctx, params: RestoreScenarioParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.restore_scenario(ctx, token, zone, params.scenario_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    result = MakeScenario(
        id=str(raw.get("id", params.scenario_id)), title=raw.get("name", ""),
        scenario_id=int(raw.get("id") or params.scenario_id),
        is_active=bool(raw.get("isActive")), team_id=int(raw.get("teamId") or 0),
    )
    return ActionResult.success(result, summary=f"Scenario {params.scenario_id} restored.", refresh_panels=["make_connect"])


@chat.function(
    "clone_scenario",
    "Clone an existing Make scenario -- same modules/connections, a new "
    "id and name. Optionally into a different team.",
    action_type="write",
    chain_callable=True,
    data_model=MakeScenario,
    event="make-com-connector.clone_scenario",
    effects=["make.scenario.cloned"],
)
async def clone_scenario(ctx, params: CloneScenarioParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.clone_scenario(
            ctx, token, zone, params.scenario_id, name=params.name,
            team_id=params.team_id, states=params.keep_states, confirmed=params.confirmed,
        )
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    new_id = raw.get("id") or (raw.get("scenario") or {}).get("id")
    result = MakeScenario(
        id=str(new_id or ""), title=params.name, scenario_id=int(new_id or 0),
        is_active=False, team_id=int(params.team_id or 0),
    )
    return ActionResult.success(result, summary=f"Scenario cloned as '{params.name}'.", refresh_panels=["make_connect"])


@chat.function(
    "update_scheduling",
    "Change how/when a scenario runs (interval, cron, on-demand, etc.) "
    "without touching its modules.",
    action_type="write",
    chain_callable=True,
    data_model=SchedulingResult,
    event="make-com-connector.update_scheduling",
    effects=["make.scenario.scheduling_changed"],
)
async def update_scheduling(ctx, params: UpdateSchedulingParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    scheduling: dict = {"type": params.scheduling_type}
    if params.interval is not None:
        scheduling["interval"] = params.interval
    if params.cron is not None:
        scheduling["cron"] = params.cron
    try:
        await mc.update_scenario(ctx, token, zone, params.scenario_id, scheduling=scheduling)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        SchedulingResult(scenario_id=params.scenario_id, scheduling_type=params.scheduling_type, interval=params.interval or 0),
        summary=f"Scenario {params.scenario_id} scheduling updated to '{params.scheduling_type}'.",
        refresh_panels=["make_connect"],
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 14: buildtime variables + usage.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_buildtime_variables",
    "List a scenario's buildtime (installation-time) variables -- the "
    "named inputs it was configured with, separate from its runtime data.",
    action_type="read",
    chain_callable=True,
    data_model=BuildtimeVariableList,
)
async def list_buildtime_variables(ctx, params: ListBuildtimeVariablesParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.list_buildtime_variables(ctx, token, zone, params.scenario_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [BuildtimeVariable(id=k, title=k, name=k, value=str(v)) for k, v in raw.items()]
    return ActionResult.success(BuildtimeVariableList(items=items, total=len(items), scenario_id=params.scenario_id))


@chat.function(
    "set_buildtime_variable",
    "Add a new buildtime variable to a scenario, or update an existing one's value.",
    action_type="write",
    chain_callable=True,
    data_model=BuildtimeVariable,
    event="make-com-connector.set_buildtime_variable",
    effects=["make.scenario.buildtime_variable_set"],
)
async def set_buildtime_variable(ctx, params: SetBuildtimeVariableParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        await mc.set_buildtime_variables(
            ctx, token, zone, params.scenario_id,
            [{"name": params.name, "value": params.value}], create=params.create_new,
        )
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        BuildtimeVariable(id=params.name, title=params.name, name=params.name, value=params.value),
        summary=f"Variable '{params.name}' {'created' if params.create_new else 'updated'}.",
    )


@chat.function(
    "delete_buildtime_variable",
    "Remove a buildtime variable from a scenario.",
    action_type="write",
    chain_callable=True,
    data_model=DeleteResult,
    event="make-com-connector.delete_buildtime_variable",
    effects=["make.scenario.buildtime_variable_deleted"],
)
async def delete_buildtime_variable(ctx, params: DeleteBuildtimeVariableParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        await mc.delete_buildtime_variable(ctx, token, zone, params.scenario_id, params.name)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(DeleteResult(deleted=True, id=params.name), summary=f"Variable '{params.name}' deleted.")


@chat.function(
    "get_scenario_usage",
    "Read a scenario's own operations/data-transfer usage history -- how "
    "much of your Make plan quota it has consumed, per day.",
    action_type="read",
    chain_callable=True,
    data_model=ScenarioUsageReport,
)
async def get_scenario_usage(ctx, params: GetScenarioUsageParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.get_scenario_usage(ctx, token, zone, params.scenario_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [
        UsageDay(
            id=d.get("date", ""), title=d.get("date", ""), date=d.get("date", ""),
            operations=int(d.get("operations") or 0), data_transfer=int(d.get("dataTransfer") or 0),
            centicredits=int(d.get("centicredits") or 0),
        )
        for d in raw
    ]
    return ActionResult.success(ScenarioUsageReport(items=items, total=len(items), scenario_id=params.scenario_id))


# ──────────────────────────────────────────────────────────────────────────
# Срез 15: execution history -- what actually happened on each run.
# ──────────────────────────────────────────────────────────────────────────

_STATUS_TO_CODE = {"success": 1, "warning": 2, "error": 3}
_CODE_TO_STATUS = {1: "success", 2: "warning", 3: "error"}


@chat.function(
    "list_scenario_logs",
    "List a scenario's own operations/data-transfer usage history -- how "
    "much of your Make quota each run consumed, most recent first.",
    action_type="read",
    chain_callable=True,
    data_model=ScenarioExecutionLogList,
)
async def list_scenario_logs(ctx, params: ListScenarioLogsParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    status_code = _STATUS_TO_CODE.get((params.status or "").lower())
    try:
        raw = await mc.list_scenario_logs(
            ctx, token, zone, params.scenario_id, status=status_code, limit=params.limit,
        )
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [
        ScenarioExecutionLog(
            id=str(l.get("id", "")), title=f"Run {l.get('id', '')}",
            execution_id=str(l.get("id", "")),
            status=_CODE_TO_STATUS.get(l.get("status"), str(l.get("status", ""))),
            duration_ms=int(l.get("duration") or 0),
            operations=int(l.get("operations") or 0),
            transfer_bytes=int(l.get("transfer") or 0),
            timestamp=str(l.get("finished") or l.get("started") or ""),
            author_name=str(l.get("author", {}).get("name", "") if isinstance(l.get("author"), dict) else ""),
            instant=bool(l.get("instant")),
        )
        for l in raw
    ]
    return ActionResult.success(
        ScenarioExecutionLogList(items=items, total=len(items), scenario_id=params.scenario_id),
    )


@chat.function(
    "get_execution_details",
    "Read one scenario execution in full -- its actual outputs, or on "
    "failure the error message and which module/app caused it.",
    action_type="read",
    chain_callable=True,
    data_model=ExecutionDetails,
)
async def get_execution_details(ctx, params: GetExecutionDetailsParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.get_execution_details(ctx, token, zone, params.scenario_id, params.execution_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    execution = raw.get("scenarioLog") or raw.get("execution") or raw
    error = execution.get("error") or {}
    result = ExecutionDetails(
        id=str(execution.get("id", params.execution_id)),
        title=f"Execution {params.execution_id}",
        status=_CODE_TO_STATUS.get(execution.get("status"), str(execution.get("status", ""))),
        outputs=execution.get("bundles") or execution.get("outputs") or {},
        error_name=str(error.get("name", "")) if isinstance(error, dict) else "",
        error_message=str(error.get("message", "")) if isinstance(error, dict) else (str(error) if error else ""),
        error_module_name=str((error.get("subModule") or {}).get("label", "")) if isinstance(error, dict) else "",
        error_app_name=str((error.get("subModule") or {}).get("app", "")) if isinstance(error, dict) else "",
    )
    return ActionResult.success(result)


@chat.function(
    "stop_execution",
    "Stop a currently-running scenario execution.",
    action_type="write",
    chain_callable=True,
    data_model=DeleteResult,
    event="make-com-connector.stop_execution",
    effects=["make.execution.stopped"],
)
async def stop_execution(ctx, params: StopExecutionParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        await mc.stop_execution(ctx, token, zone, params.scenario_id, params.execution_id, force=params.force)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        DeleteResult(deleted=True, id=params.execution_id),
        summary=f"Execution {params.execution_id} stopped.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 16: blueprint module add/remove -- the other half of "full control"
# beyond editing an existing module's own fields. Same discipline as
# preview_update_blueprint_module: read the live blueprint, mutate flow[]
# in memory, PATCH the whole document back, gated by a state token so a
# concurrent edit is refused instead of silently overwritten.
# ──────────────────────────────────────────────────────────────────────────


def _insert_after(flow: list, after_module_id: int | None, new_node: dict) -> bool:
    """Insert new_node right after the module with id == after_module_id,
    searching the top-level flow AND recursively inside every router
    branch (routes[].flow) -- same reach as _find_module_in_flow, so a
    module can be added right after any existing module regardless of
    which branch it lives in. Appends to the top-level flow if
    after_module_id is None or not found anywhere."""
    if after_module_id is None:
        flow.append(new_node)
        return True

    def try_insert(nodes: list) -> bool:
        for i, node in enumerate(nodes):
            if int(node.get("id") or -1) == after_module_id:
                nodes.insert(i + 1, new_node)
                return True
            for route in (node.get("routes") or []):
                route_flow = route.setdefault("flow", [])
                if try_insert(route_flow):
                    return True
        return False

    if try_insert(flow):
        return True
    flow.append(new_node)
    return True


def _remove_module_from_flow(flow: list, module_id: int) -> bool:
    """Remove the module with this id from wherever it lives -- the
    top-level flow or inside any router branch -- mutating in place.
    Returns True if a module was actually removed."""
    for i, node in enumerate(flow):
        if int(node.get("id") or -1) == module_id:
            del flow[i]
            return True
        for route in (node.get("routes") or []):
            route_flow = route.get("flow") or []
            if _remove_module_from_flow(route_flow, module_id):
                return True
    return False


def _next_module_id(flow: list) -> int:
    ids = [int(n.get("id") or 0) for n in flow]
    for route_node in flow:
        for route in (route_node.get("routes") or []):
            ids += [int(n.get("id") or 0) for n in (route.get("flow") or [])]
    return (max(ids) + 1) if ids else 1


@chat.function(
    "preview_add_blueprint_module",
    "Preview adding a brand-new module to a scenario's flow, without "
    "writing anything. Shows where it will land and a state token that "
    "apply_add_blueprint_module must be given unchanged. Use "
    "get_scenario_blueprint on a similar existing module first to see the "
    "exact app_module id and mapper shape to copy.",
    action_type="read",
    chain_callable=True,
    data_model=BlueprintModuleAddPreview,
)
async def preview_add_blueprint_module(ctx, params: PreviewAddBlueprintModuleParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        blueprint = await mc.get_scenario_blueprint(ctx, token, zone, params.scenario_id, draft=params.draft)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    flow = blueprint.get("flow") or []
    before = len(_flatten_blueprint_modules(flow))
    token_hash = mc.blueprint_state_hash(blueprint)
    result = BlueprintModuleAddPreview(
        scenario_id=params.scenario_id, app_module=params.app_module,
        position_after=params.after_module_id or 0,
        total_modules_before=before, total_modules_after=before + 1,
        expected_state_token=token_hash,
    )
    return ActionResult.success(
        result,
        summary=f"Will add '{params.app_module}' ({before} -> {before + 1} modules). "
                f"Pass expected_state_token to apply_add_blueprint_module to confirm.",
    )


@chat.function(
    "apply_add_blueprint_module",
    "Apply a previously previewed new module addition to a scenario. "
    "Re-reads the exact scenario blueprint and refuses to write if it "
    "changed since preview.",
    action_type="write",
    chain_callable=True,
    data_model=BlueprintModuleAddResult,
    event="make-com-connector.apply_add_blueprint_module",
    effects=["make.scenario.blueprint_module_added"],
)
async def apply_add_blueprint_module(ctx, params: ApplyAddBlueprintModuleParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        blueprint = await mc.get_scenario_blueprint(ctx, token, zone, params.scenario_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    current_hash = mc.blueprint_state_hash(blueprint)
    if current_hash != params.expected_state_token:
        return ActionResult.error(
            "This scenario's blueprint changed since you previewed this add "
            "(e.g. someone edited it in the Make UI). Run preview_add_blueprint_module "
            "again to get a fresh state token.",
            code="MAKE_BLUEPRINT_STATE_MISMATCH",
        )
    flow = blueprint.get("flow") or []
    new_id = _next_module_id(flow)
    new_node = {"id": new_id, "module": params.app_module, "version": 1, "mapper": params.mapper, "metadata": {}}
    _insert_after(flow, params.after_module_id, new_node)
    blueprint["flow"] = flow
    try:
        await mc.update_scenario(ctx, token, zone, params.scenario_id, blueprint=blueprint)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        BlueprintModuleAddResult(
            scenario_id=params.scenario_id, new_module_id=new_id,
            total_modules=len(_flatten_blueprint_modules(flow)),
        ),
        summary=f"Module '{params.app_module}' added (id {new_id}).",
        refresh_panels=["make_connect"],
    )


@chat.function(
    "preview_delete_blueprint_module",
    "Preview removing one module from a scenario's flow, without writing "
    "anything. Shows a state token that apply_delete_blueprint_module "
    "must be given unchanged.",
    action_type="read",
    chain_callable=True,
    data_model=BlueprintModuleDeletePreview,
)
async def preview_delete_blueprint_module(ctx, params: PreviewDeleteBlueprintModuleParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        blueprint = await mc.get_scenario_blueprint(ctx, token, zone, params.scenario_id, draft=params.draft)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    flow = blueprint.get("flow") or []
    target = _find_module_in_flow(flow, params.module_id)
    if target is None:
        return ActionResult.error(
            f"No module with id {params.module_id} found in this scenario's flow.",
            code="MAKE_MODULE_NOT_FOUND",
        )
    before = len(_flatten_blueprint_modules(flow))
    token_hash = mc.blueprint_state_hash(blueprint)
    title = target.get("label") or target.get("module") or f"Module {params.module_id}"
    result = BlueprintModuleDeletePreview(
        scenario_id=params.scenario_id, module_id=params.module_id, module_title=title,
        total_modules_before=before, total_modules_after=before - 1,
        expected_state_token=token_hash,
    )
    return ActionResult.success(
        result,
        summary=f"Will remove '{title}' ({before} -> {before - 1} modules). "
                f"Pass expected_state_token to apply_delete_blueprint_module to confirm.",
    )


@chat.function(
    "apply_delete_blueprint_module",
    "Apply a previously previewed module removal from a scenario. "
    "Re-reads the exact scenario blueprint and refuses to write if it "
    "changed since preview.",
    action_type="write",
    chain_callable=True,
    data_model=BlueprintModuleDeleteResult,
    event="make-com-connector.apply_delete_blueprint_module",
    effects=["make.scenario.blueprint_module_deleted"],
)
async def apply_delete_blueprint_module(ctx, params: ApplyDeleteBlueprintModuleParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        blueprint = await mc.get_scenario_blueprint(ctx, token, zone, params.scenario_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    current_hash = mc.blueprint_state_hash(blueprint)
    if current_hash != params.expected_state_token:
        return ActionResult.error(
            "This scenario's blueprint changed since you previewed this delete "
            "(e.g. someone edited it in the Make UI). Run preview_delete_blueprint_module "
            "again to get a fresh state token.",
            code="MAKE_BLUEPRINT_STATE_MISMATCH",
        )
    flow = blueprint.get("flow") or []
    if not _remove_module_from_flow(flow, params.module_id):
        return ActionResult.error(
            f"No module with id {params.module_id} found (it may already be removed).",
            code="MAKE_MODULE_NOT_FOUND",
        )
    blueprint["flow"] = flow
    try:
        await mc.update_scenario(ctx, token, zone, params.scenario_id, blueprint=blueprint)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        BlueprintModuleDeleteResult(
            scenario_id=params.scenario_id, deleted_module_id=params.module_id,
            total_modules=len(_flatten_blueprint_modules(flow)),
        ),
        summary=f"Module {params.module_id} removed.",
        refresh_panels=["make_connect"],
    )


# ──────────────────────────────────────────────────────────────────────────
# Срез 17: account-level control -- organizations, team members/roles, and
# the connected user's own API tokens. Last layer beyond scenarios/data:
# WHO can see/change things, and what credentials exist.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "list_organizations",
    "List the Make.com organizations the connected account belongs to -- "
    "the level above teams (an organization can contain several teams).",
    action_type="read",
    chain_callable=True,
    data_model=MakeOrganizationList,
)
async def list_organizations(ctx, params: ListOrganizationsParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.list_organizations(ctx, token, zone)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [
        MakeOrganization(
            id=str(o.get("id", "")), title=o.get("name", ""),
            org_id=int(o.get("id") or 0), name=o.get("name", ""),
            country=o.get("countryId") and str(o.get("countryId")) or "",
            timezone=o.get("timezone", ""),
        )
        for o in raw
    ]
    return ActionResult.success(MakeOrganizationList(items=items, total=len(items)))


@chat.function(
    "list_team_members",
    "List the people with access to a Make team and their role -- Team "
    "Member, Team Admin, Team Monitoring, or a custom org role (shown by "
    "its numeric id).",
    action_type="read",
    chain_callable=True,
    data_model=TeamMemberList,
)
async def list_team_members(ctx, params: ListTeamMembersParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.list_team_members(ctx, token, zone, params.team_id)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [
        TeamMember(
            id=str(m.get("id", "")), title=f"User {m.get('userId', '')}",
            user_id=int(m.get("userId") or 0), team_id=params.team_id,
            role_id=int(m.get("roleId") or 0),
            role_name=mc.MAKE_TEAM_ROLE_NAMES.get(m.get("roleId"), str(m.get("roleId", ""))),
            changeable=bool(m.get("changeable", True)),
        )
        for m in raw
    ]
    return ActionResult.success(TeamMemberList(items=items, total=len(items), team_id=params.team_id))


@chat.function(
    "list_api_tokens",
    "List the connected Make user's own API tokens -- label, scopes, "
    "creation date, and a masked form. Never exposes a usable secret; use "
    "create_api_token to mint a new one when a real value is needed.",
    action_type="read",
    chain_callable=True,
    data_model=MakeApiTokenList,
)
async def list_api_tokens(ctx, params: ListApiTokensParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.list_api_tokens(ctx, token, zone)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    items = [
        MakeApiToken(
            id=str(t.get("id", "")), title=t.get("label") or f"Token {t.get('id', '')}",
            label=t.get("label", ""), scope=t.get("scope") or [],
            created=str(t.get("createdAt", "")),
            token_masked=str(t.get("token", "")),
        )
        for t in raw
    ]
    return ActionResult.success(MakeApiTokenList(items=items, total=len(items)))


@chat.function(
    "create_api_token",
    "Create a brand-new Make API token for the CONNECTED user's own "
    "account. The secret value is returned exactly ONCE, same as Make's "
    "own UI -- it cannot be retrieved again afterwards. This mints a real, "
    "usable credential -- treat it like creating a password.",
    action_type="write",
    chain_callable=True,
    data_model=CreatedApiToken,
    event="make-com-connector.create_api_token",
    effects=["make.api_token.created"],
)
async def create_api_token(ctx, params: CreateApiTokenParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.create_api_token(ctx, token, zone, label=params.label, scope=params.scope)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    result = CreatedApiToken(
        id=str(raw.get("id", "")), title=params.label,
        token=str(raw.get("token", "")),
        label=params.label, scope=raw.get("scope") or params.scope,
    )
    return ActionResult.success(
        result,
        summary=f"API token '{params.label}' created. Save the secret now -- it will not be shown again.",
    )


@chat.function(
    "delete_api_token",
    "Permanently delete one of the connected user's own Make API tokens. "
    "Anything using it (external scripts, other integrations) stops "
    "working immediately.",
    action_type="destructive",
    chain_callable=True,
    data_model=DeleteResult,
    event="make-com-connector.delete_api_token",
    effects=["make.api_token.deleted"],
)
async def delete_api_token(ctx, params: DeleteApiTokenParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        await mc.delete_api_token(ctx, token, zone, params.created_timestamp)
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    return ActionResult.success(
        DeleteResult(deleted=True, id=params.created_timestamp),
        summary=f"API token (created {params.created_timestamp}) deleted.",
    )


@chat.function(
    "create_hook",
    "Create a new incoming webhook/mailhook (Make 'hook') in a team -- a "
    "fresh trigger point a scenario can listen on. For a generic HTTP "
    "webhook, type_name='gateway-webhook' works without a connection_id; "
    "app-specific hook types may need one -- check an existing similar "
    "hook via list_hooks first when unsure.",
    action_type="write",
    chain_callable=True,
    data_model=MakeHook,
    event="make-com-connector.create_hook",
    effects=["make.hook.created"],
)
async def create_hook(ctx, params: CreateHookParams) -> ActionResult:
    token, zone = await _get_credentials(ctx)
    if not token or not zone:
        return ActionResult.error("Not connected to Make.com yet.", code="MAKE_NOT_CONNECTED")
    try:
        raw = await mc.create_hook(
            ctx, token, zone,
            name=params.name, team_id=params.team_id, type_name=params.type_name,
            include_method=params.include_method, include_headers=params.include_headers,
            stringify=params.stringify, connection_id=params.connection_id, form_id=params.form_id,
        )
    except mc.ProviderError as exc:
        return ActionResult.error(str(exc), code=exc.code)
    result = MakeHook(
        id=str(raw.get("id", "")), title=raw.get("name", params.name),
        hook_id=int(raw.get("id") or 0), type_name=raw.get("typeName", params.type_name),
        url=raw.get("url", ""), enabled=bool(raw.get("enabled", True)),
        scenario_id=raw.get("scenarioId"), queue_count=int(raw.get("queueCount") or 0),
    )
    return ActionResult.success(
        result, summary=f"Hook '{params.name}' created (id {result.hook_id}).",
        refresh_panels=["make_connect"],
    )
