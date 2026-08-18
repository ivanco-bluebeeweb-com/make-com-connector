"""Pydantic params models + SDL entity contracts for Make.com Connector.

Scoped to Срез 1 (connection) for now -- scenario list/run/activate
entities land in Срез 2+ per PREPARATION.md's Срез table. All params
models are module-scope (V17 federal invariant).
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from imperal_sdk import sdl


class NoParams(BaseModel):
    """Explicit empty params model -- V17 disallows untyped handlers."""
    pass


class ConnectMakeParams(BaseModel):
    api_token: str = Field(
        "",
        description=(
            "Make.com API token -- create it in Make: avatar (bottom-left) "
            "-> Profile -> API tab -> Add token."
        ),
    )


class ProviderConnection(sdl.Entity):
    id: str = ""
    title: str = ""
    connected: bool = False
    detail: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Срез 2: scenarios (list) -- team/org scope resolution + scenario entities.
# ──────────────────────────────────────────────────────────────────────────


class MakeTeam(sdl.Entity):
    """One team the connected account belongs to. Surfaced so the user can
    pick a team explicitly when their organization has more than one --
    Make's own /scenarios endpoint requires exactly one of team_id/
    organization_id, so an account with multiple teams cannot be defaulted
    silently without risking the wrong team's scenarios being shown."""
    id: str = ""
    title: str = ""
    organization_id: int = 0


class MakeTeamList(sdl.EntityList[MakeTeam]):
    pass


class SelectTeamParams(BaseModel):
    team_id: int = Field(..., description="Make team id to scope scenario listing to (see list_make_teams).")


class ListScenariosParams(BaseModel):
    limit: int = Field(50, ge=1, le=200, description="Max scenarios to return per page.")
    offset: int = Field(0, ge=0, description="Pagination offset.")


class MakeScenario(sdl.Entity):
    id: str = ""
    title: str = ""
    scenario_id: int = 0
    team_id: int = 0
    is_active: bool = False
    is_paused: bool = False
    is_invalid: bool = False
    folder_id: int | None = None
    last_edit: str = ""
    scheduling_type: str = ""


