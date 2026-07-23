"""Schemas for the bulk /api/v1/settings endpoint (SRS §6.4).

These are the contracts the Device and System editors use to read and
write the full set of runtime-configurable settings. Type information
(`type`/`min`/`max`/`choices`) is duplicated from `engine.defaults`
so the frontend can render correct inputs without out-of-band metadata.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SettingType = Literal["str", "int", "float", "bool", "enum"]


class SettingItem(BaseModel):
    """A single runtime setting as returned by GET /api/v1/settings.

    For sensitive keys (`sensitive=true`) the plaintext `value` is
    always empty; `value_set` indicates whether one is stored. The
    caller decides whether to render a "leave blank to keep" input.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str
    value_set: bool = False
    type: SettingType
    group: str
    subsection: str
    label: str
    help: str = ""
    sensitive: bool = False
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[list[str]] = None


class SettingsList(BaseModel):
    items: list[SettingItem]


class SettingUpdate(BaseModel):
    """One write in a PUT /api/v1/settings batch.

    `value` is sent as a string and coerced server-side using the
    declared type. Set `clear=true` to reset the setting to its
    default (only meaningful for sensitive keys — used to wipe a
    saved password).
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str = ""
    clear: bool = False


class SettingsUpdateBody(BaseModel):
    items: list[SettingUpdate] = Field(..., min_length=1, max_length=200)


class SettingUpdateResult(BaseModel):
    key: str
    ok: bool
    error: str = ""


class SettingsUpdateResultList(BaseModel):
    items: list[SettingUpdateResult]
