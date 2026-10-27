"""
main.py — FastAPI Backend for ED Deterioration Monitor

Endpoints:
  POST /api/login              — OAuth2 login, returns JWT + role
  GET  /api/health             — Health check (no auth required)
  GET  /api/patients           — List all patients
  GET  /api/patients/{id}      — Get single patient with observations
  GET  /api/patients/{id}/observations — Get time-series observations
  POST /api/evaluate/{id}      — Run AI evaluation on single patient
  POST /api/evaluate/batch     — Start background AI evaluation of the whole ward (202 + job)
  GET  /api/evaluate/batch/{id} — Poll batch job progress/result
  GET  /api/escalations        — List all escalations
  POST /api/escalations/{id}   — Create escalation from evaluation result
  PATCH /api/escalations/{id}/approve — Doctor: approve escalation
  PATCH /api/escalations/{id}/reject  — Doctor: reject escalation
  GET  /api/audit-logs         — Immutable audit trail (auth required)
  GET  /api/export/handover    — Download handover JSON report
  POST /api/chat               — Clinical Copilot chatbot (auth required)
  GET  /api/metrics            — System metrics + AI performance
  GET  /api/performance        — LangGraph node latency profiling
"""
import json
import logging
import uuid
import os
import random
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import datetime

import asyncio
from fastapi import FastAPI, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    RATE_LIMITING_AVAILABLE = False
    print("[WARNING] slowapi not installed. Rate limiting is disabled.")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from dataset import generate_patients
from vector_store import initialize_vector_store
from agent import app as agent_app, clinical_chat_assistant
from models import (
    AgentRecommendation, Escalation, Patient, PatientObservation,
    VitalSigns, ChatMessageRequest,
    ChatMessageResponse
)
from database import engine, Base, SessionLocal, get_db
from models_db import User, PatientDB, ObservationDB, EscalationDB, AuditLogDB
from auth import get_password_hash, verify_password, create_access_token, require_role, get_current_user, get_user_from_token
from fastapi.security import OAuth2PasswordRequestForm

# ─────────────────────────────────────────────────────────────────────────────
# PERFORMANCE METRICS RING BUFFER
# Stores the last 100 evaluation timing records in memory for the
# /api/performance endpoint. Uses deque for O(1) append/pop.
# ─────────────────────────────────────────────────────────────────────────────
_performance_buffer: deque = deque(maxlen=100)

EXPERIMENT_RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiment_results.json")
MAX_OBSERVATIONS_PER_PATIENT = 30

