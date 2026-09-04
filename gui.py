import os
import sys
from datetime import datetime
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from PIL import Image
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import FuncFormatter
from actions import apply_breakeven, half_close, full_close, apply_custom_sltp
from trade_logic import pip_size as _pip_size, breakeven_price as _breakeven_price

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# Palette matched to thriveweb3.net's actual brand: pure black background,
# vivid green accent (Tailwind green-500/400), white headline text.
BG = "#000000"
CARD = "#0a0a0a"
CARD_ALT = "#141414"
BORDER = "#242424"
TEXT = "#ffffff"
MUTED = "#9ca3af"
ACCENT = "#22c55e"
ACCENT_HOVER = "#16a34a"
GREEN = "#4ade80"
GREEN_BG = "#123322"
RED = "#f87171"
RED_BG = "#3a1414"
AMBER = "#fbbf24"
AMBER_BG = "#3a2e0f"

_TONE_STYLES = {
    "success": (GREEN_BG, GREEN),
    "error": (RED_BG, RED),
    "warning": (AMBER_BG, AMBER),
    "neutral": (CARD_ALT, MUTED),
}


def _resource_path(relative_path: str) -> str:
    """Resolves a bundled asset both in normal dev runs and inside a
    PyInstaller onefile .exe, where bundled data lives under a temporary
    _MEIPASS extraction directory instead of next to this script."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class TradeManagerApp:
    # How often the app polls MT5 for open-position/account updates. MT5's
    # Python API has no push/subscribe mechanism -- positions_get() must be
    # polled -- so some delay is unavoidable, but a single call is cheap
    # enough that polling every 500ms keeps the UI feeling near-instant.
    REFRESH_MS = 500
    RECONNECT_MS = 5000
    # The chart redraws its whole figure every tick (clear + replot ~100
    # candles), which is far more expensive than the text-only position/
    # account refresh above -- 3s keeps it visually live without redrawing
    # matplotlib on every single 500ms position-poll tick.
    CHART_REFRESH_MS = 3000
    CHART_BAR_COUNT = 100

    def __init__(self, root, mt5, on_home=None):
        self.root = root
        self.mt5 = mt5
        self.on_home = on_home
        self.root.title("THRIVE Trade Manager")
        self.root.geometry("1180x980")
        # The 4 fixed sections (topbar, positions, detail panel, footer) sum
        # to ~661px, and Account Overview's 2-column grid of 5 stats (see
        # _build_account_overview) needs ~265px of its own to show Balance,
        # Equity, Margin, Free Margin, and Profit/Loss without any of them
        # getting silently clipped (confirmed by direct measurement -- this
        # is what was cutting off Free Margin/Profit-Loss below the ~900px
        # window height this app shipped with before). 960 is that ~926px
        # requirement plus a safety buffer; minsize enforces it at the OS
        # level instead of letting content overflow past the window's edge.
        self.root.minsize(1000, 960)
        self.root.configure(fg_color=BG)
        self.connected = False
        self.selected_ticket = None
        self.positions_by_ticket = {}
        self.be_mode = "exact"
        self._refresh_job = None
        self._reconnect_job = None
        self._chart_job = None

        # Plain (non-scrolling) container: every section the user acts on --
        # topbar, open positions, breakeven/SL/TP/close, footer -- is packed
        # with its natural height (no expand), so it always renders at full
        # size no matter how short the window gets. Only the chart+account-
        # overview row is packed with expand=True, so it alone absorbs
        # whatever space is left over (or squeezed) once the fixed sections
        # take theirs -- this is pack's standard "one expanding child soaks
        # up the slack" behavior, which degrades gracefully (a smaller
        # chart/stat panel) instead of clipping a button or field the user
        # actually needs to click. content.pack_propagate(False) is what
        # makes this work: without it, content resizes ITSELF to fit the
        # combined natural height of everything packed into it, and since
        # content is itself packed fill="both"/expand=True into root, that
        # forces the whole window to snap back to that combined size
        # regardless of what geometry() or the user's own resize says. This
        # replaces an earlier CTkScrollableFrame approach: scrolling hid the
        # action controls behind a scrollbar at smaller window sizes, which
        # is exactly the "options disappear when I shrink the window"
        # problem being fixed here.
        content = ctk.CTkFrame(root, fg_color=BG)
        content.pack(fill="both", expand=True)
        content.pack_propagate(False)

        self._build_topbar(content)

        # Open Positions and Account Overview have swapped places per user
        # request: Positions is now the full-width section right under the
        # topbar (the most immediately useful info), and Account Overview
        # moved into the row beside the chart -- which otherwise stays
        # exactly as it was. The detail panel stays full-width below both,
        # since it needs the full row's width for its four side-by-side
        # sections (see _build_detail_panel's own comment on why a narrow
        # column caused real text truncation there).
        self._build_positions_panel(content)

        chart_overview_row = ctk.CTkFrame(content, fg_color="transparent")
        chart_overview_row.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        chart_overview_row.pack_propagate(False)

        # Both columns get pack_propagate(False) with widths recomputed as a
        # fixed proportion of the row's actual width on every resize (same
        # pattern as the positions/journal tables' _on_tree_resize). Without
        # this, the matplotlib chart's natural pixel width (from its figsize
        # in inches * dpi) can exceed the space actually available once the
        # window is narrower than ~1300px, and pack's default behavior is to
        # let a child's requested size grow the row instead of shrinking the
        # child -- pushing Account Overview off the right edge of the window
        # with no horizontal scrollbar to reach it.
        self.chart_col = ctk.CTkFrame(chart_overview_row, fg_color="transparent")
        self.chart_col.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.chart_col.pack_propagate(False)

        self.overview_col = ctk.CTkFrame(chart_overview_row, fg_color="transparent")
        self.overview_col.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.overview_col.pack_propagate(False)

        chart_overview_row.bind("<Configure>", self._on_chart_row_resize)

        self._build_chart_panel(self.chart_col)
        self._build_account_overview(self.overview_col)

        self._build_detail_panel(content)

        self._build_footer(content)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._try_connect()
        self._refresh_job = self.root.after(self.REFRESH_MS, self._refresh_loop)
        self._chart_job = self.root.after(self.CHART_REFRESH_MS, self._chart_loop)

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_topbar(self, root):
        bar = ctk.CTkFrame(root, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(12, 8))

        if self.on_home:
            ctk.CTkButton(bar, text="← Home", width=72, height=24, font=ctk.CTkFont(size=10),
                          fg_color=CARD_ALT, hover_color=BORDER, text_color=TEXT,
                          command=self._go_home).pack(side="left", padx=(0, 16))

        try:
            logo_img = Image.open(_resource_path("assets/logo.png"))
            self._logo_image = ctk.CTkImage(logo_img, size=(100, 36))
            ctk.CTkLabel(bar, image=self._logo_image, text="").pack(side="left", padx=(0, 20))
        except Exception:
            ctk.CTkLabel(bar, text="THRIVE", text_color=TEXT,
                         font=ctk.CTkFont(size=16, weight="bold")).pack(side="left", padx=(0, 20))

        self.status_badge = ctk.CTkFrame(bar, corner_radius=14, fg_color=AMBER_BG)
        self.status_badge.pack(side="left", padx=(0, 16))
        self.status_label = ctk.CTkLabel(self.status_badge, text="● Connecting...",
                                          font=ctk.CTkFont(size=12, weight="bold"), text_color=AMBER)
        self.status_label.pack(padx=10, pady=4)

        # Account / Open Positions / Active Symbol chips anchored to the top
        # RIGHT of the bar (logo + connection status stay on the left).
        # Packed with side="right" in reverse visual order: the first widget
        # packed to a side claims the outermost slice on that side, so
        # packing Active Symbol first, then Open Positions, then Account
        # produces the desired left-to-right reading order (Account, Open
        # Positions, Active Symbol) ending flush against the right edge.
        self.active_symbol_chip = ctk.CTkFrame(bar, corner_radius=10, fg_color=CARD, border_width=1,
                                                 border_color=BORDER)
        self.active_symbol_chip.pack(side="right")
        self.active_symbol_value = ctk.CTkLabel(self.active_symbol_chip, text="—",
                                                  font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT)
        self.active_symbol_value.pack(padx=12, pady=(4, 0))
        ctk.CTkLabel(self.active_symbol_chip, text="Active Symbol", font=ctk.CTkFont(size=9),
                     text_color=MUTED).pack(padx=12, pady=(0, 4))

        self.position_count_chip = ctk.CTkFrame(bar, corner_radius=10, fg_color=CARD, border_width=1,
                                                  border_color=BORDER)
        self.position_count_chip.pack(side="right", padx=(0, 12))
        self.position_count_value = ctk.CTkLabel(self.position_count_chip, text="0",
                                                   font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT)
        self.position_count_value.pack(padx=12, pady=(4, 0))
        ctk.CTkLabel(self.position_count_chip, text="Open Positions", font=ctk.CTkFont(size=9),
                     text_color=MUTED).pack(padx=12, pady=(0, 4))

        account_chip = ctk.CTkFrame(bar, corner_radius=10, fg_color=CARD, border_width=1,
                                     border_color=BORDER)
        account_chip.pack(side="right", padx=(0, 12))
        inner = ctk.CTkFrame(account_chip, fg_color="transparent")
        inner.pack(padx=10, pady=4)
        ctk.CTkLabel(inner, text="Account", font=ctk.CTkFont(size=10), text_color=MUTED).pack(
            side="left", padx=(0, 8))
        self.account_number_label = ctk.CTkLabel(inner, text="—", font=ctk.CTkFont(size=12, weight="bold"),
                                                   text_color=TEXT)
        self.account_number_label.pack(side="left", padx=(0, 6))
        ctk.CTkButton(inner, text="Copy", width=40, height=20, font=ctk.CTkFont(size=9),
                      fg_color=CARD_ALT, hover_color=BORDER, text_color=MUTED,
                      command=self._copy_account_number).pack(side="left")

    def _copy_account_number(self):
        text = self.account_number_label.cget("text")
        if text and text != "—":
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _build_account_overview(self, root):
        # Now sits beside the chart (shares a row, roughly half window
        # width) instead of spanning the full window, so fill="both"/
        # expand=True matches the chart's height and no extra outer padx is
        # needed -- the wrapping column already provides that margin.
        card = ctk.CTkFrame(root, corner_radius=14, fg_color=CARD, border_width=1, border_color=BORDER)
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(card, text="ACCOUNT OVERVIEW", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=14, pady=(8, 4))

        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 8))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        # A 2-column grid (Balance/Equity, Margin/Free Margin, then P&L
        # spanning both) rather than 5 fully-stacked rows: stacking all 5
        # needs ~386px of natural height, comfortably more than this row
        # ever has once it shares space with the chart -- the bottom
        # stats (Free Margin, P&L) were silently clipped as a result. This
        # halves the vertical footprint while staying visually distinct
        # from the original single-row-of-5 layout that wasted horizontal
        # space (the thing "make it vertical" was fixing in the first
        # place).
        self.balance_value = self._stat_cell(grid, "Balance", row=0, col=0)
        self.equity_value = self._stat_cell(grid, "Equity", row=0, col=1)
        self.margin_value = self._stat_cell(grid, "Margin", row=1, col=0)
        self.free_margin_value = self._stat_cell(grid, "Free Margin", row=1, col=1)
        self.profit_value, self.profit_pct_value = self._stat_cell(
            grid, "Profit / Loss", row=2, col=0, colspan=2, with_pct=True)

    def _stat_cell(self, parent, label, row, col, colspan=1, with_pct=False):
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.grid(row=row, column=col, columnspan=colspan, sticky="w", pady=(0, 6),
                  padx=(0, 12) if col == 0 and colspan == 1 else 0)
        ctk.CTkLabel(cell, text=label, font=ctk.CTkFont(size=10), text_color=MUTED).pack(anchor="w")
        value = ctk.CTkLabel(cell, text="—", font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT)
        value.pack(anchor="w", pady=(1, 0))
        if with_pct:
            pct = ctk.CTkLabel(cell, text="", font=ctk.CTkFont(size=11), text_color=MUTED)
            pct.pack(anchor="w")
            return value, pct
        return value

    def _build_positions_panel(self, root):
        # Full-width, standalone section right under the topbar (swapped
        # with Account Overview per user request) -- fill="x" only (not
        # "both"/expand=True): standing alone rather than sharing a row with
        # something taller, an expanding card here would stretch to consume
        # leftover scroll space, turning a short table into a mostly-empty
        # box (the exact bug already fixed once before in this file).
        card = ctk.CTkFrame(root, corner_radius=14, fg_color=CARD, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=16, pady=(0, 8))

        self.positions_title = ctk.CTkLabel(card, text="OPEN POSITIONS (0)",
                                             font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED)
        self.positions_title.pack(anchor="w", padx=14, pady=(8, 4))

        self._setup_treeview_style()

        columns = ("symbol", "direction", "volume", "entry", "current", "pnl", "pips", "sl", "tp")
        headings = {
            "symbol": "Symbol", "direction": "Dir", "volume": "Vol",
            "entry": "Entry", "current": "Current", "pnl": "P&L",
            "pips": "Pips", "sl": "SL", "tp": "TP",
        }
        # Relative shares of the table's actual width (sums to 1.0), applied
        # in pixels by _on_tree_resize below -- fixed pixel widths (the
        # original design) don't fit once this table shares a row with the
        # chart instead of spanning the full window, and ttk.Treeview
        # neither shrinks columns to fit nor offers horizontal scrolling on
        # its own, so columns silently ran off the visible edge with no way
        # to reach them. Recomputing on every resize keeps all 9 columns
        # visible at whatever width is actually available.
        self._column_weights = {
            "symbol": 0.14, "direction": 0.10, "volume": 0.08, "entry": 0.14,
            "current": 0.14, "pnl": 0.12, "pips": 0.08, "sl": 0.10, "tp": 0.10,
        }
        self.tree = ttk.Treeview(card, columns=columns, show="headings", height=5,
                                  style="Positions.Treeview")
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, anchor="center", stretch=False, width=60)
        self.tree.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Configure>", self._on_tree_resize)

        self.table_summary_label = ctk.CTkLabel(card, text="0 position(s)  •  Total P/L: $0.00",
                                                  font=ctk.CTkFont(size=11), text_color=MUTED)
        self.table_summary_label.pack(anchor="w", padx=14, pady=(0, 8))

    def _on_tree_resize(self, event):
        total_width = event.width
        if total_width <= 1:
            return
        for col, weight in self._column_weights.items():
            self.tree.column(col, width=max(30, int(total_width * weight)))

    def _on_chart_row_resize(self, event):
        total_width = event.width
        height = event.height
        if total_width <= 1 or height <= 1:
            return
        gap = 16  # the (0, 8) + (8, 0) padx between the two columns
        # Account Overview's 2-column grid only needs ~156px of natural
        # width (confirmed by direct measurement) -- giving it a fixed 36%
        # share of the row left most of it empty (visible as dead space to
        # the right of the stat labels). Capping its width and handing
        # everything else to the chart makes the chart the dominant,
        # actually-useful element instead.
        overview_width = min(340, max(220, int((total_width - gap) * 0.22)))
        chart_width = max(200, total_width - gap - overview_width)
        # Height is also passed through (not just width): this row is the
        # one section packed with expand=True (see the content.pack_
        # propagate(False) comment in __init__), so it's the one that
        # actually shrinks/grows as the window is resized -- both columns'
        # height changes along with their width.
        self.chart_col.configure(width=chart_width, height=height)
        self.overview_col.configure(width=overview_width, height=height)

    def _setup_treeview_style(self):
        """ttk.Treeview has no CustomTkinter equivalent (CTk provides no table
        widget), so it's embedded here and themed by hand to match the dark
        card chrome around it -- a standard pattern for CustomTkinter apps
        that need tabular data."""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Positions.Treeview", background=CARD, fieldbackground=CARD,
                         foreground=TEXT, rowheight=22, font=("Segoe UI", 9), borderwidth=0)
        style.configure("Positions.Treeview.Heading", background=CARD_ALT, foreground=MUTED,
                         font=("Segoe UI", 9, "bold"), borderwidth=0, relief="flat")
        style.map("Positions.Treeview.Heading", background=[("active", BORDER)])
        style.map("Positions.Treeview", background=[("selected", "#1f3a5f")],
                  foreground=[("selected", TEXT)])

    def _make_number_field(self, parent, width=80, step=0.1, decimals=5, default="",
                            sign_fn=None, seed_fn=None):
        """A numeric entry with small +/- steppers, matching the reference
        mockup's spinner inputs. Returns (frame, entry).

        sign_fn (optional): called on every bump to get +1/-1, letting the
        up-arrow mean different things depending on context -- e.g. for a
        SELL position's Take Profit, "up" should actually decrease the
        price (since TP must be BELOW current price to be valid, and lower
        is more profit on a sell), not just add to whatever's typed.
        Defaults to always +1 (up = increase), which is what plain fields
        like the breakeven pips offset want.

        seed_fn (optional): called to get a starting value when the field
        is empty and a stepper is clicked -- without this, bumping from an
        empty field starts at 0, which for a real price (e.g. Gold at
        ~4436) needs dozens of clicks to reach anything meaningful.

        decimals may also be a callable (returning an int) instead of a
        fixed number -- SL/TP fields need this to match whichever symbol
        is currently selected (2 for Gold, 5 for most forex pairs)."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        entry = ctk.CTkEntry(frame, width=width, height=26, border_color=BORDER,
                              fg_color=CARD, text_color=TEXT)
        if default:
            entry.insert(0, default)
        entry.pack(side="left")
        stepper = ctk.CTkFrame(frame, fg_color="transparent")
        stepper.pack(side="left", padx=(2, 0))

        def _bump(direction):
            text = entry.get().strip()
            if text:
                try:
                    val = float(text)
                except ValueError:
                    val = 0.0
            else:
                val = seed_fn() if seed_fn else 0.0
            sign = sign_fn() if sign_fn else 1
            dec = decimals() if callable(decimals) else decimals
            entry.delete(0, tk.END)
            entry.insert(0, f"{val + step * sign * direction:.{dec}f}")
            # Clicking the ▲/▼ button moves keyboard focus to the BUTTON,
            # not the entry -- so a synthetic <KeyRelease> fired without
            # first re-focusing the entry silently doesn't invoke whatever
            # is bound to it (confirmed directly: Tk only dispatches a
            # focus-less virtual key event to whichever widget currently
            # holds focus). That meant every KeyRelease-driven live update
            # (the breakeven SL preview, risk/reward) never refreshed when
            # the stepper was used, only when actually typing.
            entry.focus_set()
            entry.event_generate("<KeyRelease>")

        ctk.CTkButton(stepper, text="▲", width=18, height=15, font=ctk.CTkFont(size=8),
                      fg_color=CARD, text_color=MUTED, hover_color=BORDER,
                      command=lambda: _bump(1)).pack()
        ctk.CTkButton(stepper, text="▼", width=18, height=15, font=ctk.CTkFont(size=8),
                      fg_color=CARD, text_color=MUTED, hover_color=BORDER,
                      command=lambda: _bump(-1)).pack()
        return frame, entry

    def _build_detail_panel(self, root):
        """Full-width horizontal layout: a fixed-width sidebar (the original
        design) forced Breakeven/Stop Loss/Take Profit/Close into a single
        420px-wide vertical stack, which caused real text truncation and
        overlap ("Current Price" clipped, the Risk/Reward and "Validated for
        ... position" labels overlapping each other). Laying the four
        sections out side-by-side across the full window width gives each
        one enough room."""
        card = ctk.CTkFrame(root, corner_radius=14, fg_color=CARD, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=16, pady=(0, 8))

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(8, 4))
        self.detail_symbol_label = ctk.CTkLabel(header, text="No position selected",
                                                 font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT)
        self.detail_symbol_label.pack(side="left")
        self.detail_direction_badge = ctk.CTkFrame(header, corner_radius=6, fg_color=CARD_ALT)
        self.detail_direction_badge.pack(side="left", padx=(10, 0))
        self.detail_direction_label = ctk.CTkLabel(self.detail_direction_badge, text="",
                                                     font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED)
        self.detail_direction_label.pack(padx=10, pady=3)
        self.detail_lots_label = ctk.CTkLabel(header, text="— lots", font=ctk.CTkFont(size=12),
                                               text_color=MUTED)
        self.detail_lots_label.pack(side="left", padx=(14, 0))
        self.detail_pl_label = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=16, weight="bold"),
                                             text_color=TEXT)
        self.detail_pl_label.pack(side="right")
        self.detail_pl_pips_label = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=11),
                                                   text_color=MUTED)
        self.detail_pl_pips_label.pack(side="right", padx=(0, 8))

        price_row = ctk.CTkFrame(card, fg_color=CARD_ALT, corner_radius=10)
        price_row.pack(fill="x", padx=14, pady=(4, 8))
        entry_cell = ctk.CTkFrame(price_row, fg_color="transparent")
        entry_cell.pack(side="left", padx=10, pady=6)
        ctk.CTkLabel(entry_cell, text="Entry Price", font=ctk.CTkFont(size=10), text_color=MUTED).pack(anchor="w")
        self.detail_entry_price_label = ctk.CTkLabel(entry_cell, text="—",
                                                       font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT)
        self.detail_entry_price_label.pack(anchor="w")
        ctk.CTkLabel(price_row, text="→", font=ctk.CTkFont(size=14), text_color=MUTED).pack(side="left")
        current_cell = ctk.CTkFrame(price_row, fg_color="transparent")
        current_cell.pack(side="left", padx=10, pady=6)
        ctk.CTkLabel(current_cell, text="Current Price", font=ctk.CTkFont(size=10), text_color=MUTED).pack(anchor="w")
        self.detail_current_price_label = ctk.CTkLabel(current_cell, text="—",
                                                         font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT)
        self.detail_current_price_label.pack(anchor="w")
        ctk.CTkLabel(price_row, text="Risk / Reward:", font=ctk.CTkFont(size=10), text_color=MUTED).pack(
            side="left", padx=(30, 6))
        self.rr_value_label = ctk.CTkLabel(price_row, text="—", font=ctk.CTkFont(size=12, weight="bold"),
                                            text_color=TEXT)
        self.rr_value_label.pack(side="left")
        self.validated_label = ctk.CTkLabel(price_row, text="", font=ctk.CTkFont(size=10), text_color=MUTED)
        self.validated_label.pack(side="right", padx=14)

        # --- Breakeven | Stop Loss | Take Profit | Close Position, side by side ---
        actions_row = ctk.CTkFrame(card, fg_color="transparent")
        actions_row.pack(fill="x", padx=14, pady=(0, 10))

        be_box = ctk.CTkFrame(actions_row, fg_color=CARD_ALT, corner_radius=10)
        be_box.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ctk.CTkLabel(be_box, text="BREAKEVEN", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=10, pady=(6, 4))
        toggle_row = ctk.CTkFrame(be_box, fg_color=CARD, corner_radius=8)
        toggle_row.pack(fill="x", padx=12)
        self.be_exact_toggle = ctk.CTkButton(toggle_row, text="Exact", height=24,
                                              fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                                              command=lambda: self._set_be_mode("exact"))
        self.be_exact_toggle.pack(side="left", expand=True, fill="x", padx=(3, 1), pady=3)
        self.be_pips_toggle = ctk.CTkButton(toggle_row, text="+ Pips", height=24,
                                             fg_color="transparent", hover_color=BORDER, text_color=MUTED,
                                             command=lambda: self._set_be_mode("pips"))
        self.be_pips_toggle.pack(side="left", expand=True, fill="x", padx=(1, 3), pady=3)

        # The pips stepper/label/note only apply to "+ Pips" mode -- shown
        # only once that tab is selected (self.be_mode starts "exact", so
        # neither is packed yet). apply_row is built AFTER this so that
        # re-showing offset_line later (pack_forget doesn't destroy it) can
        # explicitly re-insert it "before=apply_row", keeping visual order
        # correct regardless of how many times the mode's been toggled.
        self.be_offset_line = ctk.CTkFrame(be_box, fg_color="transparent")
        self.pips_offset_frame, self.pips_offset_entry = self._make_number_field(
            self.be_offset_line, width=44, step=1.0, decimals=1, default="5")
        self.pips_offset_frame.pack(side="left")
        self.pips_offset_entry.bind("<KeyRelease>", self._on_pips_entry_change)
        ctk.CTkLabel(self.be_offset_line, text="pips", font=ctk.CTkFont(size=10), text_color=MUTED).pack(
            side="left", padx=(6, 0))

        self.be_pip_note_label = ctk.CTkLabel(
            be_box, text="1 pip = $0.10 (10 cents)", font=ctk.CTkFont(size=8), text_color=MUTED)

        self.be_apply_row = ctk.CTkFrame(be_box, fg_color="transparent")
        self.be_apply_row.pack(fill="x", padx=10, pady=(6, 0))
        self.be_apply_btn = ctk.CTkButton(self.be_apply_row, text="Apply", height=24,
                                           fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                           command=self._on_breakeven_apply)
        self.be_apply_btn.pack(fill="x")

        ctk.CTkLabel(be_box, text="New SL if applied:", font=ctk.CTkFont(size=9), text_color=MUTED).pack(
            anchor="w", padx=10, pady=(6, 0))
        self.be_preview_value = ctk.CTkLabel(be_box, text="—", font=ctk.CTkFont(size=12, weight="bold"),
                                              text_color=GREEN)
        self.be_preview_value.pack(anchor="w", padx=10, pady=(0, 6))

        sl_box = ctk.CTkFrame(actions_row, fg_color=CARD_ALT, corner_radius=10)
        sl_box.pack(side="left", fill="both", expand=True, padx=8)
        ctk.CTkLabel(sl_box, text="STOP LOSS", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=RED).pack(anchor="w", padx=10, pady=(6, 4))
        sl_line = ctk.CTkFrame(sl_box, fg_color="transparent")
        sl_line.pack(fill="x", padx=10)
        self.sl_field_frame, self.sl_entry = self._make_number_field(
            sl_line, width=64, step=0.1, decimals=lambda: self._price_decimals(self._selected_symbol()),
            sign_fn=lambda: self._sltp_sign("SL"), seed_fn=self._current_price_seed)
        self.sl_field_frame.pack(side="left")
        self.sl_entry.bind("<KeyRelease>", self._update_risk_reward)
        self.set_sl_btn = ctk.CTkButton(sl_line, text="Set", width=42, height=24,
                                         fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._on_set_sl)
        self.set_sl_btn.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(sl_box, text="Current:", font=ctk.CTkFont(size=9), text_color=MUTED).pack(
            anchor="w", padx=10, pady=(6, 0))
        self.current_sl_label = ctk.CTkLabel(sl_box, text="—", font=ctk.CTkFont(size=11), text_color=TEXT)
        self.current_sl_label.pack(anchor="w", padx=10, pady=(0, 6))

        tp_box = ctk.CTkFrame(actions_row, fg_color=CARD_ALT, corner_radius=10)
        tp_box.pack(side="left", fill="both", expand=True, padx=8)
        ctk.CTkLabel(tp_box, text="TAKE PROFIT", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=GREEN).pack(anchor="w", padx=10, pady=(6, 4))
        tp_line = ctk.CTkFrame(tp_box, fg_color="transparent")
        tp_line.pack(fill="x", padx=10)
        self.tp_field_frame, self.tp_entry = self._make_number_field(
            tp_line, width=64, step=0.1, decimals=lambda: self._price_decimals(self._selected_symbol()),
            sign_fn=lambda: self._sltp_sign("TP"), seed_fn=self._current_price_seed)
        self.tp_field_frame.pack(side="left")
        self.tp_entry.bind("<KeyRelease>", self._update_risk_reward)
        self.set_tp_btn = ctk.CTkButton(tp_line, text="Set", width=42, height=24,
                                         fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._on_set_tp)
        self.set_tp_btn.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(tp_box, text="Current:", font=ctk.CTkFont(size=9), text_color=MUTED).pack(
            anchor="w", padx=10, pady=(6, 0))
        self.current_tp_label = ctk.CTkLabel(tp_box, text="—", font=ctk.CTkFont(size=11), text_color=TEXT)
        self.current_tp_label.pack(anchor="w", padx=10, pady=(0, 6))

        close_box = ctk.CTkFrame(actions_row, fg_color=CARD_ALT, corner_radius=10)
        close_box.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ctk.CTkLabel(close_box, text="CLOSE POSITION", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=MUTED).pack(anchor="w", padx=10, pady=(6, 4))
        self.half_close_btn = ctk.CTkButton(close_box, text="Half Close (50%)", height=24,
                                             fg_color=CARD, hover_color=BORDER, text_color=TEXT,
                                             border_width=1, border_color=BORDER,
                                             command=self._on_half_close)
        self.half_close_btn.pack(fill="x", padx=10, pady=(0, 4))
        self.full_close_btn = ctk.CTkButton(close_box, text="Full Close", height=24,
                                             fg_color=RED, hover_color="#dc2626",
                                             command=self._on_full_close)
        self.full_close_btn.pack(fill="x", padx=10, pady=(0, 5))
        self.skip_confirm_var = tk.BooleanVar(value=False)
        self.skip_confirm_check = ctk.CTkCheckBox(
            close_box, text="Don't ask again",
            variable=self.skip_confirm_var, font=ctk.CTkFont(size=10), text_color=MUTED,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=BORDER,
            checkbox_width=14, checkbox_height=14)
        self.skip_confirm_check.pack(anchor="w", padx=10, pady=(0, 6))

        self.detail_result_banner = ctk.CTkFrame(card, corner_radius=8, fg_color=CARD)
        self.detail_result_banner.pack(fill="x", padx=14, pady=(0, 8))
        self.detail_result_label = ctk.CTkLabel(self.detail_result_banner, text="",
                                                  font=ctk.CTkFont(size=11, weight="bold"), anchor="w")
        self.detail_result_label.pack(anchor="w", padx=10, pady=4)

        self.action_widgets = [
            self.be_exact_toggle, self.be_pips_toggle, self.pips_offset_entry, self.be_apply_btn,
            self.sl_entry, self.set_sl_btn, self.tp_entry, self.set_tp_btn,
            self.half_close_btn, self.full_close_btn,
        ]
        self._set_action_panel_enabled(False)
        self._clear_detail_header()

    def _build_chart_panel(self, root):
        card = ctk.CTkFrame(root, corner_radius=14, fg_color=CARD, border_width=1, border_color=BORDER)
        card.pack(fill="both", expand=True)

        header_row = ctk.CTkFrame(card, fg_color="transparent")
        header_row.pack(fill="x", padx=14, pady=(8, 4))
        self.chart_title_label = ctk.CTkLabel(header_row, text="LIVE CHART", font=ctk.CTkFont(size=10, weight="bold"),
                                               text_color=MUTED)
        self.chart_title_label.pack(side="left")

        self.chart_timeframe = "M1"
        self._timeframe_buttons = {}
        tf_row = ctk.CTkFrame(header_row, fg_color=CARD_ALT, corner_radius=8)
        tf_row.pack(side="right")
        for label, tf in (("1m", "M1"), ("5m", "M5"), ("15m", "M15")):
            btn = ctk.CTkButton(tf_row, text=label, width=36, height=20, font=ctk.CTkFont(size=9),
                                 command=lambda tf=tf: self._set_chart_timeframe(tf))
            btn.pack(side="left", padx=2, pady=2)
            self._timeframe_buttons[tf] = btn
        self._refresh_timeframe_buttons()

        fig = Figure(figsize=(6, 1.9), dpi=100, facecolor=CARD)
        self.chart_ax = fig.add_subplot(111)
        self._style_chart_axes()
        self.chart_ax.text(0.5, 0.5, "Select a position to view its chart", color=MUTED,
                            ha="center", va="center", transform=self.chart_ax.transAxes, fontsize=10)
        # Margins trimmed to the minimum the chart actually needs: right
        # still reserves a little room for the price-tag annotation (it
        # draws past the axes' right edge via annotation_clip=False) so it
        # doesn't get clipped by the figure boundary, and left only needs
        # enough for the y-axis tick labels aren't used on that side (the
        # price axis is on the right -- see _style_chart_axes). The old
        # margins (0.04/0.90) plus 14px of outer canvas padding left
        # visible dead space on both sides of the actual candles.
        fig.subplots_adjust(left=0.01, right=0.93, top=0.94, bottom=0.06)

        self.chart_canvas = FigureCanvasTkAgg(fig, master=card)
        self.chart_canvas.get_tk_widget().configure(bg=CARD, highlightthickness=0)
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(0, 10))
        self.chart_canvas.draw()

    def _refresh_timeframe_buttons(self):
        for tf, btn in self._timeframe_buttons.items():
            active = tf == self.chart_timeframe
            btn.configure(fg_color=ACCENT if active else "transparent",
                          text_color=TEXT if active else MUTED,
                          hover_color=ACCENT_HOVER if active else BORDER)

    def _set_chart_timeframe(self, tf: str):
        self.chart_timeframe = tf
        self._refresh_timeframe_buttons()
        if self.connected:
            self._refresh_chart()

    def _style_chart_axes(self):
        self.chart_ax.clear()
        self.chart_ax.set_facecolor(CARD)
        # Price labels on the right, next to the candles, matching how MT5/
        # TradingView-style charts place the price axis.
        self.chart_ax.yaxis.tick_right()
        self.chart_ax.yaxis.set_label_position("right")
        self.chart_ax.tick_params(colors=MUTED, labelsize=8)
        for spine in self.chart_ax.spines.values():
            spine.set_color(BORDER)
        self.chart_ax.grid(True, color=BORDER, linewidth=0.5, alpha=0.5)
        self.chart_ax.set_xticks([])

    def _build_footer(self, root):
        bar = ctk.CTkFrame(root, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 8))
        self.footer_time_label = ctk.CTkLabel(bar, text="Last Update: —", font=ctk.CTkFont(size=10),
                                               text_color=MUTED)
        self.footer_time_label.pack(side="left")
        self.footer_ping_label = ctk.CTkLabel(bar, text="Ping: —", font=ctk.CTkFont(size=10),
                                               text_color=MUTED)
        self.footer_ping_label.pack(side="left", padx=(16, 0))
        ctk.CTkLabel(bar, text="THRIVE Trade Manager", font=ctk.CTkFont(size=10),
                     text_color=MUTED).pack(side="right")

    # ------------------------------------------------------------------
    # Connection / lifecycle
    # ------------------------------------------------------------------

    def stop(self):
        """Cancels all recurring timers without destroying the window --
        used both by _on_close (window actually closing) and by the Home
        button (navigating away while the app keeps running): a scheduled
        after() callback firing against widgets that navigation has already
        torn down would raise, so this must run before the widgets go."""
        for job in (self._refresh_job, self._reconnect_job, self._chart_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass

    def _on_close(self):
        self.stop()
        self.root.destroy()

    def _go_home(self):
        self.stop()
        if self.on_home:
            self.on_home()

    def _set_status(self, text: str, tone: str):
        bg, fg = _TONE_STYLES.get(tone, _TONE_STYLES["neutral"])
        self.status_badge.configure(fg_color=bg)
        self.status_label.configure(text=f"● {text}", text_color=fg)

    def _try_connect(self):
        try:
            ok = self.mt5.initialize()
        except Exception:
            ok = False

        if ok:
            self.connected = True
            self._refresh_account_info()
        else:
            self.connected = False
            self._set_status("MT5 Disconnected", "error")
            self._reconnect_job = self.root.after(self.RECONNECT_MS, self._try_connect)

    def _refresh_loop(self):
        if self.connected:
            self._refresh_account_info()
            self._refresh_positions()
        self._refresh_job = self.root.after(self.REFRESH_MS, self._refresh_loop)

    def _chart_loop(self):
        if self.connected:
            self._refresh_chart()
        self._chart_job = self.root.after(self.CHART_REFRESH_MS, self._chart_loop)

    def _refresh_chart(self):
        symbol = None
        if self.selected_ticket is not None:
            position = self.positions_by_ticket.get(self.selected_ticket)
            if position is not None:
                symbol = position.symbol

        self._style_chart_axes()

        if symbol is None:
            self.chart_ax.text(0.5, 0.5, "Select a position to view its chart", color=MUTED,
                                ha="center", va="center", transform=self.chart_ax.transAxes, fontsize=10)
            self.chart_title_label.configure(text="LIVE CHART")
            self.chart_canvas.draw_idle()
            return

        try:
            timeframe = getattr(self.mt5, f"TIMEFRAME_{self.chart_timeframe}")
            rates = self.mt5.copy_rates_from_pos(symbol, timeframe, 0, self.CHART_BAR_COUNT)
        except Exception:
            rates = None

        if rates is None or len(rates) == 0:
            self.chart_ax.text(0.5, 0.5, f"No chart data available for {symbol}", color=MUTED,
                                ha="center", va="center", transform=self.chart_ax.transAxes, fontsize=10)
            self.chart_title_label.configure(text="LIVE CHART")
            self.chart_canvas.draw_idle()
            return

        self._draw_candles(rates)

        try:
            symbol_info = self.mt5.symbol_info(symbol)
            digits = symbol_info.digits if symbol_info else 2
        except Exception:
            digits = 2
        # Comma-separated, symbol-accurate decimals on the price axis
        # (e.g. "4,436.00" for Gold), matching the reference chart's style.
        self.chart_ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos, d=digits: f"{x:,.{d}f}"))

        # Dotted line + price tag anchored to the LAST CANDLE's own close
        # (not the live position price, which can differ slightly from the
        # chart due to bid/ask spread) -- colored by whether that candle
        # closed up or down, with its timestamp, matching TradingView/MT5's
        # own current-price marker.
        last = rates[-1]
        last_close = float(last["close"])
        last_open = float(last["open"])
        tag_color = GREEN if last_close >= last_open else RED
        try:
            last_time = datetime.fromtimestamp(int(last["time"])).strftime("%H:%M")
        except Exception:
            last_time = ""

        self.chart_ax.axhline(y=last_close, color=tag_color, linestyle=(0, (4, 3)), linewidth=1)
        self.chart_ax.annotate(
            f"{last_close:,.{digits}f}\n{last_time}", xy=(1, last_close), xycoords=("axes fraction", "data"),
            xytext=(4, 0), textcoords="offset points", va="center", ha="left",
            color=BG, fontsize=8, fontweight="bold", linespacing=1.4, annotation_clip=False,
            bbox=dict(boxstyle="round,pad=0.35", fc=tag_color, ec="none"))

        self.chart_title_label.configure(text=f"LIVE CHART — {symbol} ({self.chart_timeframe})")
        self.chart_canvas.draw_idle()

    def _draw_candles(self, rates):
        """rates: the numpy structured array returned by mt5.copy_rates_from_pos,
        with 'open'/'high'/'low'/'close' fields. Drawn with plain matplotlib
        bar/vlines primitives rather than a candlestick-charting library, to
        avoid adding a second charting dependency beyond matplotlib itself."""
        opens = rates["open"]
        highs = rates["high"]
        lows = rates["low"]
        closes = rates["close"]
        x = np.arange(len(rates))
        up = closes >= opens
        down = ~up

        if up.any():
            self.chart_ax.vlines(x[up], lows[up], highs[up], color=GREEN, linewidth=1)
            self.chart_ax.bar(x[up], closes[up] - opens[up], bottom=np.minimum(opens[up], closes[up]),
                               width=0.6, color=GREEN)
        if down.any():
            self.chart_ax.vlines(x[down], lows[down], highs[down], color=RED, linewidth=1)
            self.chart_ax.bar(x[down], opens[down] - closes[down], bottom=np.minimum(opens[down], closes[down]),
                               width=0.6, color=RED)

    def _refresh_account_info(self):
        """Refreshes the connection badge, account chip, and account-overview
        stats every tick -- not just at initial connect -- so switching
        accounts inside MT5 without restarting the app is reflected
        immediately instead of leaving stale figures on screen."""
        try:
            account = self.mt5.account_info()
        except Exception:
            account = None

        self._set_status("MT5 Connected", "success")
        self.account_number_label.configure(text=str(account.login) if account else "—")

        if account:
            self.balance_value.configure(text=f"${account.balance:,.2f}")
            self.equity_value.configure(text=f"${account.equity:,.2f}")
            self.margin_value.configure(text=f"${account.margin:,.2f}")
            self.free_margin_value.configure(text=f"${account.margin_free:,.2f}")
            profit = account.profit
            pct = (profit / account.balance * 100) if account.balance else 0.0
            tone = GREEN if profit >= 0 else RED
            self.profit_value.configure(text=f"{'+' if profit >= 0 else ''}${profit:,.2f}", text_color=tone)
            self.profit_pct_value.configure(
                text=f"({'+' if pct >= 0 else ''}{pct:.2f}%)", text_color=tone)

        try:
            terminal = self.mt5.terminal_info()
            ping = getattr(terminal, "ping_last", None) if terminal else None
            if ping:
                self.footer_ping_label.configure(text=f"Ping: {ping / 1000:.0f} ms")
        except Exception:
            pass

    def _handle_connection_lost(self):
        self.connected = False
        self._set_status("MT5 Disconnected", "error")
        self._reconnect_job = self.root.after(self.RECONNECT_MS, self._try_connect)

    # ------------------------------------------------------------------
    # Positions table
    # ------------------------------------------------------------------

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
        # whatever the user is mid-typing in the SL/TP fields.
        current_iids = set(self.tree.get_children())
        new_iids = {str(p.ticket) for p in positions}

        for iid in current_iids - new_iids:
            self.tree.delete(iid)

        for p in positions:
            direction = "BUY" if p.type == self.mt5.POSITION_TYPE_BUY else "SELL"
            pips_text = self._pips_text(p, direction)
            decimals = self._price_decimals(p.symbol)
            values = (p.symbol, direction, p.volume,
                      f"{p.price_open:.{decimals}f}", f"{p.price_current:.{decimals}f}",
                      f"{p.profit:.2f}", pips_text, f"{p.sl:.{decimals}f}", f"{p.tp:.{decimals}f}")
            iid = str(p.ticket)
            if iid in current_iids:
                self.tree.item(iid, values=values)
            else:
                self.tree.insert("", "end", iid=iid, values=values)

        if self.selected_ticket not in self.positions_by_ticket:
            self.selected_ticket = None
            self._set_action_panel_enabled(False)
            self._clear_detail_header()
        else:
            self._update_detail_header(self.positions_by_ticket[self.selected_ticket])

        self.positions_title.configure(text=f"OPEN POSITIONS ({len(positions)})")
        self.position_count_value.configure(text=str(len(positions)))
        if self.selected_ticket is not None:
            self.active_symbol_value.configure(text=self.positions_by_ticket[self.selected_ticket].symbol)
        else:
            self.active_symbol_value.configure(text="—")

        total_pl = sum(p.profit for p in positions)
        tone_color = GREEN if total_pl >= 0 else (RED if positions else MUTED)
        self.table_summary_label.configure(
            text=f"{len(positions)} position(s)  •  Total P/L: {'+' if total_pl >= 0 else ''}${total_pl:.2f}",
            text_color=tone_color)
        self.footer_time_label.configure(text=f"Last Update: {datetime.now().strftime('%H:%M:%S')}")

    def _pips_text(self, position, direction: str) -> str:
        try:
            symbol_info = self.mt5.symbol_info(position.symbol)
            ps = _pip_size(symbol_info)
            pips = (position.price_current - position.price_open) / ps
            if direction == "SELL":
                pips = -pips
            return f"{'+' if pips >= 0 else ''}{pips:.1f}"
        except Exception:
            return "—"

    def _on_select(self, event):
        selection = self.tree.selection()
        if not selection:
            self.selected_ticket = None
            self._set_action_panel_enabled(False)
            self._clear_detail_header()
            return
        self.selected_ticket = int(selection[0])
        self._set_action_panel_enabled(True)
        self._set_detail_result("", "neutral")
        position = self.positions_by_ticket[self.selected_ticket]
        decimals = self._price_decimals(position.symbol)
        self.sl_entry.delete(0, tk.END)
        if position.sl:
            self.sl_entry.insert(0, f"{position.sl:.{decimals}f}")
        self.tp_entry.delete(0, tk.END)
        if position.tp:
            self.tp_entry.insert(0, f"{position.tp:.{decimals}f}")
        self._update_detail_header(position)

    # ------------------------------------------------------------------
    # Detail panel state
    # ------------------------------------------------------------------

    def _clear_detail_header(self):
        self.detail_symbol_label.configure(text="No position selected")
        self.detail_direction_badge.configure(fg_color=CARD_ALT)
        self.detail_direction_label.configure(text="", text_color=MUTED)
        self.detail_lots_label.configure(text="— lots")
        self.detail_pl_label.configure(text="")
        self.detail_pl_pips_label.configure(text="")
        self.detail_entry_price_label.configure(text="—")
        self.detail_current_price_label.configure(text="—")
        self.current_sl_label.configure(text="—")
        self.current_tp_label.configure(text="—")
        self.validated_label.configure(text="")
        self.be_preview_value.configure(text="—")
        self.rr_value_label.configure(text="—")

    def _update_detail_header(self, position):
        direction = "BUY" if position.type == self.mt5.POSITION_TYPE_BUY else "SELL"
        self.detail_symbol_label.configure(text=position.symbol)
        self.detail_direction_badge.configure(fg_color=GREEN_BG if direction == "BUY" else RED_BG)
        self.detail_direction_label.configure(text=direction, text_color=GREEN if direction == "BUY" else RED)
        self.detail_lots_label.configure(text=f"{position.volume} lots")

        profit = position.profit
        tone = GREEN if profit >= 0 else RED
        self.detail_pl_label.configure(text=f"{'+' if profit >= 0 else ''}${profit:.2f}", text_color=tone)
        self.detail_pl_pips_label.configure(text=f"({self._pips_text(position, direction)} pips)")

        decimals = self._price_decimals(position.symbol)
        self.detail_entry_price_label.configure(text=f"{position.price_open:.{decimals}f}")
        self.detail_current_price_label.configure(text=f"{position.price_current:.{decimals}f}")
        self.current_sl_label.configure(text=f"{position.sl:.{decimals}f}" if position.sl else "—")
        self.current_tp_label.configure(text=f"{position.tp:.{decimals}f}" if position.tp else "—")
        self.validated_label.configure(text=f"Validated for {direction} position")

        self._update_be_preview()
        self._update_risk_reward()

    def _set_action_panel_enabled(self, enabled: bool):
        self._panel_enabled = enabled
        state = "normal" if enabled else "disabled"
        for widget in self.action_widgets:
            widget.configure(state=state)
        if enabled:
            self._on_pips_entry_change(None)  # re-evaluate Apply-button state for the new selection

    def _set_be_mode(self, mode: str):
        self.be_mode = mode
        if mode == "exact":
            self.be_exact_toggle.configure(fg_color=ACCENT, text_color=TEXT, hover_color=ACCENT_HOVER)
            self.be_pips_toggle.configure(fg_color="transparent", text_color=MUTED, hover_color=BORDER)
            self.be_offset_line.pack_forget()
            self.be_pip_note_label.pack_forget()
        else:
            self.be_pips_toggle.configure(fg_color=ACCENT, text_color=TEXT, hover_color=ACCENT_HOVER)
            self.be_exact_toggle.configure(fg_color="transparent", text_color=MUTED, hover_color=BORDER)
            # before=self.be_apply_row keeps these anchored above Apply
            # regardless of how many times pack_forget/pack has toggled
            # them -- a plain .pack() would just re-append at the end.
            self.be_offset_line.pack(fill="x", padx=10, pady=(4, 0), before=self.be_apply_row)
            self.be_pip_note_label.pack(anchor="w", padx=10, pady=(2, 0), before=self.be_apply_row)
        self._on_pips_entry_change(None)

    def _on_pips_entry_change(self, event):
        self._update_be_preview()
        if self.be_mode == "pips":
            try:
                pips = float(self.pips_offset_entry.get().strip())
                valid = pips > 0
            except ValueError:
                valid = False
            self.be_apply_btn.configure(state="normal" if (valid and self._panel_enabled) else "disabled")
        else:
            self.be_apply_btn.configure(state="normal" if self._panel_enabled else "disabled")

    def _sltp_sign(self, field: str) -> int:
        """Which way the SL/TP stepper's up-arrow should move the number.
        A SELL flips both fields relative to a BUY: validate_sltp requires
        SL > current-price and TP < current-price for a SELL (the opposite
        of a BUY), so "up" (toward a more valid/profitable value) means
        decrease for a SELL's TP and increase for a SELL's SL. No position
        selected defaults to +1 (up = increase) since the fields are
        disabled in that state anyway."""
        position = self.positions_by_ticket.get(self.selected_ticket) if self.selected_ticket else None
        if position is None:
            return 1
        direction = "BUY" if position.type == self.mt5.POSITION_TYPE_BUY else "SELL"
        if field == "TP":
            return 1 if direction == "BUY" else -1
        return 1 if direction == "SELL" else -1

    def _current_price_seed(self) -> float:
        """Starting value for the SL/TP steppers when their field is empty,
        so a click lands near the real price instead of at 0."""
        position = self.positions_by_ticket.get(self.selected_ticket) if self.selected_ticket else None
        return position.price_current if position is not None else 0.0

    def _price_decimals(self, symbol) -> int:
        """Decimal places for displaying/entering a price, SL, or TP --
        matches the symbol's own quoting precision (2 for Gold, 5 for most
        forex pairs) instead of a one-size-fits-all 5, which showed Gold
        prices as e.g. 4436.09000 -- needlessly precise and inconsistent
        with how the symbol actually quotes."""
        if symbol is None:
            return 5
        try:
            return self.mt5.symbol_info(symbol).digits
        except Exception:
            return 5

    def _selected_symbol(self):
        position = self.positions_by_ticket.get(self.selected_ticket) if self.selected_ticket else None
        return position.symbol if position is not None else None

    def _update_be_preview(self):
        position = self.positions_by_ticket.get(self.selected_ticket) if self.selected_ticket else None
        if position is None:
            self.be_preview_value.configure(text="—")
            return
        try:
            symbol_info = self.mt5.symbol_info(position.symbol)
            direction = "BUY" if position.type == self.mt5.POSITION_TYPE_BUY else "SELL"
            pips = 0.0
            if self.be_mode == "pips":
                pips = float(self.pips_offset_entry.get().strip() or 0)
            new_sl = _breakeven_price(direction, position.price_open, _pip_size(symbol_info), pips)
            self.be_preview_value.configure(text=f"{new_sl:.{symbol_info.digits}f}")
        except Exception:
            self.be_preview_value.configure(text="—")

    def _update_risk_reward(self, event=None):
        position = self.positions_by_ticket.get(self.selected_ticket) if self.selected_ticket else None
        if position is None:
            self.rr_value_label.configure(text="—")
            return
        try:
            sl = float(self.sl_entry.get().strip())
            tp = float(self.tp_entry.get().strip())
            risk = abs(position.price_open - sl)
            reward = abs(tp - position.price_open)
            if risk <= 0:
                self.rr_value_label.configure(text="—")
                return
            self.rr_value_label.configure(text=f"1 : {reward / risk:.2f}")
        except ValueError:
            self.rr_value_label.configure(text="—")

    def _set_detail_result(self, text: str, tone: str = "neutral"):
        bg, fg = _TONE_STYLES.get(tone, _TONE_STYLES["neutral"])
        self.detail_result_banner.configure(fg_color=bg if text else CARD)
        self.detail_result_label.configure(text=text, text_color=fg)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

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
            self._set_detail_result("Action could not be completed.", "error")
            return
        if result.retcode == self.mt5.TRADE_RETCODE_DONE:
            self._set_detail_result(success_message, "success")
        elif result.retcode == self.mt5.TRADE_RETCODE_DONE_PARTIAL:
            self._set_detail_result(
                f"Partially filled — {success_message} Check remaining volume before retrying.",
                "warning")
        else:
            self._set_detail_result(
                f"Broker rejected: {result.retcode} {getattr(result, 'comment', '')}", "error")

    def _on_breakeven_apply(self):
        if self.selected_ticket is None:
            return
        pips = 0.0
        if self.be_mode == "pips":
            try:
                pips = float(self.pips_offset_entry.get().strip())
            except ValueError:
                self._set_detail_result("Enter a valid positive pip value first.", "error")
                return
            if pips <= 0:
                self._set_detail_result("Pips must be a positive number.", "error")
                return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self._set_detail_result("Position no longer open.", "error")
            return
        try:
            result = apply_breakeven(self.mt5, position, pips=pips)
        except Exception:
            self._set_detail_result("Action failed (MT5 error).", "error")
            return
        msg = "SL moved to breakeven." if pips == 0 else f"SL moved to breakeven +{pips:g} pips."
        self._show_result(result, msg)

    def _on_set_sl(self):
        if self.selected_ticket is None:
            return
        sl_text = self.sl_entry.get().strip()
        try:
            sl = float(sl_text) if sl_text else None
        except ValueError:
            self._set_detail_result("SL must be a number.", "error")
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self._set_detail_result("Position no longer open.", "error")
            return
        try:
            result, error = apply_custom_sltp(self.mt5, position, sl, None)
        except Exception:
            self._set_detail_result("Action failed (MT5 error).", "error")
            return
        if error:
            self._set_detail_result(error, "error")
            return
        self._show_result(result, "Stop loss updated.")

    def _on_set_tp(self):
        if self.selected_ticket is None:
            return
        tp_text = self.tp_entry.get().strip()
        try:
            tp = float(tp_text) if tp_text else None
        except ValueError:
            self._set_detail_result("TP must be a number.", "error")
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self._set_detail_result("Position no longer open.", "error")
            return
        try:
            result, error = apply_custom_sltp(self.mt5, position, None, tp)
        except Exception:
            self._set_detail_result("Action failed (MT5 error).", "error")
            return
        if error:
            self._set_detail_result(error, "error")
            return
        self._show_result(result, "Take profit updated.")

    def _on_half_close(self):
        if self.selected_ticket is None:
            return
        position = self._get_live_position(self.selected_ticket)
        if position is None:
            self._set_detail_result("Position no longer open.", "error")
            return
        try:
            result = half_close(self.mt5, position)
        except Exception:
            self._set_detail_result("Action failed (MT5 error).", "error")
            return
        if result is None:
            self._set_detail_result(
                "Cannot half-close: half the volume is below the broker's minimum lot.", "error")
            return
        self._show_result(result, "Half of the position closed.")

    def _on_full_close(self):
        if self.selected_ticket is None:
            return
        ticket = self.selected_ticket
        position = self._get_live_position(ticket)
        if position is None:
            self._set_detail_result("Position no longer open.", "error")
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
            self._set_detail_result(
                "Position closed before the close order was sent -- no action taken.", "error")
            return
        try:
            result = full_close(self.mt5, position)
        except Exception:
            self._set_detail_result("Action failed (MT5 error).", "error")
            return
        self._show_result(result, "Position closed.")
