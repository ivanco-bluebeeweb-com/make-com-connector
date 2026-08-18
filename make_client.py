"""Make.com API v2 client -- token auth, zone auto-discovery, and thin
wrappers around the scenario endpoints this connector exposes.

WHY ZONE AUTO-DISCOVERY, NOT A USER-ENTERED FIELD.

Per Make's own "API structure" doc, every request goes to
`https://{zone}/api/v2/{endpoint}` where `{zone}` is account-specific
(eu1.make.com, eu2.make.com, us1.make.com, us2.make.com, and celonis
on-prem variants) -- there is no single global host, and a token from one
zone is rejected outright by another zone's host. Asking a first-time
user to go find their own zone in the browser URL bar is unnecessary
friction, so `discover_zone` probes the known public zones with the
cheap, side-effect-free `GET /users/me` call until one accepts the
token, then the caller persists the winning zone so every later call
skips straight to it.

WHY `Authorization: Token <token>`, NOT Bearer/Basic.

Make's own docs are explicit: the header value is the literal string
`Token your-api-token` (not `Bearer ...`) -- a different scheme from
DataForSEO's Basic auth or Magnific's custom header, so it is built here
rather than assumed.
"""
from __future__ import annotations

# Public Make zones, per developers.make.com/api-documentation/
# getting-started/api-structure. Tried in this order when the zone is not
# yet known -- eu1 first since it's Make's original/most common zone.
KNOWN_ZONES: list[str] = [
    "eu1.make.com",
    "eu2.make.com",
    "us1.make.com",
    "us2.make.com",
]


class ProviderError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _headers(token: str) -> dict:
    return {"Authorization": f"Token {token}", "Accept": "*/*"}


def _error_detail(resp) -> str:
    """Make's own unified error schema is {"detail", "message", "code"}
    (e.g. code="SC403"/"IM002" for a valid token missing a scope, vs a
    plain 401 for a token the zone doesn't recognise at all) -- surface
    it instead of discarding the body, since it's the one thing that
    tells a real auth failure apart from a real scope failure."""
    body = resp.body if isinstance(resp.body, dict) else {}
    detail = body.get("detail") or body.get("message") or ""
    code = body.get("code") or ""
    if detail and code:
        return f"{detail} (Make code: {code})"
    return detail or code or ""


def _check_status(resp, action: str) -> dict:
    if resp.status_code == 401:
        detail = _error_detail(resp)
        raise ProviderError(
            f"Make {action} failed: token rejected (HTTP 401)"
            + (f" -- {detail}" if detail else ""),
            "MAKE_AUTH_ERROR",
        )
    if resp.status_code == 403:
        detail = _error_detail(resp)
        raise ProviderError(
            f"Make {action} failed: access denied (HTTP 403)"
            + (f" -- {detail}." if detail else ".")
            + " Your token is valid but likely missing a required scope for "
              "this action -- edit it in Make: avatar -> Profile -> API tab, "
              "and add the missing scope(s).",
            "MAKE_SCOPE_ERROR",
        )
    if resp.status_code >= 400:
        raise ProviderError(
            f"Make {action} failed: HTTP {resp.status_code}", "MAKE_HTTP_ERROR",
        )
    return resp.body if isinstance(resp.body, dict) else {}