# ─────────────────────────────────────────────────────────────────────────────
# WEBSOCKET CONNECTION MANAGER
# ─────────────────────────────────────────────────────────────────────────────
class ConnectionManager:
    """Tracks connected /ws/vitals clients and fans out JSON events (VITAL_UPDATE, NEW_ESCALATION) to all of them."""
    def __init__(self):
        """Start with no connected WebSocket clients."""
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept the WebSocket handshake and register the client."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Forget a client (safe to call twice)."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Send `message` to every client; clients whose socket has died are dropped."""
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITER SETUP (slowapi)
# ─────────────────────────────────────────────────────────────────────────────
if RATE_LIMITING_AVAILABLE:
    limiter = Limiter(key_func=get_remote_address)
    login_rate_limit = limiter.limit("10/minute")
else:
    limiter = None

    def login_rate_limit(func):
        return func

# Create tables
Base.metadata.create_all(bind=engine)


def log_audit_event(db: Session, username: str, role: str, action: str, details: str):
    """Immutable audit logging — all clinical events are recorded here."""
    try:
        log_entry = AuditLogDB(
            timestamp=datetime.now(),
            username=username,
            role=role,
            action=action,
            details=details
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[AUDIT LOG ERROR] Failed to record audit event: {e}")


def patient_db_to_pydantic(p: PatientDB) -> Patient:
    """Map a PatientDB row (with its observations, sorted by timestamp) to the API/agent `Patient` model."""
    obs_list = []
    for obs in sorted(p.observations, key=lambda o: o.timestamp):
        obs_list.append(PatientObservation(
            patient_id=obs.patient_id,
            timestamp=obs.timestamp,
            vitals=VitalSigns(
                hr=obs.hr,
                bp_systolic=obs.bp_systolic,
                bp_diastolic=obs.bp_diastolic,
                resp_rate=obs.resp_rate,
                temp=obs.temp,
                spo2=obs.spo2,
                consciousness_level=obs.consciousness_level
            ),
            nursing_notes=obs.nursing_notes,
            is_incomplete_history=obs.is_incomplete_history,
            is_unconscious=obs.is_unconscious,
            is_distressed=obs.is_distressed
        ))
    return Patient(
        patient_id=p.id,
        name=p.name,
        bed_number=p.bed_number,
        admission_time=p.admission_time,
        observations=obs_list,
        risk_level=p.risk_level
    )


def esc_db_to_pydantic(e: EscalationDB) -> Escalation:
    """Map an EscalationDB row to the API model, parsing the stored recommendation JSON snapshot."""
    return Escalation(
        id=e.id,
        patient_id=e.patient_id,
        recommendation=AgentRecommendation.model_validate_json(e.recommendation_json),
        status=e.status,
        clinician_notes=e.clinician_notes,
        created_at=e.created_at,
        resolved_at=e.resolved_at
    )


async def live_vitals_simulator():
    """Generates new vitals periodically and triggers auto-escalations (Hybrid AI rules)."""
    while True:
        await asyncio.sleep(5)
        if not manager.active_connections:
            continue
        db = SessionLocal()
        try:
            # Pick a random patient
            patient_ids = [row[0] for row in db.query(PatientDB.id).all()]
            if not patient_ids:
                continue
            patient_id = random.choice(patient_ids)
            pdb = db.query(PatientDB).filter(PatientDB.id == patient_id).first()
            if not pdb:
                continue

            # Get their last obs
            last_obs = db.query(ObservationDB).filter(ObservationDB.patient_id == patient_id).order_by(ObservationDB.timestamp.desc()).first()
            if not last_obs:
                continue

            # Drift vitals slightly to simulate real-time changes
            new_hr = last_obs.hr + random.randint(-2, 3) if last_obs.hr else None
            new_spo2 = max(80, min(100, last_obs.spo2 + random.uniform(-1, 0.5))) if last_obs.spo2 else None
            new_sys = last_obs.bp_systolic + random.randint(-5, 5) if last_obs.bp_systolic else None

            odb = ObservationDB(
                patient_id=patient_id,
                timestamp=datetime.now(),
                hr=new_hr,
                bp_systolic=new_sys,
                bp_diastolic=last_obs.bp_diastolic,
                resp_rate=last_obs.resp_rate,
                temp=last_obs.temp,
                spo2=new_spo2,
                consciousness_level=last_obs.consciousness_level,
                nursing_notes="System auto-generated observation",
                is_incomplete_history=last_obs.is_incomplete_history,
                is_unconscious=last_obs.is_unconscious,
                is_distressed=last_obs.is_distressed
            )
            db.add(odb)
            db.commit()

            # Keep the observation history bounded so payloads don't grow forever
            all_ids = [row[0] for row in db.query(ObservationDB.id)
                       .filter(ObservationDB.patient_id == patient_id)
                       .order_by(ObservationDB.timestamp.desc()).all()]
            if len(all_ids) > MAX_OBSERVATIONS_PER_PATIENT:
                db.query(ObservationDB).filter(
                    ObservationDB.id.in_(all_ids[MAX_OBSERVATIONS_PER_PATIENT:])
                ).delete(synchronize_session=False)
                db.commit()

            # Broadcast new vital
            await manager.broadcast({
                "type": "VITAL_UPDATE",
                "patient_id": patient_id,
                "timestamp": odb.timestamp.isoformat(),
                "vitals": {
                    "hr": odb.hr,
                    "bp_systolic": odb.bp_systolic,
                    "spo2": odb.spo2,
                    "resp_rate": odb.resp_rate,
                    "temp": odb.temp
                }
            })

            # ─────────────────────────────────────────────────────────
            # AUTO-TRIGGER HYBRID RULES
            # ─────────────────────────────────────────────────────────
            needs_eval = (
                (new_spo2 is not None and new_spo2 < 88)
                or (new_hr is not None and new_hr > 130)
                or (new_sys is not None and new_sys < 90)
            )

            if needs_eval:
                db.refresh(pdb)
                patient = patient_db_to_pydantic(pdb)
                # The graph makes blocking LLM/embedding calls; keep the event loop free
                rec = await asyncio.to_thread(run_evaluation, patient)

                if rec.risk_level in ["High", "Medium"]:
                    pdb.risk_level = rec.risk_level
                    existing = db.query(EscalationDB).filter(
                        EscalationDB.patient_id == patient_id,
                        EscalationDB.status == "pending"
                    ).first()
                    if not existing:
                        db.add(EscalationDB(
                            id=str(uuid.uuid4()),
                            patient_id=patient_id,
                            recommendation_json=rec.model_dump_json(),
                            status="pending",
                            created_at=datetime.now()
                        ))
                    db.commit()
                    if not existing:
                        await manager.broadcast({
                            "type": "NEW_ESCALATION",
                            "patient_id": patient_id,
                            "risk_level": rec.risk_level
                        })

        except Exception as e:
            print(f"[SIMULATOR ERROR] {e}")
        finally:
            db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan context manager."""
    # Startup
    sim_task = asyncio.create_task(live_vitals_simulator())
    
    initialize_vector_store()
    db = SessionLocal()
    try:
        # Seed users
        if not db.query(User).first():
            users = [
                User(username="doctor", hashed_password=get_password_hash("password123"), role="Doctor"),
                User(username="nurse", hashed_password=get_password_hash("password123"), role="Nurse"),
                User(username="admin", hashed_password=get_password_hash("password123"), role="Admin")
            ]
            db.add_all(users)
            db.commit()
            print("Database seeded with default users (doctor, nurse, admin / password123)")

        # Seed patients — always re-seed if DB has fewer patients than expected
        # This handles the case where we expanded from 100 → 170 patients
        patient_count = db.query(PatientDB).count()
        patients_pydantic = generate_patients(scale_factor=10)
        expected_count = len(patients_pydantic)

        if patient_count == 0:
            # Fresh seed
            for p in patients_pydantic:
                pdb = PatientDB(id=p.patient_id, name=p.name, bed_number=p.bed_number, admission_time=p.admission_time)
                db.add(pdb)
                for obs in p.observations:
                    odb = ObservationDB(
                        patient_id=p.patient_id,
                        timestamp=obs.timestamp,
                        hr=obs.vitals.hr,
                        bp_systolic=obs.vitals.bp_systolic,
                        bp_diastolic=obs.vitals.bp_diastolic,
                        resp_rate=obs.vitals.resp_rate,
                        temp=obs.vitals.temp,
                        spo2=obs.vitals.spo2,
                        consciousness_level=obs.vitals.consciousness_level,
                        nursing_notes=obs.nursing_notes,
                        is_incomplete_history=obs.is_incomplete_history,
                        is_unconscious=obs.is_unconscious,
                        is_distressed=obs.is_distressed
                    )
                    db.add(odb)
            db.commit()
            print(f"Database seeded with {expected_count} synthetic patients across 8 clinical archetypes.")
        elif patient_count < expected_count:
            # Dataset was expanded — add new archetype patients
            print(f"Database has {patient_count} patients but {expected_count} are defined. Adding new archetypes...")
            existing_ids = set(row[0] for row in db.query(PatientDB.id).all())
            added = 0
            for p in patients_pydantic:
                if p.patient_id not in existing_ids:
                    pdb = PatientDB(id=p.patient_id, name=p.name, bed_number=p.bed_number, admission_time=p.admission_time)
                    db.add(pdb)
                    for obs in p.observations:
                        odb = ObservationDB(
                            patient_id=p.patient_id,
                            timestamp=obs.timestamp,
                            hr=obs.vitals.hr,
                            bp_systolic=obs.vitals.bp_systolic,
                            bp_diastolic=obs.vitals.bp_diastolic,
                            resp_rate=obs.vitals.resp_rate,
                            temp=obs.vitals.temp,
                            spo2=obs.vitals.spo2,
                            consciousness_level=obs.vitals.consciousness_level,
                            nursing_notes=obs.nursing_notes,
                            is_incomplete_history=obs.is_incomplete_history,
                            is_unconscious=obs.is_unconscious,
                            is_distressed=obs.is_distressed
                        )
                        db.add(odb)
                    added += 1
            db.commit()
            print(f"Added {added} new patients for expanded archetypes.")
        else:
            print(f"Database already contains {patient_count} patients.")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Startup seeding failed: {e}. Application will continue with existing data.")
    finally:
        db.close()

    yield  # Application runs here

    print("Application shutting down.")
    sim_task.cancel()


