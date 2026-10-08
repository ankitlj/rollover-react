import { useEffect, useRef, useCallback } from 'react';

const WS_URL = 'wss://rollover-react-production.up.railway.app';
const HEALTH_API_URL = 'https://rollover-react-production-a68d.up.railway.app/health';
const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 30000;
const PING_INTERVAL_MS = 20000;
const STALE_THRESHOLD_MS = 60000;
const STALE_CHECK_INTERVAL_MS = 10000;
const HEALTH_STORAGE_KEY = 'rs-connection-health';
const MAX_HEALTH_EVENTS = 500;
const HEALTH_SYNC_INTERVAL_MS = 300000;

interface HealthEvent {
  event: string;
  timestamp: string;
  details?: Record<string, unknown>;
}

function logHealthEvent(event: string, details?: Record<string, unknown>) {
  try {
    const stored = localStorage.getItem(HEALTH_STORAGE_KEY);
    let events: HealthEvent[] = stored ? JSON.parse(stored) : [];

    events.push({
      event,
      timestamp: new Date().toISOString(),
      ...(details ? { details } : {}),
    });

    if (events.length > MAX_HEALTH_EVENTS) {
      events = events.slice(-MAX_HEALTH_EVENTS);
    }

    localStorage.setItem(HEALTH_STORAGE_KEY, JSON.stringify(events));
  } catch {
    // ignore storage errors
  }
}

function syncHealthToBackend() {
  try {
    const stored = localStorage.getItem(HEALTH_STORAGE_KEY);
    if (!stored) return;

    const events = JSON.parse(stored);
    fetch(HEALTH_API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events, synced_at: new Date().toISOString() }),
    }).catch(() => {
      // ignore sync errors
    });
  } catch {
    // ignore errors
  }
}

export interface WsStockData {
  stock: string;
  initial_spread: number;
  current_spread: number | null;
  discount_pct: number | null;
  is_contango: boolean | null;
  current_fut_ltp: number | null;
  next_fut_ltp: number | null;
  timestamp: string | null;
}

export interface WsStatus {
  phase: string;
  is_connected: boolean;
  market_open: boolean;
}

export interface WsAlertData {
  stock: string;
  discount_pct: number;
  threshold: number;
  trigger_count: number;
  spread: number;
  initial_spread: number;
  current_fut_ltp: number;
  next_fut_ltp: number;
  timestamp: string;
}

export interface WsAlertExpiredData {
  stock: string;
  final_spread: number;
  timestamp: string;
}

export interface WsExpiredAlertData {
  stock: string;
  final_spread?: number;
  spread?: number;
  timestamp?: string;
  expired_at?: string;
  initial_spread?: number;
  discount_pct?: number;
}

export interface WsExpiries {
  current: string | null;
  next: string | null;
}

interface UseAlgoWSHandlers {
  onInit: (stocks: WsStockData[], status: WsStatus, expiries: WsExpiries | null, activeAlerts: WsAlertData[], expiredAlerts: WsExpiredAlertData[]) => void;
  onSnapshot: (stocks: WsStockData[], timestamp: string) => void;
  onAlert: (data: WsAlertData) => void;
  onAlertExpired: (data: WsAlertExpiredData) => void;
  onStatus: (status: WsStatus) => void;
  onConnectionChange: (status: 'connected' | 'reconnecting' | 'disconnected') => void;
}

