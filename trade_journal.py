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
        # 450px is the exact point below which the table's own hint label
        # starts getting silently clipped (confirmed by direct measurement,
        # bisecting window heights) -- the 3 fixed sections (header,
        # summary, filters) plus the closed-trades table's own natural
        # minimum add up to just over that. Lower than before since
        # removing the standalone source-editor panel (source is now
        # edited inline in the table) shrank the fixed-section total.
        self.root.minsize(960, 470)
        self.root.configure(fg_color=BG)

        self.date_range_days = 30
        self.symbol_filter = "All"
        self.sources = load_sources()
        self.records = []
        self._source_editor = None  # the inline Combobox, while a Source cell is being edited

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
        card.pack(fill="both", expand=True, padx=16, pady=(0, 12))

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
        self.tree.bind("<Configure>", self._on_tree_resize)
        # Source is an optional per-trade note, not something every trade
        # needs -- rather than a permanently-visible editor panel below the
        # table, clicking directly on a row's Source cell opens an inline
        # editor right there, matching how spreadsheet-style tables edit a
        # single cell in place.
        self.tree.bind("<Button-1>", self._on_tree_click)

        self.table_hint_label = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11), text_color=MUTED)
        self.table_hint_label.pack(anchor="w", padx=14, pady=(0, 8))

    def _on_tree_resize(self, event):
        total_width = event.width
        if total_width <= 1:
            return
        for col, weight in self._column_weights.items():
            self.tree.column(col, width=max(40, int(total_width * weight)))

    # ------------------------------------------------------------------

    def _on_tree_click(self, event):
        self._close_source_editor()
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        # identify_column returns a "#N" display-index string whose numbering
        # convention (0- vs 1-based) isn't consistent across Tk versions --
        # matching the click's x position against each column's own bbox
        # sidesteps that entirely and is unambiguous.
        source_bbox = self.tree.bbox(row_id, "source")
        if source_bbox and source_bbox[0] <= event.x <= source_bbox[0] + source_bbox[2]:
            self._open_source_editor(row_id)

    def _open_source_editor(self, position_id: str):
        bbox = self.tree.bbox(position_id, "source")
        if not bbox:
            return
        x, y, width, height = bbox
        current = self.sources.get(position_id, "")

        editor = ttk.Combobox(self.tree, values=QUICK_SOURCES, font=("Segoe UI", 9))
        editor.insert(0, current)
        editor.select_range(0, tk.END)
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        self._source_editor = editor

        def commit(_event=None):
            self._save_source(position_id, editor.get().strip())
            self._close_source_editor()

        def cancel(_event=None):
            self._close_source_editor()

        editor.bind("<Return>", commit)
        editor.bind("<<ComboboxSelected>>", commit)
        editor.bind("<Escape>", cancel)
        editor.bind("<FocusOut>", commit)

    def _close_source_editor(self):
        if self._source_editor is not None:
            editor, self._source_editor = self._source_editor, None
            editor.destroy()

    def _save_source(self, position_id: str, value: str):
        self.sources[position_id] = value
        save_sources(self.sources)
        self.tree.set(position_id, "source", value or "—")

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
