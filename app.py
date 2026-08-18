"""Extension declaration, secrets, lifecycle hooks.

WHY BYOK (bring-your-own-key), same reasoning as DataForSEO Connector /
Media Hub's Magnific integration. Make.com is a paid third-party platform
the USER has their own account, scenarios and quota with -- not something
Imperal can broker centrally. The user pastes their own Make API token
once, Vault-encrypted via `ctx.secrets`, and every call runs against their
own Make account.

WHY TWO SECRETS (token + zone), NOT JUST ONE.

Make's API base URL is zone-specific (eu1.make.com, eu2, us1, us2, and
on-prem variants like eu1.make.celonis.com) -- per Make's own API
structure doc, calling the wrong zone's host fails outright, there is no
single global endpoint. A token is only valid against the zone that
issued it. Rather than ask a first-time user to go find and paste their
own zone hostname (most people have never looked at where in the URL bar
it says eu1./us1.), `connect_make` auto-discovers the zone by probing the
known zone hosts with GET /users/me until one accepts the token, then
saves the WINNING zone alongside the token so every later call goes
straight to the right host with zero guessing.

WHY `write_mode="both"`, SAME REASONING AS DATAFORSEO CONNECTOR.

Declaring `write_mode="user"` would mean only the platform's generic
Secrets screen could write these -- leaving a first-time user with no
in-app screen explaining what a Make API token even is or whether what
they pasted actually works. `write_mode="both"` keeps the platform
Secrets screen working AND lets this extension's own `connect_make`
validate the token against Make's API *before* writing it, so a bad
paste is rejected immediately with a clear reason.
"""

from imperal_sdk import Extension, ChatExtension

ext = Extension(
    "make-com-connector",
    version="0.1.0",
    display_name="Make.com",
    description=(
        "Connect your own Make.com account to see and run your automation "
        "scenarios from Imperal -- list scenarios with their status "
        "(active/paused/invalid), run one on demand, activate/deactivate "
        "them, and send outgoing webhook events from Imperal into a Make "
        "scenario. Your Make API token is verified before it's saved, and "
        "the connector auto-detects which Make zone (eu1/eu2/us1/us2) your "
        "account lives in -- no need to know that yourself."
    ),
    icon="icon.svg",
    actions_explicit=True,
    capabilities=["make:read", "make:write"],
)

chat = ChatExtension(
    ext,
    tool_name="make-com-connector",
    description="View and run your Make.com scenarios, and send outgoing webhooks to Make",
)

ext.secret(
    name="make_api_token",
    description=(
        "Make.com API token -- create it in Make: click your avatar "
        "(bottom-left) -> Profile -> API tab -> Add token. Verified "
        "against your Make account before saving."
    ),
    write_mode="both",
)
ext.secret(
    name="make_zone",
    description=(
        "Make.com zone host (e.g. eu1.make.com) auto-detected when you "
        "connect -- not something you need to enter yourself."
    ),
    write_mode="both",
)


@ext.health_check
async def health_check(ctx) -> bool:
    """Basic liveness check -- confirms the store surface is reachable."""
    await ctx.store.query("make_app_settings", limit=1)
    return True
