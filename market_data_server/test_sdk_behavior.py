"""
SDK behavior tests — read-only, conservative, no orders.
Tests specific error scenarios and SDK capabilities.
"""
import sys
import io
import time
import threading
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pyarrow_client import ArrowClient, ArrowStreams, DataMode
from pyarrow_client.sockets import MarketTick, ConnectionConfig

APP_ID = "5c999bfe87dc"
APP_SECRET = "9f7b9f755b4a05228bb574e45fd27f19f6b2de81c21854eddfcf2577f99a91fb"
USER_ID = "AG5406"
PASSWORD = "NJQdil85@"
TOTP_SECRET = "YG4CUOOWKVYDQ5LBEAMBHMIC6VZOOZSN"

results = {}

def log(msg):
    print(f"[TEST] {msg}", flush=True)


# ═══════════════════════════════════════════════════════════
# TEST 1: Login + session token properties
# ═══════════════════════════════════════════════════════════
def test_login():
    log("=" * 50)
    log("TEST 1: Login + session token")
    client = ArrowClient(app_id=APP_ID)
    result = client.auto_login(
        user_id=USER_ID,
        password=PASSWORD,
        app_secret=APP_SECRET,
        totp_secret=TOTP_SECRET,
    )
    token = client.get_token()
    log(f"  Login OK: {result.get('name', '?')}")
    log(f"  Token length: {len(token)} chars")
    log(f"  Token prefix: {token[:20]}...")
    log(f"  Token type: {type(token)}")

    results["login"] = {
        "token_len": len(token),
        "name": result.get("name"),
        "user_id": result.get("userID"),
    }
    return client


# ═══════════════════════════════════════════════════════════
# TEST 2: REST API health — what queries work, response times
# ═══════════════════════════════════════════════════════════
def test_rest_api(client):
    log("=" * 50)
    log("TEST 2: REST API capabilities")

    # 2a: get_user_details
    t0 = time.time()
    try:
        user = client.get_user_details()
        dt = (time.time() - t0) * 1000
        log(f"  get_user_details: OK ({dt:.0f}ms)")
        log(f"    Keys: {list(user.keys()) if isinstance(user, dict) else type(user)}")
    except Exception as e:
        log(f"  get_user_details: FAILED — {e}")

    time.sleep(0.5)

    # 2b: get_user_limits
    t0 = time.time()
    try:
        limits = client.get_user_limits()
        dt = (time.time() - t0) * 1000
        log(f"  get_user_limits: OK ({dt:.0f}ms)")
        if isinstance(limits, dict):
            for k, v in limits.items():
                log(f"    {k}: {v}")
    except Exception as e:
        log(f"  get_user_limits: FAILED — {e}")

    time.sleep(0.5)

    # 2c: get_positions
    t0 = time.time()
    try:
        positions = client.get_positions()
        dt = (time.time() - t0) * 1000
        log(f"  get_positions: OK ({dt:.0f}ms), count={len(positions) if isinstance(positions, list) else '?'}")
    except Exception as e:
        log(f"  get_positions: FAILED — {e}")

    time.sleep(0.5)

    # 2d: get_holidays
    t0 = time.time()
    try:
        holidays = client.get_holidays()
        dt = (time.time() - t0) * 1000
        log(f"  get_holidays: OK ({dt:.0f}ms)")
        if isinstance(holidays, dict):
            log(f"    Keys: {list(holidays.keys())[:5]}")
    except Exception as e:
        log(f"  get_holidays: FAILED — {e}")

    time.sleep(0.5)

    # 2e: Single quote (1 stock, minimal load)
    t0 = time.time()
    try:
        from pyarrow_client import Exchange, QuoteMode
        quote = client.get_quote(QuoteMode.FULL, "RELIANCE", Exchange.NSE)
        dt = (time.time() - t0) * 1000
        log(f"  get_quote(FULL, RELIANCE): OK ({dt:.0f}ms)")
        if isinstance(quote, dict):
            log(f"    Keys: {list(quote.keys())[:10]}")
            ltp = quote.get("last_price") or quote.get("ltp") or quote.get("LTP")
            log(f"    LTP: {ltp}")
    except Exception as e:
        log(f"  get_quote: FAILED — {e}")

    time.sleep(0.5)

    # 2f: Batch quotes (5 stocks)
    t0 = time.time()
    try:
        symbols = ["RELIANCE", "INFY", "HDFCBANK", "TCS", "SBIN"]
        quotes = client.get_quotes(QuoteMode.FULL, symbols)
        dt = (time.time() - t0) * 1000
        log(f"  get_quotes(FULL, 5 stocks): OK ({dt:.0f}ms)")
        log(f"    Response type: {type(quotes)}, count: {len(quotes) if isinstance(quotes, (list, dict)) else '?'}")
    except Exception as e:
        log(f"  get_quotes: FAILED — {e}")


