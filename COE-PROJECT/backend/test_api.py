"""
test_api.py — Integration Tests for FastAPI Endpoints

Tests API routing, RBAC authorization, and data structures.

Run with: pytest test_api.py -v
"""
import os
import pytest
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from main import app
from database import Base, engine, SessionLocal
from models_db import User, PatientDB
from auth import get_password_hash

# ─────────────────────────────────────────────────────────────────────────────
# TEST SETUP
# ─────────────────────────────────────────────────────────────────────────────

# Create a clean in-memory SQLite DB for tests if you wanted to isolate fully,
# but here we'll use the TestClient which will trigger the lifespan event
# and use the default local DB. For CI, we'd mock the DB.

client = TestClient(app)

def get_auth_token(username, password="password123"):
    response = client.post("/api/login", data={"username": username, "password": password})
    if response.status_code == 200:
        return response.json()["access_token"]
    return None

@pytest.fixture(scope="module")
def admin_token():
    return get_auth_token("admin")

@pytest.fixture(scope="module")
def doctor_token():
    return get_auth_token("doctor")

@pytest.fixture(scope="module")
def nurse_token():
    return get_auth_token("nurse")


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

def test_health_check():
    """Verify health endpoint returns 200 OK and version."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_invalid_credentials():
    """Verify login fails with wrong password."""
    response = client.post("/api/login", data={"username": "doctor", "password": "wrongpassword"})
    assert response.status_code == 401
    assert "Incorrect username or password" in response.json()["detail"]


def test_login_nurse_role():
    """Verify nurse login returns correct role."""
    response = client.post("/api/login", data={"username": "nurse", "password": "password123"})
    assert response.status_code == 200
    assert response.json()["role"] == "Nurse"
    assert "access_token" in response.json()


# ─────────────────────────────────────────────────────────────────────────────
# PATIENT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

def test_get_patients_list():
    """Verify patients endpoint returns a list of patients (currently public)."""
    response = client.get("/api/patients")
    assert response.status_code == 200
    patients = response.json()
    assert len(patients) > 0
    assert "patient_id" in patients[0]
    assert "name" in patients[0]


def test_get_patient_detail():
    """Verify single patient fetch works."""
    # First get list to find an ID
    res = client.get("/api/patients")
    patient_id = res.json()[0]["patient_id"]
    
    response = client.get(f"/api/patients/{patient_id}")
    assert response.status_code == 200
    patient = response.json()
    assert patient["patient_id"] == patient_id
    assert "observations" in patient


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATION & METRICS ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

def test_metrics_endpoint_structure():
    """Verify metrics endpoint returns expected schema."""
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "totalPatients" in data
    assert "activeAlerts" in data
    assert "systemConfidence" in data


def test_batch_evaluate_ward_auth_required():
    """Batch evaluate requires auth token."""
    response = client.post("/api/evaluate/batch")
    assert response.status_code == 401


def test_batch_evaluate_ward_success(doctor_token):
    """Verify batch evaluation returns summary statistics."""
    # We use a mocked LLM response for speed if possible, but here it runs the real or fallback graph
    # To avoid burning tokens or failing without key, the agent falls back cleanly.
    headers = {"Authorization": f"Bearer {doctor_token}"}
    response = client.post("/api/evaluate/batch", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "evaluated_count" in data
    assert "total_time_seconds" in data
    assert data["evaluated_count"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# ESCALATION ENDPOINTS (RBAC)
# ─────────────────────────────────────────────────────────────────────────────

def test_nurse_cannot_approve_escalation(nurse_token):
    """Verify Nurse role receives 403 Forbidden when trying to approve."""
    # We don't need a real escalation ID if it blocks at the auth layer
    headers = {"Authorization": f"Bearer {nurse_token}"}
    response = client.patch("/api/escalations/fake-id/approve", json={"clinician_notes": "approved"}, headers=headers)
    assert response.status_code == 403


def test_admin_cannot_approve_escalation(admin_token):
    """Verify Admin role receives 403 Forbidden when trying to approve."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = client.patch("/api/escalations/fake-id/approve", json={"clinician_notes": "approved"}, headers=headers)
    assert response.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT & EXPORT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

def test_get_audit_logs_auth(admin_token):
    """Verify audit logs can be fetched with auth."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = client.get("/api/audit-logs", headers=headers)
    assert response.status_code == 200
    logs = response.json()
    assert isinstance(logs, list)


def test_export_handover_structure(doctor_token):
    """Verify handover export returns correct JSON keys."""
    headers = {"Authorization": f"Bearer {doctor_token}"}
    response = client.get("/api/export/handover", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "generated_at" in data
    assert "high_medium_risk_patients_count" in data
    assert "patients" in data


# ─────────────────────────────────────────────────────────────────────────────
# CHATBOT ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

def test_chat_out_of_domain(doctor_token):
    """Verify chatbot blocks non-clinical queries via keyword pre-filter."""
    headers = {"Authorization": f"Bearer {doctor_token}"}
    payload = {"message": "Write a python script to sort an array", "patient_id": None}
    response = client.post("/api/chat", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["out_of_domain"] is True
    assert "ED Clinical Copilot" in data["reply"]


def test_chat_clinical_query(doctor_token):
    """Verify chatbot allows clinical queries."""
    headers = {"Authorization": f"Bearer {doctor_token}"}
    payload = {"message": "What is the normal range for heart rate in an adult?", "patient_id": None}
    response = client.post("/api/chat", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["out_of_domain"] is False
    assert len(data["reply"]) > 0
