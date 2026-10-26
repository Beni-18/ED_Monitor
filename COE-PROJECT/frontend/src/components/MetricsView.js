'use client';

import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import s from './dashboard.module.css';
import BenchmarkPanel from './BenchmarkPanel';

const tick = { fill: '#ccc', fontSize: 12, fontFamily: 'monospace' };
const tooltipStyle = { background: '#000', border: '1px solid #333', fontFamily: 'monospace' };

function Stat({ label, value, unit, color }) {
  return (
    <div className={s.bigStat}>
      <div className={s.subtle}>{label}</div>
      <div className={s.bigStatValue} style={{ color }}>{value}{unit && <span> {unit}</span>}</div>
    </div>
  );
}

export default function MetricsView({ patients, metrics, performance }) {
  const distribution = [
    { name: 'High', count: patients.filter((p) => p.risk_level === 'High').length, fill: '#ff4d4d' },
    { name: 'Medium', count: patients.filter((p) => p.risk_level === 'Medium').length, fill: '#ffaa00' },
    { name: 'Low', count: patients.filter((p) => p.risk_level === 'Low').length, fill: '#00cc66' },
    { name: 'Unknown', count: patients.filter((p) => p.risk_level === 'Unknown').length, fill: '#cc8800' },
    { name: 'Unassessed', count: patients.filter((p) => !p.risk_level).length, fill: '#666666' },
  ];
  const nodeTimings = Object.entries(performance?.avg_node_timings || {})
    .map(([name, ms]) => ({ name: name.replace(/_/g, ' '), ms }));

  return (
    <div className={s.stack}>
      <h2 className={s.sectionTitle}>SYSTEM ANALYTICS & AI PERFORMANCE</h2>

      <div className={s.twoCol}>
        <section className={s.card}>
          <h3 className={s.miniHeading}>PATIENT POPULATION RISK DISTRIBUTION</h3>
          <div className={s.chartBoxSm}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={distribution}>
                <XAxis dataKey="name" stroke="var(--border-color)" tick={tick} />
                <YAxis stroke="var(--border-color)" tick={tick} allowDecimals={false} width={36} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="count" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
        <BenchmarkPanel metrics={metrics} />
      </div>

      {performance?.total_evaluations > 0 && (
        <div className={s.twoCol}>
          <section className={s.card}>
            <h3 className={s.miniHeading}>LANGGRAPH PIPELINE LATENCY (AVG PER NODE)</h3>
            <div className={s.chartBoxSm}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={nodeTimings} layout="vertical" margin={{ left: 10 }}>
                  <XAxis type="number" stroke="var(--border-color)" tick={tick} />
                  <YAxis dataKey="name" type="category" width={130} stroke="var(--border-color)" tick={{ ...tick, fontSize: 10 }} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(value) => [`${value} ms`, 'Latency']} />
                  <Bar dataKey="ms" fill="var(--text-primary)" barSize={18} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
          <div className={s.statGrid}>
            <Stat label="AVG EVAL LATENCY" value={performance.avg_total_latency_ms} unit="ms" />
            <Stat label="P95 EVAL LATENCY" value={performance.p95_latency_ms} unit="ms" color="var(--warning)" />
            <Stat label="LLM SUCCESS RATE" value={`${(performance.groq_success_rate * 100).toFixed(1)}%`} color="var(--success)" />
            <Stat label="AVG TOKENS / EVAL" value={performance.avg_tokens_used} />
          </div>
        </div>
      )}
    </div>
  );
}
