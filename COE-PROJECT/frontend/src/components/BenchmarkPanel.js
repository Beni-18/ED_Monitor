'use client';

import { useState } from 'react';
import s from './dashboard.module.css';
import { formatPct } from '../lib/risk';
import { coverageOf, MIN_COVERAGE } from '../lib/benchmark';

function MetricBar({ label, value, color, ci }) {
  return (
    <div className={s.metricRow}>
      <div className={s.metricLabel}>
        <span>{label}</span>
        <strong style={{ color }}>
          {formatPct(value)}
          {ci && <span className={s.ci}> ({formatPct(ci[0])}–{formatPct(ci[1])} 95% CI)</span>}
        </strong>
      </div>
      <div className={s.barTrack}><div className={s.barFill} style={{ width: `${(value || 0) * 100}%`, background: color }} /></div>
    </div>
  );
}

export default function BenchmarkPanel({ metrics }) {
  const exp = metrics?.experiment;
  const hasHoldout = !!exp?.holdout?.ai;
  const [which, setWhich] = useState('holdout');

  if (!exp?.ai) {
    return (
      <section className={s.card}>
        <h3 className={s.miniHeading}>BASELINE NEWS2 VS AI DETECTION</h3>
        <div className={s.empty}>NO BENCHMARK RESULTS YET. RUN <code>python experiment.py</code> IN THE BACKEND.</div>
      </section>
    );
  }

  const active = hasHoldout && which === 'holdout' ? exp.holdout : exp;
  const failures = active.llm_failures;
  const failureCount = Array.isArray(failures) ? failures.length : failures ?? 0;
  const positives = Object.entries(active.per_archetype || {});

  return (
    <section className={s.card}>
      <div className={s.cardHead}>
        <h3 className={s.miniHeading}>BASELINE NEWS2 VS AI DETECTION</h3>
        {hasHoldout && (
          <div className={s.chips}>
            <button className={`${s.chip} ${which === 'holdout' ? s.chipActive : ''}`} onClick={() => setWhich('holdout')}>HOLD-OUT</button>
            <button className={`${s.chip} ${which === 'dev' ? s.chipActive : ''}`} onClick={() => setWhich('dev')}>DEV SET</button>
          </div>
        )}
      </div>

      {coverageOf(active) < MIN_COVERAGE && (
        <div className={`${s.notice} ${s.noticeError}`} role="alert">
          Only {active.evaluated}/{active.total_patients} patients were evaluated (the rest hit LLM errors, e.g. rate limits).
          These figures come from a biased subset — treat them as unreliable and re-run <code>python experiment.py</code>.
        </div>
      )}

      <MetricBar label="NEWS2 DETECTION RATE" value={active.baseline.detection_rate} color="#888" ci={active.baseline.detection_rate_ci95} />
      <MetricBar label="AI DETECTION RATE" value={active.ai.detection_rate} color="var(--success)" ci={active.ai.detection_rate_ci95} />
      <MetricBar label="NEWS2 FALSE-ALERT RATE" value={active.baseline.false_alert_rate} color="#888" />
      <MetricBar label="AI FALSE-ALERT RATE" value={active.ai.false_alert_rate} color="var(--warning)" />

      <div className={s.callout}>
        <div>
          DETECTION IMPROVEMENT:{' '}
          <strong style={{ color: active.detection_rate_improvement >= 0 ? 'var(--success)' : 'var(--danger)' }}>
            {active.detection_rate_improvement >= 0 ? '+' : ''}{formatPct(active.detection_rate_improvement)}
          </strong>{' '}OVER BASELINE | F1: NEWS2 {formatPct(active.baseline.f1_score)} → AI {formatPct(active.ai.f1_score)}
        </div>
        <div className={s.subtle}>
          {active.evaluated ?? active.total_patients}/{active.total_patients} patients evaluated
          {failureCount > 0 && `, ${failureCount} LLM failures excluded`}.
          {active.ai_strict && ` Counting only High/Medium as a detection (Unknown excluded): ${formatPct(active.ai_strict.detection_rate)}.`}
          {which === 'dev' || !hasHoldout ? ' Dev-set patients are deterministic templates the agent was tuned against; prefer the hold-out figure.' : ''}
        </div>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead><tr><th>ARCHETYPE</th><th>TRUTH</th><th>NEWS2</th><th>AI</th></tr></thead>
          <tbody>
            {positives.map(([name, d]) => {
              const pos = d.ground_truth === 'positive';
              const key = pos ? 'detection_rate' : 'false_alert_rate';
              return (
                <tr key={name}>
                  <td>{name.replace(/_/g, ' ')}</td>
                  <td className={s.dim}>{pos ? 'at risk (detect)' : 'stable (no alert)'}</td>
                  <td>{formatPct(d.baseline[key])}</td>
                  <td>{formatPct(d.ai[key])}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
