import os
import sys
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from PIL import Image
from actions import apply_breakeven, half_close, full_close, apply_custom_sltp

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# -- Palette: clean/light, one accent color, soft semantic tints. Modeled on
# the modern-SaaS-dashboard look (Notion/Linear/Stripe) explicitly requested
# over the earlier dark trading-terminal theme. --
BG = "#f6f7f9"
CARD = "#ffffff"
BORDER = "#e5e7eb"
TEXT = "#111827"
MUTED = "#6b7280"
ACCENT = "#4f46e5"
ACCENT_HOVER = "#4338ca"
SUCCESS = "#059669"
SUCCESS_BG = "#ecfdf5"
DANGER = "#dc2626"
DANGER_HOVER = "#b91c1c"
DANGER_BG = "#fef2f2"
WARNING = "#d97706"
WARNING_BG = "#fffbeb"
LOGO_CHIP_BG = "#111827"

_RESULT_STYLES = {
    "success": (SUCCESS_BG, SUCCESS),
    "error": (DANGER_BG, DANGER),
    "warning": (WARNING_BG, WARNING),
    "neutral": (BG, MUTED),
}


def _resource_path(relative_path: str) -> str:
    """Resolves a bundled asset both in normal dev runs and inside a
    PyInstaller onefile .exe, where bundled data lives under a temporary
    _MEIPASS extraction directory instead of next to this script."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class TradeManagerApp:
    # How often the app polls MT5 for open-position updates. MT5's Python API
    # has no push/subscribe mechanism -- positions_get() must be polled -- so
    # some delay is unavoidable, but a single positions_get() call is cheap
    # enough that polling every 500ms keeps the table feeling near-instant
    # without hammering the terminal's IPC layer.
    REFRESH_MS = 500
    RECONNECT_MS = 5000

    def __init__(self, root, mt5):
        self.root = root
        self.mt5 = mt5
        self.root.title("MT5 Trade Manager")
        self.root.geometry("1040x780")
        self.root.minsize(900, 620)
        self.root.configure(fg_color=BG)
        self.connected = False
        self.selected_ticket = None
        self.positions_by_ticket = {}
        self._refresh_job = None
        self._reconnect_job = None

        # Scrollable outer container: a safety net so content is never
        # silently cut off below the window edge on a shorter screen or
        # under Windows display scaling -- it simply becomes scrollable
        # instead, rather than invisible with no way to reach it.
        scroll = ctk.CTkScrollableFrame(root, fg_color=BG)
        scroll.pack(fill="both", expand=True)
        content = scroll

        header = ctk.CTkFrame(content, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 12))

        logo_chip = ctk.CTkFrame(header, fg_color=LOGO_CHIP_BG, corner_radius=8)
        logo_chip.pack(side="left")
        try:
            logo_img = Image.open(_resource_path("assets/logo.png"))
            self._logo_image = ctk.CTkImage(logo_img, size=(96, 35))
            ctk.CTkLabel(logo_chip, image=self._logo_image, text="").pack(padx=14, pady=8)
        except Exception:
            ctk.CTkLabel(logo_chip, text="THRIVE", text_color="#ffffff",
                         font=ctk.CTkFont(size=14, weight="bold")).pack(padx=14, pady=8)

        self.status_badge = ctk.CTkFrame(header, corner_radius=14, fg_color=WARNING_BG)
        self.status_badge.pack(side="right")
        self.status_label = ctk.CTkLabel(self.status_badge, text="Connecting to MT5...",
                                          font=ctk.CTkFont(size=12, weight="bold"),
                                          text_color=WARNING)
        self.status_label.pack(padx=14, pady=6)

        table_card = ctk.CTkFrame(content, corner_radius=14, fg_color=CARD,
                                   border_width=1, border_color=BORDER)
        table_card.pack(fill="both", expand=True, padx=24, pady=8)

        ctk.CTkLabel(table_card, text="Open Positions", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=18, pady=(16, 8))

        self._setup_treeview_style()

        columns = ("symbol", "direction", "volume", "entry", "current", "pnl", "sl", "tp")
        headings = {
            "symbol": "Symbol", "direction": "Dir", "volume": "Volume",
            "entry": "Entry", "current": "Current", "pnl": "P&L",
            "sl": "SL", "tp": "TP",
        }
        widths = {"symbol": 90, "direction": 60, "volume": 70, "entry": 100,
                  "current": 100, "pnl": 90, "sl": 100, "tp": 100}
        self.tree = ttk.Treeview(table_card, columns=columns, show="headings",
                                  height=8, style="Positions.Treeview")
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center", stretch=True)
        self.tree.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self._build_action_panel(content)

        self.result_banner = ctk.CTkFrame(content, corner_radius=10, fg_color=BG)
        self.result_banner.pack(fill="x", padx=24, pady=(0, 20))
        self.result_label = ctk.CTkLabel(self.result_banner, text="",
                                          font=ctk.CTkFont(size=12, weight="bold"),
                                          anchor="w")
        self.result_label.pack(anchor="w", padx=14, pady=8)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._try_connect()
        self._refresh_job = self.root.after(self.REFRESH_MS, self._refresh_loop)

    def _setup_treeview_style(self):
        """ttk.Treeview has no CustomTkinter equivalent (CTk provides no table
        widget), so it's embedded here and themed by hand to match the light
        card chrome around it -- a standard pattern for CustomTkinter apps
        that need tabular data."""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Positions.Treeview", background=CARD, fieldbackground=CARD,
                         foreground=TEXT, rowheight=30, font=("Segoe UI", 10), borderwidth=0)
        style.configure("Positions.Treeview.Heading", background="#f9fafb", foreground=MUTED,
                         font=("Segoe UI", 9, "bold"), borderwidth=0, relief="flat")
        style.map("Positions.Treeview.Heading", background=[("active", "#f3f4f6")])
        style.map("Positions.Treeview", background=[("selected", "#eef2ff")],
                  foreground=[("selected", TEXT)])

    def _build_action_panel(self, root):
        panel = ctk.CTkFrame(root, corner_radius=14, fg_color=CARD,
                              border_width=1, border_color=BORDER)
        panel.pack(fill="x", padx=24, pady=8)

        ctk.CTkLabel(panel, text="Actions", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=18, pady=(16, 4))

        # --- Stop Loss to Breakeven ---
        be_section = ctk.CTkFrame(panel, fg_color="transparent")
        be_section.pack(fill="x", padx=18, pady=(4, 12))

        ctk.CTkLabel(be_section, text="STOP LOSS TO BREAKEVEN", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=MUTED).pack(anchor="w", pady=(0, 8))

        be_row = ctk.CTkFrame(be_section, fg_color="transparent")
        be_row.pack(fill="x")

        self.be_exact_btn = ctk.CTkButton(be_row, text="Breakeven (Exact)", width=170, height=36,
                                           fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                           command=self._on_breakeven_exact)
        self.be_exact_btn.pack(side="left", padx=(0, 24))

        ctk.CTkLabel(be_row, text="Breakeven +", font=ctk.CTkFont(size=12),
                     text_color=TEXT).pack(side="left", padx=(0, 6))
        self.pips_entry = ctk.CTkEntry(be_row, width=70, height=36, placeholder_text="e.g. 5",
                                        border_color=BORDER)
        self.pips_entry.pack(side="left", padx=(0, 6))
        self.pips_entry.bind("<KeyRelease>", self._on_pips_entry_change)
        ctk.CTkLabel(be_row, text="pips", font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            side="left", padx=(0, 12))
        self.be_pips_btn = ctk.CTkButton(be_row, text="Apply", width=90, height=36,
                                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                          command=self._on_breakeven_pips)
        self.be_pips_btn.pack(side="left")

        ctk.CTkLabel(be_section,
                     text="Locks in profit: moves the stop that many pips past your entry price,\n"
                          "in the direction of the trade, instead of leaving it exactly at entry.",
                     font=ctk.CTkFont(size=10), text_color=MUTED, justify="left").pack(
            anchor="w", pady=(8, 0))

        sep1 = ctk.CTkFrame(panel, height=1, fg_color=BORDER)
        sep1.pack(fill="x", padx=18)

        # --- Close position ---
        close_section = ctk.CTkFrame(panel, fg_color="transparent")
        close_section.pack(fill="x", padx=18, pady=12)

        ctk.CTkLabel(close_section, text="CLOSE POSITION", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=MUTED).pack(anchor="w", pady=(0, 8))

        close_row = ctk.CTkFrame(close_section, fg_color="transparent")
        close_row.pack(fill="x")

        self.half_close_btn = ctk.CTkButton(close_row, text="Half Close", width=140, height=36,
                                             fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                             command=self._on_half_close)
        self.half_close_btn.pack(side="left", padx=(0, 10))

        self.full_close_btn = ctk.CTkButton(close_row, text="Full Close", width=140, height=36,
                                             command=self._on_full_close,
                                             fg_color=DANGER, hover_color=DANGER_HOVER)
        self.full_close_btn.pack(side="left", padx=(0, 18))

        self.skip_confirm_var = tk.BooleanVar(value=False)
        self.skip_confirm_check = ctk.CTkCheckBox(
            close_row, text="Don't ask me again before closing a trade",
            variable=self.skip_confirm_var, font=ctk.CTkFont(size=11), text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=BORDER,
            checkbox_width=18, checkbox_height=18)
        self.skip_confirm_check.pack(side="left")

        sep2 = ctk.CTkFrame(panel, height=1, fg_color=BORDER)
        sep2.pack(fill="x", padx=18)

        # --- Custom SL / TP ---
        sltp_section = ctk.CTkFrame(panel, fg_color="transparent")
        sltp_section.pack(fill="x", padx=18, pady=(12, 18))

        ctk.CTkLabel(sltp_section, text="CUSTOM SL / TP", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=MUTED).pack(anchor="w", pady=(0, 8))

        sltp_row = ctk.CTkFrame(sltp_section, fg_color="transparent")
        sltp_row.pack(fill="x")

        ctk.CTkLabel(sltp_row, text="SL", font=ctk.CTkFont(size=12),
                     text_color=TEXT).pack(side="left", padx=(0, 6))
        self.sl_entry = ctk.CTkEntry(sltp_row, width=130, height=36, border_color=BORDER)
        self.sl_entry.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(sltp_row, text="TP", font=ctk.CTkFont(size=12),
                     text_color=TEXT).pack(side="left", padx=(0, 6))
        self.tp_entry = ctk.CTkEntry(sltp_row, width=130, height=36, border_color=BORDER)
        self.tp_entry.pack(side="left", padx=(0, 20))

        self.apply_sltp_btn = ctk.CTkButton(sltp_row, text="Apply SL/TP", width=140, height=36,
                                             fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                             command=self._on_apply_sltp)
        self.apply_sltp_btn.pack(side="left")

        self.action_widgets = [
            self.be_exact_btn, self.pips_entry, self.be_pips_btn,
            self.half_close_btn, self.full_close_btn,
            self.sl_entry, self.tp_entry, self.apply_sltp_btn,
        ]
        self._set_action_panel_enabled(False)

    def _set_result(self, text: str, tone: str = "neutral"):
        bg, fg = _RESULT_STYLES.get(tone, _RESULT_STYLES["neutral"])
        self.result_banner.configure(fg_color=bg if text else BG)
        self.result_label.configure(text=text, text_color=fg)

    def _on_close(self):
        for job in (self._refresh_job, self._reconnect_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self.root.destroy()

    def _set_status(self, text: str, tone: str):
        bg, fg = _RESULT_STYLES.get(tone, _RESULT_STYLES["neutral"])
        self.status_badge.configure(fg_color=bg)
        self.status_label.configure(text=text, text_color=fg)

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
            self._set_status(f"● Connected — account {login}", "success")
        else:
            self.connected = False
            self._set_status("● MT5 not connected — open and log into MetaTrader 5", "error")
            self._reconnect_job = self.root.after(self.RECONNECT_MS, self._try_connect)

    def _refresh_loop(self):
        if self.connected:
            self._refresh_account_banner()
            self._refresh_positions()
        self._refresh_job = self.root.after(self.REFRESH_MS, self._refresh_loop)

    def _refresh_account_banner(self):
        """Keeps the account number in the status badge accurate if the user
        switches accounts inside MT5 without closing/reopening the terminal.
        _try_connect() only sets this once, at initial connect, so without
        this the badge would keep showing the OLD account's login number
        even though positions_get() below is already correctly reflecting
        whichever account MT5 currently has active."""
        try:
            account = self.mt5.account_info()
            login = account.login if account else "?"
        except Exception:
            login = "?"
        self._set_status(f"● Connected — account {login}", "success")

    def _handle_connection_lost(self):
        self.connected = False
        self._set_status("● MT5 not connected — open and log into MetaTrader 5", "error")
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
            # silently looks like an empty table with a stale "Connected" badge.
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
        self._set_result("", "neutral")
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
            self._set_result("Action could not be completed.", "error")
            return
        if result.retcode == self.mt5.TRADE_RETCODE_DONE:
            self._set_result(success_message, "success")
        elif result.retcode == self.mt5.TRADE_RETCODE_DONE_PARTIAL:
            self._set_result(
                f"Partially filled — {success_message} Check remaining volume before retrying.",
                "warning")
        else:
            self._set_result(
                f"Broker rejected: {result.retcode} {getattr(result, 'comment', '')}", "error")

    def _on_breakeven_exact(self):
        if self.selected_ticket is None:
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self._set_result("Position no longer open.", "error")
            return
        try:
            result = apply_breakeven(self.mt5, position, pips=0.0)
        except Exception:
            self._set_result("Action failed (MT5 error).", "error")
            return
        self._show_result(result, "SL moved to breakeven.")

    def _on_breakeven_pips(self):
        if self.selected_ticket is None:
            return
        try:
            pips = float(self.pips_entry.get().strip())
        except ValueError:
            self._set_result("Enter a valid positive pip value first.", "error")
            return
        if pips <= 0:
            self._set_result("Pips must be a positive number.", "error")
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self._set_result("Position no longer open.", "error")
            return
        try:
            result = apply_breakeven(self.mt5, position, pips=pips)
        except Exception:
            self._set_result("Action failed (MT5 error).", "error")
            return
        self._show_result(result, f"SL moved to breakeven +{pips:g} pips.")

    def _on_half_close(self):
        if self.selected_ticket is None:
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self._set_result("Position no longer open.", "error")
            return
        try:
            result = half_close(self.mt5, position)
        except Exception:
            self._set_result("Action failed (MT5 error).", "error")
            return
        if result is None:
            self._set_result(
                "Cannot half-close: half the volume is below the broker's minimum lot.", "error")
            return
        self._show_result(result, "Half of the position closed.")

    def _on_full_close(self):
        if self.selected_ticket is None:
            return
        ticket = self.selected_ticket
        position = self._get_live_position(ticket)
        if position is None:
            self._set_result("Position no longer open.", "error")
            return
        direction = "BUY" if position.type == self.mt5.POSITION_TYPE_BUY else "SELL"
        if not self.skip_confirm_var.get():
            confirmed = messagebox.askyesno(
                "Confirm Close",
                f"Close {position.volume} {position.symbol} {direction} at market?",
            )
            if not confirmed:
                return
        # Re-fetch again -- the position may have closed, or its volume may
        # have changed, while the confirmation dialog was open (tkinter keeps
        # servicing the background refresh timer during a modal dialog) --
        # and this must also happen even when the dialog is skipped, since
        # time still passes between selecting the row and clicking Close.
        position = self._get_live_position(ticket)
        if position is None:
            self._set_result(
                "Position closed before the close order was sent -- no action taken.", "error")
            return
        try:
            result = full_close(self.mt5, position)
        except Exception:
            self._set_result("Action failed (MT5 error).", "error")
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
            self._set_result("SL/TP must be numbers.", "error")
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self._set_result("Position no longer open.", "error")
            return
        try:
            result, error = apply_custom_sltp(self.mt5, position, sl, tp)
        except Exception:
            self._set_result("Action failed (MT5 error).", "error")
            return
        if error:
            self._set_result(error, "error")
            return
        self._show_result(result, "SL/TP updated.")
