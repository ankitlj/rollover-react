import { useState } from 'react';
import { useStore } from '../store';

interface Props {
  entryId: string;
  onClose: () => void;
}

const STATUS_OPTIONS = [
  { value: 'Confirmed', label: 'Confirmed', cls: 'badge-executed' },
  { value: 'Partially Confirmed', label: 'Partially Confirmed', cls: 'badge-partial' },
  { value: 'Not Confirmed', label: 'Not Confirmed', cls: 'badge-rejected' },
];

export default function StatusModal({ entryId, onClose }: Props) {
  const { logEntries, setStatus, addToast } = useStore();
  const entry = logEntries.find(e => e.id === entryId);
  const [selected, setSelected] = useState(entry?.confirmStatus || '');

  if (!entry) return null;

  const handleConfirm = () => {
    if (!selected) return;
    setStatus(entryId, selected);
    addToast('success', 'Status updated', entry.sym + ' → ' + selected);
    onClose();
  };

  return (
    <div className="modal-overlay open" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <div className="modal-header">
          <h3>Set Status</h3>
          <p>{entry.sym} | {entry.expiry}</p>
        </div>
        <div className="modal-body">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {STATUS_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setSelected(opt.value)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '12px 16px',
                  background: selected === opt.value ? 'var(--accent-blue-dim)' : 'var(--bg-tertiary)',
                  border: selected === opt.value ? '1px solid var(--accent-blue)' : '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{opt.label}</span>
                <span className={`badge ${opt.cls}`}>{opt.value}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-modal-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-modal-submit" onClick={handleConfirm} disabled={!selected}>Confirm</button>
        </div>
      </div>
    </div>
  );
}
