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
)

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
    action_type="write",
    chain_callable=True,
    data_model=ScenarioRunResult,
    event="make-com-connector.run_scenario",
    effects=["make.scenario.run"],
)
async def run_scenario(ctx, params: RunScenarioParams) -> ActionResult:
    """Gated on an explicit `confirm`, same pattern as Trello's delete_board:
    a scenario run is a real action in a real external system (Make), with
    whatever side effects that scenario is built to have -- there is no way
    for this connector to know if those are reversible, so it never assumes
    they are."""
    if not params.confirm:
        return ActionResult.error(
            "Running a Make scenario executes its real actions right now "
            "(sending emails, writing to connected apps, etc.) with no "
            "dry-run or undo. Pass confirm=true if that is really the intent.",
            code="MAKE_CONFIRM_REQUIRED",
        )

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
