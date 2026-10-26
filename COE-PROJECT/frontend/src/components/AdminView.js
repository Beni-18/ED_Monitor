'use client';

import { useState } from 'react';
import s from './dashboard.module.css';

const roleClass = { Doctor: 'badge-danger', Nurse: 'badge-warning' };

export default function AdminView({ users, currentUsername, onAdd, onDelete }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('Doctor');
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    const message = await onAdd({ username, password, role });
    setError(message);
    if (!message) { setUsername(''); setPassword(''); }
  };

  const remove = (user) => {
    if (window.confirm(`Delete user "${user.username}"? This cannot be undone.`)) onDelete(user.id);
  };

  return (
    <div className={s.stack}>
      <div className={s.toolbar}><h2 className={s.sectionTitle}>ADMIN USER MANAGEMENT</h2></div>
      <div className={s.adminGrid}>
        <form className={s.card} onSubmit={submit}>
          <h3 className={s.miniHeading}>ADD NEW CLINICIAN</h3>
          {error && <div className={s.loginError} role="alert">{error}</div>}
          <label className={s.fieldLabel} htmlFor="new-username">USERNAME</label>
          <input id="new-username" className="input" required value={username} onChange={(e) => setUsername(e.target.value)} />
          <label className={s.fieldLabel} htmlFor="new-password">PASSWORD (MIN 8 CHARACTERS)</label>
          <input id="new-password" className="input" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          <label className={s.fieldLabel} htmlFor="new-role">ROLE</label>
          <select id="new-role" className="input" value={role} onChange={(e) => setRole(e.target.value)}>
            <option>Doctor</option><option>Nurse</option><option>Admin</option>
          </select>
          <button type="submit" className="btn btn-solid" style={{ width: '100%', padding: '0.85rem', marginTop: '0.5rem' }}>CREATE USER</button>
        </form>

        <div className={`${s.tableCard} table-scroll`}>
          <table className="data-table">
            <thead><tr><th>ID</th><th>USERNAME</th><th>ROLE</th><th>ACTION</th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td className={s.dim}>{u.id}</td>
                  <td><strong>{u.username}</strong></td>
                  <td><span className={`badge ${roleClass[u.role] || 'badge-success'}`}>{u.role}</span></td>
                  <td>
                    <button className="btn btn-danger" disabled={u.username === currentUsername} onClick={() => remove(u)}>DELETE</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
