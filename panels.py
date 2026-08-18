"""Panel UI -- Срез 1 (connection) only.

SKETCH (PREPARATION.md section 14), implemented:
  ui.Stack (v, gap=4)
    ui.Header
    ui.Card (connect form OR connected status)
      [not connected] ui.Stack (h) [ ui.Password, ui.Button("How do I get a token?") ]
                       ui.Form(action=connect_make, submit_label="Verify and connect")
      [connected]      ui.Text(detail) + ui.Button("Disconnect")
  -- separate center_overlay dialog, opened by the help button --
  @ext.panel("make_connect_help", slot="center", center_overlay=True)
    ui.Dialog(title=..., content=ui.Stack(v, [ui.Text(step1..4), ui.Divider(), ui.Link(docs)]))

PRE-PANEL CHECKLIST pass:
  - ui.Password: no label=, no type=            OK
  - ui.Card: content=, not children=            OK
  - ui.Dialog on a center_overlay panel, opened via ui.Call("__panel__...")
    (same proven pattern as yt_connect_dialog / wp_ssh_dialog)  OK
  - ui.Form does not submit pre-set value= fields -- token is user-typed,
    not pre-filled, so no hidden-context workaround needed        OK
"""
from __future__ import annotations

from imperal_sdk import ui

from app import ext
import handlers as h


def _connected_card(detail: str) -> ui.UINode:
    return ui.Card(
        title="Make.com",
        subtitle="Connected",
        content=ui.Stack(direction="v", gap=2, children=[
            ui.Text(detail, variant="caption"),
            ui.Button("Disconnect", variant="danger", size="sm",
                      on_click=ui.Call("disconnect_make")),
        ]),
    )


def _connect_card() -> ui.UINode:
    return ui.Card(
        title="Connect Make.com",
        subtitle="Bring your own Make.com account",
        content=ui.Stack(direction="v", gap=3, children=[
            ui.Text(
                "Paste your Make API token below. It's verified against "
                "your account before saving, and your zone (eu1/eu2/us1/"
                "us2) is detected automatically.",
                variant="caption",
            ),
            ui.Stack(direction="h", gap=2, align="center", children=[
                ui.Button("How do I get a token?", variant="ghost", size="sm",
                          icon="HelpCircle",
                          on_click=ui.Call("__panel__make_connect_help")),
            ]),
            ui.Form(
                action="connect_make",
                submit_label="Verify and connect",
                children=[
                    ui.Password(param_name="api_token", placeholder="Make API token"),
                ],
            ),
        ]),
    )


@ext.panel("make_connect", slot="right", title="Make.com", icon="🧩",
           default_width=320, min_width=260, max_width=420)
async def make_connect_panel(ctx, **kwargs) -> object:
    token, zone = await h._get_credentials(ctx)
    connected = bool(token and zone)

    header = ui.Header(text="Make.com", level=2,
                        subtitle="Run and monitor your Make scenarios from Imperal")
    card = _connected_card(f"Zone: {zone}") if connected else _connect_card()

    children: list[ui.UINode] = [header, card]
    if not connected:
        children.append(ui.Alert(
            title="Not connected yet",
            message="Connect your Make.com account to see and run your scenarios.",
            type="info",
        ))

    return ui.Stack(direction="v", gap=4, children=children)


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
