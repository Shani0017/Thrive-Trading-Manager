# MT5 Trade Manager

A standalone tool for manually managing open MT5 positions: move SL to breakeven
(exact or +pips), half-close, fully close, or set a custom SL/TP — all with a
single click on whichever position you select from the live table.

This tool never opens a trade and never acts on its own. Every action happens
only when you click a button.

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
