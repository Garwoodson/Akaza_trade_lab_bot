#!/usr/bin/env python3
"""Telegram bot: a free backtesting tool.

Honest backtests on historical data. No subscriptions, no payments.
Setup: see SETUP.md. Requires env var BOT_TOKEN. Runs with polling.
"""

import logging
import os

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import backtest as bt

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

STRATEGY_LABELS = {
    "ema_cross": "EMA crossover",
    "rsi": "RSI reversal",
    "bollinger": "Bollinger bounce",
    "macd": "MACD crossover",
    "stoch": "Stochastic bounce",
}

# Tunable params per strategy: key -> (button label, preset values to cycle)
STRAT_PARAMS = {
    "ema_cross": [
        ("fast", "Fast EMA", [3, 5, 8, 10, 13]),
        ("slow", "Slow EMA", [13, 21, 26, 34]),
    ],
    "rsi": [
        ("period", "RSI period", [7, 14, 21]),
        ("ob", "Overbought", [70, 75, 80]),
        ("os", "Oversold", [20, 25, 30]),
    ],
    "bollinger": [
        ("period", "BB period", [14, 20, 30]),
        ("mult", "Std dev", [1.5, 2.0, 2.5]),
    ],
    "macd": [
        ("fast", "Fast", [8, 12]),
        ("slow", "Slow", [21, 26]),
        ("signal", "Signal", [5, 9]),
    ],
    "stoch": [
        ("k", "%K period", [9, 14, 21]),
        ("d", "%D period", [3, 5]),
        ("ob", "Overbought", [70, 75, 80]),
        ("os", "Oversold", [20, 25, 30]),
    ],
}
GLOBAL_PARAMS = [
    ("expiry", "Expiry (candles)", [1, 2, 3, 5, 10]),
    ("payout", "Payout %", [70, 75, 80, 85, 90, 95]),
    ("stake", "Stake", [1, 2, 5, 10]),
]

STRAT_DEFAULTS = {
    "ema_cross": {"fast": 5, "slow": 13},
    "rsi": {"period": 14, "ob": 70, "os": 30},
    "bollinger": {"period": 20, "mult": 2.0},
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "stoch": {"k": 14, "d": 3, "ob": 80, "os": 20},
}


def default_cfg(strategy):
    cfg = {"strategy": strategy, "expiry": 5, "payout": 80, "stake": 1}
    cfg.update(STRAT_DEFAULTS[strategy])
    return cfg


def _presets_for(strategy, key):
    for k, _label, presets in STRAT_PARAMS[strategy] + GLOBAL_PARAMS:
        if k == key:
            return presets
    return None


def next_preset(strategy, key, current):
    presets = _presets_for(strategy, key)
    if not presets:
        return current
    try:
        idx = next(i for i, v in enumerate(presets) if v == current)
    except StopIteration:
        idx = -1
    return presets[(idx + 1) % len(presets)]


def fmtv(v):
    return ("%g" % v)


# ------------------------------------------------------------------ helpers

def strategies_keyboard():
    keys = list(STRATEGY_LABELS)
    rows = []
    for i in range(0, len(keys), 2):
        rows.append(
            [InlineKeyboardButton(STRATEGY_LABELS[k], callback_data=f"bt:{k}")
             for k in keys[i:i + 2]]
        )
    return InlineKeyboardMarkup(rows)


def settings_keyboard(cfg):
    rows = []
    for key, label, _presets in STRAT_PARAMS[cfg["strategy"]] + GLOBAL_PARAMS:
        rows.append(
            [InlineKeyboardButton(f"{label}: {fmtv(cfg[key])} ⟳",
                                  callback_data=f"cfg:{key}")]
        )
    rows.append([InlineKeyboardButton("▶ Run backtest", callback_data="run")])
    rows.append([InlineKeyboardButton("↩ Strategies", callback_data="back")])
    return InlineKeyboardMarkup(rows)


def settings_text(cfg):
    lines = [f"*{STRATEGY_LABELS[cfg['strategy']]}* — tap a setting to change it:"]
    for key, label, _p in STRAT_PARAMS[cfg["strategy"]] + GLOBAL_PARAMS:
        lines.append(f"• {label}: {fmtv(cfg[key])}")
    return "\n".join(lines)


def cfg_summary(cfg):
    bits = [f"{k}={fmtv(cfg[k])}" for k, _l, _p in STRAT_PARAMS[cfg["strategy"]]]
    bits += [f"expiry={fmtv(cfg['expiry'])}", f"payout={fmtv(cfg['payout'])}%",
             f"stake={fmtv(cfg['stake'])}"]
    return ", ".join(bits)


