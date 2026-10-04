import { useState } from 'react';
import { useStore } from '../store';

interface Props {
  entryId: string;
  onClose: () => void;
}

export default function RemarksModal({ entryId, onClose }: Props) {
  const { logEntries, updateDealerRemarks, addToast } = useStore();
  const entry = logEntries.find(e => e.id === entryId);
  const [value, setValue] = useState(entry?.dealerRemarks || '');

  if (!entry) return null;

  const handleSave = () => {
    updateDealerRemarks(entryId, value);
    addToast('success', 'Remarks updated', entry.sym);
    onClose();
  };

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 440 }}>
        <div className="modal-header">
          <h3>Dealer Remarks</h3>
          <p>{entry.sym} | {entry.expiry}</p>
        </div>
        <div className="modal-body">
          <textarea
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder="Enter dealer remarks..."
            style={{
              width: '100%',
              minHeight: 80,
              padding: '10px 12px',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              resize: 'vertical',
              outline: 'none',
            }}
            autoFocus
          />
        </div>
        <div className="modal-footer">
          <button className="btn-modal-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-modal-submit" onClick={handleSave}>Save</button>
        </div>
      </div>
    </div>
  );
}
