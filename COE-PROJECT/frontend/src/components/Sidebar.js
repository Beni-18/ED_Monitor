import s from './dashboard.module.css';

export default function Sidebar({ activeTab, onSelect, role, patientCount, pendingCount }) {
  const tabs = [
    { id: 'overview', label: 'OVERVIEW' },
    { id: 'patients', label: `PATIENTS (${patientCount})` },
    { id: 'inbox', label: 'CLINICIAN INBOX', badge: pendingCount },
    { id: 'metrics', label: 'SYSTEM METRICS' },
    { id: 'audit', label: 'AUDIT LOGS' },
    ...(role === 'Admin' ? [{ id: 'admin', label: 'ADMIN PANEL' }] : []),
  ];

  return (
    <nav className={s.sidebar} aria-label="Main navigation">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={`${s.navItem} ${activeTab === tab.id ? s.active : ''}`}
          aria-current={activeTab === tab.id ? 'page' : undefined}
          onClick={() => onSelect(tab.id)}
        >
          <span className={s.navIcon}>■</span> {tab.label}
          {tab.badge > 0 && <span className={s.navBadge}>{tab.badge}</span>}
        </button>
      ))}
    </nav>
  );
}
