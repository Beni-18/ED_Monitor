# ED Deterioration Monitor — Review 3 Phase Report

**Project:** AI-assisted ward deterioration monitoring for an Emergency Department (COE project)
**Author:** Bennish Christopher  **Review:** 3  **Date:** 27 October 2026
**Repository:** https://github.com/Beni-18/ED_Monitor  (see `README.md` for setup, API and schema documentation)

---

## 1. Abstract

The ED Deterioration Monitor is a clinical decision-support prototype that detects patients whose condition is worsening in ways a threshold-based early-warning score misses. It runs a five-node LangGraph pipeline that combines the NEWS2 score, a rule-based trend analysis, retrieval-augmented generation (RAG) over 25 clinical guidelines stored in ChromaDB, and a Groq-hosted LLM (`openai/gpt-oss-120b`) returning schema-validated output. Flagged patients are routed to a role-based clinician inbox; every action is written to an audit log; vital signs and alerts stream to the browser over WebSockets. At Review 3 all planned modules are implemented and the system has been evaluated against a NEWS2 baseline on a randomised hold-out set. On 80 hold-out patients the agent reached 100 % sensitivity (95 % CI 91–100 %) versus 62.5 % (47–76 %) for NEWS2, at the cost of a 25 % false-alert rate versus 0 %. All data are synthetic; the system is a research prototype and not a medical device.

## 2. Review 2 feedback and corrections made

| Review 2 feedback | Correction implemented | Where to verify |
|---|---|---|
| Provide more granular technical documentation on **unit testing** | Test suite expanded to 50 tests (26 unit, 24 integration); `README.md` §5 lists every test group, what it verifies, how isolation works (temp SQLite DB, app lifespan, offline fallback) and what is *not* covered | `README.md` §5; `backend/test_agent.py`, `backend/test_api.py`, `backend/conftest.py` |
| Document **error boundaries** | Frontend: per-view `catchError` boundaries (`ViewBoundary`), route-level `error.js`, root `global-error.js`, `not-found.js`. Backend: `error_boundary_middleware` converts unhandled exceptions to a generic JSON 500 with `request_id`/`X-Request-ID` (no stack trace, CORS headers preserved). LLM failures are contained as `Unknown`/confidence 0.0. Documented in a failure-mode table | `README.md` §6; `frontend/src/components/ViewBoundary.js`, `frontend/src/app/error.js`, `backend/main.py`; tests `test_unhandled_error_returns_generic_json_500_with_cors`, `test_validation_errors_are_422_not_500` |
| Document **API endpoints** in the README | Root `README.md` with all 20 REST endpoints and the WebSocket, including method, path, required role and behaviour (status codes 202/401/403/404/409/422/429) | `README.md` §3 |
| Document the **database schema** in the README | Five-table schema, relationships, cascade rules, JSON snapshot design and audited action list | `README.md` §4; `backend/models_db.py` |
| **Expand code comments** | Docstrings added to every previously undocumented backend module, class and function; algorithm thresholds stated in node docstrings | `backend/*.py` |

Verification of the frontend boundary: a corrupted metrics payload was served deliberately; only the Metrics view displayed the failure message, navigation, statistics and chat stayed functional, and switching tabs recovered the view.

## 3. Problem statement and objectives

**Problem.** Threshold scores such as NEWS2 miss early or atypical deterioration: slow blood-pressure decline with compensatory tachycardia (occult bleeding), falling SpO2 within "acceptable" ranges, hypothermic sepsis, drug-induced bradycardia, and patients whose vitals could not be measured. Missing measurements contribute 0 to NEWS2, so the sickest patients can score lowest.

**Objectives.**
1. Detect deterioration from trends and nursing notes, not only absolute values.
2. Quantify detection against a NEWS2 baseline with confidence intervals on unbiased data.
3. Treat missing data as risk, never as normal.
4. Give clinicians explainable recommendations with retrieved guideline evidence.
5. Enforce role-based access, a human-in-the-loop decision, and a full audit trail.
6. Operate reliably under LLM rate limits and API failures.

