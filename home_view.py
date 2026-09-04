import queue
import threading
import webbrowser
import customtkinter as ctk
from PIL import Image
from gui import BG, CARD, BORDER, TEXT, MUTED, ACCENT, ACCENT_HOVER, _resource_path
from update_check import fetch_latest_release, is_newer, APP_VERSION

FEEDBACK_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfHOk41U3m0X-QWuY1VpG751j-F8WgaXtLb_RWkyoyvFHU03g/viewform"


class HomeScreen:
    """Landing page shown on launch: lets the user choose between the Trade
    Manager (manage open positions) and the Trading Journal (history/P&L/
    trade-source notes). Purely a navigation screen -- no MT5 calls, no
    timers, nothing to clean up when leaving it.

    Content is centered via place(), which means it has no natural way to
    grow with the window (fixed pixel sizes just sit in the middle of
    whatever extra space appears) -- so logo/text/card sizes are explicitly
    rescaled on every window resize, proportional to how much bigger/smaller
    the window is than its starting size."""

    BASE_WIDTH = 760
    BASE_HEIGHT = 480
    BASE_LOGO_SIZE = (140, 51)
    BASE_CARD_SIZE = (230, 165)

    def __init__(self, root, on_open_manager, on_open_journal):
        self.root = root
        self.root.title("THRIVE Trade Manager")
        self.root.geometry(f"{self.BASE_WIDTH}x{self.BASE_HEIGHT}")
        self.root.minsize(640, 440)
        self.root.configure(fg_color=BG)

        self._resize_job = None
        self._current_scale = 1.0
        self._update_banner = None
        self._update_poll_job = None
        self._update_result_queue = queue.Queue()

        container = ctk.CTkFrame(root, fg_color=BG)
        container.pack(fill="both", expand=True)

        self.center = ctk.CTkFrame(container, fg_color="transparent")
        self.center.place(relx=0.5, rely=0.5, anchor="center")

        self._logo_img_raw = None
        try:
            self._logo_img_raw = Image.open(_resource_path("assets/logo.png"))
        except Exception:
            self._logo_img_raw = None

        if self._logo_img_raw is not None:
            self._logo_image = ctk.CTkImage(self._logo_img_raw, size=self.BASE_LOGO_SIZE)
            self.logo_label = ctk.CTkLabel(self.center, image=self._logo_image, text="")
        else:
            self.logo_label = ctk.CTkLabel(self.center, text="THRIVE", text_color=TEXT,
                                            font=ctk.CTkFont(size=28, weight="bold"))
        self.logo_label.pack(pady=(0, 20))

        self.subtitle_label = ctk.CTkLabel(self.center, text="What would you like to open?",
                                            font=ctk.CTkFont(size=13), text_color=MUTED)
        self.subtitle_label.pack(pady=(0, 16))

        cards_row = ctk.CTkFrame(self.center, fg_color="transparent")
        cards_row.pack()

        self.card1, self.card1_widgets = self._make_choice_card(
            cards_row, "Trade Manager",
            "Manage open positions: breakeven, close, SL/TP, live chart.",
            on_open_manager)
        self.card1.pack(side="left", padx=8)

        self.card2, self.card2_widgets = self._make_choice_card(
            cards_row, "Trading Journal",
            "Full trade history, P&L, filters, and notes on where each trade came from.",
            on_open_journal)
        self.card2.pack(side="left", padx=8)

        links_row = ctk.CTkFrame(self.center, fg_color="transparent")
        links_row.pack(pady=(16, 0))
        ctk.CTkButton(links_row, text="💬 Send Feedback", width=140, height=26,
                      font=ctk.CTkFont(size=11), fg_color=CARD, hover_color=BORDER,
                      text_color=MUTED, border_width=1, border_color=BORDER,
                      command=lambda: webbrowser.open(FEEDBACK_FORM_URL)).pack(side="left", padx=6)

        # Pinned to the window's own top-right corner (via place(), not
        # packed alongside the centered content) so it reads like it
        # belongs up near the native minimize/close buttons -- as close to
        # that as Tkinter allows, since those native title-bar buttons
        # belong to Windows itself and can't have a widget added next to
        # them without replacing the whole title bar. relx=1.0/rely=0.0
        # with anchor="ne" keeps it flush to the corner on any resize,
        # with no rescaling math needed (unlike self.center's contents).
        top_right = ctk.CTkFrame(container, fg_color="transparent")
        top_right.place(relx=1.0, rely=0.0, anchor="ne", x=-16, y=12)
        self.check_update_btn = ctk.CTkButton(
            top_right, text="🔄 Check for Updates", width=160, height=26,
            font=ctk.CTkFont(size=11), fg_color=CARD, hover_color=BORDER,
            text_color=MUTED, border_width=1, border_color=BORDER,
            command=self._manual_check_for_update)
        self.check_update_btn.pack(anchor="e")

        self.update_status_label = ctk.CTkLabel(top_right, text="", font=ctk.CTkFont(size=10),
                                                  text_color=MUTED, justify="right")
        self.update_status_label.pack(anchor="e", pady=(4, 0))

        self.root.bind("<Configure>", self._on_root_resize)

        # The GitHub API call is real network I/O -- it must never run on
        # the Tk main thread (would freeze the whole UI while it waits).
        # The worker thread only ever touches the thread-safe queue, never
        # a widget directly; _poll_update_queue (running via root.after on
        # the main thread) is the only thing that ever updates the UI,
        # which sidesteps Tkinter's general unsafety with cross-thread
        # widget calls. This same poll loop keeps rescheduling itself
        # (cheap: one non-blocking queue check every 500ms) for as long as
        # Home is showing, so a later manual "Check for Updates" click just
        # needs to queue a new result -- it doesn't need its own poll loop.
        threading.Thread(target=self._check_for_update_worker, daemon=True).start()
        self._update_poll_job = self.root.after(500, self._poll_update_queue)

    def _check_for_update_worker(self, manual=False):
        """manual=False (automatic, on-load check): stays silent unless a
        newer version actually exists -- nobody wants to be told "you're
        up to date" every single time they open the app. manual=True (the
        button): always reports back, success or failure, since a button
        the user explicitly clicked needs to visibly do SOMETHING."""
        result = fetch_latest_release()
        if result is None:
            if manual:
                self._update_result_queue.put(("error", None, None))
            return
        tag, url = result
        if is_newer(tag, APP_VERSION):
            self._update_result_queue.put(("update", tag, url))
        elif manual:
            self._update_result_queue.put(("uptodate", tag, None))

    def _manual_check_for_update(self):
        self.check_update_btn.configure(state="disabled")
        self.update_status_label.configure(text="Checking for updates...")
        threading.Thread(target=self._check_for_update_worker, kwargs={"manual": True}, daemon=True).start()

    def _poll_update_queue(self):
        self._update_poll_job = None
        try:
            kind, tag, url = self._update_result_queue.get_nowait()
        except queue.Empty:
            self._update_poll_job = self.root.after(500, self._poll_update_queue)
            return
        if kind == "update":
            self._show_update_banner(tag, url)
            self.update_status_label.configure(text="")
        elif kind == "uptodate":
            self.update_status_label.configure(text=f"You're on the latest version ({APP_VERSION}).")
        elif kind == "error":
            self.update_status_label.configure(text="Couldn't check for updates -- check your internet connection.")
        self.check_update_btn.configure(state="normal")
        self._update_poll_job = self.root.after(500, self._poll_update_queue)

    def _show_update_banner(self, tag, url):
        if self._update_banner is not None:
            return
        self._update_banner = ctk.CTkButton(
            self.center, text=f"🔔 Version {tag} is available — click to download",
            font=ctk.CTkFont(size=12), height=26, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=TEXT, command=lambda: webbrowser.open(url))
        self._update_banner.pack(pady=(0, 14), before=self.logo_label)

    def _make_choice_card(self, parent, title, subtitle, command):
        card = ctk.CTkFrame(parent, corner_radius=16, fg_color=CARD, border_width=1,
                             border_color=BORDER, width=self.BASE_CARD_SIZE[0],
                             height=self.BASE_CARD_SIZE[1])
        card.pack_propagate(False)
        title_label = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                                    text_color=TEXT)
        title_label.pack(anchor="w", padx=16, pady=(16, 6))
        subtitle_label = ctk.CTkLabel(card, text=subtitle, font=ctk.CTkFont(size=11), text_color=MUTED,
                                       wraplength=194, justify="left")
        subtitle_label.pack(anchor="w", padx=16)
        button = ctk.CTkButton(card, text=f"Open {title}", height=24, fg_color=ACCENT,
                                hover_color=ACCENT_HOVER, text_color=TEXT, command=command)
        button.pack(side="bottom", padx=16, pady=16, fill="x")
        return card, {"title": title_label, "subtitle": subtitle_label, "button": button}

    def stop(self):
        """Cancels the pending debounced resize callback, if any, AND
        unbinds <Configure> from root -- both are needed. Canceling the
        job alone isn't enough: the <Configure> binding lives on root
        itself (not on this screen's own widgets), so it survives this
        screen being destroyed, and the very next page's own construction
        (which resizes/repacks root) fires a fresh <Configure> event that
        re-arms _on_root_resize -> schedules a NEW _apply_scale call
        against widgets that no longer exist (confirmed directly: this
        raised TclError even with the pending job correctly canceled).
        No other page binds <Configure> on root itself (only on specific
        child widgets, for their own column-resize logic), so unbinding
        it here can't affect anything else."""
        if self._resize_job is not None:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
            self._resize_job = None
        # The update-check poll loop reschedules itself every 500ms until
        # a result shows up -- left running, it's the exact same dangling-
        # timer bug just fixed for the resize job, just with a different
        # trigger.
        if self._update_poll_job is not None:
            try:
                self.root.after_cancel(self._update_poll_job)
            except Exception:
                pass
            self._update_poll_job = None
        try:
            self.root.unbind("<Configure>")
        except Exception:
            pass

    def _on_root_resize(self, event):
        if event.widget is not self.root:
            return
        # Debounced: dragging a window edge fires many Configure events in
        # quick succession, and recomputing fonts/images on every single one
        # would be wasteful and janky -- settle for 120ms after resizing stops.
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self._apply_scale)

    def _apply_scale(self):
        self._resize_job = None
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        if width <= 1 or height <= 1:
            return
        scale = min(width / self.BASE_WIDTH, height / self.BASE_HEIGHT)
        scale = max(0.85, min(scale, 2.6))
        if abs(scale - self._current_scale) < 0.03:
            return  # ignore sub-3% jitter so we're not re-rendering fonts constantly
        self._current_scale = scale

        def s(px):
            return max(1, round(px * scale))

        if self._logo_img_raw is not None:
            self._logo_image.configure(size=(s(self.BASE_LOGO_SIZE[0]), s(self.BASE_LOGO_SIZE[1])))
        else:
            self.logo_label.configure(font=ctk.CTkFont(size=s(24), weight="bold"))

        self.subtitle_label.configure(font=ctk.CTkFont(size=s(12)))

        for card, widgets in ((self.card1, self.card1_widgets), (self.card2, self.card2_widgets)):
            card.configure(width=s(self.BASE_CARD_SIZE[0]), height=s(self.BASE_CARD_SIZE[1]))
            widgets["title"].configure(font=ctk.CTkFont(size=s(14), weight="bold"))
            widgets["subtitle"].configure(font=ctk.CTkFont(size=s(10)), wraplength=s(194))
            widgets["button"].configure(font=ctk.CTkFont(size=s(11)), height=s(24))
