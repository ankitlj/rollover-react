import { useCallback, useRef, useEffect } from 'react';
import { useAlgoWS, type WsStockData, type WsStatus, type WsAlertData, type WsAlertExpiredData, type WsExpiredAlertData, type WsExpiries } from '../hooks/useAlgoWS';
import { useStore } from '../store';
import { STOCKS } from '../data';

const SYM_MAP: Record<string, string> = { INDUSINDBK: 'INDUSINDBANK' };
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function resolveSym(sym: string): string {
  return SYM_MAP[sym] || sym;
}

function findStockInfo(sym: string) {
  const resolved = resolveSym(sym);
  return STOCKS.find(s => s.sym === resolved) || { sym: resolved, sector: 'Unknown', lot: 0, price: 0, lotsHeld: 0 };
}

function parseTs(ts: string | null): Date {
  if (!ts) return new Date();
  try {
    return new Date(ts.replace(' ', 'T') + '+05:30');
  } catch {
    return new Date();
  }
}

function getIstNow(): Date {
  const now = new Date();
  return new Date(now.getTime() + 5.5 * 3600000);
}

function calcExpiryDays(): number {
  const ist = getIstNow();
  const year = ist.getUTCFullYear();
  const month = ist.getUTCMonth();
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const dow = new Date(Date.UTC(year, month, lastDay)).getUTCDay();
  let lastThursday = lastDay - ((dow - 4 + 7) % 7);
  if (lastThursday <= 0) lastThursday += 7;
  const expiry = new Date(Date.UTC(year, month, lastThursday));
  return Math.max(0, Math.ceil((expiry.getTime() - ist.getTime()) / 86400000));
}

function isExpired(): boolean {
  const ist = getIstNow();
  const year = ist.getUTCFullYear();
  const month = ist.getUTCMonth();
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const dow = new Date(Date.UTC(year, month, lastDay)).getUTCDay();
  let lastThursday = lastDay - ((dow - 4 + 7) % 7);
  if (lastThursday <= 0) lastThursday += 7;
  const expiry = new Date(Date.UTC(year, month, lastThursday, 15, 30));
  return ist.getTime() > expiry.getTime();
}

function getCurrentMonthStr(): string {
  const ist = getIstNow();
  return MONTH_NAMES[ist.getUTCMonth()] + ' ' + ist.getUTCFullYear();
}

function getNextMonthStr(): string {
  const ist = getIstNow();
  let m = ist.getUTCMonth() + 1;
  let y = ist.getUTCFullYear();
  if (m > 11) { m = 0; y++; }
  return MONTH_NAMES[m] + ' ' + y;
}

