import asyncio
import json
import websockets
from datetime import datetime

PORT = 8766
IST_OFFSET = 5.5 * 3600

def ist_now():
    from datetime import timedelta
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

async def handler(websocket):
    print("Client connected")

    # Send init with 3 stocks
    init_msg = {
        "type": "init",
        "stocks": [
            {"stock": "RELIANCE", "initial_spread": 10.0, "current_spread": 5.5, "discount_pct": 55.0, "is_contango": True, "current_fut_ltp": 2450.0, "next_fut_ltp": 2455.5, "timestamp": ist_now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]},
            {"stock": "TCS", "initial_spread": 8.0, "current_spread": 4.2, "discount_pct": 52.5, "is_contango": True, "current_fut_ltp": 3800.0, "next_fut_ltp": 3804.2, "timestamp": ist_now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]},
            {"stock": "INFY", "initial_spread": 12.0, "current_spread": 6.8, "discount_pct": 56.7, "is_contango": True, "current_fut_ltp": 1500.0, "next_fut_ltp": 1506.8, "timestamp": ist_now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]},
        ],
        "status": {"phase": "ACTIVE", "is_connected": True, "market_open": True}
    }
    await websocket.send(json.dumps(init_msg))
    print("Sent init with 3 stocks")

    await asyncio.sleep(2)

    # Send alerts for all 3
    for stock, discount, spread in [("RELIANCE", 45.5, 5.5), ("TCS", 42.5, 4.2), ("INFY", 46.7, 6.8)]:
        alert_msg = {
            "type": "alert",
            "stock": stock,
            "discount_pct": discount,
            "threshold": 40,
            "trigger_count": 1,
            "spread": spread,
            "initial_spread": spread * 2,
            "current_fut_ltp": 2000.0,
            "next_fut_ltp": 2000.0 + spread,
            "timestamp": ist_now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        }
        await websocket.send(json.dumps(alert_msg))
        print(f"Sent alert: {stock}")
        await asyncio.sleep(0.5)

    print("\nWaiting 5 seconds before expiring alerts...\n")
    await asyncio.sleep(5)

    # Expire them one by one
    for stock, spread in [("RELIANCE", 3.2), ("TCS", 2.8), ("INFY", 4.1)]:
        expired_msg = {
            "type": "alert_expired",
            "stock": stock,
            "final_spread": spread,
            "timestamp": ist_now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        }
        await websocket.send(json.dumps(expired_msg))
        print(f"Sent alert_expired: {stock}")
        await asyncio.sleep(1)

    print("\nDone. Keeping connection alive for 30 seconds...")
    await asyncio.sleep(30)

async def main():
    async with websockets.serve(handler, "127.0.0.1", PORT):
        print(f"Mock broadcaster running on ws://127.0.0.1:{PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
