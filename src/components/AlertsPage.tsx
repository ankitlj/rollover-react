import { useState, useMemo, useRef, useEffect } from 'react';
import { useStore } from '../store';
import { STOCKS, EXPIRY_CUR } from '../data';
import ExecModal from './ExecModal';

const SECTORS = [...new Set(STOCKS.map(s => s.sector))].sort();

export default function AlertsPage() {
  const { alerts, addToast } = useStore();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sectorFilter, setSectorFilter] = useState('all');
  const [sortCol, setSortCol] = useState('discount');
  const [sortDir, setSortDir] = useState(-1);
  const [execAlertId, setExecAlertId] = useState<string | null>(null);
  const [marketOpen, setMarketOpen] = useState(() => {
    const now = new Date();
    const ist = new Date(now.getTime() + 5.5 * 3600000);
    const h = ist.getUTCHours(), m = ist.getUTCMinutes();
    const mins = h * 60 + m;
    return mins >= 555 && mins < 915;
  });
  const flashCellsRef = useRef<Record<string, 'up' | 'down'>>({});

  const filtered = useMemo(() => {
    return alerts.filter(a => {
      if (search && !a.sym.toLowerCase().includes(search.toLowerCase())) return false;
      if (statusFilter !== 'all' && a.status !== statusFilter) return false;
      if (sectorFilter !== 'all' && a.sector !== sectorFilter) return false;
      return true;
    });
  }, [alerts, search, statusFilter, sectorFilter]);

  const active = useMemo(() => {
    const arr = filtered.filter(a => a.status !== 'Expired' && a.status !== 'Cancelled');
    arr.sort((a, b) => {
      let va: number | string, vb: number | string;
      if (sortCol === 'stock') { va = a.sym; vb = b.sym; return sortDir * va.localeCompare(vb); }
      if (sortCol === 'initial') { va = a.initial; vb = b.initial; }
      else if (sortCol === 'current') { va = a.current; vb = b.current; }
      else if (sortCol === 'age') { va = a.ageSec; vb = b.ageSec; }
      else if (sortCol === 'spread') { va = a.current; vb = b.current; }
      else { va = a.discount; vb = b.discount; }
      return sortDir * ((va as number) - (vb as number));
    });
    return arr;
  }, [filtered, sortCol, sortDir]);

  const expired = useMemo(() => filtered.filter(a => a.status === 'Expired' || a.status === 'Cancelled'), [filtered]);

  const handleSort = (col: string) => {
    if (sortCol === col) setSortDir(d => d * -1);
    else { setSortCol(col); setSortDir(col === 'stock' ? 1 : -1); }
  };

  const sortIcon = (_col: string) => null;

  const openExec = (alertId: string) => {
    const a = alerts.find(x => x.id === alertId);
    if (!a) return;
    const dup = alerts.find(l => l.id === alertId && l.status === 'Instruction Sent');
    if (dup) { addToast('warning', 'Instruction already sent for ' + a.sym); return; }
    setExecAlertId(alertId);
  };

  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const checkMarket = () => {
      const now = new Date();
      const ist = new Date(now.getTime() + 5.5 * 3600000);
      const h = ist.getUTCHours(), m = ist.getUTCMinutes();
      const mins = h * 60 + m;
      setMarketOpen(mins >= 555 && mins < 915);
    };
    checkMarket();
    const id = setInterval(checkMarket, 60000);
    return () => clearInterval(id);
  }, []);

  const renderAgeCell = (a: typeof active[0]) => {
    const ageSecs = Math.floor((Date.now() - a.lastUpdated.getTime()) / 1000);
    const ageStr = ageSecs >= 60 ? Math.floor(ageSecs / 60) + 'm ' + (ageSecs % 60) + 's' : ageSecs + 's';
    return (
      <span className="timer-text">{ageStr} <span className="unit">ago</span></span>
    );
  };

  const getStatusBadge = (status: string) => {
    const map: Record<string, string> = {
      'Available': 'badge-active',
      'Instruction Sent': 'badge-sent',
      'Awaiting Confirmation': 'badge-pending',
      'Fully Filled': 'badge-executed',
      'Partially Filled': 'badge-partial',
      'Not Filled': 'badge-rejected',
    };
    return map[status] || 'badge-active';
  };

  const exportCSV = () => {
    const headers = ['Stock', 'Sector', 'Expiry', 'Initial', 'Current', 'Discount %', 'Lots', 'Status'];
    const rows = active.map(a => [a.sym, a.sector, EXPIRY_CUR, a.initial, a.current, a.discount, a.lotsAvailable, a.status]);
    let csv = headers.join(',') + '\n' + rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = 'spread_alerts.csv'; link.click();
  };

  const exportExpiredCSV = () => {
    const headers = ['Stock', 'Expiry', 'Initial', 'Final', 'Status'];
    const rows = expired.map(a => [a.sym, EXPIRY_CUR, a.initial, a.current, a.status]);
    let csv = headers.join(',') + '\n' + rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = 'expired_alerts.csv'; link.click();
  };

  return (
    <div>
      <div className="toolbar">
        <div className="toolbar-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" /></svg>
          <input type="text" placeholder="Search stock..." value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <select className="toolbar-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="all">All Status</option>
          <option value="Available">Available</option>
          <option value="Instruction Sent">Instruction Sent</option>
          <option value="Expired">Expired</option>
          <option value="Cancelled">Cancelled</option>
        </select>
        <select className="toolbar-select" value={sectorFilter} onChange={e => setSectorFilter(e.target.value)}>
          <option value="all">All Sectors</option>
          {SECTORS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="toolbar-select" value={sortCol} onChange={e => handleSort(e.target.value)}>
          <option value="discount">Sort: Discount</option>
          <option value="stock">Sort: Stock</option>
          <option value="age">Sort: Signal Age</option>
          <option value="spread">Sort: Spread</option>
        </select>
        <div className="toolbar-info">
          <span className={marketOpen ? 'fresh' : 'stale'} style={{ fontWeight: 700, letterSpacing: 0.5 }}>{marketOpen ? 'MARKET OPEN' : 'MARKET CLOSED'}</span>
        </div>
      </div>

      <div className="section-label">
        <span>Active Opportunities</span>
        <span className="label-badge">{active.length} LIVE</span>
        <span className="label-line" />
      </div>

      <div className="table-card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className={sortCol === 'stock' ? 'sorted' : ''} onClick={() => handleSort('stock')}>Stock{sortIcon('stock')}</th>
                <th>Expiry</th>
                <th className={sortCol === 'initial' ? 'sorted' : ''} onClick={() => handleSort('initial')}>Initial Spread{sortIcon('initial')}</th>
                <th className={sortCol === 'current' ? 'sorted' : ''} onClick={() => handleSort('current')}>Current Spread{sortIcon('current')}</th>
                <th className={sortCol === 'discount' ? 'sorted' : ''} onClick={() => handleSort('discount')}>Discount %{sortIcon('discount')}</th>
                <th className={sortCol === 'age' ? 'sorted' : ''} onClick={() => handleSort('age')}>Signal Age{sortIcon('age')}</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {active.length > 0 ? active.map(a => {
                const rowClass = a.expiryDays <= 2 ? 'critical' : a.expiryDays <= 5 ? 'urgent' : '';
                const discClass = a.discount >= 50 ? 'positive' : a.discount >= 20 ? 'neutral' : 'negative';
                const canExec = a.status === 'Available';
                const flash = flashCellsRef.current[a.sym];
                if (flash) delete flashCellsRef.current[a.sym];
                return (
                  <tr key={a.id} className={`row-enter ${rowClass}`}>
                    <td><span className="live-dot" /><span className="stock-name">{a.sym}</span><div className="stock-meta">{a.sector}</div></td>
                    <td>{EXPIRY_CUR}</td>
                    <td>{a.initial.toFixed(2)}</td>
                    <td className={flash ? (flash === 'up' ? 'cell-flash-green' : 'cell-flash-red') : ''}>{a.current.toFixed(2)}</td>
                    <td><span className={`discount-badge ${discClass}`}>{a.discount.toFixed(1)}%</span></td>
                    <td>{renderAgeCell(a)}</td>
                    <td><span className={`badge ${getStatusBadge(a.status)}`}>{a.status}</span></td>
                    <td>
                      {canExec
                        ? <button className="btn-execute" onClick={() => openExec(a.id)}>EXECUTE</button>
                        : <button className="btn-execute executed" disabled>{a.status}</button>
                      }
                    </td>
                  </tr>
                );
              }) : (
                <tr><td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: 20 }}>No active opportunities</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="download-bar">
          <div className="download-btns">
            <button className="btn-download" onClick={exportCSV}>CSV</button>
            <button className="btn-download" onClick={exportCSV}>Excel</button>
          </div>
        </div>
      </div>

      <div className="section-label">
        <span>Expired Opportunities</span>
        <span className="label-badge">{expired.length} CLOSED</span>
        <span className="label-line" />
      </div>
      <div className="table-card">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Stock</th><th>Expiry</th><th>Initial</th><th>Final</th><th>Status</th></tr></thead>
            <tbody>
              {expired.length > 0 ? expired.map(a => (
                <tr key={a.id}>
                  <td><span className="stock-name">{a.sym}</span></td>
                  <td>{EXPIRY_CUR}</td>
                  <td>{a.initial.toFixed(2)}</td>
                  <td>{a.current.toFixed(2)}</td>
                  <td><span className="badge badge-expired">{a.status}</span></td>
                </tr>
              )) : (
                <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: 20 }}>No expired opportunities</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="download-bar">
          <div className="download-btns">
            <button className="btn-download" onClick={exportExpiredCSV}>CSV</button>
            <button className="btn-download" onClick={exportExpiredCSV}>Excel</button>
          </div>
        </div>
      </div>

      {execAlertId && (
        <ExecModal alertId={execAlertId} onClose={() => setExecAlertId(null)} />
      )}
    </div>
  );
}
