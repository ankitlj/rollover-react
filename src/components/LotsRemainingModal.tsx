import { useMemo } from 'react';
import { useStore } from '../store';
//import { RS } from '../data';

interface Props {
  selectedDate: string;
  onClose: () => void;
}

export default function LotsRemainingModal({ selectedDate, onClose }: Props) {
  const { resolvedStocks, logEntries } = useStore();

  const breakdown = useMemo(() => {
    return resolvedStocks.map(stock => {
      const cumFilled = logEntries
        .filter(e => e.date <= selectedDate && e.sym === stock.sym)
        .reduce((sum, e) => sum + e.lotsFilled, 0);
      const remaining = stock.lotsHeld - cumFilled;
      return {
        sym: stock.sym,
        sector: stock.sector,
        lotSize: stock.lot,
        lotsHeld: stock.lotsHeld,
        cumFilled,
        remaining: Math.max(0, remaining),
      };
    });
  }, [resolvedStocks, logEntries, selectedDate]);

  const totalHeld = breakdown.reduce((s, b) => s + b.lotsHeld, 0);
  const totalRolled = breakdown.reduce((s, b) => s + b.cumFilled, 0);
  const totalRemaining = breakdown.reduce((s, b) => s + b.remaining, 0);

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 700 }}>
        <div className="modal-header">
          <h3>Lots Remaining to Rollover</h3>
          <p>As on {new Date(selectedDate).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</p>
        </div>
        <div className="modal-body">
          <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
            <div style={{ flex: 1, background: 'var(--bg-tertiary)', borderRadius: 6, padding: '10px 14px' }}>
              <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 4 }}>TOTAL LOTS</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{totalHeld}</div>
            </div>
            <div style={{ flex: 1, background: 'var(--bg-tertiary)', borderRadius: 6, padding: '10px 14px' }}>
              <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 4 }}>ROLLED OVER</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--success)' }}>{totalRolled}</div>
            </div>
            <div style={{ flex: 1, background: 'var(--bg-tertiary)', borderRadius: 6, padding: '10px 14px' }}>
              <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 4 }}>REMAINING</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: totalRemaining > 0 ? 'var(--warning)' : 'var(--success)' }}>{totalRemaining}</div>
            </div>
          </div>

          <div className="table-wrap" style={{ maxHeight: 350, overflowY: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Stock</th>
                  <th>Sector</th>
                  <th>Lot Size</th>
                  <th>Lots Held</th>
                  <th>Rolled Over</th>
                  <th>Remaining</th>
                </tr>
              </thead>
              <tbody>
                {breakdown.map(b => (
                  <tr key={b.sym} className="row-enter">
                    <td><span className="live-dot" /><span className="stock-name">{b.sym}</span></td>
                    <td>{b.sector}</td>
                    <td>{b.lotSize.toLocaleString('en-IN')}</td>
                    <td>{b.lotsHeld}</td>
                    <td style={{ color: b.cumFilled > 0 ? 'var(--success)' : 'var(--text-tertiary)' }}>
                      {b.cumFilled > 0 ? b.cumFilled : '--'}
                    </td>
                    <td style={{ color: b.remaining > 0 ? 'var(--warning)' : 'var(--success)', fontWeight: 600 }}>
                      {b.remaining}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-modal-cancel" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
