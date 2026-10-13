# -*- coding: utf-8 -*-
"""
Donationsdialog för Fakturabunten.

Öppnas från:
  • Hjälp-menyn            → "💖 Stöd Fakturabunten…"
  • Verktygsfältet         → guldknappen 💖
  • Statusfältet           → "💖 Stöd" (alltid synlig)
  • Högerklick på flikraden / systemfältsmenyn / Om-dialogen
  • Inställningsfliken     → donationskortet

Designprinciper:
  • Helt frivillig — appen fungerar lika bra utan donation.
  • Inga påhittade siffror, omdömen eller "insamlat"-mål.
  • Betalning sker hos PayPal/Ko-fi i webbläsaren. Appen ser inga
    betalningsuppgifter och kräver ingen inloggning.
  • Text på svenska eller engelska (ui/i18n.py) och färger från
    appens aktiva tema.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("Fakturabunten")
LOG_PREFIX = "[DONATE]"

# Donationslänkar. Ändra här om de ska peka på andra konton.
DONATE_PAYPAL_URL: str = "https://paypal.me/Rickard3dPrint"
DONATE_KOFI_URL: str = "https://ko-fi.com/tokke2"

# Swish-numret ägs av app.py (EN källa); importeras mjukt så att
# modulen även fungerar fristående (t.ex. i tester).
try:
    from app import DONATE_SWISH as _APP_SWISH
except Exception:  # pragma: no cover
    _APP_SWISH = ""
DONATE_SWISH_NUMBER: str = _APP_SWISH or ""

try:
    from ui.i18n import tr
except Exception:  # pragma: no cover - fristående körning
    try:
        from i18n import tr  # type: ignore[no-redef]
    except Exception:
        def tr(key: str, **_fmt: object) -> str:  # type: ignore[no-redef]
            return key

try:
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
        QPushButton, QVBoxLayout, QWidget,
    )
    _QT_AVAILABLE: bool = True
except ImportError:  # pragma: no cover - Qt saknas (t.ex. i tester)
    _QT_AVAILABLE = False


def _open_url(url: str) -> bool:
    """Öppna länk i standardwebbläsaren. Returnerar True vid lyckad start."""
    if not _QT_AVAILABLE:
        return False
    try:
        ok = QDesktopServices.openUrl(QUrl(url))
        logger.info(f"{LOG_PREFIX} öppnade donationslänk ({'ok' if ok else 'misslyckades'})")
        return bool(ok)
    except Exception as e:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} kunde inte öppna länk: {e}")
        return False


if _QT_AVAILABLE:
    class DonateDialog(QDialog):
        """Liten, ärlig donationsruta med länkar till PayPal, Ko-fi och Swish."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setWindowTitle(tr("donate.window_title"))
            self.setModal(True)
            self.setMinimumWidth(420)

            root = QVBoxLayout(self)
            root.setContentsMargins(20, 18, 20, 16)
            root.setSpacing(12)

            # ── Guldkort med titel + text ─────────────────────────────
            card = QFrame(self)
            card.setObjectName("DonateCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 12)
            card_layout.setSpacing(8)

            title = QLabel(tr("donate.title"), card)
            title.setObjectName("DonateTitle")
            title.setStyleSheet("font-size: 19px; font-weight: 800;")
            card_layout.addWidget(title)

            body = QLabel(tr("donate.body_html"), card)
            body.setTextFormat(Qt.TextFormat.RichText)
            body.setWordWrap(True)
            body.setOpenExternalLinks(False)
            card_layout.addWidget(body)
            root.addWidget(card)

            # ── Betalknappar ──────────────────────────────────────────
            buttons = QHBoxLayout()
            buttons.setSpacing(8)

            btn_paypal = QPushButton(tr("donate.paypal"), self)
            btn_paypal.setObjectName("DonateButton")
            btn_paypal.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_paypal.setToolTip(DONATE_PAYPAL_URL)
            btn_paypal.setMinimumHeight(42)
            btn_paypal.clicked.connect(lambda: self._open(DONATE_PAYPAL_URL))
            buttons.addWidget(btn_paypal, 1)

            btn_kofi = QPushButton(tr("donate.kofi"), self)
            btn_kofi.setObjectName("DonateButtonAlt")
            btn_kofi.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_kofi.setToolTip(DONATE_KOFI_URL)
            btn_kofi.setMinimumHeight(42)
            btn_kofi.clicked.connect(lambda: self._open(DONATE_KOFI_URL))
            buttons.addWidget(btn_kofi, 1)

            root.addLayout(buttons)

            # ── Swish (svenska användare): kopiera numret ─────────────
            if DONATE_SWISH_NUMBER:
                btn_swish = QPushButton(
                    f"{tr('donate.swish')}  ·  {DONATE_SWISH_NUMBER}", self
                )
                btn_swish.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_swish.setToolTip(DONATE_SWISH_NUMBER)
                btn_swish.setMinimumHeight(38)
                btn_swish.clicked.connect(self._copy_swish)
                root.addWidget(btn_swish)

            self._lbl_status = QLabel("", self)
            self._lbl_status.setWordWrap(True)
            self._lbl_status.setStyleSheet("background:transparent;")
            root.addWidget(self._lbl_status)

            close_row = QHBoxLayout()
            close_row.addStretch(1)
            btn_close = QPushButton(tr("common.close"), self)
            btn_close.setMinimumHeight(36)
            btn_close.clicked.connect(self.accept)
            close_row.addWidget(btn_close)
            root.addLayout(close_row)

        # ── Aktioner ──────────────────────────────────────────────────
        def _open(self, url: str) -> None:
            if not _open_url(url):
                self._lbl_status.setText(tr("donate.open_failed"))

        def _copy_swish(self) -> None:
            try:
                QApplication.clipboard().setText(
                    DONATE_SWISH_NUMBER.replace(" ", "")
                )
                self._lbl_status.setText(
                    tr("donate.swish_copied", number=DONATE_SWISH_NUMBER)
                )
            except Exception as e:  # pragma: no cover
                logger.warning(f"{LOG_PREFIX} Swish-kopiering: {e}")


def open_donate_dialog(parent: Optional[QWidget] = None) -> bool:
    """Visa donationsdialogen. Returnerar False om Qt inte är tillgängligt."""
    if not _QT_AVAILABLE:
        logger.warning(f"{LOG_PREFIX} Qt saknas — kan inte visa donationsdialog")
        return False
    try:
        dlg = DonateDialog(parent)
        dlg.exec()
        return True
    except Exception as e:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} donationsdialog misslyckades: {e}")
        return False


def donate_menu_action(parent: QWidget):
    """QAction för menyer (Hjälp / tray / högerklick) — eller None utan Qt."""
    if not _QT_AVAILABLE:
        return None
    from PySide6.QtGui import QAction

    action = QAction(tr("menu.donate"), parent)
    action.setToolTip(tr("toolbar.donate_tip"))
    action.triggered.connect(lambda: open_donate_dialog(parent))
    return action
