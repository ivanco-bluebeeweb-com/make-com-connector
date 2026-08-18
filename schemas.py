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


# ──────────────────────────────────────────────────────────────────────────
# Срез 12: full control -- safe blueprint module field editing (the real
# ask behind "what does module N do" was always "and can I change it"),
# plus scenario CRUD, scheduling, buildtime variables, usage.
# ──────────────────────────────────────────────────────────────────────────


class PreviewUpdateBlueprintModuleParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id (see list_scenarios).")
    module_id: int = Field(..., description="The module's own id from get_scenario_blueprint's module_id field (NOT its 1-based position).")
    field: str = Field(..., description="Top-level key inside the module's own settings (raw_config from get_scenario_blueprint) to change -- e.g. 'text' for many AI-app prompt fields. Use the exact key name seen in raw_config.")
    value: str = Field(..., description="New value for that field.")
    draft: bool | None = Field(None, description="True to preview against the draft version. Omit for Make's own default.")


class BlueprintModuleFieldPreview(sdl.Entity):
    scenario_id: int = 0
    module_id: int = 0
    field: str = ""
    current_value: str = ""
    proposed_value: str = ""
    field_exists: bool = False
    expected_state_token: str = ""


class ApplyUpdateBlueprintModuleParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id.")
    module_id: int = Field(..., description="The module's own id (module_id from get_scenario_blueprint).")
    field: str = Field(..., description="Same field name used in preview_update_blueprint_module.")
    value: str = Field(..., description="New value for that field.")
    expected_state_token: str = Field(..., description="Exact token from preview_update_blueprint_module. Execution stops if the scenario's blueprint changed since preview.")
    draft: bool | None = Field(None, description="Must match the draft flag used in preview.")
    confirmed: bool | None = Field(None, description="Set true only if Make reports a first-time-app-in-org confirmation is needed.")


class BlueprintModuleUpdateResult(sdl.Entity):
    scenario_id: int = 0
    module_id: int = 0
    field: str = ""
    new_value: str = ""
    applied: bool = False


class CreateScenarioParams(BaseModel):
    name: str = Field(..., description="Name for the new scenario.")
    team_id: int = Field(..., description="Team to create the scenario in (see list_make_teams/select_team).")
    based_on_template_id: int | None = Field(None, description="Create from an existing Make template id instead of empty, if you have one.")
    description: str = Field("", description="Optional scenario description.")
    folder_id: int | None = Field(None, description="Optional folder id to file the scenario under.")
    confirmed: bool | None = Field(None, description="Set true only if Make reports the scenario uses an app new to this org and needs install confirmation.")


class DeleteScenarioParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario to delete. Make keeps it recoverable in Trash for 30 days (see restore_scenario).")


class RestoreScenarioParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario id to restore from Trash (within Make's 30-day window).")


class CloneScenarioParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario to clone.")
    name: str = Field(..., description="Name for the clone (max 120 characters).")
    team_id: int | None = Field(None, description="Clone into a different team. Omit to clone into the same team.")
    keep_states: bool = Field(False, description="Also clone module run-state (e.g. last trigger position). False resets it in the clone.")
    confirmed: bool | None = Field(None, description="Set true only if Make reports a first-time-app-in-org confirmation is needed.")


class UpdateSchedulingParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario to reschedule.")
    scheduling_type: str = Field(..., description="Make scheduling type: 'indefinitely' (interval-based), 'immediately' (webhook/instant trigger), 'on-demand', 'cron', or 'daily'/'weekly'/'monthly' per Make's own scheduling model.")
    interval: int | None = Field(None, description="Interval in seconds, for 'indefinitely' scheduling.")
    cron: str | None = Field(None, description="Cron expression, for 'cron' scheduling.")


class SchedulingResult(sdl.Entity):
    scenario_id: int = 0
    scheduling_type: str = ""
    interval: int = 0


class ListBuildtimeVariablesParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario whose buildtime (installation-time) variables to read.")


class BuildtimeVariable(sdl.Entity):
    name: str = ""
    value: str = ""


class BuildtimeVariableList(sdl.EntityList[BuildtimeVariable]):
    scenario_id: int = 0


class SetBuildtimeVariableParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario to set the variable on.")
    name: str = Field(..., description="Variable name (as shown by list_buildtime_variables).")
    value: str = Field(..., description="New value.")
    create_new: bool = Field(False, description="True to add a brand-new variable name; false to update an existing one.")


class DeleteBuildtimeVariableParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario to remove the variable from.")
    name: str = Field(..., description="Variable name to delete.")


class GetScenarioUsageParams(BaseModel):
    scenario_id: int = Field(..., description="Scenario whose operations/data-transfer usage to read.")


class UsageDay(sdl.Entity):
    date: str = ""
    operations: int = 0
    data_transfer: int = 0
    centicredits: int = 0


class ScenarioUsageReport(sdl.EntityList[UsageDay]):
    scenario_id: int = 0


# ──────────────────────────────────────────────────────────────────────────
# Срез 15: execution history -- what actually happened on each run.
# ──────────────────────────────────────────────────────────────────────────


class ListScenarioLogsParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id (see list_scenarios).")
    status: str | None = Field(
        None, description="Filter by outcome: 'success', 'warning', or 'error'. Omit for all.")
    limit: int = Field(20, ge=1, le=100, description="Max executions to return, newest first.")


class ScenarioExecutionLog(sdl.Entity):
    id: str = ""
    title: str = ""
    execution_id: str = ""
    status: str = ""
    duration_ms: int = 0
    operations: int = 0
    transfer_bytes: int = 0
    timestamp: str = ""
    author_name: str = ""
    instant: bool = False


class ScenarioExecutionLogList(sdl.EntityList[ScenarioExecutionLog]):
    scenario_id: int = 0


class GetExecutionDetailsParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id.")
    execution_id: str = Field(..., description="Execution id -- the id field from list_scenario_logs.")


class ExecutionDetails(sdl.Entity):
    """Per-run detail -- what a scenario execution actually produced or
    why it failed, including which module/app was the cause."""
    id: str = ""
    title: str = ""
    status: str = ""
    outputs: dict = Field(default_factory=dict)
    error_name: str = ""
    error_message: str = ""
    error_module_name: str = ""
    error_app_name: str = ""


class StopExecutionParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id.")
    execution_id: str = Field(..., description="Execution id to stop -- must currently be running.")
    force: bool = Field(False, description="True to terminate immediately instead of waiting for the current module to finish.")


# ──────────────────────────────────────────────────────────────────────────
# Срез 16: blueprint module add/remove -- the other half of "full control"
# beyond editing an existing module's fields.
# ──────────────────────────────────────────────────────────────────────────


class PreviewAddBlueprintModuleParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id.")
    app_module: str = Field(..., description="Make's own app:module id, e.g. 'openai-gpt-3:messageAssistantAdvanced' or 'builtin:BasicRouter'. Copy this from an existing similar module's `module` field in get_scenario_blueprint.")
    mapper: dict = Field(default_factory=dict, description="The new module's settings (its mapper) -- same shape as raw_config on an existing module of the same app_module.")
    after_module_id: int | None = Field(None, description="Insert immediately after this existing module's id. Omit to append at the end of the main flow.")
    draft: bool | None = Field(None, description="True to preview against the draft version.")


class BlueprintModuleAddPreview(sdl.Entity):
    scenario_id: int = 0
    app_module: str = ""
    position_after: int = 0
    total_modules_before: int = 0
    total_modules_after: int = 0
    expected_state_token: str = ""


class ApplyAddBlueprintModuleParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id.")
    app_module: str = Field(..., description="Same value used in preview_add_blueprint_module.")
    mapper: dict = Field(default_factory=dict, description="Same value used in preview_add_blueprint_module.")
    after_module_id: int | None = Field(None, description="Same value used in preview_add_blueprint_module.")
    expected_state_token: str = Field(..., description="Exact token from preview_add_blueprint_module. Refuses to write if the blueprint changed since preview.")


class BlueprintModuleAddResult(sdl.Entity):
    scenario_id: int = 0
    new_module_id: int = 0
    total_modules: int = 0


class PreviewDeleteBlueprintModuleParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id.")
    module_id: int = Field(..., description="The module's own id (module_id from get_scenario_blueprint) to remove.")
    draft: bool | None = Field(None, description="True to preview against the draft version.")


class BlueprintModuleDeletePreview(sdl.Entity):
    scenario_id: int = 0
    module_id: int = 0
    module_title: str = ""
    total_modules_before: int = 0
    total_modules_after: int = 0
    expected_state_token: str = ""


class ApplyDeleteBlueprintModuleParams(BaseModel):
    scenario_id: int = Field(..., description="Make scenario id.")
    module_id: int = Field(..., description="Same module_id used in preview_delete_blueprint_module.")
    expected_state_token: str = Field(..., description="Exact token from preview_delete_blueprint_module. Refuses to write if the blueprint changed since preview.")


class BlueprintModuleDeleteResult(sdl.Entity):
    scenario_id: int = 0
    deleted_module_id: int = 0
    total_modules: int = 0
