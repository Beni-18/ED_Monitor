import s from './dashboard.module.css';
import { formatPct } from '../lib/risk';
import { pickBenchmark } from '../lib/benchmark';

export default function StatsBar({ patientCount, highRiskCount, pendingCount, metrics }) {
  const bench = pickBenchmark(metrics);
  return (
    <div className={s.statsGrid}>
      <div className={s.statCard}>
        <span className={s.statLabel}>Total Patients</span>
        <span className={s.statValue}>{patientCount || '--'}</span>
      </div>
      <div className={s.statCard} style={{ borderColor: highRiskCount > 0 ? 'var(--danger)' : undefined }}>
        <span className={s.statLabel}>High Risk Patients</span>
        <span className={s.statValue} style={{ color: highRiskCount > 0 ? 'var(--danger)' : undefined }}>{highRiskCount}</span>
      </div>
      <div className={s.statCard}>
        <span className={s.statLabel}>Pending Escalations</span>
        <span className={s.statValue} style={{ color: pendingCount > 0 ? 'var(--warning)' : undefined }}>{pendingCount}</span>
      </div>
      <div className={s.statCard}>
        <span className={s.statLabel}>AI Detection{bench.label ? ` (${bench.label})` : ''}</span>
        <span className={s.statValue}>{bench.incomplete ? '--' : formatPct(bench.data?.ai?.detection_rate)}</span>
        {bench.incomplete && <span className={s.subtle}>INCOMPLETE RUN — RE-RUN BENCHMARK</span>}
      </div>
    </div>
  );
}
