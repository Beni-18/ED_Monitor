import s from './dashboard.module.css';
import RiskBadge from './RiskBadge';

const statusColor = { approved: 'var(--success)', rejected: 'var(--danger)', pending: 'var(--warning)' };

export default function EscalationCard({ esc, patient, role, onResolve }) {
  const rec = esc.recommendation || {};
  return (
    <article className={`${s.escCard} fade-in`}>
      <div className={s.escHead}>
        <div>
          <div className={s.escName}>
            {patient?.name || esc.patient_id}
            <span className={s.escBed}> ({patient?.bed_number ? `BED ${patient.bed_number}` : esc.patient_id})</span>
          </div>
          <div className={s.escMeta}>
            ESCALATED {new Date(esc.created_at).toLocaleString()} | STATUS:{' '}
            <strong style={{ color: statusColor[esc.status] }}>{esc.status.toUpperCase()}</strong>
          </div>
        </div>
        <RiskBadge level={rec.risk_level} suffix=" RISK" />
      </div>

      <div className={s.escReasoning}>
        <div className={s.escReasoningLabel}>AI CLINICAL REASONING:</div>
        {rec.reasoning}
      </div>

      {rec.recommended_action && (
        <div className={s.escAction}>RECOMMENDED ACTION: {rec.recommended_action}</div>
      )}

      <div className={s.escStats}>
        <div>NEWS2: <strong>{rec.news2_score ?? 0}</strong></div>
        <div>CONFIDENCE: <strong>{rec.confidence_score ? `${(rec.confidence_score * 100).toFixed(0)}%` : 'N/A'}</strong></div>
        {rec.latency_ms > 0 && <div>LATENCY: <strong>{rec.latency_ms}ms</strong></div>}
        {rec.tokens_used > 0 && <div>TOKENS: <strong>{rec.tokens_used}</strong></div>}
      </div>

      {esc.status === 'pending' && (
        role === 'Doctor' ? (
          <div className={s.escButtons}>
            <button className={s.btnApprove} onClick={() => onResolve(esc.id, 'approve')}>APPROVE</button>
            <button className={s.btnReject} onClick={() => onResolve(esc.id, 'reject')}>REJECT</button>
          </div>
        ) : (
          <div className={s.awaiting}>🔒 AWAITING DOCTOR REVIEW</div>
        )
      )}
    </article>
  );
}
