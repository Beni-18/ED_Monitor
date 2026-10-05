"""
test_agent.py — Unit Tests for LangGraph Agent Pipeline Nodes

Tests each LangGraph node in isolation with synthetic patient data,
verifying correct behavior for all 8 clinical archetypes including
edge cases like silent hypoxia and drug-induced bradycardia.

Run with: pytest test_agent.py -v
"""
import pytest
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from models import Patient, PatientObservation, VitalSigns
from agent import (
    assess_missing_data,
    compute_baseline,
    analyze_trends,
    route_after_missing_data
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FACTORIES
# ─────────────────────────────────────────────────────────────────────────────

def make_obs(patient_id="test_patient", hr=72, bp_sys=120, bp_dia=80,
             rr=16, temp=36.8, spo2=98.0, consciousness="A",
             notes="Resting comfortably", unconscious=False, distressed=False,
             incomplete_history=False, offset_hours=0):
    return PatientObservation(
        patient_id=patient_id,
        timestamp=datetime.now() + timedelta(hours=offset_hours),
        vitals=VitalSigns(
            hr=hr, bp_systolic=bp_sys, bp_diastolic=bp_dia,
            resp_rate=rr, temp=temp, spo2=spo2, consciousness_level=consciousness
        ),
        nursing_notes=notes,
        is_unconscious=unconscious,
        is_distressed=distressed,
        is_incomplete_history=incomplete_history
    )


def make_state(obs, extra_obs=None, patient_id="test_patient"):
    all_obs = [obs] + (extra_obs or [])
    patient = Patient(
        patient_id=patient_id,
        name="Test Patient",
        bed_number="T1",
        admission_time=datetime.now(),
        observations=all_obs
    )
    return {"patient": patient, "current_obs": obs, "node_timings": {}}


# ─────────────────────────────────────────────────────────────────────────────
# NODE 1: assess_missing_data TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestAssessMissingData:

    def test_no_missing_vitals(self):
        """Stable patient with all vitals present — risk should be 0."""
        obs = make_obs()
        state = make_state(obs)
        result = assess_missing_data(state)
        assert result["missing_data_risk"] == 0.0
        assert result["missing_measurements"] == []

    def test_partial_missing_vitals_routes_to_baseline(self):
        """3 missing vitals → risk = 4.5 → routes to compute_baseline."""
        obs = make_obs(hr=None, bp_sys=None, bp_dia=None)
        state = make_state(obs)
        result = assess_missing_data(state)
        assert "hr" in result["missing_measurements"]
        assert "bp_systolic" in result["missing_measurements"]
        assert "bp_diastolic" in result["missing_measurements"]
        assert result["missing_data_risk"] == pytest.approx(4.5)
        # Should NOT fast-track (risk < 8.0)
        assert result["missing_data_risk"] < 8.0

    def test_critical_missing_data_fast_tracks(self):
        """6+ missing vitals + unconscious → risk ≥ 8.0 → fast-track."""
        obs = PatientObservation(
            patient_id="crit",
            timestamp=datetime.now(),
            vitals=VitalSigns(
                hr=None, bp_systolic=None, bp_diastolic=None,
                resp_rate=None, temp=None, spo2=None, consciousness_level="U"
            ),
            nursing_notes="Unresponsive",
            is_unconscious=True,
            is_distressed=False
        )
        state = {"patient": Patient(patient_id="crit", name="Crit", bed_number="C1",
                                    admission_time=datetime.now(), observations=[obs]),
                 "current_obs": obs, "node_timings": {}}
        result = assess_missing_data(state)
        assert result["missing_data_risk"] >= 8.0
        # Should fast-track
        assert route_after_missing_data(result) == "generate_recommendation"

    def test_unconscious_adds_risk(self):
        """Unconscious flag adds 3.0 to the risk score."""
        obs = make_obs(unconscious=True)
        state = make_state(obs)
        result = assess_missing_data(state)
        assert result["missing_data_risk"] == pytest.approx(3.0)

    def test_distressed_adds_risk(self):
        """Distressed flag adds 2.0 to the risk score."""
        obs = make_obs(distressed=True)
        state = make_state(obs)
        result = assess_missing_data(state)
        assert result["missing_data_risk"] == pytest.approx(2.0)

    def test_risk_capped_at_10(self):
        """Risk score cannot exceed 10.0."""
        obs = PatientObservation(
            patient_id="max_risk",
            timestamp=datetime.now(),
            vitals=VitalSigns(
                hr=None, bp_systolic=None, bp_diastolic=None,
                resp_rate=None, temp=None, spo2=None, consciousness_level=None
            ),
            nursing_notes="Combative",
            is_unconscious=True,
            is_distressed=True
        )
        state = {"patient": Patient(patient_id="max_risk", name="Max", bed_number="X",
                                    admission_time=datetime.now(), observations=[obs]),
                 "current_obs": obs, "node_timings": {}}
        result = assess_missing_data(state)
        assert result["missing_data_risk"] == 10.0  # Capped

    def test_node_timing_recorded(self):
        """assess_missing_data must record its execution time in node_timings."""
        obs = make_obs()
        state = make_state(obs)
        result = assess_missing_data(state)
        assert "assess_missing_data" in result["node_timings"]
        assert result["node_timings"]["assess_missing_data"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# NODE 1 ROUTING TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestRouteAfterMissingData:

    def test_fast_track_at_threshold(self):
        assert route_after_missing_data({"missing_data_risk": 8.0}) == "generate_recommendation"

    def test_fast_track_above_threshold(self):
        assert route_after_missing_data({"missing_data_risk": 9.5}) == "generate_recommendation"

    def test_continues_to_baseline_below_threshold(self):
        assert route_after_missing_data({"missing_data_risk": 7.9}) == "compute_baseline"

    def test_continues_to_baseline_zero_risk(self):
        assert route_after_missing_data({"missing_data_risk": 0.0}) == "compute_baseline"


# ─────────────────────────────────────────────────────────────────────────────
# NODE 2: compute_baseline TESTS (NEWS2)
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeBaseline:

    def test_stable_patient_low_news2(self):
        """Stable vitals should produce NEWS2 = 0 (Low risk)."""
        obs = make_obs(hr=70, bp_sys=125, bp_dia=80, rr=16, temp=36.8, spo2=98.5)
        state = make_state(obs)
        state["missing_data_risk"] = 0.0
        state["missing_measurements"] = []
        result = compute_baseline(state)
        assert result["news2_result"]["total_score"] == 0
        assert result["news2_result"]["risk_level"] == "Low"

    def test_obvious_deterioration_high_news2(self):
        """HR=155, SpO2=83, RR=36, BP=70 should produce NEWS2 ≥ 7 (High risk)."""
        obs = make_obs(hr=155, bp_sys=70, bp_dia=45, rr=36, temp=37.0, spo2=83.0, consciousness="V")
        state = make_state(obs)
        state["missing_data_risk"] = 0.0
        state["missing_measurements"] = []
        result = compute_baseline(state)
        assert result["news2_result"]["total_score"] >= 7
        assert result["news2_result"]["risk_level"] == "High"

    def test_bradycardia_falsely_scored(self):
        """Drug-induced bradycardia (HR=48) with all other normal vitals.
        NEWS2 gives 1 point for HR — baseline correctly identifies it as Low."""
        obs = make_obs(hr=48, bp_sys=132, bp_dia=82, rr=14, temp=36.7, spo2=98.0)
        state = make_state(obs)
        state["missing_data_risk"] = 0.0
        state["missing_measurements"] = []
        result = compute_baseline(state)
        # HR 41-50 → NEWS2 score 1 only; everything else → 0
        assert result["news2_result"]["total_score"] == 1
        assert result["news2_result"]["risk_level"] == "Low"

    def test_node_timing_recorded(self):
        obs = make_obs()
        state = make_state(obs)
        state["missing_data_risk"] = 0.0
        state["missing_measurements"] = []
        result = compute_baseline(state)
        assert "compute_baseline" in result["node_timings"]
        assert result["node_timings"]["compute_baseline"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# NODE 4: analyze_trends TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeTrends:

    def test_obvious_deterioration_flagged(self):
        """HR rises 75 bpm and SpO2 drops 15% over 6 observations → deteriorating."""
        obs_list = [
            make_obs(hr=80, spo2=98, bp_sys=120, rr=16, offset_hours=0),
            make_obs(hr=95, spo2=95, bp_sys=110, rr=20, offset_hours=2),
            make_obs(hr=110, spo2=92, bp_sys=100, rr=24, offset_hours=4),
            make_obs(hr=125, spo2=89, bp_sys=90, rr=28, offset_hours=6),
            make_obs(hr=140, spo2=86, bp_sys=80, rr=32, offset_hours=8),
            make_obs(hr=155, spo2=83, bp_sys=70, rr=36, offset_hours=10),
        ]
        patient = Patient(
            patient_id="test",
            name="Test",
            bed_number="T1",
            admission_time=datetime.now(),
            observations=obs_list
        )
        state = {"patient": patient, "current_obs": obs_list[-1], "node_timings": {}}
        result = analyze_trends(state)
        assert result["trend_deteriorating"] is True

    def test_stable_patient_not_flagged(self):
        """Flat vitals over 6 observations → not deteriorating."""
        obs_list = [
            make_obs(hr=70 + i, spo2=98.0, bp_sys=122, rr=15, offset_hours=i * 2)
            for i in range(6)
        ]
        patient = Patient(
            patient_id="test_stable",
            name="Test Stable",
            bed_number="TS",
            admission_time=datetime.now(),
            observations=obs_list
        )
        state = {"patient": patient, "current_obs": obs_list[-1], "node_timings": {}}
        result = analyze_trends(state)
        # Only HR rises by 5 bpm (< 10 threshold) — not flagged
        assert result["trend_deteriorating"] is False

    def test_silent_hypoxia_flagged(self):
        """SpO2 drops from 96 to 87.5 while HR barely changes → deteriorating (SpO2 + mild RR rise)."""
        obs_list = [
            make_obs(hr=88, spo2=96.0, rr=17, offset_hours=0),
            make_obs(hr=90, spo2=93.5, rr=17, offset_hours=2),
            make_obs(hr=92, spo2=91.0, rr=18, offset_hours=4),
            make_obs(hr=94, spo2=89.0, rr=18, offset_hours=6),
            make_obs(hr=96, spo2=87.5, rr=19, offset_hours=8),
        ]
        patient = Patient(
            patient_id="test_hypoxia",
            name="Test Hypoxia",
            bed_number="TH",
            admission_time=datetime.now(),
            observations=obs_list
        )
        state = {"patient": patient, "current_obs": obs_list[-1], "node_timings": {}}
        result = analyze_trends(state)
        # SpO2 fell by 8.5% (> 2% threshold) — deteriorating due to SpO2
        assert result["trend_deteriorating"] is True

    def test_compensated_shock_flagged(self):
        """Rising HR (75→125) with stable BP — both HR and RR rise."""
        obs_list = [
            make_obs(hr=75, bp_sys=118, rr=16, spo2=97.0, offset_hours=0),
            make_obs(hr=85, bp_sys=116, rr=18, spo2=97.0, offset_hours=2),
            make_obs(hr=95, bp_sys=114, rr=20, spo2=96.5, offset_hours=4),
            make_obs(hr=105, bp_sys=112, rr=22, spo2=96.0, offset_hours=6),
            make_obs(hr=115, bp_sys=110, rr=24, spo2=95.5, offset_hours=8),
            make_obs(hr=125, bp_sys=108, rr=26, spo2=95.2, offset_hours=10),
        ]
        patient = Patient(
            patient_id="test_comp_shock",
            name="Test Comp Shock",
            bed_number="TC",
            admission_time=datetime.now(),
            observations=obs_list
        )
        state = {"patient": patient, "current_obs": obs_list[-1], "node_timings": {}}
        result = analyze_trends(state)
        # HR rises 50 bpm (> 10), RR rises 10/min (> 4) → deteriorating
        assert result["trend_deteriorating"] is True

    def test_single_observation_not_deteriorating(self):
        """Cannot determine trend from a single observation."""
        obs = make_obs(hr=70, spo2=98)
        state = make_state(obs)
        result = analyze_trends(state)
        assert result["trend_deteriorating"] is False

    def test_node_timing_recorded(self):
        obs_list = [make_obs(offset_hours=i) for i in range(3)]
        patient = Patient(patient_id="t", name="T", bed_number="T",
                         admission_time=datetime.now(), observations=obs_list)
        state = {"patient": patient, "current_obs": obs_list[-1], "node_timings": {}}
        result = analyze_trends(state)
        assert "analyze_trends" in result["node_timings"]
