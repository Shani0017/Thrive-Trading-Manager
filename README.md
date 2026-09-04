# THRIVE Trade Manager

## ⬇ Download

**[Download the latest version](https://github.com/Shani0017/Thrive-Trading-Manager/releases/latest)** — click the `.exe` file under "Assets" on that page.

No installation, no setup — just open [MetaTrader 5](https://www.metatrader5.com/) and log into your account first, then double-click the downloaded file. That's it.

## What it does

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
  YouTube") saved locally in `%APPDATA%\THRIVE Trade Manager\trade_sources.json`.

---

## For Developers

### Running it from source

```bash
pip install -r requirements.txt
python main.py
```

Requires MetaTrader 5 to already be open and logged into your account — the
app attaches to that running terminal, it does not log in on its own.

### Building the distributable .exe

```bash
build_exe.bat
```

Produces a single file at `dist\THRIVE Trade Manager.exe`.

### Publishing a new release

1. Bump `APP_VERSION` in `update_check.py`.
2. Build the exe (`build_exe.bat`).
3. On GitHub, go to **Releases → Draft a new release**, tag it `vX.X.X`
   (matching `APP_VERSION`), and upload the `.exe` as an asset.
4. Anyone running an older version sees an in-app notice pointing them to
   this page the next time they open the app.

### Running tests

```bash
pytest -v
```
