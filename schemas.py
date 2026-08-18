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