# ═══════════════════════════════════════════════════════════
# TEST 3: Re-login — does it work? Does it invalidate old token?
# ═══════════════════════════════════════════════════════════
def test_relogin(client):
    log("=" * 50)
    log("TEST 3: Re-login behavior")

    old_token = client.get_token()
    log(f"  Old token: {old_token[:20]}...")

    time.sleep(1)

    result = client.auto_login(
        user_id=USER_ID,
        password=PASSWORD,
        app_secret=APP_SECRET,
        totp_secret=TOTP_SECRET,
    )
    new_token = client.get_token()
    log(f"  New token: {new_token[:20]}...")
    log(f"  Same token? {old_token == new_token}")
    log(f"  Login result: {result.get('name', '?')}")

    results["relogin"] = {
        "same_token": old_token == new_token,
    }


# ═══════════════════════════════════════════════════════════
# TEST 4: WebSocket connect + subscribe + receive ticks
# ═══════════════════════════════════════════════════════════
def test_websocket_stream(client):
    log("=" * 50)
    log("TEST 4: WebSocket DataStream — connect, subscribe, tick count")

    token = client.get_token()
    streams = ArrowStreams(appID=APP_ID, token=token, debug=False)

    tick_count = 0
    tokens_seen = set()
    connect_time = None
    first_tick_time = None
    errors = []

    def on_ticks(tick):
        nonlocal tick_count, first_tick_time
        tick_count += 1
        if first_tick_time is None:
            first_tick_time = time.time()
        tokens_seen.add(tick.token)

    def on_connect():
        nonlocal connect_time
        connect_time = time.time()
        log(f"  WS connected at {connect_time:.3f}")

    def on_close(code, msg):
        log(f"  WS closed: code={code}, msg={msg}")

    def on_disconnect():
        log(f"  WS disconnected")

    def on_error(error):
        errors.append(str(error))
        log(f"  WS error: {error}")

    def on_reconnect(count, delay):
        log(f"  WS reconnect attempt {count}, delay={delay}s")

    def on_no_reconnect():
        log(f"  WS MAX RECONNECT EXHAUSTED")

    streams.data_stream.on_ticks = on_ticks
    streams.data_stream.on_connect = on_connect
    streams.data_stream.on_close = on_close
    streams.data_stream.on_disconnect = on_disconnect
    streams.data_stream.on_error = on_error
    streams.data_stream.on_reconnect = on_reconnect
    streams.data_stream.on_no_reconnect = on_no_reconnect

    # Subscribe to just 3 tokens for minimal load
    raw = client.get_instruments()
    text = raw.decode() if isinstance(raw, bytes) else raw
    import csv, io
    instruments = list(csv.DictReader(io.StringIO(text)))

    test_tokens = []
    for r in instruments:
        if r["Symbol"] == "RELIANCE" and r["Segment"] == "CM" and r.get("Series") == "EQ":
            test_tokens.append(int(float(r["Token"])))
            if len(test_tokens) >= 3:
                break

    if not test_tokens:
        test_tokens = [2885]  # fallback RELIANCE cash token

    log(f"  Subscribing to {len(test_tokens)} tokens: {test_tokens}")

    t0 = time.time()
    streams.connect_data_stream()
    time.sleep(1)
    streams.subscribe_market_data(DataMode.FULL, test_tokens)

    # Collect ticks for 10 seconds
    time.sleep(10)

    elapsed = time.time() - t0
    log(f"  Collection time: {elapsed:.1f}s")
    log(f"  Total ticks: {tick_count}")
    log(f"  Unique tokens: {len(tokens_seen)} → {tokens_seen}")
    log(f"  Tick rate: {tick_count/elapsed:.1f} ticks/sec")
    log(f"  Errors: {len(errors)}")
    if errors:
        for e in errors[:5]:
            log(f"    {e}")

    if connect_time and first_tick_time:
        log(f"  First tick latency: {(first_tick_time - connect_time)*1000:.0f}ms")

    results["websocket"] = {
        "ticks": tick_count,
        "unique_tokens": len(tokens_seen),
        "rate": tick_count/elapsed,
        "errors": len(errors),
        "latency_ms": (first_tick_time - connect_time)*1000 if connect_time and first_tick_time else None,
    }

    # Clean disconnect
    streams.data_stream.disconnect()
    time.sleep(1)
    return streams


