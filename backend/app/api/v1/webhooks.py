"""Webhooks group (SRS §3.6).

Endpoints
  GET    /webhooks                       list subscriptions
  POST   /webhooks                       create subscription        §3.6.1/3.6.2
  GET    /webhooks/{id}                  view
  PUT    /webhooks/{id}                  update
  DELETE /webhooks/{id}                  delete                     (admin)
  POST   /webhooks/{id}/test             synthetic test delivery    §3.6.13
  GET    /webhooks/{id}/deliveries       delivery log               §3.6.11
  POST   /webhooks/deliveries/{id}/retry manual retry               §3.6.12
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_readonly, require_readwrite
from app.core.crypto import decrypt, encrypt
from app.db import get_db
from app.models import ApiKey, Webhook, WebhookDelivery
from app.schemas.common import Envelope, PaginatedData
from app.schemas.webhook import (
    DeliveryOut,
    TestResult,
    WebhookCreate,
    WebhookOut,
    WebhookUpdate,
)
from app.services.audit import write_audit
from app.services.webhook_queue import dispatcher

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _to_out(row: Webhook) -> WebhookOut:
    return WebhookOut(
        id=row.id,
        target_url=row.target_url,
        events=row.events.split(",") if row.events else [],
        custom_headers=json.loads(row.custom_headers_json) if row.custom_headers_json else None,
        is_enabled=row.is_enabled,
        max_retries=row.max_retries,
        timeout_ms=row.timeout_ms,
        has_secret=bool(row.secret_encrypted),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _get_or_404(db: Session, wid: str) -> Webhook:
    row = db.get(Webhook, wid)
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    return row


# --- list / create ------------------------------------------------------
@router.get("", response_model=Envelope[list[WebhookOut]])
def list_webhooks(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[list[WebhookOut]]:
    rows = db.execute(select(Webhook).order_by(Webhook.created_at.desc())).scalars().all()
    return Envelope(data=[_to_out(r) for r in rows])


@router.post("", response_model=Envelope[WebhookOut], status_code=201)
def create_webhook(
    body: WebhookCreate,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[WebhookOut]:
    row = Webhook(
        id=uuid.uuid4().hex,
        target_url=body.target_url,
        events=",".join(body.events),
        secret_encrypted=encrypt(body.secret) if body.secret else None,
        custom_headers_json=json.dumps(body.custom_headers) if body.custom_headers else None,
        is_enabled=body.is_enabled,
        max_retries=body.max_retries,
        timeout_ms=body.timeout_ms,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db, action="webhook.create", affected_id=row.id, source="api",
        actor=api_key.label, new_value={"target_url": row.target_url, "events": body.events}, commit=True,
    )
    return Envelope(data=_to_out(row))


# --- read / update / delete --------------------------------------------
@router.get("/{wid}", response_model=Envelope[WebhookOut])
def get_webhook(
    wid: str,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[WebhookOut]:
    return Envelope(data=_to_out(_get_or_404(db, wid)))


@router.put("/{wid}", response_model=Envelope[WebhookOut])
def update_webhook(
    wid: str,
    body: WebhookUpdate,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[WebhookOut]:
    row = _get_or_404(db, wid)
    updates = body.model_dump(exclude_unset=True)
    if "target_url" in updates:
        row.target_url = updates["target_url"]
    if "events" in updates and updates["events"] is not None:
        row.events = ",".join(updates["events"])
    if "secret" in updates:
        row.secret_encrypted = encrypt(updates["secret"]) if updates["secret"] else None
    if "custom_headers" in updates:
        row.custom_headers_json = json.dumps(updates["custom_headers"]) if updates["custom_headers"] else None
    if "is_enabled" in updates:
        row.is_enabled = updates["is_enabled"]
    if "max_retries" in updates:
        row.max_retries = updates["max_retries"]
    if "timeout_ms" in updates:
        row.timeout_ms = updates["timeout_ms"]
    db.commit()
    db.refresh(row)
    write_audit(
        db, action="webhook.update", affected_id=row.id, source="api",
        actor=api_key.label, new_value=updates, commit=True,
    )
    return Envelope(data=_to_out(row))


@router.delete("/{wid}", response_model=Envelope[dict])
def delete_webhook(
    wid: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[dict]:
    row = _get_or_404(db, wid)
    db.delete(row)
    write_audit(
        db, action="webhook.delete", affected_id=wid, source="api",
        actor=api_key.label, old_value={"target_url": row.target_url}, commit=True,
    )
    return Envelope(data={"deleted": wid})


# --- test delivery (§3.6.13) -------------------------------------------
@router.post("/{wid}/test", response_model=Envelope[TestResult])
async def test_webhook(
    wid: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[TestResult]:
    """Synchronous synthetic test: build payload, sign, send, return result."""
    from app.services.webhooks import build_payload, headers_for, send_one

    row = _get_or_404(db, wid)
    secret = decrypt(row.secret_encrypted) if row.secret_encrypted else None
    extra = json.loads(row.custom_headers_json) if row.custom_headers_json else None
    raw, _eid = build_payload(
        "employee.detected",
        {"log_id": None, "employee_id": "TEST", "name": "Test delivery", "confidence": 0.0, "snapshot_url": None},
        {"id": "test", "name": "test", "timezone": "UTC"},
        event_id=uuid.uuid4().hex,
    )
    headers = headers_for(row.id, "employee.detected", uuid.uuid4().hex, raw, secret, extra)
    result = await send_one(row.target_url, raw, headers, timeout_ms=row.timeout_ms)
    # Record the synthetic attempt for traceability.
    db.add(
        WebhookDelivery(
            id=uuid.uuid4().hex,
            webhook_id=row.id,
            attendance_log_id=None,
            event_type="employee.detected",
            delivery_id=uuid.uuid4().hex,
            attempt=0,
            status_code=result.status_code,
            response_body=result.response_body,
            latency_ms=result.latency_ms,
            error=result.error,
            outcome="ok" if result.ok else "failed",
        )
    )
    db.commit()
    write_audit(
        db, action="webhook.test", affected_id=row.id, source="api",
        actor=api_key.label, new_value={"ok": result.ok}, commit=True,
    )
    return Envelope(
        data=TestResult(
            ok=result.ok,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            error=result.error,
        )
    )


# --- delivery log (§3.6.11) --------------------------------------------
@router.get("/{wid}/deliveries", response_model=Envelope[PaginatedData[DeliveryOut]])
def deliveries(
    wid: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[PaginatedData[DeliveryOut]]:
    from sqlalchemy import func

    _get_or_404(db, wid)
    stmt = select(WebhookDelivery).where(WebhookDelivery.webhook_id == wid)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(WebhookDelivery.created_at.desc()).offset((page - 1) * limit).limit(limit)
        )
        .scalars()
        .all()
    )
    return Envelope(
        data=PaginatedData[DeliveryOut](
            items=[DeliveryOut.model_validate(r) for r in rows],
            total=int(total),
            page=page,
            limit=limit,
        )
    )


# --- manual retry (§3.6.12) --------------------------------------------
@router.post("/deliveries/{delivery_db_id}/retry", response_model=Envelope[dict])
async def retry_delivery(
    delivery_db_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[dict]:
    row = db.get(WebhookDelivery, delivery_db_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    ok = await dispatcher.enqueue_retry(row.webhook_id, row.delivery_id)
    write_audit(
        db, action="webhook.retry", affected_id=delivery_db_id, source="api",
        actor=api_key.label, new_value={"queued": ok}, commit=True,
    )
    return Envelope(data={"queued": ok})
