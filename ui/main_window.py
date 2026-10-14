from __future__ import annotations

"""
Fakturabunten — Main Window
===================================
Fil    : Fakturabunten_/ui/main_window.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Huvudfönster — hanterar:
• Flikar, meny, toolbar, statusfält
• System Tray (alltid minimerad vid start, göm vid kryss)
• 4 teman: Mörkt / Ljust / Auto / System
• Tydliga dropdown-pilar som anpassas efter tema
• Autostart med OS via kryssruta i Inställningar-menyn
• Stäng till tray via kryssruta i Inställningar-menyn
• Visa/dölj flikar (meny + högerklick på flik)
• Geometrisparning i JSON (debounced — skriver inte per pixel)
• Inladdning av InvoicesView och SuppliersView (builtins)
• Plugin fas-2-registrering
• Multi-OS: Windows / Linux / macOS
• Mushjul-scroll i alla flikar (QScrollArea-wrap)
• Betalningsdatum hanteras PER export-batch och nollställs efter export
  (publikt API: confirm_and_export_invoices)

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import logging
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QMenu, QSystemTrayIcon,
    QApplication, QToolBar, QStatusBar,
    QMessageBox, QScrollArea, QFrame, QPushButton, QDialog, QTextEdit, QGroupBox,
    QTableWidget, QTableWidgetItem, QKeySequenceEdit, QComboBox,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtGui import (
    QActionGroup,
    QAction, QFont, QPalette, QColor, QCursor,
    QIcon, QPixmap, QPainter, QDesktopServices,
    QKeySequence, QShortcut,
)
from PySide6.QtCore import (
    Qt, QTimer, QPoint, Signal, QUrl, QFileSystemWatcher,
)

# ═════════════════════════════════════════════════════════════════════
#  KONSTANTER
# ═════════════════════════════════════════════════════════════════════

COPYRIGHT_YEAR: int = datetime.date.today().year

BASE_DIR: Path = Path(__file__).parent.resolve()   # .../ui/
PROJECT_DIR: Path = BASE_DIR.parent                # .../Fakturabunten_/

APP_NAME: str = "Fakturabunten"
APP_VERSION: str = "1.0.0"

FONT_FAMILY: str = "Segoe UI"

log = logging.getLogger("MainWindow")

# Språk (sv/en) + donationsdialog. Mjuka importer så att filen även
# fungerar fristående (python ui/main_window.py).
try:
    from ui.i18n import (
        tr, set_language as _i18n_set_language,
        language as _i18n_language, LANGUAGE_NAMES as _LANGUAGE_NAMES,
    )
except Exception:  # pragma: no cover
    try:
        from i18n import (  # type: ignore
            tr, set_language as _i18n_set_language,
            language as _i18n_language, LANGUAGE_NAMES as _LANGUAGE_NAMES,
        )
    except Exception:
        _LANGUAGE_NAMES = {"sv": "Svenska", "en": "English"}
        def tr(key: str, **_f: object) -> str:  # type: ignore
            return key
        def _i18n_set_language(lang: str) -> str:  # type: ignore
            return "sv"
        def _i18n_language() -> str:  # type: ignore
            return "sv"

try:
    from ui.donate import open_donate_dialog
except Exception:  # pragma: no cover
    try:
        from donate import open_donate_dialog  # type: ignore
    except Exception:
        def open_donate_dialog(parent=None) -> bool:  # type: ignore
            return False


def get_platform() -> str:
    """Returnerar 'windows' | 'macos' | 'linux'."""
    p = platform.system().lower()
    if p == "darwin":
        return "macos"
    if p == "windows":
        return "windows"
    return "linux"


CURRENT_PLATFORM: str = get_platform()

VALID_THEMES: tuple[str, ...] = ("dark", "light", "auto", "system")

#: Donationslänk — definieras på EN plats (app.py), används av
#: donate-knappen i Om-dialogen.
try:
    from app import DONATE_SWISH, DONATE_PAYPAL, DONATE_BMC
except Exception:  # pragma: no cover
    DONATE_SWISH = "123 456 78 90"
    DONATE_PAYPAL = "https://www.paypal.com/donate"
    DONATE_BMC = "https://ko-fi.com/tokke2"

# ═════════════════════════════════════════════════════════════════════
#  SYS.PATH
# ═════════════════════════════════════════════════════════════════════


def _ensure_paths() -> None:
    """Säkerställer att projekt- och ui-mappen finns i sys.path."""
    for _d in (str(PROJECT_DIR), str(BASE_DIR)):
        if _d not in sys.path:
            sys.path.insert(0, _d)


_ensure_paths()

# ═════════════════════════════════════════════════════════════════════
#  TEMAN  (exakt 4: dark / light / auto / system)
# ═════════════════════════════════════════════════════════════════════

THEMES: dict[str, dict] = {
    "dark": {
        "name": "dark", "label": "🌙  Mörkt",
        "bg": "#0c1218", "bg_secondary": "#141c26",
        "bg_tertiary": "#1c2836",
        "text": "#d5deea", "text_strong": "#f4f7fb",
        "accent": "#3d8bfd", "accent_hover": "#6aa6ff",
        "button_bg": "#1c2836", "button_text": "#f4f7fb",
        "button_hover": "#283648",
        "tab_bg": "#141c26", "tab_selected": "#1f4f8a",
        "tab_text": "#b7c5d6", "tab_text_selected": "#ffffff",
        "border": "#2a3848", "header_bg": "#17304c",
        "row_alt": "#1c3044", "row_normal": "#0c1218",
        "card_bg": "#141c26", "status_bar": "#0c1218",
        "status_text": "#d5deea",
        "input_bg": "#0c1218", "input_border": "#2a3848",
        "scrollbar_bg": "#0c1218", "scrollbar_handle": "#3a4a5c",
        "menu_bg": "#141c26", "menu_text": "#d5deea",
        "menu_hover": "#1f4f8a",
        "tooltip_bg": "#1c2836", "tooltip_text": "#f4f7fb",
        "success": "#3ecf8e", "warning": "#e3b341",
        "error": "#f07178", "info": "#3d8bfd",
        "gold": "#e8b030", "gold_bg": "#2a2416",
        "toolbar_bg": "#101820", "toolbar_border": "#c9a227",
        "tray_icon_color": "#e8b030",
    },
    "light": {
        "name": "light", "label": "☀️  Ljust",
        "bg": "#f4f1ea", "bg_secondary": "#fffcf7",
        "bg_tertiary": "#e8e2d6",
        "text": "#3d4450", "text_strong": "#1c2128",
        "accent": "#0b5cab", "accent_hover": "#084a8a",
        "button_bg": "#fffcf7", "button_text": "#1c2128",
        "button_hover": "#efe8dc",
        "tab_bg": "#e8e2d6", "tab_selected": "#0b5cab",
        "tab_text": "#5c6570", "tab_text_selected": "#ffffff",
        "border": "#ddd4c6", "header_bg": "#1c3f6e",
        "row_alt": "#d5e4f5", "row_normal": "#fffcf7",
        "card_bg": "#fffcf7", "status_bar": "#fffcf7",
        "status_text": "#1c2128",
        "input_bg": "#fffcf7", "input_border": "#ddd4c6",
        "scrollbar_bg": "#f4f1ea", "scrollbar_handle": "#cfc6b6",
        "menu_bg": "#fffcf7", "menu_text": "#1c2128",
        "menu_hover": "#0b5cab",
        "tooltip_bg": "#1c2128", "tooltip_text": "#ffffff",
        "success": "#1a7f37", "warning": "#9a6700",
        "error": "#cf222e", "info": "#0b5cab",
        "gold": "#8a5a12", "gold_bg": "#f8efd4",
        "toolbar_bg": "#fffcf7", "toolbar_border": "#c4a15a",
        "tray_icon_color": "#0b5cab",
    },
}


def _resolve_auto() -> str:
    """Auto-tema: ljust 07–20, annars mörkt."""
    h = datetime.datetime.now().hour
    return "light" if 7 <= h < 20 else "dark"


def _resolve_system() -> str:
    """
    System-tema: två metoder i prioriteingordning.

    1. QStyleHints.colorScheme() (Qt ≥ 6.5) — idén från PDF reader Pro
       SPEC v2.1 §2.5: läser operativsystemets FAKTISKA mörkt/ljust-läge.
    2. Fallback: systempalettens luminans (äldre Qt / alla plattformar).
    """
    inst = None
    try:
        inst = QApplication.instance()
    except Exception:
        inst = None

    if inst is not None:
        # Metod 1: QStyleHints (Qt 6.5+)
        try:
            hints = inst.styleHints()
            if hints is not None and hasattr(hints, "colorScheme"):
                scheme = hints.colorScheme()
                scheme_name = getattr(scheme, "name", str(scheme))
                if "Dark" in scheme_name:
                    return "dark"
                if "Light" in scheme_name:
                    return "light"
                # 'Unknown' → gå vidare till palett-metoden
        except Exception as exc:
            log.debug("QStyleHints.colorScheme ej tillgänglig: %s", exc)

        # Metod 2: palettens luminans
        try:
            bg = inst.palette().color(QPalette.ColorRole.Window)
            lum = (
                0.299 * bg.red()
                + 0.587 * bg.green()
                + 0.114 * bg.blue()
            )
            return "dark" if lum < 128 else "light"
        except Exception:
            pass
    return "dark"


def resolve_theme(name: str) -> dict:
    """
    Löser ett temanamn till en konkret tema-dict.

    'auto'   → tidbaserat (ljust 07–20)
    'system' → följer operativsystemets mörkt/ljust-läge

    Varje tema WCAG-valideras innan det returneras: textfärger som
    inte håller kontrastkravet (≥ 4.5:1) rättas automatiskt och en
    CONTRAST_ADJUST-rad loggas (ui/contrast.py).
    """
    if name == "auto":
        name = _resolve_auto()
    elif name == "system":
        name = _resolve_system()
    if name not in ("dark", "light"):
        name = "dark"

    theme = dict(THEMES[name])
    try:
        from ui.contrast import enforce_theme_contrast
        theme = enforce_theme_contrast(theme)
    except ImportError:
        try:
            from contrast import enforce_theme_contrast
            theme = enforce_theme_contrast(theme)
        except ImportError:
            pass
    return theme


# ═════════════════════════════════════════════════════════════════════
#  GLOBAL STYLESHEET
# ═════════════════════════════════════════════════════════════════════


def build_stylesheet(t: dict) -> str:
    """Bygger hela appens QSS från en tema-dict."""
    # Luminans i stället för en hårdkodad lista ljusa hexvärden
    # (listan kände inte igen ljustemat #f4f1ea → fel pilfärger).
    def _lum(hexcolor: str) -> float:
        h = str(hexcolor).lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        try:
            r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        except Exception:
            return 0.0
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    is_dark = _lum(t.get("bg", "#0c1218")) < 0.5
    grid = "#8ea4ba" if is_dark else "#8a7d6c"

    return f"""
/* Fakturabunten – Global QSS
   © {COPYRIGHT_YEAR} Rickard Längkvist */

* {{
    font-family : "Segoe UI","SF Pro Display","Helvetica Neue",
                  Arial,sans-serif;
    font-size   : 13px;
    outline     : none;
}}

QMainWindow, QDialog {{
    background-color : {t["bg"]};
    color            : {t["text_strong"]};
}}

QWidget {{
    background-color : {t["bg"]};
    color            : {t["text"]};
}}

/* ── Scrollbars ─────────────────────────────────────────────── */

QScrollBar:vertical {{
    background    : {t["scrollbar_bg"]};
    width         : 12px;
    border-radius : 6px;
    margin        : 0;
    border        : none;
}}
QScrollBar::handle:vertical {{
    background    : {t["scrollbar_handle"]};
    min-height    : 30px;
    border-radius : 6px;
}}
QScrollBar::handle:vertical:hover {{ background: {t["accent"]}; }}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{ height: 0; background: none; }}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{ background: none; }}

QScrollBar:horizontal {{
    background    : {t["scrollbar_bg"]};
    height        : 12px;
    border-radius : 6px;
    margin        : 0;
    border        : none;
}}
QScrollBar::handle:horizontal {{
    background    : {t["scrollbar_handle"]};
    min-width     : 30px;
    border-radius : 6px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t["accent"]}; }}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{ width: 0; background: none; }}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{ background: none; }}

/* ── Labels ─────────────────────────────────────────────────── */

QLabel {{
    color       : {t["text_strong"]};
    font-weight : 700;
    background  : transparent;
}}

/* ── Buttons ────────────────────────────────────────────────── */

