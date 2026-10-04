import { createContext, useContext, useState, useCallback, useRef, type ReactNode } from 'react';
import type { Alert, LogEntry, Correction, Settings, Stock, Toast, Notification, PageId } from './types';
import { genAlerts, createInitialLogEntries, DEFAULT_SETTINGS, STOCKS, EXPIRY_CUR } from './data';

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
  currentMonth: string;
  nextMonth: string;
}

interface StoreActions {
  setCurrentPage: (page: PageId) => void;
  toggleTheme: () => void;
  login: (user: string, pass: string) => boolean;
  logout: () => void;
  completeTransition: () => void;
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
  setAlerts: (alerts: Alert[]) => void;
  setApiStatus: (status: 'connected' | 'reconnecting' | 'disconnected') => void;
  resolvedStocks: Stock[];
}

const StoreContext = createContext<(StoreState & StoreActions) | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const hasSession = !!sessionStorage.getItem('rs-session');
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
  const [apiStatus, setApiStatus] = useState<'connected' | 'reconnecting' | 'disconnected'>('connected');
  const [currentMonth] = useState('Oct 2025');
  const [nextMonth] = useState('Nov 2025');
  const toastIdRef = useRef(0);
  const notifIdRef = useRef(0);

  const resolvedStocks: Stock[] = STOCKS.map(s => {
    const ovr = stockOverrides[s.sym];
    return ovr ? { ...s, ...ovr } : s;
  });

  const login = useCallback((user: string, pass: string) => {
    if (user === 'ankit@36' && pass === 'ankit@321') {
      setCurrentUser(user);
      setIsLoggedIn(true);
      setShowTransition(true);
      sessionStorage.setItem('rs-session', JSON.stringify({ user, loggedInAt: new Date().toISOString() }));
      return true;
    }
    return false;
  }, []);

  const logout = useCallback(() => {
    setIsLoggedIn(false);
    setCurrentUser('');
    setAlerts([]);
    sessionStorage.removeItem('rs-session');
  }, []);

  const completeTransition = useCallback(() => {
    setShowTransition(false);
    setAlerts(genAlerts());
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

    setLogEntries(prev => [...prev, {
      id: 'LOG-' + Date.now(),
      alertId: a.id,
      date: today,
      sym: a.sym,
      sector: a.sector,
      lotSize: stock?.lot,
      price: stock?.price,
      expiry: EXPIRY_CUR,
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
    }]);

    setAlerts(prev => prev.map(x => x.id === alertId ? { ...x, status: 'Instruction Sent', executed: true } : x));
  }, [alerts, resolvedStocks]);

  const saveEod = useCallback((entryId: string, data: { filled: number; partial: number; notFilled: number; fillPrice: number; finalSpread: number; remarks: string }) => {
    setLogEntries(prev => prev.map(e => {
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
    }));
  }, [resolvedStocks]);

  const saveCorrection = useCallback((entryId: string, data: { field: string; newVal: string; reason: string }) => {
    setLogEntries(prev => prev.map(e => {
      if (e.id !== entryId) return e;
      const field = data.field as keyof LogEntry;
      const oldVal = e[field];
      let parsed: number | string = data.newVal;
      if (field !== 'dealerRemarks') {
        parsed = (field === 'avgFillPrice' || field === 'finalSpread') ? parseFloat(data.newVal) : parseInt(data.newVal);
      }

      setCorrections(prevC => [...prevC, {
        id: 'CORR-' + Date.now(),
        date: e.date,
        entryId: e.id,
        stock: e.sym,
        field: data.field,
        oldValue: oldVal,
        newValue: parsed,
        reason: data.reason,
        timestamp: new Date().toISOString()
      }]);

      const updated = { ...e, [field]: parsed, lastUpdated: new Date() };

      if (['lotsFilled', 'lotsPartiallyFilled', 'lotsNotFilled', 'finalSpread'].includes(data.field)) {
        const stock = resolvedStocks.find(s => s.sym === e.sym);
        updated.confirmedSaving = Math.max(0, updated.lotsFilled * ((updated.estimatedSpread || 0) - updated.finalSpread) * (stock?.lot || 1));
        updated.confirmStatus = updated.lotsFilled === updated.lotsInstructed ? 'Confirmed' : (updated.lotsFilled > 0) ? 'Partially Confirmed' : 'Not Filled';
      }
      return updated;
    }));
  }, [resolvedStocks]);

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
    setLogEntries(prev => prev.map(e =>
      e.id === entryId ? { ...e, finalised: true, lastUpdated: new Date() } : e
    ));
  }, []);

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

  const value = {
    alerts, logEntries, corrections, finalisedDays, settings, stockOverrides, resolvedStocks,
    currentPage, currentTheme, currentUser, toasts, notifications,
    isLoggedIn, showTransition, apiStatus, currentMonth, nextMonth,
    setCurrentPage, toggleTheme, login, logout, completeTransition,
    sendInstruction, saveEod, saveCorrection, addCorrectionBatch, finaliseDay,
    finaliseEntry, updateDealerRemarks, setStatus, updateLogField,
    updateSettings, resetSettings, updateStock,
    addToast, removeToast, addNotification, removeNotification,
    updateAlerts, setAlerts, setApiStatus
  };

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore() {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error('useStore must be used within StoreProvider');
  return ctx;
}
