import random
from datetime import datetime, timedelta
from models import Patient, PatientObservation, VitalSigns

# A pool of realistic patient names for richer dataset presentation
_FIRST_NAMES = [
    "James", "Sarah", "Michael", "Priya", "David", "Maria", "Robert", "Aisha",
    "William", "Chen", "Thomas", "Fatima", "John", "Emily", "Daniel", "Yuki",
    "Christopher", "Sophie", "Matthew", "Layla", "Andrew", "Zara", "Joseph",
    "Nina", "Charles", "Mei", "Mark", "Amara", "Paul", "Elena"
]
_LAST_NAMES = [
    "Hartwell", "Nair", "Brooks", "Okonkwo", "Fitzgerald", "Santos", "Patel",
    "Ibrahim", "Chen", "Murphy", "Wallace", "Rodriguez", "Kapoor", "Hansen",
    "Nakamura", "Thompson", "Al-Rashid", "Clarke", "Mensah", "Johansson"
]

def _random_name(seed: int) -> str:
    random.seed(seed * 7 + 13)
    return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

def generate_patients(scale_factor: int = 1) -> list[Patient]:
    base_time = datetime.now() - timedelta(hours=24)
    patients = []
    name_seed = 1

    # ─────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 1: STABLE (3 per scale unit)
    # All vitals in normal range, flat trend. Ground truth: NEGATIVE (Low risk)
    # NEWS2 correctly scores LOW. AI should also score LOW.
    # ─────────────────────────────────────────────────────────────────────────
    for i in range(1, 3 * scale_factor + 1):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j * 2)
            obs.append(PatientObservation(
                patient_id=f"p_stable_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=random.randint(62, 78),
                    bp_systolic=random.randint(112, 128),
                    bp_diastolic=random.randint(70, 82),
                    resp_rate=random.randint(13, 17),
                    temp=round(random.uniform(36.5, 37.1), 1),
                    spo2=round(random.uniform(97.5, 99.5), 1),
                    consciousness_level="A"
                ),
                nursing_notes="Patient resting comfortably. No acute distress noted."
            ))
        patients.append(Patient(
            patient_id=f"p_stable_{i}",
            name=_random_name(name_seed),
            bed_number=f"B{i}",
            admission_time=base_time,
            observations=obs
        ))
        name_seed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 2: OBVIOUS DETERIORATION (2 per scale unit)
    # Rapidly worsening HR, SpO2, BP. Ground truth: POSITIVE (High risk)
    # NEWS2 correctly scores HIGH (≥7). AI also scores HIGH.
    # ─────────────────────────────────────────────────────────────────────────
    for i in range(1, 2 * scale_factor + 1):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j * 2)
            hr = 80 + j * 15   # 80 → 80, 95, 110, 125, 140, 155
            spo2 = 98 - j * 3  # 98 → 95, 92, 89, 86, 83
            obs.append(PatientObservation(
                patient_id=f"p_obvious_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=hr,
                    bp_systolic=120 - j * 10,
                    bp_diastolic=80 - j * 5,
                    resp_rate=16 + j * 4,
                    temp=37.0,
                    spo2=round(spo2, 1),
                    consciousness_level="A" if j < 4 else "V"
                ),
                nursing_notes=(
                    "Patient looks increasingly unwell, breathing is labored. Very pale, diaphoretic."
                    if j > 3 else "Patient resting but appears uncomfortable."
                )
            ))
        patients.append(Patient(
            patient_id=f"p_obvious_{i}",
            name=_random_name(name_seed),
            bed_number=f"O{i}",
            admission_time=base_time,
            observations=obs
        ))
        name_seed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 3: SUBTLE SEPSIS TRAJECTORY (3 per scale unit)
    # Borderline trending vitals + vague nursing notes suggesting early sepsis.
    # Ground truth: POSITIVE. NEWS2 scores LOW-MEDIUM (2–4) — likely to miss.
    # AI catches trend + notes combination.
    # ─────────────────────────────────────────────────────────────────────────
    for i in range(1, 3 * scale_factor + 1):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j * 2)
            obs.append(PatientObservation(
                patient_id=f"p_subtle_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=80 + j * 3,           # 80 → 95 (gradual rise)
                    bp_systolic=115 - j * 2, # 115 → 103 (mild drop)
                    bp_diastolic=75 - j * 2,
                    resp_rate=16 + j,         # 16 → 21 (rising RR)
                    temp=round(37.2 + j * 0.15, 1),  # 37.2 → 38.0 (fever developing)
                    spo2=round(98 - j * 0.5, 1),     # 98 → 95.5 (mild drop)
                    consciousness_level="A"
                ),
                nursing_notes=(
                    "Patient feels vaguely unwell, slightly clammy. Family says 'not themselves'. "
                    "Incomplete history — care home resident, baseline unknown."
                    if j > 3 else
                    "No acute distress but somewhat restless. Slightly warm to touch."
                ),
                is_incomplete_history=True
            ))
        patients.append(Patient(
            patient_id=f"p_subtle_{i}",
            name=_random_name(name_seed),
            bed_number=f"S{i}",
            admission_time=base_time,
            observations=obs
        ))
        name_seed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 4: SEVERE MISSING DATA (2 per scale unit)
    # Unconscious / combative patient, most vitals unavailable.
    # Ground truth: POSITIVE (Unknown risk — requires immediate escalation).
    # NEWS2 cannot fully score. AI fast-tracks to generate_recommendation.
    # ─────────────────────────────────────────────────────────────────────────
    for i in range(1, 2 * scale_factor + 1):
        obs = []
        for j in range(5):
            t = base_time + timedelta(hours=j * 2)
            is_unconscious = j > 2
            is_distressed = j <= 2
            obs.append(PatientObservation(
                patient_id=f"p_missing_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=None if j > 1 else 90,
                    bp_systolic=None,
                    bp_diastolic=None,
                    resp_rate=None if j > 2 else 22,
                    temp=None,
                    spo2=None,
                    consciousness_level="U" if is_unconscious else "A"
                ),
                nursing_notes=(
                    "Patient combative, unable to obtain vitals. Refusing assessments."
                    if j <= 2 else
                    "Patient now unresponsive. Missing monitoring — equipment failure/combativeness."
                ),
                is_unconscious=is_unconscious,
                is_distressed=is_distressed,
                is_incomplete_history=True
            ))
        patients.append(Patient(
            patient_id=f"p_missing_{i}",
            name=_random_name(name_seed),
            bed_number=f"M{i}",
            admission_time=base_time,
            observations=obs
        ))
        name_seed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 5: SILENT HYPOXIA (2 per scale unit) — NEW
    # SpO2 drops significantly while HR and RR remain near-normal.
    # The patient has no subjective respiratory distress ("happy hypoxic").
    # Ground truth: POSITIVE. NEWS2 may score MEDIUM (SpO2 component only).
    # KEY TEST: AI catches SpO2 trend despite absence of typical distress markers.
    # ─────────────────────────────────────────────────────────────────────────
    for i in range(1, 2 * scale_factor + 1):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j * 2)
            obs.append(PatientObservation(
                patient_id=f"p_hypoxia_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=88 + j * 2,           # Mild HR rise: 88 → 98 (within normal)
                    bp_systolic=125 - j,     # Minimal BP drop: 125 → 120 (normal)
                    bp_diastolic=82 - j,
                    resp_rate=17 + j // 2,   # Very mild RR rise: 17 → 19 (normal range)
                    temp=round(37.0 + j * 0.05, 1),
                    spo2=round(96 - j * 1.5, 1),  # 96 → 87.5 — CRITICAL DROP but no RR change
                    consciousness_level="A"
                ),
                nursing_notes=(
                    "Patient appears comfortable and conversant despite monitoring showing low O2. "
                    "Denies shortness of breath. Consistent with silent hypoxia pattern."
                    if j > 2 else
                    "Patient resting. No respiratory complaints. Slight O2 trend noted."
                )
            ))
        patients.append(Patient(
            patient_id=f"p_hypoxia_{i}",
            name=_random_name(name_seed),
            bed_number=f"H{i}",
            admission_time=base_time,
            observations=obs
        ))
        name_seed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 6: COMPENSATED SHOCK (2 per scale unit) — NEW
    # BP is maintained in normal range by a compensatory HR rise.
    # This is pre-shock: body is compensating for blood loss or vasodilation.
    # Ground truth: POSITIVE. NEWS2 scores LOW (BP is still normal).
    # KEY TEST: AI detects the rising HR trend compensating for normal BP.
    # ─────────────────────────────────────────────────────────────────────────
    for i in range(1, 2 * scale_factor + 1):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j * 2)
            obs.append(PatientObservation(
                patient_id=f"p_comp_shock_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=75 + j * 10,          # 75 → 125 (significant rise)
                    bp_systolic=118 - j * 2, # 118 → 106 (still normal — compensated)
                    bp_diastolic=75 - j * 2, # Slight drop
                    resp_rate=16 + j * 2,    # 16 → 26 (rising RR)
                    temp=round(36.8 - j * 0.1, 1),  # Slight temp drop (perfusion issue)
                    spo2=round(97 - j * 0.3, 1),    # Mild SpO2 drop: 97 → 95.2
                    consciousness_level="A"
                ),
                nursing_notes=(
                    "Patient increasingly restless. Skin appears mottled at extremities. "
                    "BP appears maintained but HR is climbing. Peripheral perfusion concerning."
                    if j > 3 else
                    "Patient complaining of dizziness when sitting up. Slight pallor."
                )
            ))
        patients.append(Patient(
            patient_id=f"p_comp_shock_{i}",
            name=_random_name(name_seed),
            bed_number=f"C{i}",
            admission_time=base_time,
            observations=obs
        ))
        name_seed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 7: DRUG-INDUCED BRADYCARDIA (1 per scale unit) — NEW
    # Patient on beta-blockers presents with low HR (45–55 bpm) as BASELINE.
    # This is not deterioration — it's medication effect.
    # Ground truth: NEGATIVE (stable). NEWS2 flags HIGH (HR ≤ 40–50 scores 3 points).
    # KEY TEST: AI should classify as Low/Stable given clinical context from notes.
    # Stress-tests FALSE-POSITIVE reduction.
    # ─────────────────────────────────────────────────────────────────────────
    for i in range(1, 1 * scale_factor + 1):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j * 2)
            obs.append(PatientObservation(
                patient_id=f"p_bradycardia_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=random.randint(44, 54),       # Consistently low but stable
                    bp_systolic=random.randint(124, 138),  # Normal BP
                    bp_diastolic=random.randint(78, 88),
                    resp_rate=random.randint(13, 16),      # Normal
                    temp=round(random.uniform(36.6, 37.0), 1),
                    spo2=round(random.uniform(97.0, 99.0), 1),
                    consciousness_level="A"
                ),
                nursing_notes=(
                    "Patient on bisoprolol 10mg for atrial fibrillation. Bradycardia is chronic "
                    "and medication-related. Patient feels well, denies symptoms. This is their "
                    "known baseline heart rate. No acute concern."
                )
            ))
        patients.append(Patient(
            patient_id=f"p_bradycardia_{i}",
            name=_random_name(name_seed),
            bed_number=f"D{i}",
            admission_time=base_time,
            observations=obs
        ))
        name_seed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 8: ELDERLY FRAIL / ATYPICAL PRESENTATION (2 per scale unit) — NEW
    # Elderly patient with chronic low-grade confusion and borderline vitals.
    # Vitals are borderline but NOT clearly deteriorating. AVPU slips to V.
    # Ground truth: POSITIVE (needs clinical assessment despite ambiguous numbers).
    # NEWS2 may score MEDIUM (AVPU=V gives 3 points). AI should evaluate context.
    # ─────────────────────────────────────────────────────────────────────────
    for i in range(1, 2 * scale_factor + 1):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j * 2)
            obs.append(PatientObservation(
                patient_id=f"p_elderly_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=random.randint(82, 96),         # Mildly elevated
                    bp_systolic=random.randint(104, 118),  # Low-normal for elderly
                    bp_diastolic=random.randint(64, 74),
                    resp_rate=random.randint(18, 22),   # Mildly elevated
                    temp=round(random.uniform(36.0, 36.8), 1),  # No fever (elderly may not mount one)
                    spo2=round(random.uniform(94.0, 96.5), 1),  # Low-normal
                    consciousness_level="V" if j > 2 else "A"
                ),
                nursing_notes=(
                    "84-year-old patient from nursing home. More confused than usual per family. "
                    "No obvious source of infection but baseline is difficult to establish. "
                    "Staff concerned but vitals individually appear borderline rather than critical."
                    if j > 2 else
                    "Elderly patient, slightly drowsy. Family at bedside. Incomplete medical history."
                ),
                is_incomplete_history=True
            ))
        patients.append(Patient(
            patient_id=f"p_elderly_{i}",
            name=_random_name(name_seed),
            bed_number=f"E{i}",
            admission_time=base_time,
            observations=obs
        ))
        name_seed += 1

    return patients