QPushButton {{
    background-color : {t["button_bg"]};
    color            : {t["button_text"]};
    font-weight      : 700;
    font-size        : 13px;
    padding          : 8px 16px;
    border-radius    : 8px;
    border           : 1px solid {t["border"]};
    min-height       : 30px;
    min-width        : 0px;
}}
QPushButton:hover {{
    background-color : {t["button_hover"]};
    border-color     : {t["accent"]};
}}
QPushButton:pressed {{
    background-color : {t["accent"]};
    color            : #ffffff;
}}
QPushButton:disabled {{
    background-color : {t["border"]};
    color            : #666666;
    border-color     : {t["border"]};
}}
QPushButton[accent="true"] {{
    background-color : {t["accent"]};
    color            : #ffffff;
    border-color     : {t["accent"]};
}}
QPushButton[accent="true"]:hover {{
    background-color : {t["accent_hover"]};
}}
QPushButton#DonateButton {{
    background-color : {t.get("gold", "#e8b030")};
    color            : #231a00;
    border-color     : {t.get("gold", "#e8b030")};
    font-weight      : 800;
}}
QPushButton#DonateButton:hover {{
    background-color : {t.get("gold_bg", "#f5d67a")};
    border-color     : {t.get("gold", "#e8b030")};
}}
QPushButton#DonateButtonAlt {{
    background-color : {t.get("gold_bg", "#2a2416")};
    color            : {t.get("gold", "#e8b030")};
    border-color     : {t.get("gold", "#e8b030")};
    font-weight      : 800;
}}
QLabel#CountChip {{
    background-color : {t["tab_selected"]};
    color            : #ffffff;
    border-radius    : 11px;
    padding          : 3px 12px;
    font-weight      : 800;
}}
QFrame#DonateCard {{
    background-color : {t.get("gold_bg", t["card_bg"])};
    border           : 1px solid {t.get("gold", t["border"])};
    border-radius    : 12px;
}}
QLabel#DonateTitle {{ color: {t.get("gold", t["text_strong"])}; }}
QFrame#Card, QFrame#SupplierBar, QFrame#SummaryStrip {{
    background-color : {t["card_bg"]};
    border           : 1px solid {t["border"]};
    border-radius    : 12px;
}}
QPushButton[danger="true"] {{
    background-color : {t["error"]};
    color            : #ffffff;
    border-color     : {t["error"]};
}}
QPushButton[success="true"] {{
    background-color : {t["success"]};
    color            : #ffffff;
    border-color     : {t["success"]};
}}
QPushButton[info="true"] {{
    background-color : {t["info"]};
    color            : #ffffff;
    border-color     : {t["info"]};
}}

/* ── Tabs ───────────────────────────────────────────────────── */

QTabWidget::pane {{
    border        : 1px solid {t["border"]};
    background    : {t["bg_secondary"]};
    border-radius : 0 8px 8px 8px;
    top           : -1px;
}}
QTabBar {{ background: transparent; border: none; }}
QTabBar::tab {{
    background    : {t["tab_bg"]};
    color         : {t["tab_text"]};
    font-weight   : 700;
    font-size     : 13px;
    padding       : 9px 18px;
    margin-right  : 3px;
    border-radius : 10px 10px 0 0;
    border        : 1px solid {t["border"]};
    border-bottom : none;
    min-width     : 0px;
}}
QTabBar::tab:selected {{
    background   : {t["tab_selected"]};
    color        : {t["tab_text_selected"]};
    border-color : {t["tab_selected"]};
    font-weight  : 800;
}}
QTabBar::tab:hover:!selected {{
    background   : {t["button_hover"]};
    color        : {t["text_strong"]};
    border-color : {t["accent"]};
}}
QTabBar::scroller {{ width: 28px; }}

/* ── Tables ─────────────────────────────────────────────────── */

QTableWidget, QTableView, QTreeView, QListView {{
    background-color           : {t["row_normal"]};
    color                      : {t["text_strong"]};
    font-weight                : 700;
    font-size                  : 13px;
    gridline-color             : {grid};
    border                     : 1px solid {t["border"]};
    border-radius              : 6px;
    selection-background-color : {t["accent"]};
    selection-color            : #ffffff;
    alternate-background-color : {t["row_alt"]};
    outline                    : none;
}}
QHeaderView::section {{
    background-color : {t["header_bg"]};
    color            : #ffffff;
    font-weight      : 800;
    font-size        : 12px;
    padding          : 8px 10px;
    border           : none;
    border-right     : 1px solid {t["border"]};
    border-bottom    : 1px solid {t["border"]};
}}
QTableWidget::item, QTableView::item {{
    padding : 8px 8px;
    color   : {t["text_strong"]};
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color : {t["accent"]};
    color            : #ffffff;
}}

/* ── Text inputs ─────────────────────────────────────────────── */

QLineEdit, QTextEdit, QPlainTextEdit,
QSpinBox, QDoubleSpinBox, QDateEdit {{
    background-color : {t["input_bg"]};
    color            : {t["text_strong"]};
    font-weight      : 600;
    font-size        : 13px;
    border           : 1.5px solid {t["input_border"]};
    border-radius    : 6px;
    padding          : 6px 10px;
    min-height       : 32px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus {{ border-color: {t["accent"]}; }}

/* ── COMBOBOX ────────────────────────────────────────────────── */

QComboBox {{
    background-color : {t["input_bg"]};
    color            : {t["text_strong"]};
    font-weight      : 700;
    font-size        : 13px;
    border           : 1px solid {t["input_border"]};
    border-radius    : 6px;
    padding          : 4px 28px 4px 10px;
    min-height       : 30px;
}}
QComboBox:focus, QComboBox:on {{
    border-color : {t["accent"]};
}}
QComboBox:hover {{ border-color: {t["accent"]}; }}
QComboBox::drop-down {{
    subcontrol-origin   : padding;
    subcontrol-position : right center;
    width               : 26px;
    border              : none;
    background          : transparent;
}}
QComboBox::down-arrow {{
    width         : 0;
    height        : 0;
    border-left   : 5px solid transparent;
    border-right  : 5px solid transparent;
    border-top    : 6px solid {t["text_strong"]};
    margin-right  : 8px;
}}
QComboBox QAbstractItemView {{
    background-color           : {t["menu_bg"]};
    color                      : {t["text_strong"]};
    font-weight                : 700;
    font-size                  : 13px;
    selection-background-color : {t["accent"]};
    selection-color            : #ffffff;
    border                     : 1px solid {t["border"]};
    outline                    : none;
    padding                    : 4px;
}}
QComboBox QAbstractItemView::item {{
    padding    : 7px 12px;
    min-height : 26px;
    color      : {t["text_strong"]};
}}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {{
    background-color : {t["accent"]};
    color            : #ffffff;
}}

/* ── Menus ──────────────────────────────────────────────────── */

QMenuBar {{
    background-color : {t["bg_secondary"]};
    color            : {t["text_strong"]};
    font-weight      : 700;
    padding          : 2px 4px;
    border-bottom    : 1px solid {t["border"]};
}}
QMenuBar::item {{
    background    : transparent;
    padding       : 6px 14px;
    border-radius : 4px;
    color         : {t["text_strong"]};
    font-weight   : 700;
}}
QMenuBar::item:selected {{ background: {t["accent"]}; color: #ffffff; }}

QMenu {{
    background-color : {t["menu_bg"]};
    color            : {t["menu_text"]};
    font-weight      : 600;
    font-size        : 13px;
    border           : 1px solid {t["border"]};
    border-radius    : 8px;
    padding          : 4px;
}}
QMenu::item {{
    padding       : 6px 22px 6px 12px;
    border-radius : 4px;
    margin        : 1px 2px;
    color         : {t["menu_text"]};
}}
QMenu::item:selected {{
    background-color : {t["menu_hover"]};
    color            : #ffffff;
}}
QMenu::separator {{
    height     : 1px;
    background : {t["border"]};
    margin     : 4px 8px;
}}
QMenu::indicator {{ width: 16px; height: 16px; }}
QMenu::indicator:checked {{
    background    : {t["accent"]};
    border-radius : 3px;
}}
QMenu::indicator:unchecked {{
    background    : {t["input_bg"]};
    border        : 2px solid {t["border"]};
    border-radius : 3px;
}}

/* ── Toolbar ────────────────────────────────────────────────── */

QToolBar {{
    background-color : {t["toolbar_bg"]};
    border-bottom    : 1px solid {t["border"]};
    spacing          : 4px;
    padding          : 4px 8px;
}}
QToolBar QToolButton {{
    background-color : transparent;
    color            : {t["button_text"]};
    font-weight      : 700;
    font-size        : 12px;
    border-radius    : 6px;
    padding          : 4px 10px;
    border           : 1px solid transparent;
    min-height       : 28px;
}}
QToolBar QToolButton:hover {{
    background-color : {t["button_hover"]};
    border-color     : {t["accent"]};
    color            : {t["text_strong"]};
}}
QToolBar QToolButton:pressed {{
    background-color : {t["accent"]};
    color            : #ffffff;
}}
QToolBar::separator {{
    background : {t["border"]};
    width      : 1px;
    margin     : 4px 8px;
}}

/* ── Status bar ─────────────────────────────────────────────── */

QStatusBar {{
    background-color : {t["status_bar"]};
    color            : {t.get("status_text", t["text_strong"])};
    font-weight      : 700;
    font-size        : 12px;
    border-top       : 1px solid {t["border"]};
}}
QStatusBar::item {{ border: none; }}

/* ── Group box ──────────────────────────────────────────────── */

QGroupBox {{
    border        : 1px solid {t["border"]};
    border-radius : 8px;
    margin-top    : 14px;
    font-weight   : 700;
    color         : {t["text_strong"]};
    padding       : 8px 8px 6px 8px;
    background    : {t["bg_secondary"]};
}}
QGroupBox::title {{
    subcontrol-origin   : margin;
    subcontrol-position : top left;
    padding             : 0 8px;
    left                : 12px;
    color               : {t["accent"]};
    background          : {t["bg"]};
}}

/* ── Checkboxes / Radio ─────────────────────────────────────── */

QCheckBox, QRadioButton {{
    color       : {t["text_strong"]};
    font-weight : 600;
    spacing     : 8px;
    background  : transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width         : 18px;
    height        : 18px;
    border        : 2px solid {t["border"]};
    border-radius : 4px;
    background    : {t["input_bg"]};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background   : {t["accent"]};
    border-color : {t["accent"]};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color : {t["accent"]};
}}

/* ── Tooltips ───────────────────────────────────────────────── */

QToolTip {{
    background-color : {t["tooltip_bg"]};
    color            : {t["tooltip_text"]};
    border           : 1px solid {t["border"]};
    border-radius    : 5px;
    padding          : 5px 9px;
    font-weight      : 600;
    font-size        : 12px;
}}

/* ── Progress bar ───────────────────────────────────────────── */

QProgressBar {{
    background-color : {t["bg_secondary"]};
    border           : 1px solid {t["border"]};
    border-radius    : 5px;
    text-align       : center;
    color            : {t["text_strong"]};
    font-weight      : 700;
    min-height       : 18px;
}}
QProgressBar::chunk {{
    background-color : {t["accent"]};
    border-radius    : 5px;
}}

/* ── Misc ───────────────────────────────────────────────────── */

QSplitter::handle {{
    background : {t["border"]};
    width      : 2px;
    height     : 2px;
}}
QDialog {{
    background-color : {t["bg"]};
    border           : 1px solid {t["border"]};
    border-radius    : 10px;
}}
QDialogButtonBox QPushButton {{ min-width: 110px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {t["border"]}; max-height: 1px;
}}

/* ── Calendar ───────────────────────────────────────────────── */

QCalendarWidget {{
    background-color : {t["bg"]};
    color            : {t["text_strong"]};
    border           : 1px solid {t["border"]};
    border-radius    : 8px;
}}
QCalendarWidget QToolButton {{
    background-color : {t["button_bg"]};
    color            : {t["button_text"]};
    font-weight      : 700;
    border-radius    : 4px;
    padding          : 4px 8px;
}}
QCalendarWidget QAbstractItemView {{
    background-color           : {t["bg_secondary"]};
    color                      : {t["text_strong"]};
    selection-background-color : {t["accent"]};
    selection-color            : #ffffff;
    font-weight                : 600;
}}

/* ── Beloppskort (fakturavyn) ───────────────────────────────── */

QFrame#MoneyCard, QFrame#MoneyCardCredit, QFrame#MoneyCardTotal {{
    border-radius : 12px;
    border        : 1px solid {t["border"]};
    background    : {t["card_bg"]};
}}
QFrame#MoneyCardTotal {{
    background : {t.get("gold_bg", t["card_bg"])};
    border     : 1px solid {t.get("gold", t["accent"])};
}}
QLabel#MoneyCaption {{
    color       : {t["text"]};
    font-size   : 11px;
    font-weight : 700;
    background  : transparent;
}}
"""


def apply_app_palette(theme: dict) -> None:
    """
    Sätter QPalette så tabelltext inte faller tillbaka till svart.

    Fusion ignorerar stylesheet-färgen på celler som har egen
    bakgrund och använder palettens Text i stället. Utan den här
    blir fakturarader svart text på mörk statusfärg.
    """
    inst = QApplication.instance()
    if inst is None or not theme:
        return
    text = QColor(theme.get("text_strong", "#f4f7fb"))
    muted = QColor(theme.get("text", "#d5deea"))
    pal = inst.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(theme.get("bg", "#0c1218")))
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(
        QPalette.ColorRole.Base,
        QColor(theme.get("row_normal", theme.get("bg", "#0c1218"))),
    )
    pal.setColor(
        QPalette.ColorRole.AlternateBase,
        QColor(theme.get("row_alt", "#1c3044")),
    )
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(
        QPalette.ColorRole.Button,
        QColor(theme.get("button_bg", "#1c2836")),
    )
    pal.setColor(
        QPalette.ColorRole.ButtonText,
        QColor(theme.get("button_text", "#f4f7fb")),
    )
    pal.setColor(
        QPalette.ColorRole.Highlight,
        QColor("#1f6feb"),
    )
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(
        QPalette.ColorRole.ToolTipBase,
        QColor(theme.get("tooltip_bg", "#1c2836")),
    )
    pal.setColor(
        QPalette.ColorRole.ToolTipText,
        QColor(theme.get("tooltip_text", "#f4f7fb")),
    )
    pal.setColor(QPalette.ColorRole.PlaceholderText, muted)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, muted)
    pal.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, muted
    )
    inst.setPalette(pal)


# ═════════════════════════════════════════════════════════════════════
#  UI-HJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def _font(size: int = 11, bold: bool = False) -> QFont:
    """Typsnittsfabrik — konsekvent typografi i hela fönstret."""
    f = QFont(FONT_FAMILY, size)
    if bold:
        f.setBold(True)
    return f


def _load_app_icon() -> QIcon | None:
    """
    Laddar app_icon.png/.ico/.svg och registrerar flera storlekar
    så aktivitetsfält och tray blir skarpa.
    """
    icon = QIcon()
    png = PROJECT_DIR / "app_icon.png"
    if png.exists():
        pix = QPixmap(str(png))
        if not pix.isNull():
            for size in (16, 20, 24, 32, 48, 64, 128, 256):
                icon.addPixmap(
                    pix.scaled(
                        size, size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
    for name in ("app_icon.ico", "app_icon.svg", "icon.ico", "icon.png"):
        p = PROJECT_DIR / name
        if p.exists():
            icon.addFile(str(p))
    if icon.isNull():
        return None
    return icon


def _make_tray_icon(color: str = "#e8b030") -> QIcon:
    """Fallback om ikonfil saknas: tre kvitton som summeras till en guldrad."""
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#0e3444"))
    p.drawRoundedRect(1, 1, 62, 62, 14, 14)
    p.setBrush(QColor("#f7f3ec"))
    p.drawRoundedRect(14, 12, 36, 8, 3, 3)
    p.drawRoundedRect(18, 24, 28, 8, 3, 3)
    p.drawRoundedRect(22, 36, 20, 8, 3, 3)
    p.setBrush(QColor(color))
    p.drawRoundedRect(10, 48, 44, 10, 3, 3)
    p.end()
    return QIcon(pix)


def _wrap_scroll(widget: QWidget) -> QScrollArea:
    """Wrappar en widget i QScrollArea — mushjul-scroll i alla flikar."""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    sa.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    sa.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setWidget(widget)
    return sa


def _placeholder(icon: str, title: str, subtitle: str = "") -> QWidget:
    """Placeholder-innehåll för flikar som inte byggts ännu."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setAlignment(Qt.AlignmentFlag.AlignCenter)
    v.setSpacing(16)
    v.addStretch()
    for text, size, bold, color in [
        (icon,     54, False, ""),
        (title,    22, True,  ""),
        (subtitle, 12, False, "#888888"),
    ]:
        if not text:
            continue
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(_font(size, bold=bold))
        ss = "background:transparent;"
        if color:
            ss += f" color:{color};"
        lbl.setStyleSheet(ss)
        v.addWidget(lbl)
    v.addStretch()
    return w


