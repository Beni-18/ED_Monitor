"""
main.py — FastAPI Backend for ED Deterioration Monitor

Endpoints:
  POST /api/login              — OAuth2 login, returns JWT + role
  GET  /api/health             — Health check (no auth required)
  GET  /api/patients           — List all patients
  GET  /api/patients/{id}      — Get single patient with observations
  GET  /api/patients/{id}/observations — Get time-series observations
  POST /api/evaluate/{id}      — Run AI evaluation on single patient
  POST /api/evaluate/batch     — Run AI evaluation on all ward patients
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
import uuid
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime

import asyncio
from fastapi import FastAPI, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
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
    VitalSigns, AuditLog, BatchEvaluationResult, ChatMessageRequest,
    ChatMessageResponse
)
from database import engine, Base, SessionLocal, get_db
from models_db import User, PatientDB, ObservationDB, EscalationDB, AuditLogDB
from auth import get_password_hash, verify_password, create_access_token, require_role, get_current_user
from fastapi.security import OAuth2PasswordRequestForm

# ─────────────────────────────────────────────────────────────────────────────
# PERFORMANCE METRICS RING BUFFER
# Stores the last 100 evaluation timing records in memory for the
# /api/performance endpoint. Uses deque for O(1) append/pop.
# ─────────────────────────────────────────────────────────────────────────────
_performance_buffer: deque = deque(maxlen=100)

# ─────────────────────────────────────────────────────────────────────────────
# WEBSOCKET CONNECTION MANAGER
# ─────────────────────────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITER SETUP (slowapi)
# ─────────────────────────────────────────────────────────────────────────────
if RATE_LIMITING_AVAILABLE:
    limiter = Limiter(key_func=get_remote_address)
else:
    limiter = None

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
    obs_list = []
    for obs in p.observations:
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
    return Escalation(
        id=e.id,
        patient_id=e.patient_id,
        recommendation=AgentRecommendation.model_validate_json(e.recommendation_json),
        status=e.status,
        clinician_notes=e.clinician_notes,
        created_at=e.created_at,
        resolved_at=e.resolved_at
    )


import random

async def live_vitals_simulator():
    """Generates new vitals periodically and triggers auto-escalations (Hybrid AI rules)."""
    while True:
        await asyncio.sleep(5)
        if not manager.active_connections:
            continue
        db = SessionLocal()
        try:
            # Pick a random patient
            patient_id = random.choice([row[0] for row in db.query(PatientDB.id).all()])
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
            needs_eval = False
            if new_spo2 and new_spo2 < 88:
                needs_eval = True
            if new_hr and new_hr > 130:
                needs_eval = True
            if new_sys and new_sys < 90:
                needs_eval = True

            if needs_eval:
                # Trigger LangGraph!
                patient = patient_db_to_pydantic(pdb)
                state = {"patient": patient, "current_obs": patient.observations[-1], "node_timings": {}}
                result = agent_app.invoke(state)
                rec = result["final_recommendation"]

                if rec.risk_level in ["High", "Medium"]:
                    pdb.risk_level = rec.risk_level
                    existing = db.query(EscalationDB).filter(EscalationDB.patient_id == patient_id, EscalationDB.status == "pending").first()
                    if not existing:
                        new_esc = EscalationDB(
                            id=str(uuid.uuid4()),
                            patient_id=patient_id,
                            recommendation_json=rec.model_dump_json(),
                            status="pending",
                            created_at=datetime.now()
                        )
                        db.add(new_esc)
                        db.commit()
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
async def websocket_vitals_endpoint(websocket: WebSocket):
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
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    OAuth2 login endpoint. Rate-limited to 10 attempts/minute per IP to
    prevent brute-force attacks on clinical credentials.
    """
    # Apply rate limiting if available
    if RATE_LIMITING_AVAILABLE and limiter:
        try:
            limiter.check(request=request, limit_string="10/minute")
        except Exception:
            raise HTTPException(status_code=429, detail="Too many login attempts. Please wait before trying again.")

    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": user.username})
    log_audit_event(db, user.username, user.role, "USER_LOGIN",
                    f"User {user.username} ({user.role}) authenticated successfully.")
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "2.3.0"}

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN ENDPOINTS (USER MANAGEMENT)
# ─────────────────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    username: str
    password: str
    role: str

@app.get("/api/admin/users")
def get_users(current_user: User = Depends(require_role(["Admin"])), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "role": u.role} for u in users]