app = FastAPI(
    title="ED Deterioration Monitor API",
    description="AI-powered Emergency Department clinical decision support system",
    version="2.3.0",
    lifespan=lifespan
)

# Attach rate limiter if available
if RATE_LIMITING_AVAILABLE:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

logger = logging.getLogger("ed_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


# ─────────────────────────────────────────────────────────────────────────────
# BACKEND ERROR BOUNDARY
# Any exception not already turned into an HTTPException is logged with a request id and
# returned as a generic JSON 500 (no stack trace or internals leak to the client).
# This middleware is registered BEFORE CORSMiddleware so CORS wraps it: error responses
# still carry CORS headers, so the browser reports the real status instead of an opaque
# "CORS error" (the symptom of the original /api/escalations crash).
# ─────────────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def error_boundary_middleware(request: Request, call_next):
    """Log any unhandled exception and return a generic JSON 500 carrying an X-Request-ID."""
    request_id = uuid.uuid4().hex[:12]
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error [request_id=%s] %s %s", request_id, request.method, request.url.path)
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )
    response.headers["X-Request-ID"] = request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# WEBSOCKET ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
@app.websocket("/ws/vitals")
async def websocket_vitals_endpoint(websocket: WebSocket, token: str = ""):
    """Live feed. Requires ?token=<JWT>; closes with code 1008 if invalid. Server pushes events; client messages are ignored."""
    db = SessionLocal()
    try:
        user = get_user_from_token(token, db)
    finally:
        db.close()
    if user is None:
        await websocket.close(code=1008)
        return
    await manager.connect(websocket)
    try:
        while True:
            # We don't expect messages from the client right now, just keeping conn open
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)



