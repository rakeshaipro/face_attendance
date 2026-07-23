"""Schemas for the /api/v1/time group (SRS §3.1.10, §3.1.11).

The backend is the time source: it reports its own UTC clock plus the
configured IANA timezone and NTP server, accepts edits to those two
settings, and runs an on-demand NTP probe that reports the measured
offset and round-trip time against the configured server.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TimeInfo(BaseModel):
    """Current server clock + configured timezone/NTP server (GET /time)."""

    model_config = ConfigDict(extra="forbid")

    server_now_utc: str
    timezone: str
    ntp_server: str
    uptime_seconds: float


class TimeUpdate(BaseModel):
    """Editable subset of the time settings (PUT /time body)."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(..., min_length=1, description="IANA timezone, e.g. UTC, Asia/Kolkata.")
    ntp_server: str = Field(..., min_length=1, description="NTP server hostname or IPv4 address.")


class NtpResult(BaseModel):
    """Outcome of a single NTP synchronisation probe (POST /time/ntp-sync)."""

    model_config = ConfigDict(extra="forbid")

    server_now_utc: str
    ntp_server: str
    offset_seconds: float
    rtt_ms: float
    synchronized: bool
