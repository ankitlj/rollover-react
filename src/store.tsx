import { createContext, useContext, useState, useCallback, useRef, type ReactNode } from 'react';
import type { Alert, LogEntry, Correction, Settings, Stock, Toast, Notification, PageId } from './types';
import { createInitialLogEntries, DEFAULT_SETTINGS, STOCKS } from './data';

interface StoreState {
  alerts: Alert[];
  logEntries: LogEntry[];
  corrections: Correction[];
  finalisedDays: Record<string, { finalisedAt: string; entries: number }>;
  settings: Settings;
  stockOverrides: Record<string, Partial<Stock>>;
  currentPage: PageId;
  currentTheme: 'dark' | 'light';
  currentUser: string;
  toasts: Toast[];
  notifications: Notification[];
  isLoggedIn: boolean;
  showTransition: boolean;
  apiStatus: 'connected' | 'reconnecting' | 'disconnected';
  marketOpen: boolean;
  currentMonth: string;
  nextMonth: string;
  expiryCur: string;
  expiryNext: string;
}

interface StoreActions {
  setCurrentPage: (page: PageId) => void;
  toggleTheme: () => void;
  login: (user: string, pass: string) => boolean;
  logout: () => void;
  completeTransition: () => void;
  loadDataFromBackend: () => Promise<void>;
  saveToBackend: (table: string, content: any) => Promise<void>;
  saveSettingsToBackend: (settingsData: any) => Promise<void>;
  sendInstruction: (alertId: string, lots: number) => void;
  saveEod: (entryId: string, data: { filled: number; partial: number; notFilled: number; fillPrice: number; finalSpread: number; remarks: string }) => void;
  saveCorrection: (entryId: string, data: { field: string; newVal: string; reason: string }) => void;
  addCorrectionBatch: (corrections: Correction[]) => void;
  finaliseDay: (date: string) => void;
  finaliseEntry: (entryId: string) => void;
  updateDealerRemarks: (entryId: string, remarks: string) => void;
  setStatus: (entryId: string, status: string) => void;
  updateLogField: (entryId: string, field: 'lotsFilled' | 'avgFillPrice' | 'finalSpread', value: number) => void;
  updateSettings: (key: string, value: number | string) => void;
  resetSettings: () => void;
  updateStock: (sym: string, field: 'lot' | 'lotsHeld', value: number) => void;
  addToast: (type: Toast['type'], title: string, detail?: string) => void;
  removeToast: (id: string) => void;
  addNotification: (type: Notification['type'], title: string, msg: string) => void;
  removeNotification: (id: string) => void;
  updateAlerts: (updater: (alerts: Alert[]) => void) => void;
  setAlerts: (alerts: Alert[] | ((prev: Alert[]) => Alert[])) => void;
  setApiStatus: (status: 'connected' | 'reconnecting' | 'disconnected') => void;
  setMarketOpen: (open: boolean) => void;
  setCurrentMonth: (month: string) => void;
  setNextMonth: (month: string) => void;
  setExpiries: (cur: string, next: string) => void;
  resolvedStocks: Stock[];
}

