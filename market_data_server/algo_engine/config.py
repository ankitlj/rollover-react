from datetime import timedelta, timezone

STOCK_CONFIG = {
    "RELIANCE":     {"lot": 500,  "threshold": 35},
    "ADANIPORTS":   {"lot": 475,  "threshold": 35},
    "AMBUJACEM":    {"lot": 1050, "threshold": 35},
    "ASTRAL":       {"lot": 425,  "threshold": 40},
    "GRASIM":       {"lot": 250,  "threshold": 40},
    "HCLTECH":      {"lot": 350,  "threshold": 40},
    "HDFCBANK":     {"lot": 550,  "threshold": 40},
    "INFOSYS":      {"lot": 400,  "threshold": 40},
    "JSWSTEEL":     {"lot": 675,  "threshold": 40},
    "MARUTI":       {"lot": 50,   "threshold": 40},
    "TCS":          {"lot": 175,  "threshold": 40},
    "TATASTEEL":    {"lot": 2750, "threshold": 40},
    "BAJFINANCE":   {"lot": 750,  "threshold": 40},
    "SBIN":         {"lot": 750,  "threshold": 40},
    "LT":           {"lot": 175,  "threshold": 40},
    "HAL":          {"lot": 150,  "threshold": 40},
    "BANDHANBANK":  {"lot": 3600, "threshold": 40},
    "ADANIENT":     {"lot": 309,  "threshold": 40},
    "INDUSINDBK":   {"lot": 700,  "threshold": 40},
}

THRESHOLDS = {sym: cfg["threshold"] for sym, cfg in STOCK_CONFIG.items()}

INITIAL_SPREADS = {
    "RELIANCE": 6.20,
    "ADANIPORTS": 14.20,
    "AMBUJACEM": 2.50,
    "ASTRAL": -1.70,
    "GRASIM": 23.90,
    "HCLTECH": 7.50,
    "HDFCBANK": 3.55,
    "INFOSYS": 5.30,
    "JSWSTEEL": 5.00,
    "MARUTI": 54.00,
    "TCS": 10.10,
    "TATASTEEL": 1.11,
    "BAJFINANCE": 6.40,
    "SBIN": 4.70,
    "LT": 22.20,
    "HAL": 27.10,
    "BANDHANBANK": 1.19,
    "ADANIENT": 23.90,
    "INDUSINDBK": 3.50,
}

STOCK_COUNT = len(STOCK_CONFIG)
TOTAL_TOKENS = STOCK_COUNT * 3

FRESHNESS_WINDOW_MS = 500
SPREAD_FRESHNESS_SECONDS = 60
SAMPLE_INTERVAL_SECONDS = 60

WARMUP_HOUR = 9
WARMUP_MINUTE = 20
CLOSE_HOUR = 15
CLOSE_MINUTE = 0

IST = timezone(timedelta(hours=5, minutes=30))

WS_URI = "ws://127.0.0.1:8765"