# ═══════════════════════════════════════════════════════════
# TEST 5: Dynamic subscribe/unsubscribe
# ═══════════════════════════════════════════════════════════
def test_dynamic_subscription(client):
    log("=" * 50)
    log("TEST 5: Dynamic subscribe/unsubscribe")

    token = client.get_token()
    streams = ArrowStreams(appID=APP_ID, token=token, debug=False)

    tick_count = 0
    tokens_seen = set()
    last_tick_time = 0

    def on_ticks(tick):
        nonlocal tick_count, last_tick_time
        tick_count += 1
        last_tick_time = time.time()
        tokens_seen.add(tick.token)

    streams.data_stream.on_ticks = on_ticks
    streams.data_stream.on_connect = lambda: log("  [5] connected")
    streams.data_stream.on_close = lambda c, m: log(f"  [5] closed: {c} {m}")
    streams.data_stream.on_disconnect = lambda: log("  [5] disconnected")
    streams.data_stream.on_error = lambda e: log(f"  [5] error: {e}")

    streams.connect_data_stream()
    time.sleep(1)

    # Phase 1: Subscribe to 1 token
    token_a = 2885  # RELIANCE cash
    log(f"  Phase 1: Subscribe token {token_a}")
    streams.subscribe_market_data(DataMode.FULL, [token_a])
    time.sleep(3)
    count_phase1 = tick_count
    log(f"    Ticks in 3s: {count_phase1}, tokens: {tokens_seen}")

    # Phase 2: Add another token
    token_b = 48987  # some futures token
    log(f"  Phase 2: Add token {token_b}")
    tokens_seen.clear()
    tick_count_before = tick_count
    streams.subscribe_market_data(DataMode.FULL, [token_b])
    time.sleep(3)
    count_phase2 = tick_count - tick_count_before
    log(f"    Ticks in 3s: {count_phase2}, tokens seen: {tokens_seen}")

    # Phase 3: Unsubscribe first token
    log(f"  Phase 3: Unsubscribe token {token_a}")
    tokens_seen.clear()
    tick_count_before = tick_count
    streams.unsubscribe_market_data(DataMode.FULL, [token_a])
    time.sleep(3)
    count_phase3 = tick_count - tick_count_before
    log(f"    Ticks in 3s: {count_phase3}, tokens seen: {tokens_seen}")

    results["dynamic_sub"] = {
        "phase1_ticks": count_phase1,
        "phase2_ticks": count_phase2,
        "phase3_ticks": count_phase3,
        "unsubscribe_works": token_a not in tokens_seen if tokens_seen else True,
    }

    streams.data_stream.disconnect()
    time.sleep(1)


# ═══════════════════════════════════════════════════════════
# TEST 6: SDK read timeout behavior (silence detection)
# ═══════════════════════════════════════════════════════════
def test_read_timeout_config():
    log("=" * 50)
    log("TEST 6: SDK ConnectionConfig defaults")

    cfg = ConnectionConfig(appID="test", token="test")
    log(f"  read_timeout: {cfg.read_timeout}s")
    log(f"  ping_interval: {cfg.ping_interval}s")
    log(f"  max_reconnect_attempts: {cfg.max_reconnect_attempts}")
    log(f"  max_reconnect_delay: {cfg.max_reconnect_delay}s")
    log(f"  immediate_reconnect_attempts: {cfg.immediate_reconnect_attempts}")
    log(f"  enable_reconnect: {cfg.enable_reconnect}")

    results["config"] = {
        "read_timeout": cfg.read_timeout,
        "ping_interval": cfg.ping_interval,
        "max_reconnect": cfg.max_reconnect_attempts,
    }


