import { useMemo } from 'react';
import { useStore } from '../store';

export default function HealthStrip() {
  const { alerts, currentMonth, nextMonth } = useStore();

  const feedAge = useMemo(() => {
    if (alerts.length === 0) return -1;
    const latest = Math.max(...alerts.map(a => a.lastUpdated.getTime()));
    return Math.floor((Date.now() - latest) / 1000);
  }, [alerts]);

  const feedColor = feedAge < 0 ? 'var(--text-tertiary)' : feedAge < 15 ? 'var(--success)' : feedAge < 30 ? 'var(--warning)' : 'var(--danger)';
  const feedLabel = feedAge < 0 ? 'No data' : feedAge + 's ago';

  const curOk = currentMonth && currentMonth.length > 0;
  const nextOk = nextMonth && nextMonth.length > 0;
  const syncColor = curOk && nextOk ? 'var(--success)' : 'var(--warning)';

  return (
    <div className="health-strip">
      <div className="health-item">
        <span className="health-dot" style={{ background: feedColor }} />
        <span className="health-label" style={{ color: feedColor }}>{feedLabel}</span>
      </div>
      <div className="health-item">
        <span className="health-dot" style={{ background: syncColor }} />
        <span className="health-label" style={{ color: 'var(--text-secondary)' }}>
          {currentMonth} {curOk ? '✓' : '✗'} | {nextMonth} {nextOk ? '✓' : '✗'}
        </span>
      </div>
    </div>
  );
}
