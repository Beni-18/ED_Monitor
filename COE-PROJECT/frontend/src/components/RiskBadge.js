import { riskBadgeClass } from '../lib/risk';

export default function RiskBadge({ level, suffix = '', className = '' }) {
  return (
    <span className={`badge ${riskBadgeClass(level)} ${className}`}>
      {level ? `${level.toUpperCase()}${suffix}` : 'UNASSESSED'}
    </span>
  );
}
