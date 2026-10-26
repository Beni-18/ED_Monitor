"""
experiment.py — AI vs. NEWS2 Baseline Benchmark Evaluation

Runs two patient sets through the LangGraph pipeline and the NEWS2 baseline:

  development  the 8 deterministic archetypes from dataset.generate_patients()
               (the agent, guidelines and prompt were tuned against these)
  holdout      80 randomised patients from dataset.generate_holdout_patients()
               with different archetypes, noise and note wording, including hard
               negatives. This is the number to quote.

Reported per set and per archetype: detection rate (sensitivity) with a 95% Wilson
interval, false-alert rate, precision, F1, specificity.

Two AI operating points are reported:
  ai         escalate on High, Medium or Unknown (what the app actually does)
  ai_strict  escalate on High or Medium only (Unknown is not counted as a detection)

Evaluations where the Groq call failed (confidence_score == 0) are EXCLUDED from the
confusion matrices and listed under `llm_failures`, so API errors can never be
counted as detections.

Usage: python experiment.py            (needs GROQ_API_KEY in backend/.env)
"""
import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from dataset import (
    generate_patients, generate_holdout_patients, HOLDOUT_POSITIVE, HOLDOUT_NEGATIVE
)
from vector_store import initialize_vector_store
import agent
import llm_limits
from agent import app as agent_app

# Dev-set patients within an archetype are near-identical templates, so a few per
# archetype carry the same information as ten. --dev-scale 10 evaluates the full
# 170-patient corpus the API seeds.
DEFAULT_DEV_SCALE = 3
WORKERS = int(os.environ.get("BATCH_WORKERS", "6"))
RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiment_results.json")

# Ground truth: which archetypes are truly at risk (POSITIVE cases)
DEV_POSITIVE = {"obvious", "subtle", "missing", "hypoxia", "comp_shock", "elderly"}
DEV_NEGATIVE = {"stable", "bradycardia"}

_DEV_PREFIXES = {
    "p_stable_": "stable", "p_obvious_": "obvious", "p_subtle_": "subtle",
    "p_missing_": "missing", "p_hypoxia_": "hypoxia", "p_comp_shock_": "comp_shock",
    "p_bradycardia_": "bradycardia", "p_elderly_": "elderly",
}


def get_archetype(patient_id: str) -> str:
    """Extract archetype key from a patient_id string."""
    pid = patient_id.lower()
    for prefix, key in _DEV_PREFIXES.items():
        if pid.startswith(prefix):
            return key
    if pid.startswith("h_"):
        name = pid[2:].rsplit("_", 1)[0]
        if name in HOLDOUT_POSITIVE or name in HOLDOUT_NEGATIVE:
            return name
    return "unknown"


def is_positive(archetype: str) -> bool:
    return archetype in DEV_POSITIVE or archetype in HOLDOUT_POSITIVE


