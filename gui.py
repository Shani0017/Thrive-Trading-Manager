import tkinter as tk
from tkinter import ttk


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

        self._try_connect()
        self.root.after(self.REFRESH_MS, self._refresh_loop)

    def _try_connect(self):
        ok = self.mt5.initialize()
        if ok:
            self.connected = True
            account = self.mt5.account_info()
            login = account.login if account else "?"
            self.status_label.config(text=f"Connected to MT5 (account {login})", fg="dark green")
        else:
            self.connected = False
            self.status_label.config(text="MT5 not connected — please open and log into MetaTrader 5",
                                      fg="red")
            self.root.after(self.RECONNECT_MS, self._try_connect)

    def _refresh_loop(self):
        if self.connected:
            self._refresh_positions()
        self.root.after(self.REFRESH_MS, self._refresh_loop)

    def _refresh_positions(self):
        positions = self.mt5.positions_get()
        if positions is None:
            positions = ()
        self.positions_by_ticket = {p.ticket: p for p in positions}

        selected_still_open = self.selected_ticket in self.positions_by_ticket

        self.tree.delete(*self.tree.get_children())
        for p in positions:
            direction = "BUY" if p.type == self.mt5.POSITION_TYPE_BUY else "SELL"
            self.tree.insert("", "end", iid=str(p.ticket), values=(
                p.symbol, direction, p.volume,
                f"{p.price_open:.5f}", f"{p.price_current:.5f}",
                f"{p.profit:.2f}", f"{p.sl:.5f}", f"{p.tp:.5f}",
            ))

        if selected_still_open:
            self.tree.selection_set(str(self.selected_ticket))
        else:
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
