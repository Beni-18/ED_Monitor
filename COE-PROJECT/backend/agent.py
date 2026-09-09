from typing import TypedDict, List
from langgraph.graph import StateGraph, END
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

def assess_missing_data(state: AgentState) -> AgentState:
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
    
    # Calculate risk. e.g. each missing vital adds some risk. 
    # Max risk is 10.
    risk = len(missing) * 1.5
    if obs.is_unconscious: risk += 3
    if obs.is_distressed: risk += 2
    
    risk = min(risk, 10.0)
    
    state["missing_measurements"] = missing
    state["missing_data_risk"] = risk
    return state

def compute_baseline(state: AgentState) -> AgentState:
    obs = state["current_obs"]
    news2_result = calculate_news2(obs.vitals)
    state["news2_result"] = news2_result
    return state

def retrieve_context(state: AgentState) -> AgentState:
    obs = state["current_obs"]
    query = f"Patient observation notes: {obs.nursing_notes}. "
    if obs.is_incomplete_history:
        query += "Patient has incomplete history. "
    cases = retrieve_similar_cases(query, n_results=3)
    state["retrieved_cases"] = cases
    return state

def analyze_trends(state: AgentState) -> AgentState:
    patient = state["patient"]
    obs_list = sorted(patient.observations, key=lambda x: x.timestamp)
    trend_deteriorating = False
    
    if len(obs_list) >= 3:
        # Look at overall trajectory, not just last 2 points
        first = obs_list[0]
        last = obs_list[-1]
        
        hr_worsening = False
        spo2_worsening = False
        bp_worsening = False
        rr_worsening = False
        
        # HR: rising over time
        if first.vitals.hr is not None and last.vitals.hr is not None:
            if last.vitals.hr - first.vitals.hr >= 10:
                hr_worsening = True
                
        # SpO2: falling over time
        if first.vitals.spo2 is not None and last.vitals.spo2 is not None:
            if first.vitals.spo2 - last.vitals.spo2 >= 2:
                spo2_worsening = True
                
        # BP: falling over time
        if first.vitals.bp_systolic is not None and last.vitals.bp_systolic is not None:
            if first.vitals.bp_systolic - last.vitals.bp_systolic >= 10:
                bp_worsening = True
                
        # RR: rising over time
        if first.vitals.resp_rate is not None and last.vitals.resp_rate is not None:
            if last.vitals.resp_rate - first.vitals.resp_rate >= 4:
                rr_worsening = True
        
        # If 2 or more parameters are trending negatively, mark as deteriorating
        worsening_count = sum([hr_worsening, spo2_worsening, bp_worsening, rr_worsening])
        if worsening_count >= 2:
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
    return state

def generate_recommendation(state: AgentState) -> AgentState:
    missing_risk = state.get("missing_data_risk", 0.0)
    news2_score = 0
    baseline_flag = False
    if "news2_result" in state:
        news2_score = state["news2_result"]["total_score"]
        if news2_score >= 5:
            baseline_flag = True
            
    trend_deteriorating = state.get("trend_deteriorating", False)
    incomplete_hist = state["current_obs"].is_incomplete_history
    nursing_notes = state["current_obs"].nursing_notes.lower()
    retrieved_cases = state.get("retrieved_cases", [])
    
    # Check for concerning keywords in nursing notes
    concern_keywords = ["confused", "clammy", "not themselves", "restless", "unwell", "labored", "combative", "unresponsive"]
    note_concerns = any(kw in nursing_notes for kw in concern_keywords)
    
    # Check if retrieved RAG context supports a deterioration pattern
    rag_supports_risk = False
    if retrieved_cases:
        rag_text = " ".join(retrieved_cases).lower()
        if any(term in rag_text for term in ["deterioration", "sepsis", "shock", "decompensation", "escalation"]):
            rag_supports_risk = True
    
    if missing_risk >= 7:
        risk_level = "Unknown"
        confidence = 0.2
        action = "Immediate clinician review due to missing data"
        reasoning = "High missing data risk. Cannot safely evaluate."
    elif news2_score >= 7 or (news2_score >= 5 and trend_deteriorating):
        risk_level = "High"
        confidence = 0.9
        action = "Immediate medical review"
        reasoning = f"NEWS2 score ({news2_score}) is high and/or vital signs are trending toward deterioration."
    elif trend_deteriorating and (incomplete_hist or note_concerns or rag_supports_risk):
        # THIS is the key AI advantage: catching subtle deterioration
        risk_level = "High"
        confidence = 0.8
        action = "Review for subtle deterioration — trending vitals combined with concerning context"
        parts = []
        if trend_deteriorating:
            parts.append("vital signs trending negatively across multiple parameters")
        if incomplete_hist:
            parts.append("incomplete patient history")
        if note_concerns:
            parts.append("concerning nursing observations")
        if rag_supports_risk:
            parts.append("RAG-retrieved guidelines support escalation")
        reasoning = f"Subtle deterioration detected despite NEWS2={news2_score}: {', '.join(parts)}."
    elif news2_score >= 5:
        risk_level = "Medium"
        confidence = 0.85
        action = "Increase monitoring frequency"
        reasoning = f"NEWS2 score ({news2_score}) indicates medium risk."
    elif note_concerns and incomplete_hist:
        risk_level = "Medium"
        confidence = 0.7
        action = "Increase monitoring, review nursing notes"
        reasoning = "Concerning nursing notes with incomplete history warrant closer monitoring."
    else:
        risk_level = "Low"
        confidence = 0.95
        action = "Routine care"
        reasoning = "Vitals are stable and within normal limits."
        
    rec = AgentRecommendation(
        risk_level=risk_level,
        confidence_score=confidence,
        missing_measurements=state.get("missing_measurements", []),
        missing_measurement_risk_score=missing_risk,
        reasoning=reasoning,
        recommended_action=action,
        retrieved_similar_cases=state.get("retrieved_cases", []),
        news2_score=news2_score,
        baseline_would_flag=baseline_flag
    )
    state["final_recommendation"] = rec
    return state

def route_after_missing_data(state: AgentState):
    if state["missing_data_risk"] >= 8.0:
        return "generate_recommendation"
    return "compute_baseline"

# Build Graph
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
