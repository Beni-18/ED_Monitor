# ED Deterioration Monitor

A clinical decision-support prototype for an Emergency Department ward. It combines the
deterministic **NEWS2** early-warning score with a **retrieval-augmented LLM agent**
(LangGraph + Groq + ChromaDB) to flag patients who are deteriorating in ways a threshold score
misses, routes flagged patients to a clinician inbox, and records every action in an audit log.

> **Scope:** research/coursework prototype running on **synthetic data**. It is not a medical
> device and has not been clinically validated.

- Backend: FastAPI, SQLAlchemy (SQLite), LangGraph, ChromaDB, Groq (`openai/gpt-oss-120b`)
- Frontend: Next.js 16 (App Router), React 19, Recharts
- Full phase-by-phase history: [`PROJECT_LOG.md`](PROJECT_LOG.md)

---

## 1. Quick start

```bash
# backend/.env  (never commit)
GROQ_API_KEY=...          # optional: without it the agent uses a rule-based fallback
SECRET_KEY=...            # required: JWT signing key (the server refuses to start without it)

./boot.sh                 # starts backend :8000 and frontend :3000
```

Manual start:

```bash
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8000

cd frontend && npm ci && npm run build && npm start
```

Docker: `docker compose up --build` (needs `SECRET_KEY` and optionally `GROQ_API_KEY` in the
environment or a `.env` next to `docker-compose.yml`). `NEXT_PUBLIC_API_BASE` is baked into the
frontend at build time and must be reachable **from the browser** (default `http://localhost:8000`).

Demo users (seeded on first start): `doctor`, `nurse`, `admin`, password `password123`.
**Change these before any non-demo use.**

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | required | HS256 signing key for JWTs |
| `GROQ_API_KEY` | unset | Enables the LLM; unset = heuristic fallback (`/api/health` reports `llm_enabled`) |
| `DATABASE_URL` | `sqlite:///./ed_monitor.db` | SQLAlchemy URL |
| `CHROMA_DB_PATH` | `backend/chroma_db` | ChromaDB persistence directory |
| `BATCH_WORKERS` | `8` | Concurrent evaluations in a ward batch job |
| `GROQ_TPM_LIMIT` | `8000` | Org tokens-per-minute quota (free tier); raise on paid tiers |
| `GROQ_TPM_UTILISATION` | `0.8` | Fraction of the quota the app will use |
| `GROQ_EST_TOKENS_PER_CALL` | `1500` | Budget reserved before a call's real usage is known |
| `GROQ_REASONING_EFFORT` | `medium` | `low`/`medium`/`high` for the reasoning model |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000` | Backend URL used by the browser |

---

## 2. Architecture

```
Browser (Next.js)                         FastAPI backend
 ├─ hooks: useAuth, useWard   ──REST──►    auth (JWT, RBAC)  ─►  SQLite (SQLAlchemy)
 ├─ views (6) + ChatWidget    ◄──WS────    /ws/vitals            users · patients · observations
 └─ error boundaries                       simulator task        escalations · audit_logs
                                           batch job pool
                                           LangGraph agent ─► ChromaDB (25 guidelines)
                                                           └► Groq LLM (token-budget guarded)
```

### LangGraph agent (`backend/agent.py`)

```
assess_missing_data ──(risk ≥ 8)────────────────────────────► generate_recommendation
        └─(risk < 8)► compute_baseline ► retrieve_context ► analyze_trends ─┘
