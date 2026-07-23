"""Time group (SRS §3.1.10, §3.1.11).

The backend is the authoritative time source. It reports its own UTC
clock plus the configured IANA timezone and NTP server, accepts edits
to those two settings, and runs an on-demand NTP probe that reports
the measured offset + RTT against the configured server. The probe is
*measurement only* — it never sets the OS clock (SRS §3.1.11 frames
NTP as guidance for the operator).

Endpoints
  GET  /time           server clock + configured tz/NTP server   (readonly)
  PUT  /time           update timezone + NTP server              (admin)
  POST /time/ntp-sync  probe the configured NTP server           (admin)
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_readonly
from app.core.enums import LogSeverity
from app.core.settings_store import get_value, set_value
from app.db import get_db
from app.models import ApiKey
from app.schemas.common import Envelope
from app.schemas.time import NtpResult as NtpResultSchema, TimeInfo, TimeUpdate
from app.services.audit import write_audit
from app.services.ntp import NtpError, synchronize as ntp_synchronize
from app.services.system_log import write_system_log

router = APIRouter(prefix="/time", tags=["time"])

# Captured at import time, the same way device.py / health.py do it.
_START_TIME = time.monotonic()

# NTP server must be a valid hostname (RFC 1123) or an IPv4 address.
# Hostname: dot-separated labels, each ≤63 chars, alphanumeric + hyphen,
# not anchored by a hyphen; total length ≤ 253.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME_RE = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*$")
_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_NTP_MAX_LEN = 253

_TIMEZONE_KEY = "device.timezone"
_NTP_KEY = "device.ntp_server"


def _uptime() -> float:
    return round(time.monotonic() - _START_TIME, 2)


def _validate_ntp_server(raw: str) -> tuple[bool, str]:
    value = raw.strip()
    if not value:
        return False, "NTP server must not be empty."
    if len(value) > _NTP_MAX_LEN:
        return False, f"NTP server must be ≤ {_NTP_MAX_LEN} characters."
    if _IPV4_RE.match(value):
        for octet in value.split("."):
            if int(octet) > 255:
                return False, "Invalid IPv4 address (octet > 255)."
        return True, ""
    if _HOSTNAME_RE.match(value):
        return True, ""
    return False, "NTP server must be a valid hostname or IPv4 address."


@router.get("", response_model=Envelope[TimeInfo])
def get_time(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[TimeInfo]:
    """Return the server's UTC clock plus the configured timezone/NTP server."""
    return Envelope(
        data=TimeInfo(
            server_now_utc=datetime.now(timezone.utc).isoformat(),
            timezone=get_value(db, _TIMEZONE_KEY),
            ntp_server=get_value(db, _NTP_KEY),
            uptime_seconds=_uptime(),
        )
    )


@router.put("", response_model=Envelope[TimeInfo])
def update_time(
    body: TimeUpdate,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[TimeInfo]:
    """Validate and save timezone + NTP server. Writes an audit entry."""
    tz = body.timezone.strip()
    try:
        # ZoneInfo is the stdlib Intl-equivalent: it rejects unknown zones.
        ZoneInfo(tz)
    except ZoneInfoNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Unknown timezone '{tz}'.") from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid timezone '{tz}': {e}.") from e

    ntp_server = body.ntp_server.strip()
    ok, err = _validate_ntp_server(ntp_server)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    old_tz = get_value(db, _TIMEZONE_KEY)
    old_ntp = get_value(db, _NTP_KEY)
    set_value(db, _TIMEZONE_KEY, tz)
    set_value(db, _NTP_KEY, ntp_server)

    write_audit(
        db,
        action="time.update",
        source="api",
        actor=api_key.label,
        old_value={"timezone": old_tz, "ntp_server": old_ntp},
        new_value={"timezone": tz, "ntp_server": ntp_server},
        commit=True,
    )
    write_system_log(
        db,
        event="time.update",
        message=f"Time settings updated: timezone={tz}, ntp_server={ntp_server}",
    )

    return Envelope(
        data=TimeInfo(
            server_now_utc=datetime.now(timezone.utc).isoformat(),
            timezone=tz,
            ntp_server=ntp_server,
            uptime_seconds=_uptime(),
        )
    )


@router.post("/ntp-sync", response_model=Envelope[NtpResultSchema])
def ntp_sync(
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[NtpResultSchema]:
    """Probe the configured NTP server and report offset + RTT.

    On failure raises 502 with a clear error message (DNS, timeout, refused).
    Writes a system-log entry recording success or failure.
    """
    server = get_value(db, _NTP_KEY)
    try:
        result = ntp_synchronize(server)
    except NtpError as e:
        write_system_log(
            db,
            severity=LogSeverity.WARNING,
            event="time.ntp_sync_failed",
            message=f"NTP sync to '{server}' failed: {e}",
            context={"ntp_server": server, "actor": api_key.label},
        )
        # FastAPI's HTTPException handler normalises detail into the envelope.
        raise HTTPException(status_code=502, detail=str(e)) from e

    write_system_log(
        db,
        event="time.ntp_sync_ok",
        message=(
            f"NTP sync to '{result['ntp_server']}': "
            f"offset={result['offset_seconds']:+.3f}s, rtt={result['rtt_ms']:.1f}ms"
        ),
        context={
            "ntp_server": result["ntp_server"],
            "offset_seconds": result["offset_seconds"],
            "rtt_ms": result["rtt_ms"],
            "actor": api_key.label,
        },
    )
    return Envelope(data=NtpResultSchema(**result))
