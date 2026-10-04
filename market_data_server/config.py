import os
from datetime import timedelta, timezone
from pathlib import Path

APP_ID = os.getenv("ARROW_APP_ID", "")
APP_SECRET = os.getenv("ARROW_APP_SECRET", "")
USER_ID = os.getenv("ARROW_USER_ID", "")
PASSWORD = os.getenv("ARROW_PASSWORD", "")
TOTP_SECRET = os.getenv("ARROW_TOTP_SECRET", "")

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 20
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 0

STOCKS = [
    {"sym": "RELIANCE", "lot": 500},
    {"sym": "ADANIPORTS", "lot": 475},
    {"sym": "ASTRAL", "lot": 425},
    {"sym": "GRASIM", "lot": 250},
    {"sym": "HCLTECH", "lot": 350},
    {"sym": "HDFCBANK", "lot": 550},
    {"sym": "INFOSYS", "lot": 400},
    {"sym": "JSWSTEEL", "lot": 675},
    {"sym": "MARUTI", "lot": 50},
    {"sym": "TCS", "lot": 175},
    {"sym": "TATASTEEL", "lot": 2750},
    {"sym": "BAJFINANCE", "lot": 750},
    {"sym": "SBIN", "lot": 750},
    {"sym": "LT", "lot": 175},
    {"sym": "HAL", "lot": 150},
    {"sym": "BANDHANBANK", "lot": 3600},
    {"sym": "AMBUJACEM", "lot": 1050},
    {"sym": "ADANIENT", "lot": 309},
    {"sym": "INDUSINDBK", "lot": 700},
]

STOCK_SYMBOLS = [s["sym"] for s in STOCKS]
STOCK_LOT_MAP = {s["sym"]: s["lot"] for s in STOCKS}

REPORT_DIR = Path(__file__).parent / "reports"
LOG_DIR = Path(__file__).parent / "logs"

TICK_BATCH_BROADCAST_MS = 50
RECONNECT_SETTLE_SECONDS = 6.0
RECOVERY_DELAY_SECONDS = 2.0

IST = timezone(timedelta(hours=5, minutes=30))
