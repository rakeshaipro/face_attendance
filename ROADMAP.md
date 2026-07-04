# Roadmap

Single source of truth for project status. Update after each phase.

## Status legend

- ✅ **Done** — implemented, tested (backend tests pass), endpoint reachable from the frontend.
- 🟡 **Partial** — backend code exists but tests are failing or the frontend is still a placeholder.
- ⏭️ **Skipped** — explicitly skipped (see note).
- ⬜ **Pending** — not yet started.

## Phases (SRS-derived)

| # | Phase | SRS sections | Status | Summary |
|---|---|---|---|---|
| 1 | Scaffold + `/device` + `/health` | §3.1, §3.11 | ✅ | Project layout, settings store, 10 SQLAlchemy tables, Alembic baseline, FastAPI shell, lifespan-managed engine + scheduler, API-key auth, scope deps, `/health` (unauth) + `/device` (info, camera test, MJPEG proxy, frame, service controls, stats). |
| 2 | Employees + Enrollment | §3.2, §3.3 | ✅ | `/employees` (CRUD, search/filter/pagination, block/unblock, CSV import/export, cascade delete), `/employees/{id}/face` (7-pose guided enrollment with auto-capture, finalize/verify/re-enroll/remove), per-pose 512-dim ArcFace embeddings stored individually (never averaged). |
| 3 | Recognition loop + Attendance | §3.4, §3.5 | ✅ | Engine: read → detect (embeddings) → cosine match → filter chain (threshold, blocked, cooldown, min-face-size) → write. CooldownTracker (in-memory). Settings hot-reloaded on TTL. `/attendance` (query, today, manual entry, edit, delete-with-reason, snapshot download). Snapshot storage date-partitioned. |
| 4 | Webhooks + Sync | §3.6, §3.7 | ✅ | Payload builder + HMAC signer + `send_one`; async dispatcher subscribing to event bus; in-process queue + worker; backoff 5/30/300s; `max_retries` = retry count (initial + retries = max_retries + 1). `/webhooks` CRUD + test + delivery log + manual retry. `/sync` status/batch/resend/config + APScheduler auto-sync. **Bug fixed during phase:** duplicate bus subscriptions on restart (added `bus.unsubscribe_async`). |
| 5 | Real-time streaming (WS + SSE) | §3.8 | ⏭️ **Skipped** | User said: "Real-time Event Streaming is not really required. skip this". Frontend Live View keeps its 10s `/attendance/today` poll. |
| 6 | Reports + Audit + Export | §3.9 | ✅ | `/reports/logs` (filters + pagination), `/reports/logs/daily`, `/reports/logs/export` (CSV via stdlib + XLSX via `openpyxl`), `/reports/audit`, `/reports/audit/export`. `ReportLogRow` is the canonical row view; reports are read-only (§3.9.1). Frontend Reports page (2 tabs). |
| 7 | Backup/Restore + System Logs | §3.10, §3.12 | ✅ | `services/backup.py` (create full/database-only ZIP, restore with confirm flag + SQL integrity, prune, max-scheduled enforcement), `services/system_log.py` (write_system_log helper), `/backup` (CRUD + download + restore + schedule), `/system/logs` (query by severity/event/date). `write_system_log` wired into engine start/stop/restart, camera online/offline, app startup/shutdown, and post-restore. Restore handler opens a fresh session for the post-restore log writes so the engine-dispose inside the service can't stale the request's pooled connection; `.restoring` temp file is unlinked on both success (in-place write path) and failure. Frontend System page (4 tabs) backed by centralized hooks in `lib/queries.ts`. |
| 8 | Monitoring jobs | §3.11 | ✅ | Disk-space monitor (fires `device.storage_low` via event bus), attendance/snapshot/system-log retention purges, SMTP email alerts (camera offline + storage low), all scheduled via APScheduler. `/monitoring/status` endpoint. |
| 9 | Frontend dashboard | — | ✅ | React 18 + Vite + TS, TanStack Query/Table, RHF/Zod, Tailwind+shadcn-style primitives, Recharts, Lucide. Sections: Dashboard, Live View (10s poll), Employees (+Enrollment), Attendance, Reports (Phase 6), Device (RTSP), Sync + Webhooks (full UI), System (Backups, System logs, Monitoring, Settings hint, Time). JWT-less API-key auth via `localStorage`. |
| 10 | PostgreSQL + pgvector HNSW | §3.4 scaling | ✅ | Docker PG (pgvector/pgvector:pg17), HNSW index on `face_embeddings.embedding_vec`, pgvector ANN cosine search replacing brute-force numpy matcher. Migration auto-converts from `embedding_json`. Backup service rewritten for `pg_dump`/`psql`. |

**RTSP integration** (added after Phase 7 was planning): `FrameSource` + device endpoints use `cv2.CAP_FFMPEG` + `CAP_PROP_BUFFERSIZE=1`; `OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp`; default camera URL is Dahua RTSP mainstream (`rtsp://192.168.1.111:554/cam/realmonitor?channel=1&subtype=0`); MJPEG proxy self-heals on disconnect with JPEG quality=80.

## Statistics

- **Backend tests:** 128 passing, 0 failing.
- **Frontend:** typecheck clean, production build clean (590KB JS / 175KB gzip).
- **Endpoint coverage (§4.6):** `/health`, `/device`, `/employees`, `/employees/{id}/face`, `/attendance`, `/webhooks`, `/sync`, `/reports`, `/backup`, `/system/logs`, `/settings`, `/monitoring`, `/time`, `/ws/events`, `/events/stream` — last two reach 501 (not wired).

## Next decisions

1. (Optional) Implement the deferred Phase 5 streaming if there's a concrete use case.