```

| Node | What it does |
|---|---|
| `assess_missing_data` | Risk 0–10: 1.5 per missing vital (of 7), +3 unconscious, +2 distressed |
| `compute_baseline` | NEWS2 of the latest observation (`baseline.py`) |
| `retrieve_context` | ChromaDB semantic search with the nursing notes → top-3 guidelines (RAG) |
| `analyze_trends` | First vs last observation: HR +10, SpO2 −2, SBP −10, RR +4 each count as worsening; deteriorating if ≥ 2 worsen, or SpO2 falls ≥ 4 alone |
| `generate_recommendation` | Missing-data fast-track → `Unknown`; no API key → rule-based fallback; else Groq structured output (`AgentRecommendation`). LLM failure → `Unknown`, confidence `0.0` |

Every node records its latency into `node_timings`; results feed `/api/performance`.

### Other mechanisms

- **Live feed:** a background task appends a drifted observation to a random patient every 5 s
  (only while a client is connected) and pushes `VITAL_UPDATE`. If SpO2 < 88, HR > 130 or SBP < 90
  it runs the agent and, for High/Medium, creates a pending escalation and pushes `NEW_ESCALATION`.
  Observations are capped at 30 per patient.
- **Batch evaluation:** `POST /api/evaluate/batch` starts a background job (thread pool of
  `BATCH_WORKERS`); clients poll `GET /api/evaluate/batch/{job_id}` for `completed/total`.
- **Rate-limit guard (`llm_limits.py`):** all LLM calls share a rolling 60 s token budget, replace
  the reservation with real usage after each call, retry 429s after Groq's requested cool-down
  (≤ 30 s) and retry `tool_use_failed` responses. Longer waits (e.g. daily quota) fail fast.
- **Clinical Copilot (`/api/chat`):** two-layer domain guard — whole-word keyword pre-filter, then a
  system prompt — with ward/patient context injected from the database.

---

## 3. API reference

All routes except login and health require `Authorization: Bearer <JWT>`. The WebSocket takes
`?token=<JWT>`. Roles: **D**octor, **N**urse, **A**dmin.

| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/api/login` | public, 10/min/IP | OAuth2 form → `{access_token, token_type, role}`; 429 when throttled |
| GET | `/api/health` | public | `{status, version, llm_enabled}` |
| GET | `/api/patients` | any role | All patients with observations and last risk level |
| GET | `/api/patients/{id}` | any role | One patient (404 if unknown) |
| GET | `/api/patients/{id}/observations` | any role | Observation time series |
| POST | `/api/evaluate/{id}` | any role | Run the agent on one patient; persists `risk_level`; returns `AgentRecommendation` |
| POST | `/api/evaluate/batch` | any role | Start (or join) a ward batch job → `202 {job_id,…}` |
| GET | `/api/evaluate/batch/{job_id}` | any role | Job status, `completed/total`, final result |
| GET | `/api/escalations` | any role | All escalations |
| POST | `/api/escalations/{patient_id}` | any role | Create a pending escalation (refreshes an existing pending one; 404 if patient unknown) |
| PATCH | `/api/escalations/{id}/approve` | **D** | Approve with `{clinician_notes}`; 409 if already resolved |
| PATCH | `/api/escalations/{id}/reject` | **D** | Reject with `{clinician_notes}`; 409 if already resolved |
| GET | `/api/audit-logs` | any role | Latest 100 audit entries |
| GET | `/api/export/handover` | any role | JSON handover report for High/Medium patients |
| POST | `/api/chat` | any role | Clinical Copilot `{message, patient_id?}` → `{reply, out_of_domain, context_used}` |
| GET | `/api/metrics` | any role | Counts + stored benchmark results |
| GET | `/api/performance` | any role | Latency (avg/p95/min/max), per-node timings, real token usage, LLM success rate (last 100 evaluations) |
| GET | `/api/admin/users` | **A** | List users |
| POST | `/api/admin/users` | **A** | Create user `{username, password ≥ 8, role ∈ Doctor/Nurse/Admin}` |
| DELETE | `/api/admin/users/{id}` | **A** | Delete user (not yourself) |
| WS | `/ws/vitals?token=` | any role | `VITAL_UPDATE`, `NEW_ESCALATION` events; closes with 1008 on a bad token |

Interactive OpenAPI docs are served at `/docs` when the backend is running.

---

## 4. Database schema (SQLite via SQLAlchemy — `backend/models_db.py`)

```
users(id PK, username UNIQUE, hashed_password, role)
patients(id PK str, name, bed_number, admission_time, risk_level NULL)
observations(id PK, patient_id FK→patients.id, timestamp,
             hr, bp_systolic, bp_diastolic, resp_rate, temp, spo2, consciousness_level  -- all NULLable
             nursing_notes, is_incomplete_history, is_unconscious, is_distressed)
escalations(id PK uuid, patient_id FK→patients.id, status pending|approved|rejected,
            clinician_notes NULL, created_at, resolved_at NULL, recommendation_json)
audit_logs(id PK, timestamp, username, role, action, details)
```

- `patients 1—N observations` (cascade delete) and `patients 1—N escalations`.
- `escalations.recommendation_json` is a JSON snapshot of the `AgentRecommendation` at escalation
  time, so later re-evaluations do not rewrite history.
- Audited `action` values: `USER_LOGIN`, `BATCH_EVALUATION`, `APPROVE_ESCALATION`,
  `REJECT_ESCALATION`, `EXPORT_HANDOVER_REPORT`, `AI_CHAT_QUERY`, `CREATE_USER`, `DELETE_USER`.
  The log is append-only **by convention** (no update/delete endpoint); the database does not
  enforce immutability.

---

## 5. Testing

