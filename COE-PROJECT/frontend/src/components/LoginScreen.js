'use client';

import { useState } from 'react';
import s from './dashboard.module.css';

export default function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    const message = await onLogin(username, password);
    if (message) setError(message);
    setBusy(false);
  };

  return (
    <div className={s.loginWrap}>
      <form onSubmit={submit} className={s.loginForm}>
        <div className={s.loginTitle}>
          <div className={s.loginMark} />
          <h2>ED MONITOR // LOGIN</h2>
        </div>

        {error && <div className={s.loginError} role="alert">{error}</div>}

        <label className={s.fieldLabel} htmlFor="login-username">USERNAME</label>
        <input id="login-username" className="input" type="text" autoComplete="username"
          placeholder="doctor / nurse / admin" value={username} onChange={(e) => setUsername(e.target.value)} />

        <label className={s.fieldLabel} htmlFor="login-password">PASSWORD</label>
        <input id="login-password" className="input" type="password" autoComplete="current-password"
          placeholder="password123" value={password} onChange={(e) => setPassword(e.target.value)} />

        <button type="submit" className="btn btn-solid" disabled={busy} style={{ width: '100%', padding: '0.85rem' }}>
          {busy ? 'AUTHENTICATING...' : 'AUTHENTICATE'}
        </button>

        <div className={s.demoCreds}>
          <div>DEMO CREDENTIALS:</div>
          {['doctor', 'nurse', 'admin'].map((u) => (
            <div key={u}>• {u[0].toUpperCase() + u.slice(1)}: <code>{u}</code> / <code>password123</code></div>
          ))}
        </div>
      </form>
    </div>
  );
}
