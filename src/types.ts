export interface Stock {
  sym: string;
  lot: number;
  price: number;
  sector: string;
  lotsHeld: number;
}

export interface Alert {
  id: string;
  sym: string;
  sector: string;
  lot?: number;
  price?: number;
  initial: number;
  current: number;
  spreadAtSignal?: number;
  discount: number;
  lotsAvailable: number;
  ageSec: number;
  expiryDays: number;
  lastUpdated: Date;
  status: string;
  executed?: boolean;
}

export interface LogEntry {
  id: string;
  alertId?: string;
  date: string;
  sym: string;
  sector: string;
  lotSize?: number;
  price?: number;
  expiry: string;
  lotsHeld: number;
  lotsInstructed: number;
  lotsFilled: number;
  lotsPartiallyFilled: number;
  lotsNotFilled: number;
  pendingLots: number;
  avgFillPrice: number;
  finalSpread: number;
  confirmedSaving: number;
  confirmStatus: string;
  dealerRemarks: string;
  lastUpdated: Date;
  estimatedSpread?: number;
  estimatedSaving?: number;
  missedSaving?: number;
  instructionTimestamp?: string;
  finalised: boolean;
}

export interface Correction {
  id: string;
  date: string;
  entryId: string;
  stock: string;
  field: string;
  oldValue: unknown;
  newValue: unknown;
  reason: string;
  timestamp: string;
}

export interface Settings {
  tradingDays: number;
  fyMonths: number;
  refreshInterval: number;
  demoLabel: string;
}

export interface Toast {
  id: string;
  type: 'success' | 'warning' | 'error' | 'info';
  title: string;
  detail?: string;
}

export interface Notification {
  id: string;
  type: 'success' | 'warning' | 'error' | 'info';
  title: string;
  msg: string;
}

export type PageId = 'alerts' | 'rollover' | 'recon' | 'settings';
