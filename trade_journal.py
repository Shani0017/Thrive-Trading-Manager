import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta
import customtkinter as ctk
from gui import BG, CARD, CARD_ALT, BORDER, TEXT, MUTED, ACCENT, ACCENT_HOVER, GREEN, RED
from trade_records import build_trade_records
from trade_sources import load_sources, save_sources

QUICK_SOURCES = ["My Analysis", "XYZ Trader", "XYZ YouTube", "Thrive"]


class TradeJournalApp:
    """Full trade history: fetched from MT5's own closed-deal history (real
    data, not fabricated), with a running P&L summary, date-range and
    symbol filters, and a per-trade 'source' note (e.g. which trader/video/
    analysis the idea came from) that MT5 has no concept of, so it's stored
    locally via trade_sources.py."""

    def __init__(self, root, mt5, on_home):
        self.root = root
        self.mt5 = mt5
        self.on_home = on_home
        self.root.title("THRIVE Trading Journal")
        self.root.geometry("1120x760")
        # 630px is the exact point below which the source-editor's hint
        # label starts getting silently clipped (confirmed by direct
        # measurement, bisecting window heights) -- the 4 fixed sections
        # plus the closed-trades table's own natural minimum add up to
        # just over that. 640 covers it with a small buffer.
        self.root.minsize(960, 640)
        self.root.configure(fg_color=BG)

        self.date_range_days = 30
        self.symbol_filter = "All"
        self.selected_position_id = None
        self.sources = load_sources()
        self.records = []

        # Plain (non-scrolling) container, matching Trade Manager's layout
        # fix: header/summary/filters/source-editor are packed with their
        # natural height (no expand), so they always render in full no
        # matter how short the window gets, and only the closed-trades
        # table (packed with expand=True in _build_table) absorbs any extra
        # or short space. content.pack_propagate(False) is what makes this
        # work -- without it, content would resize itself to fit everything
        # at natural size and drag the whole window along with it. A
        # CTkScrollableFrame here previously meant shrinking the window hid
        # the filters/source-editor behind a scrollbar, which is exactly
        # the inconsistency being fixed (Trade Manager no longer does this).
        content = ctk.CTkFrame(root, fg_color=BG)
        content.pack(fill="both", expand=True)
        content.pack_propagate(False)

        self._build_header(content)
        self._build_summary(content)
        self._build_filters(content)
        self._build_table(content)
        self._build_source_editor(content)

        self._load_and_refresh()

    # ------------------------------------------------------------------

    def _build_header(self, root):
        bar = ctk.CTkFrame(root, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkButton(bar, text="← Home", width=72, height=24, font=ctk.CTkFont(size=10),
                      fg_color=CARD_ALT, hover_color=BORDER, text_color=TEXT,
                      command=self.on_home).pack(side="left")
        ctk.CTkLabel(bar, text="Trading Journal", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT).pack(side="left", padx=(12, 0))

    def _build_summary(self, root):
        card = ctk.CTkFrame(root, corner_radius=14, fg_color=CARD, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=16, pady=(0, 8))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=8)

        self.total_pnl_value = self._summary_cell(row, "Total P&L")
        self.win_rate_value = self._summary_cell(row, "Win Rate")
        self.total_trades_value = self._summary_cell(row, "Total Trades")

    def _summary_cell(self, parent, label):
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.pack(side="left", expand=True, fill="x")
        ctk.CTkLabel(cell, text=label, font=ctk.CTkFont(size=11), text_color=MUTED).pack(anchor="w")
        value = ctk.CTkLabel(cell, text="—", font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT)
        value.pack(anchor="w", pady=(1, 0))
        return value

    def _build_filters(self, root):
        bar = ctk.CTkFrame(root, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        bar.pack(fill="x", padx=16, pady=(0, 8))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(inner, text="Period", font=ctk.CTkFont(size=11), text_color=MUTED).pack(
            side="left", padx=(0, 8))
        self._period_buttons = {}
        for label, days in (("7D", 7), ("30D", 30), ("90D", 90), ("All", None)):
            btn = ctk.CTkButton(inner, text=label, width=46, height=24, font=ctk.CTkFont(size=10),
                                 command=lambda d=days: self._set_period(d))
            btn.pack(side="left", padx=4)
            self._period_buttons[days] = btn
        self._refresh_period_buttons()

        ctk.CTkLabel(inner, text="Symbol", font=ctk.CTkFont(size=11), text_color=MUTED).pack(
            side="left", padx=(24, 8))
        self.symbol_menu = ctk.CTkOptionMenu(
            inner, values=["All"], width=110, height=24, fg_color=CARD_ALT, button_color=CARD_ALT,
            button_hover_color=BORDER, dropdown_fg_color=CARD_ALT, text_color=TEXT,
            command=self._on_symbol_filter_change)
        self.symbol_menu.pack(side="left")

        ctk.CTkButton(inner, text="Refresh", width=72, height=24, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self._load_and_refresh).pack(side="right")

    def _refresh_period_buttons(self):
        for days, btn in self._period_buttons.items():
            active = days == self.date_range_days
            btn.configure(fg_color=ACCENT if active else CARD_ALT,
                          text_color=TEXT if active else MUTED,
                          hover_color=ACCENT_HOVER if active else BORDER)

    def _set_period(self, days):
        self.date_range_days = days
        self._refresh_period_buttons()
        self._load_and_refresh()

    def _on_symbol_filter_change(self, value):
        self.symbol_filter = value
        self._render_table()

    def _build_table(self, root):
        card = ctk.CTkFrame(root, corner_radius=14, fg_color=CARD, border_width=1, border_color=BORDER)
        card.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        ctk.CTkLabel(card, text="CLOSED TRADES", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=14, pady=(8, 4))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Journal.Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                         rowheight=22, font=("Segoe UI", 9), borderwidth=0)
        style.configure("Journal.Treeview.Heading", background=CARD_ALT, foreground=MUTED,
                         font=("Segoe UI", 9, "bold"), borderwidth=0, relief="flat")
        style.map("Journal.Treeview.Heading", background=[("active", BORDER)])
        style.map("Journal.Treeview", background=[("selected", "#123322")], foreground=[("selected", TEXT)])
        # Trade history can grow to hundreds of rows (unlike open positions,
        # which are usually just a handful) -- without a scrollbar, only the
        # first `height` rows were ever reachable, with no way to see older
        # trades. Styled to match the dark theme rather than the default
        # OS-native scrollbar chrome.
        style.configure("Journal.Vertical.TScrollbar", background=CARD_ALT, troughcolor=CARD,
                         bordercolor=CARD, arrowcolor=MUTED, relief="flat")
        style.map("Journal.Vertical.TScrollbar", background=[("active", BORDER)])

        columns = ("date", "symbol", "direction", "volume", "entry", "exit", "pnl", "source")
        headings = {"date": "Date", "symbol": "Symbol", "direction": "Dir", "volume": "Volume",
                    "entry": "Entry", "exit": "Exit", "pnl": "P&L", "source": "Source"}
        self._column_weights = {"date": 0.15, "symbol": 0.11, "direction": 0.08, "volume": 0.08,
                                 "entry": 0.12, "exit": 0.12, "pnl": 0.11, "source": 0.23}

        tree_wrap = ctk.CTkFrame(card, fg_color="transparent")
        tree_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        self.tree = ttk.Treeview(tree_wrap, columns=columns, show="headings", height=8,
                                  style="Journal.Treeview")
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, anchor="center", stretch=False, width=80)
        self.tree.tag_configure("win", foreground=GREEN)
        self.tree.tag_configure("loss", foreground=RED)

        tree_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview,
                                     style="Journal.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select_trade)
        self.tree.bind("<Configure>", self._on_tree_resize)

        self.table_hint_label = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11), text_color=MUTED)
        self.table_hint_label.pack(anchor="w", padx=14, pady=(0, 8))

    def _on_tree_resize(self, event):
        total_width = event.width
        if total_width <= 1:
            return
        for col, weight in self._column_weights.items():
            self.tree.column(col, width=max(40, int(total_width * weight)))

    def _build_source_editor(self, root):
        card = ctk.CTkFrame(root, corner_radius=14, fg_color=CARD, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(card, text="TRADE SOURCE", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=14, pady=(8, 4))
        ctk.CTkLabel(card, text="Where did this trade idea come from? Select a closed trade above, "
                                 "then type or pick a source.",
                     font=ctk.CTkFont(size=10), text_color=MUTED, wraplength=900,
                     justify="left").pack(anchor="w", padx=14, pady=(0, 6))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14)
        self.source_entry = ctk.CTkEntry(row, width=220, height=26, placeholder_text="e.g. My Analysis, XYZ Trader...")
        self.source_entry.pack(side="left")
        self.save_source_btn = ctk.CTkButton(row, text="Save", width=60, height=26, fg_color=ACCENT,
                                              hover_color=ACCENT_HOVER, command=self._save_source,
                                              state="disabled")
        self.save_source_btn.pack(side="left", padx=(8, 0))

        quick_row = ctk.CTkFrame(card, fg_color="transparent")
        quick_row.pack(fill="x", padx=14, pady=(6, 4))
        self._quick_source_buttons = []
        for label in QUICK_SOURCES:
            btn = ctk.CTkButton(quick_row, text=label, height=22, font=ctk.CTkFont(size=9),
                                 fg_color=CARD_ALT, hover_color=BORDER, text_color=TEXT,
                                 state="disabled", command=lambda l=label: self._quick_set_source(l))
            btn.pack(side="left", padx=(0, 6))
            self._quick_source_buttons.append(btn)

        self.source_hint_label = ctk.CTkLabel(card, text="Select a trade above to tag its source.",
                                               font=ctk.CTkFont(size=10), text_color=MUTED)
        self.source_hint_label.pack(anchor="w", padx=14, pady=(4, 8))

    # ------------------------------------------------------------------

    def _quick_set_source(self, label):
        self.source_entry.delete(0, tk.END)
        self.source_entry.insert(0, label)
        self._save_source()

    def _save_source(self):
        if self.selected_position_id is None:
            return
        value = self.source_entry.get().strip()
        self.sources[str(self.selected_position_id)] = value
        save_sources(self.sources)
        self._render_table()
        if value:
            self.source_hint_label.configure(text=f'Saved: "{value}"', text_color=GREEN)
        else:
            self.source_hint_label.configure(text="Cleared.", text_color=MUTED)

    def _on_select_trade(self, event):
        selection = self.tree.selection()
        if not selection:
            self.selected_position_id = None
            self.save_source_btn.configure(state="disabled")
            for btn in self._quick_source_buttons:
                btn.configure(state="disabled")
            self.source_entry.delete(0, tk.END)
            self.source_hint_label.configure(text="Select a trade above to tag its source.", text_color=MUTED)
            return
        position_id = selection[0]
        self.selected_position_id = position_id
        self.save_source_btn.configure(state="normal")
        for btn in self._quick_source_buttons:
            btn.configure(state="normal")
        self.source_entry.delete(0, tk.END)
        self.source_entry.insert(0, self.sources.get(position_id, ""))
        self.source_hint_label.configure(text="", text_color=MUTED)

    def _load_and_refresh(self):
        now = datetime.now()
        date_from = now - timedelta(days=self.date_range_days) if self.date_range_days else datetime(2000, 1, 1)
        try:
            deals = self.mt5.history_deals_get(date_from, now + timedelta(minutes=1))
        except Exception:
            deals = None
        deals = deals or ()
        self.records = build_trade_records(deals)

        symbols = sorted({r["symbol"] for r in self.records})
        self.symbol_menu.configure(values=["All"] + symbols)
        if self.symbol_filter not in (["All"] + symbols):
            self.symbol_filter = "All"
            self.symbol_menu.set("All")

        self._render_table()

    def _render_table(self):
        self.tree.delete(*self.tree.get_children())
        filtered = [r for r in self.records
                    if self.symbol_filter == "All" or r["symbol"] == self.symbol_filter]

        total_pnl = sum(r["pnl"] for r in filtered)
        wins = sum(1 for r in filtered if r["pnl"] > 0)
        total = len(filtered)
        win_rate = (wins / total * 100) if total else 0.0

        self.total_pnl_value.configure(
            text=f"{'+' if total_pnl >= 0 else ''}${total_pnl:,.2f}",
            text_color=GREEN if total_pnl >= 0 else RED)
        self.win_rate_value.configure(text=f"{win_rate:.1f}%")
        self.total_trades_value.configure(text=str(total))
        self.table_hint_label.configure(
            text="" if filtered else "No closed trades in this period/symbol.")

        for r in filtered:
            date_str = datetime.fromtimestamp(r["close_time"]).strftime("%Y-%m-%d %H:%M")
            source = self.sources.get(str(r["position_id"]), "—")
            values = (date_str, r["symbol"], r["direction"], r["volume"],
                      f"{r['entry_price']:.5f}", f"{r['exit_price']:.5f}",
                      f"{'+' if r['pnl'] >= 0 else ''}{r['pnl']:.2f}", source or "—")
            self.tree.insert("", "end", iid=str(r["position_id"]), values=values,
                              tags=("win" if r["pnl"] >= 0 else "loss",))
