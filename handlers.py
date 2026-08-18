"""Chat functions for Make.com Connector -- Срез 1 (connection) only.

Scenario list/run/activate land in Срез 2+ per PREPARATION.md's Срез
table -- this file intentionally stops at connect/disconnect/status so
each slice stays live-verifiable on its own before the next is built.
"""
from __future__ import annotations

from imperal_sdk import ActionResult

import make_client as mc
from app import ext, chat
from schemas import NoParams, ConnectMakeParams, ProviderConnection


async def _get_credentials(ctx) -> tuple[str, str]:
    """Returns (api_token, zone). Both empty means "not connected"."""
    token = await ctx.secrets.get("make_api_token")
    zone = await ctx.secrets.get("make_zone")
    return token or "", zone or ""


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
