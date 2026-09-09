import random
from datetime import datetime, timedelta
from models import Patient, PatientObservation, VitalSigns

def generate_patients() -> list[Patient]:
    base_time = datetime.now() - timedelta(hours=24)
    patients = []
    
    # 3 Stable Patients
    for i in range(1, 4):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j*2)
            obs.append(PatientObservation(
                patient_id=f"p_stable_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=random.randint(60, 80),
                    bp_systolic=random.randint(110, 130),
                    bp_diastolic=random.randint(70, 85),
                    resp_rate=random.randint(12, 18),
                    temp=random.uniform(36.5, 37.2),
                    spo2=random.uniform(97, 100),
                    consciousness_level="A"
                ),
                nursing_notes="Patient appears stable and resting quietly."
            ))
        patients.append(Patient(patient_id=f"p_stable_{i}", name=f"Stable Patient {i}", bed_number=f"B{i}", admission_time=base_time, observations=obs))

    # 2 Obvious Deterioration
    for i in range(1, 3):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j*2)
            hr = 80 + j * 15 # 80, 95, 110, 125, 140, 155
            spo2 = 98 - j * 3 # 98, 95, 92, 89, 86, 83
            obs.append(PatientObservation(
                patient_id=f"p_obvious_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=hr,
                    bp_systolic=120 - j * 10,
                    bp_diastolic=80 - j * 5,
                    resp_rate=16 + j * 4,
                    temp=37.0,
                    spo2=spo2,
                    consciousness_level="A" if j < 4 else "V"
                ),
                nursing_notes="Patient looks increasingly unwell, breathing is labored." if j > 3 else "Patient resting."
            ))
        patients.append(Patient(patient_id=f"p_obvious_{i}", name=f"Obvious Patient {i}", bed_number=f"O{i}", admission_time=base_time, observations=obs))

    # 3 Subtle Deterioration (trending bad, borderline values, incomplete history)
    for i in range(1, 4):
        obs = []
        for j in range(6):
            t = base_time + timedelta(hours=j*2)
            # HR goes from 80 to 95. RR from 16 to 20. SpO2 from 98 to 94. 
            # These are within normal or mild NEWS2 scoring, but the trend + notes suggest sepsis/shock
            obs.append(PatientObservation(
                patient_id=f"p_subtle_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=80 + j * 3,
                    bp_systolic=115 - j * 2,
                    bp_diastolic=75 - j * 2,
                    resp_rate=16 + j,
                    temp=37.2 + j * 0.1,
                    spo2=98 - j * 0.8,
                    consciousness_level="A"
                ),
                nursing_notes="Patient feels vaguely unwell, slightly clammy. Family says 'not themselves' but we lack full history." if j > 3 else "No acute distress, but somewhat restless.",
                is_incomplete_history=True
            ))
        patients.append(Patient(patient_id=f"p_subtle_{i}", name=f"Subtle Patient {i}", bed_number=f"S{i}", admission_time=base_time, observations=obs))

    # 2 Severe Missing Data
    for i in range(1, 3):
        obs = []
        for j in range(5):
            t = base_time + timedelta(hours=j*2)
            is_unconscious = True if j > 2 else False
            is_distressed = True if j <= 2 else False
            obs.append(PatientObservation(
                patient_id=f"p_missing_{i}",
                timestamp=t,
                vitals=VitalSigns(
                    hr=None if j > 1 else 90,
                    bp_systolic=None,
                    bp_diastolic=None,
                    resp_rate=None if j > 2 else 20,
                    temp=None,
                    spo2=None,
                    consciousness_level="U" if is_unconscious else "A"
                ),
                nursing_notes="Patient combative, unable to obtain vitals." if j <= 2 else "Patient unresponsive, missing most monitoring due to equipment failure.",
                is_unconscious=is_unconscious,
                is_distressed=is_distressed,
                is_incomplete_history=True
            ))
        patients.append(Patient(patient_id=f"p_missing_{i}", name=f"Missing Patient {i}", bed_number=f"M{i}", admission_time=base_time, observations=obs))

    return patients

CLINICAL_GUIDELINES = [
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
    "Malignant Arrhythmias: Sudden jumps in heart rate alternating with normal rates could be paroxysmal arrhythmias affecting cardiac output."
]
