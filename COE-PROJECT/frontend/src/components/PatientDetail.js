import s from './dashboard.module.css';
import RiskBadge from './RiskBadge';
import { formatTime, vitalStatus } from '../lib/risk';

const num = (v, digits) => (v == null ? 'N/A' : digits != null ? v.toFixed(digits) : String(v));

function VitalCard({ label, value, unit, status }) {
  return (
    <div className={s.vitalCard}>
      <div className={s.vitalLabel}>{label}</div>
      <div className={s.vitalValue} style={{ color: status === 'danger' ? 'var(--danger)' : status === 'warning' ? 'var(--warning)' : undefined }}>
        {value} {unit && value !== 'N/A' && <span className={s.vitalUnit}>{unit}</span>}
      </div>
    </div>
  );
}

export default function PatientDetail({ detail, onEvaluate, isEvaluating }) {
  if (!detail) {
    return <div className={s.empty}>SELECT A PATIENT FROM THE DIRECTORY TO VIEW FULL MEDICAL PROFILE AND VITALS HISTORY.</div>;
  }
  const obs = detail.observations || [];
  const latest = obs[obs.length - 1];
  const v = latest?.vitals || {};

  return (
    <>
      <div className={s.detailHead}>
        <div>
          <h2 className={s.detailName}>{detail.name}</h2>
          <div className={s.subtle}>PATIENT ID: {detail.patient_id} | BED {detail.bed_number}</div>
        </div>
        <div className={s.actions}>
          <RiskBadge level={detail.risk_level} suffix="" className={s.bigBadge} />
          <button className="btn btn-solid" onClick={() => onEvaluate(detail.patient_id)} disabled={isEvaluating}>
            {isEvaluating ? 'EVALUATING...' : 'RUN AI EVALUATION'}
          </button>
        </div>
      </div>

      {latest && (
        <div>
          <h3 className={s.miniHeading}>LATEST VITAL SIGNS ({formatTime(latest.timestamp, undefined)})</h3>
          <div className={s.vitalsGrid}>
            <VitalCard label="HEART RATE" value={num(v.hr)} unit="bpm" status={vitalStatus.hr(v.hr)} />
            <VitalCard label="SYSTOLIC BP" value={num(v.bp_systolic)} unit="mmHg" status={vitalStatus.bp_systolic(v.bp_systolic)} />
            <VitalCard label="SpO2" value={v.spo2 == null ? 'N/A' : `${v.spo2.toFixed(1)}%`} status={vitalStatus.spo2(v.spo2)} />
            <VitalCard label="RESP RATE" value={num(v.resp_rate)} unit="/min" status={vitalStatus.resp_rate(v.resp_rate)} />
            <VitalCard label="TEMP" value={num(v.temp, 1)} unit="°C" status={vitalStatus.temp(v.temp)} />
            <VitalCard label="AVPU" value={v.consciousness_level || 'N/A'} status={v.consciousness_level && v.consciousness_level !== 'A' ? 'danger' : null} />
          </div>
          <div className={s.notes}>
            <h4 className={s.miniHeading}>LATEST NURSING NOTES</h4>
            <p>“{latest.nursing_notes}”</p>
          </div>
        </div>
      )}

      <div>
        <h4 className={s.miniHeading}>OBSERVATION TIMELINE ({obs.length})</h4>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr><th>TIME</th><th>HR</th><th>BP</th><th>SpO2</th><th>RR</th><th>TEMP</th><th>NOTES</th></tr>
            </thead>
            <tbody>
              {obs.map((o) => (
                <tr key={o.timestamp}>
                  <td className={s.dim}>{formatTime(o.timestamp)}</td>
                  <td>{o.vitals?.hr ?? '--'} bpm</td>
                  <td>{o.vitals?.bp_systolic ?? '--'}/{o.vitals?.bp_diastolic ?? '--'}</td>
                  <td>{o.vitals?.spo2 != null ? `${o.vitals.spo2.toFixed(1)}%` : '--'}</td>
                  <td>{o.vitals?.resp_rate ?? '--'}</td>
                  <td>{o.vitals?.temp != null ? `${o.vitals.temp.toFixed(1)}°C` : '--'}</td>
                  <td className={s.noteCell} title={o.nursing_notes}>{o.nursing_notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
