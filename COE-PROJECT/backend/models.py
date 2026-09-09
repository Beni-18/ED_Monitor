from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class VitalSigns(BaseModel):
    hr: Optional[int] = None
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    resp_rate: Optional[int] = None
    temp: Optional[float] = None
    spo2: Optional[float] = None
    consciousness_level: Optional[str] = None  # AVPU: A, V, P, U

class PatientObservation(BaseModel):
    patient_id: str
    timestamp: datetime
    vitals: VitalSigns
    nursing_notes: str = ""
    is_incomplete_history: bool = False
    is_unconscious: bool = False
    is_distressed: bool = False

class Patient(BaseModel):
    patient_id: str
    name: str
    bed_number: str
    admission_time: datetime
    observations: List[PatientObservation]

class AgentRecommendation(BaseModel):
    risk_level: str
    confidence_score: float
    missing_measurements: List[str]
    missing_measurement_risk_score: float
    reasoning: str
    recommended_action: str
    retrieved_similar_cases: List[str]
    news2_score: int
    baseline_would_flag: bool

class Escalation(BaseModel):
    id: str
    patient_id: str
    recommendation: AgentRecommendation
    status: str  # pending/approved/rejected
    clinician_notes: str = ""
    created_at: datetime
    resolved_at: Optional[datetime] = None