Run: `cd backend && pytest test_agent.py test_api.py -v` (no network or API key needed). The suite
is hermetic: `test_api.py` points `DATABASE_URL` at a fresh temp SQLite file, enters the app's
lifespan (so users and 170 patients are seeded), and removes `GROQ_API_KEY` so the deterministic
fallback runs. `conftest.py` exits directly after pytest's summary to avoid an intermittent native
abort (onnxruntime) during interpreter shutdown, preserving the real exit status.

**50 tests: 26 unit (`test_agent.py`) + 24 integration (`test_api.py`).**

### Unit tests — `test_agent.py`

| Area | Tests | What is verified |
|---|---|---|
| `assess_missing_data` | 7 | No missing vitals → 0; 3 missing → 4.5; unconscious +3; distressed +2; cap at 10; fast-track condition; timing recorded |
| `route_after_missing_data` | 4 | Fast-track at and above the 8.0 threshold; baseline path below it and at zero |
| `compute_baseline` (NEWS2) | 4 | Stable → 0; extreme vitals → ≥ 7; bradycardia scoring; timing recorded |
| `analyze_trends` | 6 | Obvious deterioration, silent hypoxia (SpO2 fall alone), compensated shock flagged; stable and single-observation not flagged; timing recorded |
| LLM rate-limit guard | 5 | Token budget blocks until the window frees; settling releases unused reservation; `Retry-After` parsing; `tool_use_failed` retried; long (daily-quota) 429 fails fast |

### Integration tests — `test_api.py`

| Area | Tests | What is verified |
|---|---|---|
| Public/auth | 5 | Health; wrong password → 401; role returned at login; all protected routes → 401 without a token; login rate limit → 429 |
| Patients & metrics | 3 | List, detail, metrics schema |
| Batch evaluation | 3 | 401 without token; background job reaches `done`, `completed == total`, counts sum to `evaluated_count`; a second start joins the running job; unknown job → 404 |
| Escalation workflow & RBAC | 4 | Nurse and Admin cannot approve (403); evaluate → escalate → dedupe → approve; re-resolving → 409; unknown patient → 404 |
| Admin | 1 | Non-admin 403; invalid role/short password → 422; create and delete user |
| Audit/export | 2 | Audit-log list; handover report shape |
| Chatbot | 3 | Off-topic blocked; clinical question allowed; clinical words containing off-topic substrings ("cardiac care", "who is the highest risk patient") allowed |
| WebSocket | 1 | Invalid token rejected, valid token accepted |
| Error boundary | 2 | Unhandled exception → generic JSON 500 with `request_id`, no leaked detail, CORS header present; malformed body → 422, unknown resource → 404 |

### Not covered

No automated frontend tests (the UI was verified manually in a browser at 1280/768/375 px), no
load tests, no live-LLM tests in CI (a benchmark run exercises the real model — see §7).
CI (`.github/workflows/python-app.yml`) runs flake8 and pytest on Python 3.10 and 3.11.

---

## 6. Error handling and error boundaries

**LLM layer** (`agent.py`, `llm_limits.py`)

| Failure | Behaviour |
|---|---|
| No API key | Rule-based fallback recommendation (clearly labelled); `/api/health.llm_enabled=false`; UI shows "OFFLINE HEURISTIC MODE" |
| 429 rate limit | Shared token budget prevents bursts; remaining 429s retried after Groq's cool-down (≤ 30 s, up to 4 attempts); longer waits fail fast |
| `tool_use_failed` / schema mismatch | Retried; if it persists → raised |
| Any LLM error after retries | `risk_level="Unknown"`, `confidence_score=0.0`, reasoning explains the error, action = manual review. Never silently reported as a verdict; excluded from benchmark metrics |
| Critical missing data | Skips the LLM entirely → `Unknown` (fast-track) |

**Backend**

- `HTTPException` for expected failures: 401 (bad/expired token), 403 (role), 404, 409 (already
  resolved), 422 (Pydantic validation), 429 (login throttle).
- `error_boundary_middleware` (`main.py`): any other exception is logged with a `request_id`
  and returned as `{"detail": "Internal server error", "request_id": …}` plus an `X-Request-ID`
  header — no stack trace leaks. It sits inside `CORSMiddleware`, so error responses keep CORS
  headers.
- Startup seeding is wrapped in try/except with rollback; audit-log write failures roll back and
  never break the request that triggered them; WebSocket sends to dead clients drop the client.
- Batch jobs isolate per-patient failures (`failed_count`) and mark the job `error` on an
  unexpected exception; DB writes happen on one thread/session.

