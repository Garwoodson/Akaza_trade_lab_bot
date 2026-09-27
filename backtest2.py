"""Honest backtesting engine for binary-style contracts.

Simulates CALL/PUT trades on historical candles and reports the TRUE win rate
versus the break-even win rate. No predictions, no fake numbers.
"""

import math
import random


# ---------------------------------------------------------------- indicators

def ema(values, period):
    out = [None] * len(values)
    if len(values) < period or period < 1:
        return out
    k = 2.0 / (period + 1)
    s = sum(values[:period]) / period
    out[period - 1] = s
    for i in range(period, len(values)):
        s = values[i] * k + s * (1 - k)
        out[i] = s
    return out


def sma(values, period):
    out = [None] * len(values)
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= period:
            run -= values[i - period]
        if i >= period - 1:
            out[i] = run / period
    return out


def rsi_wilder(closes, period=14):
    """Wilder's RSI. Returns list with None for warmup."""
    out = [None] * len(closes)
    if len(closes) <= period or period < 1:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    ag = gains / period
    al = losses / period
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + (d if d > 0 else 0)) / period
        al = (al * (period - 1) + (-d if d < 0 else 0)) / period
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def bollinger(closes, period=20, mult=2.0):
    mid = sma(closes, period)
    upper = [None] * len(closes)
    lower = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        w = closes[i - period + 1:i + 1]
        m = sum(w) / period
        var = sum((x - m) ** 2 for x in w) / period
        sd = math.sqrt(var)
        upper[i] = m + mult * sd
        lower[i] = m - mult * sd
    return lower, mid, upper


# ---------------------------------------------------------------- signals

def signal_ema(i, fast, slow):
    if i < 1 or fast[i] is None or slow[i] is None:
        return None
    if fast[i - 1] is None or slow[i - 1] is None:
        return None
    if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:
        return "CALL"
    if fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]:
        return "PUT"
    return None


def signal_rsi(i, rsi_vals, ob=70, os=30):
    v = rsi_vals[i]
    if v is None:
        return None
    if v >= ob:
        return "PUT"
    if v <= os:
        return "CALL"
    return None


def signal_bb(i, closes, lower, upper):
    if lower[i] is None:
        return None
    if closes[i] >= upper[i]:
        return "PUT"
    if closes[i] <= lower[i]:
        return "CALL"
    return None


def macd_vals(closes, fast=12, slow=26, signal=9):
    """MACD line and signal line, with None warmup."""
    ef, es = ema(closes, fast), ema(closes, slow)
    mline = [(a - b) if (a is not None and b is not None) else None
             for a, b in zip(ef, es)]
    compact = [v for v in mline if v is not None]
    s_ema = ema(compact, signal)
    sline = [None] * len(closes)
    j = 0
    for i, v in enumerate(mline):
        if v is None:
            continue
        sline[i] = s_ema[j]
        j += 1
    return mline, sline


def signal_macd(i, mline, sline):
    if i < 1:
        return None
    vals = (mline[i - 1], sline[i - 1], mline[i], sline[i])
    if any(v is None for v in vals):
        return None
    if mline[i - 1] <= sline[i - 1] and mline[i] > sline[i]:
        return "CALL"
    if mline[i - 1] >= sline[i - 1] and mline[i] < sline[i]:
        return "PUT"
    return None


def stoch_vals(candles, k_period=14, d_period=3):
    """Stochastic %K and %D, with None warmup."""
    k = [None] * len(candles)
    for i in range(k_period - 1, len(candles)):
        w = candles[i - k_period + 1:i + 1]
        hh = max(x["h"] for x in w)
        ll = min(x["l"] for x in w)
        rng = hh - ll
        k[i] = 50.0 if rng == 0 else 100.0 * (candles[i]["c"] - ll) / rng
    compact = [v for v in k if v is not None]
    d_sma = sma(compact, d_period)
    d = [None] * len(candles)
    j = 0
    for i, v in enumerate(k):
        if v is None:
            continue
        d[i] = d_sma[j]
        j += 1
    return k, d


def signal_stoch(i, k, d, ob=80, os=20):
    if i < 1:
        return None
    vals = (k[i - 1], d[i - 1], k[i], d[i])
    if any(v is None for v in vals):
        return None
    if k[i - 1] <= d[i - 1] and k[i] > d[i] and k[i] < os:
        return "CALL"
    if k[i - 1] >= d[i - 1] and k[i] < d[i] and k[i] > ob:
        return "PUT"
    return None


# ---------------------------------------------------------------- backtest

STRATEGIES = ("ema_cross", "rsi", "bollinger", "macd", "stoch")