async def discover_zone(ctx, token: str) -> tuple[str, dict]:
    """Try each known public zone's GET /users/me (requires the
    organizations:read scope, per Make's own OpenAPI spec) with this token
    until one accepts it.

    401 vs 403 here mean genuinely different things and must NOT be
    conflated: a 401 means this zone doesn't recognise the token at all
    (keep probing -- it may belong to another zone), while a 403 means
    this IS the right zone -- Make found the token and knows who it
    belongs to -- but the token lacks the organizations:read scope. A 403
    therefore stops the probe immediately and reports the real, fixable
    cause (missing scope) instead of masquerading as \"rejected by every
    zone\", which would wrongly suggest the token itself is invalid.

    Returns (winning zone host, authUser dict from that same response --
    no second round-trip needed). Raises ProviderError if every known
    public zone returns 401 -- e.g. an on-prem/custom zone (eu1.make.
    celonis.com etc.) that the user must supply manually via the platform
    Secrets screen instead."""
    last_error: ProviderError | None = None
    for zone in KNOWN_ZONES:
        resp = await ctx.http.get(
            f"https://{zone}/api/v2/users/me", headers=_headers(token),
        )
        if resp.status_code == 200:
            body = resp.body if isinstance(resp.body, dict) else {}
            return zone, (body.get("authUser") or {})
        if resp.status_code == 403:
            detail = _error_detail(resp)
            raise ProviderError(
                f"Your Make token was recognised on {zone}, but it's missing "
                "the 'organizations:read' scope this connector needs to set "
                "up your account." + (f" ({detail})" if detail else "") +
                " Fix: in Make, go to avatar -> Profile -> API tab, edit (or "
                "recreate) this token, and make sure 'organizations:read' is "
                "checked, then try connecting again.",
                "MAKE_SCOPE_ERROR",
            )
        if resp.status_code == 401:
            last_error = ProviderError(
                f"Make token rejected by every known zone ({', '.join(KNOWN_ZONES)}). "
                "If your organization uses a custom/on-prem zone, that isn't "
                "auto-detected yet -- check your Make dashboard's URL bar.",
                "MAKE_AUTH_ERROR",
            )
    raise last_error or ProviderError("Could not reach any known Make zone", "MAKE_NETWORK_ERROR")


async def get_current_user(ctx, token: str, zone: str) -> dict:
    resp = await ctx.http.get(f"https://{zone}/api/v2/users/me", headers=_headers(token))
    body = _check_status(resp, "account check")
    return body.get("authUser") or {}


async def list_scenarios(
    ctx, token: str, zone: str, *, team_id: int | None, organization_id: int | None,
    limit: int = 100, offset: int = 0,
) -> tuple[list[dict], dict]:
    """GET /scenarios -- exactly one of team_id/organization_id must be set,
    per Make's own API (the two are mutually exclusive filters)."""
    if not team_id and not organization_id:
        raise ProviderError(
            "list_scenarios needs either a team_id or an organization_id",
            "MAKE_MISSING_SCOPE",
        )
    params: dict = {"limit": limit, "offset": offset}
    if team_id:
        params["teamId"] = team_id
    else:
        params["organizationId"] = organization_id
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/scenarios", headers=_headers(token), params=params,
    )
    body = _check_status(resp, "list scenarios")
    return body.get("scenarios") or [], body.get("pg") or {}


async def get_scenario(ctx, token: str, zone: str, scenario_id: int) -> dict:
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/scenarios/{scenario_id}", headers=_headers(token),
    )
    body = _check_status(resp, "get scenario")
    return body.get("scenario") or {}


async def start_scenario(ctx, token: str, zone: str, scenario_id: int) -> dict:
    """POST /scenarios/{id}/start -- activates (schedules) a scenario."""
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/start", headers=_headers(token),
    )
    body = _check_status(resp, "activate scenario")
    return body.get("scenario") or {}


async def stop_scenario(ctx, token: str, zone: str, scenario_id: int) -> dict:
    """POST /scenarios/{id}/stop -- deactivates a scenario."""
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/stop", headers=_headers(token),
    )
    body = _check_status(resp, "deactivate scenario")
    return body.get("scenario") or {}


async def run_scenario(
    ctx, token: str, zone: str, scenario_id: int, *,
    data: dict | None = None, responsive: bool = True,
) -> dict:
    """POST /scenarios/{id}/run. `responsive=True` waits for the run to
    finish (up to Make's own 40s cap) and returns status+executionId in one
    round-trip -- the right default for a chat-turn action where the user
    is waiting to see the result, per Make's own docs on the responsive flag."""
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/run",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"data": data or {}, "responsive": responsive},
    )
    return _check_status(resp, "run scenario")


