'use client';

import { useState } from 'react';
import s from './dashboard.module.css';
import EscalationCard from './EscalationCard';

const FILTERS = ['pending', 'approved', 'rejected', 'all'];

export default function InboxView({ escalations, patients, role, onResolve }) {
  const [filter, setFilter] = useState('pending');
  const shown = escalations
    .filter((e) => filter === 'all' || e.status === filter)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  return (
    <div className={s.stack}>
      <div className={s.toolbar}>
        <h2 className={s.sectionTitle}>CLINICIAN ESCALATION INBOX</h2>
        <div className={s.chips}>
          {FILTERS.map((f) => (
            <button key={f} className={`${s.chip} ${filter === f ? s.chipActive : ''}`} onClick={() => setFilter(f)}>
              {f.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 ? (
        <div className={s.empty}>NO ESCALATIONS FOUND FOR FILTER: {filter.toUpperCase()}</div>
      ) : shown.map((esc) => (
        <EscalationCard key={esc.id} esc={esc} role={role} onResolve={onResolve}
          patient={patients.find((p) => p.patient_id === esc.patient_id)} />
      ))}
    </div>
  );
}
