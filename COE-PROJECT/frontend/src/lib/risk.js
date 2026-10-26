export const RISK_LEVELS = ['High', 'Medium', 'Low', 'Unknown'];

export const riskBadgeClass = (level) =>
  level === 'High' ? 'badge-danger'
    : (level === 'Medium' || level === 'Unknown') ? 'badge-warning'
    : level === 'Low' ? 'badge-success'
    : '';

export const formatPct = (value) => (typeof value === 'number' ? `${(value * 100).toFixed(0)}%` : '--');

export const formatTime = (iso, opts = { hour: '2-digit', minute: '2-digit' }) =>
  new Date(iso).toLocaleTimeString([], opts);

// Out-of-range checks used to highlight vital signs (NEWS2-aligned cut-offs)
export const vitalStatus = {
  hr: (v) => (v == null ? null : v > 110 || v <= 40 ? 'danger' : v > 90 || v <= 50 ? 'warning' : null),
  bp_systolic: (v) => (v == null ? null : v <= 90 || v >= 220 ? 'danger' : v <= 100 ? 'warning' : null),
  spo2: (v) => (v == null ? null : v <= 91 ? 'danger' : v < 95 ? 'warning' : null),
  resp_rate: (v) => (v == null ? null : v >= 25 || v <= 8 ? 'danger' : v >= 21 || v <= 11 ? 'warning' : null),
  temp: (v) => (v == null ? null : v <= 35 || v >= 39.1 ? 'danger' : v < 36.1 || v > 38 ? 'warning' : null),
};
