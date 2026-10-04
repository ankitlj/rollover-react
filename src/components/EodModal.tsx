import { useState } from 'react';
import { useStore } from '../store';

interface Props {
  entryId: string;
  onClose: () => void;
}

export default function EodModal({ entryId, onClose }: Props) {
  const { logEntries, saveEod, addToast, addNotification } = useStore();
  const e = logEntries.find(x => x.id === entryId);
  const [filled, setFilled] = useState(0);
  const [partial, setPartial] = useState(0);
  const [notFilled, setNotFilled] = useState(0);
  const [fillPrice, setFillPrice] = useState(0);
  const [finalSpread, setFinalSpread] = useState(0);
  const [remarks, setRemarks] = useState('');

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
    saveEod(entryId, { filled, partial, notFilled, fillPrice, finalSpread, remarks });
    addNotification('success', 'EOD Details Saved', e.sym + ' fill details recorded');
    addToast('success', e.sym + ' EOD details saved');
    onClose();
  };

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Enter EOD Fill Details</h3>
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
            <div className="modal-field full">
              <label>Dealer Remarks</label>
              <textarea placeholder="Enter dealer remarks..." value={remarks} onChange={ev => setRemarks(ev.target.value)} />
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-modal-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-modal-submit" onClick={handleSave}>Save EOD Details</button>
        </div>
      </div>
    </div>
  );
}