**Frontend** (Next.js 16 error conventions)

| Boundary | File | Scope |
|---|---|---|
| Per-view | `components/ViewBoundary.js` (`catchError`) | Each dashboard view and the chat widget; a crash shows a recoverable message and the rest of the app keeps working. Keyed by tab, so switching tabs recovers |
| Route segment | `app/error.js` | Errors outside the view boundaries; `retry()` |
| Root layout | `app/global-error.js` | Last resort; renders its own `<html>` |
| 404 | `app/not-found.js` | Unknown routes |

Network/API failures are handled in `hooks/useWard.js` (try/catch, user-visible notices, offline
banner, WebSocket auto-reconnect every 3 s); any `401` returns the user to the login screen.

---

## 7. Evaluation (`backend/experiment.py`)

`python experiment.py [--dev-scale N]` benchmarks the pipeline against the NEWS2 baseline
(score ≥ 5) on two sets, and writes `experiment_results.json` (shown in the Metrics tab):

- **development** — deterministic templates from `generate_patients` (8 archetypes). The agent,
  guidelines and prompt were tuned on these, so results are an upper bound.
- **hold-out** — 80 randomised patients (`generate_holdout_patients`): different archetypes,
  noise and note wording, including hard negatives (anxious tachycardia, settling fever,
  chronic COPD baseline).

Reported: sensitivity with 95 % Wilson interval, false-alert rate, precision, F1, per-archetype
breakdown, and an `ai_strict` operating point that does not count `Unknown` as a detection.
Evaluations whose LLM call failed are **excluded and listed**, never counted as detections; the UI
refuses to headline a run with < 90 % coverage.

**Latest complete run** (`gpt-oss-120b`, reasoning effort `medium`, 27 Oct 2026, 0 LLM failures, `--dev-scale 2`):

| Set (n) | Metric | NEWS2 ≥ 5 | AI agent |
|---|---|---|---|
| **Hold-out (80)** | Sensitivity (95 % CI) | 62.5 % (47–76) | **100 %** (91–100) |
| | False-alert rate | 0 % | 25 % (10/40 negatives) |
| | Precision / F1 | 100 % / 76.9 % | 80.0 % / 88.9 % |
| Development (34) | Sensitivity (95 % CI) | 38.5 % (22–57) | 100 % (87–100) |
| | False-alert rate | 0 % | 0 % |
| | Precision / F1 | 100 % / 55.6 % | 100 % / 100 % |

Hold-out sensitivity per archetype (AI vs NEWS2): occult bleed 100 % vs 10 %, overdose 100 % vs 70 %,
respiratory decline 100 % vs 80 %, atypical sepsis 100 % vs 90 %. Hold-out false alerts (AI vs
NEWS2): chronic-COPD baseline **90 % vs 0 %**, well/fit 10 % vs 0 %, anxious 0 %, settling fever 0 %.
The agent therefore trades a 25 % false-alert rate for a 37.5-point gain in sensitivity; its main
known failure mode is treating a chronically low SpO2 baseline as deterioration. With `Unknown`
not counted as a detection (`ai_strict`) dev sensitivity is 84.6 % and hold-out is unchanged.
Samples are small (CI shown); do not read these as clinical performance.

**Limitations:** all data are synthetic and labels come from how each trajectory was constructed;
NEWS2 omits the supplemental-oxygen item and SpO2 scale 2; on both sets the NEWS2 baseline has no
false alerts, so the benchmark cannot show a false-alert reduction.

---

## 8. Security summary

JWT (HS256, 24 h) with bcrypt-hashed passwords; RBAC via FastAPI dependencies; login throttled to
10/min/IP; the server refuses to start without `SECRET_KEY`; every data route and the WebSocket
require a token; secrets and databases are gitignored; no stack traces in error responses; admin
input validated (role whitelist, password ≥ 8); `npm audit`: 0 vulnerabilities.
Known gaps: tokens are stored in `localStorage` with no server-side revocation, CORS allows any
origin, demo credentials are seeded, and the audit log is not tamper-proof.

## 9. Project layout

```
backend/   main.py (API) · agent.py (LangGraph) · llm_limits.py · baseline.py · auth.py
           dataset.py · vector_store.py · experiment.py · models.py · models_db.py · tests
frontend/src/app/         page.js (composition) · error.js · global-error.js · not-found.js
frontend/src/components/  views, chat, charts, EscalationCard, ViewBoundary, dashboard.module.css
frontend/src/hooks/       useAuth.js · useWard.js        frontend/src/lib/  config, risk, benchmark
```