def _open_path(path: Path) -> None:
    """Öppnar en fil eller mapp i OS:ets standardprogram."""
    try:
        if not path.is_file():
            path.mkdir(parents=True, exist_ok=True)
        if CURRENT_PLATFORM == "windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif CURRENT_PLATFORM == "macos":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        log.error("_open_path: %s", exc)


def _field(obj: Any, *names: str, default: Any = "") -> Any:
    """
    Hämtar första icke-tomma värdet från dict ELLER objekt.

    Används av confirm_and_export_invoices så att både faktura-dicts
    och objekt med attribut fungerar.
    """
    for n in names:
        if isinstance(obj, dict):
            v = obj.get(n)
        else:
            v = getattr(obj, n, None)
        if v not in (None, ""):
            return v
    return default


# ═════════════════════════════════════════════════════════════════════
#  AUTOSTART FALLBACK  (används bara om app.py saknar manager)
# ═════════════════════════════════════════════════════════════════════


def _set_autostart_os(enable: bool) -> None:
    """Fallback: samma AutostartManager som app.py (startfil i appmappen)."""
    try:
        from app import AutostartManager
        AutostartManager().set_enabled(enable)
    except Exception as exc:
        log.error("_set_autostart_os: %s", exc)


# ═════════════════════════════════════════════════════════════════════
#  EXPORT-BETALNINGSDATUM — PUBLIKT API
#
#  Betalningsdatum hanteras ENBART per PDF-exportbatch.
#  Ingen session-lagring, inget globalt tillstånd.
#  Flöde: bekräftelsedialog → export → nollställning.
# ═════════════════════════════════════════════════════════════════════


