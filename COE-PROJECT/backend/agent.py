"""
agent.py — LangGraph AI Pipeline for ED Deterioration Detection

The pipeline runs as a stateful directed acyclic graph:

    assess_missing_data
        │
        ├─ (risk ≥ 8.0) ──────────────────────► generate_recommendation
        │
        └─ (risk < 8.0) → compute_baseline → retrieve_context → analyze_trends → generate_recommendation

Every node records its own execution time (perf_counter) into state["node_timings"],
producing a per-node latency breakdown that is attached to the final AgentRecommendation.
"""
import os
import time
from typing import TypedDict, List, Optional, Dict
from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from models import Patient, PatientObservation, AgentRecommendation
from baseline import calculate_news2
from vector_store import retrieve_similar_cases


class AgentState(TypedDict):
    patient: Patient
    current_obs: PatientObservation
    missing_data_risk: float
    missing_measurements: List[str]
    news2_result: dict
    retrieved_cases: List[str]
    trend_deteriorating: bool
    final_recommendation: AgentRecommendation
    node_timings: Dict[str, float]  # Per-node latency in ms


# ─────────────────────────────────────────────────────────────────────────────
# NODE 1: Assess Missing Data
# Computes a missing-data risk score (0–10) based on absent vitals,
# unconsciousness, and distress markers.
# ─────────────────────────────────────────────────────────────────────────────
def assess_missing_data(state: AgentState) -> AgentState:
    t_start = time.perf_counter()

    obs = state["current_obs"]
    vitals = obs.vitals
    missing = []

    if vitals.hr is None: missing.append("hr")
    if vitals.bp_systolic is None: missing.append("bp_systolic")
    if vitals.bp_diastolic is None: missing.append("bp_diastolic")
    if vitals.resp_rate is None: missing.append("resp_rate")
    if vitals.temp is None: missing.append("temp")
    if vitals.spo2 is None: missing.append("spo2")
    if vitals.consciousness_level is None: missing.append("consciousness_level")

    risk = len(missing) * 1.5
    if obs.is_unconscious: risk += 3
    if obs.is_distressed: risk += 2
    risk = min(risk, 10.0)

    state["missing_measurements"] = missing
    state["missing_data_risk"] = risk

    if "node_timings" not in state or state["node_timings"] is None:
        state["node_timings"] = {}
    state["node_timings"]["assess_missing_data"] = round((time.perf_counter() - t_start) * 1000, 2)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# NODE 2: Compute Baseline NEWS2
# Uses the validated NEWS2 clinical scoring algorithm from baseline.py.
# ─────────────────────────────────────────────────────────────────────────────
def compute_baseline(state: AgentState) -> AgentState:
    t_start = time.perf_counter()

    obs = state["current_obs"]
    news2_result = calculate_news2(obs.vitals)
    state["news2_result"] = news2_result

    state["node_timings"]["compute_baseline"] = round((time.perf_counter() - t_start) * 1000, 2)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# NODE 3: Retrieve Context (RAG)
# Queries ChromaDB with nursing notes to retrieve top-3 relevant clinical
# guidelines using semantic similarity via sentence-transformers.
# ─────────────────────────────────────────────────────────────────────────────
def retrieve_context(state: AgentState) -> AgentState:
    t_start = time.perf_counter()

    obs = state["current_obs"]
    query = f"Patient observation notes: {obs.nursing_notes}. "
    if obs.is_incomplete_history:
        query += "Patient has incomplete history. "
    if obs.is_distressed:
        query += "Patient appears distressed. "
    cases = retrieve_similar_cases(query, n_results=3)
    state["retrieved_cases"] = cases

    state["node_timings"]["retrieve_context"] = round((time.perf_counter() - t_start) * 1000, 2)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# NODE 4: Analyze Trends
