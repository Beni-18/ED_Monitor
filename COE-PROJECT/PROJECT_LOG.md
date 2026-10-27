# ED Deterioration Monitor — Project Log
## COE Project | Phase Submission Reference Document

> **Last Updated:** 2026-09-10  
> **Version:** v2.2.0  
> **Author:** Bennish (with AI pair-programming)

---

## 1. Project Overview

The **Emergency Department (ED) Deterioration Monitor** is a real-time clinical decision support system designed to automatically detect patients at risk of deterioration and escalate to the appropriate clinical staff. It uses a multi-agent AI pipeline powered by a Large Language Model (Groq), retrieval-augmented generation (RAG) from clinical guidelines, and a NEWS2 baseline scoring system.

### Core Goals
- Detect subtle patient deterioration that rule-based systems miss
- Quantify detection rate improvement over a pure NEWS2 baseline
- Provide clinicians with explainable AI recommendations
- Support role-based access for Doctors, Nurses, and Admins

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| **Backend Framework** | FastAPI (Python) |
| **AI Orchestration** | LangGraph (stateful agent graph) |
| **LLM Provider** | Groq API — `openai/gpt-oss-120b` |
| **LLM Integration** | LangChain (`langchain-groq`, `langchain-core`) |
| **Vector Store (RAG)** | ChromaDB with `sentence-transformers` embeddings |
| **Database** | SQLite via SQLAlchemy ORM |
| **Auth** | JWT (`python-jose`), bcrypt password hashing (`passlib`) |
| **Frontend** | Next.js 16 (App Router, Turbopack) |
| **Charts** | Recharts |
| **CI/CD** | GitHub Actions |
| **Containerization** | Docker + Docker Compose |

---

## 3. Project Architecture

```
┌────────────────────────────────────────────┐
│                Next.js Frontend            │
│  Login → Dashboard → Patient Detail View  │
│  RBAC UI (Doctor/Nurse/Admin roles)        │
└───────────────────┬────────────────────────┘
                    │ REST API (JWT Auth)
┌───────────────────▼────────────────────────┐
│              FastAPI Backend               │
│  /api/login  /api/patients  /api/evaluate  │
│  /api/escalations  /api/metrics            │
└──────┬──────────────────────┬──────────────┘
       │                      │
┌──────▼──────┐    ┌──────────▼───────────┐
│  SQLite DB  │    │   LangGraph Agent    │
│  - users    │    │   assess_missing_data│
│  - patients │    │   compute_baseline   │
│  - obs      │    │   retrieve_context   │
│  - escalat. │    │   analyze_trends     │
└─────────────┘    │   generate_recommendation│
                   └──────────┬───────────┘
                              │
                   ┌──────────▼───────────┐
                   │  ChromaDB + Groq LLM │
                   │  15 Clinical Guidel. │
                   └──────────────────────┘
```

---

## 4. User Roles & Permissions

| Feature | Doctor | Nurse | Admin |
|---|---|---|---|
| View patient list | ✅ | ✅ | ✅ |
| View vital trends | ✅ | ✅ | ✅ |
| Run AI evaluation | ✅ | ✅ | ✅ |
| Approve escalation | ✅ | ❌ | ❌ |
| Reject escalation | ✅ | ❌ | ❌ |
| View system metrics | ✅ | ✅ | ✅ |
| View AI latency/tokens | ❌ | ❌ | ✅ |

**Default credentials (development):** `doctor / nurse / admin` — password: `password123`

---

## 5. API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/login` | None | OAuth2 form login, returns JWT + role |
| GET | `/api/health` | None | Health check |
| GET | `/api/patients` | Bearer | List all 100 synthetic patients |
| GET | `/api/patients/{id}` | Bearer | Get single patient with observations |
| GET | `/api/patients/{id}/observations` | Bearer | Get time-series observations |
| POST | `/api/evaluate/{id}` | Bearer | Run AI evaluation on patient |
| GET | `/api/escalations` | Bearer | List all escalations |
| POST | `/api/escalations/{id}` | Bearer | Create escalation from evaluation |
| PATCH | `/api/escalations/{id}/approve` | Doctor | Approve escalation |
| PATCH | `/api/escalations/{id}/reject` | Doctor | Reject escalation |
| GET | `/api/metrics` | Bearer | System metrics + AI performance |

