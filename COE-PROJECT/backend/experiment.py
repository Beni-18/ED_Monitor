import json
from dataset import generate_patients
from vector_store import initialize_vector_store
from agent import app as agent_app

def run_experiment():
    initialize_vector_store()
    patients = generate_patients()
    
    baseline_tp = 0
    baseline_fp = 0
    baseline_fn = 0
    baseline_tn = 0
    
    ai_tp = 0
    ai_fp = 0
    ai_fn = 0
    ai_tn = 0
    
    for p in patients:
        # Ground truth
        if "stable" in p.patient_id:
            gt_positive = False
        else:
            gt_positive = True
            
        latest_obs = p.observations[-1]
        state = {
            "patient": p,
            "current_obs": latest_obs
        }
        
        result = agent_app.invoke(state)
        rec = result["final_recommendation"]
        
        # Baseline
        baseline_pred = rec.baseline_would_flag
        if gt_positive:
            if baseline_pred: baseline_tp += 1
            else: baseline_fn += 1
        else:
            if baseline_pred: baseline_fp += 1
            else: baseline_tn += 1
            
        # AI
        # AI considers High risk or Unknown (fallback) as positive escalation
        ai_pred = rec.risk_level in ["High", "Unknown"]
        if gt_positive:
            if ai_pred: ai_tp += 1
            else: ai_fn += 1
        else:
            if ai_pred: ai_fp += 1
            else: ai_tn += 1
            
    # Metrics
    baseline_detection_rate = baseline_tp / (baseline_tp + baseline_fn) if (baseline_tp + baseline_fn) > 0 else 0
    ai_detection_rate = ai_tp / (ai_tp + ai_fn) if (ai_tp + ai_fn) > 0 else 0
    
    baseline_false_alert_rate = baseline_fp / (baseline_fp + baseline_tn) if (baseline_fp + baseline_tn) > 0 else 0
    ai_false_alert_rate = ai_fp / (ai_fp + ai_tn) if (ai_fp + ai_tn) > 0 else 0
    
    results = {
        "baseline": {
            "tp": baseline_tp,
            "fp": baseline_fp,
            "fn": baseline_fn,
            "tn": baseline_tn,
            "detection_rate": baseline_detection_rate,
            "false_alert_rate": baseline_false_alert_rate
        },
        "ai": {
            "tp": ai_tp,
            "fp": ai_fp,
            "fn": ai_fn,
            "tn": ai_tn,
            "detection_rate": ai_detection_rate,
            "false_alert_rate": ai_false_alert_rate
        },
        "detection_rate_improvement": ai_detection_rate - baseline_detection_rate
    }
    
    with open("experiment_results.json", "w") as f:
        json.dump(results, f, indent=4)
        
    print("Experiment completed. Results saved to experiment_results.json")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    run_experiment()
