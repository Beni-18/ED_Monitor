from models import VitalSigns

def calculate_news2(vitals: VitalSigns) -> dict:
    score = 0
    details = {}
    
    # Resp Rate
    if vitals.resp_rate is not None:
        rr = vitals.resp_rate
        if rr <= 8: s = 3
        elif 9 <= rr <= 11: s = 1
        elif 12 <= rr <= 20: s = 0
        elif 21 <= rr <= 24: s = 2
        else: s = 3
        score += s
        details['resp_rate'] = s
        
    # SpO2
    if vitals.spo2 is not None:
        spo2 = vitals.spo2
        if spo2 <= 91: s = 3
        elif 92 <= spo2 <= 93: s = 2
        elif 94 <= spo2 <= 95: s = 1
        else: s = 0
        score += s
        details['spo2'] = s
        
    # Systolic BP
    if vitals.bp_systolic is not None:
        sbp = vitals.bp_systolic
        if sbp <= 90: s = 3
        elif 91 <= sbp <= 100: s = 2
        elif 101 <= sbp <= 110: s = 1
        elif 111 <= sbp <= 219: s = 0
        else: s = 3
        score += s
        details['bp_systolic'] = s
        
    # HR
    if vitals.hr is not None:
        hr = vitals.hr
        if hr <= 40: s = 3
        elif 41 <= hr <= 50: s = 1
        elif 51 <= hr <= 90: s = 0
        elif 91 <= hr <= 110: s = 1
        elif 111 <= hr <= 130: s = 2
        else: s = 3
        score += s
        details['hr'] = s
        
    # Temp
    if vitals.temp is not None:
        t = vitals.temp
        if t <= 35.0: s = 3
        elif 35.1 <= t <= 36.0: s = 1
        elif 36.1 <= t <= 38.0: s = 0
        elif 38.1 <= t <= 39.0: s = 1
        else: s = 2
        score += s
        details['temp'] = s
        
    # Consciousness
    if vitals.consciousness_level is not None:
        c = vitals.consciousness_level.upper()
        if c == 'A': s = 0
        else: s = 3
        score += s
        details['consciousness_level'] = s

    # Clinical risk
    if score >= 7:
        risk = "High"
    elif score >= 5:
        risk = "Medium"
    else:
        risk = "Low"
        
    return {
        "total_score": score,
        "details": details,
        "risk_level": risk
    }
