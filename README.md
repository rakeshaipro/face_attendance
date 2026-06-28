# Face Recognition Attendance System

IP-camera-based face recognition attendance system. Replaces biometric punch
machines with a Dahua IP camera + face recognition backend. Per-site instances
each identify themselves by a unique machine ID; an external HRMS consumes
detection events via webhooks and the REST API.

See `backend/README.md` for the FastAPI backend (phase 1: scaffold + `/device`
vertical slice) and `frontend/README.md` for the planned React dashboard.

## Repository layout

```
face_attendance/
├── backend/    FastAPI + SQLAlchemy + InsightFace (Python)
└── frontend/   React + Vite dashboard (planned)
```

## Quick start

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -e ".[dev]"
python -m app.cli gen-encryption-key              # → set FA_ENCRYPTION_KEY in .env
python -m alembic upgrade head
python -m app.cli create-api-key --label Admin --scope admin
uvicorn app.main:app --reload
```

API docs at <http://localhost:8000/docs>, health at <http://localhost:8000/health>.
