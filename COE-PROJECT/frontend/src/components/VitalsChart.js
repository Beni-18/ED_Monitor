'use client';

import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Legend } from 'recharts';
import s from './dashboard.module.css';

const UNITS = { heartRate: ' bpm', systolicBP: ' mmHg', spO2: ' %' };

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className={s.tooltip}>
      <div className={s.tooltipTime}>TIME: {label}</div>
      {payload.map((entry) => (
        <div key={entry.dataKey} className={s.tooltipRow} style={{ color: entry.color }}>
          <span>{entry.name}:</span>
          <strong>{entry.value !== null ? `${entry.value}${UNITS[entry.dataKey] || ''}` : 'N/A'}</strong>
        </div>
      ))}
    </div>
  );
}

export default function VitalsChart({ data }) {
  const tick = { fill: 'var(--text-secondary)', fontSize: 12, fontFamily: 'monospace' };
  return (
    <div className={s.chartBox}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 15, right: 20, left: 0, bottom: 5 }}>
          <XAxis dataKey="timestamp" stroke="var(--border-color)" tick={tick} />
          <YAxis domain={[0, 160]} stroke="var(--border-color)" tick={tick} width={36} />
          <Tooltip content={<ChartTooltip />} />
          <Legend wrapperStyle={{ paddingTop: '10px', fontFamily: 'monospace', fontSize: '0.8rem' }}
            formatter={(value) => <span style={{ color: '#ccc' }}>{value}</span>} />
          <ReferenceLine y={100} stroke="var(--warning)" strokeDasharray="3 3" />
          <ReferenceLine y={90} stroke="var(--danger)" strokeDasharray="3 3" />
          <Line type="monotone" dataKey="systolicBP" name="Systolic BP (mmHg)" stroke="#ffffff" strokeWidth={2} dot={{ r: 3, fill: '#ffffff' }} isAnimationActive={false} />
          <Line type="monotone" dataKey="heartRate" name="Heart Rate (bpm)" stroke="var(--danger)" strokeWidth={2} dot={{ r: 3, fill: 'var(--danger)' }} isAnimationActive={false} />
          <Line type="monotone" dataKey="spO2" name="SpO2 (%)" stroke="var(--success)" strokeWidth={2} dot={{ r: 3, fill: 'var(--success)' }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