# ─────────────────────────────────────────────────────────────────────────────
# AUTH ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/login")
@login_rate_limit
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    OAuth2 login endpoint. Rate-limited to 10 attempts/minute per IP to
    prevent brute-force attacks on clinical credentials.
    """
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": user.username})
    log_audit_event(db, user.username, user.role, "USER_LOGIN",
                    f"User {user.username} ({user.role}) authenticated successfully.")
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}


@app.get("/api/health")
def health_check():
    """Unauthenticated liveness probe; also reports whether a Groq key is configured (`llm_enabled`)."""
    return {"status": "ok", "version": "2.3.0", "llm_enabled": bool(os.environ.get("GROQ_API_KEY"))}

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN ENDPOINTS (USER MANAGEMENT)
# ─────────────────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    """Request body for creating a user: non-empty username, password >= 8 chars, role limited to Doctor/Nurse/Admin."""
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)
    role: Literal["Doctor", "Nurse", "Admin"]

@app.get("/api/admin/users")
def get_users(current_user: User = Depends(require_role(["Admin"])), db: Session = Depends(get_db)):
    """Admin only: list all users (id, username, role; never the password hash)."""
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "role": u.role} for u in users]

@app.post("/api/admin/users")
def create_user(user: UserCreate, current_user: User = Depends(require_role(["Admin"])), db: Session = Depends(get_db)):
    """Admin only: create a user with a bcrypt-hashed password; 400 if the username exists. Audit-logged."""
    existing = db.query(User).filter(User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    new_user = User(
        username=user.username,
        hashed_password=get_password_hash(user.password),
        role=user.role
    )
    db.add(new_user)
    db.commit()
    log_audit_event(db, current_user.username, current_user.role, "CREATE_USER", f"Created new user {user.username} ({user.role})")
    return {"status": "success", "user": {"username": user.username, "role": user.role}}

@app.delete("/api/admin/users/{user_id}")
def delete_user(user_id: int, current_user: User = Depends(require_role(["Admin"])), db: Session = Depends(get_db)):
    """Admin only: delete a user by id; an admin cannot delete their own account. Audit-logged."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.username == current_user.username:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    db.delete(user)
    db.commit()
    log_audit_event(db, current_user.username, current_user.role, "DELETE_USER", f"Deleted user {user.username}")
    return {"status": "success"}


