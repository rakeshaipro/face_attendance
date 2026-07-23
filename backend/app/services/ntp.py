"""NTP synchronisation probe (SRS §3.1.10, §3.1.11).

`synchronize(server, timeout)` issues a single NTP request against the
configured server and returns the measured offset + round-trip time. It
is a *measurement only* — it never sets the OS clock. On any failure
(DNS, timeout, refused) it raises `NtpError` with a clear, user-facing
message; the API layer maps that to HTTP 502.

ntplib is imported lazily inside `synchronize` so the module imports
cleanly even on environments without network access (tests mock the
client).
"""
from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import TypedDict


class NtpError(Exception):
    """Raised when the NTP probe fails (DNS, timeout, refused, ...).

    `str(error)` is safe to surface to the operator/API caller.
    """


class NtpResult(TypedDict):
    server_now_utc: str
    ntp_server: str
    offset_seconds: float
    rtt_ms: float
    synchronized: bool


def synchronize(server: str, timeout: float = 2.0) -> NtpResult:
    """Probe `server` once and return the measured offset + RTT.

    Raises `NtpError` on any failure (DNS, timeout, connection refused,
    malformed reply). The caller is expected to map that to a 5xx.
    """
    if not server or not server.strip():
        raise NtpError("No NTP server configured.")

    host = server.strip()
    try:
        # Lazy import keeps the module importable without network deps.
        import ntplib  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover - dependency is pinned
        raise NtpError("ntplib is not installed on the server.") from e

    try:
        client = ntplib.NTPClient()
        stats = client.request(host, version=3, timeout=timeout)
    except socket.gaierror as e:
        raise NtpError(f"DNS resolution failed for '{host}': {e.strerror or e}.") from e
    except socket.timeout as e:
        raise NtpError(f"NTP request to '{host}' timed out after {timeout:.1f}s.") from e
    except (OSError, ConnectionError) as e:
        # Refused / unreachable / reset — OSError is the common base.
        raise NtpError(f"Could not reach NTP server '{host}': {e}.") from e
    except Exception as e:  # ntplib raises bare Exception on bad replies
        raise NtpError(f"NTP probe failed for '{host}': {e}.") from e

    offset = float(stats.offset)
    rtt_ms = float(stats.delay) * 1000.0

    return NtpResult(
        server_now_utc=datetime.now(timezone.utc).isoformat(),
        ntp_server=host,
        offset_seconds=offset,
        rtt_ms=rtt_ms,
        synchronized=True,
    )