# Compares first vs. last observation for HR, SpO2, BP, RR trends over the
# 12-hour observation window. Flags deterioration if ≥2 parameters worsen.
# ─────────────────────────────────────────────────────────────────────────────
def analyze_trends(state: AgentState) -> AgentState:
    t_start = time.perf_counter()

    patient = state["patient"]
    obs_list = sorted(patient.observations, key=lambda x: x.timestamp)
    trend_deteriorating = False

    if len(obs_list) >= 3:
        first = obs_list[0]
        last = obs_list[-1]

        hr_worsening = False
        spo2_worsening = False
        bp_worsening = False
        rr_worsening = False

        # HR: rising over time (≥10 bpm rise is clinically significant)
        if first.vitals.hr is not None and last.vitals.hr is not None:
            if last.vitals.hr - first.vitals.hr >= 10:
                hr_worsening = True

        # SpO2: falling over time (≥2% fall is clinically significant)
        if first.vitals.spo2 is not None and last.vitals.spo2 is not None:
            if first.vitals.spo2 - last.vitals.spo2 >= 2:
                spo2_worsening = True

        # BP: falling over time (≥10 mmHg systolic drop is significant)
        if first.vitals.bp_systolic is not None and last.vitals.bp_systolic is not None:
            if first.vitals.bp_systolic - last.vitals.bp_systolic >= 10:
                bp_worsening = True

        # RR: rising over time (≥4 breaths/min rise is significant)
        if first.vitals.resp_rate is not None and last.vitals.resp_rate is not None:
            if last.vitals.resp_rate - first.vitals.resp_rate >= 4:
                rr_worsening = True

        worsening_count = sum([hr_worsening, spo2_worsening, bp_worsening, rr_worsening])
        
        # Deteriorating if 2+ parameters worsen, OR if SpO2 drops severely (≥4%) on its own (Silent Hypoxia)
        if worsening_count >= 2:
            trend_deteriorating = True
        elif first.vitals.spo2 is not None and last.vitals.spo2 is not None:
            if first.vitals.spo2 - last.vitals.spo2 >= 4:
                trend_deteriorating = True

    elif len(obs_list) >= 2:
        last = obs_list[-1]
        prev = obs_list[-2]

        if last.vitals.hr is not None and prev.vitals.hr is not None:
            if last.vitals.hr > prev.vitals.hr + 5:
                trend_deteriorating = True

        if last.vitals.spo2 is not None and prev.vitals.spo2 is not None:
            if last.vitals.spo2 < prev.vitals.spo2 - 1:
                trend_deteriorating = True

    state["trend_deteriorating"] = trend_deteriorating
    state["node_timings"]["analyze_trends"] = round((time.perf_counter() - t_start) * 1000, 2)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# NODE 5: Generate Recommendation (Groq LLM)