def confirm_and_export_invoices(
    parent_widget: QWidget,
    invoices: list,
    due_date: "datetime.date | str",
    export_callback,
    reset_callback=None,
) -> bool:
    """
    Visar bekräftelsedialog innan PDF-export av fakturor.

    Parametrar
    ----------
    parent_widget   : föräldrafönster för dialogen
    invoices        : lista med faktura-dicts/objekt som ska exporteras
    due_date        : betalningsdatum (date-objekt eller ISO-sträng)
    export_callback : funktion(invoices, due_date) som utför exporten,
                      ska returnera (ok: bool, exported_files: list)
    reset_callback  : valfri funktion() som nollställer betalningsdatumet
                      i den anropande vyn efter lyckad export

    Returnerar
    ----------
    True  om exporten genomfördes
    False om användaren avbröt eller exporten misslyckades
    """
    # ── Normalisera datum ─────────────────────────────────────────────
    if isinstance(due_date, str):
        try:
            due_date = datetime.date.fromisoformat(due_date.strip())
        except ValueError:
            QMessageBox.warning(
                parent_widget,
                "Ogiltigt datum",
                f"Betalningsdatumet '{due_date}' är ogiltigt.\n"
                f"Använd formatet ÅÅÅÅ-MM-DD.",
            )
            return False

    if not isinstance(due_date, datetime.date):
        QMessageBox.warning(
            parent_widget,
            "Datum saknas",
            "Inget giltigt betalningsdatum angivet för export.",
        )
        return False

    n = len(invoices)
    date_str = due_date.strftime("%d/%m")   # "10/11"-format i dialogen
    today = datetime.date.today()
    days = (due_date - today).days

    # ── Bygg informationstext ─────────────────────────────────────────
    if days > 0:
        days_txt = f"{days} dagar kvar"
    elif days == 0:
        days_txt = "förfaller idag!"
    else:
        days_txt = f"⚠️  PASSERAT — {abs(days)} dagar sedan"

    invoice_list = ""
    for i, inv in enumerate(invoices[:10]):           # max 10 i listan
        supplier = _field(
            inv, "supplier_name", "supplier", default=f"Faktura {i + 1}"
        )
        amount = _field(inv, "amount", "total", "total_amount")
        ref = _field(inv, "invoice_number", "reference")

        row = f"  • {supplier}"
        if ref:
            row += f"  #{ref}"
        if amount not in (None, ""):
            row += f"  {amount} kr"
        invoice_list += row + "\n"

    if n > 10:
        invoice_list += f"  … och {n - 10} till\n"

    msg = (
        f"Du är på väg att exportera {n} faktura"
        f"{'r' if n != 1 else ''} till PDF.\n\n"
        f"Betalningsdatum : {due_date.isoformat()}  ({date_str})  "
        f"[{days_txt}]\n\n"
        f"Fakturor:\n{invoice_list}\n"
        f"Efter export nollställs betalningsdatumet.\n\n"
        f"Vill du fortsätta?"
    )

    reply = QMessageBox.question(
        parent_widget,
        "📄  Bekräfta PDF-export",
        msg,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if reply != QMessageBox.StandardButton.Yes:
        log.info("PDF-export avbruten av användaren")
        return False

    # ── Genomför exporten ─────────────────────────────────────────────
    try:
        ok, exported = export_callback(invoices, due_date)
    except Exception as exc:
        log.error(
            "export_callback kraschade: %s\n%s",
            exc, traceback.format_exc(),
        )
        QMessageBox.critical(
            parent_widget, "Exportfel", f"Export misslyckades:\n{exc}"
        )
        return False

    if not ok:
        QMessageBox.warning(
            parent_widget,
            "Export misslyckades",
            "Exporten kunde inte genomföras.\n"
            "Kontrollera loggen för detaljer.",
        )
        return False

    # ── Nollställ betalningsdatum i anropande vy ──────────────────────
    if reset_callback is not None:
        try:
            reset_callback()
            log.info(
                "Betalningsdatum nollställt efter export (%d filer)",
                len(exported or []),
            )
        except Exception as exc:
            log.warning("reset_callback: %s", exc)

    # ── Bekräftelse till användaren ───────────────────────────────────
    files_txt = "\n".join(
        f"  • {Path(f).name}" for f in (exported or [])[:8]
    )
    if len(exported or []) > 8:
        files_txt += f"\n  … och {len(exported) - 8} till"

    QMessageBox.information(
        parent_widget,
        "✅  Export klar",
        f"{n} faktura{'r' if n != 1 else ''} exporterade.\n"
        f"Betalningsdatum {due_date.isoformat()} applicerat.\n\n"
        + (f"Filer:\n{files_txt}\n" if files_txt else "")
        + "\nBetalningsdatumet är nollställt.",
    )
    log.info(
        "PDF-export klar: %d fakturor, betaldatum=%s",
        n, due_date.isoformat(),
    )
    return True


# ═════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═════════════════════════════════════════════════════════════════════


class MainWindow(QMainWindow):
    """Centralt huvudfönster för Fakturabunten."""

    theme_changed = Signal(dict)

    #: (nyckel, titel med emoji, ren titel, ikon, undertext)
    _TAB_DEFS: list[tuple[str, str, str, str, str]] = [
        ("dashboard",    "Dashboard",     "🏠  Dashboard",
         "🏠", "Översikt och nyckeltal"),
        ("invoices",     "Fakturor",      "🧾  Fakturor",
         "🧾", "Hantera inkommande fakturor"),
        ("suppliers",    "Leverantörer",  "🏢  Leverantörer",
         "🏢", "Leverantörsregister"),
        ("payments",     "Betalningar",   "💳  Betalningar",
         "💳", "Betalbatcher och betalhistorik"),
        ("import_tab",   "Import",        "📥  Import",
         "📥", "Importera fakturor via PDF / e-post"),
        ("reports",      "Rapporter",     "📊  Rapporter",
         "📊", "Månads- och leverantörsrapporter"),
        ("log_tab",      "Logg",          "🪵  Logg",
         "🪵", "Systemlogg och felsökning"),
        ("settings_tab", "Inställningar", "⚙️  Inställningar",
         "⚙️", "Program- och företagsinställningar"),
    ]

    def __init__(self, app: Any) -> None:
        super().__init__()
        self._app = app
        self._settings = app.settings
        self._tab_map: dict[str, tuple[QScrollArea, QWidget]] = {}
        self._hidden: dict[str, str] = {}
        self._plugins_ui_registered = False
        #: Loggen är en inbyggd flik (ui/log_view.py) — advanced_logger-
        #: pluginet ska INTE lägga till en andra loggflik.
        self._builtin_log_tab = True
        self._invoices_view: QWidget | None = None
        self._suppliers_view: QWidget | None = None
        #: Senast applicerat KONKRETA tema (dark/light) — används av
        #: _refresh_auto_theme för att undvika onödig ommålning/loggspam.
        self._last_resolved_theme: str = ""
        #: Sätts True av _build_settings_panel() — skyddar fliken från
        #: att skrivas över av plugins (loggvyn blir egen flik i stället).
        self._settings_tab_custom: bool = False

        # Språk först — allt UI nedan byggs på valt språk.
        try:
            _i18n_set_language(self._settings.get("language", "sv"))
        except Exception:
            pass

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(860, 560)

        # Egen app-ikon (app_icon.*) med QPainter-fallback
        self._custom_icon = _load_app_icon()
        if self._custom_icon is not None:
            self.setWindowIcon(self._custom_icon)
            app_qt = QApplication.instance()
            if app_qt is not None:
                app_qt.setWindowIcon(self._custom_icon)

        # Återställ dolda flikar från settings
        tab_titles = {d[0]: d[2] for d in self._TAB_DEFS}
        for key in self._settings.get("hidden_tabs", []):
            if key in tab_titles:
                self._hidden[key] = tab_titles[key]

        # ── Debounced geometri-sparning (skriv inte JSON per pixel) ──
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(500)
        self._geometry_timer.timeout.connect(self._save_geometry)

        # ── Flikar ─────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tabs.customContextMenuRequested.connect(
            self._tab_context_menu
        )
        self.setCentralWidget(self.tabs)

        self._build_menu_bar()
        self._build_toolbar()
        self._build_status_bar()
        self._build_tabs()
        self._setup_tray()
        self._apply_theme(self._settings.get("theme", "dark"), save=False)
        self._restore_geometry()
        _ensure_paths()
        self._load_builtin_views()

        # ── Inställningar-fliken: riktig panel (genvägar + plugins) ──
        self._build_settings_panel()

        # ── Konfigurerbara kortkommandon (shortcuts.json) ────────────
        self._shortcut_objects: list = []
        self._build_shortcut_actions()

        # ── GUI-frysningsvakt (heartbeat var 5:e sekund) ─────────────
        self._watchdog = None
        try:
            from app import FreezeWatchdog
            self._watchdog = FreezeWatchdog(interval=5.0, limit=30.0)
            self._beat_timer = QTimer(self)
            self._beat_timer.setInterval(5_000)
            self._beat_timer.timeout.connect(self._watchdog.beat)
            self._beat_timer.start()
            self._watchdog.start()
        except Exception as exc:
            log.debug("FreezeWatchdog ej startad: %s", exc)

        # ── Tema-timer (auto/system uppdateras var 60:e sekund) ──────
        self._theme_timer = QTimer(self)
        self._theme_timer.setInterval(60_000)
        self._theme_timer.timeout.connect(self._refresh_auto_theme)
        self._theme_timer.start()

        self._watch_data_folder()
        ready = "✅  Redo"
        try:
            if hasattr(self._app, "data_load_summary"):
                ready = self._app.data_load_summary()
        except Exception:
            pass
        self.set_status(ready, 8000)
        log.info("MainWindow klar  platform=%s  %s", CURRENT_PLATFORM, ready)

    def _watch_data_folder(self) -> None:
        """
        Om suppliers.json sparas i en editor läser appen om den själv.
        Debounce så en halvskriven fil inte tolkas som tom.
        """
        self._data_watch = QFileSystemWatcher(self)
        self._data_watch_timer = QTimer(self)
        self._data_watch_timer.setSingleShot(True)
        self._data_watch_timer.setInterval(600)
        self._data_watch_timer.timeout.connect(self._refresh_all)
        roots = [PROJECT_DIR / "data", PROJECT_DIR / "ui" / "data"]
        for folder in roots:
            if folder.is_dir():
                self._data_watch.addPath(str(folder))
            for name in ("suppliers.json", "invoices.json", "payments.json"):
                f = folder / name
                if f.is_file():
                    self._data_watch.addPath(str(f))
        self._data_watch.fileChanged.connect(self._on_data_file_changed)
        self._data_watch.directoryChanged.connect(self._on_data_file_changed)

    def _on_data_file_changed(self, _path: str) -> None:
        # os.replace tar bort bevakningen — lägg tillbaka filen.
        for folder in (PROJECT_DIR / "data", PROJECT_DIR / "ui" / "data"):
            if folder.is_dir() and str(folder) not in self._data_watch.directories():
                self._data_watch.addPath(str(folder))
            for name in ("suppliers.json", "invoices.json", "payments.json"):
                f = folder / name
                if f.is_file() and str(f) not in self._data_watch.files():
                    self._data_watch.addPath(str(f))
        self._data_watch_timer.start()

    # ══════════════════════════════════════════════════════════════════
    #  INBYGGDA VYER
    # ══════════════════════════════════════════════════════════════════

    #: (fliknyckel) → (klassnamn, moduler att prova)
    _BUILTIN_VIEWS: dict[str, tuple[str, list[str]]] = {
        "suppliers": ("SuppliersView", ["ui.suppliers_view", "suppliers_view"]),
        "invoices": ("InvoicesView", ["ui.invoices_view", "invoices_view"]),
        "log_tab": ("LogView", ["ui.log_view", "log_view"]),
        "dashboard": ("DashboardView", ["ui.dashboard_view", "dashboard_view"]),
    }

    def _load_builtin_views(self) -> None:
        """Laddar SuppliersView och InvoicesView."""
        _ensure_paths()
        for key, (class_name, modules) in self._BUILTIN_VIEWS.items():
            view = self._safe_load_view(class_name, key, modules)
            setattr(self, f"_{key}_view", view)
            if view:
                log.info("%s laddad ✔", class_name)
            else:
                log.error("%s KUNDE INTE LADDAS ✘", class_name)

    def _show_view_error(self, key: str, error_text: str) -> None:
        """
        Visar en FELRUTA i fliken i stället för en död platshållare.

        Bakgrund: leverantörsfliken dog tyst av ett ImportError i
        månader — användaren såg en till synes normal flik som inte
        gjorde någonting. Nu syns felet + en Försök-igen-knapp.
        """
        if key in self._BUILTIN_VIEWS:
            setattr(self, f"_{key}_view", None)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.setSpacing(12)
        v.addStretch()
        for text, size, bold in [
            ("⚠", 44, False),
            (tr("view.load_failed_title"), 18, True),
            (tr("view.load_failed_body"), 11, False),
        ]:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setFont(_font(size, bold=bold))
            lbl.setStyleSheet("background:transparent;")
            v.addWidget(lbl)
        details = QTextEdit(w)
        details.setReadOnly(True)
        details.setPlainText(error_text)
        details.setMaximumHeight(150)
        v.addWidget(details)
        btn = QPushButton(tr("view.retry"), w)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.clicked.connect(lambda: self._retry_load_view(key))
        v.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
        v.addStretch()
        self.replace_tab_content(key, w)

    def _retry_load_view(self, key: str) -> None:
        """Försök igen-knappen i felrutan: ladda om vyn."""
        spec = self._BUILTIN_VIEWS.get(key)
        if spec is None:
            return
        class_name, modules = spec
        view = self._safe_load_view(class_name, key, modules)
        setattr(self, f"_{key}_view", view)
        if view:
            self.set_status(f"✅  {class_name}", 4000)

    def _safe_load_view(
        self,
        class_name: str,
        tab_key: str,
        module_names: list[str],
    ) -> QWidget | None:
        """Importerar och monterar en vy. Returnerar widget eller None."""
        import importlib
        import importlib.util

        view_class = None
        last_error = ""

        # Försök 1: normal modulimport
        for mod_name in module_names:
            try:
                importlib.invalidate_caches()
                mod = importlib.import_module(mod_name)
                cls = getattr(mod, class_name, None)
                if cls is not None:
                    view_class = cls
                    log.debug(
                        "%s hittad via import('%s')", class_name, mod_name
                    )
                    break
                log.debug(
                    "%s: import('%s') OK men klass saknas. Tillgängligt: %s",
                    class_name, mod_name,
                    [x for x in dir(mod) if not x.startswith("_")],
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.debug(
                    "%s: import('%s') fel: %s", class_name, mod_name, exc
                )

        # Försök 2: direkt filimport
        if view_class is None:
            for fp in [
                BASE_DIR / f"{tab_key}_view.py",
                PROJECT_DIR / "ui" / f"{tab_key}_view.py",
            ]:
                if not fp.exists():
                    continue
                try:
                    spec = importlib.util.spec_from_file_location(
                        fp.stem, str(fp)
                    )
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)  # type: ignore
                        cls = getattr(mod, class_name, None)
                        if cls is not None:
                            view_class = cls
                            log.debug(
                                "%s hittad via direktfil '%s'",
                                class_name, fp,
                            )
                            break
                except Exception as exc:
                    log.warning(
                        "%s direktfil '%s': %s\n%s",
                        class_name, fp, exc, traceback.format_exc(),
                    )

        if view_class is None:
            err = (
                f"KUNDE INTE HITTA KLASSEN {class_name}\n"
                f"Kontrollera att ui/{tab_key}_view.py finns "
                f"och att alla imports i den är korrekta.\n\n"
                f"Senaste importfel: {last_error or 'okänt'}"
            )
            log.error(err)
            self._show_view_error(tab_key, err)
            return None

        try:
            view = view_class(self._app, parent=self)
        except Exception as exc:
            tb = traceback.format_exc()
            log.error(
                "%s __init__ kraschade: %s\n%s", class_name, exc, tb
            )
            self._show_view_error(tab_key, f"{exc}\n\n{tb}")
            return None

        try:
            self.replace_tab_content(tab_key, view)
        except Exception as exc:
            log.error("%s montering: %s", class_name, exc)
            self._show_view_error(tab_key, str(exc))
            return None

        if hasattr(view, "apply_theme"):
            try:
                self.theme_changed.connect(view.apply_theme)
                view.apply_theme(self.current_theme_dict())
            except Exception as exc:
                log.warning("%s apply_theme: %s", class_name, exc)

        return view

    # ══════════════════════════════════════════════════════════════════
    #  PLUGIN-REGISTRERING (fas 2)
    # ══════════════════════════════════════════════════════════════════

    def register_plugins_ui(self, plugins: list) -> None:
        """Kör register_ui(main_window) för externa plugins (en gång)."""
        if self._plugins_ui_registered:
            log.debug("register_plugins_ui: redan kört")
            return
        self._plugins_ui_registered = True

        builtin_names = {"invoices_view", "suppliers_view"}
        for module in plugins:
            name = getattr(module, "__name__", str(module))
            if name in builtin_names:
                continue
            if hasattr(module, "register_ui"):
                try:
                    module.register_ui(self)
                    log.info("plugin fas 2: %s ✔", name)
                except Exception as exc:
                    log.error(
                        "plugin register_ui (%s): %s\n%s",
                        name, exc, traceback.format_exc(),
                    )

    # ══════════════════════════════════════════════════════════════════
    #  MENYRAD
    # ══════════════════════════════════════════════════════════════════

    def _build_menu_bar(self) -> None:
        bar = self.menuBar()

        # ── Arkiv ─────────────────────────────────────────────────────
        m_file = bar.addMenu(tr("menu.file"))

        a_sup = QAction(tr("menu.new_supplier"), self)
        a_sup.setShortcut(self._shortcut_seq("ny_leverantor", "Ctrl+L"))
        a_sup.triggered.connect(self._quick_new_supplier)
        m_file.addAction(a_sup)

        a_inv = QAction(tr("menu.new_invoice"), self)
        a_inv.setShortcut(self._shortcut_seq("ny_faktura", "Ctrl+N"))
        a_inv.triggered.connect(self._quick_new_invoice)
        m_file.addAction(a_inv)

        m_file.addSeparator()

        a_backup = QAction(tr("menu.backup_now"), self)
        a_backup.setShortcut(self._shortcut_seq("skapa_backup", "Ctrl+B"))
        a_backup.triggered.connect(self._manual_backup)
        m_file.addAction(a_backup)

        a_exports = QAction(tr("menu.open_exports"), self)
        a_exports.triggered.connect(self._open_export_folder)
        m_file.addAction(a_exports)

        a_log = QAction(tr("menu.open_log"), self)
        a_log.triggered.connect(self._open_log_file)
        m_file.addAction(a_log)

        m_file.addSeparator()

        a_hide = QAction(tr("menu.minimize_tray"), self)
        a_hide.triggered.connect(self.hide)
        m_file.addAction(a_hide)

        a_quit = QAction(tr("menu.quit"), self)
        a_quit.setShortcut(self._shortcut_seq("avsluta", "Ctrl+Q"))
        a_quit.triggered.connect(self._force_exit)
        m_file.addAction(a_quit)

        # ── Visa ──────────────────────────────────────────────────────
        self._view_menu = bar.addMenu(tr("menu.view"))
        self._rebuild_view_menu()

        # ── Tema ──────────────────────────────────────────────────────
        m_theme = bar.addMenu(tr("menu.theme"))
        for key, label_key in [
            ("dark",   "menu.theme_dark"),
            ("light",  "menu.theme_light"),
            ("auto",   "menu.theme_auto"),
            ("system", "menu.theme_system"),
        ]:
            act = QAction(tr(label_key), self)
            act.triggered.connect(
                lambda checked=False, k=key: self._apply_theme(k)
            )
            m_theme.addAction(act)

        # ── Språk (svenska / engelska, byts direkt) ───────────────────
        m_lang = bar.addMenu(tr("menu.language"))
        self._lang_actions: dict[str, QAction] = {}
        for code in ("sv", "en"):
            act = QAction(_LANGUAGE_NAMES[code], self)
            act.setCheckable(True)
            act.setChecked(_i18n_language() == code)
            act.triggered.connect(
                lambda checked=False, c=code: self._set_language(c)
            )
            m_lang.addAction(act)
            self._lang_actions[code] = act

        # ── Inställningar ─────────────────────────────────────────────
        m_set = bar.addMenu(tr("menu.settings"))

        self._act_autostart = QAction(tr("menu.autostart"), self)
        self._act_autostart.setCheckable(True)
        self._act_autostart.setChecked(self._read_autostart_status())
        self._act_autostart.setToolTip(
            "Startar gömd vid inloggning.\n"
            "Väntar om disken inte är redo. Arbetsmapp = appmappen."
        )
        self._act_autostart.triggered.connect(self._toggle_autostart)
        m_set.addAction(self._act_autostart)

        # Autostart-metod: radioval (utan VBS / startfil)
        self._m_autostart_method = m_set.addMenu(tr("autostart.method"))
        self._m_autostart_method.setToolTip(tr("autostart.method_tip"))
        self._autostart_method_actions: dict = {}
        _method_group = QActionGroup(self)
        _method_group.setExclusive(True)
        _current_method = str(
            self._settings.get("autostart_method", "auto")
        )
        for _method in ("auto", "direct", "launcher"):
            _act = QAction(tr(f"autostart.method_{_method}"), self)
            _act.setCheckable(True)
            _act.setChecked(_current_method == _method)
            _act.triggered.connect(
                lambda _c=False, m=_method: self._set_autostart_method(m)
            )
            _method_group.addAction(_act)
            self._m_autostart_method.addAction(_act)
            self._autostart_method_actions[_method] = _act

        self._act_close_to_tray = QAction(
            tr("menu.close_to_tray"), self
        )
        self._act_close_to_tray.setCheckable(True)
        self._act_close_to_tray.setChecked(
            bool(self._settings.get("close_to_tray", True))
        )
        self._act_close_to_tray.triggered.connect(
            self._toggle_close_to_tray
        )
        m_set.addAction(self._act_close_to_tray)

        self._act_trace = QAction(tr("menu.trace"), self)
        self._act_trace.setCheckable(True)
        self._act_trace.setChecked(
            bool(self._settings.get("log_trace", True))
        )
        self._act_trace.setToolTip(
            "PÅ (standard): varje musklick, tangenttryck, fokusflytt,\n"
            "menyval och fönsterhändelse skrivs till logs/app.log.\n"
            "AV: detaljnivån sänks till DEBUG. Ändringen gäller direkt,\n"
            "ingen omstart krävs."
        )
        self._act_trace.triggered.connect(self._toggle_trace_logging)
        m_set.addAction(self._act_trace)

        self._act_clean_cache = QAction(tr("menu.clean_cache"), self)
        self._act_clean_cache.setCheckable(True)
        self._act_clean_cache.setChecked(
            bool(self._settings.get("clean_cache_on_exit", True))
        )
        self._act_clean_cache.setToolTip(
            "Tömmer __pycache__, *.pyc och kvarlämnade tmp-filer när\n"
            "programmet avslutas. Data, inställningar, loggar och\n"
            "backuper röras aldrig."
        )
        self._act_clean_cache.triggered.connect(self._toggle_clean_cache)
        m_set.addAction(self._act_clean_cache)

        # ── Hjälp ─────────────────────────────────────────────────────
        m_help = bar.addMenu(tr("menu.help"))
        a_about = QAction(tr("menu.about"), self)
        if self._custom_icon is not None:
            a_about.setIcon(self._custom_icon)
        a_about.triggered.connect(self._show_about)
        m_help.addAction(a_about)

        a_donate = QAction(tr("menu.donate"), self)
        a_donate.setToolTip(tr("toolbar.donate_tip"))
        if self._custom_icon is not None:
            a_donate.setIcon(self._custom_icon)
        a_donate.triggered.connect(lambda: open_donate_dialog(self))
        m_help.addAction(a_donate)
        m_help.addSeparator()
        a_diag = QAction(tr("menu.diagnostics"), self)
        a_diag.setToolTip(
            "Kopierar versioner, sökvägar, dataantal, plugin-hälsa,\n"
            "inställningar och senaste loggraderna till urklipp.\n"
            "Klistra in texten i en felrapport eller AI-chatt."
        )
        a_diag.triggered.connect(self._copy_diagnostics)
        m_help.addAction(a_diag)

    def _rebuild_view_menu(self) -> None:
        """Bygger om Visa-menyn med aktuella visa/dölj-statusar."""
        self._view_menu.clear()
        for key, _plain, _title, _icon, _sub in self._TAB_DEFS:
            title = self._tab_title(key)
            act = QAction(title.strip(), self)
            act.setCheckable(True)
            act.setChecked(key not in self._hidden)
            act.triggered.connect(
                lambda checked, k=key, t=title:
                    self._set_tab_visible(k, t, checked)
            )
            self._view_menu.addAction(act)

        self._view_menu.addSeparator()
        a_all = QAction(tr("menu.show_all_tabs"), self)
        a_all.triggered.connect(self._show_all_tabs)
        self._view_menu.addAction(a_all)

    # ══════════════════════════════════════════════════════════════════
    #  TOOLBAR
    # ══════════════════════════════════════════════════════════════════

    def _build_toolbar(self) -> None:
        tb = QToolBar("Verktygsfält", self)
        self._toolbar = tb
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        if self._custom_icon is not None:
            logo = QLabel()
            logo.setPixmap(self._custom_icon.pixmap(28, 28))
            logo.setStyleSheet("background:transparent; padding:0 4px 0 8px;")
            logo.setToolTip(APP_NAME)
            tb.addWidget(logo)
            brand = QLabel(APP_NAME)
            brand.setStyleSheet(
                "background:transparent; font-weight:800; padding-right:10px;"
            )
            tb.addWidget(brand)
            tb.addSeparator()

        def _add(label: str, tip: str, slot) -> None:
            act = QAction(label, self)
            act.setToolTip(tip)
            act.triggered.connect(slot)
            tb.addAction(act)

        _add(tr("toolbar.new_supplier"),
             "Registrera ny leverantör (Ctrl+L)",
             self._quick_new_supplier)
        _add(tr("toolbar.new_invoice"),
             "Registrera ny faktura (Ctrl+N)",
             self._quick_new_invoice)
        tb.addSeparator()
        _add(tr("toolbar.refresh"), "Uppdatera alla vyer", self._refresh_all)
        tb.addSeparator()
        _add(tr("toolbar.backup"), "Skapa backup (Ctrl+B)", self._manual_backup)
        _add(tr("toolbar.exports"), "Öppna exportmappen",
             self._open_export_folder)
        tb.addSeparator()
        _add(tr("toolbar.dark"), "Aktivera mörkt tema",
             lambda: self._apply_theme("dark"))
        _add(tr("toolbar.light"), "Aktivera ljust tema",
             lambda: self._apply_theme("light"))
        tb.addSeparator()
        # 💖 Donation — alltid synlig guldknapp (frivillig, tyst).
        btn_donate = QPushButton(tr("menu.donate").replace("…", "").strip(), tb)
        btn_donate.setObjectName("DonateButton")
        btn_donate.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_donate.setToolTip(tr("toolbar.donate_tip"))
        btn_donate.clicked.connect(lambda: open_donate_dialog(self))
        tb.addWidget(btn_donate)
        tb.addSeparator()
        _add(tr("toolbar.minimize"), "Minimera till systemfältet", self.hide)
        _add(tr("toolbar.quit"), "Avsluta helt (Ctrl+Q)", self._force_exit)

    # ══════════════════════════════════════════════════════════════════
    #  STATUSFÄLT
    # ══════════════════════════════════════════════════════════════════

    def _build_status_bar(self) -> None:
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        if self._custom_icon is not None:
            mark = QLabel()
            mark.setPixmap(self._custom_icon.pixmap(16, 16))
            mark.setStyleSheet("background:transparent; padding-left:6px;")
            sb.addWidget(mark)
        lbl = QLabel(
            f"  {APP_NAME}  v{APP_VERSION}  ·  "
            f"© {COPYRIGHT_YEAR} Rickard Längkvist  ·  "
            f"{CURRENT_PLATFORM}  "
        )
        lbl.setFont(_font(10, bold=True))
        sb.addPermanentWidget(lbl)
        self._btn_status_donate = QPushButton(tr("status.donate"), sb)
        self._btn_status_donate.setObjectName("DonateButton")
        self._btn_status_donate.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor)
        )
        self._btn_status_donate.setToolTip(tr("toolbar.donate_tip"))
        self._btn_status_donate.setMinimumHeight(24)
        self._btn_status_donate.clicked.connect(
            lambda: open_donate_dialog(self)
        )
        sb.addPermanentWidget(self._btn_status_donate)

    # ══════════════════════════════════════════════════════════════════
    #  FLIKAR
    # ══════════════════════════════════════════════════════════════════

    def _tab_title(self, key: str) -> str:
        """Fliktitel på aktuellt språk (med _TAB_DEFS som fallback)."""
        text = tr(f"tab.{key}")
        if text != f"tab.{key}":
            return text
        for k, _plain, title, _icon, _sub in self._TAB_DEFS:
            if k == key:
                return title
        return key

    def _tab_subtitle(self, key: str) -> str:
        text = tr(f"tab.{key}.sub")
        if text != f"tab.{key}.sub":
            return text
        for k, _plain, _title, _icon, sub in self._TAB_DEFS:
            if k == key:
                return sub
        return ""

    def _make_placeholder(self, key: str) -> QWidget:
        icon = next(
            (d[3] for d in self._TAB_DEFS if d[0] == key), "📄"
        )
        return _placeholder(icon, self._tab_title(key).strip(),
                            self._tab_subtitle(key))

    def _build_tabs(self) -> None:
        """Skapar alla flikar med placeholders (vyer monteras senare)."""
        hidden_keys = set(self._hidden.keys())
        #: Flikar som fortfarande bara har platshållare (för språkbyte).
        self._placeholder_keys: set[str] = set()
        for key, _plain, _title, _icon, _sub in self._TAB_DEFS:
            inner = self._make_placeholder(key)
            self._placeholder_keys.add(key)
            scroll = _wrap_scroll(inner)
            self._tab_map[key] = (scroll, inner)
            if key not in hidden_keys:
                self.tabs.addTab(scroll, self._tab_title(key))

    def _tab_index(self, key: str) -> int:
        """Aktuell tab-index för en fliknyckel (-1 om dold/saknas)."""
        scroll, _ = self._tab_map.get(key, (None, None))
        if scroll is None:
            return -1
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) is scroll:
                return i
        return -1

    def _set_tab_visible(
        self, key: str, title: str, visible: bool
    ) -> None:
        """Visar/döljer en flik och sparar i settings (hidden_tabs)."""
        idx = self._tab_index(key)

        if visible and idx == -1:
            # Hitta rätt insättningsposition enligt _TAB_DEFS-ordningen
            order = [k for k, *_ in self._TAB_DEFS]
            pos = order.index(key)
            ins = self.tabs.count()
            for k in order[pos + 1:]:
                i = self._tab_index(k)
                if i != -1:
                    ins = i
                    break
            scroll, _ = self._tab_map[key]
            self.tabs.insertTab(ins, scroll, title)
            self._hidden.pop(key, None)
        elif not visible and idx != -1:
            self.tabs.removeTab(idx)
            self._hidden[key] = title

        self._settings.set("hidden_tabs", list(self._hidden.keys()))
        self._rebuild_view_menu()

    def _show_all_tabs(self) -> None:
        for key, _plain, _title, _icon, _sub in self._TAB_DEFS:
            self._set_tab_visible(key, self._tab_title(key), True)

    def _tab_context_menu(self, pos: QPoint) -> None:
        """Högerklick på flik: dölj flik / visa dolda flikar."""
        bar = self.tabs.tabBar()
        bar_pos = bar.mapFrom(self.tabs, pos)
        idx = bar.tabAt(bar_pos)
        if idx < 0:
            return

        clicked = self.tabs.widget(idx)
        current_key = next(
            (
                k for k, (s, _) in self._tab_map.items() if s is clicked
            ),
            None,
        )
        if not current_key:
            return

        menu = QMenu(self)
        a_hide = QAction(tr("menu.hide_tab"), self)
        a_hide.triggered.connect(
            lambda: self._set_tab_visible(
                current_key, self.tabs.tabText(idx), False
            )
        )
        menu.addAction(a_hide)

        menu.addSeparator()
        a_donate_tab = QAction(tr("menu.donate"), self)
        a_donate_tab.triggered.connect(lambda: open_donate_dialog(self))
        menu.addAction(a_donate_tab)

        if self._hidden:
            menu.addSeparator()
            sub = menu.addMenu(tr("menu.show_hidden"))
            for k, t in self._hidden.items():
                act = QAction(t.strip(), self)
                act.triggered.connect(
                    lambda checked=False, hk=k, ht=t:
                        self._set_tab_visible(hk, ht, True)
                )
                sub.addAction(act)

        menu.exec(bar.mapToGlobal(bar_pos))

    # ══════════════════════════════════════════════════════════════════
    #  PUBLIKT API (används av vyer och plugins)
    # ══════════════════════════════════════════════════════════════════

    def replace_tab_content(self, key: str, new_widget: QWidget) -> None:
        """Ersätter innehållet i en befintlig flik."""
        entry = self._tab_map.get(key)
        if not entry:
            log.warning("replace_tab_content: okänd nyckel '%s'", key)
            return
        scroll, old = entry
        scroll.takeWidget()
        old.deleteLater()
        scroll.setWidget(new_widget)
        self._tab_map[key] = (scroll, new_widget)
        if hasattr(self, "_placeholder_keys"):
            self._placeholder_keys.discard(key)

    def add_plugin_tab(
        self, widget: QWidget, title: str, key: str = ""
    ) -> None:
        """Lägger till en ny plugin-flik."""
        scroll = _wrap_scroll(widget)
        if key:
            self._tab_map[key] = (scroll, widget)
        self.tabs.addTab(scroll, title)

    def current_theme_dict(self) -> dict:
        """Aktuellt tema som dict (löser auto/system)."""
        return resolve_theme(self._settings.get("theme", "dark"))

    def set_status(self, msg: str, timeout: int = 4000) -> None:
        """Visar ett meddelande i statusfältet."""
        self.statusBar().showMessage(msg, timeout)

    def get_invoices_view(self) -> QWidget | None:
        return self._invoices_view

    def get_suppliers_view(self) -> QWidget | None:
        return self._suppliers_view

    # ══════════════════════════════════════════════════════════════════
    #  SNABBAKTIONER
    # ══════════════════════════════════════════════════════════════════

    def _quick_new_supplier(self) -> None:
        """Öppnar leverantörsfliken och startar 'Ny leverantör'."""
        idx = self._tab_index("suppliers")
        if idx == -1:
            self._set_tab_visible(
                "suppliers", self._tab_title("suppliers"), True
            )
            idx = self._tab_index("suppliers")
        self.tabs.setCurrentIndex(idx)

        if self._suppliers_view and hasattr(
            self._suppliers_view, "_add_supplier"
        ):
            self._suppliers_view._add_supplier()
        else:
            QMessageBox.warning(
                self, "Vy ej laddad", "Leverantörsvyn saknas."
            )

    def _quick_new_invoice(self) -> None:
        """
        Öppnar fakturafliken och startar 'Ny faktura'.

        LEVERANTÖRSKONTROLL: minst en leverantör måste finnas innan
        en faktura kan registreras.
        """
        try:
            suppliers = self._app.get_suppliers()
        except Exception:
            suppliers = []

        if not suppliers:
            reply = QMessageBox.question(
                self,
                tr("main.no_supplier_title"),
                tr("main.no_supplier_body"),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._quick_new_supplier()
            return

        idx = self._tab_index("invoices")
        if idx == -1:
            self._set_tab_visible(
                "invoices", self._tab_title("invoices"), True
            )
            idx = self._tab_index("invoices")
        self.tabs.setCurrentIndex(idx)

        if self._invoices_view and hasattr(
            self._invoices_view, "_add_invoice"
        ):
            self._invoices_view._add_invoice()
        else:
            QMessageBox.warning(self, "Vy ej laddad", "Fakturavyn saknas.")

    # ══════════════════════════════════════════════════════════════════
    #  AUTOSTART
    # ══════════════════════════════════════════════════════════════════

    def _read_autostart_status(self) -> bool:
        """Läser faktisk OS-status via AutostartManager (app.py)."""
        try:
            if self._app and hasattr(self._app, "settings"):
                mgr = self._app.settings.get_autostart_manager()
                return mgr.is_enabled()
        except Exception:
            pass
        return bool(self._settings.get("startup", False))

    def _toggle_autostart(self, checked: bool) -> None:
        """Kryssruta i Inställningar-menyn → synka settings + OS."""
        try:
            if self._app and hasattr(self._app, "settings"):
                self._app.settings.set("startup", checked)
            else:
                _set_autostart_os(checked)
                self._settings.set("startup", checked)
        except Exception as exc:
            log.error("_toggle_autostart: %s", exc)
            QMessageBox.warning(
                self, tr("main.autostart"),
                tr("main.autostart_error", error=exc)
            )
            return

        actual = checked
        message = (
            tr("main.autostart_on")
            if checked
            else tr("main.autostart_off")
        )
        try:
            if self._app and hasattr(self._app, "settings"):
                mgr = self._app.settings.get_autostart_manager()
                actual = mgr.is_enabled()
                message = mgr.user_message(actual)
                if _i18n_language() == "en":
                    # app.py:s user_message är svenska — bygg EN-text här
                    if actual:
                        plan = mgr.plan()
                        if plan.get("resolved_method") == "direct":
                            message = tr(
                                "main.autostart_on_direct",
                                workdir=plan["working_directory"],
                                command=plan["os_command"],
                            )
                        else:
                            message = tr(
                                "main.autostart_on_full",
                                workdir=plan["working_directory"],
                                launcher=plan["launcher"],
                            )
                    else:
                        message = tr("main.autostart_off")
                self._sync_autostart_checkboxes(actual)
        except Exception:
            pass
        if checked and not actual:
            QMessageBox.warning(
                self,
                tr("main.autostart"),
                tr("main.autostart_failed"),
            )
            return
        txt = tr("main.on_check") if actual else tr("main.off")
        self.set_status(tr("main.autostart_status", state=txt), 4000)
        QMessageBox.information(self, tr("main.autostart"), message)

    def _set_autostart_method(self, method: str) -> None:
        """Byter autostart-metod; registrerar om hos OS om den är på."""
        ok = True
        try:
            self._settings.set("autostart_method", method)
            if self._app and hasattr(self._app, "settings"):
                mgr = self._app.settings.get_autostart_manager()
                if mgr.is_enabled():
                    ok = bool(mgr.set_enabled(True))
        except Exception as exc:
            log.error("_set_autostart_method: %s", exc)
            ok = False
        for key, act in self._autostart_method_actions.items():
            act.setChecked(key == method)
        self.set_status(
            tr(
                "autostart.method_set",
                method=tr(f"autostart.method_{method}"),
            ),
            4000,
        )
        if not ok:
            QMessageBox.warning(
                self,
                tr("main.autostart"),
                tr("autostart.method_failed"),
            )

    def _toggle_close_to_tray(self, checked: bool) -> None:
        """Kryssruta: göm till tray vid kryss."""
        self._settings.set("close_to_tray", checked)
        self.set_status(
            tr(
                "main.close_tray_status",
                state=tr("main.on") if checked else tr("main.off_state"),
            ),
            4000,
        )
        log.info("close_to_tray → %s", checked)

    def _toggle_trace_logging(self, checked: bool) -> None:
        """
        Kryssruta: logga VARJE tryck (TRACE) PÅ/AV.

        Sparas i settings.json → advanced_logger lyssnar på
        settings-ändringen och byter loggnivå DIREKT (ingen omstart).
        """
        self._settings.set("log_trace", checked)
        self.set_status(
            f"🔬  TRACE-loggning (varje tryck): "
            f"{'PÅ' if checked else 'AV'}", 5000
        )
        log.info("log_trace → %s", checked)

    def _toggle_clean_cache(self, checked: bool) -> None:
        """Kryssruta: Smart Cache-rensare PÅ/AV (tömmer cache vid avslut)."""
        self._settings.set("clean_cache_on_exit", checked)
        self.set_status(
            f"🧹  Töm cache vid avslut: {'PÅ' if checked else 'AV'}", 4000
        )
        log.info("clean_cache_on_exit → %s", checked)

    def set_autostart(self, enable: bool) -> None:
        """Programmatisk autostart-sättning (synkar även kryssrutan)."""
        try:
            if self._app and hasattr(self._app, "settings"):
                self._app.settings.set("startup", enable)
            else:
                _set_autostart_os(enable)
                self._settings.set("startup", enable)
        except Exception as exc:
            log.error("set_autostart: %s", exc)
        if hasattr(self, "_act_autostart"):
            self._act_autostart.setChecked(enable)
        log.info("set_autostart → %s", enable)

    def _sync_autostart_checkboxes(self, checked: bool) -> None:
        """Synkar autostart-kryssrutorna i meny och tray."""
        if hasattr(self, "_act_autostart"):
            self._act_autostart.setChecked(checked)
        if hasattr(self, "_tray_act_autostart"):
            self._tray_act_autostart.setChecked(checked)

    # ══════════════════════════════════════════════════════════════════
    #  SPRÅK  (svenska / engelska — byts direkt, ingen omstart)
    # ══════════════════════════════════════════════════════════════════

    def _set_language(self, code: str) -> None:
        """Byter gränssnittsspråk, sparar valet och ritar om texterna."""
        code = _i18n_set_language(code)
        try:
            self._settings.set("language", code)
        except Exception:
            pass
        self._retranslate_ui()
        self.set_status(tr("menu.language_changed"), 4000)
        log.info("Språk → %s", code)

    def _retranslate_ui(self) -> None:
        """
        Ritar om all text på aktuellt språk.

        Menyer/verktygsfält byggs om från grunden (samma byggmetoder
        som vid start), fliktitlar sätts om, platshållare byggs om och
        varje monterad vy får anropet retranslate() om den har ett.
        """
        # Menyer (inkl. Visa-menyn och krysslägen)
        self.menuBar().clear()
        self._build_menu_bar()
        # Verktygsfält
        if hasattr(self, "_toolbar"):
            self.removeToolBar(self._toolbar)
            self._toolbar.deleteLater()
        self._build_toolbar()
        # Fliktitlar (synliga) + dolda flikars titlar
        for key in list(self._hidden):
            self._hidden[key] = self._tab_title(key)
        for key, (scroll, _inner) in self._tab_map.items():
            idx = self.tabs.indexOf(scroll)
            if idx != -1:
                self.tabs.setTabText(idx, self._tab_title(key))
        # Platshållare byggs om på nya språket
        for key in list(getattr(self, "_placeholder_keys", set())):
            self.replace_tab_content(key, self._make_placeholder(key))
            self._placeholder_keys.add(key)
        # Statusfältets donationsknapp
        if hasattr(self, "_btn_status_donate"):
            self._btn_status_donate.setText(tr("status.donate"))
        # Inställningsfliken (byggs om med nya texter + språkväljare)
        self._build_settings_panel()
        # Monterade vyer
        seen: set[int] = set()
        for _key, (_scroll, inner) in self._tab_map.items():
            if id(inner) in seen:
                continue
            seen.add(id(inner))
            fn = getattr(inner, "retranslate", None)
            if callable(fn):
                try:
                    fn()
                except Exception as exc:
                    log.warning("retranslate %s: %s", _key, exc)
        # Tray-menyn på nya språket
        if hasattr(self, "tray"):
            self.tray.setContextMenu(self._build_tray_menu())

    # ══════════════════════════════════════════════════════════════════
    #  TEMA-MOTOR
    # ══════════════════════════════════════════════════════════════════

    def _apply_theme(self, name: str, save: bool = True) -> None:
        """Applicerar tema globalt och emitterar theme_changed."""
        if name not in VALID_THEMES:
            name = "dark"
        if save:
            self._settings.set("theme", name)

        theme = resolve_theme(name)
        # Kom ihåg vilket KONKRET tema (dark/light) som nu applicerats —
        # så att 60-sekundersrefreshen kan hoppa över ommålning när
        # upplöst tema är oförändrat (annars målas hela fönstret om
        # i onödan och loggen spammas).
        self._last_resolved_theme = theme.get("name", name)
        inst = QApplication.instance()
        if inst is not None:
            apply_app_palette(theme)
            inst.setStyleSheet(build_stylesheet(theme))

        if hasattr(self, "tray"):
            # Egen ikon behålls vid temabyte; annars ritas tray-ikonen om
            if getattr(self, "_custom_icon", None) is None:
                self.tray.setIcon(
                    _make_tray_icon(
                        theme.get("tray_icon_color", "#58a6ff")
                    )
                )

        self.theme_changed.emit(theme)
        log.info("Tema → %s", name)

    def _refresh_auto_theme(self) -> None:
        """
        Var 60:e sekund: uppdatera auto/system-teman.

        Applicera OM och ENDAST OM det upplösta temat (dark/light)
        faktiskt har ändrats. Annars hoppar vi över — ingen onödig
        ommålning av hela fönstret och inget loggspam var 60:e sekund.
        """
        current = self._settings.get("theme", "dark")
        if current not in ("auto", "system"):
            return

        resolved_name = resolve_theme(current).get("name", current)
        if resolved_name == getattr(self, "_last_resolved_theme", None):
            # Samma konkreta tema som redan visas → gör ingenting.
            return

        self._apply_theme(current, save=False)

    # ══════════════════════════════════════════════════════════════════
    #  SYSTEM TRAY
    # ══════════════════════════════════════════════════════════════════

    def _setup_tray(self) -> None:
        """Skapar tray-ikon med meny. Exakt EN ikon i processen."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("System tray ej tillgängligt")
            return

        theme = resolve_theme(self._settings.get("theme", "dark"))
        tray_icon = (
            self._custom_icon
            if getattr(self, "_custom_icon", None) is not None
            else _make_tray_icon(theme.get("tray_icon_color", "#58a6ff"))
        )
        self.tray = QSystemTrayIcon(tray_icon, self)
        self.tray.setToolTip(tr("tray.tooltip", app=APP_NAME))
        self.tray.setContextMenu(self._build_tray_menu())
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _build_tray_menu(self) -> QMenu:
        """Systemfältsmenyn — byggs om vid språkbyte."""
        m = QMenu()

        a_show = QAction(tr("tray.show"), self)
        a_show.triggered.connect(self._bring_to_front)
        m.addAction(a_show)
        m.addSeparator()

        a_sup = QAction(tr("menu.new_supplier"), self)
        a_sup.triggered.connect(self._tray_new_supplier)
        m.addAction(a_sup)

        a_inv = QAction(tr("menu.new_invoice"), self)
        a_inv.triggered.connect(self._tray_new_invoice)
        m.addAction(a_inv)
        m.addSeparator()

        tm = m.addMenu(tr("tray.theme"))
        for key, label_key in [
            ("dark",   "menu.theme_dark"),
            ("light",  "menu.theme_light"),
            ("auto",   "menu.theme_auto"),
            ("system", "menu.theme_system"),
        ]:
            act = QAction(tr(label_key), self)
            act.triggered.connect(
                lambda checked=False, k=key: self._apply_theme(k)
            )
            tm.addAction(act)
        m.addSeparator()

        self._tray_act_autostart = QAction(tr("menu.autostart"), self)
        self._tray_act_autostart.setCheckable(True)
        self._tray_act_autostart.setChecked(self._read_autostart_status())
        self._tray_act_autostart.triggered.connect(
            self._tray_autostart_toggled
        )
        m.addAction(self._tray_act_autostart)
        m.addSeparator()

        a_backup = QAction(tr("tray.backup"), self)
        a_backup.triggered.connect(self._manual_backup)
        m.addAction(a_backup)

        a_exports = QAction(tr("tray.exports"), self)
        a_exports.triggered.connect(self._open_export_folder)
        m.addAction(a_exports)
        m.addSeparator()

        a_hide = QAction(tr("tray.minimize"), self)
        a_hide.triggered.connect(self.hide)
        m.addAction(a_hide)

        a_donate_tray = QAction(tr("menu.donate"), self)
        a_donate_tray.triggered.connect(lambda: open_donate_dialog(self))
        m.addAction(a_donate_tray)
        m.addSeparator()

        a_quit = QAction(tr("tray.quit"), self)
        a_quit.triggered.connect(self._force_exit)
        m.addAction(a_quit)
        return m

    def _tray_new_supplier(self) -> None:
        self._bring_to_front()
        self._quick_new_supplier()

    def _tray_new_invoice(self) -> None:
        self._bring_to_front()
        self._quick_new_invoice()

    def _tray_autostart_toggled(self, checked: bool) -> None:
        self._toggle_autostart(checked)
        self._sync_autostart_checkboxes(checked)

    def _tray_activated(
        self, reason: QSystemTrayIcon.ActivationReason
    ) -> None:
        """Enkelklick/dubbelklick på tray-ikonen → öppna fönstret."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._bring_to_front()

    def _bring_to_front(self) -> None:
        """Visar och fokuserar fönstret."""
        if self.isMinimized():
            self.showNormal()
        elif not self.isVisible():
            # show() respekterar sparat tillstånd (maximerat/normalt) —
            # showNormal() skulle tvinga ner ett maximerat fönster.
            self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        """Kryss → göm till tray (om close_to_tray), annars avsluta."""
        close_to_tray = bool(self._settings.get("close_to_tray", True))
        if (
            close_to_tray
            and hasattr(self, "tray")
            and self.tray.isVisible()
        ):
            event.ignore()
            self.hide()
            self.tray.showMessage(
                APP_NAME,
                "Programmet körs i systemfältet.\n"
                "Enkelklicka på ikonen för att öppna.\n"
                "Högerklicka → Avsluta helt.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        else:
            self._save_geometry()
            if hasattr(self, "tray"):
                self.tray.hide()
            event.accept()

    def _force_exit(self) -> None:
        """Avsluta helt — med bekräftelse."""
        reply = QMessageBox.question(
            self,
            tr("main.quit_title"),
            tr("main.quit_body", app=APP_NAME),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._save_geometry()
            if self._watchdog is not None:
                self._watchdog.stop()
            if hasattr(self, "tray"):
                self.tray.hide()
            log.info("Programmet avslutas av användaren")
            QApplication.quit()

    # ══════════════════════════════════════════════════════════════════
    #  ACTIONER
    # ══════════════════════════════════════════════════════════════════

    def _refresh_all(self) -> None:
        """Läser om data/ från disk och uppdaterar alla vyer."""
        self.set_status(tr("main.reading"))
        summary = ""
        try:
            if hasattr(self._app, "rescan_data"):
                summary = self._app.rescan_data()
        except Exception as exc:
            log.error("rescan_data: %s", exc)
        self.theme_changed.emit(self.current_theme_dict())
        for key, (_, inner) in self._tab_map.items():
            for method in ("refresh", "_do_refresh"):
                if hasattr(inner, method):
                    try:
                        getattr(inner, method)()
                    except Exception as exc:
                        log.warning(
                            "refresh %s.%s: %s", key, method, exc
                        )
                    break
        self.set_status(
            f"✅  {summary}" if summary else "✅  Uppdaterad", 6000
        )

    def _manual_backup(self) -> None:
        """Skapar en backup via app.backup."""
        try:
            result = self._app.backup.create()
            if result:
                self.set_status(f"💾  Backup: {result.name}", 5000)
                QMessageBox.information(
                    self, "Backup",
                    tr("main.backup_created", path=str(result))
                )
            else:
                QMessageBox.warning(
                    self, "Backup", tr("main.backup_failed")
                )
        except AttributeError:
            QMessageBox.information(
                self, "Backup", "Backup-modulen är inte tillgänglig."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Backup-fel", str(exc))

    def _open_export_folder(self) -> None:
        """Öppnar exports/ i appmappen. Aldrig en mapp utanför."""
        export_path = PROJECT_DIR / "exports"
        try:
            from ui.invoices_helpers import get_export_base
            export_path = get_export_base()
        except Exception:
            export_path.mkdir(parents=True, exist_ok=True)
        _open_path(export_path)
        self.set_status(tr("main.opening", path=export_path), 3000)

    def _open_log_file(self) -> None:
        """Öppnar app.log i OS:ets standardprogram."""
        for name in ("logs/app.log", "app.log"):
            p = PROJECT_DIR / name
            if p.exists():
                _open_path(p)
                return
        QMessageBox.information(self, "Logg", "Ingen loggfil hittades.")

    # ══════════════════════════════════════════════════════════════════
    #  DIAGNOSTIK  ("Kopiera diagnostik" — Hjälp-menyn)
    # ══════════════════════════════════════════════════════════════════

    def _copy_diagnostics(self) -> None:
        """
        Kopierar komplett diagnostik till urklipp (idén från PDF reader
        Pro SPEC v2.1 §2.3). Texten kan klistras in i en felrapport
        eller en AI-chatt. Knappen får ALDRIG vara död — fallback bygger
        en minimidiagnostik lokalt.
        """
        text: str | None = None
        try:
            text = self._app.diagnostics()
        except Exception as exc:
            log.warning("app.diagnostics() föll tillbaka: %s", exc)
        if not text:
            text = (
                f"{APP_NAME} — DIAGNOSTIK (minimal)\n"
                f"Version   : {APP_VERSION}\n"
                f"Plattform : {CURRENT_PLATFORM}\n"
                f"Python    : {sys.version.split()[0]}\n"
                f"Tema      : {self._settings.get('theme', 'dark')}\n"
                f"Appmapp   : {PROJECT_DIR}\n"
            )
        try:
            QApplication.clipboard().setText(text)
            self.set_status("🩺  Diagnostik kopierad till urklipp", 6000)
            QMessageBox.information(
                self,
                "🩺  Diagnostik kopierad",
                "Diagnostiken ligger i urklipp.\n\n"
                "Klistra in den i din felrapport eller AI-chatt.\n"
                "(Versioner, sökvägar, dataantal, plugin-hälsa,\n"
                "inställningar och de senaste loggraderna.)",
            )
            log.info("DIAGNOSTICS_COPIED: %d tecken", len(text))
        except Exception as exc:
            log.error("_copy_diagnostics: %s", exc)
            QMessageBox.warning(
                self, "Diagnostik", f"Kunde inte kopiera:\n{exc}"
            )

    # ══════════════════════════════════════════════════════════════════
    #  KORTKOMMANDON  (konfigurerbara via shortcuts.json)
    # ══════════════════════════════════════════════════════════════════

    def _shortcut_seq(self, action: str, fallback: str) -> QKeySequence:
        """Hämtar en kortkommando-sekvens från ShortcutManager (app.py)."""
        mgr = getattr(self._app, "shortcuts", None)
        if mgr is not None:
            try:
                seq = mgr.get(action)
                if seq:
                    return QKeySequence(seq)
            except Exception:
                pass
        return QKeySequence(fallback)

    def _build_shortcut_actions(self) -> None:
        """
        (Om)bygger alla QShortcut utifrån shortcuts.json:

        • Ctrl+1–7 : hoppa till flik (visar fliken om den är dold)
        • F5       : uppdatera alla vyer

        Anropas vid start och efter varje sparad genvägsändring.
        """
        # Ta bort gamla genvägar
        for sc in getattr(self, "_shortcut_objects", []):
            try:
                sc.deleteLater()
            except Exception:
                pass
        self._shortcut_objects = []

        tab_shortcuts = [
            ("tab_dashboard",     "dashboard"),
            ("tab_fakturor",      "invoices"),
            ("tab_leverantorer",  "suppliers"),
            ("tab_betalningar",   "payments"),
            ("tab_import",        "import_tab"),
            ("tab_rapporter",     "reports"),
            ("tab_installningar", "settings_tab"),
            ("tab_logg",          "log_tab"),
        ]
        fallback = [
            "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4",
            "Ctrl+5", "Ctrl+6", "Ctrl+7", "Ctrl+8",
        ]
        for i, (action, key) in enumerate(tab_shortcuts):
            seq = self._shortcut_seq(action, fallback[i])
            if seq.isEmpty():
                continue
            sc = QShortcut(seq, self)
            sc.activated.connect(
                lambda k=key: self._goto_tab(k, self._tab_title(k))
            )
            self._shortcut_objects.append(sc)

        seq = self._shortcut_seq("uppdatera", "F5")
        if not seq.isEmpty():
            sc = QShortcut(seq, self)
            sc.activated.connect(self._refresh_all)
            self._shortcut_objects.append(sc)

        log.debug(
            "Kortkommandon aktiva: %d st", len(self._shortcut_objects)
        )

    def _goto_tab(self, key: str, title: str) -> None:
        """Hoppa till flik — visar den först om den är dold."""
        idx = self._tab_index(key)
        if idx == -1:
            self._set_tab_visible(key, title, True)
            idx = self._tab_index(key)
        if idx != -1:
            self.tabs.setCurrentIndex(idx)

    # ══════════════════════════════════════════════════════════════════
    #  INSTÄLLNINGSFLIKEN  (kortkommandon + plugin-återställning)
    # ══════════════════════════════════════════════════════════════════

    def _build_settings_panel(self) -> None:
        """
        Bygger Inställningar-flikens innehåll:

        • Kortkommandon  — redigerbar tabell, sparas i shortcuts.json
        • Plugins        — status + återställning av 3-strikes-spärrade

        Flaggan _settings_tab_custom talar om för plugins (t.ex.
        advanced_logger) att fliken har EGET innehåll och inte får
        skrivas över — loggvyn blir då en separat flik i stället.
        """
        self._settings_tab_custom = True
        panel = QWidget()
        root = QVBoxLayout(panel)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(14)

        hdr = QLabel(tr("settings.title"))
        hdr.setFont(_font(16, bold=True))
        root.addWidget(hdr)

        # ── Språk ─────────────────────────────────────────────────────
        box_lang = QGroupBox(tr("settings.language"))
        v_lang = QHBoxLayout(box_lang)
        self._lang_combo = QComboBox()
        for code in ("sv", "en"):
            self._lang_combo.addItem(_LANGUAGE_NAMES[code], code)
        self._lang_combo.setCurrentIndex(
            0 if _i18n_language() == "sv" else 1
        )
        self._lang_combo.currentIndexChanged.connect(
            lambda i: self._set_language(
                self._lang_combo.itemData(i) or "sv"
            )
        )
        lbl_lang_hint = QLabel(tr("settings.language_hint"))
        lbl_lang_hint.setStyleSheet("color:#8b949e; background:transparent;")
        v_lang.addWidget(self._lang_combo)
        v_lang.addWidget(lbl_lang_hint)
        v_lang.addStretch(1)
        root.addWidget(box_lang)

        # ── Donation (frivilligt stöd) ────────────────────────────────
        box_donate = QGroupBox(tr("settings.donate_group"))
        v_donate = QVBoxLayout(box_donate)
        v_donate.setSpacing(8)
        lbl_donate = QLabel(tr("settings.donate_text"))
        lbl_donate.setWordWrap(True)
        lbl_donate.setStyleSheet("background:transparent;")
        v_donate.addWidget(lbl_donate)
        btn_donate_settings = QPushButton(tr("settings.donate_open"))
        btn_donate_settings.setObjectName("DonateButton")
        btn_donate_settings.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor)
        )
        btn_donate_settings.clicked.connect(
            lambda: open_donate_dialog(self)
        )
        v_donate.addWidget(btn_donate_settings)
        root.addWidget(box_donate)

        # ── Kortkommandon ─────────────────────────────────────────────
        box_keys = QGroupBox(tr("settings.shortcuts"))
        v_keys = QVBoxLayout(box_keys)
        v_keys.setSpacing(8)

        self._shortcut_editors: list[tuple[str, QKeySequenceEdit]] = []

        tbl = QTableWidget(0, 2)
        tbl.setColumnCount(2)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        tbl.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        tbl.setAlternatingRowColors(True)
        tbl.setShowGrid(False)

        labels: dict[str, str] = {}
        defaults: dict[str, str] = {}
        try:
            from app import SHORTCUT_LABELS, DEFAULT_SHORTCUTS
            labels = dict(SHORTCUT_LABELS)
            defaults = dict(DEFAULT_SHORTCUTS)
        except ImportError:
            pass

        mgr = getattr(self._app, "shortcuts", None)
        rows = list(labels.items()) if labels else [
            ("ny_leverantor", "Ny leverantör"),
            ("ny_faktura", "Ny faktura"),
            ("skapa_backup", "Skapa backup"),
            ("uppdatera", "Uppdatera alla vyer"),
            ("avsluta", "Avsluta programmet"),
        ]
        tbl.setRowCount(len(rows))
        for r, (action, label) in enumerate(rows):
            # Visningsetikett på aktuellt språk (shortcut.<id> i i18n);
            # svensk standardetikett som fallback för okända nycklar.
            _alt = tr(f"shortcut.{action}")
            if _alt != f"shortcut.{action}":
                label = _alt
            if mgr is not None:
                try:
                    seq = mgr.get(action)
                except Exception:
                    seq = defaults.get(action, "")
            else:
                seq = defaults.get(action, "")
            cell = QTableWidgetItem(label)
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(r, 0, cell)
            editor = QKeySequenceEdit(QKeySequence(seq or ""))
            editor.setClearButtonEnabled(True)
            tbl.setCellWidget(r, 1, editor)
            self._shortcut_editors.append((action, editor))

        tbl.resizeColumnsToContents()
        tbl.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        tbl.setMinimumHeight(min(60 + 38 * len(rows), 460))
        v_keys.addWidget(tbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_save = QPushButton(tr("settings.save_shortcuts"))
        btn_save.clicked.connect(self._save_shortcuts_panel)
        btn_reset = QPushButton(tr("settings.reset_shortcuts"))
        btn_reset.clicked.connect(self._reset_shortcuts_panel)
        hint = QLabel(tr("settings.shortcuts_hint"))
        hint.setStyleSheet("color:#8b949e; background:transparent;")
        hint.setFont(_font(10))
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch(1)
        btn_row.addWidget(hint)
        v_keys.addLayout(btn_row)
        root.addWidget(box_keys)

        # ── Plugins ───────────────────────────────────────────────────
        box_plug = QGroupBox(tr("settings.plugins"))
        v_plug = QVBoxLayout(box_plug)
        v_plug.setSpacing(6)

        self._plugin_status_label = QLabel()
        self._plugin_status_label.setFont(_font(11))
        self._plugin_status_label.setWordWrap(True)
        self._refresh_plugin_status_label()
        v_plug.addWidget(self._plugin_status_label)

        btn_reenable = QPushButton(tr("settings.reenable_plugins"))
        btn_reenable.setToolTip(
            "Nollställer kraschräknarna och lyfter bort 3-strikes-"
            "spärren.\nPlugins försöks laddas igen vid nästa programstart."
        )
        btn_reenable.clicked.connect(self._reenable_plugins)
        v_plug.addWidget(btn_reenable)
        root.addWidget(box_plug)

        note = QLabel(tr("settings.note"))
        note.setStyleSheet("color:#8b949e; background:transparent;")
        note.setFont(_font(10))
        root.addWidget(note)
        root.addStretch(1)

        self.replace_tab_content("settings_tab", panel)

    def _refresh_plugin_status_label(self) -> None:
        """Uppdaterar plugin-status-texten i Inställningar-fliken."""
        if not hasattr(self, "_plugin_status_label"):
            return
        try:
            status = self._app.plugin_loader.status()
            loaded = ", ".join(status["loaded"]) or "(inga)"
            lines = [f"Laddade: {loaded}"]
            if status["disabled"]:
                lines.append(
                    "⛔ Avaktiverade (3 krascher): "
                    + ", ".join(status["disabled"])
                )
            if status["strikes"]:
                lines.append(f"Kraschräknare: {status['strikes']}")
            self._plugin_status_label.setText("\n".join(lines))
        except Exception as exc:
            self._plugin_status_label.setText(
                tr("main.plugin_status_na", error=exc)
            )

    def _save_shortcuts_panel(self) -> None:
        """Sparar redigerade kortkommandon till shortcuts.json."""
        mgr = getattr(self._app, "shortcuts", None)
        if mgr is None:
            QMessageBox.warning(
                self, "Kortkommandon", "ShortcutManager saknas i app-kärnan."
            )
            return
        changed = 0
        for action, editor in self._shortcut_editors:
            seq = editor.keySequence().toString()
            if seq != mgr.get(action):
                mgr.set(action, seq)
                changed += 1
        self._build_shortcut_actions()
        self.set_status(
            f"⌨️  {changed} kortkommando(n) sparade", 5000
        )
        log.info("SHORTCUT_SAVE: %d ändring(ar) sparade", changed)

    def _reset_shortcuts_panel(self) -> None:
        """Återställer alla kortkommandon till standard."""
        mgr = getattr(self._app, "shortcuts", None)
        if mgr is None:
            return
        mgr.reset_all()
        for action, editor in self._shortcut_editors:
            editor.setKeySequence(QKeySequence(mgr.get(action)))
        self._build_shortcut_actions()
        self.set_status(tr("main.shortcuts_restored"), 5000)

    def _reenable_plugins(self) -> None:
        """Återställer 3-strikes-avaktiverade plugins."""
        try:
            self._app.reenable_plugins()
        except Exception as exc:
            QMessageBox.warning(
                self, "Plugins", f"Kunde inte återställa:\n{exc}"
            )
            return
        self._refresh_plugin_status_label()
        QMessageBox.information(
            self,
            "🧩  Plugins återställda",
            "Kraschräknare nollställda och spärrar borttagna.\n\n"
            "Avaktiverade plugins försöks laddas igen\n"
            "vid nästa programstart.",
        )

    # ══════════════════════════════════════════════════════════════════
    #  GEOMETRI  (sparas i settings.json, debounced)
    # ══════════════════════════════════════════════════════════════════

    def _restore_geometry(self) -> None:
        """
        Återställ storlek/position från settings.

        VIKTIGT FIX: den sparade positionen VALIDERAS mot alla
        anslutna skärmar. Om den pekar utanför (t.ex. en skärm som
        inte längre är ansluten) centreras fönstret i stället —
        annars öppnas fönstret OSYNLIGT utanför skärmen
        ("blinkar till och är borta").
        """
        try:
            screen = QApplication.primaryScreen().availableGeometry()
        except Exception:
            self.resize(1280, 820)
            return

        w = min(
            int(self._settings.get("window_width", 1280)), screen.width()
        )
        h = min(
            int(self._settings.get("window_height", 820)), screen.height()
        )
        self.resize(w, h)

        x = int(self._settings.get("window_x", -1))
        y = int(self._settings.get("window_y", -1))

        placed = False
        if x >= 0 and y >= 0:
            # Fönstrets övre vänstra hörn måste ligga INOM minst en
            # ansluten skärm (med minst 80 px synlig marginal).
            try:
                screens = QApplication.screens()
            except Exception:
                screens = []
            for s in screens:
                try:
                    g = s.availableGeometry()
                except Exception:
                    continue
                if (
                    g.x() - 80 <= x < g.x() + g.width()
                    and g.y() - 80 <= y < g.y() + g.height()
                ):
                    self.move(x, y)
                    placed = True
                    break
            if not placed:
                # Sparad position ligger utanför alla skärmar →
                # centrera på primärskärmen och logga händelsen.
                self.move(
                    screen.x() + (screen.width() - w) // 2,
                    screen.y() + (screen.height() - h) // 2,
                )
                log.warning(
                    "GEOMETRI_RESET: sparad position (%s, %s) ligger "
                    "utanför alla skärmar → fönstret centrerat "
                    "(%s skärmar anslutna)",
                    x, y, len(screens),
                )
        else:
            self.move(
                screen.x() + (screen.width() - w) // 2,
                screen.y() + (screen.height() - h) // 2,
            )

        log.debug(
            "Fönstergeometri återställd: %sx%s @ (%s, %s), maximerat=%s",
            w, h, self.x(), self.y(),
            bool(self._settings.get("window_maximized", False)),
        )

        if self._settings.get("window_maximized", False):
            # VIKTIGT: setWindowState, ALDRIG showMaximized här —
            # showMaximized() gör fönstret SYNLIGT redan i __init__
            # och får annars autostartade (gömda) starter att
            # "blinka till". Tillståndet appliceras först när
            # fönstret faktiskt visas.
            self.setWindowState(
                self.windowState() | Qt.WindowState.WindowMaximized
            )

    def _save_geometry(self) -> None:
        """Sparar storlek/position till settings (maximerat bevaras)."""
        try:
            mx = self.isMaximized()
            self._settings.update({
                "window_maximized": mx,
                "window_width": (
                    self.width() if not mx
                    else self._settings.get("window_width", 1280)
                ),
                "window_height": (
                    self.height() if not mx
                    else self._settings.get("window_height", 820)
                ),
                "window_x": (
                    self.x() if not mx
                    else self._settings.get("window_x", -1)
                ),
                "window_y": (
                    self.y() if not mx
                    else self._settings.get("window_y", -1)
                ),
            })
        except Exception as exc:
            log.warning("_save_geometry: %s", exc)

    def _schedule_geometry_save(self) -> None:
        """
        Debounced geometri-sparning.

        resize/move-event startar om timern; JSON skrivs först efter
        500 ms stillastående — inte per pixel.
        """
        if hasattr(self, "_geometry_timer"):
            self._geometry_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_geometry_save()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._schedule_geometry_save()

    # ══════════════════════════════════════════════════════════════════
    #  OM-DIALOG
    # ══════════════════════════════════════════════════════════════════

    def _show_about(self) -> None:
        """
        Om/Hjälp-sida med donationsinfo (Swish/PayPal/BMC).

        Fungerar ALLTID: om den rika dialogen mot förmodan skulle
        falla finns en enkel fallback-ruta (MUST: knappen får aldrig
        vara död).
        """
        try:
            self._show_about_dialog()
        except Exception as exc:
            log.warning("Om-dialog föll tillbaka till enkel ruta: %s", exc)
            QMessageBox.about(
                self,
                f"Om {APP_NAME}",
                f"{APP_NAME} v{APP_VERSION}\n"
                "Modern lokal fakturahantering för\n"
                "Windows, Linux och macOS.\n\n"
                f"💙 Swish: {DONATE_SWISH}\n"
                f"🅿️ PayPal: {DONATE_PAYPAL}\n"
                f"☕ Ko-fi: {DONATE_BMC}\n\n"
                f"© {COPYRIGHT_YEAR} Rickard Längkvist",
            )

    def _copy_swish(self) -> None:
        """Kopierar Swish-numret till urklipp + bekräftar i statusraden."""
        try:
            QApplication.clipboard().setText(DONATE_SWISH.replace(" ", ""))
            self.set_status(f"💙  Swish-nummer kopierat: {DONATE_SWISH}", 6000)
        except Exception as exc:
            log.warning("Swish-kopiering: %s", exc)

    def _open_about_file(self) -> None:
        """Öppnar about.md — komplett info om programmet + donationer."""
        _open_path(PROJECT_DIR / "about.md")

    def _show_about_dialog(self) -> None:
        """Rik Om-dialog: info, snabbknappar, funktioner, donationer."""
        autostart_status = (
            "✅ aktiv" if self._read_autostart_status() else "❌ inaktiv"
        )
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("about.title", app=APP_NAME))
        if self._custom_icon is not None:
            dlg.setWindowIcon(self._custom_icon)
        dlg.setMinimumSize(640, 580)
        dlg.setSizeGripEnabled(True)

        root = QVBoxLayout(dlg)
        root.setSpacing(12)
        root.setContentsMargins(18, 16, 18, 14)

        icon = self.windowIcon()
        if not icon.isNull():
            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon.pixmap(96, 96))
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setStyleSheet("background:transparent;")
            root.addWidget(icon_lbl)

        text = QTextEdit(dlg)
        text.setReadOnly(True)
        text.setOpenExternalLinks(False)
        text.setHtml(tr(
            "about.body_html",
            app=APP_NAME, version=APP_VERSION, year=COPYRIGHT_YEAR,
            swish=DONATE_SWISH, paypal=DONATE_PAYPAL, kofi=DONATE_BMC,
            platform=CURRENT_PLATFORM, python=sys.version.split()[0],
            autostart=autostart_status,
        ))
        root.addWidget(text, stretch=1)

        # ── Donations- och infoknappar ────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_swish = QPushButton("💙  Swish")
        btn_swish.setToolTip(f"Kopierar Swish-numret {DONATE_SWISH}")
        btn_swish.clicked.connect(self._copy_swish)

        btn_paypal = QPushButton("🅿️  PayPal")
        btn_paypal.setToolTip(tr("donate.paypal_tip"))
        btn_paypal.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DONATE_PAYPAL))
        )

        btn_bmc = QPushButton("☕  Ko-fi")
        btn_bmc.setToolTip(tr("donate.kofi_tip"))
        btn_bmc.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DONATE_BMC))
        )

        btn_about = QPushButton("📖  Om programmet")
        btn_about.setToolTip(tr("donate.about_tip"))
        btn_about.clicked.connect(self._open_about_file)

        btn_donate = QPushButton(tr("about.donate_btn"))
        btn_donate.setObjectName("DonateButton")
        btn_donate.setToolTip(tr("toolbar.donate_tip"))
        btn_donate.clicked.connect(lambda: open_donate_dialog(dlg))

        btn_close = QPushButton(tr("about.close"))
        btn_close.clicked.connect(dlg.accept)

        for b in (btn_donate, btn_swish, btn_paypal, btn_bmc, btn_about, btn_close):
            b.setMinimumHeight(38)
            b.setFont(_font(11, bold=True))
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_row.addWidget(b)
        root.addLayout(btn_row)

        dlg.exec()


# ═════════════════════════════════════════════════════════════════════
#  STANDALONE (utvecklingsläge: python ui/main_window.py)
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _ensure_paths()
    try:
        from app import FakturaApp  # type: ignore

        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        try:
            from ui.letter_jump import LetterJumpApplication
            _App = LetterJumpApplication
        except ImportError:
            _App = QApplication
        qt = QApplication.instance() or _App(sys.argv)
        qt.setApplicationName(APP_NAME)
        qt.setApplicationVersion(APP_VERSION)
        qt.setOrganizationName("Rickard Längkvist")
        qt.setStyle("Fusion")
        qt.setQuitOnLastWindowClosed(False)

        fa = FakturaApp()
        theme = resolve_theme(fa.settings.get("theme", "dark"))
        apply_app_palette(theme)
        qt.setStyleSheet(build_stylesheet(theme))

        w = MainWindow(app=fa)
        if fa.settings.get("startup", False):
            w.set_autostart(True)

        w.show()
        log.info("Standalone-läge: MainWindow startad")
        sys.exit(qt.exec())
    except ImportError as exc:
        print(f"Kan inte ladda FakturaApp: {exc}")
        print("Kör programmet via main.py istället.")
        sys.exit(1)
