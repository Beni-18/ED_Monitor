import s from './dashboard.module.css';

const roleClass = { Doctor: 'badge-danger', Nurse: 'badge-warning' };

export default function AuditView({ logs, onRefresh }) {
  return (
    <div className={s.stack}>
      <div className={s.toolbar}>
        <h2 className={s.sectionTitle}>CLINICIAN AUDIT LOG (LAST 100)</h2>
        <button className="btn" onClick={onRefresh}>🔄 REFRESH</button>
      </div>
      <div className={`${s.tableCard} table-scroll`}>
        <table className="data-table">
          <thead><tr><th>TIMESTAMP</th><th>USER</th><th>ROLE</th><th>ACTION</th><th>EVENT DETAILS</th></tr></thead>
          <tbody>
            {logs.length === 0 ? (
              <tr><td colSpan={5} className={s.empty}>NO AUDIT LOGS RECORDED YET</td></tr>
            ) : logs.map((log) => (
              <tr key={log.id}>
                <td className={s.dim}>{new Date(log.timestamp).toLocaleString()}</td>
                <td><strong>{log.username}</strong></td>
                <td><span className={`badge ${roleClass[log.role] || 'badge-success'}`}>{log.role}</span></td>
                <td className={s.actionCell}>{log.action}</td>
                <td>{log.details}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