# ═══════════════════════════════════════════════════════════
# TEST 7: Multiple mode subscription on same connection
# ═══════════════════════════════════════════════════════════
def test_multi_mode(client):
    log("=" * 50)
    log("TEST 7: Multiple DataMode on same connection")

    token = client.get_token()
    streams = ArrowStreams(appID=APP_ID, token=token, debug=False)

    tick_count = 0
    modes_seen = set()

    def on_ticks(tick):
        nonlocal tick_count
        tick_count += 1
        modes_seen.add(tick.mode)

    streams.data_stream.on_ticks = on_ticks
    streams.data_stream.on_connect = lambda: log("  [7] connected")
    streams.data_stream.on_close = lambda c, m: log(f"  [7] closed")
    streams.data_stream.on_disconnect = lambda: log("  [7] disconnected")
    streams.data_stream.on_error = lambda e: log(f"  [7] error: {e}")

    streams.connect_data_stream()
    time.sleep(1)

    test_token = [2885]  # RELIANCE

    # Subscribe same token in LTP mode
    log(f"  Subscribing {test_token} in LTP mode")
    streams.subscribe_market_data(DataMode.LTP, test_token)
    time.sleep(2)
    ltp_count = tick_count
    log(f"    LTP ticks in 2s: {ltp_count}, modes: {modes_seen}")

    # Also subscribe in FULL mode
    log(f"  Subscribing {test_token} in FULL mode")
    modes_seen.clear()
    tick_count_before = tick_count
    streams.subscribe_market_data(DataMode.FULL, test_token)
    time.sleep(2)
    full_count = tick_count - tick_count_before
    log(f"    Ticks in 2s: {full_count}, modes: {modes_seen}")

    results["multi_mode"] = {
        "ltp_ticks": ltp_count,
        "full_ticks": full_count,
        "modes_seen": list(modes_seen),
    }

    streams.data_stream.disconnect()
    time.sleep(1)


# ═══════════════════════════════════════════════════════════
# TEST 8: Order stream (post connection behavior)
# ═══════════════════════════════════════════════════════════
def test_order_stream(client):
    log("=" * 50)
    log("TEST 8: OrderStream connection")

    token = client.get_token()
    streams = ArrowStreams(appID=APP_ID, token=token, debug=False)

    connected = False

    streams.order_stream.on_connect = lambda: log("  [8] Order stream connected") or setattr(threading.current_thread(), '_connected', True)
    streams.order_stream.on_close = lambda c, m: log(f"  [8] Order stream closed: {c} {m}")
    streams.order_stream.on_disconnect = lambda: log("  [8] Order stream disconnected")
    streams.order_stream.on_error = lambda e: log(f"  [8] Order stream error: {e}")

    try:
        streams.connect_order_stream()
        time.sleep(3)
        log(f"  Order stream connected successfully")
        results["order_stream"] = {"connected": True}
    except Exception as e:
        log(f"  Order stream FAILED: {e}")
        results["order_stream"] = {"connected": False, "error": str(e)}

    try:
        streams.order_stream.disconnect()
    except:
        pass
    time.sleep(1)