async def list_teams(ctx, token: str, zone: str, organization_id: int) -> list[dict]:
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/teams", headers=_headers(token),
        params={"organizationId": organization_id},
    )
    body = _check_status(resp, "list teams")
    return body.get("teams") or []


async def list_organizations(ctx, token: str, zone: str) -> list[dict]:
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/organizations", headers=_headers(token),
    )
    body = _check_status(resp, "list organizations")
    return body.get("organizations") or []


async def get_scenario_blueprint(
    ctx, token: str, zone: str, scenario_id: int, *, draft: bool | None = None,
) -> dict:
    """GET /scenarios/{id}/blueprint -- the actual module tree (flow[]),
    the one thing list_scenarios/get_scenario never return. This is what
    answers "what does module N do": each flow[] entry is one module, in
    the same 1-based order the Make editor numbers them."""
    params: dict = {}
    if draft is not None:
        params["draft"] = draft
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/blueprint",
        headers=_headers(token), params=params,
    )
    body = _check_status(resp, "get scenario blueprint")
    # This endpoint wraps its payload one level deeper: {code, response:{blueprint:{...}}}.
    return ((body.get("response") or {}).get("blueprint")) or body.get("blueprint") or {}


async def list_connections(ctx, token: str, zone: str, team_id: int) -> list[dict]:
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/connections", headers=_headers(token),
        params={"teamId": team_id},
    )
    body = _check_status(resp, "list connections")
    return body.get("connections") or []


async def delete_connection(ctx, token: str, zone: str, connection_id: int, *, confirmed: bool) -> int:
    resp = await ctx.http.delete(
        f"https://{zone}/api/v2/connections/{connection_id}",
        headers=_headers(token), params={"confirmed": confirmed},
    )
    body = _check_status(resp, "delete connection")
    return body.get("connection", connection_id)


async def rename_connection(ctx, token: str, zone: str, connection_id: int, name: str) -> dict:
    resp = await ctx.http.patch(
        f"https://{zone}/api/v2/connections/{connection_id}",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"name": name},
    )
    body = _check_status(resp, "rename connection")
    return body.get("connection") or {}


async def verify_connection(ctx, token: str, zone: str, connection_id: int) -> bool:
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/connections/{connection_id}/test", headers=_headers(token),
    )
    body = _check_status(resp, "verify connection")
    return bool(body.get("verified"))


async def list_data_stores(ctx, token: str, zone: str, team_id: int) -> list[dict]:
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/data-stores", headers=_headers(token),
        params={"teamId": team_id},
    )
    body = _check_status(resp, "list data stores")
    return body.get("dataStores") or []


async def create_data_store(
    ctx, token: str, zone: str, team_id: int, name: str, *,
    max_size_mb: int = 1, data_structure_id: int | None = None,
) -> dict:
    payload: dict = {"name": name, "teamId": team_id, "maxSizeMB": max_size_mb}
    if data_structure_id is not None:
        payload["dataStructureId"] = data_structure_id
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/data-stores",
        headers={**_headers(token), "Content-Type": "application/json"}, json=payload,
    )
    body = _check_status(resp, "create data store")
    return body.get("dataStore") or {}


async def delete_data_store(ctx, token: str, zone: str, data_store_id: int) -> int:
    resp = await ctx.http.delete(
        f"https://{zone}/api/v2/data-stores/{data_store_id}", headers=_headers(token),
    )
    body = _check_status(resp, "delete data store")
    return body.get("dataStore", data_store_id)


async def list_hooks(ctx, token: str, zone: str, team_id: int) -> list[dict]:
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/hooks", headers=_headers(token),
        params={"teamId": team_id},
    )
    body = _check_status(resp, "list hooks")
    return body.get("hooks") or []