def run_backtest(candles, strategy="ema_cross", strategy_params=None,
                 expiry=5, payout=0.80, stake=1.0):
    """Run a binary-contract backtest.

    candles: list of dicts with keys o,h,l,c (floats)
    expiry:  trade length in candles
    payout:  broker payout as fraction (0.80 = 80%)
    stake:   units risked per trade
    Returns dict with trades, win_rate, break-even rate, pnl, expectancy,
    max drawdown and the full trade log.
    """
    sp = strategy_params or {}
    closes = [float(c["c"]) for c in candles]
    n = len(closes)
    if n < 60:
        raise ValueError("need at least 60 candles, got %d" % n)
    if expiry < 1:
        raise ValueError("expiry must be >= 1 candle")

    if strategy == "ema_cross":
        fast_n = int(sp.get("fast", 5))
        slow_n = int(sp.get("slow", 13))
        fast = ema(closes, fast_n)
        slow = ema(closes, slow_n)
        warmup = slow_n
        sig = lambda i: signal_ema(i, fast, slow)
    elif strategy == "rsi":
        per = int(sp.get("period", 14))
        r = rsi_wilder(closes, per)
        warmup = per
        sig = lambda i, r=r, ob=float(sp.get("ob", 70)), os=float(sp.get("os", 30)): signal_rsi(i, r, ob, os)
    elif strategy == "bollinger":
        per = int(sp.get("period", 20))
        lo, _, hi = bollinger(closes, per, float(sp.get("mult", 2.0)))
        warmup = per
        sig = lambda i: signal_bb(i, closes, lo, hi)
    elif strategy == "macd":
        mf = int(sp.get("fast", 12))
        ms = int(sp.get("slow", 26))
        sg = int(sp.get("signal", 9))
        mline, sline = macd_vals(closes, mf, ms, sg)
        warmup = ms + sg
        sig = lambda i: signal_macd(i, mline, sline)
    elif strategy == "stoch":
        kp = int(sp.get("k", 14))
        dp = int(sp.get("d", 3))
        kk, dd = stoch_vals(candles, kp, dp)
        warmup = kp + dp
        ob = float(sp.get("ob", 80))
        os = float(sp.get("os", 20))
        sig = lambda i, kk=kk, dd=dd, ob=ob, os=os: signal_stoch(i, kk, dd, ob, os)
    else:
        raise ValueError("unknown strategy: %r (choose from %s)" % (strategy, STRATEGIES))

    trades = []
    equity = 0.0
    curve = [0.0]
    peak = 0.0
    max_dd = 0.0

    i = warmup
    while i < n - expiry:
        direction = sig(i)
        if direction:
            entry = closes[i]
            ex = closes[i + expiry]
            # ties count as losses (standard for binary contracts)
            win = (ex > entry) if direction == "CALL" else (ex < entry)
            pnl = stake * payout if win else -stake
            equity += pnl
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            trades.append({
                "index": i,
                "direction": direction,
                "entry": entry,
                "exit": ex,
                "win": win,
                "pnl": round(pnl, 4),
            })
            curve.append(equity)
            i += expiry  # no overlapping trades
        else:
            i += 1

    total = len(trades)
    wins = sum(1 for t in trades if t["win"])
    win_rate = (wins / total) if total else 0.0
    be = 1.0 / (1.0 + payout)  # break-even win rate
    expectancy = win_rate * payout * stake - (1 - win_rate) * stake

    return {
        "strategy": strategy,
        "candles": n,
        "expiry": expiry,
        "payout": payout,
        "stake": stake,
        "trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": win_rate,
        "be_win_rate": be,
        "pnl": round(equity, 4),
        "expectancy": round(expectancy, 4),
        "max_drawdown": round(max_dd, 4),
        "beats_breakeven": win_rate >= be and total > 0,
        "log": trades,
    }


# ---------------------------------------------------------------- data

def gen_demo_candles(n=2000, seed=42):
    """Deterministic simulated candles, clearly labeled as simulated."""
    rnd = random.Random(seed)
    candles = []
    p = 1.0850
    drift = 0.0
    for i in range(n):
        if i % 300 == 0:
            drift = (rnd.random() - 0.5) * 0.000004
        o = p
        shock = (rnd.random() + rnd.random() + rnd.random() - 1.5) * 0.0008
        c = o * (1 + drift + shock)
        h = max(o, c) * (1 + rnd.random() * 0.0004)
        l = min(o, c) * (1 - rnd.random() * 0.0004)
        candles.append({"o": o, "h": h, "l": l, "c": c})
        p = c
    return candles


def parse_csv(text):
    """Parse user-supplied candles.

    Accepts rows of: open,high,low,close (with optional leading timestamp
    column) or a single close column. Header row is auto-skipped.
    """
    candles = []
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines:
        # drop a header row if it contains non-numeric cells
        first = [p.strip() for p in lines[0].split(",")]
        try:
            [float(p) for p in first]
        except ValueError:
            lines = lines[1:]
    for ln in lines:
        parts = [p.strip() for p in ln.split(",")]
        vals = []
        for p in parts:
            try:
                vals.append(float(p))
            except ValueError:
                vals.append(None)  # e.g. a timestamp like 2026-01-01
        # drop non-numeric edge columns (timestamps, labels)
        while vals and vals[0] is None:
            vals.pop(0)
        while vals and vals[-1] is None:
            vals.pop()
        if not vals or any(v is None for v in vals):
            continue  # junk row
        if len(vals) >= 5:
            o, h, l, c = vals[1:5]  # leading col is a timestamp
        elif len(vals) == 4:
            o, h, l, c = vals
        elif len(vals) == 1:
            o = h = l = c = vals[0]
        else:
            continue
        candles.append({"o": o, "h": h, "l": l, "c": c})
    if len(candles) < 60:
        raise ValueError("need at least 60 candles, found %d" % len(candles))
    return candles
