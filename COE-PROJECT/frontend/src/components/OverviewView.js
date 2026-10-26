import s from './dashboard.module.css';
import VitalsChart from './VitalsChart';
import RiskBadge from './RiskBadge';
import EscalationCard from './EscalationCard';

export default function OverviewView({
  patients, selectedPatient, selectedPatientId, onSelect, trendData, escalations, role,
  onResolve, onEvaluate, isEvaluating, onBatch, batch, onExport, onNavigate,
}) {
  const pending = escalations.filter((e) => e.status === 'pending');
  const batchLabel = batch
    ? (batch.total ? `EVALUATING ${batch.completed}/${batch.total}` : 'STARTING...')
    : '⚡ BATCH EVALUATE WARD';

  return (
    <>
      <section className={s.chartSection}>
        <div className={s.sectionHeader}>
          <div>
            <h2 className={s.sectionTitle}>VITAL TRENDS // {selectedPatient ? selectedPatient.name : 'NO PATIENT SELECTED'}</h2>
            <span className={s.subtle}>
              BED: {selectedPatient?.bed_number || '--'} | CURRENT AI STATUS:{' '}
              {selectedPatient?.risk_level ? `${selectedPatient.risk_level.toUpperCase()} RISK` : 'UNASSESSED'}
            </span>
          </div>
          <div className={s.actions}>
            <button className="btn" onClick={onExport}>📥 HANDOVER REPORT</button>
            <button className="btn btn-warn" onClick={onBatch} disabled={!!batch}>{batchLabel}</button>
            <button className="btn btn-solid" onClick={() => onEvaluate(selectedPatientId)} disabled={isEvaluating || !selectedPatientId}>
              {isEvaluating ? 'EVALUATING...' : '⚡ EVALUATE PATIENT'}
            </button>
          </div>
        </div>
        {batch?.total > 0 && (
          <div className={s.progress} aria-label="Batch evaluation progress">
            <div className={s.progressBar} style={{ width: `${(batch.completed / batch.total) * 100}%` }} />
          </div>
        )}
        <VitalsChart data={trendData} />
        <div className={s.chartKey}>
          <span style={{ color: 'var(--warning)' }}>┄ 100 bpm tachycardia threshold</span>
          <span style={{ color: 'var(--danger)' }}>┄ 90% SpO2 hypoxia threshold</span>
        </div>
      </section>

      <div className={s.bottomGrid}>
        <section className={s.panel}>
          <div className={s.panelHeader}>
            <span>PATIENT LIST // QUICK SELECT</span>
            <button className={s.linkBtn} onClick={() => onNavigate('patients')}>VIEW ALL →</button>
          </div>
          <div className={s.panelContent}>
            {patients.map((p) => (
              <button key={p.patient_id}
                className={`${s.patientRow} ${selectedPatientId === p.patient_id ? s.active : ''}`}
                onClick={() => onSelect(p.patient_id)}>
                <span>
                  <span className={s.patientName}>{p.name}</span>
                  <span className={s.patientBed}>BED {p.bed_number} • ID: {p.patient_id}</span>
                </span>
                <RiskBadge level={p.risk_level} suffix=" RISK" />
              </button>
            ))}
          </div>
        </section>

        <section className={s.panel}>
          <div className={s.panelHeader}>
            <span>CLINICIAN INBOX ({pending.length} PENDING)</span>
            <button className={s.linkBtn} onClick={() => onNavigate('inbox')}>FULL INBOX →</button>
          </div>
          <div className={s.panelContent}>
            {pending.length === 0 ? (
              <div className={s.empty}>✓ NO PENDING ESCALATIONS REQUIRE REVIEW</div>
            ) : pending.map((esc) => (
              <EscalationCard key={esc.id} esc={esc} role={role} onResolve={onResolve}
                patient={patients.find((p) => p.patient_id === esc.patient_id)} />
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