# ─────────────────────────────────────────────────────────────────────────────
# PATIENT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/patients")
def get_patients(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List every patient with all observations and the latest persisted AI risk level."""
    patients = db.query(PatientDB).all()
    return [patient_db_to_pydantic(p) for p in patients]


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return one patient with observations; 404 if unknown."""
    p = db.query(PatientDB).filter(PatientDB.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient_db_to_pydantic(p)


@app.get("/api/patients/{patient_id}/observations")
def get_observations(patient_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return only the patient's observation time series; 404 if the patient is unknown."""
    p = db.query(PatientDB).filter(PatientDB.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient_db_to_pydantic(p).observations


# ─────────────────────────────────────────────────────────────────────────────
# AI EVALUATION ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

def run_evaluation(patient: Patient) -> AgentRecommendation:
    """Run the LangGraph pipeline on a patient's latest observation and record timing."""
    start = time.perf_counter()
    state = {"patient": patient, "current_obs": patient.observations[-1], "node_timings": {}}
    result = agent_app.invoke(state)

    recommendation = result["final_recommendation"]
    recommendation.latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
    # tokens_used is the real Groq usage set by the agent (0 when no LLM call was made)

    _performance_buffer.append({
        "timestamp": datetime.now().isoformat(),
        "patient_id": patient.patient_id,
        "total_latency_ms": recommendation.latency_ms,
        "tokens_used": recommendation.tokens_used,
        "risk_level": recommendation.risk_level,
        "node_timings": recommendation.node_timings or {},
        "groq_success": recommendation.confidence_score > 0
    })
    return recommendation


# ─────────────────────────────────────────────────────────────────────────────
# BATCH EVALUATION JOBS
# A ward-wide run makes one LLM call per patient, so it runs as a background job
# on a worker pool and the UI polls for progress instead of holding a request open.
# ─────────────────────────────────────────────────────────────────────────────
BATCH_WORKERS = int(os.environ.get("BATCH_WORKERS", "8"))
_batch_lock = threading.Lock()
_batch_jobs: dict[str, dict] = {}


def _run_batch_job(job_id: str, username: str, role: str):
    """Worker thread for a ward batch: evaluate patients concurrently, then persist risk levels and create pending escalations (High/Medium/Unknown) on this single thread/session."""
    job = _batch_jobs[job_id]
    start = time.time()
    db = SessionLocal()
    try:
        patients = [patient_db_to_pydantic(p) for p in db.query(PatientDB).all()]
        patients = [p for p in patients if p.observations]
        job["total"] = len(patients)

        recommendations: dict[str, AgentRecommendation] = {}
        with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as pool:
            futures = {pool.submit(run_evaluation, p): p.patient_id for p in patients}
            for fut in as_completed(futures):
                pid = futures[fut]
                try:
                    recommendations[pid] = fut.result()
                except Exception as e:
                    job["failed"] += 1
                    print(f"[BATCH EVAL ERROR] Failed for patient {pid}: {e}")
                job["completed"] += 1

        # All DB writes happen on this one thread/session
        counts = {"High": 0, "Medium": 0, "Low": 0, "Unknown": 0}
        escalations_created = 0
        llm_failures = 0
        for pdb in db.query(PatientDB).filter(PatientDB.id.in_(recommendations.keys())).all():
            rec = recommendations[pdb.id]
            pdb.risk_level = rec.risk_level
            counts[rec.risk_level] = counts.get(rec.risk_level, 0) + 1
            if rec.confidence_score == 0.0:
                llm_failures += 1

            if rec.risk_level in ("High", "Medium", "Unknown"):
                has_pending = db.query(EscalationDB.id).filter(
                    EscalationDB.patient_id == pdb.id, EscalationDB.status == "pending"
                ).first()
                if not has_pending:
                    db.add(EscalationDB(
                        id=str(uuid.uuid4()),
                        patient_id=pdb.id,
                        recommendation_json=rec.model_dump_json(),
                        status="pending",
                        created_at=datetime.now()
                    ))
                    escalations_created += 1
        db.commit()

        elapsed = round(time.time() - start, 2)
        job["result"] = {
            "evaluated_count": len(recommendations),
            "high_risk_count": counts["High"],
            "medium_risk_count": counts["Medium"],
            "low_risk_count": counts["Low"],
            "unknown_risk_count": counts["Unknown"],
            "failed_count": job["failed"] + llm_failures,
            "escalations_created": escalations_created,
            "total_time_seconds": elapsed
        }
        log_audit_event(
            db, username, role, "BATCH_EVALUATION",
            f"Evaluated {len(recommendations)} patients in {elapsed:.2f}s. "
            f"High: {counts['High']}, Medium: {counts['Medium']}, Low: {counts['Low']}, "
            f"Unknown: {counts['Unknown']}. LLM/eval failures: {job['failed'] + llm_failures}. "
            f"Created {escalations_created} new escalations."
        )
        job["status"] = "done"
    except Exception as e:
        db.rollback()
        job["status"] = "error"
        job["error"] = str(e)
        print(f"[BATCH JOB ERROR] {e}")
    finally:
        job["finished_at"] = datetime.now().isoformat()
        db.close()


def _public_job(job: dict) -> dict:
    """Subset of a batch-job record that is safe to return to clients."""
    return {k: job.get(k) for k in
            ("job_id", "status", "total", "completed", "failed", "started_at", "finished_at", "result", "error")}


@app.post("/api/evaluate/batch", status_code=202)
def start_batch_evaluation(current_user: User = Depends(get_current_user)):
    """
    Start a ward-wide AI evaluation in the background. Returns the job immediately;
    poll GET /api/evaluate/batch/{job_id}. If a run is already in progress, that job
    is returned instead of starting a second one.
    """
    with _batch_lock:
        running = next((j for j in _batch_jobs.values() if j["status"] == "running"), None)
        if running:
            return _public_job(running)
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id, "status": "running", "total": 0, "completed": 0, "failed": 0,
            "started_at": datetime.now().isoformat(), "finished_at": None, "result": None, "error": None
        }
        _batch_jobs[job_id] = job
        # Keep only the most recent jobs
        for old_id in list(_batch_jobs)[:-10]:
            _batch_jobs.pop(old_id, None)
    threading.Thread(
        target=_run_batch_job, args=(job_id, current_user.username, current_user.role), daemon=True
    ).start()
    return _public_job(job)


@app.get("/api/evaluate/batch/{job_id}")
def get_batch_evaluation(job_id: str, current_user: User = Depends(get_current_user)):
    """Poll a batch job: status (running/done/error), completed/total counts, and the result once done."""
    job = _batch_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return _public_job(job)


@app.post("/api/evaluate/{patient_id}")
def evaluate_patient(patient_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Run the LangGraph AI pipeline on a single patient."""
    pdb = db.query(PatientDB).filter(PatientDB.id == patient_id).first()
    if not pdb:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient = patient_db_to_pydantic(pdb)
    if not patient.observations:
        raise HTTPException(status_code=400, detail="No observations for this patient")

    recommendation = run_evaluation(patient)

    # Persist risk level to DB
    pdb.risk_level = recommendation.risk_level
    db.commit()

    return recommendation


# ─────────────────────────────────────────────────────────────────────────────
# ESCALATION ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/escalations")
def get_escalations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List all escalations (pending, approved, rejected) with their stored recommendation snapshots."""
    escalations = db.query(EscalationDB).all()
    return [esc_db_to_pydantic(e) for e in escalations]


class EscalationRequest(BaseModel):
    """Request body wrapping the AgentRecommendation to snapshot into a new escalation."""
    recommendation: AgentRecommendation


@app.post("/api/escalations/{patient_id}")
def create_escalation(
    patient_id: str,
    req: EscalationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a pending escalation for a patient (404 if unknown). If one is already pending, refresh it instead of stacking duplicates."""
    if not db.query(PatientDB.id).filter(PatientDB.id == patient_id).first():
        raise HTTPException(status_code=404, detail="Patient not found")

    # Re-evaluating a patient must not stack duplicate pending escalations
    existing = db.query(EscalationDB).filter(
        EscalationDB.patient_id == patient_id,
        EscalationDB.status == "pending"
    ).first()
    if existing:
        existing.recommendation_json = req.recommendation.model_dump_json()
        existing.created_at = datetime.now()
        db.commit()
        db.refresh(existing)
        return esc_db_to_pydantic(existing)

    rec_json = req.recommendation.model_dump_json()
    new_esc = EscalationDB(
        id=str(uuid.uuid4()),
        patient_id=patient_id,
        recommendation_json=rec_json,
        status="pending",
        created_at=datetime.now()
    )
    db.add(new_esc)
    db.commit()
    db.refresh(new_esc)
    return esc_db_to_pydantic(new_esc)


class ClinicianNotes(BaseModel):
    """Request body for approve/reject: the clinician's free-text note, stored on the escalation."""
    clinician_notes: str


@app.patch("/api/escalations/{escalation_id}/approve")
def approve_escalation(
    escalation_id: str,
    body: ClinicianNotes,
    current_user: User = Depends(require_role(["Doctor"])),
    db: Session = Depends(get_db)
):
    """Doctor only: mark a pending escalation approved and record notes/time; 409 if already resolved. Audit-logged."""
    esc = db.query(EscalationDB).filter(EscalationDB.id == escalation_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    if esc.status != "pending":
        raise HTTPException(status_code=409, detail=f"Escalation already {esc.status}")

    esc.status = "approved"
    esc.clinician_notes = body.clinician_notes
    esc.resolved_at = datetime.now()
    db.commit()
    db.refresh(esc)
    log_audit_event(db, current_user.username, current_user.role, "APPROVE_ESCALATION",
                    f"Approved escalation for patient {esc.patient_id}. Notes: {body.clinician_notes}")
    return esc_db_to_pydantic(esc)


@app.patch("/api/escalations/{escalation_id}/reject")
def reject_escalation(
    escalation_id: str,
    body: ClinicianNotes,
    current_user: User = Depends(require_role(["Doctor"])),
    db: Session = Depends(get_db)
):
    """Doctor only: mark a pending escalation rejected and record notes/time; 409 if already resolved. Audit-logged."""
    esc = db.query(EscalationDB).filter(EscalationDB.id == escalation_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    if esc.status != "pending":
        raise HTTPException(status_code=409, detail=f"Escalation already {esc.status}")

    esc.status = "rejected"
    esc.clinician_notes = body.clinician_notes
    esc.resolved_at = datetime.now()
    db.commit()
    db.refresh(esc)
    log_audit_event(db, current_user.username, current_user.role, "REJECT_ESCALATION",
                    f"Rejected escalation for patient {esc.patient_id}. Notes: {body.clinician_notes}")
    return esc_db_to_pydantic(esc)


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/audit-logs")
def get_audit_logs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Returns the last 100 immutable audit log entries."""
    logs = db.query(AuditLogDB).order_by(AuditLogDB.timestamp.desc()).limit(100).all()
    return logs


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/export/handover")
def export_handover_report(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Generate a clinical handover report for all High and Medium risk patients.
    Returns structured JSON with latest vitals, nursing notes, and AI reasoning.
    """
    high_med_patients = db.query(PatientDB).filter(
        PatientDB.risk_level.in_(["High", "Medium"])
    ).all()
    report = []
    for p in high_med_patients:
        patient_obj = patient_db_to_pydantic(p)
        latest_obs = patient_obj.observations[-1] if patient_obj.observations else None

        latest_esc = db.query(EscalationDB).filter(
            EscalationDB.patient_id == p.id
        ).order_by(EscalationDB.created_at.desc()).first()
        esc_pydantic = esc_db_to_pydantic(latest_esc) if latest_esc else None

        report.append({
            "patient_id": p.id,
            "name": p.name,
            "bed_number": p.bed_number,
            "risk_level": p.risk_level,
            "latest_hr": latest_obs.vitals.hr if latest_obs else None,
            "latest_bp": f"{latest_obs.vitals.bp_systolic}/{latest_obs.vitals.bp_diastolic}" if latest_obs else None,
            "latest_spo2": latest_obs.vitals.spo2 if latest_obs else None,
            "latest_resp_rate": latest_obs.vitals.resp_rate if latest_obs else None,
            "nursing_notes": latest_obs.nursing_notes if latest_obs else "",
            "ai_reasoning": esc_pydantic.recommendation.reasoning if esc_pydantic else "No active escalation reasoning",
            "recommended_action": esc_pydantic.recommendation.recommended_action if esc_pydantic else "Monitor vitals",
            "news2_score": esc_pydantic.recommendation.news2_score if esc_pydantic else None,
            "escalation_status": esc_pydantic.status if esc_pydantic else None
        })

    log_audit_event(
        db, current_user.username, current_user.role,
        "EXPORT_HANDOVER_REPORT",
        f"Exported handover report for {len(report)} High/Medium risk patients."
    )

    return {
        "generated_at": datetime.now().isoformat(),
        "generated_by": current_user.username,
        "high_medium_risk_patients_count": len(report),
        "patients": report
    }


# ─────────────────────────────────────────────────────────────────────────────
# CHAT ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatMessageResponse)
def clinical_chat_endpoint(
    body: ChatMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Clinical Copilot chatbot — domain-restricted to ED clinical topics."""
    context_lines = []

    # 1. Selected patient context
    if body.patient_id:
        pdb = db.query(PatientDB).filter(PatientDB.id == body.patient_id).first()
        if pdb:
            p_obj = patient_db_to_pydantic(pdb)
            latest_obs = p_obj.observations[-1] if p_obj.observations else None
            context_lines.append(
                f"SELECTED PATIENT: {p_obj.name} (Bed {p_obj.bed_number}, ID: {p_obj.patient_id})\n"
                f"  Risk Level: {p_obj.risk_level or 'UNASSESSED'}\n"
                f"  Latest Vitals: HR {latest_obs.vitals.hr if latest_obs else 'N/A'} bpm, "
                f"BP {latest_obs.vitals.bp_systolic if latest_obs else 'N/A'}/"
                f"{latest_obs.vitals.bp_diastolic if latest_obs else 'N/A'} mmHg, "
                f"SpO2 {latest_obs.vitals.spo2 if latest_obs else 'N/A'}%, "
                f"RR {latest_obs.vitals.resp_rate if latest_obs else 'N/A'}/min, "
                f"Temp {latest_obs.vitals.temp if latest_obs else 'N/A'}°C\n"
                f"  Nursing Notes: '{latest_obs.nursing_notes if latest_obs else ''}'"
            )

    # 2. Ward-wide overview
    all_patients = db.query(PatientDB).all()
    assessed = [p for p in all_patients if p.risk_level]
    high_risk = [p for p in all_patients if p.risk_level == "High"]
    med_risk = [p for p in all_patients if p.risk_level == "Medium"]
    pending_escs = db.query(EscalationDB).filter(EscalationDB.status == "pending").all()

    context_lines.append(
        f"\nWARD DATABASE OVERVIEW:\n"
        f"- Total Patients: {len(all_patients)}\n"
        f"- Assessed Patients: {len(assessed)}\n"
        f"- High Risk: {len(high_risk)}\n"
        f"- Medium Risk: {len(med_risk)}\n"
        f"- Pending Escalations: {len(pending_escs)}"
    )

    if assessed:
        context_lines.append("\nASSESSED PATIENTS SUMMARY:")
        for p in assessed[:30]:
            p_obj = patient_db_to_pydantic(p)
            latest_obs = p_obj.observations[-1] if p_obj.observations else None
            context_lines.append(
                f"- {p.name} | Bed {p.bed_number} | Risk: {p.risk_level} | "
                f"HR={latest_obs.vitals.hr if latest_obs else 'N/A'}, "
                f"BP={latest_obs.vitals.bp_systolic if latest_obs else 'N/A'}/"
                f"{latest_obs.vitals.bp_diastolic if latest_obs else 'N/A'}, "
                f"SpO2={latest_obs.vitals.spo2 if latest_obs else 'N/A'}%"
            )

    if pending_escs:
        context_lines.append("\nPENDING ESCALATIONS:")
        for esc in pending_escs[:10]:
            p_name = next((p.name for p in all_patients if p.id == esc.patient_id), esc.patient_id)
            context_lines.append(f"- Patient: {p_name} | Created: {esc.created_at}")

    full_context = "\n".join(context_lines)
    res = clinical_chat_assistant(body.message, patient_context=full_context)

    log_audit_event(
        db, current_user.username, current_user.role,
        "AI_CHAT_QUERY",
        f"Query: '{body.message[:80]}' | Out-of-domain: {res['out_of_domain']}"
    )

    return {
        "reply": res["reply"],
        "out_of_domain": res["out_of_domain"],
        "context_used": full_context
    }


# ─────────────────────────────────────────────────────────────────────────────
# METRICS + PERFORMANCE ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/metrics")
def get_metrics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """System metrics — patient counts, risk distribution, AI vs baseline performance."""
    pending_escalations = db.query(EscalationDB).filter(EscalationDB.status == "pending").count()
    total_patients = db.query(PatientDB).count()

    experiment_data = {}
    try:
        with open(EXPERIMENT_RESULTS_PATH, "r") as f:
            experiment_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    return {
        "totalPatients": total_patients,
        "activeAlerts": pending_escalations,
        "systemConfidence": experiment_data.get("ai", {}).get("detection_rate", 0),
        "baselineDetectionRate": experiment_data.get("baseline", {}).get("detection_rate", 0),
        "aiDetectionRate": experiment_data.get("ai", {}).get("detection_rate", 0),
        "aiFalseAlertRate": experiment_data.get("ai", {}).get("false_alert_rate", 0),
        "baselineFalseAlertRate": experiment_data.get("baseline", {}).get("false_alert_rate", 0),
        "aiF1Score": experiment_data.get("ai", {}).get("f1_score", 0),
        "baselineF1Score": experiment_data.get("baseline", {}).get("f1_score", 0),
        "detectionRateImprovement": experiment_data.get("detection_rate_improvement", 0),
        "falseAlertReduction": experiment_data.get("false_alert_reduction", 0),
        "f1Improvement": experiment_data.get("f1_improvement", 0),
        "perArchetype": experiment_data.get("per_archetype", {}),
        "experiment": experiment_data
    }


@app.get("/api/performance")
def get_performance(current_user: User = Depends(get_current_user)):
    """
    LangGraph Pipeline Latency Profiling Endpoint.
    
    Returns aggregate statistics from the in-memory performance ring buffer
    (last 100 evaluations), including:
    - Average total latency
    - 95th percentile latency (P95)
    - Per-node average latency breakdown
    - Token utilization statistics
    - Groq API success rate
    """
    if not _performance_buffer:
        return {
            "message": "No evaluations recorded yet. Run an evaluation to populate performance data.",
            "total_evaluations": 0,
            "avg_total_latency_ms": 0,
            "p95_latency_ms": 0,
            "avg_tokens_used": 0,
            "groq_success_rate": 0,
            "avg_node_timings": {}
        }

    records = list(_performance_buffer)
    latencies = [r["total_latency_ms"] for r in records if r["total_latency_ms"] > 0]
    tokens = [r["tokens_used"] for r in records]
    successes = [r["groq_success"] for r in records]

    # Per-node aggregation
    node_timing_sums = {}
    node_timing_counts = {}
    for r in records:
        for node, ms in (r.get("node_timings") or {}).items():
            node_timing_sums[node] = node_timing_sums.get(node, 0) + ms
            node_timing_counts[node] = node_timing_counts.get(node, 0) + 1

    avg_node_timings = {
        node: round(node_timing_sums[node] / node_timing_counts[node], 2)
        for node in node_timing_sums
    }

    # P95 latency
    if latencies:
        sorted_latencies = sorted(latencies)
        p95_idx = int(len(sorted_latencies) * 0.95)
        p95_latency = sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)]
    else:
        p95_latency = 0

    return {
        "total_evaluations": len(records),
        "avg_total_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "p95_latency_ms": round(p95_latency, 2),
        "min_latency_ms": round(min(latencies), 2) if latencies else 0,
        "max_latency_ms": round(max(latencies), 2) if latencies else 0,
        "avg_tokens_used": round(sum(tokens) / len(tokens), 1) if tokens else 0,
        "groq_success_rate": round(sum(successes) / len(successes), 4) if successes else 0,
        "avg_node_timings": avg_node_timings,
        "recent_evaluations": records[-10:]  # Last 10 for display
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
