# -*- coding: utf-8 -*-
"""
icons — krisp vektorbaserad ikonmotor, QSS-indikatorer och ren textritning.

Skapar enhetliga SVG-ikoner i 24×24-koordinater (Lucide-inspirerad geometri)
med dynamisk temafärgning, temporära SVG-indikatorer för Qt-stilark
(bock i kryssrutor, nedåtpil i kombinationsrutor) samt CleanIconProxyStyle
som döljer råa emoji-prefix vid målning utan att ändra .text()-strängar.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import re
import tempfile
import weakref
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QGuiApplication,
    QIcon,
    QIconEngine,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QLineEdit, QProxyStyle, QStyle

#: Dekorativa emoji-/symbolprefix (och efterled) som döljs visuellt.
#: Bevarar ★, ⚠, ⛔, ☑, ✓, ✔, ✖, pilar och matematiska tecken orörda.
_ICON_CHAR_CLASS = (
    r"\U0001F100-\U0001F1FF"
    r"\U0001F300-\U0001FAFF"
    r"\u231A-\u23FF"
    r"\u2600-\u2604\u260E\u2614-\u2615\u267B\u2699\u26A1"
    r"\u2702-\u270F\u2728\u274C\u274E\u2757\u2764\u2795-\u2797\u27B0"
    r"\u2B00-\u2BFF"
    r"\u2139\u21A9\u23F0-\u23FA\u25B6\u23F8\u23F9"
)
_DECORATIVE_ICON_RE = re.compile(
    rf"^(?:[{_ICON_CHAR_CLASS}]|\uFE0F|\u200D)+\s*"
)
_TRAILING_ICON_RE = re.compile(
    rf"\s*(?:[{_ICON_CHAR_CLASS}]|\uFE0F|\u200D)+$"
)
_BARE_AMP_RE = re.compile(r"(?<= )&(?= )")


def strip_visual_prefix(text: str) -> str:
    """Tar bort dekorativa emoji i början/slutet för ren visning med QIcon."""
    if not text:
        return text
    cleaned = _DECORATIVE_ICON_RE.sub("", text)
    if cleaned != text:
        cleaned = cleaned.lstrip()
    cleaned_end = _TRAILING_ICON_RE.sub("", cleaned)
    if cleaned_end != cleaned:
        cleaned = cleaned_end.rstrip()
    return cleaned


def _clean_mnemonic_text(text: str) -> str:
    """Ren visningstext för knappar/flikar/menyer: döljer emoji och ' & '-understrykning."""
    if not text:
        return text
    cleaned = strip_visual_prefix(text)
    if " & " in cleaned:
        cleaned = _BARE_AMP_RE.sub("&&", cleaned)
    return cleaned


# ═════════════════════════════════════════════════════════════════════
#  VEKTOR-SVG-IKONER (24×24 viewBox)
# ═════════════════════════════════════════════════════════════════════

_SVG_PATHS: dict[str, str] = {
    "dashboard": (
        '<rect x="3" y="3" width="7" height="9" rx="1.5"/>'
        '<rect x="14" y="3" width="7" height="5" rx="1.5"/>'
        '<rect x="14" y="12" width="7" height="9" rx="1.5"/>'
        '<rect x="3" y="16" width="7" height="5" rx="1.5"/>'
    ),
    "invoices": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="8" y1="13" x2="16" y2="13"/>'
        '<line x1="8" y1="17" x2="13" y2="17"/>'
    ),
    "history": (
        '<rect x="3" y="4" width="18" height="4" rx="1"/>'
        '<path d="M5 8v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8"/>'
        '<line x1="10" y1="12" x2="14" y2="12"/>'
    ),
    "suppliers": (
        '<path d="M3 21h18"/>'
        '<path d="M5 21V7l8-4v18"/>'
        '<path d="M19 21V11l-6-4"/>'
        '<line x1="9" y1="9" x2="9" y2="9.01"/>'
        '<line x1="9" y1="13" x2="9" y2="13.01"/>'
        '<line x1="9" y1="17" x2="9" y2="17.01"/>'
    ),
    "payments": (
        '<rect x="2" y="5" width="20" height="14" rx="2"/>'
        '<line x1="2" y1="10" x2="22" y2="10"/>'
        '<line x1="6" y1="15" x2="10" y2="15"/>'
    ),
    "import": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/>'
        '<line x1="12" y1="15" x2="12" y2="3"/>'
    ),
    "reports": (
        '<line x1="18" y1="20" x2="18" y2="10"/>'
        '<line x1="12" y1="20" x2="12" y2="4"/>'
        '<line x1="6" y1="20" x2="6" y2="14"/>'
    ),
    "log": (
        '<polyline points="4 17 10 11 4 5"/>'
        '<line x1="12" y1="19" x2="20" y2="19"/>'
    ),
    "settings": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06'
        'a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09'
        'a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06'
        'a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09'
        'a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06'
        'a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09'
        'a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06'
        'a1.65 1.65 0 0 0-.33 1.82V9c.26.6.78 1 1.51 1H21a2 2 0 0 1 0 4h-.09'
        'a1.65 1.65 0 0 0-1.51 1z"/>'
    ),
    "add": (
        '<line x1="12" y1="5" x2="12" y2="19"/>'
        '<line x1="5" y1="12" x2="19" y2="12"/>'
    ),
    "edit": (
        '<path d="M12 20h9"/>'
        '<path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4Z"/>'
    ),
    "duplicate": (
        '<rect x="9" y="9" width="13" height="13" rx="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    "delete": (
        '<polyline points="3 6 5 6 21 6"/>'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
        '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
        '<line x1="10" y1="11" x2="10" y2="17"/>'
        '<line x1="14" y1="11" x2="14" y2="17"/>'
    ),
    "check": (
        '<circle cx="12" cy="12" r="9"/>'
        '<polyline points="8.5 12.5 11 15 15.5 9.5"/>'
    ),
    "refresh": (
        '<polyline points="23 4 23 10 17 10"/>'
        '<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>'
    ),
    "undo": (
        '<polyline points="9 14 4 9 9 4"/>'
        '<path d="M20 20v-7a4 4 0 0 0-4-4H4"/>'
    ),
    "export": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<polyline points="9 15 12 12 15 15"/>'
        '<line x1="12" y1="12" x2="12" y2="19"/>'
    ),
    "folder": (
        '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'
    ),
    "search": (
        '<circle cx="11" cy="11" r="7"/>'
        '<line x1="21" y1="21" x2="16.65" y2="16.65"/>'
    ),
    "combine": (
        '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
        '<polyline points="2 12 12 17 22 12"/>'
        '<polyline points="2 17 12 22 22 17"/>'
    ),
    "link": (
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
    ),
    "zap": (
        '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'
    ),
    "calendar": (
        '<rect x="3" y="4" width="18" height="18" rx="2"/>'
        '<line x1="16" y1="2" x2="16" y2="6"/>'
        '<line x1="8" y1="2" x2="8" y2="6"/>'
        '<line x1="3" y1="10" x2="21" y2="10"/>'
    ),
    "clock": (
        '<circle cx="12" cy="12" r="9"/>'
        '<polyline points="12 7 12 12 15 14"/>'
    ),
    "alert": (
        '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>'
        '<line x1="12" y1="9" x2="12" y2="13"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/>'
    ),
    "dark": (
        '<path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/>'
    ),
    "light": (
        '<circle cx="12" cy="12" r="4"/>'
        '<line x1="12" y1="2" x2="12" y2="4"/>'
        '<line x1="12" y1="20" x2="12" y2="22"/>'
        '<line x1="4.93" y1="4.93" x2="6.34" y2="6.34"/>'
        '<line x1="17.66" y1="17.66" x2="19.07" y2="19.07"/>'
        '<line x1="2" y1="12" x2="4" y2="12"/>'
        '<line x1="20" y1="12" x2="22" y2="12"/>'
        '<line x1="4.93" y1="19.07" x2="6.34" y2="17.66"/>'
        '<line x1="17.66" y1="6.34" x2="19.07" y2="4.93"/>'
    ),
    "auto": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor" stroke="none"/>'
    ),
    "system": (
        '<rect x="2" y="3" width="20" height="14" rx="2"/>'
        '<line x1="8" y1="21" x2="16" y2="21"/>'
        '<line x1="12" y1="17" x2="12" y2="21"/>'
    ),
    "language": (
        '<circle cx="12" cy="12" r="9"/>'
        '<line x1="3" y1="12" x2="21" y2="12"/>'
        '<path d="M12 3a14 14 0 0 1 0 18"/>'
        '<path d="M12 3a14 14 0 0 0 0 18"/>'
    ),
    "donate": (
        '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>'
    ),
    "backup": (
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
        '<polyline points="17 21 17 13 7 13 7 21"/>'
        '<polyline points="7 3 7 8 15 8"/>'
    ),
    "update": (
        '<polyline points="8 17 12 21 16 17"/>'
        '<line x1="12" y1="12" x2="12" y2="21"/>'
        '<path d="M20.88 18.09A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.29"/>'
    ),
    "diagnostics": (
        '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>'
    ),
    "pause": (
        '<rect x="6" y="4" width="4" height="16" rx="1"/>'
        '<rect x="14" y="4" width="4" height="16" rx="1"/>'
    ),
    "play": (
        '<polygon points="6 4 20 12 6 20 6 4"/>'
    ),
    "mark": (
        '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>'
    ),
    "learn": (
        '<path d="M22 10v6"/>'
        '<path d="M2 10l10-5 10 5-10 5z"/>'
        '<path d="M6 12v5c3 3 9 3 12 0v-5"/>'
    ),
    "puzzle": (
        '<path d="M19.439 7.85c-.049.322.059.648.289.878l1.568 1.568c.47.47.706 1.087.706 1.704s-.235 1.233-.706 1.704l-1.611 1.611a.98.98 0 0 1-.837.276c-.47-.07-.802-.48-.968-.925a2.501 2.501 0 1 0-3.214 3.214c.446.166.855.497.925.968a.979.979 0 0 1-.276.837l-1.61 1.61a2.404 2.404 0 0 1-1.705.707 2.402 2.402 0 0 1-1.704-.706l-1.568-1.568a1.026 1.026 0 0 0-.877-.29c-.493.074-.84.504-1.02.968a2.5 2.5 0 1 1-3.237-3.237c.464-.18.894-.527.967-1.02a1.026 1.026 0 0 0-.289-.877l-1.568-1.568A2.402 2.402 0 0 1 1.998 12c0-.617.236-1.234.706-1.704L4.23 8.77c.24-.24.581-.353.917-.303.515.077.877.528 1.073 1.01a2.5 2.5 0 1 0 3.259-3.259c-.482-.196-.933-.558-1.01-1.073-.05-.336.062-.676.303-.917l1.525-1.525A2.402 2.402 0 0 1 12 1.998c.617 0 1.234.236 1.704.706l1.568 1.568c.23.23.556.338.877.29.493-.074.84-.504 1.02-.968a2.5 2.5 0 1 1 3.237 3.237c-.464.18-.894.527-.967 1.02z"/>'
    ),
    "eye": (
        '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    "minimize": (
        '<polyline points="4 14 10 14 10 20"/>'
        '<polyline points="20 10 14 10 14 4"/>'
        '<line x1="14" y1="10" x2="21" y2="3"/>'
        '<line x1="3" y1="21" x2="10" y2="14"/>'
    ),
    "quit": (
        '<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/>'
        '<line x1="12" y1="2" x2="12" y2="12"/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="9"/>'
        '<line x1="12" y1="16" x2="12" y2="12"/>'
        '<line x1="12" y1="8" x2="12.01" y2="8"/>'
    ),
    "keyboard": (
        '<rect x="2" y="5" width="20" height="14" rx="2"/>'
        '<line x1="6" y1="9" x2="6.01" y2="9"/>'
        '<line x1="10" y1="9" x2="10.01" y2="9"/>'
        '<line x1="14" y1="9" x2="14.01" y2="9"/>'
        '<line x1="18" y1="9" x2="18.01" y2="9"/>'
        '<line x1="8" y1="14" x2="16" y2="14"/>'
    ),
    "clear": (
        '<line x1="18" y1="6" x2="6" y2="18"/>'
        '<line x1="6" y1="6" x2="18" y2="18"/>'
    ),
    "list": (
        '<line x1="8" y1="6" x2="21" y2="6"/>'
        '<line x1="8" y1="12" x2="21" y2="12"/>'
        '<line x1="8" y1="18" x2="21" y2="18"/>'
        '<line x1="3" y1="6" x2="3.01" y2="6"/>'
        '<line x1="3" y1="12" x2="3.01" y2="12"/>'
        '<line x1="3" y1="18" x2="3.01" y2="18"/>'
    ),
    "clean": (
        '<path d="M20 20H7L3 16c-.8-.8-.8-2 0-2.8l9.9-9.9c.8-.8 2-.8 2.8 0l5.4 5.4c.8.8.8 2 0 2.8L12.6 20"/>'
        '<path d="M6 11l7 7"/>'
    ),
    "rocket": (
        '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/>'
        '<path d="M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>'
    ),
    "arrow_right": (
        '<line x1="5" y1="12" x2="19" y2="12"/>'
        '<polyline points="12 5 19 12 12 19"/>'
    ),
    "chevron_left": (
        '<polyline points="15 18 9 12 15 6"/>'
    ),
    "chevron_right": (
        '<polyline points="9 18 15 12 9 6"/>'
    ),
    "external": (
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
        '<polyline points="15 3 21 3 21 9"/>'
        '<line x1="10" y1="14" x2="21" y2="3"/>'
    ),
    # ── Utökat set v2: säkerhet, bank, statistik, åtgärder ──────────
    "shield_check": (
        '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
        '<polyline points="9 11.5 11.5 14 15.5 9.5"/>'
    ),
    "bank": (
        '<line x1="3" y1="21" x2="21" y2="21"/>'
        '<line x1="5" y1="21" x2="5" y2="10"/>'
        '<line x1="9" y1="21" x2="9" y2="10"/>'
        '<line x1="15" y1="21" x2="15" y2="10"/>'
        '<line x1="19" y1="21" x2="19" y2="10"/>'
        '<polygon points="12 3 3 8 21 8 12 3"/>'
    ),
    "banknote": (
        '<rect x="2" y="6" width="20" height="12" rx="2"/>'
        '<circle cx="12" cy="12" r="2.5"/>'
        '<path d="M6 12h.01M18 12h.01"/>'
    ),
    "qr": (
        '<rect x="3" y="3" width="7" height="7" rx="1"/>'
        '<rect x="14" y="3" width="7" height="7" rx="1"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1"/>'
        '<line x1="14" y1="14" x2="14.01" y2="14"/>'
        '<line x1="17" y1="14" x2="17.01" y2="14"/>'
        '<line x1="14" y1="17" x2="14.01" y2="17"/>'
        '<line x1="17" y1="17" x2="17.01" y2="17"/>'
        '<path d="M21 14v4a3 3 0 0 1-3 3h-4"/>'
    ),
    "scan": (
        '<path d="M3 7V5a2 2 0 0 1 2-2h2"/>'
        '<path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
        '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
        '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
        '<line x1="7" y1="12" x2="17" y2="12"/>'
    ),
    "scissors": (
        '<circle cx="6" cy="6" r="3"/>'
        '<circle cx="6" cy="18" r="3"/>'
        '<line x1="20" y1="4" x2="8.12" y2="15.88"/>'
        '<line x1="14.47" y1="14.48" x2="20" y2="20"/>'
        '<line x1="8.12" y1="8.12" x2="12" y2="12"/>'
    ),
    "bell": (
        '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>'
        '<path d="M13.73 21a2 2 0 0 1-3.46 0"/>'
    ),
    "eye_off": (
        '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/>'
        '<path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 11 7 11 7'
        'a13.16 13.16 0 0 1-1.67 2.68"/>'
        '<path d="M6.61 6.61A13.526 13.526 0 0 0 1 12s4 7 11 7'
        'a10.9 10.9 0 0 0 5.03-1.12"/>'
        '<line x1="2" y1="2" x2="22" y2="22"/>'
    ),
    "filter": (
        '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>'
    ),
    "sliders": (
        '<line x1="4" y1="21" x2="4" y2="14"/>'
        '<line x1="4" y1="10" x2="4" y2="3"/>'
        '<line x1="12" y1="21" x2="12" y2="12"/>'
        '<line x1="12" y1="8" x2="12" y2="3"/>'
        '<line x1="20" y1="21" x2="20" y2="16"/>'
        '<line x1="20" y1="12" x2="20" y2="3"/>'
        '<line x1="1" y1="14" x2="7" y2="14"/>'
        '<line x1="9" y1="8" x2="15" y2="8"/>'
        '<line x1="17" y1="16" x2="23" y2="16"/>'
    ),
    "printer": (
        '<polyline points="6 9 6 2 18 2 18 9"/>'
        '<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16'
        'a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>'
        '<rect x="6" y="14" width="12" height="8"/>'
    ),
    "share": (
        '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>'
        '<polyline points="16 6 12 2 8 6"/>'
        '<line x1="12" y1="2" x2="12" y2="15"/>'
    ),
    "send": (
        '<line x1="22" y1="2" x2="11" y2="13"/>'
        '<polygon points="22 2 15 22 11 13 2 9 22 2"/>'
    ),
    "mail": (
        '<rect x="2" y="4" width="20" height="16" rx="2"/>'
        '<path d="m22 7-10 6L2 7"/>'
    ),
    "users": (
        '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M23 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "gauge": (
        '<path d="m12 14 4-4"/>'
        '<path d="M3.34 19a10 10 0 1 1 17.32 0"/>'
    ),
    "trending_up": (
        '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>'
        '<polyline points="16 7 22 7 22 13"/>'
    ),
    "trending_down": (
        '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/>'
        '<polyline points="16 17 22 17 22 11"/>'
    ),
    "pie": (
        '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/>'
        '<path d="M22 12A10 10 0 0 0 12 2v10z"/>'
    ),
    "hash": (
        '<line x1="4" y1="9" x2="20" y2="9"/>'
        '<line x1="4" y1="15" x2="20" y2="15"/>'
        '<line x1="10" y1="3" x2="8" y2="21"/>'
        '<line x1="16" y1="3" x2="14" y2="21"/>'
    ),
    "percent": (
        '<line x1="19" y1="5" x2="5" y2="19"/>'
        '<circle cx="6.5" cy="6.5" r="2.5"/>'
        '<circle cx="17.5" cy="17.5" r="2.5"/>'
    ),
    "lock": (
        '<rect x="3" y="11" width="18" height="11" rx="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "cpu": (
        '<rect x="4" y="4" width="16" height="16" rx="2"/>'
        '<rect x="9" y="9" width="6" height="6"/>'
        '<line x1="9" y1="1" x2="9" y2="4"/>'
        '<line x1="15" y1="1" x2="15" y2="4"/>'
        '<line x1="9" y1="20" x2="9" y2="23"/>'
        '<line x1="15" y1="20" x2="15" y2="23"/>'
        '<line x1="20" y1="9" x2="23" y2="9"/>'
        '<line x1="20" y1="14" x2="23" y2="14"/>'
        '<line x1="1" y1="9" x2="4" y2="9"/>'
        '<line x1="1" y1="14" x2="4" y2="14"/>'
    ),
    "package": (
        '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4'
        'A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4'
        'A2 2 0 0 0 21 16Z"/>'
        '<path d="m3.3 7 8.7 5 8.7-5"/>'
        '<path d="M12 22V12"/>'
    ),
    "calendar_check": (
        '<rect x="3" y="4" width="18" height="18" rx="2"/>'
        '<line x1="16" y1="2" x2="16" y2="6"/>'
        '<line x1="8" y1="2" x2="8" y2="6"/>'
        '<line x1="3" y1="10" x2="21" y2="10"/>'
        '<polyline points="9 15.5 11.5 18 15.5 13.5"/>'
    ),
    "calendar_x": (
        '<rect x="3" y="4" width="18" height="18" rx="2"/>'
        '<line x1="16" y1="2" x2="16" y2="6"/>'
        '<line x1="8" y1="2" x2="8" y2="6"/>'
        '<line x1="3" y1="10" x2="21" y2="10"/>'
        '<line x1="10" y1="14" x2="14" y2="18"/>'
        '<line x1="14" y1="14" x2="10" y2="18"/>'
    ),
    "x_circle": (
        '<circle cx="12" cy="12" r="9"/>'
        '<line x1="9" y1="9" x2="15" y2="15"/>'
        '<line x1="15" y1="9" x2="9" y2="15"/>'
    ),
}

_MAX_ICON_CACHE = 256
_MAX_PIXMAP_CACHE = 384
_ICON_CACHE: "OrderedDict[tuple[str, str, str, int], QIcon]" = OrderedDict()
_PIXMAP_CACHE: "OrderedDict[tuple[str, str, int, int], QPixmap]" = OrderedDict()


def clear_icon_caches() -> None:
    """Frigör cachade ikon-pixmaps och SVG-ikoner för lägre minnesanvändning."""
    _PIXMAP_CACHE.clear()
    _ICON_CACHE.clear()


def _effective_dpr(dpr: Any = None) -> float:
    """Returnerar effektiv enhetsskalning (>= 1.0) för skarp HiDPI-rendering."""
    if dpr is not None and not isinstance(dpr, (int, float)):
        try:
            scr = dpr.screen()
            if scr is not None:
                return max(1.0, float(scr.devicePixelRatio()))
        except Exception:
            pass
        dpr = None
    if dpr is not None:
        try:
            return max(1.0, float(dpr))
        except (TypeError, ValueError):
            return 1.0
    try:
        inst = QGuiApplication.instance()
        if inst is not None:
            scr = inst.primaryScreen()
            if scr is not None:
                return max(1.0, float(scr.devicePixelRatio()))
    except Exception:
        pass
    return 1.0


def _svg_markup(name: str, color: str) -> str:
    body = _SVG_PATHS.get(name) or _SVG_PATHS["info"]
    body = body.replace("currentColor", color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1 -1 26 26" '
        f'shape-rendering="geometricPrecision" '
        f'fill="none" stroke="{color}" stroke-width="2.0" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def _render_svg_pixmap(
    name: str,
    color: str,
    width: int,
    height: int,
    dpr: float = 1.0,
    opacity: float = 1.0,
) -> QPixmap:
    scale = max(1.0, float(dpr))
    pw = max(1, int(round(max(1, int(width)) * scale)))
    ph = max(1, int(round(max(1, int(height)) * scale)))
    pix = QPixmap(pw, ph)
    pix.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(_svg_markup(name, color).encode("utf-8")))
    if renderer.isValid():
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if opacity < 1.0:
            painter.setOpacity(max(0.0, float(opacity)))
        renderer.render(painter, QRectF(0, 0, pw, ph))
        painter.end()
    if scale > 1.0:
        pix.setDevicePixelRatio(scale)
    return pix


class _VectorIconEngine(QIconEngine):
    """Äkta vektor-QIconEngine som ritar SVG skarpt vid alla DPR-skalningar."""

    def __init__(
        self,
        name: str,
        color: str,
        disabled_color: str = "",
        base_size: int = 16,
    ) -> None:
        super().__init__()
        self._name = name
        self._color = color
        self._disabled_color = disabled_color
        self._base_size = max(1, int(base_size))

    def _color_for(self, mode: QIcon.Mode) -> str:
        if mode == QIcon.Mode.Disabled and self._disabled_color:
            return self._disabled_color
        return self._color

    def paint(  # noqa: N802
        self,
        painter: QPainter,
        rect: QRect,
        mode: QIcon.Mode,
        state: QIcon.State,
    ) -> None:
        if rect.isEmpty():
            return
        col = self._color_for(mode)
        renderer = QSvgRenderer(
            QByteArray(_svg_markup(self._name, col).encode("utf-8"))
        )
        if not renderer.isValid():
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if mode == QIcon.Mode.Disabled and not self._disabled_color:
            painter.setOpacity(0.38)
        side = float(min(rect.width(), rect.height()))
        target = QRectF(
            rect.x() + (rect.width() - side) / 2.0,
            rect.y() + (rect.height() - side) / 2.0,
            side,
            side,
        )
        renderer.render(painter, target)
        painter.restore()

    def pixmap(  # noqa: N802
        self, size: QSize, mode: QIcon.Mode, state: QIcon.State
    ) -> QPixmap:
        return self.scaledPixmap(size, mode, state, _effective_dpr())

    def scaledPixmap(  # noqa: N802
        self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float
    ) -> QPixmap:
        w = max(1, int(size.width()) or self._base_size)
        h = max(1, int(size.height()) or self._base_size)
        op = 0.38 if (mode == QIcon.Mode.Disabled and not self._disabled_color) else 1.0
        return _render_svg_pixmap(
            self._name,
            self._color_for(mode),
            w,
            h,
            dpr=max(1.0, float(scale)),
            opacity=op,
        )

    def availableSizes(  # noqa: N802
        self, mode: QIcon.Mode = QIcon.Mode.Normal, state: QIcon.State = QIcon.State.Off
    ) -> list[QSize]:
        return [QSize(self._base_size, self._base_size)]

    def clone(self) -> "_VectorIconEngine":
        return _VectorIconEngine(
            self._name,
            self._color,
            self._disabled_color,
            self._base_size,
        )


def icon_pixmap(
    name: str,
    color: str = "#1c2128",
    size: int = 16,
    dpr: float | None = None,
) -> QPixmap:
    """Renderar en vektorikon som skarp DPR-medveten QPixmap i exakt storlek/färg."""
    eff_dpr = _effective_dpr(dpr)
    dpr_key = int(round(eff_dpr * 100))
    key = (name, color.lower(), int(size), dpr_key)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None and not cached.isNull():
        _PIXMAP_CACHE.move_to_end(key)
        return cached
    pix = _render_svg_pixmap(name, color, int(size), int(size), dpr=eff_dpr)
    _PIXMAP_CACHE[key] = pix
    while len(_PIXMAP_CACHE) > _MAX_PIXMAP_CACHE:
        _PIXMAP_CACHE.popitem(last=False)
    return pix


def vector_icon(
    name: str,
    color: str = "#1c2128",
    size: int = 16,
    disabled_color: str | None = None,
) -> QIcon:
    """Returnerar en vektor-QIcon som skalas knivskarpt på 100%–300% skärmar."""
    dis = (disabled_color or "").lower()
    key = (name, color.lower(), dis, int(size))
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        _ICON_CACHE.move_to_end(key)
        return cached
    ic = QIcon(_VectorIconEngine(name, color, disabled_color or "", int(size)))
    _ICON_CACHE[key] = ic
    while len(_ICON_CACHE) > _MAX_ICON_CACHE:
        _ICON_CACHE.popitem(last=False)
    return ic


def _asset_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "invoicebundle_ui_assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def qss_indicator_urls(arrow_color: str, check_color: str = "#ffffff") -> dict[str, str]:
    """Skriver minimala SVG-filer för pil- och kryssruteindikatorer i QSS."""
    out = _asset_dir()
    assets = {
        "chevron_up": (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
            f'shape-rendering="geometricPrecision" '
            f'fill="none" stroke="{arrow_color}" stroke-width="2.1" '
            f'stroke-linecap="round" stroke-linejoin="round">'
            f'<polyline points="4 10 8 6 12 10"/></svg>'
        ),
        "chevron_down": (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
            f'shape-rendering="geometricPrecision" '
            f'fill="none" stroke="{arrow_color}" stroke-width="2.1" '
            f'stroke-linecap="round" stroke-linejoin="round">'
            f'<polyline points="4 6 8 10 12 6"/></svg>'
        ),
        "chevron_right": (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
            f'shape-rendering="geometricPrecision" '
            f'fill="none" stroke="{arrow_color}" stroke-width="2.1" '
            f'stroke-linecap="round" stroke-linejoin="round">'
            f'<polyline points="6 4 10 8 6 12"/></svg>'
        ),
        "check": (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
            f'shape-rendering="geometricPrecision" '
            f'fill="none" stroke="{check_color}" stroke-width="2.4" '
            f'stroke-linecap="round" stroke-linejoin="round">'
            f'<polyline points="3.5 8.5 6.5 11.5 12.5 4.5"/></svg>'
        ),
    }
    urls: dict[str, str] = {}
    for key, svg in assets.items():
        digest = hashlib.sha1(svg.encode("utf-8")).hexdigest()[:8]
        fpath = out / f"{key}_{digest}.svg"
        if not fpath.is_file():
            try:
                fpath.write_text(svg, encoding="utf-8")
            except Exception:
                continue
        urls[key] = fpath.as_posix()
    return urls


_BOUND_ICONS: "weakref.WeakKeyDictionary[Any, tuple[str, str, int]]" = (
    weakref.WeakKeyDictionary()
)


def _resolve_icon_color(theme: dict | None, role: str) -> str:
    if not theme:
        if role == "on_accent":
            return "#ffffff"
        return "#e2eaf4"
    if role == "on_accent":
        return "#ffffff"
    if role == "on_gold":
        bg = str(theme.get("bg", "#0c1218"))
        # Dark gold chip uses dark ink; light gold chip uses white
        try:
            r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            return "#1c1400" if (0.299 * r + 0.587 * g + 0.114 * b) < 128 else "#ffffff"
        except Exception:
            return "#ffffff"
    return str(theme.get(role, theme.get("text_strong", "#e2eaf4")))


def _resolve_disabled_color(theme: dict | None) -> str:
    if theme:
        return str(theme.get("text_disabled", theme.get("text_muted", "#6b7280")))
    return "#7d8590"


def bind_icon(
    target: Any,
    icon_name: str,
    role: str = "text_strong",
    size: int = 16,
    theme: dict | None = None,
) -> Any:
    """Sätter vektorikon på en knapp/action och minns den för temaväxling."""
    if target is None or not icon_name:
        return target
    try:
        _BOUND_ICONS[target] = (icon_name, role, int(size))
    except TypeError:
        pass
    color = _resolve_icon_color(theme, role)
    dis_color = _resolve_disabled_color(theme)
    try:
        target.setIcon(
            vector_icon(icon_name, color=color, size=size, disabled_color=dis_color)
        )
        if hasattr(target, "setIconSize"):
            target.setIconSize(QSize(int(size), int(size)))
    except Exception:
        pass
    return target


def _is_qt_alive(obj: Any) -> bool:
    try:
        import shiboken6

        return bool(shiboken6.isValid(obj))
    except Exception:
        return True


def refresh_bound_icons(theme: dict | None) -> None:
    """Uppdaterar färgen på alla registrerade vektorikoner vid temabyte."""
    dis_color = _resolve_disabled_color(theme)
    for target, spec in list(_BOUND_ICONS.items()):
        if not _is_qt_alive(target):
            _BOUND_ICONS.pop(target, None)
            continue
        icon_name, role, size = spec
        color = _resolve_icon_color(theme, role)
        try:
            target.setIcon(
                vector_icon(icon_name, color=color, size=size, disabled_color=dis_color)
            )
        except RuntimeError:
            # C++-objekt borttaget
            _BOUND_ICONS.pop(target, None)
        except Exception:
            pass


def attach_search_icon(
    line_edit: QLineEdit | None,
    size: int = 14,
    theme: dict | None = None,
) -> QLineEdit | None:
    """Lägger till vektor-sökikon i QLineEdit och rensar emoji ur platshållartexten."""
    if line_edit is None:
        return None
    try:
        ph = line_edit.placeholderText()
        if ph:
            clean_ph = strip_visual_prefix(ph)
            if clean_ph != ph:
                line_edit.setPlaceholderText(clean_ph)
    except Exception:
        pass
    act = getattr(line_edit, "_search_icon_action", None)
    if act is None:
        try:
            act = line_edit.addAction(
                vector_icon("search", color=_resolve_icon_color(theme, "text_muted"), size=size),
                QLineEdit.ActionPosition.LeadingPosition,
            )
            line_edit._search_icon_action = act  # type: ignore[attr-defined]
        except Exception:
            return line_edit
    if act is not None:
        bind_icon(act, "search", role="text_muted", size=size, theme=theme)
    return line_edit


_MNEMONIC_CONTROLS = frozenset({
    QStyle.ControlElement.CE_PushButton,
    QStyle.ControlElement.CE_PushButtonLabel,
    QStyle.ControlElement.CE_CheckBox,
    QStyle.ControlElement.CE_CheckBoxLabel,
    QStyle.ControlElement.CE_RadioButton,
    QStyle.ControlElement.CE_RadioButtonLabel,
    QStyle.ControlElement.CE_MenuItem,
    QStyle.ControlElement.CE_MenuBarItem,
    QStyle.ControlElement.CE_TabBarTab,
    QStyle.ControlElement.CE_TabBarTabLabel,
})

_MNEMONIC_CONTENTS = frozenset({
    QStyle.ContentsType.CT_PushButton,
    QStyle.ContentsType.CT_CheckBox,
    QStyle.ContentsType.CT_RadioButton,
    QStyle.ContentsType.CT_MenuItem,
    QStyle.ContentsType.CT_MenuBarItem,
    QStyle.ContentsType.CT_TabBarTab,
    QStyle.ContentsType.CT_ToolButton,
})


class CleanIconProxyStyle(QProxyStyle):
    """Döljer dekorativa emoji-prefix i kontroller utan att röra .text()."""

    def drawControl(  # noqa: N802
        self, element: QStyle.ControlElement, option: Any,
        painter: Any, widget: Any = None,
    ) -> None:
        if hasattr(option, "text") and option.text:
            cleaner = (
                _clean_mnemonic_text
                if element in _MNEMONIC_CONTROLS
                else strip_visual_prefix
            )
            option.text = cleaner(option.text)
        super().drawControl(element, option, painter, widget)

    def drawComplexControl(  # noqa: N802
        self, control: QStyle.ComplexControl, option: Any,
        painter: Any, widget: Any = None,
    ) -> None:
        if hasattr(option, "text") and option.text:
            cleaner = (
                _clean_mnemonic_text
                if control == QStyle.ComplexControl.CC_ToolButton
                else strip_visual_prefix
            )
            option.text = cleaner(option.text)
        super().drawComplexControl(control, option, painter, widget)

    def drawItemText(  # noqa: N802
        self, painter: Any, rect: QRect, flags: int, pal: Any,
        enabled: bool, text: str,
        textRole: Any = QPalette.ColorRole.NoRole,  # noqa: N803
    ) -> None:
        if text:
            if flags & int(Qt.TextFlag.TextShowMnemonic):
                text = _clean_mnemonic_text(text)
            else:
                text = strip_visual_prefix(text)
        super().drawItemText(painter, rect, flags, pal, enabled, text, textRole)

    def sizeFromContents(  # noqa: N802
        self, contents_type: QStyle.ContentsType, option: Any,
        size: QSize, widget: Any = None,
    ) -> QSize:
        if hasattr(option, "text") and option.text:
            cleaner = (
                _clean_mnemonic_text
                if contents_type in _MNEMONIC_CONTENTS
                else strip_visual_prefix
            )
            option.text = cleaner(option.text)
        return super().sizeFromContents(contents_type, option, size, widget)


_ACTIVE_CLEAN_STYLES: dict[int, CleanIconProxyStyle] = {}


def install_clean_style(app: QApplication | None = None) -> None:
    """Aktiverar CleanIconProxyStyle('Fusion') på QApplication säkert."""
    inst = app or QApplication.instance()
    if inst is None:
        return
    try:
        if isinstance(inst.style(), CleanIconProxyStyle):
            return
    except Exception:
        pass
    try:
        style = CleanIconProxyStyle("Fusion")
        _ACTIVE_CLEAN_STYLES[id(inst)] = style
        inst.setStyle(style)
    except Exception:
        pass
