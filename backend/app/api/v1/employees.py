"""Employees group (SRS §3.2).

Endpoints
  GET    /employees            list + search/filter + pagination  §3.2.3, §4.5
  POST   /employees            create                              §3.2.2
  GET    /employees/{id}       view                                §3.2.2
  PUT    /employees/{id}       update                              §3.2.2
  DELETE /employees/{id}       cascade delete                      §3.2.6  (admin)
  POST   /employees/{id}/block                                     §3.2.7
  POST   /employees/{id}/unblock                                   §3.2.8
  GET    /employees/blocked    blocked-employee list               §3.2.9
  POST   /employees/import     bulk CSV import                     §3.2.4
  GET    /employees/export     CSV export                          §3.2.5

All write endpoints record an audit entry (§3.9.5).
"""
from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_readwrite, require_readonly
from app.db import get_db
from app.models import ApiKey, Employee, FaceEmbedding
from app.schemas.common import Envelope, PaginatedData
from app.schemas.employee import (
    BlockedEmployeeOut,
    BulkImportResult,
    BulkImportRow,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/employees", tags=["employees"])


def _get_employee_or_404(db: Session, employee_id: str) -> Employee:
    row = db.execute(select(Employee).where(Employee.id == employee_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return row


# --- §3.2.3 list ---------------------------------------------------------
@router.get("", response_model=Envelope[PaginatedData[EmployeeOut]])
def list_employees(
    q: str | None = None,
    enrolled: bool | None = None,
    blocked: bool | None = None,
    active: bool | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[PaginatedData[EmployeeOut]]:
    stmt = select(Employee)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(Employee.name.ilike(pattern), Employee.employee_id.ilike(pattern))
        )
    if enrolled is not None:
        stmt = stmt.where(Employee.is_enrolled.is_(enrolled))
    if blocked is not None:
        stmt = stmt.where(Employee.is_blocked.is_(blocked))
    if active is not None:
        stmt = stmt.where(Employee.is_active.is_(active))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(stmt.order_by(Employee.created_at.desc()).offset((page - 1) * limit).limit(limit))
        .scalars()
        .all()
    )
    return Envelope(
        data=PaginatedData[EmployeeOut](
            items=[EmployeeOut.model_validate(r) for r in rows],
            total=int(total),
            page=page,
            limit=limit,
        )
    )


# --- §3.2.9 blocked list -------------------------------------------------
@router.get("/blocked", response_model=Envelope[list[BlockedEmployeeOut]])
def blocked_employees(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[list[BlockedEmployeeOut]]:
    rows = (
        db.execute(
            select(Employee)
            .where(Employee.is_blocked.is_(True))
            .order_by(Employee.name.asc())
        )
        .scalars()
        .all()
    )
    return Envelope(data=[BlockedEmployeeOut(id=r.id, employee_id=r.employee_id, name=r.name, is_blocked=True) for r in rows])


# --- §3.2.4 CSV import ---------------------------------------------------
@router.post("/import", response_model=Envelope[BulkImportResult])
def import_employees(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[BulkImportResult]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file.")
    raw = file.file.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    result_rows: list[BulkImportRow] = []
    succeeded = failed = 0
    expected = {"employee_id", "name"}

    for idx, row in enumerate(reader, start=2):  # row 1 is the header
        eid = (row.get("employee_id") or "").strip()
        name = (row.get("name") or "").strip()
        missing = expected - {k.strip() for k in row.keys() if k}
        if not eid or not name:
            failed += 1
            result_rows.append(BulkImportRow(row=idx, employee_id=eid or "<missing>", status="error", error="Missing employee_id or name."))
            continue
        emp = Employee(
            id=uuid.uuid4().hex,
            employee_id=eid,
            name=name,
            phone=(row.get("phone") or "").strip() or None,
            email=(row.get("email") or "").strip() or None,
            is_active=_bool((row.get("is_active") or "true").strip()),
        )
        try:
            db.add(emp)
            db.flush()
            write_audit(
                db, action="employee.create", affected_id=emp.id, source="api",
                actor=api_key.label, new_value={"employee_id": eid, "name": name}, commit=False,
            )
            db.commit()
            succeeded += 1
            result_rows.append(BulkImportRow(row=idx, employee_id=eid, status="ok"))
        except IntegrityError:
            db.rollback()
            failed += 1
            result_rows.append(BulkImportRow(row=idx, employee_id=eid, status="error", error="Duplicate employee_id."))
        except Exception as exc:  # pragma: no cover - defensive
            db.rollback()
            failed += 1
            result_rows.append(BulkImportRow(row=idx, employee_id=eid, status="error", error=str(exc)))

    total = succeeded + failed
    return Envelope(data=BulkImportResult(total=total, succeeded=succeeded, failed=failed, rows=result_rows))


# --- §3.2.5 CSV export ---------------------------------------------------
@router.get("/export")
def export_employees(
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
):
    rows = db.execute(select(Employee).order_by(Employee.name.asc())).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["employee_id", "name", "phone", "email", "is_active", "is_blocked", "is_enrolled"]
    )
    for r in rows:
        writer.writerow(
            [r.employee_id, r.name, r.phone or "", r.email or "", int(r.is_active), int(r.is_blocked), int(r.is_enrolled)]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=employees.csv"},
    )


# --- §3.2.2 create -------------------------------------------------------
@router.post("", response_model=Envelope[EmployeeOut], status_code=status.HTTP_201_CREATED)
def create_employee(
    body: EmployeeCreate,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[EmployeeOut]:
    emp = Employee(id=uuid.uuid4().hex, **body.model_dump())
    db.add(emp)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="employee_id already exists.")
    write_audit(
        db, action="employee.create", affected_id=emp.id, source="api",
        actor=api_key.label, new_value=body.model_dump(), commit=True,
    )
    return Envelope(data=EmployeeOut.model_validate(emp))


# --- §3.2.2 read ---------------------------------------------------------
@router.get("/{employee_id}", response_model=Envelope[EmployeeOut])
def get_employee(
    employee_id: str,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(require_readonly),
) -> Envelope[EmployeeOut]:
    # Accept either the internal id or the organisation employee_id.
    emp = db.execute(
        select(Employee).where(or_(Employee.id == employee_id, Employee.employee_id == employee_id))
    ).scalar_one_or_none()
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return Envelope(data=EmployeeOut.model_validate(emp))


# --- §3.2.2 update -------------------------------------------------------
@router.put("/{employee_id}", response_model=Envelope[EmployeeOut])
def update_employee(
    employee_id: str,
    body: EmployeeUpdate,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[EmployeeOut]:
    emp = _get_employee_or_404(db, employee_id)
    updates = body.model_dump(exclude_unset=True)
    old = {k: getattr(emp, k) for k in updates}
    for k, v in updates.items():
        setattr(emp, k, v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="employee_id already exists.")
    write_audit(
        db, action="employee.update", affected_id=emp.id, source="api",
        actor=api_key.label, old_value=old, new_value=updates, commit=True,
    )
    return Envelope(data=EmployeeOut.model_validate(emp))


# --- §3.2.6 cascade delete (admin) --------------------------------------
@router.delete("/{employee_id}", response_model=Envelope[dict])
def delete_employee(
    employee_id: str,
    reason: str = Query(..., description="Mandatory reason (audit)."),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_admin),
) -> Envelope[dict]:
    emp = _get_employee_or_404(db, employee_id)
    snapshot = {"id": emp.id, "employee_id": emp.employee_id, "name": emp.name}
    # ONDELETE CASCADE on FKs removes embeddings + attendance logs.
    db.delete(emp)
    write_audit(
        db, action="employee.delete", affected_id=emp.id, source="api",
        actor=api_key.label, old_value=snapshot, note=reason, commit=True,
    )
    return Envelope(data={"deleted": emp.id})


# --- §3.2.7 / §3.2.8 block + unblock ------------------------------------
@router.post("/{employee_id}/block", response_model=Envelope[EmployeeOut])
def block_employee(
    employee_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[EmployeeOut]:
    emp = _get_employee_or_404(db, employee_id)
    old = emp.is_blocked
    emp.is_blocked = True
    write_audit(
        db, action="employee.block", affected_id=emp.id, source="api",
        actor=api_key.label, old_value=old, new_value=True, commit=True,
    )
    return Envelope(data=EmployeeOut.model_validate(emp))


@router.post("/{employee_id}/unblock", response_model=Envelope[EmployeeOut])
def unblock_employee(
    employee_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_readwrite),
) -> Envelope[EmployeeOut]:
    emp = _get_employee_or_404(db, employee_id)
    old = emp.is_blocked
    emp.is_blocked = False
    write_audit(
        db, action="employee.unblock", affected_id=emp.id, source="api",
        actor=api_key.label, old_value=old, new_value=False, commit=True,
    )
    return Envelope(data=EmployeeOut.model_validate(emp))


# --- helpers -------------------------------------------------------------
def _bool(s: str) -> bool:
    return s.lower() in {"1", "true", "yes", "y", "on"}