class MakeScenarioList(sdl.EntityList[MakeScenario]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Срез 3: run_scenario -- explicit confirmation, real side effects in Make.
# ──────────────────────────────────────────────────────────────────────────


class RunScenarioParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id to run now (see list_scenarios).")
    confirm: bool = Field(
        False, description="Must be true. Running a scenario executes its real "
                           "actions in Make right now (sending emails, writing to "
                           "connected apps, etc.) -- there is no dry-run or undo.")


class ScenarioRunResult(sdl.Entity):
    id: str = ""
    title: str = ""
    scenario_id: int = 0
    execution_id: str = ""
    status: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Срез 4: activate/deactivate scenario -- reversible toggle, no confirm gate.
# ──────────────────────────────────────────────────────────────────────────


class SetScenarioActiveParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id to activate/deactivate (see list_scenarios).")
    active: bool = Field(
        ..., description="True to activate (schedule/turn on) the scenario, "
                         "False to deactivate (pause) it.")


class ScenarioStateResult(sdl.Entity):
    id: str = ""
    title: str = ""
    scenario_id: int = 0
    is_active: bool = False


# ──────────────────────────────────────────────────────────────────────────
# Срез 5: outgoing webhook Imperal -> Make (a Make "Custom Webhook" trigger
# URL the user pastes here; treated as a bearer-style secret, same tier as
# make_api_token, since anyone holding that URL can fire the scenario).
# ──────────────────────────────────────────────────────────────────────────


class SetOutgoingWebhookParams(BaseModel):
    webhook_url: str = Field(
        "", description="The Custom Webhook trigger URL copied from a Make "
                        "scenario (add a 'Custom Webhook' module, copy its "
                        "URL). Leave empty to remove/disable it.")


class OutgoingWebhookStatus(sdl.Entity):
    configured: bool = False
    detail: str = ""


class SendWebhookEventParams(BaseModel):
    payload: dict = Field(
        default_factory=dict,
        description="JSON-serializable payload to POST to the configured "
                    "Make webhook URL -- shape is whatever the receiving "
                    "Make scenario expects.")


class WebhookDeliveryResult(sdl.Entity):
    delivered: bool = False
    status_code: int = 0
    detail: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Срез 6: scenario blueprint -- read a scenario's actual module list
# (what module N is/does), the gap that prompted this whole expansion.
# ──────────────────────────────────────────────────────────────────────────


class GetScenarioBlueprintParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id (see list_scenarios).")
    draft: bool | None = Field(
        None, description="True for the draft (unsaved editor) version, False "
                          "for the live/published version. Omit to get Make's "
                          "own default for this scenario.")


class BlueprintModule(sdl.Entity):
    """One module (step) in a scenario's blueprint -- position, app/module
    identity, and a short label describing what it is. `position` is
    1-based to match how modules are numbered in the Make editor UI, so
    'module 7' means the 7th entry here.

    `raw_config` is the module's own `mapper` object exactly as Make
    stores it -- for AI modules (OpenAI/Anthropic/Gemini "message
    assistant"/"create completion" etc.) this is where the actual prompt
    text, assistant/model id, and generation params (temperature, etc.)
    live. Exposed verbatim (not reshaped) so nothing is silently dropped
    or misinterpreted -- Make's own field names vary per app/module."""
    id: str = ""
    title: str = ""
    position: int = 0
    module_id: int = 0
    app: str = ""
    module: str = ""
    label: str = ""
    is_router: bool = False
    branch_count: int = 0
    raw_config: dict = Field(default_factory=dict)


class BlueprintModuleList(sdl.EntityList[BlueprintModule]):
    scenario_id: int = 0
    scenario_name: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Срез 7: connections -- what a scenario's modules actually authenticate as.
# ──────────────────────────────────────────────────────────────────────────


class ListConnectionsParams(BaseModel):
    pass


class MakeConnection(sdl.Entity):
    id: str = ""
    title: str = ""
    connection_id: int = 0
    account_type: str = ""
    account_label: str = ""
    expires: str = ""
    editable: bool = True


class MakeConnectionList(sdl.EntityList[MakeConnection]):
    pass


class DeleteConnectionParams(BaseModel):
    connection_id: int = Field(..., description="Connection id (see list_connections).")
    confirm: bool = Field(
        False, description="Must be true. Any scenario using this connection "
                           "will stop working once it's deleted.")


class RenameConnectionParams(BaseModel):
    connection_id: int = Field(..., description="Connection id (see list_connections).")
    name: str = Field(..., description="New display name for the connection.")


class VerifyConnectionParams(BaseModel):
    connection_id: int = Field(..., description="Connection id (see list_connections).")


class ConnectionVerifyResult(sdl.Entity):
    connection_id: int = 0
    verified: bool = False


class DeleteResult(sdl.Entity):
    id: str = ""
    deleted: bool = False


# ──────────────────────────────────────────────────────────────────────────
# Срез 8: data stores -- Make's own key/value storage used by scenarios.
# ──────────────────────────────────────────────────────────────────────────


class ListDataStoresParams(BaseModel):
    pass


class MakeDataStore(sdl.Entity):
    id: str = ""
    title: str = ""
    data_store_id: int = 0
    records: int = 0
    size: int = 0
    max_size: int = 0


class MakeDataStoreList(sdl.EntityList[MakeDataStore]):
    pass


class CreateDataStoreParams(BaseModel):
    name: str = Field(..., description="Name for the new data store.")
    max_size_mb: int = Field(1, ge=1, description="Max size in megabytes.")
    data_structure_id: int | None = Field(
        None, description="Optional data structure id defining the record "
                          "schema. Omit for a schema-less store.")


class DeleteDataStoreParams(BaseModel):
    data_store_id: int = Field(..., description="Data store id (see list_data_stores).")
    confirm: bool = Field(False, description="Must be true. This permanently deletes all its records.")


# ──────────────────────────────────────────────────────────────────────────
# Срез 9: hooks -- Make's incoming webhooks/mailhooks (distinct from Срез 5's
# OUTGOING webhook: these are triggers scenarios listen on).
# ──────────────────────────────────────────────────────────────────────────


class ListHooksParams(BaseModel):
    pass


class MakeHook(sdl.Entity):
    id: str = ""
    title: str = ""
    hook_id: int = 0
    type_name: str = ""
    url: str = ""
    enabled: bool = True
    scenario_id: int | None = None
    queue_count: int = 0


class MakeHookList(sdl.EntityList[MakeHook]):
    pass


class SetHookEnabledParams(BaseModel):
    hook_id: int = Field(..., description="Hook id (see list_hooks).")
    enabled: bool = Field(..., description="True to enable (accept data), False to disable.")


class DeleteHookParams(BaseModel):
    hook_id: int = Field(..., description="Hook id (see list_hooks).")
    confirm: bool = Field(
        False, description="Must be true. Any scenario using this hook will "
                           "stop working once it's deleted.")


# ──────────────────────────────────────────────────────────────────────────
# Срез 10: incomplete executions (DLQ) -- failed scenario runs held for
# manual resolution/retry.
# ──────────────────────────────────────────────────────────────────────────


class ListIncompleteExecutionsParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario id whose incomplete executions to list.")
    status: str | None = Field(
        None, description="Filter by derived status: resolved, scheduled, "
                          "inprogress, or unresolved.")


class IncompleteExecution(sdl.Entity):
    id: str = ""
    title: str = ""
    reason: str = ""
    created: str = ""
    size: int = 0
    resolved: bool = False
    retry: bool = False
    attempts: int = 0


class IncompleteExecutionList(sdl.EntityList[IncompleteExecution]):
    pass


class RetryIncompleteExecutionParams(BaseModel):
    dlq_id: str = Field(..., description="Incomplete execution id (see list_incomplete_executions).")


class DeleteIncompleteExecutionsParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario id whose incomplete executions to delete.")
    dlq_ids: list[str] = Field(
        default_factory=list, description="Explicit incomplete execution ids to "
                                          "delete. Omit and set all=true to delete every one.")
    all: bool = Field(False, description="Delete every incomplete execution of this scenario.")
    confirm: bool = Field(False, description="Must be true when all=true.")


class BulkDeleteResult(sdl.Entity):
    deleted_count: int = 0
    ids: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Срез 11: bulk operations over explicit id lists -- batched versions of
# the single-item write actions above, all requiring 1-100 explicit ids
# (never inferred), same convention as the platform's own bulk tools.
# ──────────────────────────────────────────────────────────────────────────


class BulkSetScenarioActiveParams(BaseModel):
    scenario_ids: list[int] = Field(
        ..., min_length=1, max_length=100,
        description="Explicit Make scenario ids; 1-100, never inferred.")
    active: bool = Field(..., description="True to activate every listed scenario, False to deactivate.")


class BulkScenarioStateResult(sdl.Entity):
    succeeded: list[int] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)


class BulkRunScenariosParams(BaseModel):
    scenario_ids: list[int] = Field(
        ..., min_length=1, max_length=100,
        description="Explicit Make scenario ids; 1-100, never inferred.")
    confirm: bool = Field(
        False, description="Must be true. Runs every listed scenario's real "
                           "actions right now, with no dry-run or undo.")


class BulkRunResult(sdl.Entity):
    succeeded: dict[str, str] = Field(default_factory=dict)
    failed: dict[str, str] = Field(default_factory=dict)


class BulkDeleteConnectionsParams(BaseModel):
    connection_ids: list[int] = Field(
        ..., min_length=1, max_length=100,
        description="Explicit connection ids; 1-100, never inferred.")
    confirm: bool = Field(False, description="Must be true. Scenarios using these connections will stop working.")


class BulkDeleteHooksParams(BaseModel):
    hook_ids: list[int] = Field(
        ..., min_length=1, max_length=100,
        description="Explicit hook ids; 1-100, never inferred.")
    confirm: bool = Field(False, description="Must be true. Scenarios using these hooks will stop working.")