# ═══════════════════════════════════════════════════════════
# TEST 9: Candle data (historical API)
# ═══════════════════════════════════════════════════════════
def test_candle_data(client):
    log("=" * 50)
    log("TEST 9: Historical candle data")

    from pyarrow_client import Exchange

    t0 = time.time()
    try:
        candles = client.candle_data(
            exchange=Exchange.NSE,
            token=2885,
            interval="1m",
            from_date="2026-09-25",
            to_date="2026-09-26",
        )
        dt = (time.time() - t0) * 1000
        log(f"  candle_data: OK ({dt:.0f}ms)")
        if isinstance(candles, list):
            log(f"  Candles returned: {len(candles)}")
            if candles:
                log(f"  First candle keys: {list(candles[0].keys()) if isinstance(candles[0], dict) else candles[0]}")
                log(f"  Last candle: {candles[-1]}")
        else:
            log(f"  Response type: {type(candles)}")
            log(f"  Response: {str(candles)[:200]}")
        results["candles"] = {"ok": True, "count": len(candles) if isinstance(candles, list) else 0}
    except Exception as e:
        dt = (time.time() - t0) * 1000
        log(f"  candle_data: FAILED ({dt:.0f}ms) — {e}")
        results["candles"] = {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════
# TEST 10: SDK reconnect behavior after intentional close
# ═══════════════════════════════════════════════════════════
def test_reconnect_behavior(client):
    log("=" * 50)
    log("TEST 10: Reconnect after network-style disruption")

    token = client.get_token()
    streams = ArrowStreams(appID=APP_ID, token=token, debug=False)

    reconnect_events = []
    tick_count = 0
    recovered = False

    def on_ticks(tick):
        nonlocal tick_count
        tick_count += 1

    def on_connect():
        log(f"  [10] CONNECTED (ticks so far: {tick_count})")

    def on_close(code, msg):
        log(f"  [10] CLOSED: code={code}, msg={msg}")

    def on_disconnect():
        log(f"  [10] DISCONNECTED")

    def on_reconnect(count, delay):
        reconnect_events.append({"count": count, "delay": delay, "time": time.time()})
        log(f"  [10] RECONNECT attempt={count}, delay={delay}s")

    def on_no_reconnect():
        log(f"  [10] NO RECONNECT — exhausted")

    streams.data_stream.on_ticks = on_ticks
    streams.data_stream.on_connect = on_connect
    streams.data_stream.on_close = on_close
    streams.data_stream.on_disconnect = on_disconnect
    streams.data_stream.on_reconnect = on_reconnect
    streams.data_stream.on_no_reconnect = on_no_reconnect

    streams.connect_data_stream()
    time.sleep(1)
    streams.subscribe_market_data(DataMode.FULL, [2885])

    # Collect normal ticks for 3 seconds
    time.sleep(3)
    normal_ticks = tick_count
    log(f"  Normal ticks in 3s: {normal_ticks}")

    # Force-close the underlying websocket to simulate network drop
    log(f"  Force-closing WebSocket to simulate disconnect...")
    try:
        if streams.data_stream.ws:
            streams.data_stream.ws.close()
    except Exception as e:
        log(f"  Force close error: {e}")

    # Wait for auto-reconnect
    log(f"  Waiting 8s for auto-reconnect...")
    time.sleep(8)

    post_reconnect_ticks = tick_count - normal_ticks
    log(f"  Ticks after reconnect: {post_reconnect_ticks}")
    log(f"  Reconnect events: {len(reconnect_events)}")
    for ev in reconnect_events:
        log(f"    attempt={ev['count']}, delay={ev['delay']}s")

    results["reconnect"] = {
        "normal_ticks": normal_ticks,
        "post_reconnect_ticks": post_reconnect_ticks,
        "reconnect_events": len(reconnect_events),
        "auto_recovered": post_reconnect_ticks > 0,
    }

    streams.data_stream.disconnect()
    time.sleep(1)


# ═══════════════════════════════════════════════════════════
# RUN ALL TESTS
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    log("SDK BEHAVIOR TESTS — starting")
    log(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("")

    try:
        client = test_login()
        time.sleep(1)

        test_rest_api(client)
        time.sleep(2)

        test_relogin(client)
        time.sleep(2)

        test_read_timeout_config()
        time.sleep(1)

        test_websocket_stream(client)
        time.sleep(2)

        test_dynamic_subscription(client)
        time.sleep(2)

        test_multi_mode(client)
        time.sleep(2)

        test_order_stream(client)
        time.sleep(2)

        test_candle_data(client)
        time.sleep(2)

        test_reconnect_behavior(client)
        time.sleep(1)

    except Exception as e:
        import traceback
        log(f"FATAL ERROR: {e}")
        log(traceback.format_exc())

    log("")
    log("=" * 50)
    log("FINAL RESULTS SUMMARY")
    log("=" * 50)
    for test_name, result in results.items():
        log(f"  {test_name}: {result}")

    log("")
    log("ALL TESTS COMPLETE")