---

## 6. LangGraph Agent Pipeline

The AI evaluation pipeline is a stateful directed acyclic graph:

```
assess_missing_data
    │
    ├─ (risk ≥ 8) ──────────────────────► generate_recommendation
    │
    └─ (risk < 8) → compute_baseline → retrieve_context → analyze_trends → generate_recommendation
```

### Node descriptions
1. **assess_missing_data** — Calculates a risk score from missing vitals (each missing vital = 1.5 pts), unconscious (+3), distressed (+2). Max 10.
2. **compute_baseline** — Calculates the NEWS2 score from vitals using clinical scoring tables.
3. **retrieve_context** — Queries ChromaDB with the nursing notes to retrieve the 3 most relevant clinical guidelines using semantic similarity.
4. **analyze_trends** — Compares first vs. last observation for HR, SpO2, BP, RR trends. Flags as "deteriorating" if ≥2 parameters trend negatively.
5. **generate_recommendation** — Calls the Groq LLM with all context. Uses structured output to force the response into the `AgentRecommendation` Pydantic schema. Falls back to heuristics if the API fails.

### Groq Model
- **Current:** `openai/gpt-oss-120b`
- **Previous (decommissioned):** `llama-3.1-70b-versatile` → then `llama-3.3-70b-versatile` (also not available)
- **Average latency:** ~1,400ms per evaluation

---

## 7. Synthetic Dataset

The dataset generator (`dataset.py`) produces 4 patient categories at `scale_factor=10` (100 total patients):

| Category | Count | Description |
|---|---|---|
| Stable | 30 | Normal vitals, flat trends |
| Obvious Deterioration | 20 | Rapidly worsening HR, SpO2, BP |
| Subtle Deterioration | 30 | Borderline trending vitals + vague nursing notes — this is what the AI catches |
| Severe Missing Data | 20 | Missing vitals, unconscious patients, equipment failure scenarios |

Each patient has **6 observations** spaced 2 hours apart (12-hour window).

**15 clinical guidelines** are embedded in ChromaDB covering: sepsis recognition, hypovolemic shock, respiratory failure, altered mental status, NEWS2 limitations, compensated shock, silent hypoxia, and more.

---

## 8. Chronological Work Log

### Phase 1 — Baseline & Evaluation Framework
- ✅ Created `dataset.py` with 4 patient archetypes (initially 10 patients, scaled to 100)
- ✅ Created `baseline.py` with NEWS2 scoring algorithm
- ✅ Created `experiment.py` to compare AI vs. baseline detection rates
- ✅ Created `vector_store.py` with ChromaDB and sentence-transformers embeddings
- ✅ Built initial LangGraph agent graph in `agent.py` with heuristic nodes

### Phase 2 — LLM Integration (Groq)
- ✅ Replaced heuristic `generate_recommendation` node with `ChatGroq` LLM call
- ✅ Used `with_structured_output(AgentRecommendation)` to enforce JSON schema output
- ✅ Added `latency_ms` and `tokens_used` tracking to `AgentRecommendation` model
- ✅ Added heuristic fallback if Groq API fails or key is missing
- ✅ Stored Groq API key in `backend/.env` loaded via `python-dotenv`
- ✅ **Model history:** `llama-3.1-70b-versatile` (decommissioned) → `llama-3.3-70b-versatile` (not found) → `openai/gpt-oss-120b` (current, ~1.4s latency)

### Phase 3 — Dataset Scaling & Profiling
- ✅ Scaled `generate_patients(scale_factor=10)` from 10 to 100 patients
- ✅ Added `latency_ms` and `tokens_used` fields to track API performance per evaluation