async def set_hook_enabled(ctx, token: str, zone: str, hook_id: int, enabled: bool) -> bool:
    verb = "enable" if enabled else "disable"
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/hooks/{hook_id}/{verb}", headers=_headers(token),
    )
    body = _check_status(resp, f"{verb} hook")
    return bool(body.get("success"))


async def delete_hook(ctx, token: str, zone: str, hook_id: int, *, confirmed: bool) -> int:
    resp = await ctx.http.delete(
        f"https://{zone}/api/v2/hooks/{hook_id}",
        headers=_headers(token), params={"confirmed": confirmed},
    )
    body = _check_status(resp, "delete hook")
    return body.get("hook", hook_id)


async def list_incomplete_executions(
    ctx, token: str, zone: str, scenario_id: int, *, status: str | None = None,
) -> list[dict]:
    params: dict = {"scenarioId": scenario_id}
    if status:
        params["status"] = status
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/dlqs", headers=_headers(token), params=params,
    )
    body = _check_status(resp, "list incomplete executions")
    return body.get("dlqs") or []


async def retry_incomplete_execution(ctx, token: str, zone: str, dlq_id: str) -> dict:
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/dlqs/{dlq_id}/retry", headers=_headers(token),
    )
    return _check_status(resp, "retry incomplete execution")


async def delete_incomplete_executions(
    ctx, token: str, zone: str, scenario_id: int, *,
    ids: list[str] | None = None, all_: bool = False, confirmed: bool = False,
) -> list[str]:
    payload: dict = {}
    if all_:
        payload["all"] = True
    if ids:
        payload["ids"] = ids
    resp = await ctx.http.delete(
        f"https://{zone}/api/v2/dlqs",
        headers={**_headers(token), "Content-Type": "application/json"},
        params={"scenarioId": scenario_id, "confirmed": confirmed},
        json=payload,
    )
    body = _check_status(resp, "delete incomplete executions")
    return body.get("dlqs") or []


async def post_webhook(ctx, webhook_url: str, payload: dict) -> tuple[bool, int, str]:
    """POST an arbitrary JSON payload to a Make Custom Webhook trigger URL.

    Unlike every other call in this module, this does NOT go through
    `https://{zone}/api/v2/...` with a bearer token -- a Custom Webhook
    URL is its own secret (Make authenticates by knowing the URL, not by
    header), per Make's own "Custom webhook" trigger docs. Returns
    (delivered, status_code, detail) rather than raising, since a failed
    delivery to the USER's own downstream scenario is an expected,
    non-exceptional outcome the caller reports back, not a connector bug.
    """
    try:
        resp = await ctx.http.post(
            webhook_url, headers={"Content-Type": "application/json"}, json=payload,
        )
    except Exception as exc:  # network-level failure (DNS, timeout, refused)
        return False, 0, f"Could not reach the webhook URL: {exc}"

    status = getattr(resp, "status_code", 0)
    if 200 <= status < 300:
        return True, status, "Delivered."
    return False, status, f"Make responded with HTTP {status}."


# ──────────────────────────────────────────────────────────────────────────
# Срез 12: scenario CRUD (create/delete/clone/restore/trash) + scheduling +
# buildtime variables + usage -- the remaining surface for "full control".
# ──────────────────────────────────────────────────────────────────────────

import hashlib
import json as _json


