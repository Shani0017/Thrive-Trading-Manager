import os
import sys
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from PIL import Image
from actions import apply_breakeven, half_close, full_close, apply_custom_sltp

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

GREEN = "#2fa84f"
RED = "#e5484d"
AMBER = "#d6a419"
MUTED = "#9aa0a6"


def _resource_path(relative_path: str) -> str:
    """Resolves a bundled asset both in normal dev runs and inside a
    PyInstaller onefile .exe, where bundled data lives under a temporary
    _MEIPASS extraction directory instead of next to this script."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class TradeManagerApp:
    # How often the app polls MT5 for open-position updates. MT5's Python API
    # has no push/subscribe mechanism -- positions_get() must be polled -- so
    # some delay is unavoidable, but 2s was needlessly cautious for how cheap
    # a single positions_get() call + table refresh actually is. 500ms keeps
    # the table visually near-instant without hammering the terminal's IPC
    # layer on every UI frame.
    REFRESH_MS = 500
    RECONNECT_MS = 5000

    def __init__(self, root, mt5):
        self.root = root
        self.mt5 = mt5
        self.root.title("MT5 Trade Manager")
        self.root.geometry("940x600")
        self.root.minsize(860, 560)
        self.connected = False
        self.selected_ticket = None
        self.positions_by_ticket = {}
        self._refresh_job = None
        self._reconnect_job = None

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(16, 0))

        try:
            logo_img = Image.open(_resource_path("assets/logo.png"))
            self._logo_image = ctk.CTkImage(logo_img, size=(120, 44))
            ctk.CTkLabel(header, image=self._logo_image, text="").pack(side="left", padx=(0, 14))
        except Exception:
            pass  # missing/unreadable logo must never block the app from starting

        self.status_label = ctk.CTkLabel(header, text="Connecting to MT5...",
                                          font=ctk.CTkFont(size=15, weight="bold"),
                                          anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True, pady=8)

        table_frame = ctk.CTkFrame(root, corner_radius=12)
        table_frame.pack(fill="both", expand=True, padx=18, pady=8)

        ctk.CTkLabel(table_frame, text="OPEN POSITIONS", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(14, 6))

        self._setup_treeview_style()

        columns = ("symbol", "direction", "volume", "entry", "current", "pnl", "sl", "tp")
        headings = {
            "symbol": "Symbol", "direction": "Dir", "volume": "Volume",
            "entry": "Entry", "current": "Current", "pnl": "P&L",
            "sl": "SL", "tp": "TP",
        }
        widths = {"symbol": 90, "direction": 60, "volume": 70, "entry": 100,
                  "current": 100, "pnl": 90, "sl": 100, "tp": 100}
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                  height=9, style="Positions.Treeview")
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center", stretch=True)
        self.tree.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self._build_action_panel(root)

        self.result_label = ctk.CTkLabel(root, text="", font=ctk.CTkFont(size=13, weight="bold"),
                                          anchor="w")
        self.result_label.pack(fill="x", padx=18, pady=(4, 16))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._try_connect()
        self._refresh_job = self.root.after(self.REFRESH_MS, self._refresh_loop)

    def _setup_treeview_style(self):
        """ttk.Treeview has no CustomTkinter equivalent (CTk provides no table
        widget), so it's embedded here and themed by hand to match the dark
        CTk chrome around it -- a standard pattern for CustomTkinter apps that
        need tabular data."""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Positions.Treeview", background="#2b2b2b", fieldbackground="#2b2b2b",
                         foreground="#e6e6e6", rowheight=28, font=("Segoe UI", 10), borderwidth=0)
        style.configure("Positions.Treeview.Heading", background="#242424", foreground="#c9cdd3",
                         font=("Segoe UI", 10, "bold"), borderwidth=0, relief="flat")
        style.map("Positions.Treeview.Heading", background=[("active", "#2f2f2f")])
        style.map("Positions.Treeview", background=[("selected", "#1f6aa5")],
                  foreground=[("selected", "#ffffff")])

    def _build_action_panel(self, root):
        panel = ctk.CTkFrame(root, corner_radius=12)
        panel.pack(fill="x", padx=18, pady=(0, 8))

        ctk.CTkLabel(panel, text="ACTIONS", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=18, pady=(16, 4))

        # --- Stop Loss to Breakeven ---
        be_section = ctk.CTkFrame(panel, fg_color="transparent")
        be_section.pack(fill="x", padx=18, pady=(2, 12))

        ctk.CTkLabel(be_section, text="Stop Loss to Breakeven", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).pack(anchor="w", pady=(0, 8))

        be_row = ctk.CTkFrame(be_section, fg_color="transparent")
        be_row.pack(fill="x")

        self.be_exact_btn = ctk.CTkButton(be_row, text="Breakeven (Exact)", width=170, height=36,
                                           command=self._on_breakeven_exact)
        self.be_exact_btn.pack(side="left", padx=(0, 24))

        ctk.CTkLabel(be_row, text="Breakeven +", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        self.pips_entry = ctk.CTkEntry(be_row, width=70, height=36, placeholder_text="e.g. 5")
        self.pips_entry.pack(side="left", padx=(0, 6))
        self.pips_entry.bind("<KeyRelease>", self._on_pips_entry_change)
        ctk.CTkLabel(be_row, text="pips", font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            side="left", padx=(0, 12))
        self.be_pips_btn = ctk.CTkButton(be_row, text="Apply", width=90, height=36,
                                          command=self._on_breakeven_pips)
        self.be_pips_btn.pack(side="left")

        ctk.CTkLabel(be_section,
                     text="Locks in profit: moves the stop that many pips past your entry price,\n"
                          "in the direction of the trade, instead of leaving it exactly at entry.",
                     font=ctk.CTkFont(size=10), text_color=MUTED, justify="left").pack(
            anchor="w", pady=(8, 0))

        sep1 = ctk.CTkFrame(panel, height=1, fg_color="#3a3a3a")
        sep1.pack(fill="x", padx=18)

        # --- Close position ---
        close_section = ctk.CTkFrame(panel, fg_color="transparent")
        close_section.pack(fill="x", padx=18, pady=12)

        ctk.CTkLabel(close_section, text="Close Position", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).pack(anchor="w", pady=(0, 8))

        close_row = ctk.CTkFrame(close_section, fg_color="transparent")
        close_row.pack(fill="x")

        self.half_close_btn = ctk.CTkButton(close_row, text="Half Close", width=140, height=36,
                                             command=self._on_half_close)
        self.half_close_btn.pack(side="left", padx=(0, 10))

        self.full_close_btn = ctk.CTkButton(close_row, text="Full Close", width=140, height=36,
                                             command=self._on_full_close,
                                             fg_color=RED, hover_color="#b03a3e")
        self.full_close_btn.pack(side="left", padx=(0, 18))

        self.skip_confirm_var = tk.BooleanVar(value=False)
        self.skip_confirm_check = ctk.CTkCheckBox(
            close_row, text="Don't ask me again before closing a trade",
            variable=self.skip_confirm_var, font=ctk.CTkFont(size=11),
            checkbox_width=18, checkbox_height=18)
        self.skip_confirm_check.pack(side="left")

        sep2 = ctk.CTkFrame(panel, height=1, fg_color="#3a3a3a")
        sep2.pack(fill="x", padx=18)

        # --- Custom SL / TP ---
        sltp_section = ctk.CTkFrame(panel, fg_color="transparent")
        sltp_section.pack(fill="x", padx=18, pady=(12, 18))

        ctk.CTkLabel(sltp_section, text="Custom SL / TP", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).pack(anchor="w", pady=(0, 8))

        sltp_row = ctk.CTkFrame(sltp_section, fg_color="transparent")
        sltp_row.pack(fill="x")

        ctk.CTkLabel(sltp_row, text="SL", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        self.sl_entry = ctk.CTkEntry(sltp_row, width=130, height=36)
        self.sl_entry.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(sltp_row, text="TP", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        self.tp_entry = ctk.CTkEntry(sltp_row, width=130, height=36)
        self.tp_entry.pack(side="left", padx=(0, 20))

        self.apply_sltp_btn = ctk.CTkButton(sltp_row, text="Apply SL/TP", width=140, height=36,
                                             command=self._on_apply_sltp)
        self.apply_sltp_btn.pack(side="left")

        self.action_widgets = [
            self.be_exact_btn, self.pips_entry, self.be_pips_btn,
            self.half_close_btn, self.full_close_btn,
            self.sl_entry, self.tp_entry, self.apply_sltp_btn,
        ]
        self._set_action_panel_enabled(False)

    def _on_close(self):
        for job in (self._refresh_job, self._reconnect_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self.root.destroy()

    def _try_connect(self):
        try:
            ok = self.mt5.initialize()
        except Exception:
            ok = False

        if ok:
            self.connected = True
            try:
                account = self.mt5.account_info()
                login = account.login if account else "?"
            except Exception:
                login = "?"
            self.status_label.configure(text=f"● Connected to MT5 (account {login})",
                                         text_color=GREEN)
        else:
            self.connected = False
            self.status_label.configure(
                text="● MT5 not connected — please open and log into MetaTrader 5",
                text_color=RED)
            self._reconnect_job = self.root.after(self.RECONNECT_MS, self._try_connect)

    def _refresh_loop(self):
        if self.connected:
            self._refresh_account_banner()
            self._refresh_positions()
        self._refresh_job = self.root.after(self.REFRESH_MS, self._refresh_loop)

    def _refresh_account_banner(self):
        """Keeps the account number in the status banner accurate if the user
        switches accounts inside MT5 without closing/reopening the terminal.
        _try_connect() only sets this once, at initial connect, so without
        this the banner would keep showing the OLD account's login number
        even though positions_get() below is already correctly reflecting
        whichever account MT5 currently has active."""
        try:
            account = self.mt5.account_info()
            login = account.login if account else "?"
        except Exception:
            login = "?"
        self.status_label.configure(text=f"● Connected to MT5 (account {login})", text_color=GREEN)

    def _handle_connection_lost(self):
        self.connected = False
        self.status_label.configure(
            text="● MT5 not connected — please open and log into MetaTrader 5",
            text_color=RED)
        self._reconnect_job = self.root.after(self.RECONNECT_MS, self._try_connect)

    def _refresh_positions(self):
        try:
            positions = self.mt5.positions_get()
        except Exception:
            positions = None

        if positions is None:
            # The real MetaTrader5 package returns None specifically on error/
            # disconnection, and an empty tuple for the valid "no open positions"
            # case -- these must NOT be treated the same, or a real disconnection
            # silently looks like an empty table with a stale "Connected" banner.
            self._handle_connection_lost()
            return

        self.positions_by_ticket = {p.ticket: p for p in positions}

        # Update rows in place (rather than delete-then-reinsert) so that a
        # periodic refresh never re-fires <<TreeviewSelect>> for the row the
        # user already has selected -- deleting and re-adding an item counts
        # as a new selection to tkinter, which would otherwise clobber
        # whatever the user is mid-typing in the SL/TP fields every 2 seconds.
        current_iids = set(self.tree.get_children())
        new_iids = {str(p.ticket) for p in positions}

        for iid in current_iids - new_iids:
            self.tree.delete(iid)

        for p in positions:
            direction = "BUY" if p.type == self.mt5.POSITION_TYPE_BUY else "SELL"
            values = (p.symbol, direction, p.volume,
                      f"{p.price_open:.5f}", f"{p.price_current:.5f}",
                      f"{p.profit:.2f}", f"{p.sl:.5f}", f"{p.tp:.5f}")
            iid = str(p.ticket)
            if iid in current_iids:
                self.tree.item(iid, values=values)
            else:
                self.tree.insert("", "end", iid=iid, values=values)

        if self.selected_ticket not in self.positions_by_ticket:
            self.selected_ticket = None
            self._set_action_panel_enabled(False)

    def _on_select(self, event):
        selection = self.tree.selection()
        if not selection:
            self.selected_ticket = None
            self._set_action_panel_enabled(False)
            return
        self.selected_ticket = int(selection[0])
        self._set_action_panel_enabled(True)
        self.result_label.configure(text="")
        position = self.positions_by_ticket[self.selected_ticket]
        self.sl_entry.delete(0, tk.END)
        if position.sl:
            self.sl_entry.insert(0, f"{position.sl:.5f}")
        self.tp_entry.delete(0, tk.END)
        if position.tp:
            self.tp_entry.insert(0, f"{position.tp:.5f}")

    def _set_action_panel_enabled(self, enabled: bool):
        self._panel_enabled = enabled
        state = "normal" if enabled else "disabled"
        for widget in self.action_widgets:
            widget.configure(state=state)
        if enabled:
            self._on_pips_entry_change(None)  # re-evaluate pips-button state for the new selection

    def _on_pips_entry_change(self, event):
        value = self.pips_entry.get().strip()
        try:
            pips = float(value)
            valid = pips > 0
        except ValueError:
            valid = False
        self.be_pips_btn.configure(state="normal" if (valid and self._panel_enabled) else "disabled")

    def _get_live_position(self, ticket):
        """Re-fetches the position directly from MT5 by ticket, rather than
        trusting the periodically-refreshed self.positions_by_ticket cache --
        that cache can be stale by up to one refresh interval, or much longer
        while a confirmation dialog is open (tkinter keeps servicing the
        background refresh timer even while a messagebox is modal). Returns
        None if the ticket no longer exists (position already closed) or if
        the MT5 call itself fails."""
        try:
            positions = self.mt5.positions_get(ticket=ticket)
        except Exception:
            return None
        if not positions:
            return None
        return positions[0]

    def _show_result(self, result, success_message="Done."):
        if result is None:
            self.result_label.configure(text="Action could not be completed.", text_color=RED)
            return
        if result.retcode == self.mt5.TRADE_RETCODE_DONE:
            self.result_label.configure(text=success_message, text_color=GREEN)
        elif result.retcode == self.mt5.TRADE_RETCODE_DONE_PARTIAL:
            self.result_label.configure(
                text=f"Partially filled — {success_message} Check remaining volume before retrying.",
                text_color=AMBER)
        else:
            self.result_label.configure(
                text=f"Broker rejected: {result.retcode} {getattr(result, 'comment', '')}",
                text_color=RED)

    def _on_breakeven_exact(self):
        if self.selected_ticket is None:
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self.result_label.configure(text="Position no longer open.", text_color=RED)
            return
        try:
            result = apply_breakeven(self.mt5, position, pips=0.0)
        except Exception:
            self.result_label.configure(text="Action failed (MT5 error).", text_color=RED)
            return
        self._show_result(result, "SL moved to breakeven.")

    def _on_breakeven_pips(self):
        if self.selected_ticket is None:
            return
        try:
            pips = float(self.pips_entry.get().strip())
        except ValueError:
            self.result_label.configure(text="Enter a valid positive pip value first.", text_color=RED)
            return
        if pips <= 0:
            self.result_label.configure(text="Pips must be a positive number.", text_color=RED)
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self.result_label.configure(text="Position no longer open.", text_color=RED)
            return
        try:
            result = apply_breakeven(self.mt5, position, pips=pips)
        except Exception:
            self.result_label.configure(text="Action failed (MT5 error).", text_color=RED)
            return
        self._show_result(result, f"SL moved to breakeven +{pips:g} pips.")

    def _on_half_close(self):
        if self.selected_ticket is None:
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self.result_label.configure(text="Position no longer open.", text_color=RED)
            return
        try:
            result = half_close(self.mt5, position)
        except Exception:
            self.result_label.configure(text="Action failed (MT5 error).", text_color=RED)
            return
        if result is None:
            self.result_label.configure(
                text="Cannot half-close: half the volume is below the broker's minimum lot.",
                text_color=RED)
            return
        self._show_result(result, "Half of the position closed.")

    def _on_full_close(self):
        if self.selected_ticket is None:
            return
        ticket = self.selected_ticket
        position = self._get_live_position(ticket)
        if position is None:
            self.result_label.configure(text="Position no longer open.", text_color=RED)
            return
        direction = "BUY" if position.type == self.mt5.POSITION_TYPE_BUY else "SELL"
        confirmed = messagebox.askyesno(
            "Confirm Close",
            f"Close {position.volume} {position.symbol} {direction} at market?",
        )
        if not confirmed:
            return
        # Re-fetch again -- the position may have closed, or its volume may
        # have changed, while the confirmation dialog was open (tkinter keeps
        # servicing the background refresh timer during a modal dialog).
        position = self._get_live_position(ticket)
        if position is None:
            self.result_label.configure(
                text="Position closed before confirmation completed -- no action taken.",
                text_color=RED)
            return
        try:
            result = full_close(self.mt5, position)
        except Exception:
            self.result_label.configure(text="Action failed (MT5 error).", text_color=RED)
            return
        self._show_result(result, "Position closed.")

    def _on_apply_sltp(self):
        if self.selected_ticket is None:
            return
        sl_text = self.sl_entry.get().strip()
        tp_text = self.tp_entry.get().strip()
        try:
            sl = float(sl_text) if sl_text else None
            tp = float(tp_text) if tp_text else None
        except ValueError:
            self.result_label.configure(text="SL/TP must be numbers.", text_color=RED)
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self.result_label.configure(text="Position no longer open.", text_color=RED)
            return
        try:
            result, error = apply_custom_sltp(self.mt5, position, sl, tp)
        except Exception:
            self.result_label.configure(text="Action failed (MT5 error).", text_color=RED)
            return
        if error:
            self.result_label.configure(text=error, text_color=RED)
            return
        self._show_result(result, "SL/TP updated.")
