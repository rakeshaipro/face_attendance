# Face Recognition Attendance System — Backend

FastAPI backend for the IP-camera-based face attendance system described in the SRS.
This is **phase 1**: project scaffold + the `/device` and `/health` endpoint groups
implemented end-to-end. All other route groups exist as stubs returning `501`.

## Tech stack

| Layer | Choice |
|---|---|
| Web framework | FastAPI + Uvicorn |
| DB / ORM | SQLite + SQLAlchemy 2.0 (sync) + Alembic |
| Validation | Pydantic v2 |
| Scheduling | APScheduler (wired, no jobs registered yet) |
| CV / face recognition | OpenCV + InsightFace `buffalo_l` (optional) |
| Crypto | `cryptography` (Fernet for camera creds) |
| Tests | pytest + FastAPI TestClient |

## Requirements

- **Python 3.11–3.12 recommended.** The venv on this machine is 3.14, which works
  for the core stack. **InsightFace / onnxruntime wheels lag the latest CPython**;
  if you want real face matching, use Python 3.11 or 3.12 for the venv.
- Windows: the [Microsoft VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
  is required by `onnxruntime`.

## Setup

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"

# Generate a Fernet key and put it in .env
python -m app.cli gen-encryption-key > /dev/null   # prints the key
# → copy the printed key into .env as FA_ENCRYPTION_KEY=...

# Create the database schema
python -m alembic upgrade head

# Create your first admin API key (plaintext shown once — save it)
python -m app.cli create-api-key --label "Admin" --scope admin
```

`.env` should look like:

```
FA_ENCRYPTION_KEY=<from gen-encryption-key>
FA_AUTOSTART_ENGINE=true
FA_HOST=0.0.0.0
FA_PORT=8000
```

## Running

```bash
uvicorn app.main:app --reload
```

- Interactive API docs: <http://localhost:8000/docs>
- Health check (no auth): <http://localhost:8000/health>

## CLI

```bash
python -m app.cli gen-encryption-key             # print a new Fernet key
python -m app.cli create-api-key --label X --scope admin
python -m app.cli list-api-keys
python -m app.cli revoke-api-key <id>
```

## Tests

```bash
pytest
```

Camera-dependent tests are marked `@pytest.mark.camera` and skipped by default.

## Configuring the camera

The default MJPEG URL (SRS §1.4) is seeded into `system_settings` on first run:

```
http://192.168.1.111/cgi-bin/mjpg/video.cgi?channel=1&subtype=1
```

For a URL with credentials, use the form
`http://user:pass@host/...` — the userinfo is encrypted at rest (§3.13.9) and
masked in API responses (§3.1.9). Once the `/settings` group is implemented you'll
edit it through the dashboard; for now update the `system_settings` row directly
or re-seed.

## GPU acceleration (§6.1.1)

To use an NVIDIA GPU:

```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu
```

Then `InsightFaceProvider` is initialised with `providers=["CUDAExecutionProvider"]`
(see `app/engine/face_provider.py`).

## HTTPS / reverse proxy (§3.13.8)

This server is HTTP-only by design. For public deployments, put NGINX (or similar)
in front and terminate TLS there. The `/health` endpoint is unauthenticated by
design for external monitors.

## CORS (admin dashboard)

The app enables `CORSMiddleware`. Allowed origins come from `FA_CORS_ORIGINS`
(comma-separated); the Vite dev server (`http://localhost:5173`) is allowed by
default. Add more origins for production deployments:

```
FA_CORS_ORIGINS=http://localhost:5173,https://attendance.example.com
```

In development the Vite proxy forwards `/api` and `/health` to the backend, so
CORS isn't even exercised — but it's there for separately-served frontends.

## What's implemented vs. stubbed

| Group | Status | SRS |
|---|---|---|
| `/health` | ✅ implemented | §3.11.1 |
| `/api/v1/device` | ✅ implemented (info, camera test, MJPEG proxy, frame, service control, stats) | §3.1, §3.4.14, §3.11.3 |
| `/api/v1/employees` | ⏳ stub (501) | §3.2 |
| `/api/v1/employees/{id}/face` | ⏳ stub | §3.3 |
| `/api/v1/attendance` | ⏳ stub | §3.5 |
| `/api/v1/webhooks` | ⏳ stub | §3.6 |
| `/api/v1/sync` | ⏳ stub | §3.7 |
| `/api/v1/reports` | ⏳ stub | §3.9 |
| `/api/v1/backup` | ⏳ stub | §3.10 |
| `/api/v1/settings` | ⏳ stub | §6.4.1 |
| `/api/v1/system/logs` | ⏳ stub | §3.12 |
| `/ws/events`, `/events/stream` | ⏳ not yet routed | §3.8 |

### Engine status

The recognition engine runs as a background thread (started by the FastAPI
lifespan). It reads the MJPEG stream with reconnect/backoff (§3.4.13), runs face
detection at the configured rate (§3.4.2) via InsightFace when installed, and
exposes operational stats. **Not yet wired in this phase:** embedding extraction →
cosine match → attendance-log write → webhook dispatch → WebSocket/SSE fan-out.
The matching logic itself (`app/engine/matcher.py`) is implemented and unit-ready.

### InsightFace fallback

If `insightface` is not installed (e.g. on a CPython version lacking wheels), the
provider falls back to `StubFaceProvider`, which detects no faces. The rest of the
app still runs, reads frames, tracks FPS, and reports camera online/offline.

Install it separately when ready:

```bash
pip install insightface onnxruntime
```

## Project layout

```
backend/
├── app/
│   ├── main.py            # app factory + lifespan
│   ├── config.py          # env-driven settings
│   ├── db.py              # engine, SessionLocal, Base, get_db
│   ├── cli.py             # gen-encryption-key, create-api-key, ...
│   ├── api/
│   │   ├── deps.py        # API-key + scope dependencies
│   │   └── v1/
│   │       ├── router.py  # mounts all groups
│   │       ├── health.py  # GET /health (unauthenticated)
│   │       ├── device.py  # full vertical slice
│   │       └── stubs.py   # 501 stubs for the rest
│   ├── core/              # security, crypto, response, enums, settings_store
│   ├── engine/            # service, frame_source, face_provider, matcher, defaults
│   ├── events/bus.py      # in-process pub/sub
│   ├── workers/scheduler.py
│   ├── models/            # 10 SQLAlchemy tables (SRS §5)
│   └── schemas/           # Pydantic v2 (common envelope + device)
├── alembic/               # migrations
├── data/                  # runtime: db, snapshots/, backups/, models/  (gitignored)
├── tests/
├── pyproject.toml
└── .env.example
```
