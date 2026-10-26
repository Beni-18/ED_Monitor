'use client';

import { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '../lib/config';

const read = (key) => {
  try { return localStorage.getItem(key); } catch { return null; }
};
const write = (key, value) => {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* storage unavailable: session just won't persist */ }
};

/** Owns the JWT session and an authenticated fetch that logs out on 401. */
export function useAuth() {
  const [session, setSession] = useState({ token: null, role: null, username: '' });
  const [restored, setRestored] = useState(false);

  useEffect(() => {
    const token = read('token');
    const role = read('role');
    if (token && role) setSession({ token, role, username: read('username') || '' });
    setRestored(true);
  }, []);

  const logout = useCallback(() => {
    setSession({ token: null, role: null, username: '' });
    ['token', 'role', 'username'].forEach((k) => write(k, null));
  }, []);

  /** Resolves to '' on success or a user-facing error message. */
  const login = useCallback(async (username, password) => {
    try {
      const res = await fetch(`${API_BASE}/api/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username, password }),
      });
      if (res.status === 429) return 'Too many attempts. Please wait a minute and try again.';
      if (!res.ok) return 'Invalid credentials';
      const data = await res.json();
      setSession({ token: data.access_token, role: data.role, username });
      write('token', data.access_token);
      write('role', data.role);
      write('username', username);
      return '';
    } catch {
      return 'Network error — unable to reach authentication server.';
    }
  }, []);

  const { token } = session;
  const authFetch = useCallback(async (path, options = {}) => {
    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { ...options.headers, Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) logout();
    return res;
  }, [token, logout]);

  return { ...session, restored, login, logout, authFetch };
}
