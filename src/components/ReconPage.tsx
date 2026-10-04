import { useState, useMemo } from 'react';
import { useStore } from '../store';
import { RS } from '../data';
import EodModal from './EodModal';
import CorrectionModal from './CorrectionModal';
import FinaliseModal from './FinaliseModal';
import UpdateModal from './UpdateModal';
import LotsRemainingModal from './LotsRemainingModal';

export default function ReconPage() {
  const { logEntries, corrections, finalisedDays, resolvedStocks } = useStore();
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [eodEntryId, setEodEntryId] = useState<string | null>(null);
  const [correctionEntryId, setCorrectionEntryId] = useState<string | null>(null);
  const [updateEntryId, setUpdateEntryId] = useState<string | null>(null);
  const [showFinalise, setShowFinalise] = useState(false);
  const [showLotsRemaining, setShowLotsRemaining] = useState(false);

  const isFinalised = !!finalisedDays[date];
  const entries = useMemo(() => logEntries.filter(e => e.finalised && e.date === date), [logEntries, date]);

  const totalInstructions = entries.length;
  const totalInstructed = entries.reduce((s, e) => s + e.lotsInstructed, 0);
  const totalFilled = entries.reduce((s, e) => s + e.lotsFilled, 0);
  const totalPartial = entries.reduce((s, e) => s + e.lotsPartiallyFilled, 0);
  const totalNotFilled = entries.reduce((s, e) => s + e.lotsNotFilled, 0);
  const confirmedSaving = entries.reduce((s, e) => s + e.confirmedSaving, 0);
  const completionPct = totalInstructed > 0 ? (totalFilled / totalInstructed * 100).toFixed(1) : '0.0';

  const selectedDate = new Date(date);
  const monthStart = date.substring(0, 7) + '-01';
  const fyStart = selectedDate.getMonth() >= 3
    ? selectedDate.getFullYear() + '-04-01'
    : (selectedDate.getFullYear() - 1) + '-04-01';

  const mtdSaving = useMemo(() =>
    logEntries.filter(e => e.date >= monthStart && e.date <= date).reduce((s, e) => s + e.confirmedSaving, 0),
    [logEntries, monthStart, date]
  );

  const fySaving = useMemo(() =>
    logEntries.filter(e => e.date >= fyStart && e.date <= date).reduce((s, e) => s + e.confirmedSaving, 0),
    [logEntries, fyStart, date]
  );

  const totalLotsHeld = resolvedStocks.reduce((s, r) => s + r.lotsHeld, 0);
  const totalLotsRolled = useMemo(() =>
    logEntries.filter(e => e.date <= date).reduce((s, e) => s + e.lotsFilled, 0),
    [logEntries, date]
  );
  const lotsRemaining = totalLotsHeld - totalLotsRolled;

  const summaryCards = [
    { label: 'Total Instructions', value: String(totalInstructions), sub: 'entries' },
    { label: 'Lots Instructed', value: String(totalInstructed), sub: 'lots' },
    { label: 'Lots Filled', value: String(totalFilled), sub: 'confirmed', cls: 'positive' },
    { label: 'Partially Filled', value: String(totalPartial), sub: 'lots', cls: totalPartial > 0 ? 'warning' : '' },
    { label: 'Not Filled', value: String(totalNotFilled), sub: 'lots', cls: totalNotFilled > 0 ? 'negative' : '' },
    { label: 'Completion', value: completionPct + '%', sub: 'filled/instructed' },
    { label: 'Daily Saving', value: RS + confirmedSaving.toLocaleString('en-IN'), sub: 'on filled lots', cls: 'positive' },
    { label: 'Monthly Saving', value: RS + mtdSaving.toLocaleString('en-IN'), sub: 'as on date', cls: 'positive' },
    { label: 'FY Saving', value: RS + fySaving.toLocaleString('en-IN'), sub: 'as on date', cls: 'positive' },
  ];

  const dayCorrections = corrections.filter(c => c.date === date);
  const pendingCount = entries.filter(e => e.confirmStatus === 'Awaiting EOD Update').length;

  return (
    <div>
      <div className="toolbar">
        <input type="date" className="toolbar-select" value={date} onChange={e => setDate(e.target.value)} />
        {isFinalised && <span style={{ color: 'var(--success)', fontSize: 10, fontWeight: 700, background: 'var(--success-dim)', padding: '3px 8px', borderRadius: 4 }}>LOCKED</span>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button className="btn-sm">Save Draft</button>
          <button className="btn-execute" style={{ fontSize: 10, padding: '5px 12px' }} onClick={() => setShowFinalise(true)}>Finalise Day</button>
        </div>
      </div>

      <div className="dash-grid" id="reconSummaryCards">
        {summaryCards.map(c => (
          <div key={c.label} className="dash-card">
            <div className="dc-label">{c.label}</div>
            <div className={`dc-value ${c.cls || ''}`}>{c.value}</div>
            <div className="dc-sub">{c.sub}</div>
          </div>
        ))}
        <div className="dash-card" style={{ cursor: 'pointer' }} onClick={() => setShowLotsRemaining(true)}>
          <div className="dc-label">Lots Remaining</div>
          <div className={`dc-value ${lotsRemaining > 0 ? 'warning' : 'positive'}`}>{lotsRemaining}/{totalLotsHeld}</div>
          <div className="dc-sub">{totalLotsRolled} rolled over</div>
        </div>
      </div>

      <div className="section-label">
        <span>End-of-Day Execution Details</span>
        <span className="label-badge">{pendingCount} PENDING</span>
        <span className="label-line" />
      </div>

      <div className="table-card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stock</th>
                <th>LOTS INSTRUCTED</th>
                <th>FILLED</th>
                <th>Avg Fill Price</th>
                <th>Final Spread</th>
                <th>Confirmed Saving</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {entries.length > 0 ? entries.map(e => {
                const sb = e.confirmStatus === 'Confirmed' ? 'badge-executed' :
                  e.confirmStatus === 'Partially Confirmed' ? 'badge-partial' :
                  e.confirmStatus === 'Not Filled' ? 'badge-rejected' : 'badge-pending';
                return (
                  <tr key={e.id} className="row-enter">
                    <td><span className="live-dot" /><span className="stock-name">{e.sym}</span></td>
                    <td>{e.lotsInstructed}</td>
                    <td>{e.lotsFilled > 0 ? e.lotsFilled : <span style={{ color: 'var(--text-tertiary)' }}>--</span>}</td>
                    <td>{e.avgFillPrice > 0 ? RS + e.avgFillPrice.toLocaleString('en-IN') : <span style={{ color: 'var(--text-tertiary)' }}>--</span>}</td>
                    <td>{e.finalSpread > 0 ? e.finalSpread.toFixed(2) : <span style={{ color: 'var(--text-tertiary)' }}>--</span>}</td>
                    <td>{e.confirmedSaving > 0 ? <span style={{ color: 'var(--success)' }}>{RS}{e.confirmedSaving.toLocaleString('en-IN')}</span> : <span style={{ color: 'var(--text-tertiary)' }}>--</span>}</td>
                    <td><span className={`badge ${sb}`}>{e.confirmStatus}</span></td>
                    <td>
                      {!isFinalised && e.confirmStatus === 'Awaiting EOD Update' && (
                        <button className="btn-sm" onClick={() => setEodEntryId(e.id)}>Enter EOD</button>
                      )}
                      {isFinalised && (
                        <button className="btn-sm" onClick={() => setCorrectionEntryId(e.id)}>Correct</button>
                      )}
                      {!isFinalised && e.confirmStatus !== 'Awaiting EOD Update' && (
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <span style={{ color: 'var(--text-tertiary)', fontSize: 10 }}>Done</span>
                          <button className="btn-execute" style={{ fontSize: 10, padding: '5px 12px' }} onClick={() => setUpdateEntryId(e.id)}>Update</button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              }) : (
                <tr><td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: 20 }}>No entries for this date</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="download-bar">
          <span className="footer-stats">
            Entries: <b>{entries.length}</b> | Confirmed: <b style={{ color: 'var(--success)' }}>{entries.filter(e => e.confirmStatus === 'Confirmed').length}</b> | Awaiting: <b>{pendingCount}</b>
          </span>
        </div>
      </div>

      <div className="section-label" style={{ marginTop: 20 }}>
        <span>Correction History</span>
        <span className="label-badge">{dayCorrections.length} CORRECTIONS</span>
        <span className="label-line" />
      </div>
      <div className="table-card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Stock</th>
                <th>Field</th>
                <th>Old Value</th>
                <th>New Value</th>
              </tr>
            </thead>
            <tbody>
              {dayCorrections.length > 0 ? dayCorrections.map(c => (
                <tr key={c.id} className="row-enter">
                  <td style={{ fontSize: 10 }}>{new Date(c.timestamp).toLocaleString()}</td>
                  <td>{c.stock}</td>
                  <td>{c.field}</td>
                  <td>{String(c.oldValue)}</td>
                  <td>{String(c.newValue)}</td>
                </tr>
              )) : (
                <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: 20 }}>No corrections recorded</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {eodEntryId && <EodModal entryId={eodEntryId} onClose={() => setEodEntryId(null)} />}
      {correctionEntryId && <CorrectionModal entryId={correctionEntryId} onClose={() => setCorrectionEntryId(null)} />}
      {updateEntryId && <UpdateModal entryId={updateEntryId} onClose={() => setUpdateEntryId(null)} />}
      {showFinalise && <FinaliseModal date={date} page="recon" onClose={() => setShowFinalise(false)} />}
      {showLotsRemaining && <LotsRemainingModal selectedDate={date} onClose={() => setShowLotsRemaining(false)} />}
    </div>
  );
}
