# MT5 Trade Manager

Launches to a home screen with two tools:

- **Trade Manager** — manage open MT5 positions: move SL to breakeven (exact
  or +pips), half-close, fully close, or set a custom SL/TP, plus a live
  candlestick chart, all with a single click on whichever position you select
  from the live table. Never opens a trade and never acts on its own — every
  action happens only when you click a button.
- **Trading Journal** — full closed-trade history pulled from MT5's own deal
  records (real data, reconstructed by pairing each position's entry/exit
  deals), with a running P&L/win-rate summary, date-range and symbol filters,
  and a "source" note per trade (e.g. "My Analysis", "XYZ Trader", "XYZ
  YouTube") saved locally next to the app in `trade_sources.json`.

## Running it (developer)

```bash
pip install -r requirements.txt
python main.py
```

Requires MetaTrader 5 to already be open and logged into your account — the
app attaches to that running terminal, it does not log in on its own.

## Building the distributable .exe

```bash
build_exe.bat
```

Produces a single file at `dist\MT5TradeManager.exe`. Send that one file to
anyone — they just need their own MT5 terminal open and logged in, nothing
else to install.

## Running tests

```bash
pytest -v
```
