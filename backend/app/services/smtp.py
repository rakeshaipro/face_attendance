"""SMTP email alert service (SRS §3.11.4).

Sends plain-text alerts via an external SMTP server. Credentials and
recipients are read from the settings store. The service is intentionally
synchronous — it runs inside APScheduler background jobs, not on the async
event loop.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from sqlalchemy.orm import Session

from app.core.settings_store import get_bool, get_int, get_value
from app.services.system_log import write_system_log

logger = logging.getLogger(__name__)


def _parse_recipients(raw: str) -> list[str]:
    return [r.strip() for r in (raw or "").split(",") if r.strip()]


def send_alert(
    db: Session,
    *,
    subject: str,
    body: str,
    context: dict[str, Any] | None = None,
) -> bool:
    """Send an SMTP alert if SMTP is enabled and configured.

    Returns True if the message was accepted by the server (or would have been
    sent but no recipients were configured — caller decides if that's a failure).
    Logs errors to the system log.
    """
    if not get_bool(db, "smtp.enabled"):
        return False

    host = (get_value(db, "smtp.host") or "").strip()
    port = get_int(db, "smtp.port") or 587
    username = (get_value(db, "smtp.username") or "").strip()
    password = get_value(db, "smtp.password_encrypted") or ""
    from_addr = (get_value(db, "smtp.from_addr") or "").strip()
    recipients = _parse_recipients(get_value(db, "smtp.recipients"))

    if not host or not from_addr or not recipients:
        logger.warning("SMTP enabled but host/from/recipients missing")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if username:
                server.starttls()
                server.login(username, password)
            server.send_message(msg)
        write_system_log(
            db,
            event="smtp.sent",
            message=f"Sent SMTP alert: {subject}",
            context=context,
        )
        return True
    except Exception as exc:
        logger.exception("SMTP alert failed: %s", subject)
        write_system_log(
            db,
            severity="error",
            event="smtp.failed",
            message=f"SMTP alert failed: {subject} — {exc}",
            context=context,
        )
        return False


def send_camera_offline_alert(db: Session, offline_minutes: int) -> bool:
    """Send the camera-offline email alert."""
    machine_id = get_value(db, "device.machine_id")
    location = get_value(db, "device.location_name")
    subject = f"[{machine_id}] Camera offline for {offline_minutes} minutes"
    body = (
        f"Camera on {machine_id} ({location}) has been offline for "
        f"{offline_minutes} minutes.\n\n"
        "Please check the device and network connectivity."
    )
    return send_alert(db, subject=subject, body=body, context={"machine_id": machine_id, "offline_minutes": offline_minutes})


def send_storage_low_alert(db: Session, free_mb: float, threshold_mb: int) -> bool:
    """Send the storage-low email alert."""
    machine_id = get_value(db, "device.machine_id")
    location = get_value(db, "device.location_name")
    subject = f"[{machine_id}] Storage low: {free_mb:.1f} MB free"
    body = (
        f"Free disk space on {machine_id} ({location}) is {free_mb:.1f} MB, "
        f"below the configured threshold of {threshold_mb} MB.\n\n"
        "Consider freeing disk space or adjusting retention settings."
    )
    return send_alert(
        db,
        subject=subject,
        body=body,
        context={"machine_id": machine_id, "free_mb": round(free_mb, 2), "threshold_mb": threshold_mb},
    )
