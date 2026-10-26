'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE } from '../lib/config';
import { formatTime } from '../lib/risk';

const FLAGGED = ['High', 'Medium', 'Unknown'];

/**
 * All ward data + actions for the dashboard: patients, escalations, metrics,
 * the live WebSocket feed, single/batch evaluation and the admin/audit lists.
 */
export function useWard({ token, authFetch }) {
  const [patients, setPatients] = useState([]);
  const [escalations, setEscalations] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [performance, setPerformance] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [adminUsers, setAdminUsers] = useState([]);
  const [selectedPatientId, setSelectedPatientId] = useState(null);
  const [detail, setDetail] = useState(null);

  const [backendOffline, setBackendOffline] = useState(false);
  const [liveConnected, setLiveConnected] = useState(false);
  const [llmEnabled, setLlmEnabled] = useState(null);
  const [notice, setNotice] = useState(null); // { type: 'success' | 'error', text }
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [batch, setBatch] = useState(null); // { completed, total } while running

  const selectedRef = useRef(null);
  useEffect(() => { selectedRef.current = selectedPatientId; }, [selectedPatientId]);

  const noticeTimer = useRef(null);
  const showNotice = useCallback((type, text, ms = 6000) => {
    clearTimeout(noticeTimer.current);
    setNotice({ type, text });
    noticeTimer.current = setTimeout(() => setNotice(null), ms);
  }, []);
  useEffect(() => () => clearTimeout(noticeTimer.current), []);

  // ── Fetchers ───────────────────────────────────────────────────────────────
  const fetchPatients = useCallback(async () => {
    const res = await authFetch('/api/patients');
    if (!res.ok) throw new Error(`patients ${res.status}`);
    const data = await res.json();
    setPatients(data);
    setSelectedPatientId((prev) => prev ?? data[0]?.patient_id ?? null);
  }, [authFetch]);

  const fetchData = useCallback(async () => {
    try {
      const [pRes, eRes, mRes] = await Promise.all([
        authFetch('/api/patients'),
        authFetch('/api/escalations'),
        authFetch('/api/metrics'),
      ]);
      if (!pRes.ok || !eRes.ok || !mRes.ok) throw new Error('bad response');
      const [pData, eData, mData] = await Promise.all([pRes.json(), eRes.json(), mRes.json()]);
      setPatients(pData);
      setEscalations(eData);
      setMetrics(mData);
      setSelectedPatientId((prev) => prev ?? pData[0]?.patient_id ?? null);
      setBackendOffline(false);
    } catch (err) {
      console.error('Error fetching data:', err);
      setBackendOffline(true);
    }
  }, [authFetch]);

  const fetchEscalations = useCallback(async () => {
    const res = await authFetch('/api/escalations');
    if (res.ok) setEscalations(await res.json());
  }, [authFetch]);

  const fetchDetail = useCallback(async (id) => {
    if (!id) return;
    try {
      const res = await authFetch(`/api/patients/${id}`);
      if (res.ok && selectedRef.current === id) setDetail(await res.json());
    } catch (err) {
      console.error('Error fetching patient detail:', err);
    }
  }, [authFetch]);

  const fetchPerformance = useCallback(async () => {
    try {
      const res = await authFetch('/api/performance');
      if (res.ok) setPerformance(await res.json());
    } catch (err) {
      console.error('Error fetching performance metrics:', err);
    }
  }, [authFetch]);

  const fetchAuditLogs = useCallback(async () => {
    try {
      const res = await authFetch('/api/audit-logs');
      if (res.ok) setAuditLogs(await res.json());
    } catch (err) {
      console.error('Error fetching audit logs:', err);
    }
  }, [authFetch]);

  const fetchAdminUsers = useCallback(async () => {
    try {
      const res = await authFetch('/api/admin/users');
      if (res.ok) setAdminUsers(await res.json());
    } catch (err) {
      console.error('Error fetching users:', err);
    }
  }, [authFetch]);

  // ── Initial load, health, selected-patient detail ──────────────────────────
  useEffect(() => {
    if (!token) {
      setPatients([]); setEscalations([]); setMetrics(null); setDetail(null);
      setSelectedPatientId(null); setPerformance(null); setLiveConnected(false);
      return;
    }
    fetchData();
    fetch(`${API_BASE}/api/health`).then((r) => r.json()).then((h) => setLlmEnabled(h.llm_enabled)).catch(() => {});
  }, [token, fetchData]);

  useEffect(() => {
    setDetail(null);
    if (token && selectedPatientId) fetchDetail(selectedPatientId);
  }, [token, selectedPatientId, fetchDetail]);

  // ── Live feed (auto-reconnects) ────────────────────────────────────────────
  useEffect(() => {
    if (!token) return undefined;
    let ws;
    let retry;
    let closed = false;
    const wsUrl = `${API_BASE.replace(/^http/, 'ws')}/ws/vitals?token=${encodeURIComponent(token)}`;

    const connect = () => {
      ws = new WebSocket(wsUrl);
      ws.onopen = () => setLiveConnected(true);
      ws.onclose = () => {
        setLiveConnected(false);
        if (!closed) retry = setTimeout(connect, 3000);
      };
      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'VITAL_UPDATE') {
            fetchPatients().catch(() => {});
            if (selectedRef.current === message.patient_id) fetchDetail(message.patient_id);
          } else if (message.type === 'NEW_ESCALATION') {
            showNotice('error', `New system escalation: patient ${message.patient_id} flagged ${message.risk_level} risk`, 8000);
            fetchPatients().catch(() => {});
            fetchEscalations();
          }
        } catch (e) {
          console.error('WS parse error', e);
        }
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [token, fetchPatients, fetchEscalations, fetchDetail, showNotice]);

  // ── Derived ────────────────────────────────────────────────────────────────
  const trendData = useMemo(() => (detail?.observations || []).map((obs) => ({
    timestamp: formatTime(obs.timestamp),
    heartRate: obs.vitals?.hr ?? null,
    systolicBP: obs.vitals?.bp_systolic ?? null,
    spO2: obs.vitals?.spo2 != null ? Number(obs.vitals.spo2.toFixed(1)) : null,
  })), [detail]);

  const selectedPatient = useMemo(
    () => patients.find((p) => p.patient_id === selectedPatientId) || null,
    [patients, selectedPatientId],
  );
  const pendingCount = useMemo(() => escalations.filter((e) => e.status === 'pending').length, [escalations]);
  const highRiskCount = useMemo(() => patients.filter((p) => p.risk_level === 'High').length, [patients]);

  // ── Actions ────────────────────────────────────────────────────────────────
  const resolveEscalation = useCallback(async (id, action) => {
    try {
      const res = await authFetch(`/api/escalations/${id}/${action}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clinician_notes: `Actioned (${action.toUpperCase()}) via ED Monitor Dashboard` }),
      });
      if (res.status === 403) showNotice('error', 'Permission denied: only Doctors can approve or reject escalations.');
      else if (res.status === 409) showNotice('error', 'That escalation was already resolved.');
      else if (!res.ok) showNotice('error', `Could not ${action} escalation (${res.status}).`);
      else showNotice('success', `Escalation ${action === 'approve' ? 'approved' : 'rejected'}.`, 3000);
    } catch (err) {
      console.error(`Error ${action} escalation:`, err);
      showNotice('error', 'Network error while updating the escalation.');
    }
    fetchData();
  }, [authFetch, fetchData, showNotice]);

  const evaluatePatient = useCallback(async (id) => {
    if (!id) return;
    setIsEvaluating(true);
    try {
      const res = await authFetch(`/api/evaluate/${id}`, { method: 'POST' });
      if (!res.ok) {
        showNotice('error', 'Evaluation failed. Check API connectivity.');
        return;
      }
      const rec = await res.json();
      if (FLAGGED.includes(rec.risk_level)) {
        await authFetch(`/api/escalations/${id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recommendation: rec }),
        });
      }
      showNotice('success', `Evaluated: ${rec.risk_level} risk (${(rec.confidence_score * 100).toFixed(0)}% confidence)`);
      await fetchData();
      fetchDetail(id);
    } catch (err) {
      console.error('Error evaluating:', err);
      showNotice('error', 'Network error during evaluation.');
    } finally {
      setIsEvaluating(false);
    }
  }, [authFetch, fetchData, fetchDetail, showNotice]);

  const batchEvaluate = useCallback(async () => {
    if (batch) return;
    setBatch({ completed: 0, total: 0 });
    try {
      const res = await authFetch('/api/evaluate/batch', { method: 'POST' });
      if (!res.ok) throw new Error(`start ${res.status}`);
      let job = await res.json();
      while (job.status === 'running') {
        setBatch({ completed: job.completed, total: job.total });
        await new Promise((r) => setTimeout(r, 1000));
        const poll = await authFetch(`/api/evaluate/batch/${job.job_id}`);
        if (!poll.ok) throw new Error(`poll ${poll.status}`);
        job = await poll.json();
      }
      if (job.status === 'done') {
        const r = job.result;
        const failed = r.failed_count ? ` ${r.failed_count} failed.` : '';
        showNotice('success',
          `Ward evaluation complete: ${r.evaluated_count} patients in ${r.total_time_seconds}s, ${r.escalations_created} new escalations.${failed}`,
          10000);
      } else {
        showNotice('error', `Batch evaluation failed: ${job.error || 'unknown error'}`);
      }
      await fetchData();
    } catch (err) {
      console.error('Error in batch evaluate:', err);
      showNotice('error', 'Batch evaluation failed.');
    } finally {
      setBatch(null);
    }
  }, [authFetch, batch, fetchData, showNotice]);

  const exportHandover = useCallback(async () => {
    try {
      const res = await authFetch('/api/export/handover');
      if (!res.ok) throw new Error(String(res.status));
      const report = await res.json();
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `clinical_handover_report_${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showNotice('success', `Downloaded handover report for ${report.high_medium_risk_patients_count} High/Medium risk patients.`);
    } catch (err) {
      console.error('Error exporting handover report:', err);
      showNotice('error', 'Could not export the handover report.');
    }
  }, [authFetch, showNotice]);

  const addUser = useCallback(async (user) => {
    const res = await authFetch('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(user),
    });
    if (res.ok) {
      fetchAdminUsers();
      return '';
    }
    const body = await res.json().catch(() => ({}));
    const detailMsg = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join('; ') : body.detail;
    return detailMsg || 'Failed to add user';
  }, [authFetch, fetchAdminUsers]);

  const deleteUser = useCallback(async (id) => {
    const res = await authFetch(`/api/admin/users/${id}`, { method: 'DELETE' });
    if (res.ok) fetchAdminUsers();
    else showNotice('error', 'Failed to delete user.');
  }, [authFetch, fetchAdminUsers, showNotice]);

  return {
    patients, escalations, metrics, performance, auditLogs, adminUsers,
    selectedPatientId, setSelectedPatientId, selectedPatient, detail, trendData,
    backendOffline, liveConnected, llmEnabled, notice, isEvaluating, batch,
    pendingCount, highRiskCount,
    fetchPerformance, fetchAuditLogs, fetchAdminUsers,
    resolveEscalation, evaluatePatient, batchEvaluate, exportHandover, addUser, deleteUser,
  };
}