# ─────────────────────────────────────────────────────────────────────────────
# CLINICAL GUIDELINES (25 total — 15 original + 10 new for new archetypes)
# Embedded in ChromaDB as RAG context for the LangGraph retrieve_context node.
# ─────────────────────────────────────────────────────────────────────────────
CLINICAL_GUIDELINES = [
    # Original 15
    "Sepsis Recognition: Subtle upward trends in heart rate (even if < 100) and respiratory rate (e.g., from 14 to 20) combined with vague symptoms ('not themselves') and mild temperature elevation can indicate early sepsis.",
    "Hypovolemic Shock: A gradual decrease in systolic blood pressure along with a compensatory rise in heart rate suggests hypovolemia or occult bleeding, especially if history is incomplete.",
    "Respiratory Failure: Slowly trending oxygen saturation down from 98% to 94%, with increasing respiratory rate, may precede rapid decompensation.",
    "Missing Vitals: Inability to obtain blood pressure or oxygen saturation in a combative or restless patient is a red flag for hypoxia or poor perfusion until proven otherwise.",
    "Unconscious Unknowns: An unconscious patient with missing vital signs and no clear history requires immediate escalation to rule out intracranial events or severe toxic/metabolic crises.",
    "Subtle Deterioration in Elderly: Older adults may not mount a fever. A slight increase in confusion or restlessness with borderline tachycardia is often the only sign of serious infection.",
    "Compensated Shock: Normal blood pressure can be maintained by a rising heart rate for hours before a sudden collapse. Look at the trend, not just the absolute numbers.",
    "NEWS2 Limitations: The NEWS2 score may underestimate risk in patients with chronic baseline alterations, or when multiple parameters are just slightly off but trending together negatively.",
    "Incomplete History Risk: Patients arriving from care homes or found down without a history are at higher risk. Subtle signs like a changing trend in vital signs must be taken seriously.",
    "Pain vs Deterioration: Tachycardia might be due to pain, but if it steadily increases while respiratory rate also trends up, consider systemic deterioration.",
    "Equipment Failure: Repeatedly failing to get an SpO2 reading might not just be a cold finger; it can indicate central centralization of circulation due to shock.",
    "Tachypnea as an Early Sign: A rising respiratory rate is often the most sensitive and earliest indicator of critical illness, preceding changes in HR and BP.",
    "Altered Mental Status: A drop from 'Alert' to 'Voice' on the AVPU scale is a late and very concerning sign requiring immediate review.",
    "Silent Hypoxia: Patients may have dangerously low oxygen saturations without showing obvious respiratory distress, particularly in certain viral pneumonias.",
    "Malignant Arrhythmias: Sudden jumps in heart rate alternating with normal rates could be paroxysmal arrhythmias affecting cardiac output.",

    # 10 New guidelines for expanded archetypes
    "Drug-Induced Bradycardia: A patient on beta-blockers (e.g., bisoprolol, metoprolol) or digoxin may have a chronically low heart rate (45–60 bpm) as an expected medication effect. Always review the drug chart before escalating bradycardia. The NEWS2 score will overestimate risk in these patients.",
    "Beta-Blocker Effect: Beta-blockers suppress the compensatory tachycardia response to shock. A patient on beta-blockers in septic shock may present with a paradoxically 'normal' or low heart rate, masking deterioration severity.",
    "Silent Hypoxia — Viral Pneumonia Pattern: Patients with certain respiratory infections may have SpO2 values of 85–92% while remaining comfortable and conversant, with minimal increase in respiratory rate. This 'happy hypoxic' presentation is dangerous and requires oxygen therapy and senior review even without subjective distress.",
    "Compensated Shock Recognition: Rising heart rate with maintained blood pressure in a previously normotensive patient should be treated as pre-shock until proven otherwise. Administer IV fluids and perform a fluid responsiveness assessment. Do not wait for BP to drop.",
    "Elderly Confusion as Sepsis Marker: In patients over 75, new or worsening confusion (AVPU shifting from A to V) without clear neurological cause should be presumed to be sepsis, urinary tract infection, or pneumonia until ruled out by blood cultures and urinalysis.",
    "SpO2 Trending in Silent Hypoxia: A fall in SpO2 from baseline even within 'acceptable' ranges (e.g., 97% → 93%) must be considered significant if accompanied by nursing notes indicating patient appears 'comfortable' — this dissociation between subjective well-being and objective hypoxia is the hallmark of silent hypoxia.",
    "Mottled Skin and Capillary Refill: Mottled extremities and capillary refill time >2 seconds are bedside signs of poor peripheral perfusion that may precede measurable changes in blood pressure. These clinical signs must prompt urgent escalation.",
    "Frailty and Vital Signs Interpretation: Frail elderly patients may have a lower baseline blood pressure and heart rate. A systolic BP of 108 mmHg may be significantly hypotensive for a patient whose normal baseline is 145 mmHg. Document and compare against known baseline values where available.",
    "SpO2 Absolute Value vs Trend: An SpO2 of 94% in isolation may not trigger alarm, but a trend from 98% to 94% over 12 hours in a patient with risk factors (smoking history, COPD, recent viral illness) represents a 4% fall that warrants investigation.",
    "Nursing Notes as Clinical Context: Qualitative nursing observations ('patient looks unwell', 'family says not themselves', 'mottled skin') are high-value clinical signals. An AI system should weight these notes heavily when vital sign thresholds alone are borderline, as they capture clinical gestalt that numerical scores cannot."
]
