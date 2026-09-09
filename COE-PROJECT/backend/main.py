import json
import uuid
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dataset import generate_patients
from vector_store import initialize_vector_store
from agent import app as agent_app
from models import AgentRecommendation, Escalation

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage
patients_db = {}
escalations_db = []

@app.on_event("startup")
def on_startup():
    initialize_vector_store()
    patients = generate_patients()
    for p in patients:
        patients_db[p.patient_id] = p
    print(f"Loaded {len(patients_db)} patients.")

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/patients")
def get_patients():
    return list(patients_db.values())

@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: str):
    if patient_id not in patients_db:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patients_db[patient_id]

@app.get("/api/patients/{patient_id}/observations")
def get_observations(patient_id: str):
    if patient_id not in patients_db:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patients_db[patient_id].observations

@app.post("/api/evaluate/{patient_id}")
def evaluate_patient(patient_id: str):
    if patient_id not in patients_db:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    patient = patients_db[patient_id]
    if not patient.observations:
        raise HTTPException(status_code=400, detail="No observations")
        
    latest_obs = patient.observations[-1]
    
    state = {
        "patient": patient,
        "current_obs": latest_obs
    }
    
    result = agent_app.invoke(state)
    return result["final_recommendation"]

@app.get("/api/escalations")
def get_escalations():
    return escalations_db

class EscalationRequest(BaseModel):
    recommendation: AgentRecommendation

@app.post("/api/escalations/{patient_id}")
def create_escalation(patient_id: str, req: EscalationRequest):
    escalation = Escalation(
        id=str(uuid.uuid4()),
        patient_id=patient_id,
        recommendation=req.recommendation,
        status="pending",
        created_at=datetime.now()
    )
    escalations_db.append(escalation)
    return escalation

class ClinicianNotes(BaseModel):
    clinician_notes: str

@app.patch("/api/escalations/{escalation_id}/approve")
def approve_escalation(escalation_id: str, body: ClinicianNotes):
    for esc in escalations_db:
        if esc.id == escalation_id:
            esc.status = "approved"
            esc.clinician_notes = body.clinician_notes
            esc.resolved_at = datetime.now()
            return esc
    raise HTTPException(status_code=404, detail="Escalation not found")

@app.patch("/api/escalations/{escalation_id}/reject")
def reject_escalation(escalation_id: str, body: ClinicianNotes):
    for esc in escalations_db:
        if esc.id == escalation_id:
            esc.status = "rejected"
            esc.clinician_notes = body.clinician_notes
            esc.resolved_at = datetime.now()
            return esc
    raise HTTPException(status_code=404, detail="Escalation not found")

@app.get("/api/metrics")
def get_metrics():
    pending_escalations = [e for e in escalations_db if e.status == "pending"]
    
    experiment_data = {}
    try:
        with open("experiment_results.json", "r") as f:
            experiment_data = json.load(f)
    except FileNotFoundError:
        pass
    
    return {
        "totalPatients": len(patients_db),
        "activeAlerts": len(pending_escalations),
        "systemConfidence": experiment_data.get("ai", {}).get("detection_rate", 0),
        "baselineDetectionRate": experiment_data.get("baseline", {}).get("detection_rate", 0),
        "aiDetectionRate": experiment_data.get("ai", {}).get("detection_rate", 0),
        "aiFalseAlertRate": experiment_data.get("ai", {}).get("false_alert_rate", 0),
        "detectionRateImprovement": experiment_data.get("detection_rate_improvement", 0),
        "experiment": experiment_data
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