export function useAlgoWS(handlers: UseAlgoWSHandlers) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<number>(0);
  const pingTimer = useRef<number>(0);
  const healthSyncTimer = useRef<number>(0);
  const staleWatchTimer = useRef<number>(0);
  const lastMessageTime = useRef<number>(Date.now());
  const handlersRef = useRef(handlers);
  const mountedRef = useRef(true);

  handlersRef.current = handlers;

  const clearTimers = useCallback(() => {
    if (pingTimer.current) {
      clearInterval(pingTimer.current);
      pingTimer.current = 0;
    }
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = 0;
    }
    if (healthSyncTimer.current) {
      clearInterval(healthSyncTimer.current);
      healthSyncTimer.current = 0;
    }
    if (staleWatchTimer.current) {
      clearInterval(staleWatchTimer.current);
      staleWatchTimer.current = 0;
    }
  }, []);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) { ws.close(); return; }
        reconnectAttempt.current = 0;
        lastMessageTime.current = Date.now();
        handlersRef.current.onConnectionChange('connected');
        logHealthEvent('connected');

        pingTimer.current = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, PING_INTERVAL_MS);

        staleWatchTimer.current = window.setInterval(() => {
          if (!mountedRef.current) return;
          if (Date.now() - lastMessageTime.current > STALE_THRESHOLD_MS) {
            logHealthEvent('stale_connection', { silent_ms: Date.now() - lastMessageTime.current });
            ws.close();
          }
        }, STALE_CHECK_INTERVAL_MS);
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        lastMessageTime.current = Date.now();
        try {
          const msg = JSON.parse(event.data);
          logHealthEvent('message_received', { type: msg.type });
          switch (msg.type) {
            case 'init': {
              const freshActives: WsAlertData[] = [];
              const staleActives: WsAlertData[] = [];
              const now = Date.now();
              (Array.isArray(msg.active_alerts) ? msg.active_alerts : []).forEach((a: WsAlertData) => {
                const age = a.timestamp ? (now - new Date(a.timestamp).getTime()) / 1000 : 0;
                if (age > 90) {
                  staleActives.push(a);
                } else {
                  freshActives.push(a);
                }
              });
              handlersRef.current.onInit(
                msg.stocks,
                msg.status,
                msg.expiries ?? null,
                freshActives,
                Array.isArray(msg.expired_alerts) ? msg.expired_alerts : [],
              );
              staleActives.forEach((a) => {
                handlersRef.current.onAlertExpired({
                  stock: a.stock,
                  final_spread: a.spread,
                  timestamp: a.timestamp,
                });
              });
              break;
            }
            case 'snapshot':
              handlersRef.current.onSnapshot(msg.stocks, msg.timestamp);
              break;
            case 'alert':
              handlersRef.current.onAlert(msg);
              break;
            case 'alert_expired':
              handlersRef.current.onAlertExpired(msg);
              break;
            case 'status':
              handlersRef.current.onStatus(msg);
              break;
            case 'pong':
              break;
          }
        } catch (e) {
          logHealthEvent('message_parse_error', { error: String(e) });
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        if (pingTimer.current) {
          clearInterval(pingTimer.current);
          pingTimer.current = 0;
        }
        if (staleWatchTimer.current) {
          clearInterval(staleWatchTimer.current);
          staleWatchTimer.current = 0;
        }
        handlersRef.current.onConnectionChange('disconnected');
        logHealthEvent('disconnected');

        if (mountedRef.current) {
          const delay = Math.min(
            RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt.current),
            RECONNECT_MAX_MS,
          );
          reconnectAttempt.current++;
          handlersRef.current.onConnectionChange('reconnecting');
          logHealthEvent('reconnecting', { attempt: reconnectAttempt.current, delay_ms: delay });
          reconnectTimer.current = window.setTimeout(() => {
            if (mountedRef.current) connect();
          }, delay);
        }
      };

      ws.onerror = () => {
        logHealthEvent('connection_error');
      };
    } catch (e) {
      logHealthEvent('connect_exception', { error: String(e) });
      if (!mountedRef.current) return;
      const delay = Math.min(
        RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt.current),
        RECONNECT_MAX_MS,
      );
      reconnectAttempt.current++;
      handlersRef.current.onConnectionChange('reconnecting');
      logHealthEvent('reconnecting', { attempt: reconnectAttempt.current, delay_ms: delay });
      reconnectTimer.current = window.setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    healthSyncTimer.current = window.setInterval(() => {
      if (mountedRef.current) {
        syncHealthToBackend();
      }
    }, HEALTH_SYNC_INTERVAL_MS);

    return () => {
      mountedRef.current = false;
      clearTimers();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect, clearTimers]);
}
