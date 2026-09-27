# Backtester Bot — Setup Guide

A free Telegram bot: an honest strategy backtester. It shows true win rates
vs. break-even on historical data — never fake signals, never promises.

## What you need (your side)

1. **A Telegram bot token** — free, 2 minutes:
   - Message [@BotFather](https://t.me/BotFather) → `/newbot` → follow the prompts → copy the token.
2. **Hosting** — the bot must run 24/7. Easiest options:
   - **Railway** (railway.app): new project → deploy from the folder → set env vars → done.
   - **Render** (render.com): new Background Worker → same env vars.
   - Any VPS works too.

## Deploy steps (Railway example)

1. Push this folder to a GitHub repo (or use Railway's file upload).
2. Railway → New Project → Deploy from GitHub.
3. Add environment variable:
   - `BOT_TOKEN` — from BotFather
4. Start command: `python bot.py`
5. Deploy. Message your bot `/start` to test.

## Bot commands (for BotFather /setcommands)

```
start - Start the bot
backtest - Pick a strategy, tune it, run it
data - Reset to demo candle data
help - Show help
```

## Test the backtest engine locally (no Telegram needed)

```bash
python3 - <<'EOF'
import backtest as bt
data = bt.gen_demo_candles()
for s in bt.STRATEGIES:
    r = bt.run_backtest(data, strategy=s, expiry=5, payout=0.80)
    print(s, "trades:", r["trades"], "win%:", round(r["win_rate"]*100,1),
          "break-even%:", round(r["be_win_rate"]*100,1), "P/L:", r["pnl"])
EOF
```

## How people use it

- `/start` → welcome → `/backtest`
- `/backtest` → picks a strategy (EMA / RSI / Bollinger / MACD / Stochastic) →
  taps settings to tune them (lengths, levels, payout, expiry, stake) → runs
- Sends a CSV (`open,high,low,close`) → backtests their own candle data
- `/data` → back to built-in demo data

## Honest-marketing rules (protect yourself)

- Never advertise win rates or guaranteed profits — that invites bans and angry users.
- Present it as what it is: a tool that shows the *real* historical performance of strategies.
