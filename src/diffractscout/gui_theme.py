"""Shared presentation tokens and native ttk styles for the desktop workbench."""

NAVY = "#17324D"
NAVY_DARK = "#11283F"
TEAL = "#128794"
TEAL_DARK = "#0E737D"
BLUE = "#277DA1"
BG = "#F2F5F8"
CARD = "#FFFFFF"
TEXT = "#20354A"
MUTED = "#586D80"
BORDER = "#D8E2EA"
SUCCESS = "#177849"
WARNING = "#925300"
ERROR = "#B42318"
LOG_BG = "#182B3D"
LOG_TEXT = "#E0EAF2"


def configure_styles(root: object) -> str:
    """Use installed system fonts and keep all widgets in the same ttk theme."""
    from tkinter import font, ttk

    families = set(font.families(root))
    family = next(
        (name for name in ("Microsoft YaHei UI", "Noto Sans CJK SC", "Segoe UI", "DejaVu Sans")
         if name in families),
        font.nametofont("TkDefaultFont", root).actual("family"),
    )
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        font.nametofont(name, root).configure(family=family, size=9)
    fixed_font = font.nametofont("TkFixedFont", root)
    fixed_family = next((name for name in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono")
                         if name in families), fixed_font.actual("family"))
    fixed_font.configure(family=fixed_family, size=9)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(family, 9), foreground=TEXT, background=BG)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=CARD)
    style.configure("Title.TLabel", background=CARD, foreground=NAVY, font=(family, 12, "bold"))
    style.configure("PageTitle.TLabel", background=BG, foreground=NAVY, font=(family, 15, "bold"))
    style.configure("Hint.TLabel", background=CARD, foreground=MUTED, font=(family, 9))
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("Warning.TLabel", background="#FFF5E5", foreground=WARNING, padding=10)
    style.configure("HeaderTitle.TLabel", background=NAVY_DARK, foreground=CARD,
                    font=(family, 18, "bold"))
    style.configure("HeaderSub.TLabel", background=NAVY_DARK, foreground="#C7D9E8")
    style.configure("Badge.TLabel", background=TEAL_DARK, foreground=CARD, padding=(8, 3))
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(18, 9),
                    font=(family, 9, "bold"))
    style.map("TNotebook.Tab", background=[("selected", CARD), ("active", "#E5EDF3")],
              foreground=[("selected", TEAL_DARK)], focuscolor=[("focus", TEAL_DARK)])
    style.configure("TButton", background="#E8EFF5", foreground=NAVY, padding=(10, 6),
                    borderwidth=1, bordercolor=BORDER, focusthickness=1, focuscolor=TEAL_DARK)
    style.map("TButton", background=[("disabled", "#EEF2F6"), ("pressed", "#D2E3EB"),
                                     ("active", "#DCE8F0")],
              foreground=[("disabled", MUTED)])
    style.configure("Secondary.TButton", padding=(10, 6))
    style.configure("Primary.TButton", background=TEAL_DARK, foreground=CARD,
                    padding=(14, 9), bordercolor=TEAL_DARK, font=(family, 10, "bold"),
                    focuscolor=CARD)
    style.map("Primary.TButton", background=[("disabled", "#D4E0E7"),
                                             ("pressed", "#095D65"), ("active", "#09656E")],
              foreground=[("disabled", MUTED), ("!disabled", CARD)])
    style.configure("Danger.TButton", background="#FFF0EE", foreground=ERROR,
                    bordercolor="#F0D2CE")
    style.map("Danger.TButton", background=[("disabled", "#EEF2F6"), ("active", "#FDE2DE")],
              foreground=[("disabled", MUTED), ("!disabled", ERROR)])
    style.configure("Disclosure.TButton", background=CARD, bordercolor=BORDER,
                    anchor="w", padding=(10, 7), font=(family, 9, "bold"))
    style.configure("TEntry", fieldbackground=CARD, foreground=TEXT, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=(8, 6))
    style.map("TEntry", bordercolor=[("focus", TEAL_DARK)],
              fieldbackground=[("disabled", "#EEF2F6")], foreground=[("disabled", MUTED)])
    style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(8, 5),
                    arrowsize=14)
    style.map("TCombobox", fieldbackground=[("disabled", "#EEF2F6"), ("readonly", CARD)],
              background=[("disabled", "#EEF2F6"), ("readonly", CARD)],
              foreground=[("disabled", MUTED), ("readonly", TEXT)],
              selectbackground=[("readonly", CARD)], selectforeground=[("readonly", TEXT)],
              bordercolor=[("focus", TEAL_DARK)])
    style.configure("TLabelframe", background=CARD, bordercolor=BORDER, relief="solid")
    style.configure("TLabelframe.Label", background=CARD, foreground=NAVY,
                    font=(family, 9, "bold"))
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=CARD, foreground=TEXT, padding=(0, 3))
        style.map(name, background=[("active", CARD)], foreground=[("disabled", MUTED)],
                  indicatorcolor=[("selected", TEAL_DARK)], focuscolor=[("focus", TEAL_DARK)])
    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                    rowheight=29, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.map("Treeview", background=[("selected", "#DCEEF0")],
              foreground=[("selected", NAVY)])
    style.configure("Treeview.Heading", background="#EAF0F5", foreground=NAVY,
                    font=(family, 9, "bold"), padding=(6, 7), relief="flat")
    style.map("Treeview.Heading", background=[("active", "#DCE8F0")])
    style.configure("TScrollbar", background="#DAE3EB", troughcolor=BG, borderwidth=0,
                    arrowsize=12)
    style.configure("Horizontal.TProgressbar", background=TEAL_DARK,
                    troughcolor="#DDE7EE", borderwidth=0, thickness=6)
    root.option_add("*TCombobox*Listbox.font", (family, 9))
    root.option_add("*TCombobox*Listbox.background", CARD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    return family