## 4. Methodology and system architecture

```
Next.js 16 / React 19 ──REST + WebSocket──► FastAPI ──► SQLite (SQLAlchemy)
 hooks · views · error boundaries            │  JWT/RBAC · rate limit · batch jobs · simulator
                                             └─► LangGraph agent ─► ChromaDB (25 guidelines)
                                                                └─► Groq LLM (token-budget guarded)
```

**Agent pipeline** (`backend/agent.py`): `assess_missing_data` → (risk ≥ 8: fast-track) or `compute_baseline` → `retrieve_context` → `analyze_trends` → `generate_recommendation`. Each node records its latency in `node_timings`.

**Evaluation method** (`backend/experiment.py`): the agent and NEWS2 (score ≥ 5) are run on two sets, with ground truth fixed by how each trajectory was constructed. Metrics: sensitivity with a 95 % Wilson interval, false-alert rate, precision, F1, per-archetype breakdown, and a stricter operating point that does not count `Unknown` as a detection. Evaluations whose LLM call failed are excluded and listed, never counted as detections.

## 5. Implemented modules

| Module | Implementation |
|---|---|
| API (`main.py`) | 20 REST endpoints + 1 WebSocket; OAuth2 password login; Pydantic validation; startup seeding of users and 170 patients; audit logging helper |
| Agent (`agent.py`) | LangGraph `StateGraph` with conditional routing; Groq structured output (`AgentRecommendation`); rule-based fallback without a key; domain-restricted Clinical Copilot |
| NEWS2 baseline (`baseline.py`) | RR, SpO2 (scale 1), systolic BP, HR, temperature and AVPU scoring; High ≥ 7, Medium ≥ 5, Low otherwise |
| LLM guard (`llm_limits.py`) | Shared rolling 60-s token budget (8,000 TPM default, 80 % utilisation), reservation replaced by real usage, 429 cool-down parsing, `tool_use_failed` retry, fail-fast above 30 s |
| RAG (`vector_store.py`) | Thread-safe cached ChromaDB client, embedding function and collection; rebuild when the guideline count changes |
| Data (`dataset.py`) | 170-patient development corpus (8 archetypes) and an 80-patient randomised hold-out set (8 archetypes incl. hard negatives); 25 guidelines |
| Auth (`auth.py`) | HS256 JWT (24 h), bcrypt hashes, `require_role` dependency |
| Persistence | `users`, `patients`, `observations`, `escalations` (JSON recommendation snapshot), `audit_logs` |
| Frontend | 18 components, 2 hooks (`useAuth`, `useWard`), responsive CSS (breakpoints 1200/900/520 px), 6 views + chat widget |
| Tests / CI | 50 pytest tests; GitHub Actions (flake8 + pytest, Python 3.10/3.11) |

Code size: backend source 2,822 lines, backend tests 750, frontend 1,552 lines of JS.

## 6. Algorithms

- **Missing-data risk:** `1.5 × (missing vitals of 7) + 3 (unconscious) + 2 (distressed)`, capped at 10. ≥ 8 skips straight to recommendation; ≥ 7 yields `Unknown` without calling the LLM.
- **Trend analysis:** comparing first and last observation, HR ↑ ≥ 10, SpO2 ↓ ≥ 2, systolic BP ↓ ≥ 10 and RR ↑ ≥ 4 each count as worsening. Deteriorating if ≥ 2 worsen or SpO2 falls ≥ 4 alone (silent hypoxia). Two-observation fallback uses HR > +5 or SpO2 < −1.
- **Retrieval:** nursing notes (plus incomplete-history and distress flags) are embedded and matched to the top-3 guidelines by semantic similarity; they are passed to the LLM as evidence.
- **Structured generation:** `with_structured_output(AgentRecommendation, include_raw=True)` returns risk level, confidence, reasoning, recommended action, and real token usage from Groq metadata.
- **Failure containment:** an LLM error becomes `Unknown`, confidence 0.0, "manual review required" — never a silent verdict.
- **Rate-limit control:** a rolling token budget gates every call; after a call the reservation is replaced with actual usage; `Retry-After` hints are parsed from 429 responses.
- **Evaluation statistics:** Wilson score interval for sensitivity.