@app.post("/api/admin/users")
def create_user(user: UserCreate, current_user: User = Depends(require_role(["Admin"])), db: Session = Depends(get_db)):
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
def get_patients(db: Session = Depends(get_db)):
    patients = db.query(PatientDB).all()
    return [patient_db_to_pydantic(p) for p in patients]


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    p = db.query(PatientDB).filter(PatientDB.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient_db_to_pydantic(p)


@app.get("/api/patients/{patient_id}/observations")
def get_observations(patient_id: str, db: Session = Depends(get_db)):
    p = db.query(PatientDB).filter(PatientDB.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient_db_to_pydantic(p).observations


# ─────────────────────────────────────────────────────────────────────────────
# AI EVALUATION ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/evaluate/batch", response_model=BatchEvaluationResult)
def batch_evaluate_patients(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Run the AI pipeline across the entire ward.
    Auto-creates escalations for High/Medium/Unknown risk patients.
    """
    start_time = time.time()
    patients = db.query(PatientDB).all()

    high_risk = med_risk = low_risk = 0
    escalations_created = 0
    evaluated_count = 0

    for pdb in patients:
        patient = patient_db_to_pydantic(pdb)
        if not patient.observations:
            continue

        latest_obs = patient.observations[-1]
        state = {"patient": patient, "current_obs": latest_obs, "node_timings": {}}

        try:
            result = agent_app.invoke(state)
            recommendation = result["final_recommendation"]

            pdb.risk_level = recommendation.risk_level
            evaluated_count += 1

            if recommendation.risk_level == "High":
                high_risk += 1
            elif recommendation.risk_level == "Medium":
                med_risk += 1
            else:
                low_risk += 1

            if recommendation.risk_level in ["High", "Medium", "Unknown"]:
                existing = db.query(EscalationDB).filter(
                    EscalationDB.patient_id == pdb.id,
                    EscalationDB.status == "pending"
                ).first()

                if not existing:
                    rec_json = recommendation.model_dump_json()
                    new_esc = EscalationDB(
                        id=str(uuid.uuid4()),
                        patient_id=pdb.id,
                        recommendation_json=rec_json,
                        status="pending",
                        created_at=datetime.now()
                    )
                    db.add(new_esc)
                    escalations_created += 1

            # Record to performance buffer
            _performance_buffer.append({
                "timestamp": datetime.now().isoformat(),
                "patient_id": pdb.id,
                "total_latency_ms": recommendation.latency_ms,
                "tokens_used": recommendation.tokens_used,
                "risk_level": recommendation.risk_level,
                "node_timings": recommendation.node_timings or {},
                "groq_success": recommendation.confidence_score > 0
            })

        except Exception as e:
            print(f"[BATCH EVAL ERROR] Failed for patient {pdb.id}: {e}")

    db.commit()
    total_time = time.time() - start_time

    log_audit_event(
        db, current_user.username, current_user.role,
        "BATCH_EVALUATION",
        f"Evaluated {evaluated_count} patients in {total_time:.2f}s. "
        f"High: {high_risk}, Medium: {med_risk}, Low/Other: {low_risk}. "
        f"Created {escalations_created} new escalations."
    )

    return {
        "evaluated_count": evaluated_count,
        "high_risk_count": high_risk,
        "medium_risk_count": med_risk,
        "low_risk_count": low_risk,
        "escalations_created": escalations_created,
        "total_time_seconds": round(total_time, 2)
    }


@app.post("/api/evaluate/{patient_id}")
def evaluate_patient(patient_id: str, db: Session = Depends(get_db)):
    """Run the LangGraph AI pipeline on a single patient."""
    start_time = time.perf_counter()

    pdb = db.query(PatientDB).filter(PatientDB.id == patient_id).first()
    if not pdb:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient = patient_db_to_pydantic(pdb)
    if not patient.observations:
        raise HTTPException(status_code=400, detail="No observations for this patient")

    latest_obs = patient.observations[-1]
    state = {"patient": patient, "current_obs": latest_obs, "node_timings": {}}

    result = agent_app.invoke(state)
    end_time = time.perf_counter()
    total_latency_ms = round((end_time - start_time) * 1000.0, 2)

    # Token estimation based on input length
    input_text = latest_obs.nursing_notes or ""
    rag_text = " ".join(result.get("retrieved_cases", []))
    tokens_used = (len(input_text) + len(rag_text)) // 4

    recommendation = result["final_recommendation"]
    recommendation.latency_ms = total_latency_ms
    recommendation.tokens_used = tokens_used

    # Persist risk level to DB
    pdb.risk_level = recommendation.risk_level
    db.commit()

    # Record to performance buffer
    _performance_buffer.append({
        "timestamp": datetime.now().isoformat(),
        "patient_id": patient_id,
        "total_latency_ms": total_latency_ms,
        "tokens_used": tokens_used,
        "risk_level": recommendation.risk_level,
        "node_timings": recommendation.node_timings or {},
        "groq_success": recommendation.confidence_score > 0
    })

    return recommendation


# ─────────────────────────────────────────────────────────────────────────────
# ESCALATION ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/escalations")
def get_escalations(db: Session = Depends(get_db)):
    escalations = db.query(EscalationDB).all()
    return [esc_db_to_pydantic(e) for e in escalations]


class EscalationRequest(BaseModel):
    recommendation: AgentRecommendation


@app.post("/api/escalations/{patient_id}")
def create_escalation(patient_id: str, req: EscalationRequest, db: Session = Depends(get_db)):
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
    clinician_notes: str


@app.patch("/api/escalations/{escalation_id}/approve")
def approve_escalation(
    escalation_id: str,
    body: ClinicianNotes,
    current_user: User = Depends(require_role(["Doctor"])),
    db: Session = Depends(get_db)
):
    esc = db.query(EscalationDB).filter(EscalationDB.id == escalation_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")

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
    esc = db.query(EscalationDB).filter(EscalationDB.id == escalation_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")

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
def get_metrics(db: Session = Depends(get_db)):
    """System metrics — patient counts, risk distribution, AI vs baseline performance."""
    pending_escalations = db.query(EscalationDB).filter(EscalationDB.status == "pending").count()
    total_patients = db.query(PatientDB).count()

    experiment_data = {}
    try:
        with open("experiment_results.json", "r") as f:
            experiment_data = json.load(f)
    except FileNotFoundError:
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