def wilson_interval(successes: int, n: int, z: float = 1.96) -> list:
    """95% Wilson score interval for a proportion; [0, 0] when n == 0."""
    if n == 0:
        return [0.0, 0.0]
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def compute_metrics(tp: int, fp: int, fn: int, tn: int) -> dict:
    """Compute precision, recall, specificity, F1, false alert rate."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    false_alert_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "detection_rate": round(recall, 4),
        "detection_rate_ci95": wilson_interval(tp, tp + fn),
        "false_alert_rate": round(false_alert_rate, 4),
        "precision": round(precision, 4),
        "f1_score": round(f1, 4),
        "specificity": round(specificity, 4)
    }


def _evaluate_one(patient):
    state = {"patient": patient, "current_obs": patient.observations[-1], "node_timings": {}}
    try:
        return patient, agent_app.invoke(state)["final_recommendation"], None
    except Exception as e:  # graph-level failure, distinct from an LLM API error
        return patient, None, str(e)


def _confusion(counts: dict, positive: bool, predicted: bool):
    key = ("tp" if predicted else "fn") if positive else ("fp" if predicted else "tn")
    counts[key] += 1


def evaluate_set(patients: list, label: str) -> dict:
    """Run one patient set and return aggregate + per-archetype metrics."""
    print(f"[{label}] evaluating {len(patients)} patients with {WORKERS} workers...", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        outcomes = list(pool.map(_evaluate_one, patients))

        # One more pass for evaluations that still failed after the in-call retries
        retry = [p for p, rec, err in outcomes if rec is None or rec.confidence_score == 0.0]
        if retry:
            print(f"[{label}] retrying {len(retry)} failed evaluations...", flush=True)
            redone = {p.patient_id: (p, rec, err) for p, rec, err in pool.map(_evaluate_one, retry)}
            outcomes = [redone.get(p.patient_id, (p, rec, err)) for p, rec, err in outcomes]

    def zero():
        return {"tp": 0, "fp": 0, "fn": 0, "tn": 0}

    agg = {"baseline": zero(), "ai": zero(), "ai_strict": zero()}
    per_arch = {}
    failures = []

    for patient, rec, err in outcomes:
        arch = get_archetype(patient.patient_id)
        if rec is None or rec.confidence_score == 0.0:
            failures.append({"patient_id": patient.patient_id, "reason": err or rec.reasoning[:160]})
            continue

        gt = is_positive(arch)
        preds = {
            "baseline": rec.baseline_would_flag,                                # NEWS2 >= 5
            "ai": rec.risk_level in ("High", "Medium", "Unknown"),              # app behaviour
            "ai_strict": rec.risk_level in ("High", "Medium"),                  # Unknown not counted
        }
        stats = per_arch.setdefault(arch, {"baseline": zero(), "ai": zero(), "ai_strict": zero()})
        for name, pred in preds.items():
            _confusion(agg[name], gt, pred)
            _confusion(stats[name], gt, pred)

    base, ai, strict = (compute_metrics(**agg[k]) for k in ("baseline", "ai", "ai_strict"))
    return {
        "total_patients": len(patients),
        "evaluated": len(patients) - len(failures),
        "llm_failures": failures,
        "baseline": base,
        "ai": ai,
        "ai_strict": strict,
        "detection_rate_improvement": round(ai["detection_rate"] - base["detection_rate"], 4),
        "false_alert_reduction": round(base["false_alert_rate"] - ai["false_alert_rate"], 4),
        "f1_improvement": round(ai["f1_score"] - base["f1_score"], 4),
        "per_archetype": {
            arch: {
                "ground_truth": "positive" if is_positive(arch) else "negative",
                "baseline": compute_metrics(**s["baseline"]),
                "ai": compute_metrics(**s["ai"]),
                "ai_strict": compute_metrics(**s["ai_strict"]),
            }
            for arch, s in per_arch.items()
        },
    }


def _print_set(label: str, r: dict):
    print("=" * 66)
    print(f"{label.upper()} — {r['evaluated']}/{r['total_patients']} evaluated, "
          f"{len(r['llm_failures'])} LLM failures excluded")
    print("=" * 66)
    print(f"{'Metric':<22} {'NEWS2':>10} {'AI':>10} {'AI strict':>11}")
    for key in ("detection_rate", "false_alert_rate", "precision", "f1_score"):
        print(f"{key:<22} {r['baseline'][key]:>10.1%} {r['ai'][key]:>10.1%} {r['ai_strict'][key]:>11.1%}")
    lo, hi = r["ai"]["detection_rate_ci95"]
    blo, bhi = r["baseline"]["detection_rate_ci95"]
    print(f"95% CI detection:  NEWS2 {blo:.0%}–{bhi:.0%} | AI {lo:.0%}–{hi:.0%}")
    print("Per-archetype detection / false-alert (AI vs NEWS2):")
    for arch, d in r["per_archetype"].items():
        pos = d["ground_truth"] == "positive"
        key = "detection_rate" if pos else "false_alert_rate"
        tag = "POS detect" if pos else "NEG false-alert"
        print(f"  {arch:<18} {tag:<16} AI {d['ai'][key]:>5.0%} | NEWS2 {d['baseline'][key]:>5.0%}")


def run_experiment(dev_scale: int = DEFAULT_DEV_SCALE):
    if not os.environ.get("GROQ_API_KEY"):
        sys.exit("GROQ_API_KEY is not set (add it to backend/.env). Refusing to benchmark the "
                 "heuristic fallback as if it were the LLM.")
    initialize_vector_store()

    development = evaluate_set(generate_patients(scale_factor=dev_scale), "development")
    holdout = evaluate_set(generate_holdout_patients(), "holdout")

    # Top-level keys mirror the development set (existing API/UI contract);
    # the hold-out set is the unbiased figure.
    results = {
        **development,
        "holdout": holdout,
        "config": {
            "model": agent.GROQ_MODEL,
            "reasoning_effort": agent.REASONING_EFFORT,
            "dev_scale": dev_scale,
            "tpm_limit": llm_limits.TPM_LIMIT,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=4)

    _print_set("development", development)
    _print_set("holdout", holdout)
    print(f"\nResults saved to {RESULTS_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--dev-scale", type=int, default=DEFAULT_DEV_SCALE,
                        help="patients per dev archetype = 1-3 x scale (10 = full 170-patient corpus)")
    run_experiment(parser.parse_args().dev_scale)