## 7. Workflows

1. **Login** → JWT stored client-side; the WebSocket authenticates with `?token=`.
2. **Live monitoring:** while a client is connected a background task appends a drifted observation to a random patient every 5 s and pushes `VITAL_UPDATE`. If SpO2 < 88, HR > 130 or SBP < 90 the agent is triggered; High/Medium results create one pending escalation and push `NEW_ESCALATION` (observations capped at 30 per patient).
3. **Single evaluation:** `POST /api/evaluate/{id}` → agent → risk persisted → escalation created for High/Medium/Unknown (duplicates refreshed, not stacked).
4. **Ward batch:** `POST /api/evaluate/batch` returns `202` and a job id; a thread pool evaluates patients; the UI polls `completed/total`; results, escalations and one audit entry are written on a single DB session.
5. **Escalation review:** only a Doctor can approve or reject (409 if already resolved); notes and timestamp are stored and audit-logged.
6. **Handover export:** JSON report of all High/Medium patients with latest vitals, notes, AI reasoning and NEWS2.
7. **Clinical Copilot:** whole-word keyword pre-filter, then a domain-restricted system prompt with ward context from the database; every query is audit-logged.

## 8. Features by role

| Feature | Doctor | Nurse | Admin |
|---|---|---|---|
| View patients, vitals trends, metrics, audit log | ✔ | ✔ | ✔ |
| Run single / batch AI evaluation, export handover, use Copilot | ✔ | ✔ | ✔ |
| Approve / reject escalations | ✔ | ✘ (403) | ✘ (403) |
| Create / delete users | ✘ | ✘ | ✔ (cannot delete self) |

Additional capabilities: live vitals chart, patient directory with search and risk filter, escalation inbox with status filters, benchmark panel (hold-out vs development with confidence intervals and per-archetype table), latency/token profiling, automatic WebSocket reconnect, header indicator of whether the LLM is enabled.

## 9. Security measures

JWT authentication on every data route and the WebSocket; role-based access control; bcrypt password hashing; login limited to 10 requests/min/IP (429); server refuses to start without `SECRET_KEY`; input validation (role whitelist, minimum password length 8); generic error responses with request ids; secrets and databases gitignored; admin cannot delete their own account; dependency audit clean (`npm audit`: 0 vulnerabilities after upgrading Next.js to 16.4.3; `pip check` clean). **Known gaps:** tokens in `localStorage` without server-side revocation, CORS allows any origin, seeded demo credentials, audit log immutability is by convention only.

## 10. Testing

50 automated tests, all passing (three consecutive runs, exit code 0), flake8 clean. Unit tests (26) cover each agent node, routing thresholds, NEWS2 scoring, trend rules and the LLM rate-limit guard (budget blocking, settlement, `Retry-After` parsing, `tool_use_failed` retry, fail-fast on long waits). Integration tests (24) cover authentication, RBAC (403 for Nurse/Admin approval), 401 on every protected route, escalation lifecycle and de-duplication, 409/404/422 handling, background batch jobs, admin user management, rate limiting, WebSocket authentication, chatbot guard (including clinical terms that contain off-topic substrings), and the backend error boundary. Tests are hermetic (temporary database, no API key). Frontend behaviour was verified manually in a browser at 1280, 768 and 375 px; there are no automated frontend tests.

## 11. Results

**System metrics.** 170-patient development corpus and 80-patient hold-out set; 25 guidelines; 20 REST endpoints + WebSocket; 50 tests; offline pipeline latency (no LLM, 60 patients) mean 91 ms, median 96 ms, p95 114 ms, of which ≈ 100 ms is retrieval; ward batch of 170 patients offline in 15–19 s with 8 workers. Live-LLM latency was only spot-checked (≈ 1.0 s at low and 1.8–2.4 s at medium reasoning effort) and is not benchmarked systematically.

