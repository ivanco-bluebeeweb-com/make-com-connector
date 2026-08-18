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