def blueprint_state_hash(blueprint: dict) -> str:
    """Deterministic hash of a scenario's current blueprint -- used as the
    expected_state_token for safe read-verify-write module edits, so a
    concurrent edit (in the Make UI or elsewhere) is detected instead of
    silently overwritten."""
    canonical = _json.dumps(blueprint, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def update_scenario(
    ctx, token: str, zone: str, scenario_id: int, *,
    blueprint: dict | None = None, scheduling: dict | None = None,
    name: str | None = None, folder_id: int | None = None,
    confirmed: bool | None = None,
) -> dict:
    """PATCH /scenarios/{id}. Per Make's own docs, blueprint/scheduling
    must be sent as JSON-encoded STRINGS (not objects) to save resources,
    and any field omitted here is left unchanged server-side."""
    payload: dict = {}
    if blueprint is not None:
        payload["blueprint"] = _json.dumps(blueprint)
    if scheduling is not None:
        payload["scheduling"] = _json.dumps(scheduling)
    if name is not None:
        payload["name"] = name
    if folder_id is not None:
        payload["folderId"] = folder_id
    params = {}
    if confirmed is not None:
        params["confirmed"] = confirmed
    resp = await ctx.http.patch(
        f"https://{zone}/api/v2/scenarios/{scenario_id}",
        headers={**_headers(token), "Content-Type": "application/json"},
        json=payload, params=params,
    )
    body = _check_status(resp, "update scenario")
    return body.get("scenario") or {}


async def create_scenario(
    ctx, token: str, zone: str, *, blueprint: dict, team_id: int,
    scheduling: dict | None = None, folder_id: int | None = None,
    description: str = "", confirmed: bool | None = None,
) -> dict:
    payload: dict = {
        "blueprint": _json.dumps(blueprint),
        "teamId": team_id,
        "scheduling": _json.dumps(scheduling or {"type": "indefinitely", "interval": 900}),
    }
    if folder_id is not None:
        payload["folderId"] = folder_id
    if description:
        payload["description"] = description
    params = {}
    if confirmed is not None:
        params["confirmed"] = confirmed
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/scenarios",
        headers={**_headers(token), "Content-Type": "application/json"},
        json=payload, params=params,
    )
    body = _check_status(resp, "create scenario")
    return body.get("scenario") or {}


async def delete_scenario(ctx, token: str, zone: str, scenario_id: int) -> int:
    resp = await ctx.http.delete(
        f"https://{zone}/api/v2/scenarios/{scenario_id}", headers=_headers(token),
    )
    body = _check_status(resp, "delete scenario")
    return body.get("scenario", scenario_id)


async def restore_scenario(ctx, token: str, zone: str, scenario_id: int) -> dict:
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/restore", headers=_headers(token),
    )
    body = _check_status(resp, "restore scenario")
    return body.get("scenario") or {}


async def clone_scenario(
    ctx, token: str, zone: str, scenario_id: int, *, name: str, team_id: int | None = None,
    states: bool = False, confirmed: bool | None = None,
) -> dict:
    payload: dict = {"name": name, "states": states}
    if team_id is not None:
        payload["teamId"] = team_id
    params = {}
    if confirmed is not None:
        params["confirmed"] = confirmed
    resp = await ctx.http.post(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/clone",
        headers={**_headers(token), "Content-Type": "application/json"},
        json=payload, params=params,
    )
    return _check_status(resp, "clone scenario")


async def get_scenario_usage(ctx, token: str, zone: str, scenario_id: int) -> list[dict]:
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/usage", headers=_headers(token),
    )
    body = _check_status(resp, "get scenario usage")
    return body.get("data") or []


async def list_buildtime_variables(ctx, token: str, zone: str, scenario_id: int) -> dict:
    resp = await ctx.http.get(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/build-variables", headers=_headers(token),
    )
    body = _check_status(resp, "list buildtime variables")
    return (body.get("variables") or {}).get("input") or {}


async def set_buildtime_variables(
    ctx, token: str, zone: str, scenario_id: int, variables: list[dict], *, create: bool,
) -> None:
    """POST to add new ones, PUT to update existing ones -- Make treats
    these as two distinct operations, not an upsert."""
    method = ctx.http.post if create else ctx.http.put
    resp = await method(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/build-variables",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"input": variables},
    )
    _check_status(resp, "set buildtime variables")


async def delete_buildtime_variable(ctx, token: str, zone: str, scenario_id: int, name: str) -> None:
    resp = await ctx.http.delete(
        f"https://{zone}/api/v2/scenarios/{scenario_id}/build-variables",
        headers=_headers(token), params={"value": name},
    )
    _check_status(resp, "delete buildtime variable")