const StoreContext = createContext<(StoreState & StoreActions) | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  //const hasSession = !!sessionStorage.getItem('rs-session');
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [logEntries, setLogEntries] = useState<LogEntry[]>(createInitialLogEntries);
  const [corrections, setCorrections] = useState<Correction[]>([]);
  const [finalisedDays, setFinalisedDays] = useState<Record<string, { finalisedAt: string; entries: number }>>({});
  const [settings, setSettings] = useState<Settings>({ ...DEFAULT_SETTINGS });
  const [currentPage, setCurrentPage] = useState<PageId>('alerts');
  const [currentTheme, setCurrentTheme] = useState<'dark' | 'light'>('dark');
  const [currentUser, setCurrentUser] = useState(() => {
    try {
      const s = sessionStorage.getItem('rs-session');
      return s ? JSON.parse(s).user : '';
    } catch { return ''; }
  });
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [isLoggedIn, setIsLoggedIn] = useState(() => {
    return !!sessionStorage.getItem('rs-session');
  });
  const [showTransition, setShowTransition] = useState(false);
  const [stockOverrides, setStockOverrides] = useState<Record<string, Partial<Stock>>>({});
  const [apiStatus, setApiStatus] = useState<'connected' | 'reconnecting' | 'disconnected'>('disconnected');
  const [marketOpen, setMarketOpen] = useState(false);
  const [currentMonth, setCurrentMonth] = useState('');
  const [nextMonth, setNextMonth] = useState('');
  const [expiryCur, setExpiryCur] = useState('');
  const [expiryNext, setExpiryNext] = useState('');
  const toastIdRef = useRef(0);
  const notifIdRef = useRef(0);

  const resolvedStocks: Stock[] = STOCKS.map(s => {
    const ovr = stockOverrides[s.sym];
    return ovr ? { ...s, ...ovr } : s;
  });

  const login = useCallback((user: string, pass: string) => {
    const valid = (user === 'ankit@36' && pass === 'ankit@321') || (user === 'user@1' && pass === 'user@123');
    if (valid) {
      setCurrentUser(user);
      setIsLoggedIn(true);
      setShowTransition(true);
      sessionStorage.setItem('rs-session', JSON.stringify({ user, loggedInAt: new Date().toISOString() }));
      return true;
    }
    return false;
  }, []);

  const loadDataFromBackend = useCallback(async () => {
    try {
      const resp = await fetch('https://rollover-react-production-a68d.up.railway.app/data/load');
      if (!resp.ok) return;
      const data = await resp.json();
      const dateTag = new Date().toISOString().split('T')[0].replace(/-/g, '');
      
      const activeKey = `active_opportunities_${dateTag}`;
      const expiredKey = `expired_opportunities_${dateTag}`;
      const logKey = `daily_instruction_log_${dateTag}`;
      const corrKey = `correction_history_${dateTag}`;

      let logRows: LogEntry[] = [];
      if (data[logKey] && Array.isArray(data[logKey])) {
        logRows = (data[logKey] as LogEntry[]).map(e => ({
          ...e,
          lastUpdated: new Date(e.lastUpdated as unknown as string),
        }));
        setLogEntries(logRows);
      }
      const instructedSyms = new Set(logRows.map(e => e.sym));

      const restored: Alert[] = [];
      for (const key of [activeKey, expiredKey]) {
        if (data[key] && Array.isArray(data[key])) {
          for (const a of data[key] as Alert[]) {
            const gone = a.status === 'Expired' || a.status === 'Cancelled';
            const instructed = !gone && instructedSyms.has(a.sym);
            restored.push({
              ...a,
              status: gone ? a.status : instructed ? 'Instruction Sent' : (a.status === 'Instruction Sent' ? 'Available' : a.status),
              executed: instructed ? true : a.executed,
              lastUpdated: new Date(a.lastUpdated as unknown as string),
            });
          }
        }
      }
      if (restored.length > 0) {
        setAlerts(prev => {
          const merged = [...prev];
          for (const a of restored) {
            const idx = merged.findIndex(x => x.id === a.id);
            if (idx === -1) {
              merged.push(a);
            } else if (merged[idx].status !== 'Instruction Sent' && a.status === 'Instruction Sent') {
              merged[idx] = { ...merged[idx], status: 'Instruction Sent', executed: true };
            }
          }
          return merged;
        });
      }
      
      if (data[corrKey] && Array.isArray(data[corrKey])) {
        setCorrections(data[corrKey]);
      }
      
      if (data.settings && typeof data.settings === 'object') {
        if (data.settings.settings) {
          setSettings(data.settings.settings);
        }
        if (data.settings.stockOverrides) {
          setStockOverrides(data.settings.stockOverrides);
        }
      }
    } catch (err) {
      console.warn('Failed to load data from backend:', err);
    }
  }, []);

  const saveToBackend = useCallback(async (table: string, content: any) => {
    try {
      await fetch('https://rollover-react-production-a68d.up.railway.app/data/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table, content })
      });
    } catch (err) {
      console.warn(`Failed to save ${table} to backend:`, err);
    }
  }, []);

  const saveSettingsToBackend = useCallback(async (settingsData: any) => {
    try {
      await fetch('https://rollover-react-production-a68d.up.railway.app/data/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settingsData)
      });
    } catch (err) {
      console.warn('Failed to save settings to backend:', err);
    }
  }, []);

  const logout = useCallback(() => {
    setIsLoggedIn(false);
    setCurrentUser('');
    setAlerts([]);
    sessionStorage.removeItem('rs-session');
  }, []);

  const completeTransition = useCallback(() => {
    setShowTransition(false);
  }, []);

  const toggleTheme = useCallback(() => {
    setCurrentTheme(prev => {
      const next = prev === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      return next;
    });
  }, []);

  const addToast = useCallback((type: Toast['type'], title: string, detail?: string) => {
    const id = 'toast-' + (++toastIdRef.current);
    setToasts(prev => [...prev, { id, type, title, detail }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const addNotification = useCallback((type: Notification['type'], title: string, msg: string) => {
    const id = 'notif-' + (++notifIdRef.current);
    setNotifications(prev => [...prev, { id, type, title, msg }]);
    setTimeout(() => setNotifications(prev => prev.filter(n => n.id !== id)), 5000);
  }, []);

  const removeNotification = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  }, []);

  const sendInstruction = useCallback((alertId: string, lots: number) => {
    const a = alerts.find(x => x.id === alertId);
    if (!a) return;
    const stock = resolvedStocks.find(s => s.sym === a.sym);
    const estSaving = (a.initial - a.current) * lots * (stock?.lot || 1);
    const today = new Date().toISOString().split('T')[0];

    const newEntry = {
      id: 'LOG-' + Date.now(),
      alertId: a.id,
      date: today,
      sym: a.sym,
      sector: a.sector,
      lotSize: stock?.lot,
      price: stock?.price,
      expiry: expiryCur,
      lotsHeld: a.lotsAvailable,
      lotsInstructed: lots,
      lotsFilled: 0,
      lotsPartiallyFilled: 0,
      lotsNotFilled: 0,
      pendingLots: lots,
      avgFillPrice: 0,
      finalSpread: 0,
      dealerRemarks: '',
      confirmStatus: 'Awaiting EOD Update',
      estimatedSpread: a.current,
      estimatedSaving: estSaving,
      confirmedSaving: 0,
      missedSaving: 0,
      lastUpdated: new Date(),
      instructionTimestamp: new Date().toISOString(),
      finalised: false
    };

    setLogEntries(prev => {
      const updated = [...prev, newEntry];
      const dateTag = new Date().toISOString().split('T')[0].replace(/-/g, '');
      saveToBackend(`daily_instruction_log_${dateTag}`, updated);
      return updated;
    });

    setAlerts(prev => prev.map(x => x.id === alertId ? { ...x, status: 'Instruction Sent', executed: true } : x));
  }, [alerts, resolvedStocks, saveToBackend, expiryCur]);

  const saveEod = useCallback((entryId: string, data: { filled: number; partial: number; notFilled: number; fillPrice: number; finalSpread: number; remarks: string }) => {
    setLogEntries(prev => {
      const updated = prev.map(e => {
        if (e.id !== entryId) return e;
        const stock = resolvedStocks.find(s => s.sym === e.sym);
        const confirmedSaving = Math.max(0, data.filled * ((e.estimatedSpread || 0) - data.finalSpread) * (stock?.lot || 1));
        const confirmStatus = data.filled === e.lotsInstructed ? 'Confirmed' : (data.filled > 0 || data.partial > 0) ? 'Partially Confirmed' : 'Not Filled';

        setAlerts(prevA => prevA.map(a => {
          if (a.id !== e.alertId) return a;
          const newStatus = data.filled === e.lotsInstructed ? 'Fully Filled' : (data.filled > 0 || data.partial > 0) ? 'Partially Filled' : 'Not Filled';
          return { ...a, status: newStatus };
        }));

        return {
          ...e,
          lotsFilled: data.filled,
          lotsPartiallyFilled: data.partial,
          lotsNotFilled: data.notFilled,
          pendingLots: data.partial,
          avgFillPrice: data.fillPrice,
          finalSpread: data.finalSpread,
          dealerRemarks: data.remarks,
          confirmedSaving,
          missedSaving: data.notFilled * ((e.estimatedSpread || 0) - data.finalSpread) * (stock?.lot || 1),
          confirmStatus,
          lastUpdated: new Date()
        };
      });
      const dateTag = new Date().toISOString().split('T')[0].replace(/-/g, '');
      const finalised = updated.filter(e => e.finalised);
      saveToBackend(`execution_details_${dateTag}`, finalised);
      return updated;
    });
  }, [resolvedStocks, saveToBackend]);

  const saveCorrection = useCallback((entryId: string, data: { field: string; newVal: string; reason: string }) => {
    setLogEntries(prev => prev.map(e => {
      if (e.id !== entryId) return e;
      const field = data.field as keyof LogEntry;
      const oldVal = e[field];
      let parsed: number | string = data.newVal;
      if (field !== 'dealerRemarks') {
        parsed = (field === 'avgFillPrice' || field === 'finalSpread') ? parseFloat(data.newVal) : parseInt(data.newVal);
      }

      setCorrections(prevC => {
        const updatedCorrections = [...prevC, {
          id: 'CORR-' + Date.now(),
          date: e.date,
          entryId: e.id,
          stock: e.sym,
          field: data.field,
          oldValue: oldVal,
          newValue: parsed,
          reason: data.reason,
          timestamp: new Date().toISOString()
        }];
        const dateTag = new Date().toISOString().split('T')[0].replace(/-/g, '');
        saveToBackend(`correction_history_${dateTag}`, updatedCorrections);
        return updatedCorrections;
      });

      const updated = { ...e, [field]: parsed, lastUpdated: new Date() };

      if (['lotsFilled', 'lotsPartiallyFilled', 'lotsNotFilled', 'finalSpread'].includes(data.field)) {
        const stock = resolvedStocks.find(s => s.sym === e.sym);
        updated.confirmedSaving = Math.max(0, updated.lotsFilled * ((updated.estimatedSpread || 0) - updated.finalSpread) * (stock?.lot || 1));
        updated.confirmStatus = updated.lotsFilled === updated.lotsInstructed ? 'Confirmed' : (updated.lotsFilled > 0) ? 'Partially Confirmed' : 'Not Filled';
      }
      return updated;
    }));
  }, [resolvedStocks, saveToBackend]);

  const addCorrectionBatch = useCallback((newCorrections: Correction[]) => {
    setCorrections(prev => [...prev, ...newCorrections]);
  }, []);

  const finaliseDay = useCallback((date: string) => {
    setFinalisedDays(prev => ({
      ...prev,
      [date]: { finalisedAt: new Date().toISOString(), entries: logEntries.filter(e => e.date === date).length }
    }));
  }, [logEntries]);

  const finaliseEntry = useCallback((entryId: string) => {
    setLogEntries(prev => {
      const updated = prev.map(e =>
        e.id === entryId ? { ...e, finalised: true, lastUpdated: new Date() } : e
      );
      const dateTag = new Date().toISOString().split('T')[0].replace(/-/g, '');
      const finalised = updated.filter(e => e.finalised);
      saveToBackend(`execution_details_${dateTag}`, finalised);
      return updated;
    });
  }, [saveToBackend]);

  const updateDealerRemarks = useCallback((entryId: string, remarks: string) => {
    setLogEntries(prev => prev.map(e =>
      e.id === entryId ? { ...e, dealerRemarks: remarks, lastUpdated: new Date() } : e
    ));
  }, []);

  const setStatus = useCallback((entryId: string, status: string) => {
    setLogEntries(prev => prev.map(e =>
      e.id === entryId ? { ...e, confirmStatus: status, lastUpdated: new Date() } : e
    ));
  }, []);

  const updateLogField = useCallback((entryId: string, field: 'lotsFilled' | 'avgFillPrice' | 'finalSpread', value: number) => {
    setLogEntries(prev => prev.map(e => {
      if (e.id !== entryId) return e;
      const updated = { ...e, [field]: value, lastUpdated: new Date() };
      if (field === 'lotsFilled' || field === 'finalSpread') {
        const stock = resolvedStocks.find(s => s.sym === e.sym);
        updated.confirmedSaving = Math.max(0, updated.lotsFilled * ((updated.estimatedSpread || 0) - updated.finalSpread) * (stock?.lot || 1));
      }
      return updated;
    }));
  }, [resolvedStocks]);

  const updateSettings = useCallback((key: string, value: number | string) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  }, []);

  const resetSettings = useCallback(() => {
    setSettings({ ...DEFAULT_SETTINGS });
  }, []);

  const updateStock = useCallback((sym: string, field: 'lot' | 'lotsHeld', value: number) => {
    setStockOverrides(prev => ({
      ...prev,
      [sym]: { ...prev[sym], [field]: value }
    }));
  }, []);

  const updateAlerts = useCallback((updater: (alerts: Alert[]) => void) => {
    setAlerts(prev => {
      const copy = prev.map(a => ({ ...a }));
      updater(copy);
      return copy;
    });
  }, []);

  const setExpiries = useCallback((cur: string, next: string) => {
    setExpiryCur(cur);
    setExpiryNext(next);
  }, []);

  const value = {
    alerts, logEntries, corrections, finalisedDays, settings, stockOverrides, resolvedStocks,
    currentPage, currentTheme, currentUser, toasts, notifications,
    isLoggedIn, showTransition, apiStatus, marketOpen, currentMonth, nextMonth, expiryCur, expiryNext,
    setCurrentPage, toggleTheme, login, logout, completeTransition, loadDataFromBackend,
    saveToBackend, saveSettingsToBackend,
    sendInstruction, saveEod, saveCorrection, addCorrectionBatch, finaliseDay,
    finaliseEntry, updateDealerRemarks, setStatus, updateLogField,
    updateSettings, resetSettings, updateStock, setExpiries,
    addToast, removeToast, addNotification, removeNotification,
    updateAlerts, setAlerts, setApiStatus, setMarketOpen, setCurrentMonth, setNextMonth
  };

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore() {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error('useStore must be used within StoreProvider');
  return ctx;
}
