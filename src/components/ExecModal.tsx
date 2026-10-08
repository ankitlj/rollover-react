import { useState, useMemo } from 'react';
import { useStore } from '../store';
import { RS } from '../data';

interface Props {
  alertId: string;
  onClose: () => void;
}

export default function ExecModal({ alertId, onClose }: Props) {
  const { alerts, resolvedStocks, sendInstruction, addToast, addNotification, expiryCur, expiryNext } = useStore();
  const a = alerts.find(x => x.id === alertId);
  const stock = a ? resolvedStocks.find(s => s.sym === a.sym) : null;
  const [lots, setLots] = useState(0);
  const [lotsError, setLotsError] = useState(false);

  const estSaving = a && stock ? ((a.spreadAtSignal || 0) - a.current) * lots * stock.lot : 0;

  const warnings = useMemo(() => {
    if (!a) return [];
    const w: string[] = [];
    if (Math.abs(a.current - (a.spreadAtSignal || 0)) > 0.5) w.push('Spread moved ' + Math.abs(a.current - (a.spreadAtSignal || 0)).toFixed(2) + ' since entry.');
    return w;
  }, [a]);

  if (!a || !stock) return null;

  const handleLotsChange = (val: string) => {
    const v = parseInt(val);
    setLots(v);
    if (isNaN(v) || v <= 0) setLotsError(true);
    else setLotsError(false);
  };

  const canSend = !lotsError && lots > 0;

  const handleSend = () => {
    if (!canSend) return;
    sendInstruction(alertId, lots);
    addNotification('success', 'Instruction Sent', lots + ' lots of ' + a.sym + ' sent to dealer');
    addToast('success', a.sym + ' instruction sent to dealer');
    onClose();
  };

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Send Instruction to Dealer</h3>
          <p>{a.sym} | Expiry: {expiryCur || '—'}</p>
        </div>
        <div className="modal-body">
          <div className="modal-grid">
            <div className="modal-field"><label>Stock</label><div className="val">{a.sym}</div></div>
            <div className="modal-field"><label>Sector</label><div className="val">{a.sector}</div></div>
            <div className="modal-field"><label>Current-Month Contract</label><div className="val">{expiryCur || '—'} FUT</div></div>
            <div className="modal-field"><label>Next-Month Contract</label><div className="val">{expiryNext || '—'} FUT</div></div>
            <div className="modal-field"><label>Lots Advices</label><div className="val">{a.lotsAvailable}</div></div>
            <div className="modal-field"><label>Lot Size</label><div className="val">{stock.lot}</div></div>
            <div className="modal-field"><label>Current Spread</label><div className="val">{a.current.toFixed(2)}</div></div>
            <div className="modal-field"><label>Spread at Entry</label><div className="val">{(a.spreadAtSignal || 0).toFixed(2)}</div></div>
            <div className="modal-field"><label>Discount %</label><div className="val">{a.discount.toFixed(1)}%</div></div>
            <div className="modal-field"><label>Estimated Saving</label><div className={`val ${estSaving >= 0 ? 'estimate-pos' : 'estimate-neg'}`}>{RS}{Math.abs(estSaving).toLocaleString('en-IN')}</div></div>
          </div>

          <div className="modal-divider" />

          <div className="modal-grid">
            <div className="modal-field">
              <label>Lots to Instruct</label>
              <input
                type="number"
                min={1}
                value={lots || ''}
                onChange={e => handleLotsChange(e.target.value)}
                className={lotsError ? 'error' : ''}
              />
            </div>
          </div>

          {warnings.map((w, i) => (
            <div key={i} className="modal-warning">&#9888; {w}</div>
          ))}
        </div>
        <div className="modal-footer">
          <button className="btn-modal-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-modal-send" disabled={!canSend} onClick={handleSend}>Send Instruction</button>
        </div>
      </div>
    </div>
  );
}
