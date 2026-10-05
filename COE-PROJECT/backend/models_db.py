from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String) # 'Doctor', 'Nurse', 'Admin'

class PatientDB(Base):
    __tablename__ = "patients"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    bed_number = Column(String)
    admission_time = Column(DateTime)
    risk_level = Column(String, nullable=True)  # Set after AI evaluation: High/Medium/Low/Unknown
    
    observations = relationship("ObservationDB", back_populates="patient", cascade="all, delete-orphan")
    escalations = relationship("EscalationDB", back_populates="patient")

class ObservationDB(Base):
    __tablename__ = "observations"
    
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String, ForeignKey("patients.id"))
    timestamp = Column(DateTime)
    
    # Vitals
    hr = Column(Integer, nullable=True)
    bp_systolic = Column(Integer, nullable=True)
    bp_diastolic = Column(Integer, nullable=True)
    resp_rate = Column(Integer, nullable=True)
    temp = Column(Float, nullable=True)
    spo2 = Column(Float, nullable=True)
    consciousness_level = Column(String, nullable=True)
    
    nursing_notes = Column(String)
    is_incomplete_history = Column(Boolean, default=False)
    is_unconscious = Column(Boolean, default=False)
    is_distressed = Column(Boolean, default=False)
    
    patient = relationship("PatientDB", back_populates="observations")

class EscalationDB(Base):
    __tablename__ = "escalations"
    
    id = Column(String, primary_key=True, index=True)
    patient_id = Column(String, ForeignKey("patients.id"))
    status = Column(String, default="pending")
    clinician_notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    
    # Snapshot of recommendation JSON
    recommendation_json = Column(String)
    
    patient = relationship("PatientDB", back_populates="escalations")

class AuditLogDB(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    username = Column(String)
    role = Column(String)
    action = Column(String)
    details = Column(String)
