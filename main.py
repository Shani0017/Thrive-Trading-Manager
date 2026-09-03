import sys
import traceback
import tkinter as tk
from tkinter import messagebox

LOG_FILE = "mt5_trade_manager_error.log"


def main():
    try:
        import customtkinter as ctk
        import MetaTrader5 as mt5
        from gui import TradeManagerApp
        from trade_journal import TradeJournalApp
        from home_view import HomeScreen

        root = ctk.CTk()

        def clear_root():
            for widget in root.winfo_children():
                widget.destroy()

        def show_home():
            clear_root()
            HomeScreen(root, on_open_manager=show_manager, on_open_journal=show_journal)

        def show_manager():
            clear_root()
            TradeManagerApp(root, mt5, on_home=show_home)

        def show_journal():
            clear_root()
            TradeJournalApp(root, mt5, on_home=show_home)

        show_home()
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