def fmt_results(res, strategy_label, n_candles, data_src, cfg):
    wr = res["win_rate"] * 100
    be = res["be_win_rate"] * 100
    verdict = "ABOVE break-even ✓" if res["beats_breakeven"] else "BELOW break-even ✗"
    return (
        f"*{strategy_label}*\n"
        f"Settings: {cfg_summary(cfg)}\n"
        f"Candles: {n_candles} ({data_src})\n\n"
        f"Trades: {res['trades']} — Wins: {res['wins']} / Losses: {res['losses']}\n"
        f"Win rate: *{wr:.1f}%* (break-even needed: {be:.1f}%)\n"
        f"Net P/L: *{res['pnl']:+.2f}* units\n"
        f"Expectancy per trade: {res['expectancy']:+.3f} units\n"
        f"Max drawdown: {res['max_drawdown']:.2f} units\n\n"
        f"Verdict: {verdict}\n\n"
        f"_Historical results don't predict future trades._"
    )


# ------------------------------------------------------------------ handlers

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Backtester Bot.\n\n"
        "Test trading strategies on historical price data and see their *true* "
        "win rate — no fake signals, no promises.\n\n"
        "Use /backtest to start, or send me a CSV of candles (open,high,low,close) "
        "to test your own data.",
        parse_mode="Markdown",
    )
async def backtest_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Pick a strategy — then tune the settings before you run:",
        reply_markup=strategies_keyboard(),
    )


async def bt_flow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """One handler for the whole strategy/settings/run button flow."""
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "back":
        await q.message.edit_text(
            "Pick a strategy — then tune the settings before you run:",
            reply_markup=strategies_keyboard(),
        )
        return

    if data.startswith("bt:"):
        strat = data[3:]
        if strat not in STRATEGY_LABELS:
            return
        ctx.user_data["cfg"] = default_cfg(strat)
        cfg = ctx.user_data["cfg"]
        await q.message.edit_text(
            settings_text(cfg), parse_mode="Markdown",
            reply_markup=settings_keyboard(cfg),
        )
        return

    if data.startswith("cfg:"):
        cfg = ctx.user_data.get("cfg")
        if not cfg:
            return
        key = data[4:]
        cfg[key] = next_preset(cfg["strategy"], key, cfg[key])
        await q.message.edit_text(
            settings_text(cfg), parse_mode="Markdown",
            reply_markup=settings_keyboard(cfg),
        )
        return

    if data == "run":
        cfg = ctx.user_data.get("cfg")
        if not cfg:
            return
        candles = ctx.user_data.get("candles") or bt.gen_demo_candles()
        data_src = "your CSV" if "candles" in ctx.user_data else "built-in demo data (simulated)"
        strat = cfg["strategy"]
        sp = {k: cfg[k] for k, _l, _p in STRAT_PARAMS[strat]}
        try:
            res = bt.run_backtest(
                candles, strategy=strat, strategy_params=sp,
                expiry=int(cfg["expiry"]), payout=float(cfg["payout"]) / 100.0,
                stake=float(cfg["stake"]),
            )
        except ValueError as e:
            await q.message.reply_text(f"Backtest failed: {e}")
            return
        if res["trades"] == 0:
            await q.message.reply_text(
                "No signals fired on this data — try different settings or data.",
                reply_markup=settings_keyboard(cfg),
            )
            return
        await q.message.reply_text(
            fmt_results(res, STRATEGY_LABELS[strat], len(candles), data_src, cfg),
            parse_mode="Markdown",
            reply_markup=settings_keyboard(cfg),  # tweak and re-run
        )
        return


async def csv_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not (doc.file_name or "").lower().endswith(".csv"):
        await update.message.reply_text("Please send a .csv file.")
        return
    blob = await (await doc.get_file()).download_as_bytearray()
    try:
        candles = bt.parse_csv(bytes(blob).decode("utf-8", errors="ignore"))
    except ValueError as e:
        await update.message.reply_text(
            f"Couldn't read that CSV: {e}\n"
            "Expected rows like: open,high,low,close (a timestamp column in front is fine)."
        )
        return
    ctx.user_data["candles"] = candles
    await update.message.reply_text(
        f"Loaded {len(candles)} candles from your file. "
        "Use /backtest to test strategies on it. /data resets to demo data."
    )


async def data_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("candles", None)
    await update.message.reply_text(
        "Back to built-in demo data. Send a CSV anytime to use your own candles."
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/backtest — pick a strategy, tune it, run it\n"
        "/data — reset to demo data\n"
        "Or just send a CSV (open,high,low,close) to test your own candles."
    )


def main():
    if not BOT_TOKEN:
        raise SystemExit("Set the BOT_TOKEN environment variable (see SETUP.md).")
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("backtest", backtest_cmd))
    app.add_handler(CommandHandler("data", data_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(bt_flow, pattern=r"^(bt:|cfg:|run$|back$)"))
    app.add_handler(MessageHandler(filters.Document.ALL, csv_upload))
    app.run_polling()


if __name__ == "__main__":
    main()
