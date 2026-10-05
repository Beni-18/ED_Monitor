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
    risk_level: Optional[str] = None  # Updated after AI evaluation

class AgentRecommendation(BaseModel):
    risk_level: str = Field(..., description="Risk level of the patient: 'High', 'Medium', 'Low', or 'Unknown'")
    confidence_score: float = Field(..., description="Confidence score of the recommendation between 0.0 and 1.0")
    missing_measurements: list[str] = Field(default_factory=list, description="List of vital signs that are missing")
    missing_measurement_risk_score: float = Field(..., description="Calculated risk score based on missing measurements")
    reasoning: str = Field(..., description="Detailed clinical reasoning for the recommendation")
    recommended_action: str = Field(..., description="Recommended action for the clinician (e.g., 'Immediate medical review')")
    retrieved_similar_cases: list[str] = Field(default_factory=list, description="Clinical guidelines retrieved for context")
    news2_score: int = Field(default=0, description="The calculated NEWS2 score")
    baseline_would_flag: bool = Field(default=False, description="Whether the baseline NEWS2 heuristic would flag this patient")
    latency_ms: float = Field(default=0.0, description="Total end-to-end latency in milliseconds")
    tokens_used: int = Field(default=0, description="Estimated tokens used")
    node_timings: Optional[dict] = Field(default=None, description="Per-node LangGraph latency breakdown in milliseconds")


class Escalation(BaseModel):
    id: str
    patient_id: str
    recommendation: AgentRecommendation
    status: str  # pending/approved/rejected
    clinician_notes: Optional[str] = None  # NULL when pending, set when actioned
    created_at: datetime
    resolved_at: Optional[datetime] = None

class AuditLog(BaseModel):
    id: int
    timestamp: datetime
    username: str
    role: str
    action: str
    details: str

class BatchEvaluationResult(BaseModel):
    evaluated_count: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    escalations_created: int
    total_time_seconds: float

class ChatMessageRequest(BaseModel):
    message: str
    patient_id: Optional[str] = None

class ChatMessageResponse(BaseModel):
    reply: str
    out_of_domain: bool = False
    context_used: Optional[str] = None
