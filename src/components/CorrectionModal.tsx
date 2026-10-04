import { useState } from 'react';
import { useStore } from '../store';

interface Props {
  entryId: string;
  onClose: () => void;
}

const FIELDS = [
  { value: 'lotsFilled', label: 'Lots Filled' },
  { value: 'lotsPartiallyFilled', label: 'Lots Partially Filled' },
  { value: 'lotsNotFilled', label: 'Lots Not Filled' },
  { value: 'avgFillPrice', label: 'Avg Fill Price' },
  { value: 'finalSpread', label: 'Final Spread' },
  { value: 'dealerRemarks', label: 'Dealer Remarks' },
];

export default function CorrectionModal({ entryId, onClose }: Props) {
  const { logEntries, saveCorrection, addToast, addNotification } = useStore();
  const e = logEntries.find(x => x.id === entryId);
  const [field, setField] = useState('lotsFilled');
  const [newVal, setNewVal] = useState('');
  const [reason, setReason] = useState('');

  if (!e) return null;

  const currentVal = (e as any)[field];

  const handleSave = () => {
    if (!newVal.trim()) { addToast('error', 'Enter a new value'); return; }
    if (!reason.trim()) { addToast('error', 'Enter a reason'); return; }

    saveCorrection(entryId, { field, newVal: newVal.trim(), reason: reason.trim() });
    addNotification('success', 'Correction Recorded', e.sym + ' record amended');
    addToast('success', 'Correction saved for ' + e.sym);
    onClose();
  };

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={ev => ev.stopPropagation()}>
        <div className="modal-header">
          <h3>Record Correction</h3>
          <p>{e.sym} | Amend a finalised record</p>
        </div>
        <div className="modal-body">
          <div className="modal-grid">
            <div className="modal-field"><label>Stock</label><div className="val">{e.sym}</div></div>
            <div className="modal-field"><label>Current Status</label><div className="val">{e.confirmStatus}</div></div>
            <div className="modal-field">
              <label>Field to Correct</label>
              <select value={field} onChange={ev => setField(ev.target.value)}>
                {FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
              </select>
            </div>
            <div className="modal-field"><label>Current Value</label><div className="val">{String(currentVal ?? '--')}</div></div>
            <div className="modal-field">
              <label>New Value</label>
              <input type="text" value={newVal} onChange={ev => setNewVal(ev.target.value)} />
            </div>
            <div className="modal-field full">
              <label>Reason for Correction</label>
              <textarea placeholder="Explain why this correction is needed..." value={reason} onChange={ev => setReason(ev.target.value)} />
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-modal-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-modal-submit" onClick={handleSave}>Save Correction</button>
        </div>
      </div>
    </div>
  );
}
