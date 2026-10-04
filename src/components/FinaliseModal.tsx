import { useState, useEffect } from 'react';
import { useStore } from '../store';
import { RS } from '../data';

interface Props {
  date: string;
  page: 'log' | 'recon';
  onClose: () => void;
}

export default function FinaliseModal({ date, onClose }: Props) {
  const { logEntries, finalisedDays, finaliseDay, addToast, addNotification } = useStore();
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    if (finalisedDays[date]) {
      addToast('warning', 'Day already finalised');
      onClose();
    }
  }, [finalisedDays, date, addToast, onClose]);

  if (finalisedDays[date]) return null;

  const entries = logEntries.filter(e => e.date === date);
  const pending = entries.filter(e => e.confirmStatus === 'Awaiting EOD Update');
  const totalInstructed = entries.reduce((s, e) => s + e.lotsInstructed, 0);
  const totalFilled = entries.reduce((s, e) => s + e.lotsFilled, 0);
  const saving = entries.reduce((s, e) => s + e.confirmedSaving, 0);

  const handleConfirm = () => {
    finaliseDay(date);
    addNotification('success', 'Day Finalised', date + ' locked. Corrections available if needed.');
    addToast('success', 'Day ' + date + ' finalised');
    onClose();
  };

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Finalise Trading Day</h3>
          <p>Lock all records for {date}</p>
        </div>
        <div className="modal-body">
          <div className="modal-grid">
            <div className="modal-field"><label>Date</label><div className="val">{date}</div></div>
            <div className="modal-field"><label>Total Entries</label><div className="val">{entries.length}</div></div>
            <div className="modal-field"><label>Lots Instructed</label><div className="val">{totalInstructed}</div></div>
            <div className="modal-field"><label>Lots Filled</label><div className="val">{totalFilled}</div></div>
            <div className="modal-field"><label>Confirmed Saving</label><div className="val">{RS}{saving.toLocaleString('en-IN')}</div></div>
            <div className="modal-field"><label>Pending EOD</label><div className="val" style={{ color: pending.length > 0 ? 'var(--warning)' : 'var(--success)' }}>{pending.length}</div></div>
          </div>

          <div className="modal-warning">&#9888; Once finalised, edits require a correction entry.</div>

          <label className="modal-checkbox">
            <input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
            I confirm all EOD details are correct.
          </label>
        </div>
        <div className="modal-footer">
          <button className="btn-modal-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-modal-submit" disabled={!confirmed} onClick={handleConfirm}>Finalise Trading Day</button>
        </div>
      </div>
    </div>
  );
}
