import { useState } from 'react';
import { useStore } from '../store';

const SETTING_GROUPS = [
  {
    title: 'Savings Calculation',
    settings: [
      { key: 'tradingDays', label: 'Trading Days / Month', type: 'number' as const },
      { key: 'fyMonths', label: 'Months in FY', type: 'number' as const },
    ],
  },
  {
    title: 'System',
    settings: [
      { key: 'refreshInterval', label: 'Refresh Interval (sec)', type: 'number' as const },
      { key: 'demoLabel', label: 'Show Demo Label', type: 'select' as const, options: ['yes', 'no'] },
    ],
  },
];

export default function SettingsPage() {
  const { settings, resolvedStocks, updateSettings, resetSettings, updateStock, addToast, addNotification } = useStore();
  const [editLot, setEditLot] = useState<Record<string, string>>({});
  const [editHeld, setEditHeld] = useState<Record<string, string>>({});

  const handleSave = () => {
    addToast('success', 'Settings saved');
    addNotification('success', 'Settings Updated', 'Configuration saved successfully');
  };

  const handleReset = () => {
    resetSettings();
    addToast('warning', 'Settings reset to defaults');
  };

  const handleLotBlur = (sym: string, currentLot: number) => {
    const val = editLot[sym];
    if (val !== undefined && val !== '') {
      const num = parseInt(val);
      if (!isNaN(num) && num > 0 && num !== currentLot) {
        updateStock(sym, 'lot', num);
      }
    }
    setEditLot(prev => { const n = { ...prev }; delete n[sym]; return n; });
  };

  const handleHeldBlur = (sym: string, currentHeld: number) => {
    const val = editHeld[sym];
    if (val !== undefined && val !== '') {
      const num = parseInt(val);
      if (!isNaN(num) && num >= 0 && num !== currentHeld) {
        updateStock(sym, 'lotsHeld', num);
      }
    }
    setEditHeld(prev => { const n = { ...prev }; delete n[sym]; return n; });
  };

  const totalLots = resolvedStocks.reduce((s, r) => s + r.lotsHeld, 0);

  return (
    <div>
      <div className="section-label">
        <span>System Settings</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
          <button className="btn-sm" onClick={handleReset}>Reset Defaults</button>
          <button className="btn-execute" onClick={handleSave}>Save Settings</button>
        </div>
        <span className="label-line" />
      </div>

      <div className="settings-grid">
        {SETTING_GROUPS.map(g => (
          <div key={g.title} className="settings-group">
            <h4>{g.title}</h4>
            {g.settings.map(s => (
              <div key={s.key} className="setting-row">
                <span className="sr-label">{s.label}</span>
                {s.type === 'select' ? (
                  <select
                    className="sr-input"
                    value={String(settings[s.key as keyof typeof settings])}
                    onChange={e => updateSettings(s.key, e.target.value)}
                  >
                    {s.options!.map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input
                    className="sr-input"
                    type="number"
                    value={Number(settings[s.key as keyof typeof settings])}
                    onChange={e => updateSettings(s.key, parseFloat(e.target.value))}
                  />
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="section-label" style={{ marginTop: 24 }}>
        <span>Stock Management</span>
        <span className="label-badge">{resolvedStocks.length} STOCKS | {totalLots} TOTAL LOTS</span>
        <span className="label-line" />
      </div>

      <div className="table-card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stock</th>
                <th>Sector</th>
                <th>Lot Size</th>
                <th>Lots Held</th>
                <th>Capital ({String.fromCharCode(8377)})</th>
              </tr>
            </thead>
            <tbody>
              {resolvedStocks.map(r => (
                <tr key={r.sym} className="row-enter">
                  <td><span className="live-dot" /><span className="stock-name">{r.sym}</span></td>
                  <td>{r.sector}</td>
                  <td>
                    <input
                      className="sr-input"
                      style={{ width: 80, textAlign: 'right' }}
                      type="number"
                      value={editLot[r.sym] !== undefined ? editLot[r.sym] : r.lot}
                      onChange={e => setEditLot(prev => ({ ...prev, [r.sym]: e.target.value }))}
                      onBlur={() => handleLotBlur(r.sym, r.lot)}
                      onKeyDown={e => { if (e.key === 'Enter') handleLotBlur(r.sym, r.lot); }}
                    />
                  </td>
                  <td>
                    <input
                      className="sr-input"
                      style={{ width: 80, textAlign: 'right' }}
                      type="number"
                      value={editHeld[r.sym] !== undefined ? editHeld[r.sym] : r.lotsHeld}
                      onChange={e => setEditHeld(prev => ({ ...prev, [r.sym]: e.target.value }))}
                      onBlur={() => handleHeldBlur(r.sym, r.lotsHeld)}
                      onKeyDown={e => { if (e.key === 'Enter') handleHeldBlur(r.sym, r.lotsHeld); }}
                    />
                  </td>
                  <td style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>
                    {String.fromCharCode(8377)}{(r.lot * r.lotsHeld * r.price).toLocaleString('en-IN')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="download-bar">
          <span className="footer-stats">
            Total Stocks: <b>{resolvedStocks.length}</b> | Total Lots: <b>{totalLots}</b> | Total Capital: <b style={{ color: 'var(--success)' }}>{String.fromCharCode(8377)}{resolvedStocks.reduce((s, r) => s + r.lot * r.lotsHeld * r.price, 0).toLocaleString('en-IN')}</b>
          </span>
        </div>
      </div>
    </div>
  );
}