export default function AlgoConnection() {
  const { setAlerts, setApiStatus, setMarketOpen, setCurrentMonth, setNextMonth, addToast, loadDataFromBackend, saveToBackend, setExpiries, takePendingActiveAlerts } = useStore();
  const prevAlertsRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    setCurrentMonth(getCurrentMonthStr());
    setNextMonth(getNextMonthStr());
    loadDataFromBackend();
  }, [setCurrentMonth, setNextMonth, loadDataFromBackend]);

  const onInit = useCallback((stocks: WsStockData[], status: WsStatus, expiries: WsExpiries | null, activeAlerts: WsAlertData[], expiredAlerts: WsExpiredAlertData[]) => {
    if (expiries?.current) setExpiries(expiries.current, expiries.next ?? '');
    setMarketOpen(status.market_open);

    const pendingStatus = new Map<string, string>();
    for (const p of takePendingActiveAlerts()) {
      pendingStatus.set(p.sym, p.status);
    }
    const activeSet = new Set(activeAlerts.map(d => resolveSym(d.stock)));

    setAlerts(prev => {
      const updated = prev.map(a => ({ ...a }));

      for (const data of activeAlerts) {
        const resolved = resolveSym(data.stock);
        const idx = updated.findIndex(x => x.sym === resolved);
        if (idx >= 0) {
          const a = updated[idx];
          if (a.status === 'Cancelled') continue;
          if (a.status === 'Expired') {
            updated[idx] = {
              ...a,
              initial: data.initial_spread,
              spreadAtSignal: data.spread,
              current: data.spread,
              discount: data.discount_pct,
              lastUpdated: parseTs(data.timestamp),
              ageSec: 0,
              status: pendingStatus.get(resolved) === 'Instruction Sent' ? 'Instruction Sent' : 'Available',
            };
          } else {
            updated[idx] = {
              ...a,
              current: data.spread,
              discount: data.discount_pct,
              lastUpdated: parseTs(data.timestamp),
              ageSec: 0,
              status: a.status === 'Instruction Sent' ? a.status : 'Available',
            };
          }
        } else {
          const info = findStockInfo(data.stock);
          updated.push({
            id: `ws-${resolved}`,
            sym: resolved,
            sector: info.sector,
            lot: info.lot,
            price: info.price,
            initial: data.initial_spread,
            current: data.spread,
            spreadAtSignal: data.spread,
            discount: data.discount_pct,
            lotsAvailable: info.lotsHeld ?? 0,
            ageSec: 0,
            expiryDays: calcExpiryDays(),
            lastUpdated: parseTs(data.timestamp),
            status: pendingStatus.get(resolved) === 'Instruction Sent' ? 'Instruction Sent' : 'Available',
          });
        }
      }

      for (const data of expiredAlerts) {
        const resolved = resolveSym(data.stock);
        if (activeSet.has(resolved)) continue;
        const idx = updated.findIndex(x => x.sym === resolved);
        const current = data.final_spread ?? data.spread ?? 0;
        const ts = data.expired_at ?? data.timestamp ?? null;
        if (idx >= 0) {
          const a = updated[idx];
          if (a.status === 'Expired' || a.status === 'Cancelled') continue;
          updated[idx] = {
            ...a,
            current,
            lastUpdated: parseTs(ts),
            status: 'Expired',
          };
        } else {
          const info = findStockInfo(data.stock);
          updated.push({
            id: `ws-${resolved}`,
            sym: resolved,
            sector: info.sector,
            lot: info.lot,
            price: info.price,
            initial: data.initial_spread ?? 0,
            current,
            discount: data.discount_pct ?? 0,
            lotsAvailable: info.lotsHeld ?? 0,
            ageSec: 0,
            expiryDays: calcExpiryDays(),
            lastUpdated: parseTs(ts),
            status: 'Expired',
          });
        }
      }

      // Purge: write the server-confirmed lists back so rows saved while the
      // tab was disconnected stop reappearing on every reload.
      const dateTag = new Date().toISOString().split('T')[0].replace(/-/g, '');
      const active = updated.filter(a => a.status !== 'Expired' && a.status !== 'Cancelled');
      const expiredList = updated.filter(a => a.status === 'Expired' || a.status === 'Cancelled');
      saveToBackend(`active_opportunities_${dateTag}`, active);
      saveToBackend(`expired_opportunities_${dateTag}`, expiredList);

      return updated;
    });

    const map = new Map<string, number>();
    for (const s of stocks) {
      if (s.discount_pct !== null) map.set(resolveSym(s.stock), s.discount_pct);
    }
    prevAlertsRef.current = map;
  }, [setExpiries, setMarketOpen, setAlerts, saveToBackend, takePendingActiveAlerts]);

  const onSnapshot = useCallback((stocks: WsStockData[], _timestamp: string) => {
    const expired = isExpired();
    setAlerts(prev => {
      const updated = prev.map(a => {
        if (a.status === 'Expired' || a.status === 'Cancelled') return a;
        const match = stocks.find(s => resolveSym(s.stock) === a.sym);
        if (!match || match.current_spread === null) return a;
        const newStatus = expired ? 'Expired' : (a.status === 'Instruction Sent' ? a.status : 'Available');
        return {
          ...a,
          current: match.current_spread!,
          discount: match.discount_pct!,
          lastUpdated: parseTs(match.timestamp),
          ageSec: 0,
          status: newStatus,
        };
      });
      if (expired) {
        const dateTag = new Date().toISOString().split('T')[0].replace(/-/g, '');
        const active = updated.filter(a => a.status !== 'Expired' && a.status !== 'Cancelled');
        const expiredList = updated.filter(a => a.status === 'Expired' || a.status === 'Cancelled');
        saveToBackend(`active_opportunities_${dateTag}`, active);
        saveToBackend(`expired_opportunities_${dateTag}`, expiredList);
      }
      return updated;
    });

    const map = new Map<string, number>();
    for (const s of stocks) {
      if (s.discount_pct !== null) map.set(resolveSym(s.stock), s.discount_pct);
    }
    prevAlertsRef.current = map;
  }, [setAlerts, saveToBackend]);

  const onAlert = useCallback((data: WsAlertData) => {
    const resolved = resolveSym(data.stock);
    const info = findStockInfo(data.stock);
    setAlerts(prev => {
      const existing = prev.find(a => a.sym === resolved);
      if (existing) {
        return prev.map(a => a.sym !== resolved ? a : {
          ...a,
          current: data.spread,
          discount: data.discount_pct,
          lastUpdated: parseTs(data.timestamp),
          ageSec: 0,
          status: a.status === 'Instruction Sent' ? a.status : 'Available',
        });
      }
      return [...prev, {
        id: `ws-${resolved}`,
        sym: resolved,
        sector: info.sector,
        lot: info.lot,
        price: info.price,
        initial: data.initial_spread,
        current: data.spread,
        spreadAtSignal: data.spread,
        discount: data.discount_pct,
        lotsAvailable: info.lotsHeld ?? 0,
        ageSec: 0,
        expiryDays: calcExpiryDays(),
        lastUpdated: parseTs(data.timestamp),
        status: 'Available',
      }];
    });
    addToast('info', `Alert: ${resolved}`);
    prevAlertsRef.current.set(resolved, data.discount_pct);
  }, [setAlerts, addToast]);

  const onAlertExpired = useCallback((data: WsAlertExpiredData) => {
    const resolved = resolveSym(data.stock);
    setAlerts(prev => {
      const updated = prev.map(a => {
        if (a.sym !== resolved) return a;
        return {
          ...a,
          current: data.final_spread,
          lastUpdated: parseTs(data.timestamp),
          status: 'Expired',
        };
      });
      const dateTag = new Date().toISOString().split('T')[0].replace(/-/g, '');
      const active = updated.filter(a => a.status !== 'Expired' && a.status !== 'Cancelled');
      const expired = updated.filter(a => a.status === 'Expired' || a.status === 'Cancelled');
      saveToBackend(`active_opportunities_${dateTag}`, active);
      saveToBackend(`expired_opportunities_${dateTag}`, expired);
      return updated;
    });
  }, [setAlerts, saveToBackend]);

  const onStatus = useCallback((status: WsStatus) => {
    setMarketOpen(status.market_open);
  }, [setMarketOpen]);

  const onConnectionChange = useCallback((status: 'connected' | 'reconnecting' | 'disconnected') => {
    setApiStatus(status);
  }, [setApiStatus]);

  useAlgoWS({ onInit, onSnapshot, onAlert, onAlertExpired, onStatus, onConnectionChange });

  return null;
}
