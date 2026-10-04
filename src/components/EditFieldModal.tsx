import { useState } from 'react';
import { useStore } from '../store';

interface Props {
  entryId: string;
  field: 'lotsFilled' | 'avgFillPrice' | 'finalSpread';
  label: string;
  onClose: () => void;
}

export default function EditFieldModal({ entryId, field, label, onClose }: Props) {
  const { logEntries, updateLogField, addToast } = useStore();
  const entry = logEntries.find(e => e.id === entryId);
  const [value, setValue] = useState(entry ? String(entry[field] || '') : '');

  if (!entry) return null;

  const handleSave = () => {
    const num = parseFloat(value);
    if (isNaN(num) || num < 0) return;
    updateLogField(entryId, field, num);
    addToast('success', label + ' updated', entry.sym);
    onClose();
  };

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 400 }}>
        <div className="modal-header">
          <h3>{label}</h3>
          <p>{entry.sym} | {entry.expiry}</p>
        </div>
        <div className="modal-body">
          <input
            type="number"
            step="any"
            min="0"
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder={'Enter ' + label.toLowerCase() + '...'}
            style={{
              width: '100%',
              padding: '10px 12px',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 14,
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
