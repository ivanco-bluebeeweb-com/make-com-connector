"""Panel UI -- Срез 1 (connection) only.

SIDEBAR CONTENT -- NO CARDS ANYWHERE, updated 2026-08-20 per
~/UI_INTERFACE_STANDARD.md's "left sidebar, no decorated cards" rule.

Every section (connected status, team picker, scenarios) is a plain
ui.Stack, content stacked vertically and left-aligned, sections separated
by ui.Divider() -- no Card border/background/shadow anywhere in this
slot. Disconnect and the outgoing-webhook config now live in the "App
settings" screen (panels_settings.py) instead of inline in the sidebar --
the sidebar only shows the connected summary line. The one secondary
"App settings" button is always the LAST element at the bottom of the
sidebar.
"""
from __future__ import annotations

from imperal_sdk import ui

from app import ext
import handlers as h
import make_client as mc


def _settings_button() -> ui.UINode:
    """The one required secondary entry point into the settings screen --
    always the last element at the bottom of the sidebar."""
    return ui.Button(
        "App settings", variant="secondary", size="sm", icon="settings", on_click=ui.Call("__panel__make_settings"),
    )


def _connected_section(detail: str) -> ui.UINode:
    """Plain content, no Card wrapper -- disconnect lives in App settings now."""
    return ui.Stack(direction="v", gap=1, align="start", children=[
        ui.Text("Make.com", variant="body"),
        ui.Text(detail, variant="caption"),
    ])


def _connect_section() -> ui.UINode:
    """Plain content, no Card wrapper -- shown only while not connected.
    Stretched full-width per UI_INTERFACE_STANDARD.md (2026-08-20). No
    intro heading/description text here -- that instruction lives ONLY in
    make_connect_help's modal (button below opens it)."""
    return ui.Stack(direction="v", gap=3, align="stretch", children=[
        ui.Button("How do I get a token?", variant="ghost", size="sm",
                  icon="HelpCircle",
                  on_click=ui.Call("__panel__make_connect_help")),
        ui.Button("Authorize Make.com (OAuth 2.0)", variant="primary", size="sm", icon="login"),
        ui.Divider(),
        ui.Text("Or connect via API Token", variant="caption"),
        ui.Form(
            action="connect_make",
            submit_label="Verify and connect",
            children=[
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("API token", variant="caption"),
                    ui.Password(param_name="api_token", placeholder="Make API token"),
                ]),
            ],
        ),
    ])


def _team_picker_section(teams: list[dict]) -> ui.UINode:
    """Plain section, no Card wrapper -- a Divider above separates it
    from whatever came before (the connected status)."""
    if not teams:
        return ui.Stack(direction="v", gap=2, children=[
            ui.Divider(),
            ui.Alert(
                title="No teams found",
                message="Your Make account has no teams to select from yet.",
                type="warning",
            ),
        ])
    return ui.Stack(direction="v", gap=2, children=[
        ui.Divider(),
        ui.Text("Pick a team", variant="heading"),
        ui.Text(
            "Make scopes scenarios by team -- choose which one to show",
            variant="caption",
        ),
        *[
            ui.Button(
                t.get("title", f"Team {t.get('id')}"), variant="secondary", size="sm",
                on_click=ui.Call("select_team", team_id=int(t["id"])),
            )
            for t in teams
        ],
    ])


def _scenario_item(s: dict) -> ui.UINode:
    is_active = bool(s.get("is_active"))
    if s.get("is_invalid"):
        badge = ui.Badge(label="Invalid", color="red")
    elif is_active:
        badge = ui.Badge(label="Active", color="green")
    else:
        badge = ui.Badge(label="Paused", color="gray")
    scenario_id = s.get("scenario_id", 0)
    toggle_action = (
        {
            "icon": "Pause",
            "on_click": ui.Call("set_scenario_active", scenario_id=scenario_id, active=False),
        }
        if is_active
        else {
            "icon": "PlayCircle",
            "on_click": ui.Call("set_scenario_active", scenario_id=scenario_id, active=True),
        }
    )
    return ui.ListItem(
        id=str(scenario_id),
        title=s.get("title", ""),
        badge=badge,
        actions=[
            {
                "icon": "Play",
                "on_click": ui.Call("run_scenario", scenario_id=scenario_id),
                "confirm": (
                    "Run this scenario now? It executes its real actions in "
                    "Make immediately -- there is no dry-run or undo."
                ),
            },
            toggle_action,
        ],
    )


def _scenarios_section(scenarios: list[dict]) -> ui.UINode:
    """Plain section, no Card wrapper. ui.List already renders its own
    ListItems with a divider between rows -- that's the separator asked
    for, not another layer of card padding around the whole list."""
    if not scenarios:
        return ui.Stack(direction="v", gap=2, children=[
            ui.Divider(),
            ui.Alert(
                title="No scenarios yet",
                message="This team has no scenarios, or none matched the current page.",
                type="info",
            ),
        ])
    return ui.Stack(direction="v", gap=2, children=[
        ui.Divider(),
        ui.Text("Your scenarios", variant="heading"),
        ui.List(items=[_scenario_item(s) for s in scenarios]),
    ])