### Phase 4 — Automated Testing & CI
- ✅ Created `backend/test_agent.py` — unit tests for LangGraph nodes
- ✅ Created `backend/test_api.py` — integration tests for all REST endpoints
- ✅ Tests include JWT authentication headers and RBAC access control checks
- ✅ Created `.github/workflows/python-app.yml` — GitHub Actions CI pipeline

### Phase 5 — Role-Based Access Control (RBAC) & Auth
- ✅ Implemented JWT authentication with `python-jose` and `passlib[bcrypt]`
- ✅ Created `backend/auth.py` with `get_current_user()` and `require_role()` FastAPI dependencies
- ✅ Created `backend/database.py` — SQLAlchemy engine + session factory
- ✅ Created `backend/models_db.py` — ORM models: `User`, `PatientDB`, `ObservationDB`, `EscalationDB`
- ✅ Seeded default users: doctor, nurse, admin (password: `password123`)
- ✅ Added `/api/login` endpoint returning JWT + role
- ✅ Protected `/api/escalations/{id}/approve` and `reject` with `require_role(["Doctor"])`
- ✅ Updated frontend with login screen, JWT localStorage, conditional UI per role

### Phase 6 — Full Database Persistence
- ✅ Removed all in-memory Python dictionaries (`patients_db`, `escalations_db`)
- ✅ On startup: seeded 100 synthetic patients + all observations into SQLite
- ✅ Rewrote all API endpoints to use SQLAlchemy DB session
- ✅ Created mapper functions: `patient_db_to_pydantic()`, `esc_db_to_pydantic()`
- ✅ All data survives server reboots

### Phase 7 — Dockerization
- ✅ Created `backend/Dockerfile` (Python 3.10-slim + build-essential for ChromaDB)
- ✅ Created `frontend/Dockerfile` (Node 18 + Next.js)
- ✅ Created `docker-compose.yml` orchestrating both services
- ✅ **Fixed:** `NEXT_PUBLIC_API_BASE` points to `http://backend:8000` (Docker service name, not localhost)
- ✅ **Fixed:** Named volume for SQLite DB, ChromaDB volume mount

### Phase 8 — Security & Code Audit
Comprehensive audit identified 16 issues; all resolved:
- ✅ **Critical:** `SECRET_KEY` now raises `RuntimeError` if not set (no insecure fallback)
- ✅ **Critical:** Hardcoded `/Users/bennish/...` path in `vector_store.py` → replaced with `os.path.dirname(__file__)` relative path + env override
- ✅ **Critical:** Token expiry bug — was using 15-min fallback instead of the configured 24h constant
- ✅ **Critical:** Pydantic v1/v2 compatibility — fully migrated to `model_dump_json()` / `model_validate_json()`
- ✅ **Critical:** `on_startup` lacked `try/except` — added rollback on failure
- ✅ **Critical:** `python-jose` missing from `requirements.txt`
- ✅ **Warning:** Deprecated `@app.on_event("startup")` → replaced with modern `lifespan` context manager
- ✅ **Warning:** CI pipeline missing `python-jose`, `SECRET_KEY` env var
- ✅ **Warning:** Duplicate import in `models.py`
- ✅ **Warning:** Docker `localhost` networking bug
- ✅ **Warning:** Frontend hardcoded API URL — now reads `process.env.NEXT_PUBLIC_API_BASE`
- ✅ **Info:** Created `.gitignore` protecting `.env`, `*.db`, `chroma_db/`, `node_modules/`

### Phase 9 — Bug Fixes (Runtime)
- ✅ **Fixed:** `clinician_notes` ValidationError — was `str=""` but DB column is `NULL` for pending escalations. Changed to `Optional[str] = None`
- ✅ **Fixed:** CORS errors caused by 500 crashes on `/api/escalations` (symptom of above bug)
- ✅ **Fixed:** Groq model `llama-3.1-70b-versatile` decommissioned → updated to current available model
- ✅ **Fixed:** `SECRET_KEY` added to `.env` to prevent `RuntimeError` on startup

