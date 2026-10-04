import { useState, useMemo } from 'react';
import { useStore } from '../store';
import { RS } from '../data';
import StatusModal from './StatusModal';
import RemarksModal from './RemarksModal';
import EditFieldModal from './EditFieldModal';

export default function LogPage() {
  const { logEntries, finaliseEntry, addToast } = useStore();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [statusEntryId, setStatusEntryId] = useState<string | null>(null);
  const [remarksEntryId, setRemarksEntryId] = useState<string | null>(null);
  const [editField, setEditField] = useState<{ entryId: string; field: 'lotsFilled' | 'avgFillPrice' | 'finalSpread'; label: string } | null>(null);

  const entries = useMemo(() => logEntries.filter(e => !e.finalised), [logEntries]);
  const filtered = useMemo(() => entries.filter(e => {
    if (search && !e.sym.toLowerCase().includes(search.toLowerCase())) return false;
    if (statusFilter !== 'all' && e.confirmStatus !== statusFilter) return false;
    return true;
  }), [entries, search, statusFilter]);

  const totalInstructed = entries.reduce((s, e) => s + e.lotsInstructed, 0);
  const totalFilled = entries.reduce((s, e) => s + e.lotsFilled, 0);
  const dailySaving = entries.reduce((s, e) => s + e.confirmedSaving, 0);

  const handleFinalise = (entryId: string) => {
    finaliseEntry(entryId);
    const entry = logEntries.find(e => e.id === entryId);
    addToast('success', 'Entry finalised', entry?.sym + ' moved to Reconciliation');
  };

  const openEdit = (entryId: string, field: 'lotsFilled' | 'avgFillPrice' | 'finalSpread', label: string) => {
    setEditField({ entryId, field, label });
  };

  const exportCSV = () => {
    const headers = ['Stock', 'Expiry', 'Instructed', 'Filled', 'Avg Fill Price', 'Final Spread', 'Remarks', 'Status'];
    const rows = entries.map(e => [e.sym, e.expiry, e.lotsInstructed, e.lotsFilled, e.avgFillPrice, e.finalSpread, e.dealerRemarks, e.confirmStatus]);
    let csv = headers.join(',') + '\n' + rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = 'rollover_log.csv'; link.click();
  };

  const cellStyle = (hasValue: boolean) => ({
    cursor: 'pointer',
    color: hasValue ? 'var(--text-primary)' : 'var(--text-tertiary)',
    borderBottom: hasValue ? '1px dashed var(--border-subtle)' : '1px dashed var(--border-subtle)',
  });

  return (
    <div>
      <div className="toolbar">
        <div className="toolbar-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" /></svg>
          <input type="text" placeholder="Search stock..." value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <select className="toolbar-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="all">All Status</option>
          <option value="Awaiting EOD Update">Awaiting EOD</option>
          <option value="Confirmed">Confirmed</option>
          <option value="Partially Confirmed">Partially Confirmed</option>
          <option value="Not Confirmed">Not Confirmed</option>
        </select>
      </div>

      <div className="section-label">
        <span>Daily Instruction & Confirmation Log</span>
        <span className="label-badge">{entries.length} ENTRIES</span>
        <span className="label-line" />
      </div>

      <div className="table-card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stock</th>
                <th>Expiry</th>
                <th>Lots Instructed</th>
                <th>Filled</th>
                <th>Avg Fill Price</th>
                <th>Final Spread</th>
                <th>Dealer Remarks</th>
                <th>Status</th>
                <th>Last Updated</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length > 0 ? filtered.map(e => {
                const sb = e.confirmStatus === 'Confirmed' ? 'badge-executed' :
                  e.confirmStatus === 'Partially Confirmed' ? 'badge-partial' :
                  e.confirmStatus === 'Not Confirmed' ? 'badge-rejected' :
                  e.confirmStatus === 'Exception' ? 'badge-mismatch' : 'badge-pending';
                const rowClass = e.confirmStatus === 'Awaiting EOD Update' ? 'urgent' : '';
                return (
                  <tr key={e.id} className={`row-enter ${rowClass}`}>
                    <td>
                      {e.confirmStatus === 'Awaiting EOD Update' && <span className="live-dot warning" />}
                      <span className="stock-name">{e.sym}</span>
                      <div className="stock-meta">{e.sector}</div>
                    </td>
                    <td>{e.expiry}</td>
                    <td>{e.lotsInstructed}</td>
                    <td>
                      <span
                        onClick={() => openEdit(e.id, 'lotsFilled', 'Filled')}
                        style={cellStyle(e.lotsFilled > 0)}
                        title="Click to edit"
                      >
                        {e.lotsFilled > 0 ? e.lotsFilled : 'Click to add'}
                      </span>
                    </td>
                    <td>
                      <span
                        onClick={() => openEdit(e.id, 'avgFillPrice', 'Avg Fill Price')}
                        style={cellStyle(e.avgFillPrice > 0)}
                        title="Click to edit"
                      >
                        {e.avgFillPrice > 0 ? RS + e.avgFillPrice.toLocaleString('en-IN') : 'Click to add'}
                      </span>
                    </td>
                    <td>
                      <span
                        onClick={() => openEdit(e.id, 'finalSpread', 'Final Spread')}
                        style={cellStyle(e.finalSpread > 0)}
                        title="Click to edit"
                      >
                        {e.finalSpread > 0 ? e.finalSpread.toFixed(2) : 'Click to add'}
                      </span>
                    </td>
                    <td>
                      <span
                        onClick={() => setRemarksEntryId(e.id)}
                        style={{
                          maxWidth: 120,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          display: 'block',
                          cursor: 'pointer',
                          color: e.dealerRemarks ? 'var(--text-primary)' : 'var(--text-tertiary)',
                          borderBottom: '1px dashed var(--border-subtle)',
                        }}
                        title={e.dealerRemarks || 'Click to add remarks'}
                      >
                        {e.dealerRemarks || 'Click to add'}
                      </span>
                    </td>
                    <td>
                      <span
                        onClick={() => setStatusEntryId(e.id)}
                        className={`badge ${sb}`}
                        style={{ cursor: 'pointer' }}
                        title="Click to change status"
                      >
                        {e.confirmStatus}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{e.lastUpdated.toLocaleTimeString()}</span>
                        <button
                          className="btn-execute"
                          onClick={() => handleFinalise(e.id)}
                          style={{ fontSize: 9, padding: '3px 8px' }}
                        >
                          FINALISE
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              }) : (
                <tr><td colSpan={9} style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: 20 }}>No entries in log</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="download-bar">
          <div className="footer-stats">
            Instructed: <b>{totalInstructed}</b> | Filled: <b style={{ color: 'var(--success)' }}>{totalFilled}</b> | Daily Saving: <b style={{ color: 'var(--success)' }}>{RS}{dailySaving.toLocaleString('en-IN')}</b>
          </div>
          <div className="download-btns">
            <button className="btn-download" onClick={exportCSV}>CSV</button>
            <button className="btn-download" onClick={exportCSV}>Excel</button>
          </div>
        </div>
      </div>

      {statusEntryId && <StatusModal entryId={statusEntryId} onClose={() => setStatusEntryId(null)} />}
      {remarksEntryId && <RemarksModal entryId={remarksEntryId} onClose={() => setRemarksEntryId(null)} />}
      {editField && <EditFieldModal entryId={editField.entryId} field={editField.field} label={editField.label} onClose={() => setEditField(null)} />}
    </div>
  );
}
