import s from './dashboard.module.css';

export default function Header({ role, backendOffline, liveConnected, llmEnabled, onLogout }) {
  let dotColor = 'var(--success)';
  let status = `ONLINE // ${llmEnabled === false ? 'OFFLINE HEURISTIC MODE' : 'GROQ LLM ACTIVE'}`;
  if (backendOffline) {
    dotColor = 'var(--danger)';
    status = 'SYSTEM OFFLINE';
  } else if (!liveConnected) {
    dotColor = 'var(--warning)';
    status = 'ONLINE // LIVE FEED RECONNECTING';
  }

  return (
    <header className={s.header}>
      <div className={s.logoArea}>
        <div className={s.logoIcon} />
        <h1 className={s.title}>ED DETERIORATION MONITOR</h1>
        <span className={s.versionTag}>AI RAG v2.3</span>
      </div>
      <div className={s.statusArea}>
        <div className={s.statusIndicator}>
          <div className={s.statusDot} style={{ background: dotColor }} />
          {status}
        </div>
        <div className={s.userArea}>
          <span className={s.roleText}>ROLE: <strong>{role?.toUpperCase()}</strong></span>
          <button className={s.userIcon} onClick={onLogout} title="Log out" aria-label="Log out">
            {role ? role.charAt(0) : 'U'}
          </button>
        </div>
      </div>
    </header>
  );
}
