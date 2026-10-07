import { useCallback, useRef, useEffect } from 'react';
import { useAlgoWS, type WsStockData, type WsStatus, type WsAlertData, type WsAlertExpiredData } from '../hooks/useAlgoWS';
import { useStore } from '../store';
import { STOCKS } from '../data';

const SYM_MAP: Record<string, string> = { INDUSINDBK: 'INDUSINDBANK' };
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function resolveSym(sym: string): string {
  return SYM_MAP[sym] || sym;
}

function findStockInfo(sym: string) {
  const resolved = resolveSym(sym);
  return STOCKS.find(s => s.sym === resolved) || { sym: resolved, sector: 'Unknown', lot: 0 };
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
  const { setAlerts, setApiStatus, setMarketOpen, setCurrentMonth, setNextMonth, addToast, loadDataFromBackend, saveToBackend } = useStore();
  const prevAlertsRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    setCurrentMonth(getCurrentMonthStr());
    setNextMonth(getNextMonthStr());
    loadDataFromBackend();
  }, [setCurrentMonth, setNextMonth, loadDataFromBackend]);

  const onInit = useCallback((stocks: WsStockData[], status: WsStatus) => {
    const expiryDays = calcExpiryDays();
    const expired = isExpired();
    const alerts = stocks.map((s) => {
      const resolved = resolveSym(s.stock);
      const info = findStockInfo(s.stock);
      const hasData = s.current_spread !== null && s.discount_pct !== null;
      return {
        id: `ws-${resolved}`,
        sym: resolved,
        sector: info.sector,
        lot: info.lot,
        initial: s.initial_spread,
        current: hasData ? s.current_spread! : 0,
        discount: hasData ? s.discount_pct! : 0,
        lotsAvailable: 0,
        ageSec: 0,
        expiryDays,
        lastUpdated: hasData ? parseTs(s.timestamp) : new Date(0),
        status: expired ? 'Expired' : hasData ? 'Available' : 'Awaiting Data',
      };
    });
    setAlerts(alerts);
    setMarketOpen(status.market_open);

    const map = new Map<string, number>();
    for (const s of stocks) {
      if (s.discount_pct !== null) map.set(resolveSym(s.stock), s.discount_pct);
    }
    prevAlertsRef.current = map;
  }, [setAlerts, setMarketOpen]);

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
    setAlerts(prev => prev.map(a => {
      if (a.sym !== resolved) return a;
      return {
        ...a,
        current: data.spread,
        discount: data.discount_pct,
        lastUpdated: parseTs(data.timestamp),
        ageSec: 0,
        status: a.status === 'Instruction Sent' ? a.status : 'Available',
      };
    }));
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
