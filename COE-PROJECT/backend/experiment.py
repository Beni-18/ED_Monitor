"""
experiment.py — AI vs. NEWS2 Baseline Benchmark Evaluation

Runs all 8 patient archetypes through both the AI pipeline and NEWS2 baseline,
then computes per-archetype and aggregate detection metrics including:
- Detection Rate (Sensitivity / Recall)
- False-Positive Rate (1 - Specificity)
- Precision
- F1 Score
- Detection Rate Improvement (AI vs Baseline)
"""
import json
from dataset import generate_patients
from vector_store import initialize_vector_store
from agent import app as agent_app

# Ground truth: which patient archetypes are truly at risk (POSITIVE cases)
POSITIVE_ARCHETYPES = {"obvious", "subtle", "missing", "hypoxia", "comp_shock", "elderly"}
NEGATIVE_ARCHETYPES = {"stable", "bradycardia"}

def get_archetype(patient_id: str) -> str:
    """Extract archetype key from patient_id string."""
    pid = patient_id.lower()
    if pid.startswith("p_stable_"):
        return "stable"
    elif pid.startswith("p_obvious_"):
        return "obvious"
    elif pid.startswith("p_subtle_"):
        return "subtle"
    elif pid.startswith("p_missing_"):
        return "missing"
    elif pid.startswith("p_hypoxia_"):
        return "hypoxia"
    elif pid.startswith("p_comp_shock_"):
        return "comp_shock"
    elif pid.startswith("p_bradycardia_"):
        return "bradycardia"
    elif pid.startswith("p_elderly_"):
        return "elderly"
    else:
        return "unknown"

def compute_metrics(tp: int, fp: int, fn: int, tn: int) -> dict:
    """Compute precision, recall, specificity, F1, false alert rate."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    false_alert_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    detection_rate = recall  # Also known as sensitivity

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "detection_rate": round(detection_rate, 4),
        "false_alert_rate": round(false_alert_rate, 4),
        "precision": round(precision, 4),
        "f1_score": round(f1, 4),
        "specificity": round(specificity, 4)
    }

def run_experiment():
    initialize_vector_store()
    patients = generate_patients()

    # Aggregate counters
    baseline_tp = baseline_fp = baseline_fn = baseline_tn = 0
    ai_tp = ai_fp = ai_fn = ai_tn = 0

    # Per-archetype counters
    archetype_stats = {}

    for p in patients:
        archetype = get_archetype(p.patient_id)
        gt_positive = archetype in POSITIVE_ARCHETYPES

        if archetype not in archetype_stats:
            archetype_stats[archetype] = {
                "baseline": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
                "ai": {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
            }

        latest_obs = p.observations[-1]
        state = {"patient": p, "current_obs": latest_obs}

        result = agent_app.invoke(state)
        rec = result["final_recommendation"]

        # ── Baseline NEWS2 prediction ──────────────────────────────────────
        baseline_pred = rec.baseline_would_flag  # True if NEWS2 ≥ 5
        if gt_positive:
            if baseline_pred:
                baseline_tp += 1
                archetype_stats[archetype]["baseline"]["tp"] += 1
            else:
                baseline_fn += 1
                archetype_stats[archetype]["baseline"]["fn"] += 1
        else:
            if baseline_pred:
                baseline_fp += 1
                archetype_stats[archetype]["baseline"]["fp"] += 1
            else:
                baseline_tn += 1
                archetype_stats[archetype]["baseline"]["tn"] += 1

        # ── AI LangGraph prediction ────────────────────────────────────────
        # High = confirmed positive. Medium + Unknown = escalation-worthy positive.
        ai_pred = rec.risk_level in ["High", "Medium", "Unknown"]
        if gt_positive:
            if ai_pred:
                ai_tp += 1
                archetype_stats[archetype]["ai"]["tp"] += 1
            else:
                ai_fn += 1
                archetype_stats[archetype]["ai"]["fn"] += 1
        else:
            if ai_pred:
                ai_fp += 1
                archetype_stats[archetype]["ai"]["fp"] += 1
            else:
                ai_tn += 1
                archetype_stats[archetype]["ai"]["tn"] += 1

    # ── Aggregate metrics ─────────────────────────────────────────────────
    baseline_metrics = compute_metrics(baseline_tp, baseline_fp, baseline_fn, baseline_tn)
    ai_metrics = compute_metrics(ai_tp, ai_fp, ai_fn, ai_tn)

    # ── Per-archetype metrics ─────────────────────────────────────────────
    per_archetype = {}
    for arch, stats in archetype_stats.items():
        per_archetype[arch] = {
            "ground_truth": "positive" if arch in POSITIVE_ARCHETYPES else "negative",
            "baseline": compute_metrics(**stats["baseline"]),
            "ai": compute_metrics(**stats["ai"])
        }

    results = {
        "total_patients": len(patients),
        "baseline": baseline_metrics,
        "ai": ai_metrics,
        "detection_rate_improvement": round(ai_metrics["detection_rate"] - baseline_metrics["detection_rate"], 4),
        "false_alert_reduction": round(baseline_metrics["false_alert_rate"] - ai_metrics["false_alert_rate"], 4),
        "f1_improvement": round(ai_metrics["f1_score"] - baseline_metrics["f1_score"], 4),
        "per_archetype": per_archetype
    }

    with open("experiment_results.json", "w") as f:
        json.dump(results, f, indent=4)

    print("=" * 60)
    print("EXPERIMENT COMPLETE — Results saved to experiment_results.json")
    print("=" * 60)
    print(f"Total Patients Evaluated: {len(patients)}")
    print()
    print(f"{'Metric':<35} {'Baseline':>10} {'AI':>10}")
    print("-" * 60)
    for key in ["detection_rate", "false_alert_rate", "precision", "f1_score"]:
        print(f"{key:<35} {baseline_metrics[key]:>10.1%} {ai_metrics[key]:>10.1%}")
    print()
    print(f"Detection Rate Improvement: +{results['detection_rate_improvement']:.1%} over NEWS2 baseline")
    print(f"False Alert Reduction:       {results['false_alert_reduction']:.1%}")
    print(f"F1 Score Improvement:       +{results['f1_improvement']:.4f}")
    print()
    print("Per-Archetype AI Detection Rates:")
    for arch, data in per_archetype.items():
        ai_dr = data["ai"]["detection_rate"]
        bl_dr = data["baseline"]["detection_rate"]
        gt = data["ground_truth"]
        marker = "[POSITIVE]" if gt == "positive" else "[NEGATIVE]"
        print(f"  {arch:<20} {marker} AI: {ai_dr:.0%}  |  Baseline: {bl_dr:.0%}")

if __name__ == "__main__":
    run_experiment()
