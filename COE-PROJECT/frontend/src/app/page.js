"use client";

import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import styles from './page.module.css';

const API_BASE = 'http://localhost:8000';

export default function Dashboard() {
  const [patients, setPatients] = useState([]);
  const [escalations, setEscalations] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [selectedPatientId, setSelectedPatientId] = useState(null);
  const [trendData, setTrendData] = useState([]);
  const [backendOffline, setBackendOffline] = useState(false);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000); // Poll every 10s
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (selectedPatientId) {
      fetchTrendData(selectedPatientId);
    }
  }, [selectedPatientId]);

  const fetchData = async () => {
    try {
      const [patientsRes, escalationsRes, metricsRes] = await Promise.all([
        fetch(`${API_BASE}/api/patients`).catch(() => null),
        fetch(`${API_BASE}/api/escalations`).catch(() => null),
        fetch(`${API_BASE}/api/metrics`).catch(() => null)
      ]);

      if (!patientsRes || !escalationsRes || !metricsRes) {
        setBackendOffline(true);
        return;
      }

      setBackendOffline(false);
      
      const pData = await patientsRes.json();
      const eData = await escalationsRes.json();
      const mData = await metricsRes.json();

      setPatients(pData);
      setEscalations(eData.filter(e => e.status === 'pending'));
      setMetrics(mData);

      if (pData.length > 0 && !selectedPatientId) {
        setSelectedPatientId(pData[0].patient_id);
      }
    } catch (err) {
      setBackendOffline(true);
      console.error("Error fetching data:", err);
    }
  };

  const fetchTrendData = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/api/patients/${id}/observations`);
      if (res.ok) {
        const data = await res.json();
        // Transform nested vitals into flat objects for Recharts
        const transformed = data.map(obs => ({
          timestamp: new Date(obs.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          heartRate: obs.vitals?.hr ?? null,
          systolicBP: obs.vitals?.bp_systolic ?? null,
          spO2: obs.vitals?.spo2 ?? null,
        }));
        setTrendData(transformed);
      }
    } catch (err) {
      console.error("Error fetching trend data:", err);
    }
  };

  const handleAction = async (id, action) => {
    try {
      // Optimistic update
      setEscalations(prev => prev.filter(e => e.id !== id));
      await fetch(`${API_BASE}/api/escalations/${id}/${action}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clinician_notes: "Actioned via dashboard" })
      });
      fetchData(); // Refresh data
    } catch (err) {
      console.error(`Error ${action} escalation:`, err);
    }
  };

  const handleEvaluate = async (id) => {
    try {
      const evalRes = await fetch(`${API_BASE}/api/evaluate/${id}`, { method: 'POST' });
      if (evalRes.ok) {
        const recommendation = await evalRes.json();
        
        // If the AI flags a risk, escalate it to the inbox
        if (['High', 'Medium', 'Unknown'].includes(recommendation.risk_level)) {
          await fetch(`${API_BASE}/api/escalations/${id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recommendation })
          });
        }
        
        // Refresh data to show new escalations
        fetchData();
      }
    } catch (err) {
      console.error("Error evaluating:", err);
    }
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.logoArea}>
          <div className={styles.logoIcon}></div>
          <h1 className={styles.title}>ED DETERIORATION MONITOR</h1>
        </div>
        <div className={styles.statusArea}>
          <div className={styles.statusIndicator}>
            <div className={styles.statusDot} style={{ background: backendOffline ? 'var(--danger)' : 'var(--success)' }}></div>
            {backendOffline ? 'SYSTEM OFFLINE' : 'SYSTEM ONLINE'}
          </div>
          <div className={styles.userIcon}>U</div>
        </div>
      </header>

      <aside className={styles.sidebar}>
        <div className={`${styles.navItem} ${styles.active}`}>
          <span className={styles.navIcon}>■</span> OVERVIEW
        </div>
        <div className={styles.navItem}>
          <span className={styles.navIcon}>■</span> PATIENTS
        </div>
        <div className={styles.navItem}>
          <span className={styles.navIcon}>■</span> INBOX
        </div>
        <div className={styles.navItem}>
          <span className={styles.navIcon}>■</span> METRICS
        </div>
      </aside>

      <main className={styles.mainContent}>
        {backendOffline && (
          <div style={{ background: 'var(--danger)', color: '#000', padding: '1rem', fontFamily: 'var(--font-mono)' }}>
            CRITICAL ERROR: BACKEND API IS UNREACHABLE.
          </div>
        )}

        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>Total Patients</span>
            <span className={styles.statValue}>{patients.length || metrics?.totalPatients || '--'}</span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>Active Alerts</span>
            <span className={styles.statValue}>{metrics?.activeAlerts || '--'}</span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>Escalations Pending</span>
            <span className={styles.statValue}>{escalations.length}</span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>System Confidence</span>
            <span className={styles.statValue}>{metrics?.systemConfidence ? `${(metrics.systemConfidence * 100).toFixed(0)}%` : '--'}</span>
          </div>
        </div>

        <div className={styles.chartSection}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>VITAL TRENDS // {patients.find(p => p.patient_id === selectedPatientId)?.name || 'UNKNOWN'}</h2>
            <button onClick={() => selectedPatientId && handleEvaluate(selectedPatientId)} style={{ padding: '0.25rem 0.75rem', fontSize: '0.75rem' }}>
              RUN EVALUATION
            </button>
          </div>
          <div style={{ flex: 1, width: '100%', minHeight: 0 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
                <XAxis dataKey="timestamp" stroke="var(--border-color)" tick={{ fill: 'var(--text-secondary)', fontSize: 12, fontFamily: 'monospace' }} />
                <YAxis stroke="var(--border-color)" tick={{ fill: 'var(--text-secondary)', fontSize: 12, fontFamily: 'monospace' }} />
                <Tooltip 
                  contentStyle={{ backgroundColor: 'var(--background)', border: '1px solid var(--border-color)', borderRadius: 0, fontFamily: 'monospace' }}
                  itemStyle={{ color: 'var(--text-primary)' }}
                />
                <ReferenceLine y={100} stroke="var(--warning)" strokeDasharray="3 3" />
                <ReferenceLine y={60} stroke="var(--danger)" strokeDasharray="3 3" />
                
                <Line type="monotone" dataKey="heartRate" name="Heart Rate" stroke="var(--danger)" strokeWidth={2} dot={{ r: 3, fill: 'var(--danger)' }} isAnimationActive={false} />
                <Line type="monotone" dataKey="systolicBP" name="Systolic BP" stroke="#ffffff" strokeWidth={2} dot={{ r: 3, fill: '#ffffff' }} isAnimationActive={false} />
                <Line type="monotone" dataKey="spO2" name="SpO2" stroke="var(--success)" strokeWidth={2} dot={{ r: 3, fill: 'var(--success)' }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className={styles.bottomGrid}>
          <div className={styles.panel}>
            <div className={styles.panelHeader}>PATIENT LIST</div>
            <div className={styles.panelContent}>
              {patients.map(patient => (
                <div 
                  key={patient.patient_id} 
                  className={`${styles.patientRow} ${selectedPatientId === patient.patient_id ? styles.active : ''}`}
                  onClick={() => setSelectedPatientId(patient.patient_id)}
                >
                  <div>
                    <div className={styles.patientName}>{patient.name}</div>
                    <div className={styles.patientBed}>BED {patient.bed_number}</div>
                  </div>
                  <span className={`badge ${patient.riskLevel === 'High' ? 'badge-danger' : patient.riskLevel === 'Medium' ? 'badge-warning' : patient.riskLevel === 'Low' ? 'badge-success' : ''}`}>
                    {patient.riskLevel ? `${patient.riskLevel} RISK` : 'UNASSESSED'}
                  </span>
                </div>
              ))}
              {patients.length === 0 && !backendOffline && (
                <div style={{ color: 'var(--text-secondary)', fontFamily: 'monospace', padding: '1rem' }}>NO PATIENT DATA FOUND</div>
              )}
            </div>
          </div>

          <div className={styles.panel}>
            <div className={styles.panelHeader}>CLINICIAN INBOX</div>
            <div className={styles.panelContent}>
              {escalations.length === 0 ? (
                <div style={{ color: 'var(--text-secondary)', fontFamily: 'monospace', padding: '1rem' }}>NO PENDING ESCALATIONS</div>
              ) : (
                escalations.map(escalation => (
                  <div key={escalation.id} className={`${styles.inboxCard} fade-in`}>
                    <div className={styles.inboxHeader}>
                      <div className={styles.inboxMeta}>
                        <span style={{ fontWeight: '600' }}>
                          {patients.find(p => p.patient_id === escalation.patient_id)?.name || escalation.patient_id}
                        </span>
                        <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                          CONFIDENCE: {(escalation.recommendation?.confidence_score * 100).toFixed(0)}%
                        </span>
                        {escalation.recommendation?.missing_measurements?.length > 0 && (
                          <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--warning)' }}>WARNING: MISSING DATA</span>
                        )}
                      </div>
                      <span className="badge badge-danger">ESCALATION</span>
                    </div>
                    <div className={styles.inboxReasoning}>
                      {escalation.recommendation?.reasoning}
                    </div>
                    <div className={styles.inboxActions}>
                      <button className={styles.btnApprove} onClick={() => handleAction(escalation.id, 'approve')}>
                        APPROVE
                      </button>
                      <button className={styles.btnReject} onClick={() => handleAction(escalation.id, 'reject')}>
                        REJECT
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </main>

      <footer className={styles.footer}>
        <div>COE PROJECT - ED DETERIORATION MONITOR v2.1.0</div>
        <div>DATA SOURCE: LOCAL_NETWORK</div>
      </footer>
    </div>
  );
}
