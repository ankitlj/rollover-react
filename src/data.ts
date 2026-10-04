import type { Stock, Alert, LogEntry, Settings } from './types';

export const STOCKS: Stock[] = [
  { sym: 'RELIANCE', lot: 500, price: 1414, sector: 'Energy', lotsHeld: 145 },
  { sym: 'ADANIPORTS', lot: 475, price: 1255, sector: 'Infrastructure', lotsHeld: 435 },
  { sym: 'ASTRAL', lot: 425, price: 1335, sector: 'Building Materials', lotsHeld: 50 },
  { sym: 'GRASIM', lot: 250, price: 2726, sector: 'Textiles', lotsHeld: 62 },
  { sym: 'HCLTECH', lot: 350, price: 1567, sector: 'IT', lotsHeld: 30 },
  { sym: 'HDFCBANK', lot: 550, price: 965, sector: 'Banking', lotsHeld: 6 },
  { sym: 'INFOSYS', lot: 400, price: 1500, sector: 'IT', lotsHeld: 53 },
  { sym: 'JSWSTEEL', lot: 675, price: 1021, sector: 'Metals', lotsHeld: 64 },
  { sym: 'MARUTI', lot: 50, price: 12257, sector: 'Auto', lotsHeld: 15 },
  { sym: 'TCS', lot: 175, price: 3472, sector: 'IT', lotsHeld: 30 },
  { sym: 'TATASTEEL', lot: 2750, price: 140, sector: 'Metals', lotsHeld: 21 },
  { sym: 'BAJFINANCE', lot: 750, price: 858, sector: 'Finance', lotsHeld: 1 },
  { sym: 'SBIN', lot: 750, price: 790, sector: 'Banking', lotsHeld: 7 },
  { sym: 'LT', lot: 175, price: 3325, sector: 'Construction', lotsHeld: 46 },
  { sym: 'HAL', lot: 150, price: 4499, sector: 'Defence', lotsHeld: 40 },
  { sym: 'BANDHANBANK', lot: 3600, price: 169, sector: 'Banking', lotsHeld: 2 },
  { sym: 'AMBUJACEM', lot: 1050, price: 538, sector: 'Cement', lotsHeld: 130 },
  { sym: 'ADANIENT', lot: 309, price: 2279, sector: 'Energy', lotsHeld: 80 },
  { sym: 'INDUSINDBANK', lot: 700, price: 835, sector: 'Banking', lotsHeld: 25 },
];

export const EXPIRY_CUR = '28 AUG 2025';
export const EXPIRY_NEXT = '25 SEP 2025';
export const EXPIRY_CUR_DATE = new Date('2025-08-28');
export const EXPIRY_NEXT_DATE = new Date('2025-09-25');
export const RS = String.fromCharCode(8377);

export const DEFAULT_SETTINGS: Settings = {
  tradingDays: 20,
  fyMonths: 12,
  refreshInterval: 10,
  demoLabel: 'yes',
};

export function genAlerts(): Alert[] {
  return [];
}

export function createInitialLogEntries(): LogEntry[] {
  return [];
}
