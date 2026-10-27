'use client';

import { useEffect, useState } from 'react';
import s from '../components/dashboard.module.css';
import { useAuth } from '../hooks/useAuth';
import { useWard } from '../hooks/useWard';
import { API_BASE } from '../lib/config';
import LoginScreen from '../components/LoginScreen';
import Header from '../components/Header';
import Sidebar from '../components/Sidebar';
import StatsBar from '../components/StatsBar';
import NoticeBanner from '../components/NoticeBanner';
import OverviewView from '../components/OverviewView';
import PatientsView from '../components/PatientsView';
import InboxView from '../components/InboxView';
import MetricsView from '../components/MetricsView';
import AuditView from '../components/AuditView';
import AdminView from '../components/AdminView';
import ChatWidget from '../components/ChatWidget';
import ViewBoundary from '../components/ViewBoundary';

const views = { overview: 'OVERVIEW', patients: 'PATIENTS', inbox: 'INBOX', metrics: 'METRICS', audit: 'AUDIT LOG', admin: 'ADMIN' };

export default function Dashboard() {
  const auth = useAuth();
  const ward = useWard({ token: auth.token, authFetch: auth.authFetch });
  const [tab, setTab] = useState('overview');

  const { fetchPerformance, fetchAuditLogs, fetchAdminUsers } = ward;
  useEffect(() => {
    if (!auth.token) { setTab('overview'); return; }
    if (tab === 'metrics') fetchPerformance();
    if (tab === 'audit') fetchAuditLogs();
    if (tab === 'admin') fetchAdminUsers();
  }, [auth.token, tab, fetchPerformance, fetchAuditLogs, fetchAdminUsers]);

  if (!auth.restored) return null;
  if (!auth.token) return <LoginScreen onLogin={auth.login} />;

  return (
    <div className={s.container}>
      <Header role={auth.role} backendOffline={ward.backendOffline} liveConnected={ward.liveConnected}
        llmEnabled={ward.llmEnabled} onLogout={auth.logout} />
      <Sidebar activeTab={tab} onSelect={setTab} role={auth.role}
        patientCount={ward.patients.length} pendingCount={ward.pendingCount} />

      <main className={s.mainContent}>
        {ward.backendOffline && (
          <div className={s.offlineBanner} role="alert">
            CRITICAL ERROR: BACKEND API IS UNREACHABLE AT {API_BASE}. ENSURE THE FASTAPI SERVER IS RUNNING.
          </div>
        )}
        <NoticeBanner notice={ward.notice} />
        <StatsBar patientCount={ward.patients.length} highRiskCount={ward.highRiskCount}
          pendingCount={ward.pendingCount} metrics={ward.metrics} />

        <ViewBoundary key={tab} name={views[tab] || tab.toUpperCase()}>
        {tab === 'overview' && (
          <OverviewView patients={ward.patients} selectedPatient={ward.selectedPatient}
            selectedPatientId={ward.selectedPatientId} onSelect={ward.setSelectedPatientId}
            trendData={ward.trendData} escalations={ward.escalations} role={auth.role}
            onResolve={ward.resolveEscalation} onEvaluate={ward.evaluatePatient}
            isEvaluating={ward.isEvaluating} onBatch={ward.batchEvaluate} batch={ward.batch}
            onExport={ward.exportHandover} onNavigate={setTab} />
        )}
        {tab === 'patients' && (
          <PatientsView patients={ward.patients} selectedPatientId={ward.selectedPatientId}
            onSelect={ward.setSelectedPatientId} detail={ward.detail}
            onEvaluate={ward.evaluatePatient} isEvaluating={ward.isEvaluating} />
        )}
        {tab === 'inbox' && (
          <InboxView escalations={ward.escalations} patients={ward.patients} role={auth.role}
            onResolve={ward.resolveEscalation} />
        )}
        {tab === 'metrics' && (
          <MetricsView patients={ward.patients} metrics={ward.metrics} performance={ward.performance} />
        )}
        {tab === 'audit' && <AuditView logs={ward.auditLogs} onRefresh={ward.fetchAuditLogs} />}
        {tab === 'admin' && auth.role === 'Admin' && (
          <AdminView users={ward.adminUsers} currentUsername={auth.username}
            onAdd={ward.addUser} onDelete={ward.deleteUser} />
        )}
        </ViewBoundary>
      </main>

      <footer className={s.footer}>
        <div>COE PROJECT — ED DETERIORATION MONITOR v2.3</div>
        <div>
          USER: <strong>{auth.username || auth.role}</strong> | PATIENTS: {ward.patients.length} | PENDING ALERTS: {ward.pendingCount}
        </div>
      </footer>

      <ViewBoundary name="CHAT">
        <ChatWidget authFetch={auth.authFetch} selectedPatient={ward.selectedPatient} />
      </ViewBoundary>
    </div>
  );
}
