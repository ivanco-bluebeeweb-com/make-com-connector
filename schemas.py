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
