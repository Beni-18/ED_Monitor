'use client';

import { useMemo, useState } from 'react';
import s from './dashboard.module.css';
import RiskBadge from './RiskBadge';
import PatientDetail from './PatientDetail';

const FILTERS = ['ALL', 'High', 'Medium', 'Low', 'Unknown', 'UNASSESSED'];

export default function PatientsView({ patients, selectedPatientId, onSelect, detail, onEvaluate, isEvaluating }) {
  const [query, setQuery] = useState('');
  const [riskFilter, setRiskFilter] = useState('ALL');

  const filtered = useMemo(() => {
    const q = query.toLowerCase();
    return patients.filter((p) => {
      const matches = p.name.toLowerCase().includes(q) || p.bed_number.toLowerCase().includes(q) || p.patient_id.toLowerCase().includes(q);
      if (!matches) return false;
      if (riskFilter === 'ALL') return true;
      if (riskFilter === 'UNASSESSED') return !p.risk_level;
      return p.risk_level === riskFilter;
    });
  }, [patients, query, riskFilter]);

  return (
    <div className={s.stack}>
      <div className={s.toolbar}>
        <input className="input" style={{ flex: 1, minWidth: 180 }} type="search" placeholder="Search by name, bed #, or ID..."
          value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search patients" />
        <div className={s.chips}>
          <span className={s.subtle}>RISK:</span>
          {FILTERS.map((f) => (
            <button key={f} className={`${s.chip} ${riskFilter === f ? s.chipActive : ''}`} onClick={() => setRiskFilter(f)}>
              {f.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div className={s.splitView}>
        <div className={s.directory}>
          <div className={s.directoryHead}>PATIENT DIRECTORY ({filtered.length} MATCHES)</div>
          {filtered.map((p) => (
            <button key={p.patient_id}
              className={`${s.directoryRow} ${selectedPatientId === p.patient_id ? s.directoryActive : ''}`}
              onClick={() => onSelect(p.patient_id)}>
              <span className={s.rowTop}>
                <span className={s.patientName}>{p.name}</span>
                <RiskBadge level={p.risk_level} />
              </span>
              <span className={s.patientBed}>BED: {p.bed_number} • ID: {p.patient_id}</span>
            </button>
          ))}
          {filtered.length === 0 && <div className={s.empty}>NO PATIENTS MATCH</div>}
        </div>

        <div className={s.detailPane}>
          <PatientDetail detail={detail} onEvaluate={onEvaluate} isEvaluating={isEvaluating} />
        </div>
      </div>
    </div>
  );
}