@ext.panel("make_connect", slot="left", title="Make.com", icon="🧩",
           default_width=320, min_width=260, max_width=420)
async def make_connect_panel(ctx, **kwargs) -> object:
    token, zone = await h._get_credentials(ctx)
    connected = bool(token and zone)

    header = ui.Header(text="Make.com", level=2,
                        subtitle="Run and monitor your Make scenarios from Imperal")

    if not connected:
        return ui.Stack(direction="v", gap=4, align="stretch", children=[
            header,
            _connect_section(),
            ui.Divider(),
            _settings_button(),
        ])

    children: list[ui.UINode] = [header, _connected_section(f"Zone: {zone}")]

    team_id = await h._get_team_scope(ctx)
    if not team_id:
        try:
            orgs = await mc.list_organizations(ctx, token, zone)
            raw_teams: list[dict] = []
            for org in orgs:
                org_id = org.get("id")
                if org_id is None:
                    continue
                for t in await mc.list_teams(ctx, token, zone, org_id):
                    raw_teams.append({"id": t.get("id"), "title": t.get("name", "")})
        except mc.ProviderError as exc:
            children.append(ui.Alert(title="Couldn't load teams", message=str(exc), type="danger"))
            raw_teams = []
        children.append(_team_picker_section(raw_teams))
        return ui.Stack(direction="v", gap=4, children=children)

    scenarios: list[dict] = []
    try:
        rows, _pg = await mc.list_scenarios(
            ctx, token, zone, team_id=team_id, organization_id=None, limit=50, offset=0,
        )
        scenarios = [
            {"title": s.get("name", ""), "scenario_id": s.get("id", 0),
             "is_active": bool(s.get("isActive")),
             "is_invalid": bool(s.get("isinvalid"))}
            for s in rows
        ]
    except mc.ProviderError as exc:
        children.append(ui.Alert(title="Couldn't load scenarios", message=str(exc), type="danger"))

    children.append(_scenarios_section(scenarios))
    children.append(ui.Divider())
    children.append(ui.Button("View scenario overview", variant="primary", size="sm", icon="LayoutDashboard", on_click=ui.Call("__panel__make_center")))
    children.append(ui.Divider())
    children.append(_settings_button())
    return ui.Stack(direction="v", gap=4, align="stretch", children=children)


@ext.panel("make_connect_help", slot="center", title="How to get a Make API token",
           center_overlay=True)
async def make_connect_help(ctx, **kwargs) -> object:
    content = ui.Stack(direction="v", gap=3, children=[
        ui.Text("1. Log in to Make.com and open your profile (avatar, bottom-left)."),
        ui.Text("2. Open the API tab."),
        ui.Text("3. Click Add token, name it, and save."),
        ui.Text("4. Copy the token -- Make only shows it once."),
        ui.Divider(),
        ui.Link(
            label="Open Make's official documentation",
            href="https://developers.make.com/api-documentation/authentication/create-authentication-token",
        ),
    ])
    return ui.Dialog(
        title="How to get a Make API token",
        content=content,
        confirm_label="",
        cancel_label="Close",
    )


@ext.panel("make_center", slot="center", title="Make.com", icon="🧩", center_overlay=True)
async def make_center_panel(ctx, **kwargs) -> object:
    """Base center panel -- per UI_INTERFACE_STANDARD.md (2026-08-20).
    This app has no list/detail content of its own to show in the center
    by default (everything lives in the sidebar). MUST carry
    center_overlay=True: per docs.imperal.io/en/concepts/panels, a plain
    slot="center" panel is registered but the Panel app never fetches it
    at session-init without that flag -- the center slot stays genuinely
    empty (not a caching issue) until center_overlay=True is set. Text is
    the shared canonical wording -- must stay identical across every app
    in this situation, not app-specific."""
    from schemas import ListScenariosParams
    token, zone = await h._get_credentials(ctx)
    if not (token and zone):
        return ui.Empty(message="Connect Make.com from the sidebar to see it here.", icon="🧩")

    result = await h.list_scenarios(ctx, ListScenariosParams())
    body: list[ui.UINode] = [ui.Text("Scenario overview", variant="subtitle")]
    if result.success and result.data and result.data.items:
        items = result.data.items
        active = sum(1 for s in items if s.is_active)
        paused = sum(1 for s in items if s.is_paused)
        invalid = sum(1 for s in items if s.is_invalid)
        body.append(ui.Stats(children=[
            ui.Stat(label="Total", value=str(len(items))),
            ui.Stat(label="Active", value=str(active)),
            ui.Stat(label="Paused", value=str(paused)),
            ui.Stat(label="Invalid", value=str(invalid)),
        ]))
        for s in items[:15]:
            color = "red" if s.is_invalid else ("green" if s.is_active else "gray")
            status = "INVALID" if s.is_invalid else ("ACTIVE" if s.is_active else "PAUSED")
            body.append(ui.Stack(direction="h", gap=2, align="center", children=[
                ui.Badge(label=status, color=color),
                ui.Text(s.title, variant="body"),
            ]))
    else:
        body.append(ui.Text("No scenarios found, or no team selected yet.", variant="caption"))

    return ui.Stack(direction="v", gap=3, align="stretch", children=body)