### Phase 10 — Patient Risk Level Persistence & UI
- ✅ Added `risk_level` column to `PatientDB` SQLAlchemy model
- ✅ Backend `POST /api/evaluate/{id}` now writes the AI's risk level back to the patient's DB record
- ✅ `patient_db_to_pydantic()` now includes `risk_level` in the API response
- ✅ Added `risk_level: Optional[str]` to the `Patient` Pydantic model
- ✅ Frontend fixed: was reading `patient.riskLevel` (camelCase) but API returns `patient.risk_level` (snake_case)

### Phase 11 — Frontend Overhaul (Current)
- ✅ **Working navigation:** OVERVIEW, PATIENTS, INBOX, METRICS sidebar tabs now navigate between full views
- ✅ **Patient Detail View:** Clicking a patient shows full demographics, formatted vitals grid, nursing notes, vital trends, and escalation history
- ✅ **Vitals formatting:** HR shows "72 bpm", SpO2 shows "97.4%", BP shows "120/80 mmHg", Temp shows "36.8°C"
- ✅ **Vitals warnings:** Out-of-range vital signs highlighted in amber
- ✅ **Custom chart tooltip:** Formatted with units instead of raw floats
- ✅ **Chart legend:** Lines now labeled (Heart Rate, Systolic BP, SpO2)
- ✅ **Inbox view:** Full escalation list with ALL escalations (pending + resolved), shows resolved timestamp, recommended action, NEWS2 score, latency
- ✅ **Metrics view:** Risk distribution bar chart, total/evaluated counts, AI vs. baseline performance comparison
- ✅ **Patient search:** Filter by name or bed number in Patients view
- ✅ **Escalation history on patient:** Per-patient escalation timeline shown in detail view
- ✅ **Loading state:** "EVALUATING..." button state while AI runs
- ✅ **Chart Reference Line Overlap Fix:** Shifted threshold labels (`Tachycardia` and `Hypoxia`) to top-right/bottom-right alignments with vertical offsets (`dy`) to prevent text collision.
- ✅ **Footer:** Shows current role, patient count, pending escalations

---

## 9. Next Phase Implementation Roadmap & Completed Enhancements

### ✅ Phase 12 — Completed High-Priority Enhancements

1. **Automated Batch Evaluation Engine (`POST /api/evaluate/batch`)** — **COMPLETED**
   - Implemented a ward-wide evaluation engine that runs the Groq LLM graph across all 100 ward patients, updates DB risk ratings, and auto-generates escalations for High/Medium risk patients.
   - Added **`⚡ BATCH EVALUATE WARD`** button in the dashboard UI.

2. **Clinician Audit Trail & Event Logging (`audit_logs` DB Table)** — **COMPLETED**
   - Created `AuditLogDB` SQLAlchemy table recording logins, single & batch evaluations, escalation approvals/rejections, and report exports.
   - Added dedicated **`AUDIT LOGS`** tab in the Next.js sidebar.

3. **Clinical Handover Report Exporter (`GET /api/export/handover`)** — **COMPLETED**
   - Endpoint generates a JSON/CSV clinical handover report for all High & Medium risk patients containing latest vitals, nursing notes, and AI clinical recommendations.
   - Added **`📥 HANDOVER REPORT`** download button in the dashboard header.

---

### ✅ Phase 13 — ED Clinical Copilot Assistant (`POST /api/chat`) — **COMPLETED**

- **Project-Wide Dataset RAG Context:**
  - The chatbot has real-time access to the entire SQLite ward database. When queried about *"status of all assessed patients"* or *"which beds have high risk patients?"*, it pulls live data across all ward patients, bed numbers, risk levels, vital signs, and pending escalations.
