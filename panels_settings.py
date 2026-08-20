"""The single 'App settings' screen (center slot) -- everything configurable
for Make.com Connector: connection (connect/disconnect) and the outgoing
webhook URL. Split out of panels.py per the same convention as Aidentika's
panels_settings.py.

Per ~/UI_INTERFACE_STANDARD.md (updated 2026-08-20): the left sidebar no
longer wraps connection status in a Card, and outgoing-webhook config
(previously inline in the sidebar) now lives here too -- "весь функционал
настраиваемого... — всё в одном месте", not scattered across sidebar
sections. The one secondary "App settings" button sits LAST at the bottom
of the sidebar.
"""
from __future__ import annotations

from imperal_sdk import ui

from app import ext
import handlers as h


def _connection_section(zone: str, connected: bool) -> ui.UINode:
    if not connected:
        return ui.Stack(direction="v", gap=2, align="stretch", children=[
            ui.Text("Connection", variant="heading"),
            ui.Text(
                "Paste your Make API token below. It's verified against "
                "your account before saving, and your zone (eu1/eu2/us1/"
                "us2) is detected automatically.",
                variant="caption",
            ),
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
    return ui.Stack(direction="v", gap=2, children=[
        ui.Text("Connection", variant="heading"),
        ui.Text(f"Connected -- zone: {zone}", variant="caption"),
        ui.Button("Disconnect", variant="danger", size="sm",
                  on_click=ui.Call("disconnect_make")),
    ])


def _webhook_section(configured: bool) -> ui.UINode:
    """Outgoing Make Custom Webhook trigger URL -- other Imperal apps fire
    a Make scenario via send_webhook_event against this saved URL."""
    if configured:
        return ui.Stack(direction="v", gap=2, children=[
            ui.Text("Outgoing webhook", variant="heading"),
            ui.Badge(label="Configured", color="green"),
            ui.Button(
                "Clear webhook", variant="secondary", size="sm",
                on_click=ui.Call("set_outgoing_webhook", webhook_url=""),
            ),
        ])
    return ui.Stack(direction="v", gap=2, align="stretch", children=[
        ui.Text("Outgoing webhook", variant="heading"),
        ui.Text("Send events from Imperal to a Make scenario.", variant="caption"),
        ui.Form(
            children=[
                ui.Stack(direction="v", gap=1, children=[
                    ui.Text("Webhook URL", variant="caption"),
                    ui.Input(
                        placeholder="Paste a Make Custom Webhook URL...",
                        param_name="webhook_url",
                    ),
                ]),
            ],
            submit_label="Save webhook",
            action="set_outgoing_webhook",
        ),
    ])


@ext.panel("make_settings", slot="center", title="App settings", icon="⚙️",
           center_overlay=True)
async def make_settings_panel(ctx, **kwargs) -> object:
    token, zone = await h._get_credentials(ctx)
    connected = bool(token and zone)
    webhook_configured = bool(await ctx.secrets.get("make_webhook_url"))

    content = ui.Stack(direction="v", gap=4, align="stretch", children=[
        _connection_section(zone or "", connected),
        ui.Divider(),
        _webhook_section(webhook_configured),
    ])
    return ui.Dialog(
        title="App settings",
        content=content,
        confirm_label="",
        cancel_label="Close",
    )
