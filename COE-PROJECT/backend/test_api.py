"""
test_api.py — Integration Tests for FastAPI Endpoints

Tests API routing, RBAC authorization, and data structures.

Run with: pytest test_api.py -v
"""
import os
import sys
import tempfile
import pytest

# Isolate tests: fresh temp SQLite DB, never touch the real ward database.
# Must be set before `database` is imported.
_TMP_DIR = tempfile.mkdtemp(prefix="ed_monitor_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'test.db')}"
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-not-for-production")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from fastapi.testclient import TestClient
from main import app

# main.py loads backend/.env on import; force offline heuristic mode so tests
# are deterministic and never spend Groq tokens.
os.environ.pop("GROQ_API_KEY", None)

# ─────────────────────────────────────────────────────────────────────────────
# TEST SETUP
# ─────────────────────────────────────────────────────────────────────────────

# Entering the client as a context manager runs the app lifespan, which seeds
# the default users and patients into the temp DB.
_client_cm = TestClient(app)
client = _client_cm.__enter__()


def teardown_module(module):
    _client_cm.__exit__(None, None, None)


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

def test_patients_require_auth():
    """Patient data must not be readable without a token."""
    assert client.get("/api/patients").status_code == 401
    assert client.get("/api/escalations").status_code == 401
    assert client.get("/api/metrics").status_code == 401
    assert client.post("/api/evaluate/p_stable_1").status_code == 401


def test_get_patients_list(nurse_token):
    """Verify patients endpoint returns a list of patients."""
    response = client.get("/api/patients", headers={"Authorization": f"Bearer {nurse_token}"})
    assert response.status_code == 200
    patients = response.json()
    assert len(patients) > 0
    assert "patient_id" in patients[0]
    assert "name" in patients[0]


def test_get_patient_detail(nurse_token):
    """Verify single patient fetch works."""
    headers = {"Authorization": f"Bearer {nurse_token}"}
    res = client.get("/api/patients", headers=headers)
    patient_id = res.json()[0]["patient_id"]

    response = client.get(f"/api/patients/{patient_id}", headers=headers)
    assert response.status_code == 200
    patient = response.json()
    assert patient["patient_id"] == patient_id
    assert "observations" in patient


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATION & METRICS ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

def test_metrics_endpoint_structure(nurse_token):
    """Verify metrics endpoint returns expected schema."""
    response = client.get("/api/metrics", headers={"Authorization": f"Bearer {nurse_token}"})
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
    """Batch evaluation runs as a background job; poll it to completion."""
    import time
    headers = {"Authorization": f"Bearer {doctor_token}"}
    start = client.post("/api/evaluate/batch", headers=headers)
    assert start.status_code == 202
    job = start.json()
    assert job["status"] in ("running", "done")

    # A second request while one is running joins the same job instead of starting another
    if job["status"] == "running":
        assert client.post("/api/evaluate/batch", headers=headers).json()["job_id"] == job["job_id"]

    deadline = time.time() + 120
    while job["status"] == "running" and time.time() < deadline:
        time.sleep(0.5)
        job = client.get(f"/api/evaluate/batch/{job['job_id']}", headers=headers).json()
    assert job["status"] == "done", job
    assert job["completed"] == job["total"] > 0

    data = job["result"]
    assert data["evaluated_count"] > 0
    assert "total_time_seconds" in data
    assert data["evaluated_count"] == (
        data["high_risk_count"] + data["medium_risk_count"]
        + data["low_risk_count"] + data["unknown_risk_count"]
    )


def test_batch_job_not_found(doctor_token):
    headers = {"Authorization": f"Bearer {doctor_token}"}
    assert client.get("/api/evaluate/batch/nope", headers=headers).status_code == 404


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


def test_chat_does_not_block_clinical_words(doctor_token):
    """Clinical terms containing off-topic substrings (car-diac, who is...) must pass the filter."""
    headers = {"Authorization": f"Bearer {doctor_token}"}
    for msg in ["Which patients need cardiac care?", "Who is the highest risk patient?"]:
        data = client.post("/api/chat", json={"message": msg}, headers=headers).json()
        assert data["out_of_domain"] is False, msg


# ─────────────────────────────────────────────────────────────────────────────
# ESCALATION WORKFLOW & ADMIN
# ─────────────────────────────────────────────────────────────────────────────

def test_escalation_lifecycle_and_dedupe(doctor_token, nurse_token):
    """Evaluate -> escalate (deduped) -> approve -> cannot re-resolve."""
    d = {"Authorization": f"Bearer {doctor_token}"}
    rec = client.post("/api/evaluate/p_obvious_1", headers=d).json()

    first = client.post("/api/escalations/p_obvious_1", json={"recommendation": rec}, headers=d).json()
    second = client.post("/api/escalations/p_obvious_1", json={"recommendation": rec}, headers=d).json()
    assert first["id"] == second["id"], "re-escalating must not stack duplicate pending items"

    approved = client.patch(f"/api/escalations/{first['id']}/approve", json={"clinician_notes": "ok"}, headers=d)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    again = client.patch(f"/api/escalations/{first['id']}/reject", json={"clinician_notes": "no"}, headers=d)
    assert again.status_code == 409


def test_escalation_unknown_patient(doctor_token):
    d = {"Authorization": f"Bearer {doctor_token}"}
    rec = client.post("/api/evaluate/p_obvious_1", headers=d).json()
    assert client.post("/api/escalations/nope", json={"recommendation": rec}, headers=d).status_code == 404


def test_admin_user_management(admin_token, nurse_token):
    a = {"Authorization": f"Bearer {admin_token}"}
    assert client.get("/api/admin/users", headers={"Authorization": f"Bearer {nurse_token}"}).status_code == 403

    bad_role = client.post("/api/admin/users", json={"username": "x", "password": "longenough", "role": "Root"}, headers=a)
    assert bad_role.status_code == 422
    weak = client.post("/api/admin/users", json={"username": "x", "password": "short", "role": "Nurse"}, headers=a)
    assert weak.status_code == 422

    ok = client.post("/api/admin/users", json={"username": "temp_nurse", "password": "longenough", "role": "Nurse"}, headers=a)
    assert ok.status_code == 200
    users = client.get("/api/admin/users", headers=a).json()
    uid = next(u["id"] for u in users if u["username"] == "temp_nurse")
    assert client.delete(f"/api/admin/users/{uid}", headers=a).status_code == 200


def test_login_rate_limit():
    """11th login attempt within a minute from one IP is throttled."""
    codes = [client.post("/api/login", data={"username": "ghost", "password": "x"}).status_code for _ in range(14)]
    assert 429 in codes


def test_websocket_requires_valid_token(doctor_token):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/vitals?token=bogus"):
            pass
    with client.websocket_connect(f"/ws/vitals?token={doctor_token}"):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ERROR BOUNDARY
# ─────────────────────────────────────────────────────────────────────────────

def test_unhandled_error_returns_generic_json_500_with_cors():
    """An unexpected exception must not leak internals and must keep CORS headers."""
    def boom():
        raise RuntimeError("secret internal detail: /etc/passwd")

    app.add_api_route("/api/_test_boom", boom, methods=["GET"])
    res = client.get("/api/_test_boom", headers={"Origin": "http://localhost:3000"})
    assert res.status_code == 500
    body = res.json()
    assert body["detail"] == "Internal server error"
    assert "secret internal detail" not in res.text
    assert body["request_id"] == res.headers["X-Request-ID"]
    assert res.headers.get("access-control-allow-origin") in ("*", "http://localhost:3000")


def test_validation_errors_are_422_not_500(doctor_token):
    """Malformed request bodies are rejected by Pydantic before reaching business logic."""
    headers = {"Authorization": f"Bearer {doctor_token}"}
    res = client.post("/api/chat", json={"nope": 1}, headers=headers)
    assert res.status_code == 422
    assert client.get("/api/patients/does-not-exist", headers=headers).status_code == 404
