import { useState } from 'react';
import { useStore } from '../store';
import type { Correction } from '../types';

interface Props {
  entryId: string;
  onClose: () => void;
}

export default function UpdateModal({ entryId, onClose }: Props) {
  const { logEntries, saveEod, setStatus, addCorrectionBatch, addToast, addNotification } = useStore();
  const e = logEntries.find(x => x.id === entryId);
  const [filled, setFilled] = useState(e?.lotsFilled ?? 0);
  const [partial, setPartial] = useState(e?.lotsPartiallyFilled ?? 0);
  const [notFilled, setNotFilled] = useState(e?.lotsNotFilled ?? 0);
  const [fillPrice, setFillPrice] = useState(e?.avgFillPrice ?? 0);
  const [finalSpread, setFinalSpread] = useState(e?.finalSpread ?? 0);
  const [status, setStatus_] = useState(e?.confirmStatus ?? 'Confirmed');
  const [remarks, setRemarks] = useState(e?.dealerRemarks ?? '');

  if (!e) return null;

  const handleSave = () => {
    if (filled + partial + notFilled !== e.lotsInstructed) {
      addToast('error', 'Filled + Partial + Not Filled must equal ' + e.lotsInstructed);
      return;
    }
    if (filled < 0 || partial < 0 || notFilled < 0) {
      addToast('error', 'Values cannot be negative');
      return;
    }
    if (fillPrice < 0) {
      addToast('error', 'Fill price must be positive');
      return;
    }

    const now = new Date().toISOString();
    const changes: Correction[] = [];

    if (filled !== e.lotsFilled) {
      changes.push({ id: 'CORR-' + Date.now() + '-1', date: e.date, entryId: e.id, stock: e.sym, field: 'Lots Filled', oldValue: e.lotsFilled, newValue: filled, reason: '', timestamp: now });
    }
    if (partial !== e.lotsPartiallyFilled) {
      changes.push({ id: 'CORR-' + Date.now() + '-2', date: e.date, entryId: e.id, stock: e.sym, field: 'Lots Partially Filled', oldValue: e.lotsPartiallyFilled, newValue: partial, reason: '', timestamp: now });
    }
    if (notFilled !== e.lotsNotFilled) {
      changes.push({ id: 'CORR-' + Date.now() + '-3', date: e.date, entryId: e.id, stock: e.sym, field: 'Lots Not Filled', oldValue: e.lotsNotFilled, newValue: notFilled, reason: '', timestamp: now });
    }
    if (fillPrice !== e.avgFillPrice) {
      changes.push({ id: 'CORR-' + Date.now() + '-4', date: e.date, entryId: e.id, stock: e.sym, field: 'Avg Fill Price', oldValue: e.avgFillPrice, newValue: fillPrice, reason: '', timestamp: now });
    }
    if (finalSpread !== e.finalSpread) {
      changes.push({ id: 'CORR-' + Date.now() + '-5', date: e.date, entryId: e.id, stock: e.sym, field: 'Final Spread', oldValue: e.finalSpread, newValue: finalSpread, reason: '', timestamp: now });
    }
    if (status !== e.confirmStatus) {
      changes.push({ id: 'CORR-' + Date.now() + '-6', date: e.date, entryId: e.id, stock: e.sym, field: 'Status', oldValue: e.confirmStatus, newValue: status, reason: '', timestamp: now });
    }

    if (changes.length > 0) {
      addCorrectionBatch(changes);
    }

    saveEod(entryId, { filled, partial, notFilled, fillPrice, finalSpread, remarks });
    setStatus(entryId, status);
    addNotification('success', 'EOD Details Updated', e.sym + ' details amended');
    addToast('success', e.sym + ' details updated');
    onClose();
  };

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Update EOD Details</h3>
          <p>{e.sym} | {e.lotsInstructed} lots instructed</p>
        </div>
        <div className="modal-body">
          <div className="modal-grid">
            <div className="modal-field"><label>Stock</label><div className="val">{e.sym}</div></div>
            <div className="modal-field"><label>Lots Instructed</label><div className="val">{e.lotsInstructed}</div></div>
            <div className="modal-field">
              <label>Lots Fully Filled</label>
              <input type="number" min={0} max={e.lotsInstructed} value={filled} onChange={ev => setFilled(parseInt(ev.target.value) || 0)} />
            </div>
            <div className="modal-field">
              <label>Lots Partially Filled</label>
              <input type="number" min={0} max={e.lotsInstructed} value={partial} onChange={ev => setPartial(parseInt(ev.target.value) || 0)} />
            </div>
            <div className="modal-field">
              <label>Lots Not Filled</label>
              <input type="number" min={0} max={e.lotsInstructed} value={notFilled} onChange={ev => setNotFilled(parseInt(ev.target.value) || 0)} />
            </div>
            <div className="modal-field">
              <label>Avg Fill Price</label>
              <input type="number" min={0} step={0.05} value={fillPrice} onChange={ev => setFillPrice(parseFloat(ev.target.value) || 0)} />
            </div>
            <div className="modal-field">
              <label>Final Rollover Spread</label>
              <input type="number" min={0} step={0.01} value={finalSpread} onChange={ev => setFinalSpread(parseFloat(ev.target.value) || 0)} />
            </div>
            <div className="modal-field">
              <label>Status</label>
              <select value={status} onChange={ev => setStatus_(ev.target.value)}>
                <option value="Confirmed">Confirmed</option>
                <option value="Partially Confirmed">Partially Confirmed</option>
                <option value="Not Filled">Not Filled</option>
              </select>
            </div>
            <div className="modal-field full">
              <label>Dealer Remarks</label>
              <textarea placeholder="Enter dealer remarks..." value={remarks} onChange={ev => setRemarks(ev.target.value)} />
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-modal-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-modal-submit" onClick={handleSave}>Update Details</button>
        </div>
      </div>
    </div>
  );
}
