import os
import sys
import traceback
import tkinter as tk
from tkinter import messagebox

LOG_FILENAME = "mt5_trade_manager_error.log"


def _log_file_path() -> str:
    """Resolves next to the .exe/script itself -- NOT a plain relative
    path, which would land wherever the current working directory
    happens to be when the exe was launched (double-clicking from
    Explorer sets CWD to the exe's own folder, but a shortcut with a
    different "Start in" value, or launching via cmd from elsewhere,
    would not) -- silently contradicting the error dialog's own claim
    that the log was saved "next to this program"."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, LOG_FILENAME)


def main():
    try:
        import customtkinter as ctk
        import MetaTrader5 as mt5
        from gui import TradeManagerApp, _resource_path
        from trade_journal import TradeJournalApp
        from home_view import HomeScreen

        root = ctk.CTk()
        # This is the window's own title-bar icon (top-left corner, and
        # Alt+Tab on some setups) -- a separate thing from the .exe file's
        # icon, which is embedded by PyInstaller's --icon flag and was
        # already fixed. Without this, Tkinter shows a generic default
        # icon regardless of what the exe's file icon looks like. Set once
        # here since root is the single Tk window reused across every page
        # (Home/Trade Manager/Journal just swap its contents).
        try:
            root.iconbitmap(_resource_path("assets/icon.ico"))
        except Exception:
            pass

        # Tracks whichever page is currently showing, so clear_root() can
        # cancel its timers (if it has any) before destroying its widgets --
        # without this, a page's still-pending after() callback can fire
        # against widgets that no longer exist. Every page class that owns
        # a recurring timer must expose a stop() method for this to find.
        current_page = {"page": None}

        def clear_root():
            page = current_page["page"]
            if page is not None and hasattr(page, "stop"):
                page.stop()
            for widget in root.winfo_children():
                widget.destroy()

        def show_home():
            clear_root()
            current_page["page"] = HomeScreen(root, on_open_manager=show_manager, on_open_journal=show_journal)

        def show_manager():
            clear_root()
            current_page["page"] = TradeManagerApp(root, mt5, on_home=show_home)

        def show_journal():
            clear_root()
            current_page["page"] = TradeJournalApp(root, mt5, on_home=show_home)

        show_home()
        root.mainloop()
    except Exception:
        error_text = traceback.format_exc()
        log_path = _log_file_path()
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(error_text)
        except Exception:
            pass
        try:
            error_root = tk.Tk()
            error_root.withdraw()
            messagebox.showerror(
                "THRIVE Trade Manager — Startup Error",
                "The app failed to start.\n\n" + error_text +
                f"\n\nA log file was saved at:\n{log_path}",
            )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
