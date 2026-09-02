import sys
import traceback
import tkinter as tk
from tkinter import messagebox

LOG_FILE = "mt5_trade_manager_error.log"


def main():
    try:
        import MetaTrader5 as mt5
        from gui import TradeManagerApp

        root = tk.Tk()
        root.geometry("820x420")
        TradeManagerApp(root, mt5)
        root.mainloop()
    except Exception:
        error_text = traceback.format_exc()
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write(error_text)
        except Exception:
            pass
        try:
            error_root = tk.Tk()
            error_root.withdraw()
            messagebox.showerror(
                "MT5 Trade Manager — Startup Error",
                "The app failed to start.\n\n" + error_text +
                f"\n\nA log file was saved as {LOG_FILE} next to this program.",
            )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
