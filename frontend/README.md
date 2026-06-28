# Face Attendance — Admin Dashboard

React 18 + Vite + TypeScript single-page app for the Face Recognition Attendance
System. Talks to the FastAPI backend (Phases 1–3) via a Vite dev proxy.

## Stack

- **React 18** + **Vite** + **TypeScript**
- **React Router** — navigation across the 9 dashboard sections
- **TanStack Query** — server state, cache invalidation, polling
- **React Hook Form** + **Zod** — form validation
- **shadcn/ui**-style primitives + **Tailwind CSS** — UI
- **Recharts** — Dashboard charts
- **lucide-react** — icons

## Prerequisites

- Node 18+ (tested on Node 24)
- The backend running (see `../backend/README.md`)

## Setup

```bash
cd frontend
npm install
```

## Development

Start the backend first (default `http://localhost:8000`), then:

```bash
npm run dev
```

The dashboard is served at **http://localhost:5173**. Sign in with an API key
(created via `python -m app.cli create-api-key --scope admin` in the backend).

### Backend on a different port

If the backend isn't on `:8000`, point Vite at it:

```bash
VITE_BACKEND_URL=http://localhost:8001 npm run dev
```

### Webcam enrollment

The guided enrollment screen uses the device webcam (`getUserMedia`). Browsers
only grant webcam access on **`localhost`** or over **HTTPS**. The Vite dev
server on `localhost` satisfies this; for LAN deployment you must serve the
built dashboard over HTTPS.

## Build

```bash
npm run build      # type-checks (tsc -b) then builds to dist/
npm run preview    # serve the production build locally
```

## Sections

| # | Section | Status | Notes |
|---|---|---|---|
| 1 | Dashboard | ✅ | Health cards + engine stats, recent detections |
| 2 | Live View | ✅ | MJPEG preview + recent-detections strip (10s poll) |
| 3 | Employees | ✅ | List/search/filter, create/edit, block/unblock, CSV import/export |
| 3a | Enrollment | ✅ | Guided 7-pose webcam flow (auto-capture on pose+quality) |
| 4 | Attendance | ✅ | Filters, manual entry, edit/delete, snapshot thumbnails |
| 5 | Reports | 🟡 ComingSoon | backend stub returns 501 (Phase 6) |
| 6 | Sync | 🟡 ComingSoon | (Phase 4) |
| 7 | Webhooks | 🟡 ComingSoon | (Phase 4) |
| 8 | Device | ✅ | Identity, camera test, preview, service controls, stats |
| 9 | System | 🟡 ComingSoon | (Phase 7) |

## Project layout

```
src/
├── main.tsx                # entry: QueryClient + Router + AuthProvider
├── App.tsx                 # routes + auth gate
├── auth/                   # AuthContext (API key in localStorage) + Login
├── components/
│   ├── layout/             # AppShell, Sidebar (9 sections), Topbar
│   ├── ui/                 # shadcn-style primitives (Button, Card, Table, Dialog…)
│   └── shared.tsx          # StatusBadge, EmptyState, ComingSoon, ErrorBanner
├── lib/
│   ├── api.ts              # fetch wrapper: envelope unwrap, X-API-Key, 401 logout
│   ├── queries.ts          # TanStack Query hooks per endpoint
│   ├── types.ts            # TS types mirrored from backend schemas
│   └── utils.ts            # cn(), date/uptime/bytes formatters
└── pages/
    ├── Dashboard.tsx · LiveView.tsx · Device.tsx
    ├── employees/          # EmployeeList, EmployeeDetail, Enrollment
    └── attendance/         # AttendanceList (list + manual + detail drawer)
```
