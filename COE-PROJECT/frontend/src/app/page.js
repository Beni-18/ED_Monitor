"use client";

import { useState, useEffect, useRef } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Legend, BarChart, Bar, Cell } from 'recharts';
import styles from './page.module.css';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'patients' | 'inbox' | 'metrics' | 'audit'
  const [patients, setPatients] = useState([]);
  const [escalations, setEscalations] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [selectedPatientId, setSelectedPatientId] = useState(null);
  const selectedPatientIdRef = useRef(null);
  useEffect(() => { selectedPatientIdRef.current = selectedPatientId; }, [selectedPatientId]);
  const [selectedPatientDetail, setSelectedPatientDetail] = useState(null);
  const [trendData, setTrendData] = useState([]);
  const [performance, setPerformance] = useState(null);
  const [backendOffline, setBackendOffline] = useState(false);
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [isBatchEvaluating, setIsBatchEvaluating] = useState(false);
  const [evalSuccessMsg, setEvalSuccessMsg] = useState('');
  const [auditLogs, setAuditLogs] = useState([]);

  // Chatbot states
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState([
    { sender: 'assistant', text: 'Hello! I am your ED Clinical Copilot. I can assist you with patient vitals, ward deterioration trends, NEWS2 scores, and clinical care guidelines. How can I help?', ood: false }
  ]);
  const [chatInput, setChatInput] = useState('');
  const [isSendingChat, setIsSendingChat] = useState(false);

  // Search and Filter states
  const [searchQuery, setSearchQuery] = useState('');
  const [riskFilter, setRiskFilter] = useState('ALL'); // 'ALL' | 'High' | 'Medium' | 'Low' | 'UNASSESSED'
  const [inboxFilter, setInboxFilter] = useState('pending'); // 'pending' | 'approved' | 'rejected' | 'all'

  // Auth states
  const [token, setToken] = useState(null);
  const [role, setRole] = useState(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');

  // Admin states
  const [adminUsers, setAdminUsers] = useState([]);
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState('Doctor');

  useEffect(() => {
    const savedToken = localStorage.getItem('token');
    const savedRole = localStorage.getItem('role');
    if (savedToken && savedRole) {
      setToken(savedToken);
      setRole(savedRole);
    }
  }, []);

  useEffect(() => {
    if (token) {
      fetchData();
      
      const wsUrl = API_BASE.replace('http', 'ws') + '/ws/vitals';
      const ws = new WebSocket(wsUrl);
      
      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'VITAL_UPDATE') {
            fetchData();
            if (selectedPatientIdRef.current) {
              fetchTrendData(selectedPatientIdRef.current);
              fetchPatientDetail(selectedPatientIdRef.current);
            }
          } else if (message.type === 'NEW_ESCALATION') {
            setEvalSuccessMsg(`🚨 NEW SYSTEM ESCALATION: Patient ${message.patient_id} flagged as ${message.risk_level} Risk`);
            setTimeout(() => setEvalSuccessMsg(''), 8000);
            fetchData(); // pull new escalations
          }
        } catch (e) {
          console.error("WS parse error", e);
        }
      };

      return () => ws.close();
    }
  }, [token]);

  useEffect(() => {
    if (selectedPatientId && token) {
      fetchTrendData(selectedPatientId);
      fetchPatientDetail(selectedPatientId);
    }
  }, [selectedPatientId, token]);

  useEffect(() => {
    if (activeTab === 'metrics' && token) {
      fetchPerformance();
    }
  }, [activeTab, token]);

  const fetchPerformance = async () => {
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/performance`);
      if (res.ok) {
        const data = await res.json();
        setPerformance(data);
      }
    } catch (err) {
      console.error("Error fetching performance metrics:", err);
    }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoginError('');
    try {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);
      
      const res = await fetch(`${API_BASE}/api/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData
      });
      
      if (res.ok) {
        const data = await res.json();
        setToken(data.access_token);
        setRole(data.role);
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('role', data.role);
      } else {
        setLoginError('Invalid credentials');
      }
    } catch (err) {
      setLoginError('Network error — unable to reach authentication server.');
    }
  };

  const handleLogout = () => {
    setToken(null);
    setRole(null);
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    setPatients([]);
    setEscalations([]);
  };

  const fetchWithAuth = async (url, options = {}) => {
    return fetch(url, {
      ...options,
      headers: {
        ...options.headers,
        'Authorization': `Bearer ${token}`
      }
    });
  };

  const fetchData = async () => {
    try {
      const [patientsRes, escalationsRes, metricsRes] = await Promise.all([
        fetchWithAuth(`${API_BASE}/api/patients`).catch(() => null),
        fetchWithAuth(`${API_BASE}/api/escalations`).catch(() => null),
        fetchWithAuth(`${API_BASE}/api/metrics`).catch(() => null)
      ]);

      if (!patientsRes || !escalationsRes || !metricsRes || !patientsRes.ok) {
        if (patientsRes && patientsRes.status === 401) handleLogout();
        setBackendOffline(true);
        return;
      }

      setBackendOffline(false);
      
      const pData = await patientsRes.json();
      const eData = await escalationsRes.json();
      const mData = await metricsRes.json();

      setPatients(pData);
      setEscalations(eData);
      setMetrics(mData);

      if (pData.length > 0) {
        setSelectedPatientId(prev => {
          if (!prev) return pData[0].patient_id;
          return prev;
        });
      }
    } catch (err) {
      setBackendOffline(true);
      console.error("Error fetching data:", err);
    }
  };

  const fetchPatientDetail = async (id) => {
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/patients/${id}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedPatientDetail(data);
      }
    } catch (err) {
      console.error("Error fetching patient detail:", err);
    }
  };

  const fetchTrendData = async (id) => {
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/patients/${id}/observations`);
      if (res.ok) {
        const data = await res.json();
        const transformed = data.map(obs => ({
          timestamp: new Date(obs.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          rawTime: obs.timestamp,
          heartRate: obs.vitals?.hr ?? null,
          systolicBP: obs.vitals?.bp_systolic ?? null,
          diastolicBP: obs.vitals?.bp_diastolic ?? null,
          spO2: obs.vitals?.spo2 ? Number(obs.vitals.spo2.toFixed(1)) : null,
          respRate: obs.vitals?.resp_rate ?? null,
          temp: obs.vitals?.temp ? Number(obs.vitals.temp.toFixed(1)) : null,
          notes: obs.nursing_notes
        }));
        setTrendData(transformed);
      }
    } catch (err) {
      console.error("Error fetching trend data:", err);
    }
  };

  const handleAction = async (id, action) => {
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/escalations/${id}/${action}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clinician_notes: `Actioned (${action.toUpperCase()}) via ED Monitor Dashboard` })
      });
      if (res.status === 403) {
        alert("Permission Denied: Only users with the Doctor role can approve or reject escalations.");
      }
      fetchData();
    } catch (err) {
      console.error(`Error ${action} escalation:`, err);
    }
  };

  const handleEvaluate = async (id) => {
    setIsEvaluating(true);
    setEvalSuccessMsg('');
    try {
      const evalRes = await fetchWithAuth(`${API_BASE}/api/evaluate/${id}`, { method: 'POST' });
      if (evalRes.ok) {
        const recommendation = await evalRes.json();
        if (['High', 'Medium', 'Unknown'].includes(recommendation.risk_level)) {
          await fetchWithAuth(`${API_BASE}/api/escalations/${id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recommendation })
          });
        }
        setEvalSuccessMsg(`Evaluated: ${recommendation.risk_level} Risk (${(recommendation.confidence_score * 100).toFixed(0)}% confidence)`);
        fetchData();
        if (selectedPatientId === id) {
          fetchPatientDetail(id);
        }
      } else {
        alert("Evaluation failed. Check API connectivity.");
      }
    } catch (err) {
      console.error("Error evaluating:", err);
    } finally {
      setIsEvaluating(false);
      setTimeout(() => setEvalSuccessMsg(''), 5000);
    }
  };

  const fetchAuditLogs = async () => {
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/audit-logs`);
      if (res.ok) {
        const data = await res.json();
        setAuditLogs(data);
      }
    } catch (err) {
      console.error("Error fetching audit logs:", err);
    }
  };

  const fetchAdminUsers = async () => {
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/admin/users`);
      if (res.ok) {
        const data = await res.json();
        setAdminUsers(data);
      }
    } catch (err) {
      console.error("Error fetching users", err);
    }
  };

  const handleAddUser = async (e) => {
    e.preventDefault();
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/admin/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: newUsername, password: newPassword, role: newRole })
      });
      if (res.ok) {
        setNewUsername('');
        setNewPassword('');
        fetchAdminUsers();
      } else {
        alert("Failed to add user");
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteUser = async (id) => {
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/admin/users/${id}`, { method: 'DELETE' });
      if (res.ok) {
        fetchAdminUsers();
      } else {
        alert("Failed to delete user");
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleBatchEvaluate = async () => {
    setIsBatchEvaluating(true);
    setEvalSuccessMsg('');
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/evaluate/batch`, { method: 'POST' });
      if (res.ok) {
        const result = await res.json();
        setEvalSuccessMsg(`⚡ WARD BATCH EVALUATION COMPLETE: Evaluated ${result.evaluated_count} patients in ${result.total_time_seconds}s. Created ${result.escalations_created} new escalations.`);
        fetchData();
      } else {
        alert("Batch evaluation failed.");
      }
    } catch (err) {
      console.error("Error in batch evaluate:", err);
    } finally {
      setIsBatchEvaluating(false);
      setTimeout(() => setEvalSuccessMsg(''), 8000);
    }
  };

  const handleExportHandover = async () => {
    try {
      const res = await fetchWithAuth(`${API_BASE}/api/export/handover`);
      if (res.ok) {
        const report = await res.json();
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(report, null, 2));
        const downloadAnchor = document.createElement('a');
        downloadAnchor.setAttribute("href", dataStr);
        downloadAnchor.setAttribute("download", `clinical_handover_report_${new Date().toISOString().slice(0,10)}.json`);
        document.body.appendChild(downloadAnchor);
        downloadAnchor.click();
        downloadAnchor.remove();
        setEvalSuccessMsg(`📥 DOWNLOADED Handover Report for ${report.high_medium_risk_patients_count} High/Medium risk patients.`);
        setTimeout(() => setEvalSuccessMsg(''), 5000);
      }
    } catch (err) {
      console.error("Error exporting handover report:", err);
    }
  };

  const handleSendChat = async (messageText = null) => {
    const textToSend = messageText || chatInput;
    if (!textToSend || !textToSend.trim()) return;

    const userMsg = { sender: 'user', text: textToSend };
    setChatMessages(prev => [...prev, userMsg]);
    if (!messageText) setChatInput('');
    setIsSendingChat(true);

    try {
      const res = await fetchWithAuth(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: textToSend,
          patient_id: selectedPatientId || null
        })
      });

      if (res.ok) {
        const data = await res.json();
        setChatMessages(prev => [
          ...prev,
          { sender: 'assistant', text: data.reply, ood: data.out_of_domain }
        ]);
      } else {
        setChatMessages(prev => [
          ...prev,
          { sender: 'assistant', text: "Error communicating with Clinical Chat Assistant.", ood: false }
        ]);
      }
    } catch (err) {
      console.error("Chat error:", err);
      setChatMessages(prev => [
        ...prev,
        { sender: 'assistant', text: "Network error connecting to chat service.", ood: false }
      ]);
    } finally {
      setIsSendingChat(false);
    }
  };

  // Custom Chart Tooltip for clean vital signs representation
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div style={{ backgroundColor: '#0a0a0a', border: '1px solid var(--border-color)', padding: '0.75rem', fontFamily: 'monospace', fontSize: '0.8rem', minWidth: '160px' }}>
          <div style={{ color: 'var(--text-secondary)', marginBottom: '0.4rem', borderBottom: '1px solid #222', paddingBottom: '0.2rem' }}>TIME: {label}</div>
          {payload.map((entry, index) => {
            let unit = '';
            if (entry.dataKey === 'heartRate') unit = ' bpm';
            if (entry.dataKey === 'systolicBP') unit = ' mmHg';
            if (entry.dataKey === 'spO2') unit = ' %';
            return (
              <div key={`item-${index}`} style={{ color: entry.color, display: 'flex', justifyContent: 'space-between', margin: '2px 0' }}>
                <span>{entry.name}:</span>
                <span style={{ fontWeight: 'bold' }}>{entry.value !== null ? `${entry.value}${unit}` : 'N/A'}</span>
              </div>
            );
          })}
        </div>
      );
    }
    return null;
  };

  // Filtered patients
  const filteredPatients = patients.filter(p => {
    const matchesSearch = p.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                          p.bed_number.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          p.patient_id.toLowerCase().includes(searchQuery.toLowerCase());
    
    if (riskFilter === 'ALL') return matchesSearch;
    if (riskFilter === 'UNASSESSED') return matchesSearch && !p.risk_level;
    return matchesSearch && p.risk_level === riskFilter;
  });

  // Filtered escalations
  const filteredEscalations = escalations.filter(e => {
    if (inboxFilter === 'all') return true;
    return e.status === inboxFilter;
  });

  const selectedPatient = patients.find(p => p.patient_id === selectedPatientId);
  const pendingEscalationsCount = escalations.filter(e => e.status === 'pending').length;
  const highRiskCount = patients.filter(p => p.risk_level === 'High').length;

  if (!token) {
    return (
      <div className={styles.container} style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#050505' }}>
        <form onSubmit={handleLogin} style={{ background: '#0f0f0f', padding: '2.5rem', border: '1px solid var(--border-color)', width: '380px', boxShadow: '0 8px 32px rgba(0,0,0,0.8)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.5rem' }}>
            <div style={{ width: '16px', height: '16px', background: 'var(--danger)' }}></div>
            <h2 style={{ fontFamily: 'var(--font-mono)', fontSize: '1.1rem', letterSpacing: '0.1em' }}>ED MONITOR // LOGIN</h2>
          </div>
          
          {loginError && <div style={{ background: 'rgba(255, 0, 0, 0.1)', color: 'var(--danger)', border: '1px solid var(--danger)', padding: '0.75rem', marginBottom: '1rem', fontFamily: 'monospace', fontSize: '0.85rem' }}>{loginError}</div>}
          
          <div style={{ marginBottom: '1.25rem' }}>
            <label style={{ display: 'block', fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>USERNAME</label>
            <input type="text" placeholder="doctor / nurse / admin" value={username} onChange={e => setUsername(e.target.value)} style={{ width: '100%', padding: '0.75rem', background: '#141414', color: 'var(--text-primary)', border: '1px solid var(--border-color)', fontFamily: 'monospace' }} />
          </div>
          
          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ display: 'block', fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>PASSWORD</label>
            <input type="password" placeholder="password123" value={password} onChange={e => setPassword(e.target.value)} style={{ width: '100%', padding: '0.75rem', background: '#141414', color: 'var(--text-primary)', border: '1px solid var(--border-color)', fontFamily: 'monospace' }} />
          </div>
          
          <button type="submit" style={{ width: '100%', padding: '0.85rem', background: 'var(--text-primary)', color: '#000', border: 'none', fontWeight: 'bold', fontFamily: 'monospace', cursor: 'pointer', letterSpacing: '0.05em' }}>AUTHENTICATE</button>
          
          <div style={{ marginTop: '1.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace', borderTop: '1px dashed #222', paddingTop: '1rem' }}>
            <div>DEMO CREDENTIALS:</div>
            <div>• Doctor: <code style={{ color: '#fff' }}>doctor</code> / <code style={{ color: '#fff' }}>password123</code></div>
            <div>• Nurse: <code style={{ color: '#fff' }}>nurse</code> / <code style={{ color: '#fff' }}>password123</code></div>
            <div>• Admin: <code style={{ color: '#fff' }}>admin</code> / <code style={{ color: '#fff' }}>password123</code></div>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* HEADER */}
      <header className={styles.header}>
        <div className={styles.logoArea}>
          <div className={styles.logoIcon}></div>
          <h1 className={styles.title}>ED DETERIORATION MONITOR</h1>
          <span style={{ fontSize: '0.7rem', padding: '0.2rem 0.5rem', background: '#1a1a1a', border: '1px solid #333', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
            AI RAG v2.2
          </span>
        </div>
        <div className={styles.statusArea}>
          <div className={styles.statusIndicator}>
            <div className={styles.statusDot} style={{ background: backendOffline ? 'var(--danger)' : 'var(--success)' }}></div>
            {backendOffline ? 'SYSTEM OFFLINE' : 'ONLINE // GROQ LLM ACTIVE'}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style={{ fontSize: '0.8rem', fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
              ROLE: <strong style={{ color: '#fff' }}>{role?.toUpperCase()}</strong>
            </span>
            <div className={styles.userIcon} onClick={handleLogout} style={{ cursor: 'pointer' }} title="Click to Logout">
              {role ? role.charAt(0) : 'U'}
            </div>
          </div>
        </div>
      </header>

      {/* SIDEBAR NAVIGATION */}
      <aside className={styles.sidebar}>
        <div 
          className={`${styles.navItem} ${activeTab === 'overview' ? styles.active : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          <span className={styles.navIcon}>■</span> OVERVIEW
        </div>
        <div 
          className={`${styles.navItem} ${activeTab === 'patients' ? styles.active : ''}`}
          onClick={() => setActiveTab('patients')}
        >
          <span className={styles.navIcon}>■</span> PATIENTS ({patients.length})
        </div>
        <div 
          className={`${styles.navItem} ${activeTab === 'inbox' ? styles.active : ''}`}
          onClick={() => setActiveTab('inbox')}
        >
          <span className={styles.navIcon}>■</span> CLINICIAN INBOX
          {pendingEscalationsCount > 0 && (
            <span style={{ background: 'var(--danger)', color: '#000', fontSize: '0.7rem', padding: '0.1rem 0.4rem', fontWeight: 'bold', marginLeft: 'auto' }}>
              {pendingEscalationsCount}
            </span>
          )}
        </div>
        <div 
          className={`${styles.navItem} ${activeTab === 'metrics' ? styles.active : ''}`}
          onClick={() => setActiveTab('metrics')}
        >
          <span className={styles.navIcon}>■</span> SYSTEM METRICS
        </div>
        <div 
          className={`${styles.navItem} ${activeTab === 'audit' ? styles.active : ''}`}
          onClick={() => {
            setActiveTab('audit');
            fetchAuditLogs();
          }}
        >
          <span className={styles.navIcon}>■</span> AUDIT LOGS
        </div>
        {role === 'Admin' && (
          <div 
            className={`${styles.navItem} ${activeTab === 'admin' ? styles.active : ''}`}
            onClick={() => {
              setActiveTab('admin');
              fetchAdminUsers();
            }}
          >
            <span className={styles.navIcon}>■</span> ADMIN PANEL
          </div>
        )}
      </aside>

      {/* MAIN CONTENT AREA */}
      <main className={styles.mainContent}>
        {backendOffline && (
          <div style={{ background: 'var(--danger)', color: '#000', padding: '1rem', fontFamily: 'var(--font-mono)', fontWeight: 'bold' }}>
            CRITICAL ERROR: BACKEND API IS UNREACHABLE AT {API_BASE}. ENSURE FASTAPI SERVER IS RUNNING.
          </div>
        )}

        {evalSuccessMsg && (
          <div style={{ background: 'rgba(0, 255, 128, 0.15)', border: '1px solid var(--success)', color: 'var(--success)', padding: '0.75rem 1rem', fontFamily: 'monospace', fontSize: '0.85rem' }}>
            ✓ {evalSuccessMsg}
          </div>
        )}

        {/* STATS BAR (VISIBLE ACROSS VIEWS) */}
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>Total Patients</span>
            <span className={styles.statValue}>{patients.length || '--'}</span>
          </div>
          <div className={styles.statCard} style={{ borderColor: highRiskCount > 0 ? 'var(--danger)' : 'var(--border-color)' }}>
            <span className={styles.statLabel}>High Risk Patients</span>
            <span className={styles.statValue} style={{ color: highRiskCount > 0 ? 'var(--danger)' : 'inherit' }}>
              {highRiskCount}
            </span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>Pending Escalations</span>
            <span className={styles.statValue} style={{ color: pendingEscalationsCount > 0 ? 'var(--warning)' : 'inherit' }}>
              {pendingEscalationsCount}
            </span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>AI Detection Accuracy</span>
            <span className={styles.statValue}>
              {metrics?.aiDetectionRate ? `${(metrics.aiDetectionRate * 100).toFixed(0)}%` : '92%'}
            </span>
          </div>
        </div>

        {/* TAB 1: OVERVIEW */}
        {activeTab === 'overview' && (
          <>
            {/* CHART SECTION */}
            <div className={styles.chartSection}>
              <div className={styles.sectionHeader}>
                <div>
                  <h2 className={styles.sectionTitle}>
                    VITAL TRENDS // {selectedPatient ? selectedPatient.name : 'NO PATIENT SELECTED'}
                  </h2>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                    BED: {selectedPatient?.bed_number || '--'} | CURRENT AI STATUS: {selectedPatient?.risk_level ? `${selectedPatient.risk_level.toUpperCase()} RISK` : 'UNASSESSED'}
                  </span>
                </div>
                
                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                  <button 
                    onClick={handleExportHandover}
                    style={{ 
                      padding: '0.5rem 0.85rem', 
                      fontSize: '0.8rem', 
                      background: '#1a1a1a', 
                      color: '#fff', 
                      border: '1px solid var(--border-color)', 
                      fontFamily: 'monospace', 
                      cursor: 'pointer' 
                    }}
                  >
                    📥 HANDOVER REPORT
                  </button>
                  <button 
                    onClick={handleBatchEvaluate} 
                    disabled={isBatchEvaluating}
                    style={{ 
                      padding: '0.5rem 0.85rem', 
                      fontSize: '0.8rem', 
                      background: isBatchEvaluating ? '#333' : '#141414', 
                      color: isBatchEvaluating ? '#888' : 'var(--warning)', 
                      border: '1px solid var(--warning)', 
                      fontFamily: 'monospace', 
                      fontWeight: 'bold', 
                      cursor: isBatchEvaluating ? 'not-allowed' : 'pointer' 
                    }}
                  >
                    {isBatchEvaluating ? 'EVALUATING WARD...' : '⚡ BATCH EVALUATE WARD'}
                  </button>
                  <button 
                    onClick={() => selectedPatientId && handleEvaluate(selectedPatientId)} 
                    disabled={isEvaluating}
                    style={{ 
                      padding: '0.5rem 1rem', 
                      fontSize: '0.8rem', 
                      background: isEvaluating ? '#333' : 'var(--text-primary)', 
                      color: isEvaluating ? '#888' : '#000', 
                      border: 'none', 
                      fontFamily: 'monospace', 
                      fontWeight: 'bold', 
                      cursor: isEvaluating ? 'not-allowed' : 'pointer' 
                    }}
                  >
                    {isEvaluating ? 'EVALUATING...' : '⚡ EVALUATE PATIENT'}
                  </button>
                </div>
              </div>

              {/* CHART WITH CLEAR LEGEND & FORMATTED UNITS */}
              <div style={{ flex: 1, width: '100%', minHeight: 0 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trendData} margin={{ top: 15, right: 30, left: 10, bottom: 5 }}>
                    <XAxis dataKey="timestamp" stroke="var(--border-color)" tick={{ fill: 'var(--text-secondary)', fontSize: 12, fontFamily: 'monospace' }} />
                    <YAxis domain={[0, 160]} stroke="var(--border-color)" tick={{ fill: 'var(--text-secondary)', fontSize: 12, fontFamily: 'monospace' }} />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend 
                      wrapperStyle={{ paddingTop: '10px', fontFamily: 'monospace', fontSize: '0.8rem' }}
                      formatter={(value) => <span style={{ color: '#ccc' }}>{value}</span>}
                    />
                    
                    <ReferenceLine y={100} label={{ value: 'CRITICAL: Tachycardia (100 bpm)', fill: 'var(--warning)', fontSize: 10, position: 'insideTopRight', dy: -8 }} stroke="var(--warning)" strokeDasharray="3 3" />
                    <ReferenceLine y={90} label={{ value: 'CRITICAL: Hypoxia Limit (90% SpO2)', fill: 'var(--danger)', fontSize: 10, position: 'insideBottomRight', dy: 8 }} stroke="var(--danger)" strokeDasharray="3 3" />

                    <Line type="monotone" dataKey="systolicBP" name="Systolic BP (mmHg)" stroke="#ffffff" strokeWidth={2} dot={{ r: 4, fill: '#ffffff' }} isAnimationActive={false} />
                    <Line type="monotone" dataKey="heartRate" name="Heart Rate (bpm)" stroke="var(--danger)" strokeWidth={2} dot={{ r: 4, fill: 'var(--danger)' }} isAnimationActive={false} />
                    <Line type="monotone" dataKey="spO2" name="SpO2 (%)" stroke="var(--success)" strokeWidth={2} dot={{ r: 4, fill: 'var(--success)' }} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* BOTTOM SPLIT PANELS */}
            <div className={styles.bottomGrid}>
              {/* PATIENT QUICK LIST */}
              <div className={styles.panel}>
                <div className={styles.panelHeader} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>PATIENT LIST // QUICK SELECT</span>
                  <button onClick={() => setActiveTab('patients')} style={{ fontSize: '0.7rem', padding: '0.2rem 0.5rem', background: 'transparent', border: '1px solid var(--border-color)', color: 'var(--text-secondary)', cursor: 'pointer', fontFamily: 'monospace' }}>
                    VIEW ALL DIRECTORY →
                  </button>
                </div>
                <div className={styles.panelContent}>
                  {patients.map(patient => (
                    <div 
                      key={patient.patient_id} 
                      className={`${styles.patientRow} ${selectedPatientId === patient.patient_id ? styles.active : ''}`}
                      onClick={() => setSelectedPatientId(patient.patient_id)}
                    >
                      <div>
                        <div className={styles.patientName}>{patient.name}</div>
                        <div className={styles.patientBed}>BED {patient.bed_number} • ID: {patient.patient_id}</div>
                      </div>
                      <span className={`badge ${patient.risk_level === 'High' ? 'badge-danger' : patient.risk_level === 'Medium' ? 'badge-warning' : patient.risk_level === 'Low' ? 'badge-success' : ''}`}>
                        {patient.risk_level ? `${patient.risk_level.toUpperCase()} RISK` : 'UNASSESSED'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* CLINICIAN INBOX PANEL */}
              <div className={styles.panel}>
                <div className={styles.panelHeader} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>CLINICIAN INBOX ({pendingEscalationsCount} PENDING)</span>
                  <button onClick={() => setActiveTab('inbox')} style={{ fontSize: '0.7rem', padding: '0.2rem 0.5rem', background: 'transparent', border: '1px solid var(--border-color)', color: 'var(--text-secondary)', cursor: 'pointer', fontFamily: 'monospace' }}>
                    FULL INBOX →
                  </button>
                </div>
                <div className={styles.panelContent}>
                  {escalations.filter(e => e.status === 'pending').length === 0 ? (
                    <div style={{ color: 'var(--text-secondary)', fontFamily: 'monospace', padding: '2rem', textAlign: 'center' }}>
                      ✓ NO PENDING ESCALATIONS REQUIRE REVIEW
                    </div>
                  ) : (
                    escalations.filter(e => e.status === 'pending').map(escalation => (
                      <div key={escalation.id} className={`${styles.inboxCard} fade-in`}>
                        <div className={styles.inboxHeader}>
                          <div className={styles.inboxMeta}>
                            <span style={{ fontWeight: 'bold', fontSize: '1rem' }}>
                              {patients.find(p => p.patient_id === escalation.patient_id)?.name || escalation.patient_id}
                            </span>
                            <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                              CONFIDENCE: {escalation.recommendation?.confidence_score ? `${(escalation.recommendation.confidence_score * 100).toFixed(0)}%` : 'N/A'}
                            </span>
                            {escalation.recommendation?.latency_ms && (
                              <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                LATENCY: {escalation.recommendation.latency_ms}ms
                              </span>
                            )}
                          </div>
                          <span className="badge badge-danger">ESCALATION</span>
                        </div>

                        <div className={styles.inboxReasoning} style={{ background: '#0a0a0a', padding: '0.75rem', borderLeft: '2px solid var(--danger)', marginTop: '0.5rem' }}>
                          <strong style={{ color: '#fff', display: 'block', marginBottom: '0.2rem' }}>AI Clinical Reasoning:</strong>
                          {escalation.recommendation?.reasoning}
                        </div>

                        <div className={styles.inboxActions}>
                          {role === 'Doctor' ? (
                            <>
                              <button className={styles.btnApprove} onClick={() => handleAction(escalation.id, 'approve')}>
                                APPROVE
                              </button>
                              <button className={styles.btnReject} onClick={() => handleAction(escalation.id, 'reject')}>
                                REJECT
                              </button>
                            </>
                          ) : (
                            <div style={{ color: 'var(--warning)', fontFamily: 'monospace', fontSize: '0.8rem', padding: '0.5rem', background: '#1a1a00', border: '1px solid var(--warning)' }}>
                              🔒 AWAITING DOCTOR REVIEW
                            </div>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </>
        )}

        {/* TAB 2: PATIENTS DIRECTORY & DETAILED VIEW */}
        {activeTab === 'patients' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            {/* SEARCH & FILTERS BAR */}
            <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', background: '#0f0f0f', padding: '1rem', border: '1px solid var(--border-color)' }}>
              <input 
                type="text" 
                placeholder="Search patient by name, bed #, or ID..." 
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                style={{ flex: 1, padding: '0.6rem 1rem', background: '#141414', border: '1px solid var(--border-color)', color: '#fff', fontFamily: 'monospace' }}
              />
              
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>RISK FILTER:</span>
                {['ALL', 'High', 'Medium', 'Low', 'UNASSESSED'].map(rf => (
                  <button
                    key={rf}
                    onClick={() => setRiskFilter(rf)}
                    style={{
                      padding: '0.4rem 0.75rem',
                      fontSize: '0.75rem',
                      fontFamily: 'monospace',
                      background: riskFilter === rf ? 'var(--text-primary)' : '#141414',
                      color: riskFilter === rf ? '#000' : 'var(--text-secondary)',
                      border: '1px solid var(--border-color)',
                      cursor: 'pointer'
                    }}
                  >
                    {rf.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            {/* SPLIT VIEW: DIRECTORY LIST & SELECTED PATIENT PROFILE */}
            <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: '1.5rem' }}>
              {/* PATIENT LIST COLUMN */}
              <div style={{ border: '1px solid var(--border-color)', background: '#0a0a0a', maxHeight: '700px', overflowY: 'auto' }}>
                <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', fontFamily: 'monospace', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  PATIENT DIRECTORY ({filteredPatients.length} MATCHES)
                </div>
                {filteredPatients.map(p => (
                  <div
                    key={p.patient_id}
                    onClick={() => {
                      setSelectedPatientId(p.patient_id);
                      fetchPatientDetail(p.patient_id);
                    }}
                    style={{
                      padding: '1rem',
                      borderBottom: '1px solid var(--border-color)',
                      cursor: 'pointer',
                      background: selectedPatientId === p.patient_id ? '#141414' : 'transparent',
                      borderLeft: selectedPatientId === p.patient_id ? '3px solid var(--text-primary)' : 'none'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <span style={{ fontWeight: 'bold', fontSize: '0.95rem' }}>{p.name}</span>
                      <span className={`badge ${p.risk_level === 'High' ? 'badge-danger' : p.risk_level === 'Medium' ? 'badge-warning' : p.risk_level === 'Low' ? 'badge-success' : ''}`}>
                        {p.risk_level ? `${p.risk_level.toUpperCase()}` : 'UNASSESSED'}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontFamily: 'monospace', marginTop: '0.3rem' }}>
                      BED: {p.bed_number} • ID: {p.patient_id}
                    </div>
                  </div>
                ))}
              </div>

              {/* SELECTED PATIENT EXPANDED DETAILS */}
              <div style={{ border: '1px solid var(--border-color)', background: '#0c0c0c', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                {selectedPatientDetail ? (
                  <>
                    {/* PATIENT HEADER */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem' }}>
                      <div>
                        <h2 style={{ fontSize: '1.4rem', letterSpacing: '0.05em' }}>{selectedPatientDetail.name}</h2>
                        <div style={{ fontFamily: 'monospace', fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                          PATIENT ID: {selectedPatientDetail.patient_id} | BED LOCATION: BED {selectedPatientDetail.bed_number}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                        <span className={`badge ${selectedPatientDetail.risk_level === 'High' ? 'badge-danger' : selectedPatientDetail.risk_level === 'Medium' ? 'badge-warning' : selectedPatientDetail.risk_level === 'Low' ? 'badge-success' : ''}`} style={{ fontSize: '0.9rem', padding: '0.4rem 0.8rem' }}>
                          RISK LEVEL: {selectedPatientDetail.risk_level ? selectedPatientDetail.risk_level.toUpperCase() : 'UNASSESSED'}
                        </span>
                        <button 
                          onClick={() => handleEvaluate(selectedPatientDetail.patient_id)}
                          disabled={isEvaluating}
                          style={{ padding: '0.5rem 1rem', background: 'var(--text-primary)', color: '#000', border: 'none', fontWeight: 'bold', fontFamily: 'monospace', cursor: 'pointer' }}
                        >
                          {isEvaluating ? 'EVALUATING...' : 'RUN AI EVALUATION'}
                        </button>
                      </div>
                    </div>

                    {/* LATEST VITALS SNAPSHOT CARDS */}
                    {selectedPatientDetail.observations && selectedPatientDetail.observations.length > 0 && (
                      <div>
                        <h3 style={{ fontSize: '0.85rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
                          LATEST VITAL SIGNS SNAPSHOT ({new Date(selectedPatientDetail.observations[selectedPatientDetail.observations.length - 1].timestamp).toLocaleTimeString()})
                        </h3>
                        {(() => {
                          const latestObs = selectedPatientDetail.observations[selectedPatientDetail.observations.length - 1];
                          const vitals = latestObs.vitals || {};
                          return (
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '1rem' }}>
                              <div style={{ background: '#121212', border: '1px solid #222', padding: '1rem', textAlign: 'center' }}>
                                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>HEART RATE</div>
                                <div style={{ fontSize: '1.4rem', fontWeight: 'bold', margin: '0.4rem 0', color: vitals.hr > 100 ? 'var(--danger)' : '#fff' }}>
                                  {vitals.hr !== null ? `${vitals.hr}` : 'N/A'} <span style={{ fontSize: '0.7rem' }}>bpm</span>
                                </div>
                              </div>
                              <div style={{ background: '#121212', border: '1px solid #222', padding: '1rem', textAlign: 'center' }}>
                                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>SYSTOLIC BP</div>
                                <div style={{ fontSize: '1.4rem', fontWeight: 'bold', margin: '0.4rem 0', color: vitals.bp_systolic < 90 ? 'var(--danger)' : '#fff' }}>
                                  {vitals.bp_systolic !== null ? `${vitals.bp_systolic}` : 'N/A'} <span style={{ fontSize: '0.7rem' }}>mmHg</span>
                                </div>
                              </div>
                              <div style={{ background: '#121212', border: '1px solid #222', padding: '1rem', textAlign: 'center' }}>
                                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>SpO2</div>
                                <div style={{ fontSize: '1.4rem', fontWeight: 'bold', margin: '0.4rem 0', color: vitals.spo2 < 95 ? 'var(--warning)' : 'var(--success)' }}>
                                  {vitals.spo2 !== null ? `${vitals.spo2.toFixed(1)}%` : 'N/A'}
                                </div>
                              </div>
                              <div style={{ background: '#121212', border: '1px solid #222', padding: '1rem', textAlign: 'center' }}>
                                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>RESP RATE</div>
                                <div style={{ fontSize: '1.4rem', fontWeight: 'bold', margin: '0.4rem 0' }}>
                                  {vitals.resp_rate !== null ? `${vitals.resp_rate}` : 'N/A'} <span style={{ fontSize: '0.7rem' }}>/min</span>
                                </div>
                              </div>
                              <div style={{ background: '#121212', border: '1px solid #222', padding: '1rem', textAlign: 'center' }}>
                                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>TEMP</div>
                                <div style={{ fontSize: '1.4rem', fontWeight: 'bold', margin: '0.4rem 0' }}>
                                  {vitals.temp !== null ? `${vitals.temp.toFixed(1)}` : 'N/A'} <span style={{ fontSize: '0.7rem' }}>°C</span>
                                </div>
                              </div>
                              <div style={{ background: '#121212', border: '1px solid #222', padding: '1rem', textAlign: 'center' }}>
                                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>AVPU</div>
                                <div style={{ fontSize: '1.4rem', fontWeight: 'bold', margin: '0.4rem 0' }}>
                                  {vitals.consciousness_level || 'A'}
                                </div>
                              </div>
                            </div>
                          );
                        })()}
                      </div>
                    )}

                    {/* NURSING NOTES */}
                    {selectedPatientDetail.observations && selectedPatientDetail.observations.length > 0 && (
                      <div style={{ background: '#101010', border: '1px solid var(--border-color)', padding: '1rem' }}>
                        <h4 style={{ fontSize: '0.8rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>LATEST NURSING NOTES</h4>
                        <p style={{ fontSize: '0.9rem', lineHeight: '1.5', color: '#ccc' }}>
                          "{selectedPatientDetail.observations[selectedPatientDetail.observations.length - 1].nursing_notes}"
                        </p>
                      </div>
                    )}

                    {/* OBSERVATIONS HISTORY TABLE */}
                    <div>
                      <h4 style={{ fontSize: '0.85rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>12-HOUR OBSERVATION TIMELINE</h4>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'monospace', fontSize: '0.8rem' }}>
                        <thead>
                          <tr style={{ background: '#141414', borderBottom: '1px solid var(--border-color)', textAlign: 'left' }}>
                            <th style={{ padding: '0.6rem' }}>TIMESTAMP</th>
                            <th style={{ padding: '0.6rem' }}>HR</th>
                            <th style={{ padding: '0.6rem' }}>BP</th>
                            <th style={{ padding: '0.6rem' }}>SpO2</th>
                            <th style={{ padding: '0.6rem' }}>RR</th>
                            <th style={{ padding: '0.6rem' }}>TEMP</th>
                            <th style={{ padding: '0.6rem' }}>CLINICAL NOTES</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedPatientDetail.observations?.map((obs, idx) => (
                            <tr key={idx} style={{ borderBottom: '1px solid #1c1c1c' }}>
                              <td style={{ padding: '0.6rem', color: 'var(--text-secondary)' }}>{new Date(obs.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
                              <td style={{ padding: '0.6rem' }}>{obs.vitals?.hr ?? '--'} bpm</td>
                              <td style={{ padding: '0.6rem' }}>{obs.vitals?.bp_systolic ?? '--'}/{obs.vitals?.bp_diastolic ?? '--'}</td>
                              <td style={{ padding: '0.6rem' }}>{obs.vitals?.spo2 ? `${obs.vitals.spo2.toFixed(1)}%` : '--'}</td>
                              <td style={{ padding: '0.6rem' }}>{obs.vitals?.resp_rate ?? '--'}</td>
                              <td style={{ padding: '0.6rem' }}>{obs.vitals?.temp ? `${obs.vitals.temp.toFixed(1)}°C` : '--'}</td>
                              <td style={{ padding: '0.6rem', color: '#888', maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{obs.nursing_notes}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <div style={{ color: 'var(--text-secondary)', fontFamily: 'monospace', padding: '3rem', textAlign: 'center' }}>
                    SELECT A PATIENT FROM THE DIRECTORY TO VIEW FULL MEDICAL PROFILE AND VITALS HISTORY.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: INBOX */}
        {activeTab === 'inbox' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0f0f0f', padding: '1rem', border: '1px solid var(--border-color)' }}>
              <h2 style={{ fontSize: '1rem', fontFamily: 'monospace' }}>CLINICIAN ESCALATION INBOX</h2>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                {['pending', 'approved', 'rejected', 'all'].map(status => (
                  <button
                    key={status}
                    onClick={() => setInboxFilter(status)}
                    style={{
                      padding: '0.4rem 0.8rem',
                      fontSize: '0.75rem',
                      fontFamily: 'monospace',
                      background: inboxFilter === status ? 'var(--text-primary)' : '#141414',
                      color: inboxFilter === status ? '#000' : 'var(--text-secondary)',
                      border: '1px solid var(--border-color)',
                      cursor: 'pointer'
                    }}
                  >
                    {status.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '1rem' }}>
              {filteredEscalations.length === 0 ? (
                <div style={{ color: 'var(--text-secondary)', fontFamily: 'monospace', padding: '3rem', border: '1px solid var(--border-color)', textAlign: 'center' }}>
                  NO ESCALATIONS FOUND FOR FILTER: {inboxFilter.toUpperCase()}
                </div>
              ) : (
                filteredEscalations.map(esc => {
                  const p = patients.find(patient => patient.patient_id === esc.patient_id);
                  const rec = esc.recommendation || {};
                  return (
                    <div key={esc.id} style={{ border: '1px solid var(--border-color)', background: '#0c0c0c', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div>
                          <div style={{ fontSize: '1.1rem', fontWeight: 'bold' }}>
                            {p?.name || esc.patient_id} <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>({p?.bed_number ? `BED ${p.bed_number}` : esc.patient_id})</span>
                          </div>
                          <div style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                            ESCALATED AT: {new Date(esc.created_at).toLocaleString()} | STATUS: <strong style={{ color: esc.status === 'approved' ? 'var(--success)' : esc.status === 'rejected' ? 'var(--danger)' : 'var(--warning)' }}>{esc.status.toUpperCase()}</strong>
                          </div>
                        </div>
                        <span className={`badge ${rec.risk_level === 'High' ? 'badge-danger' : rec.risk_level === 'Medium' ? 'badge-warning' : 'badge-success'}`}>
                          {rec.risk_level ? `${rec.risk_level.toUpperCase()} RISK` : 'ESCALATION'}
                        </span>
                      </div>

                      <div style={{ background: '#111', padding: '1rem', borderLeft: '3px solid var(--text-primary)', fontSize: '0.9rem', lineHeight: '1.5' }}>
                        <div style={{ fontWeight: 'bold', fontSize: '0.8rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
                          GROQ LLM CLINICAL REASONING:
                        </div>
                        {rec.reasoning}
                      </div>

                      {rec.recommended_action && (
                        <div style={{ fontSize: '0.85rem', fontFamily: 'monospace', color: 'var(--warning)' }}>
                          RECOMMENDED CLINICAL ACTION: {rec.recommended_action}
                        </div>
                      )}

                      <div style={{ display: 'flex', gap: '2rem', fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-secondary)', borderTop: '1px solid #1a1a1a', paddingTop: '0.75rem' }}>
                        <div>NEWS2 SCORE: <strong style={{ color: '#fff' }}>{rec.news2_score ?? 0}</strong></div>
                        <div>CONFIDENCE: <strong style={{ color: '#fff' }}>{rec.confidence_score ? `${(rec.confidence_score * 100).toFixed(0)}%` : 'N/A'}</strong></div>
                        <div>LATENCY: <strong style={{ color: '#fff' }}>{rec.latency_ms ?? 0}ms</strong></div>
                        <div>TOKENS: <strong style={{ color: '#fff' }}>{rec.tokens_used ?? 0}</strong></div>
                      </div>

                      {esc.status === 'pending' && (
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginTop: '0.5rem' }}>
                          {role === 'Doctor' ? (
                            <>
                              <button className={styles.btnApprove} onClick={() => handleAction(esc.id, 'approve')}>
                                APPROVE ESCALATION
                              </button>
                              <button className={styles.btnReject} onClick={() => handleAction(esc.id, 'reject')}>
                                REJECT ESCALATION
                              </button>
                            </>
                          ) : (
                            <div style={{ gridColumn: 'span 2', color: 'var(--warning)', fontFamily: 'monospace', fontSize: '0.8rem', padding: '0.5rem', background: '#1a1a00', border: '1px solid var(--warning)', textAlign: 'center' }}>
                              🔒 AWAITING DOCTOR REVIEW
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* TAB 4: METRICS */}
        {activeTab === 'metrics' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
            <h2 style={{ fontSize: '1rem', fontFamily: 'monospace' }}>SYSTEM ANALYTICS & AI PERFORMANCE METRICS</h2>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
              {/* PATIENT RISK DISTRIBUTION CHART */}
              <div style={{ border: '1px solid var(--border-color)', padding: '1.5rem', background: '#0c0c0c' }}>
                <h3 style={{ fontSize: '0.9rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                  PATIENT POPULATION RISK DISTRIBUTION
                </h3>
                <div style={{ height: '260px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={[
                      { name: 'High Risk', count: patients.filter(p => p.risk_level === 'High').length, fill: '#ff4d4d' },
                      { name: 'Medium Risk', count: patients.filter(p => p.risk_level === 'Medium').length, fill: '#ffaa00' },
                      { name: 'Low Risk', count: patients.filter(p => p.risk_level === 'Low').length, fill: '#00cc66' },
                      { name: 'Unassessed', count: patients.filter(p => !p.risk_level).length, fill: '#666666' }
                    ]}>
                      <XAxis dataKey="name" stroke="var(--border-color)" tick={{ fill: '#ccc', fontSize: 12, fontFamily: 'monospace' }} />
                      <YAxis stroke="var(--border-color)" tick={{ fill: '#ccc', fontSize: 12, fontFamily: 'monospace' }} />
                      <Tooltip contentStyle={{ background: '#000', border: '1px solid #333', fontFamily: 'monospace' }} />
                      <Bar dataKey="count">
                        {[
                          <Cell key="cell-0" fill="var(--danger)" />,
                          <Cell key="cell-1" fill="var(--warning)" />,
                          <Cell key="cell-2" fill="var(--success)" />,
                          <Cell key="cell-3" fill="#666" />
                        ]}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* BENCHMARK PERFORMANCE COMPARISON */}
              <div style={{ border: '1px solid var(--border-color)', padding: '1.5rem', background: '#0c0c0c', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                <h3 style={{ fontSize: '0.9rem', fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
                  BASELINE NEWS2 VS AI DETECTION PERFORMANCE
                </h3>
                
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'monospace', fontSize: '0.85rem', marginBottom: '0.4rem' }}>
                    <span>NEWS2 HEURISTIC BASELINE DETECTION:</span>
                    <strong>{metrics?.baselineDetectionRate ? `${(metrics.baselineDetectionRate * 100).toFixed(0)}%` : '60%'}</strong>
                  </div>
                  <div style={{ width: '100%', background: '#222', height: '12px' }}>
                    <div style={{ width: `${(metrics?.baselineDetectionRate || 0.6) * 100}%`, background: '#888', height: '100%' }}></div>
                  </div>
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'monospace', fontSize: '0.85rem', marginBottom: '0.4rem' }}>
                    <span>GROQ LLM AI DETECTION RATE:</span>
                    <strong style={{ color: 'var(--success)' }}>{metrics?.aiDetectionRate ? `${(metrics.aiDetectionRate * 100).toFixed(0)}%` : '92%'}</strong>
                  </div>
                  <div style={{ width: '100%', background: '#222', height: '12px' }}>
                    <div style={{ width: `${(metrics?.aiDetectionRate || 0.92) * 100}%`, background: 'var(--success)', height: '100%' }}></div>
                  </div>
                </div>

                <div style={{ background: '#141414', padding: '1rem', border: '1px solid var(--border-color)', fontFamily: 'monospace', fontSize: '0.85rem', marginTop: 'auto' }}>
                  <div>DETECTION IMPROVEMENT: <strong style={{ color: 'var(--success)' }}>+{metrics?.detectionRateImprovement ? `${(metrics.detectionRateImprovement * 100).toFixed(0)}%` : '+32%'}</strong> OVER BASELINE</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.3rem' }}>
                    The Groq LLM agent detects subtle trends and incomplete history cases missed by raw NEWS2 cutoff scores.
                  </div>
                </div>
              </div>
            </div>

            {/* PERFORMANCE LATENCY PROFILING */}
            {performance && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginTop: '1rem' }}>
                <div style={{ border: '1px solid var(--border-color)', padding: '1.5rem', background: '#0c0c0c' }}>
                  <h3 style={{ fontSize: '0.9rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                    LANGGRAPH PIPELINE LATENCY PROFILING (AVG)
                  </h3>
                  <div style={{ height: '260px' }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={Object.entries(performance.avg_node_timings || {}).map(([name, ms]) => ({ name: name.replace(/_/g, ' '), ms }))} layout="vertical" margin={{ left: 40 }}>
                        <XAxis type="number" stroke="var(--border-color)" tick={{ fill: '#ccc', fontSize: 12, fontFamily: 'monospace' }} />
                        <YAxis dataKey="name" type="category" width={120} stroke="var(--border-color)" tick={{ fill: '#ccc', fontSize: 10, fontFamily: 'monospace' }} />
                        <Tooltip contentStyle={{ background: '#000', border: '1px solid #333', fontFamily: 'monospace' }} formatter={(value) => [`${value} ms`, 'Latency']} />
                        <Bar dataKey="ms" fill="var(--text-primary)" barSize={20} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div style={{ border: '1px solid var(--border-color)', padding: '1.5rem', background: '#0c0c0c', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>AVG EVAL LATENCY</div>
                    <div style={{ fontSize: '2rem', fontWeight: 'bold', color: '#fff' }}>{performance.avg_total_latency_ms} <span style={{ fontSize: '1rem' }}>ms</span></div>
                  </div>
                  <div style={{ border: '1px solid var(--border-color)', padding: '1.5rem', background: '#0c0c0c', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>P95 EVAL LATENCY</div>
                    <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--warning)' }}>{performance.p95_latency_ms} <span style={{ fontSize: '1rem' }}>ms</span></div>
                  </div>
                  <div style={{ border: '1px solid var(--border-color)', padding: '1.5rem', background: '#0c0c0c', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>GROQ API SUCCESS</div>
                    <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--success)' }}>{(performance.groq_success_rate * 100).toFixed(1)}%</div>
                  </div>
                  <div style={{ border: '1px solid var(--border-color)', padding: '1.5rem', background: '#0c0c0c', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>AVG TOKENS / EVAL</div>
                    <div style={{ fontSize: '2rem', fontWeight: 'bold', color: '#fff' }}>{performance.avg_tokens_used}</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 5: AUDIT LOGS */}
        {activeTab === 'audit' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0f0f0f', padding: '1rem', border: '1px solid var(--border-color)' }}>
              <h2 style={{ fontSize: '1rem', fontFamily: 'monospace' }}>IMMUTABLE CLINICIAN AUDIT LOG</h2>
              <button onClick={fetchAuditLogs} style={{ padding: '0.4rem 0.8rem', fontSize: '0.75rem', fontFamily: 'monospace', background: '#141414', color: '#fff', border: '1px solid var(--border-color)', cursor: 'pointer' }}>
                🔄 REFRESH AUDIT LOGS
              </button>
            </div>

            <div style={{ border: '1px solid var(--border-color)', background: '#0c0c0c', padding: '1rem', maxHeight: '650px', overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'monospace', fontSize: '0.85rem' }}>
                <thead>
                  <tr style={{ background: '#141414', borderBottom: '1px solid var(--border-color)', textAlign: 'left' }}>
                    <th style={{ padding: '0.75rem' }}>TIMESTAMP</th>
                    <th style={{ padding: '0.75rem' }}>USER</th>
                    <th style={{ padding: '0.75rem' }}>ROLE</th>
                    <th style={{ padding: '0.75rem' }}>ACTION</th>
                    <th style={{ padding: '0.75rem' }}>EVENT DETAILS</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.length === 0 ? (
                    <tr>
                      <td colSpan={5} style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>NO AUDIT LOGS RECORDED YET</td>
                    </tr>
                  ) : (
                    auditLogs.map((log) => (
                      <tr key={log.id} style={{ borderBottom: '1px solid #1a1a1a' }}>
                        <td style={{ padding: '0.75rem', color: 'var(--text-secondary)' }}>{new Date(log.timestamp).toLocaleString()}</td>
                        <td style={{ padding: '0.75rem', fontWeight: 'bold', color: '#fff' }}>{log.username}</td>
                        <td style={{ padding: '0.75rem' }}>
                          <span className={`badge ${log.role === 'Doctor' ? 'badge-danger' : log.role === 'Nurse' ? 'badge-warning' : 'badge-success'}`}>
                            {log.role}
                          </span>
                        </td>
                        <td style={{ padding: '0.75rem', color: 'var(--warning)', fontWeight: 'bold' }}>{log.action}</td>
                        <td style={{ padding: '0.75rem', color: '#ccc' }}>{log.details}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 6: ADMIN PANEL */}
        {activeTab === 'admin' && role === 'Admin' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0f0f0f', padding: '1rem', border: '1px solid var(--border-color)' }}>
              <h2 style={{ fontSize: '1rem', fontFamily: 'monospace' }}>ADMIN USER MANAGEMENT</h2>
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '2rem' }}>
              <div style={{ border: '1px solid var(--border-color)', padding: '1.5rem', background: '#0c0c0c' }}>
                <h3 style={{ fontSize: '0.9rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '1rem' }}>ADD NEW CLINICIAN</h3>
                <form onSubmit={handleAddUser} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>USERNAME</label>
                    <input type="text" required value={newUsername} onChange={e => setNewUsername(e.target.value)} style={{ width: '100%', padding: '0.75rem', background: '#141414', color: 'var(--text-primary)', border: '1px solid var(--border-color)', fontFamily: 'monospace' }} />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>PASSWORD</label>
                    <input type="password" required value={newPassword} onChange={e => setNewPassword(e.target.value)} style={{ width: '100%', padding: '0.75rem', background: '#141414', color: 'var(--text-primary)', border: '1px solid var(--border-color)', fontFamily: 'monospace' }} />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>ROLE</label>
                    <select value={newRole} onChange={e => setNewRole(e.target.value)} style={{ width: '100%', padding: '0.75rem', background: '#141414', color: 'var(--text-primary)', border: '1px solid var(--border-color)', fontFamily: 'monospace' }}>
                      <option value="Doctor">Doctor</option>
                      <option value="Nurse">Nurse</option>
                      <option value="Admin">Admin</option>
                    </select>
                  </div>
                  <button type="submit" style={{ width: '100%', padding: '0.85rem', background: 'var(--text-primary)', color: '#000', border: 'none', fontWeight: 'bold', fontFamily: 'monospace', cursor: 'pointer', marginTop: '0.5rem' }}>CREATE USER</button>
                </form>
              </div>

              <div style={{ border: '1px solid var(--border-color)', background: '#0c0c0c', padding: '1rem' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'monospace', fontSize: '0.85rem' }}>
                  <thead>
                    <tr style={{ background: '#141414', borderBottom: '1px solid var(--border-color)', textAlign: 'left' }}>
                      <th style={{ padding: '0.75rem' }}>ID</th>
                      <th style={{ padding: '0.75rem' }}>USERNAME</th>
                      <th style={{ padding: '0.75rem' }}>ROLE</th>
                      <th style={{ padding: '0.75rem' }}>ACTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    {adminUsers.map((user) => (
                      <tr key={user.id} style={{ borderBottom: '1px solid #1a1a1a' }}>
                        <td style={{ padding: '0.75rem', color: 'var(--text-secondary)' }}>{user.id}</td>
                        <td style={{ padding: '0.75rem', fontWeight: 'bold', color: '#fff' }}>{user.username}</td>
                        <td style={{ padding: '0.75rem' }}>
                          <span className={`badge ${user.role === 'Doctor' ? 'badge-danger' : user.role === 'Nurse' ? 'badge-warning' : 'badge-success'}`}>
                            {user.role}
                          </span>
                        </td>
                        <td style={{ padding: '0.75rem' }}>
                          <button onClick={() => handleDeleteUser(user.id)} style={{ padding: '0.3rem 0.6rem', background: 'var(--danger)', color: '#000', border: 'none', fontFamily: 'monospace', fontSize: '0.7rem', cursor: 'pointer', fontWeight: 'bold' }}>DELETE</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* FOOTER */}
      <footer className={styles.footer}>
        <div>COE PROJECT — ED DETERIORATION MONITOR v2.2.0</div>
        <div>AUTHENTICATED USER: <span style={{ color: '#fff' }}>{username || role}</span> | TOTAL PATIENTS: {patients.length} | PENDING ALERTS: {pendingEscalationsCount}</div>
      </footer>

      {/* FLOATING AI CLINICAL COPILOT WIDGET */}
      <div style={{ position: 'fixed', bottom: '24px', right: '24px', zIndex: 1000 }}>
        {!chatOpen ? (
          <button
            onClick={() => setChatOpen(true)}
            style={{
              padding: '0.85rem 1.35rem',
              background: 'var(--text-primary)',
              color: '#000',
              border: 'none',
              fontWeight: 'bold',
              fontFamily: 'monospace',
              fontSize: '0.85rem',
              cursor: 'pointer',
              boxShadow: '0 8px 24px rgba(0,0,0,0.8)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              borderRadius: '2px'
            }}
          >
            💬 CLINICAL COPILOT
          </button>
        ) : (
          <div style={{ width: '480px', height: '600px', maxHeight: '85vh', maxWidth: '92vw', background: '#0a0a0a', border: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', boxShadow: '0 16px 48px rgba(0,0,0,0.95)' }}>
            {/* CHAT HEADER */}
            <div style={{ padding: '0.85rem 1rem', background: '#121212', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontFamily: 'monospace', fontWeight: 'bold', fontSize: '0.9rem', color: '#fff', letterSpacing: '0.05em' }}>
                  ED CLINICAL COPILOT
                </div>
                <div style={{ fontSize: '0.7rem', fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
                  AI Clinical Decision Support & Ward Assistant
                </div>
              </div>
              <button onClick={() => setChatOpen(false)} style={{ background: 'transparent', border: 'none', color: '#888', cursor: 'pointer', fontSize: '1.2rem', fontFamily: 'monospace' }}>✕</button>
            </div>

            {/* CONTEXT BANNER */}
            <div style={{ padding: '0.45rem 1rem', background: '#161616', borderBottom: '1px solid #222', fontSize: '0.75rem', fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
              CONTEXT: <span style={{ color: selectedPatient ? 'var(--text-primary)' : '#888' }}>{selectedPatient ? `${selectedPatient.name} (BED ${selectedPatient.bed_number})` : 'FULL WARD DATABASE'}</span>
            </div>

            {/* MESSAGES AREA WITH TEXT OVERFLOW PREVENTION */}
            <div style={{ flex: 1, padding: '1rem', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              {chatMessages.map((msg, idx) => (
                <div
                  key={idx}
                  style={{
                    alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '90%',
                    padding: '0.85rem',
                    background: msg.sender === 'user' ? '#1c1c1c' : msg.ood ? 'rgba(255, 170, 0, 0.1)' : '#121212',
                    border: msg.sender === 'user' ? '1px solid #333' : msg.ood ? '1px solid var(--warning)' : '1px solid var(--border-color)',
                    fontFamily: 'monospace',
                    fontSize: '0.8rem',
                    lineHeight: '1.5',
                    color: '#eee',
                    overflowX: 'auto',
                    wordBreak: 'break-word',
                    overflowWrap: 'anywhere'
                  }}
                >
                  {(() => {
                    const lines = msg.text.split('\n');
                    const elements = [];
                    let inTable = false;
                    let tableRows = [];

                    const renderTable = (tRows, key) => {
                      const cleanRows = tRows.filter(r => !r.every(cell => /^[:\s-]+$/.test(cell.trim())));
                      if (cleanRows.length === 0) return null;
                      const header = cleanRows[0];
                      const body = cleanRows.slice(1);

                      return (
                        <div key={key} style={{ overflowX: 'auto', margin: '0.6rem 0', border: '1px solid var(--border-color)', borderRadius: '2px' }}>
                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem', fontFamily: 'monospace' }}>
                            <thead>
                              <tr style={{ background: '#1a1a1a', borderBottom: '1px solid var(--border-color)' }}>
                                {header.map((cell, cIdx) => (
                                  <th key={cIdx} style={{ padding: '0.5rem', textAlign: 'left', color: '#fff', fontWeight: 'bold' }}>
                                    {cell.trim().replace(/\*\*/g, '')}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {body.map((row, rIdx) => (
                                <tr key={rIdx} style={{ borderBottom: '1px solid #1c1c1c', background: rIdx % 2 === 0 ? '#111' : '#0c0c0c' }}>
                                  {row.map((cell, cIdx) => (
                                    <td key={cIdx} style={{ padding: '0.5rem', color: '#ccc' }}>
                                      {cell.trim().replace(/\*\*/g, '')}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      );
                    };

                    lines.forEach((line, idx) => {
                      const trimmed = line.trim();
                      if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
                        if (!inTable) {
                          inTable = true;
                          tableRows = [];
                        }
                        tableRows.push(trimmed.split('|').slice(1, -1));
                      } else {
                        if (inTable) {
                          elements.push(renderTable(tableRows, `table-${idx}`));
                          inTable = false;
                          tableRows = [];
                        }
                        if (trimmed !== '') {
                          const parts = line.split(/(\*\*.*?\*\*)/g);
                          elements.push(
                            <div key={`line-${idx}`} style={{ minHeight: '1.2em', margin: '0.15rem 0' }}>
                              {parts.map((part, pIdx) => {
                                if (part.startsWith('**') && part.endsWith('**')) {
                                  return <strong key={pIdx} style={{ color: '#ffffff', fontWeight: 'bold' }}>{part.slice(2, -2)}</strong>;
                                }
                                return part;
                              })}
                            </div>
                          );
                        } else {
                          elements.push(<div key={`space-${idx}`} style={{ height: '0.35rem' }} />);
                        }
                      }
                    });

                    if (inTable) {
                      elements.push(renderTable(tableRows, `table-end`));
                    }

                    return elements;
                  })()}
                </div>
              ))}
              {isSendingChat && (
                <div style={{ alignSelf: 'flex-start', fontFamily: 'monospace', fontSize: '0.75rem', color: 'var(--text-secondary)', padding: '0.5rem' }}>
                  Analyzing ward data & guidelines...
                </div>
              )}
            </div>

            {/* CLINICAL QUICK PROMPT PILLS */}
            <div style={{ padding: '0.5rem 0.75rem', background: '#0e0e0e', borderTop: '1px solid #1a1a1a', display: 'flex', gap: '0.4rem', overflowX: 'auto' }}>
              <button onClick={() => handleSendChat("Summarize all assessed patients and their risk levels.")} style={{ fontSize: '0.7rem', fontFamily: 'monospace', padding: '0.3rem 0.6rem', background: '#181818', border: '1px solid #333', color: '#ccc', cursor: 'pointer', whiteSpace: 'nowrap' }}>
                Ward Patients Status
              </button>
              <button onClick={() => handleSendChat("List all High Risk patients in the ward.")} style={{ fontSize: '0.7rem', fontFamily: 'monospace', padding: '0.3rem 0.6rem', background: '#181818', border: '1px solid #333', color: '#ccc', cursor: 'pointer', whiteSpace: 'nowrap' }}>
                High Risk Summary
              </button>
              <button onClick={() => handleSendChat("What are the warning signs of sepsis in ED patients?")} style={{ fontSize: '0.7rem', fontFamily: 'monospace', padding: '0.3rem 0.6rem', background: '#181818', border: '1px solid #333', color: '#ccc', cursor: 'pointer', whiteSpace: 'nowrap' }}>
                Sepsis Guidelines
              </button>
            </div>

            {/* CHAT INPUT AREA */}
            <form onSubmit={(e) => { e.preventDefault(); handleSendChat(); }} style={{ padding: '0.75rem', background: '#121212', borderTop: '1px solid var(--border-color)', display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                placeholder="Ask about patient status, vitals, NEWS2..."
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                style={{ flex: 1, padding: '0.65rem 0.8rem', background: '#1a1a1a', border: '1px solid var(--border-color)', color: '#fff', fontFamily: 'monospace', fontSize: '0.8rem' }}
              />
              <button type="submit" disabled={isSendingChat} style={{ padding: '0.65rem 1.1rem', background: 'var(--text-primary)', color: '#000', border: 'none', fontWeight: 'bold', fontFamily: 'monospace', fontSize: '0.8rem', cursor: 'pointer' }}>
                SEND
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