- **Visual & Layperson-Friendly Plain-English Formatting:**
  - **Emoji Policy:** Kept emoji clutter to an absolute minimum, utilizing clean text markers (`[CRITICAL]`, `[WARNING]`, `[STABLE]`) for professional medical presentation.
  - Every vital sign reading is paired with a plain-English explanation (e.g. *HR > 90 bpm — Heart beating faster than normal*, *SBP < 100 mmHg — Blood pressure dropping*).
- **HTML Table Renderer & Markdown Parser:**
  - Integrated a custom markdown table parser into `page.js` that converts pipe tables (`| col | col |`) into clean, styled HTML `<table>` elements with dark row shading, borders, and crisp headers.
- **Polite Domain Guardrails (Silent Enforcement):**
  - If queried on non-clinical/off-topic subjects (e.g. *"what is Java?"*, coding, trivia), it responds naturally and politely:
    > *"I am your ED Clinical Copilot, designed specifically for ward deterioration monitoring, patient vitals analysis, NEWS2 scores, and clinical care guidelines. I can only assist with patient care and emergency department clinical questions."*
- **Clean UI & Responsive Layout Fixes:**
  - Renamed to **`💬 CLINICAL COPILOT`**.
  - Fixed markdown table text overflows (`overflow-x: auto`, `word-break: break-word`, custom bold inline text renderer).
- **Audit Integration:** All chatbot interactions are logged to `audit_logs` under action `"AI_CHAT_QUERY"`.

---

### ✅ Phase 14 — Expanded Dataset & Evaluation Corpus — **COMPLETED**
- **Expanded Archetypes**: Increased synthetic patient generator from 4 to 8 diverse clinical archetypes (Stable, Obvious Deterioration, Sepsis Trajectory, Severe Missing Data, Silent Hypoxia, Compensated Shock, Drug-Induced Bradycardia, Elderly Frail).
- **Scale Factor**: Increased scale factor to generate 170+ synthetic patients, meeting evaluator requirements for a larger corpus.
- **RAG Updates**: Added 10 new clinical guidelines to `vector_store.py` to cover the new archetypes.
- **Experiment Runner**: Updated `experiment.py` to compute per-archetype metrics (Precision, Recall/Sensitivity, Specificity, F1 Score, False Alert Rate).

### ✅ Phase 15 — Automated Testing Suite (CI/CD) — **COMPLETED**
- **LangGraph Unit Tests**: Expanded `test_agent.py` to 20 unit tests, isolating each LangGraph node and verifying threshold logic, NEWS2 scoring, and trend detection (including Silent Hypoxia SpO2 drops).
- **API Integration Tests**: Expanded `test_api.py` to 14 tests covering all REST endpoints, RBAC constraints (Nurse cannot approve), and Chatbot domain filtering.
- **CI Pipeline**: Updated `.github/workflows/python-app.yml` with Python 3.10/3.11 matrix, pip caching, and `flake8` linting.

### ✅ Phase 16 — Latency Profiling & Performance Dashboard — **COMPLETED**
- **Per-Node Profiling**: Implemented `time.perf_counter()` inside every LangGraph node in `agent.py`, recording latency breakdown into state.
- **Performance API**: Added `GET /api/performance` in `main.py` using a high-performance in-memory `deque` (ring buffer) to track the last 100 evaluation latencies, tokens used, and Groq success rates.
- **Frontend Dashboard**: Integrated a new visual "Latency Profiling (AVG)" bar chart and performance stats (P95 latency, Tokens/Eval, Success Rate) into the Metrics tab in `page.js`.

### ✅ Phase 17 — Security Hardening — **COMPLETED**
- **Rate Limiting**: Integrated `slowapi` to enforce strict rate limits on `/api/login` (max 10 requests/minute per IP) to prevent brute-force attacks on clinical credentials.

---

### ✅ Phase 18 — WebSockets for Real-Time Vital Sign Streaming (`/ws/vitals`) — **COMPLETED**
- Replaced 10-second polling (`setInterval`) with a persistent WebSocket connection pushing live vital sign observations to the UI.
- Implemented `live_vitals_simulator` background task in `main.py` that periodically simulates vital drifts and pushes data to the UI.