**Benchmark** (complete run, 27 Oct 2026; model `gpt-oss-120b`, reasoning effort medium; 0 LLM failures):

| Set | Metric | NEWS2 ≥ 5 | AI agent |
|---|---|---|---|
| **Hold-out (n = 80)** | Sensitivity (95 % CI) | 62.5 % (47–76) | **100 %** (91–100) |
| | False-alert rate | 0 % | 25 % |
| | Precision / F1 | 100 % / 76.9 % | 80.0 % / 88.9 % |
| Development (n = 34) | Sensitivity (95 % CI) | 38.5 % (22–57) | 100 % (87–100) |
| | False-alert rate | 0 % | 0 % |
| | Precision / F1 | 100 % / 55.6 % | 100 % / 100 % |

Hold-out sensitivity by archetype (AI vs NEWS2): occult bleed 100 % vs 10 %; overdose 100 % vs 70 %; respiratory decline 100 % vs 80 %; atypical sepsis 100 % vs 90 %. Hold-out false alerts (AI vs NEWS2): chronic-COPD baseline 90 % vs 0 %; well/fit 10 % vs 0 %; anxious and settling-fever 0 % for both. Counting `Unknown` as a non-detection lowers development sensitivity to 84.6 %; hold-out is unchanged.

**Interpretation.** The agent detects deteriorations NEWS2 misses, most clearly occult bleeding, but over-alerts on patients with a chronically low SpO2 baseline. The development result is an upper bound because the agent and guidelines were tuned on those templates; the hold-out figure is the one to cite.

**Threats to validity.** All data are synthetic and labelled by construction; sample sizes are small (wide intervals); the NEWS2 baseline omits the supplemental-oxygen item and SpO2 scale 2, so it is not the full specification; a single LLM and prompt were evaluated.

## 12. Implementation status

**Completed and verified**
- LangGraph pipeline with RAG, trend analysis, NEWS2 baseline, structured LLM output and rule-based fallback.
- JWT authentication, RBAC, login throttling, audit logging, admin user management.
- REST API (20 endpoints), WebSocket live feed with auto-triggered evaluation and escalation.
- Background batch evaluation with progress; LLM token-budget guard; real token accounting.
- Responsive Next.js dashboard (overview, patients, inbox, metrics, audit log, admin, Copilot) with error boundaries.
- Benchmark harness with hold-out set, confidence intervals and failure exclusion; complete results recorded.
- Documentation (README, API, schema, tests, error handling), 50 passing tests, CI workflow, Docker configuration.

**Current limitations**
- Synthetic data only; no clinical validation.
- The vitals feed is simulated (random drift), not connected to monitoring devices.
- 25 % hold-out false-alert rate; COPD-baseline weakness.
- Docker configuration has not been built or run end to end.
- No automated frontend tests; SQLite only; demo credentials seeded.

**Future enhancements**
- Baseline-aware scoring (NEWS2 SpO2 scale 2 / patient-specific baselines) to cut COPD false alerts.
- Validation on de-identified real or public datasets (e.g. MIMIC-IV) and larger samples.
- Integration with HL7/FHIR feeds and bedside devices in place of the simulator.
- httpOnly-cookie sessions with server-side revocation, restricted CORS, SSO.
- Database migrations (Alembic) and PostgreSQL; tamper-evident audit log.
- Frontend component and end-to-end tests; load testing; systematic LLM latency benchmarking.

## 13. Conclusion

All modules planned for this phase are implemented and covered by documentation, automated tests and a complete, honestly reported evaluation. The Review 2 feedback has been addressed with concrete changes in code and documentation. The central result — higher sensitivity than NEWS2 with a quantified false-alert cost — is supported by a randomised hold-out experiment, with its limitations stated. The remaining work is validation on real data and production hardening.