# Calls the Groq LLM with full clinical context using structured output
# to enforce the AgentRecommendation Pydantic schema. Falls back to
# heuristics if the API is unavailable or returns an error.
# ─────────────────────────────────────────────────────────────────────────────
def generate_recommendation(state: AgentState) -> AgentState:
    t_start = time.perf_counter()

    missing_risk = state.get("missing_data_risk", 0.0)
    news2_score = 0
    baseline_flag = False
    if "news2_result" in state and state["news2_result"]:
        news2_score = state["news2_result"]["total_score"]
        if news2_score >= 5:
            baseline_flag = True

    trend_deteriorating = state.get("trend_deteriorating", False)
    incomplete_hist = state["current_obs"].is_incomplete_history
    nursing_notes = state["current_obs"].nursing_notes
    retrieved_cases = state.get("retrieved_cases", [])

    # ── Fast-track: extremely high missing data risk ──────────────────────
    if missing_risk >= 7:
        rec = AgentRecommendation(
            risk_level="Unknown",
            confidence_score=0.2,
            missing_measurements=state.get("missing_measurements", []),
            missing_measurement_risk_score=missing_risk,
            reasoning=(
                f"High missing data risk score ({missing_risk:.1f}/10). "
                "Cannot safely evaluate patient status without key vital sign measurements. "
                "Immediate bedside clinical assessment is required."
            ),
            recommended_action="Immediate clinician review — escalate due to missing data",
            retrieved_similar_cases=retrieved_cases,
            news2_score=news2_score,
            baseline_would_flag=baseline_flag
        )
        state["node_timings"]["generate_recommendation"] = round((time.perf_counter() - t_start) * 1000, 2)
        rec.node_timings = dict(state["node_timings"])
        state["final_recommendation"] = rec
        return state

    # ── Groq API key check — fallback to heuristics if not available ──────
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("Warning: GROQ_API_KEY not found. Using heuristic fallback.")
        risk_level = "High" if (news2_score >= 5 or trend_deteriorating) else "Low"
        rec = AgentRecommendation(
            risk_level=risk_level,
            confidence_score=0.7,
            missing_measurements=state.get("missing_measurements", []),
            missing_measurement_risk_score=missing_risk,
            reasoning=(
                f"Heuristic fallback (no Groq API key). NEWS2={news2_score}, "
                f"Trend deteriorating={trend_deteriorating}."
            ),
            recommended_action="Manual clinical review recommended.",
            retrieved_similar_cases=retrieved_cases,
            news2_score=news2_score,
            baseline_would_flag=baseline_flag
        )
        state["node_timings"]["generate_recommendation"] = round((time.perf_counter() - t_start) * 1000, 2)
        rec.node_timings = dict(state["node_timings"])
        state["final_recommendation"] = rec
        return state

    # ── Full Groq LLM evaluation ──────────────────────────────────────────
    llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.1)
    structured_llm = llm.with_structured_output(AgentRecommendation)

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an expert AI clinical assistant for the Emergency Department. "
         "Evaluate the patient data, notes, and clinical guidelines to determine the risk level "
         "('High', 'Medium', 'Low', or 'Unknown') and provide a detailed clinical recommendation. "
         "Pay special attention to trends over time, not just absolute values. "
         "Context from clinical guidelines is provided to help recognize subtle presentations "
         "such as silent hypoxia, compensated shock, and drug-induced bradycardia."),
        ("human",
         "Patient Vitals: {vitals}\n"
         "Nursing Notes: {nursing_notes}\n"
         "NEWS2 Score: {news2_score} (≥5 = Medium risk; ≥7 = High risk)\n"
         "Trend Deteriorating (≥2 parameters worsening over 12h): {trend_deteriorating}\n"
         "Incomplete History: {incomplete_hist}\n"
         "Relevant Clinical Guidelines:\n{retrieved_cases}")
    ])

    chain = prompt | structured_llm

    try:
        response: AgentRecommendation = chain.invoke({
            "vitals": str(state["current_obs"].vitals),
            "nursing_notes": nursing_notes,
            "news2_score": news2_score,
            "trend_deteriorating": trend_deteriorating,
            "incomplete_hist": incomplete_hist,
            "retrieved_cases": "\n".join(f"• {g}" for g in retrieved_cases)
        })

        # Merge state-specific properties
        response.missing_measurements = state.get("missing_measurements", [])
        response.missing_measurement_risk_score = missing_risk
        response.retrieved_similar_cases = retrieved_cases
        response.news2_score = news2_score
        response.baseline_would_flag = baseline_flag

        state["node_timings"]["generate_recommendation"] = round((time.perf_counter() - t_start) * 1000, 2)
        response.node_timings = dict(state["node_timings"])
        state["final_recommendation"] = response

    except Exception as e:
        print(f"[LLM ERROR] {e}")
        rec = AgentRecommendation(
            risk_level="Unknown",
            confidence_score=0.0,
            missing_measurements=state.get("missing_measurements", []),
            missing_measurement_risk_score=missing_risk,
            reasoning=f"LLM API Error: {str(e)[:200]}. Manual review required.",
            recommended_action="Manual clinician review required.",
            retrieved_similar_cases=retrieved_cases,
            news2_score=news2_score,
            baseline_would_flag=baseline_flag
        )
        state["node_timings"]["generate_recommendation"] = round((time.perf_counter() - t_start) * 1000, 2)
        rec.node_timings = dict(state["node_timings"])
        state["final_recommendation"] = rec

    return state


# ─────────────────────────────────────────────────────────────────────────────
# ROUTING FUNCTION
# ─────────────────────────────────────────────────────────────────────────────
def route_after_missing_data(state: AgentState):
    """Fast-track to generate_recommendation if missing data risk is critical."""
    if state["missing_data_risk"] >= 8.0:
        return "generate_recommendation"
    return "compute_baseline"


# ─────────────────────────────────────────────────────────────────────────────
# GRAPH CONSTRUCTION
# ─────────────────────────────────────────────────────────────────────────────
graph = StateGraph(AgentState)
graph.add_node("assess_missing_data", assess_missing_data)
graph.add_node("compute_baseline", compute_baseline)
graph.add_node("retrieve_context", retrieve_context)
graph.add_node("analyze_trends", analyze_trends)
graph.add_node("generate_recommendation", generate_recommendation)

graph.set_entry_point("assess_missing_data")
graph.add_conditional_edges("assess_missing_data", route_after_missing_data, {
    "generate_recommendation": "generate_recommendation",
    "compute_baseline": "compute_baseline"
})
graph.add_edge("compute_baseline", "retrieve_context")
graph.add_edge("retrieve_context", "analyze_trends")
graph.add_edge("analyze_trends", "generate_recommendation")
graph.add_edge("generate_recommendation", END)

app = graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# CLINICAL COPILOT CHATBOT MODULE
# Domain-restricted to Emergency Department clinical topics only.
# ─────────────────────────────────────────────────────────────────────────────

NON_CLINICAL_KEYWORDS = [
    "java", "python", "javascript", "c++", "html", "css", "code", "programming",
    "recipe", "cook", "movie", "song", "joke", "poem", "sport", "football", "cricket",
    "basketball", "weather", "president", "capital of", "solve equation", "who is",
    "game", "car", "travel", "flight", "hotel", "crypto", "bitcoin", "stock",
    "netflix", "restaurant", "shopping", "fashion", "music", "history of", "geography"
]

OUT_OF_DOMAIN_RESPONSE = (
    "I am your ED Clinical Copilot, designed specifically for ward deterioration monitoring, "
    "patient vitals analysis, NEWS2 scores, and clinical care guidelines. I can only assist with "
    "patient care and emergency department clinical questions."
)

def clinical_chat_assistant(user_message: str, patient_context: str = "") -> dict:
    """
    Domain-restricted chatbot assistant for ED deterioration monitoring.
    
    Dual-layer guardrails:
    1. Deterministic keyword pre-filter blocks obvious off-topic queries instantly
    2. Groq LLM system prompt enforces clinical-only domain restriction
    
    Returns dict with 'reply' (str) and 'out_of_domain' (bool).
    """
    clean_msg = user_message.lower().strip()

    # Layer 1: Deterministic keyword pre-filter
    for word in NON_CLINICAL_KEYWORDS:
        if word in clean_msg:
            return {"reply": OUT_OF_DOMAIN_RESPONSE, "out_of_domain": True}

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {
            "reply": "Groq API key unavailable. System operating in offline mode.",
            "out_of_domain": False
        }

    llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.1)

    system_instruction = (
        "You are the ED Clinical Copilot, an intelligent clinical decision support assistant "
        "for the Emergency Department.\n\n"
        "FORMATTING & CLINICAL EXPLANATION GUIDELINES:\n"
        "1. EMOJI POLICY: Keep emoji usage to an absolute minimum. Use clean text markers "
        "([CRITICAL], [WARNING], [STABLE]) or clean bullet points. Do NOT clutter responses with emojis.\n"
        "2. VISUAL LAYOUT: Structure your responses cleanly with bold section titles and organized "
        "bullet points instead of dense raw text or pipe tables.\n"
        "3. LAYPERSON-FRIENDLY CLINICAL EXPLANATIONS: Make all patient summaries easy to understand:\n"
        "   - Whenever listing a vital sign, add a plain-English explanation in parentheses. For example:\n"
        "     • Heart Rate: 155 bpm (Dangerously fast — heart working too hard)\n"
        "     • Blood Pressure: 70/55 mmHg (Critically low — shock risk)\n"
        "     • SpO2: 83% (Critically low oxygen in blood — emergency oxygen needed)\n"
        "4. Provide actionable clinical steps clearly under bullet points.\n\n"
        "STRICT DOMAIN RESTRICTION RULE:\n"
        "If the user asks about ANYTHING outside of emergency medicine, patient vital signs, "
        "clinical deterioration, NEWS2 scores, medical guidelines, or ED patient care "
        "(e.g. general programming, trivia, coding, non-medical advice, entertainment, "
        "hobbies, politics, cooking, travel, sports), you MUST refuse and reply with EXACTLY:\n"
        f"'{OUT_OF_DOMAIN_RESPONSE}'"
    )

    messages = [("system", system_instruction)]
    if patient_context:
        messages.append(("system", f"CURRENT WARD CONTEXT:\n{patient_context}"))
    messages.append(("human", user_message))

    try:
        prompt = ChatPromptTemplate.from_messages(messages)
        chain = prompt | llm
        response = chain.invoke({})
        reply_text = response.content if hasattr(response, "content") else str(response)

        is_ood = OUT_OF_DOMAIN_RESPONSE.strip() in reply_text.strip()
        return {"reply": reply_text, "out_of_domain": is_ood}

    except Exception as e:
        print(f"[CHATBOT ERROR] {e}")
        return {
            "reply": f"Clinical Chat Assistant encountered an error: {str(e)[:100]}",
            "out_of_domain": False
        }