### ✅ Phase 19 — Automatic Threshold Trigger Rules (Hybrid Rule + AI) — **COMPLETED**
- Added auto-trigger rules in the simulator: Auto-trigger AI evaluations immediately when vitals cross critical limits (e.g. SpO2 < 88% or HR > 130 bpm).
- If the AI confirms High or Medium risk, it generates a `NEW_ESCALATION` WebSocket event, triggering instant UI alerts.

### ✅ Phase 20 — Admin User Management UI (`/admin/users`) — **COMPLETED**
- Implemented CRUD API endpoints (`GET`, `POST`, `DELETE` `/api/admin/users`) protected by `require_role(["Admin"])`.
- Added a dedicated "ADMIN PANEL" tab in the Next.js UI, allowing administrators to add or remove clinicians from the system.

---

## 10. File Structure

```
COE-PROJECT/
├── .github/workflows/python-app.yml  # CI pipeline
├── .gitignore                         # Protects .env, *.db
├── docker-compose.yml                 # Orchestrates backend + frontend
├── backend/
│   ├── .env                          # GROQ_API_KEY, SECRET_KEY (never commit)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                        # FastAPI app, all endpoints
│   ├── agent.py                       # LangGraph AI pipeline
│   ├── auth.py                        # JWT + RBAC
│   ├── baseline.py                    # NEWS2 scoring
│   ├── database.py                    # SQLAlchemy engine + session
│   ├── dataset.py                     # Synthetic patient generator + guidelines
│   ├── experiment.py                  # AI vs baseline comparison runner
│   ├── models.py                      # Pydantic API models
│   ├── models_db.py                   # SQLAlchemy ORM models
│   ├── vector_store.py                # ChromaDB RAG store
│   ├── test_agent.py                  # Unit tests
│   └── test_api.py                    # Integration tests
└── frontend/
    ├── Dockerfile
    └── src/app/
        ├── page.js                    # Full dashboard SPA
        ├── page.module.css            # Dark theme styles
        └── globals.css
```

---

### ✅ Phase 21 — Final Audit & Hardening — **COMPLETED**
- **Auth:** `/api/patients*`, `/api/evaluate/{id}`, `/api/escalations`, `/api/metrics` and `/ws/vitals` now require a valid JWT (WebSocket via `?token=`).
- **Rate limiting:** login limiter rewritten with slowapi's `@limiter.limit` (the previous `limiter.check` call does not exist and would have returned 429 for every login once slowapi was installed).
- **Chatbot guardrail:** off-topic filter matches whole words only (previously "cardiac care" / "who is the highest risk patient" were refused).
- **Escalations:** re-evaluating a patient no longer stacks duplicate pending escalations; approve/reject return 409 if already resolved; unknown patient returns 404.
- **Admin:** role restricted to Doctor/Nurse/Admin, minimum password length 8.
- **Simulator:** LangGraph call moved off the event loop, risk level is always committed, observation history capped at 30 per patient.
- **Profiling:** batch evaluations now record latency/tokens (shared `run_evaluation` helper).
- **Frontend:** `Unknown` risk gets its own badge/filter/chart bar; hard-coded fake metric fallbacks (92% / 60% / +32%) replaced with `--`; stray `0` in inbox cards fixed; any 401 returns to login.
- **Docker/ops:** Node 22 image, `NEXT_PUBLIC_API_BASE` passed as a build arg, SQLite/Chroma stored in a directory volume (`DATABASE_URL`, `CHROMA_DB_PATH`), `.dockerignore` files, `boot.sh` no longer overrides the real Groq key, `bcrypt` pinned for passlib compatibility.
- **Tests:** API tests use an isolated temp DB and run the app lifespan (they previously only passed against a pre-seeded local DB); 42 tests pass offline.

---

