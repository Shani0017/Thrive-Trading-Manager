import customtkinter as ctk
from PIL import Image
from gui import BG, CARD, BORDER, TEXT, MUTED, ACCENT, ACCENT_HOVER, _resource_path


class HomeScreen:
    """Landing page shown on launch: lets the user choose between the Trade
    Manager (manage open positions) and the Trading Journal (history/P&L/
    trade-source notes). Purely a navigation screen -- no MT5 calls, no
    timers, nothing to clean up when leaving it."""

    def __init__(self, root, on_open_manager, on_open_journal):
        self.root = root
        self.root.title("MT5 Trade Manager")
        self.root.geometry("900x600")
        self.root.minsize(760, 520)
        self.root.configure(fg_color=BG)

        container = ctk.CTkFrame(root, fg_color=BG)
        container.pack(fill="both", expand=True)

        center = ctk.CTkFrame(container, fg_color="transparent")
        center.place(relx=0.5, rely=0.5, anchor="center")

        try:
            logo_img = Image.open(_resource_path("assets/logo.png"))
            self._logo_image = ctk.CTkImage(logo_img, size=(180, 66))
            ctk.CTkLabel(center, image=self._logo_image, text="").pack(pady=(0, 30))
        except Exception:
            ctk.CTkLabel(center, text="THRIVE", text_color=TEXT,
                         font=ctk.CTkFont(size=28, weight="bold")).pack(pady=(0, 30))

        ctk.CTkLabel(center, text="What would you like to open?", font=ctk.CTkFont(size=14),
                     text_color=MUTED).pack(pady=(0, 24))

        cards_row = ctk.CTkFrame(center, fg_color="transparent")
        cards_row.pack()

        self._make_choice_card(
            cards_row, "Trade Manager",
            "Manage open positions: breakeven, close, SL/TP, live chart.",
            on_open_manager,
        ).pack(side="left", padx=12)

        self._make_choice_card(
            cards_row, "Trading Journal",
            "Full trade history, P&L, filters, and notes on where each trade came from.",
            on_open_journal,
        ).pack(side="left", padx=12)

    def _make_choice_card(self, parent, title, subtitle, command):
        card = ctk.CTkFrame(parent, corner_radius=16, fg_color=CARD, border_width=1,
                             border_color=BORDER, width=280, height=200)
        card.pack_propagate(False)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=22, pady=(24, 8))
        ctk.CTkLabel(card, text=subtitle, font=ctk.CTkFont(size=11), text_color=MUTED,
                     wraplength=236, justify="left").pack(anchor="w", padx=22)
        ctk.CTkButton(card, text=f"Open {title}", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=command).pack(side="bottom", padx=22, pady=22, fill="x")
        return card
