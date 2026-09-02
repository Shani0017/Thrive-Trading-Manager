import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from actions import apply_breakeven, half_close, full_close, apply_custom_sltp


class TradeManagerApp:
    REFRESH_MS = 2000
    RECONNECT_MS = 5000

    def __init__(self, root, mt5):
        self.root = root
        self.mt5 = mt5
        self.root.title("MT5 Trade Manager")
        self.connected = False
        self.selected_ticket = None
        self.positions_by_ticket = {}
        self._refresh_job = None
        self._reconnect_job = None

        self.status_label = tk.Label(root, text="Connecting to MT5...", fg="black",
                                      font=("Segoe UI", 10, "bold"))
        self.status_label.pack(fill="x", padx=8, pady=6)

        columns = ("symbol", "direction", "volume", "entry", "current", "pnl", "sl", "tp")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", height=10)
        headings = {
            "symbol": "Symbol", "direction": "Dir", "volume": "Volume",
            "entry": "Entry", "current": "Current", "pnl": "P&L",
            "sl": "SL", "tp": "TP",
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=90, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self._build_action_panel()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._try_connect()
        self._refresh_job = self.root.after(self.REFRESH_MS, self._refresh_loop)

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
            self.status_label.config(text=f"Connected to MT5 (account {login})", fg="dark green")
        else:
            self.connected = False
            self.status_label.config(text="MT5 not connected — please open and log into MetaTrader 5",
                                      fg="red")
            self._reconnect_job = self.root.after(self.RECONNECT_MS, self._try_connect)

    def _refresh_loop(self):
        if self.connected:
            self._refresh_positions()
        self._refresh_job = self.root.after(self.REFRESH_MS, self._refresh_loop)

    def _handle_connection_lost(self):
        self.connected = False
        self.status_label.config(text="MT5 not connected — please open and log into MetaTrader 5",
                                  fg="red")
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
        position = self.positions_by_ticket[self.selected_ticket]
        self.sl_entry.delete(0, tk.END)
        self.sl_entry.insert(0, f"{position.sl:.5f}")
        self.tp_entry.delete(0, tk.END)
        self.tp_entry.insert(0, f"{position.tp:.5f}")

    def _build_action_panel(self):
        frame = tk.Frame(self.root)
        frame.pack(fill="x", padx=8, pady=8)

        self.be_exact_btn = tk.Button(frame, text="Breakeven (Exact)", command=self._on_breakeven_exact)
        self.be_exact_btn.grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        self.pips_entry = tk.Entry(frame, width=6)
        self.pips_entry.grid(row=0, column=1, padx=(4, 0), pady=4)
        self.pips_entry.bind("<KeyRelease>", self._on_pips_entry_change)

        self.be_pips_btn = tk.Button(frame, text="Breakeven + Pips", command=self._on_breakeven_pips)
        self.be_pips_btn.grid(row=0, column=2, padx=4, pady=4, sticky="ew")

        self.half_close_btn = tk.Button(frame, text="Half Close", command=self._on_half_close)
        self.half_close_btn.grid(row=0, column=3, padx=4, pady=4, sticky="ew")

        self.full_close_btn = tk.Button(frame, text="Full Close", command=self._on_full_close, fg="red")
        self.full_close_btn.grid(row=0, column=4, padx=4, pady=4, sticky="ew")

        tk.Label(frame, text="SL:").grid(row=1, column=0, sticky="e")
        self.sl_entry = tk.Entry(frame, width=12)
        self.sl_entry.grid(row=1, column=1, padx=4, pady=4)

        tk.Label(frame, text="TP:").grid(row=1, column=2, sticky="e")
        self.tp_entry = tk.Entry(frame, width=12)
        self.tp_entry.grid(row=1, column=3, padx=4, pady=4)

        self.apply_sltp_btn = tk.Button(frame, text="Apply SL/TP", command=self._on_apply_sltp)
        self.apply_sltp_btn.grid(row=1, column=4, padx=4, pady=4, sticky="ew")

        self.result_label = tk.Label(self.root, text="", fg="black")
        self.result_label.pack(fill="x", padx=8, pady=(0, 8))

        self.action_widgets = [
            self.be_exact_btn, self.pips_entry, self.be_pips_btn,
            self.half_close_btn, self.full_close_btn,
            self.sl_entry, self.tp_entry, self.apply_sltp_btn,
        ]
        self._set_action_panel_enabled(False)

    def _set_action_panel_enabled(self, enabled: bool):
        self._panel_enabled = enabled
        state = "normal" if enabled else "disabled"
        for widget in self.action_widgets:
            widget.config(state=state)
        if enabled:
            self._on_pips_entry_change(None)  # re-evaluate pips-button state for the new selection
        self.result_label.config(text="")

    def _on_pips_entry_change(self, event):
        value = self.pips_entry.get().strip()
        try:
            pips = float(value)
            valid = pips > 0
        except ValueError:
            valid = False
        self.be_pips_btn.config(state="normal" if (valid and self._panel_enabled) else "disabled")

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
            self.result_label.config(text="Action could not be completed.", fg="red")
            return
        if result.retcode == self.mt5.TRADE_RETCODE_DONE:
            self.result_label.config(text=success_message, fg="dark green")
        else:
            self.result_label.config(
                text=f"Broker rejected: {result.retcode} {getattr(result, 'comment', '')}", fg="red")

    def _on_breakeven_exact(self):
        if self.selected_ticket is None:
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self.result_label.config(text="Position no longer open.", fg="red")
            return
        try:
            result = apply_breakeven(self.mt5, position, pips=0.0)
        except Exception:
            self.result_label.config(text="Action failed (MT5 error).", fg="red")
            return
        self._show_result(result, "SL moved to breakeven.")

    def _on_breakeven_pips(self):
        if self.selected_ticket is None:
            return
        try:
            pips = float(self.pips_entry.get().strip())
        except ValueError:
            self.result_label.config(text="Enter a valid positive pip value first.", fg="red")
            return
        if pips <= 0:
            self.result_label.config(text="Pips must be a positive number.", fg="red")
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self.result_label.config(text="Position no longer open.", fg="red")
            return
        try:
            result = apply_breakeven(self.mt5, position, pips=pips)
        except Exception:
            self.result_label.config(text="Action failed (MT5 error).", fg="red")
            return
        self._show_result(result, f"SL moved to breakeven +{pips:g} pips.")

    def _on_half_close(self):
        if self.selected_ticket is None:
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self.result_label.config(text="Position no longer open.", fg="red")
            return
        try:
            result = half_close(self.mt5, position)
        except Exception:
            self.result_label.config(text="Action failed (MT5 error).", fg="red")
            return
        if result is None:
            self.result_label.config(
                text="Cannot half-close: half the volume is below the broker's minimum lot.", fg="red")
            return
        self._show_result(result, "Half of the position closed.")

    def _on_full_close(self):
        if self.selected_ticket is None:
            return
        ticket = self.selected_ticket
        position = self._get_live_position(ticket)
        if position is None:
            self.result_label.config(text="Position no longer open.", fg="red")
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
            self.result_label.config(
                text="Position closed before confirmation completed -- no action taken.", fg="red")
            return
        try:
            result = full_close(self.mt5, position)
        except Exception:
            self.result_label.config(text="Action failed (MT5 error).", fg="red")
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
            self.result_label.config(text="SL/TP must be numbers.", fg="red")
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self.result_label.config(text="Position no longer open.", fg="red")
            return
        try:
            result, error = apply_custom_sltp(self.mt5, position, sl, tp)
        except Exception:
            self.result_label.config(text="Action failed (MT5 error).", fg="red")
            return
        if error:
            self.result_label.config(text=error, fg="red")
            return
        self._show_result(result, "SL/TP updated.")