### ✅ Phase 22 — Concurrency, Honest Benchmark & Component Frontend — **COMPLETED**
- **Background batch evaluation:** `POST /api/evaluate/batch` now returns `202` with a job; `GET /api/evaluate/batch/{job_id}` reports `completed/total` and the final result (evaluated, per-risk counts incl. `unknown_risk_count`, `failed_count`, escalations created). Patients are evaluated on a worker pool (`BATCH_WORKERS`, default 8); a second click joins the running job. The dashboard shows live progress.
- **Groq rate-limit guard (`llm_limits.py`):** all LLM calls share a rolling 60 s token budget (`GROQ_TPM_LIMIT`, default 8000 = free tier) and retry 429s after the cool-down Groq asks for. Previously concurrent evaluation produced 429s that were recorded as failed evaluations. Set `GROQ_TPM_LIMIT` higher on a paid tier to evaluate faster.
- **Real token accounting:** `tokens_used` now comes from Groq's usage metadata (0 when no LLM call was made) instead of a character-count guess. `gpt-oss` reasoning effort is configurable (`GROQ_REASONING_EFFORT`, default `medium`; `low` saves ~3x output tokens but sometimes skips the structured-output tool call, which is retried).
- **Shared Chroma client:** the vector store caches its client, embedding model and collection (thread-safe) instead of rebuilding them on every query.
- **Benchmark (`experiment.py`) rewritten:** evaluates the development archetypes **and** a randomised hold-out set (`dataset.generate_holdout_patients`: different archetypes, noise and note wording, with hard negatives such as anxious tachycardia, settling fever, chronic COPD). Reports detection rate with 95% Wilson intervals, false-alert rate, precision, F1 per archetype, plus an `ai_strict` operating point that does not count `Unknown` as a detection. Evaluations whose LLM call failed are excluded and listed under `llm_failures` instead of counting as detections. Refuses to run without `GROQ_API_KEY`, loads `.env`, and records model/config in the results file. Run with `python experiment.py [--dev-scale N]`.
- **Frontend split:** the 1,500-line `page.js` is now a 90-line composition of `hooks/` (`useAuth`, `useWard`) and `components/` (views, chat, charts, shared `EscalationCard`/`RiskBadge`), with CSS classes instead of inline styles.
- **Responsive layout:** breakpoints at 1200 / 900 / 520 px — sidebar becomes a scrollable top nav on tablets/phones, grids collapse, tables scroll horizontally, chat becomes a bottom sheet. No horizontal page scroll down to 375 px.
- **UI behaviour:** live-feed auto-reconnect and status indicator, header reports whether the LLM is actually enabled (`/api/health.llm_enabled`), accessible nav buttons, delete-user confirmation, own-account delete disabled, metrics panel shows hold-out vs dev results with confidence intervals.
- **Tests:** 46 tests (batch job lifecycle, throttle, 429 parsing added); `conftest.py` exits cleanly after pytest's summary to avoid an intermittent onnxruntime abort (exit 134) at interpreter teardown.

---

### ✅ Phase 23 — Review 2 Feedback: Error Boundaries, Documentation, Complete Benchmark — **COMPLETED**
- **Error boundaries:** frontend per-view `catchError` boundaries (`ViewBoundary`), `error.js`, `global-error.js`, `not-found.js`; backend `error_boundary_middleware` returning a generic JSON 500 with `request_id`/`X-Request-ID` while preserving CORS headers. Verified by forcing a render crash (only the Metrics view failed) and by two new API tests.
- **Documentation:** root `README.md` (setup, configuration, architecture, full API table with access levels, database schema, granular test inventory, error-handling matrix, security summary, evaluation limits); docstrings added to every backend module, class and function.
- **Tests:** 50 passing (26 unit, 24 integration).
- **Benchmark (complete, 0 LLM failures):** hold-out sensitivity 100 % (CI 91–100) vs NEWS2 62.5 % (47–76), false-alert rate 25 % vs 0 %, F1 88.9 % vs 76.9 %. Known weakness: 90 % false alerts on chronic-COPD baseline patients.

