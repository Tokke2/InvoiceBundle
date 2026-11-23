# -*- coding: utf-8 -*-
"""
Donationsdialog och låsta donationsuppgifter för Fakturabunten.

Öppnas från:
  • Hjälp-menyn            → "💖  Donationer…"
  • Verktygsfältet         → guldknappen 💖
  • Statusfältet           → "💖  Stöd" (alltid synlig)
  • Högerklick på flikraden / systemfältsmenyn / Om-dialogen
  • Inställningsfliken     → donationskortet

Designprinciper:
  • Låst konfiguration — mottagare (Swish-QR, PayPal, Ko-fi) är
    skrivskyddade konstanter som aldrig läses från settings.json eller
    går att ändra i gränssnittet.
  • Endast Swish QR-kod enligt Swishs officiella C-standard
    (numret visas aldrig i klartext och mottagarfältet är låst).
  • PayPal och Ko-fi har egna knappar direkt inne i appen samt valfria
    skanningsbara QR-koder — ingen separat webbsida skapas.
  • Helt frivillig — appen fungerar lika bra utan donation, både
    privat och kommersiellt (se LICENSE).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable, Optional
from urllib.parse import quote

logger = logging.getLogger("Fakturabunten")
LOG_PREFIX = "[DONATE]"


@dataclass(frozen=True)
class LockedDonationConfig:
    """Oföränderlig (låst) donationskonfiguration för appen."""

    swish_number: str
    paypal_url: str
    kofi_url: str
    swish_message: str
    preset_amounts_sek: tuple[int, ...]
    locked: bool = True


#: Låsta mottagaruppgifter — går ej att ändra i appen eller via settings.
LOCKED_DONATION: LockedDonationConfig = LockedDonationConfig(
    swish_number="0721817177",
    paypal_url="https://paypal.me/Rickard3dPrint",
    kofi_url="https://ko-fi.com/tokke2",
    swish_message="Fakturabunten",
    preset_amounts_sek=(25, 50, 100, 200),
    locked=True,
)

DONATE_PAYPAL_URL: str = LOCKED_DONATION.paypal_url
DONATE_KOFI_URL: str = LOCKED_DONATION.kofi_url
DONATE_SWISH_NUMBER: str = LOCKED_DONATION.swish_number


def locked_donation_config() -> LockedDonationConfig:
    """Returnerar den låsta, skrivskyddade donationskonfigurationen."""
    return LOCKED_DONATION


def _parse_positive_sek(value: str | int | float | Decimal | None) -> Optional[Decimal]:
    if value is None:
        return None
    raw = str(value).strip().replace(" ", "").replace(",", ".")
    if not raw:
        return None
    try:
        dec = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not dec.is_finite() or dec <= 0 or dec > Decimal("999999.99"):
        return None
    return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_swish_amount(amount: str | int | float | Decimal | None) -> str:
    """Formaterar belopp enligt Swish-specifikationen: två decimaler och komma."""
    dec = _parse_positive_sek(amount)
    if dec is None:
        return ""
    return f"{dec:.2f}".replace(".", ",")


def swish_qr_payload(
    number: str,
    amount: str | int | float | Decimal = "",
    message: str = "",
    *,
    lock_mask: int = 6,
) -> str:
    """
    Swish-QR i originalformatet (Swish "QR code design specification",
    typ C):  C<nummer>;<belopp>;<meddelande>;<mask>

    • nummer: bara siffror (072…), bit 0 hålls alltid 0 så mottagaren är låst
    • belopp: tomt för valfritt, annars två decimaler med decimalkomma
    • meddelande: högst 50 tecken (Swish-appens gräns), URL-kodat
    • mask 6 = belopp (2) + meddelande (4) redigerbara i Swish-appen
    """
    digits = "".join(c for c in (number or "") if c.isdigit())
    if digits.startswith("46") and len(digits) == 11:
        digits = "0" + digits[2:]
    amount_str = format_swish_amount(amount)
    msg_clean = (message or "")[:50]
    safe_mask = int(lock_mask) & ~1  # Bit 0 (mottagare) alltid låst
    return f"C{digits};{amount_str};{quote(msg_clean, safe='')};{safe_mask}"


def format_swish_number(number: str) -> str:
    """0721817177 → '072-181 71 77' (endast intern hjälpfunktion)."""
    digits = "".join(c for c in (number or "") if c.isdigit())
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]} {digits[6:8]} {digits[8:]}"
    return number or ""


def paypal_donate_url(amount_sek: str | int | float | Decimal | None = None) -> str:
    """Bygger PayPal.me-länk utifrån den låsta mottagaren och valt SEK-belopp."""
    dec = _parse_positive_sek(amount_sek)
    if dec is None:
        return LOCKED_DONATION.paypal_url
    if dec == dec.to_integral_value():
        amount_token = str(int(dec))
    else:
        amount_token = f"{dec:.2f}"
    return f"{LOCKED_DONATION.paypal_url}/{amount_token}SEK"


def make_qr_pixmap(payload: str, size: int = 188, dpr: float = 1.0):
    """Renderar högkontrast QR-pixmap (svart på vitt, quiet zone 4), skarp på HiDPI."""
    try:
        import qrcode
        from PySide6.QtGui import QImage, QPixmap

        dpr_val = max(1.0, float(dpr or 1.0))
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        modules = len(matrix)
        phys_target = max(modules * 2, int(round(size * dpr_val)))
        scale = max(2, phys_target // modules)
        side = modules * scale
        buf = bytearray(side * side)
        pos = 0
        for row in matrix:
            line = bytearray(side)
            i = 0
            for dark in row:
                fill = b"\x00" * scale if dark else b"\xff" * scale
                line[i:i + scale] = fill
                i += scale
            row_bytes = bytes(line)
            for _ in range(scale):
                buf[pos:pos + side] = row_bytes
                pos += side
        img = QImage(
            bytes(buf), side, side, side,
            QImage.Format.Format_Grayscale8,
        )
        pm = QPixmap.fromImage(img.copy())
        if dpr_val > 1.0:
            pm.setDevicePixelRatio(dpr_val)
        return pm
    except Exception as exc:  # qrcode ej installerat ännu / Qt saknas
        logger.info(f"{LOG_PREFIX} QR-kod ej tillgänglig: {exc}")
        return None


def make_swish_qr_pixmap(payload: str, size: int = 188, dpr: float = 1.0):
    """Renderar högkontrast QR-pixmap (svart på vitt, quiet zone 4) enligt Swish-standard."""
    return make_qr_pixmap(payload, size=size, dpr=dpr)


try:
    from ui.i18n import tr
except Exception:  # pragma: no cover - fristående körning
    try:
        from i18n import tr  # type: ignore[no-redef]
    except Exception:
        def tr(key: str, **_fmt: object) -> str:  # type: ignore[no-redef]
            return key

try:
    from ui.design import (
        app_icon_path,
        app_icon_pixmap,
        effective_dpr,
        fit_dialog_to_screen,
    )
except Exception:  # pragma: no cover
    try:
        from design import (  # type: ignore[no-redef]
            app_icon_path,
            app_icon_pixmap,
            effective_dpr,
            fit_dialog_to_screen,
        )
    except Exception:
        app_icon_path = None  # type: ignore[assignment]
        app_icon_pixmap = None  # type: ignore[assignment]
        effective_dpr = None  # type: ignore[assignment]
        fit_dialog_to_screen = None  # type: ignore[assignment]

try:
    from PySide6.QtCore import QPoint, QRect, QRegularExpression, QSize, Qt, QUrl
    from PySide6.QtGui import (
        QDesktopServices,
        QPalette,
        QPixmap,
        QRegularExpressionValidator,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QBoxLayout,
        QButtonGroup,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLayout,
        QLayoutItem,
        QLineEdit,
        QMenu,
        QPushButton,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )
    _QT_AVAILABLE: bool = True
except ImportError:  # pragma: no cover - Qt saknas (t.ex. i tester)
    _QT_AVAILABLE = False


def _open_url(url: str) -> bool:
    """Öppna låst länk i standardwebbläsaren. Returnerar True vid lyckad start."""
    if not _QT_AVAILABLE:
        return False
    try:
        ok = QDesktopServices.openUrl(QUrl(url))
        logger.info(
            f"{LOG_PREFIX} öppnade donationslänk ({'ok' if ok else 'misslyckades'})"
        )
        return bool(ok)
    except Exception as e:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} kunde inte öppna länk: {e}")
        return False


def _detect_dark(parent: Optional[QWidget]) -> bool:
    if parent is not None and hasattr(parent, "_dark"):
        try:
            return bool(getattr(parent, "_dark"))
        except Exception:
            pass
    if _QT_AVAILABLE:
        inst = QApplication.instance()
        if inst is not None:
            try:
                bg = inst.palette().color(QPalette.ColorRole.Window)
                return bg.lightness() < 128
            except Exception:
                pass
    return False


if _QT_AVAILABLE:
    class _FlowLayout(QLayout):
        """Enkel radbrytande layout så knappar och märken aldrig klipps smalt."""

        def __init__(self, parent: Optional[QWidget] = None, spacing: int = 8) -> None:
            super().__init__(parent)
            self._items: list[QLayoutItem] = []
            self.setSpacing(spacing)
            self.setContentsMargins(0, 0, 0, 0)

        def __del__(self) -> None:
            while self.count():
                self.takeAt(0)

        def addItem(self, item: QLayoutItem) -> None:
            self._items.append(item)

        def count(self) -> int:
            return len(self._items)

        def itemAt(self, index: int) -> Optional[QLayoutItem]:
            return self._items[index] if 0 <= index < len(self._items) else None

        def takeAt(self, index: int) -> Optional[QLayoutItem]:
            if 0 <= index < len(self._items):
                return self._items.pop(index)
            return None

        def expandingDirections(self) -> Qt.Orientation:
            return Qt.Orientation(0)

        def hasHeightForWidth(self) -> bool:
            return True

        def heightForWidth(self, width: int) -> int:
            return self._do_layout(QRect(0, 0, width, 0), test_only=True)

        def setGeometry(self, rect: QRect) -> None:
            super().setGeometry(rect)
            self._do_layout(rect, test_only=False)

        def sizeHint(self) -> QSize:
            return self.minimumSize()

        def minimumSize(self) -> QSize:
            size = QSize()
            for item in self._items:
                size = size.expandedTo(item.minimumSize())
            m = self.contentsMargins()
            size += QSize(m.left() + m.right(), m.top() + m.bottom())
            return size

        def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
            m = self.contentsMargins()
            effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
            x = effective.x()
            y = effective.y()
            line_height = 0
            spacing = max(0, self.spacing())

            for item in self._items:
                sz = item.sizeHint()
                next_x = x + sz.width() + spacing
                if next_x - spacing > effective.right() and line_height > 0:
                    x = effective.x()
                    y += line_height + spacing
                    next_x = x + sz.width() + spacing
                    line_height = 0
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), sz))
                x = next_x
                line_height = max(line_height, sz.height())

            return y + line_height - rect.y() + m.bottom()

    class DonateDialog(QDialog):
        """Stilren, låst donationsdialog i appen med Swish-QR, PayPal och Ko-fi."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setObjectName("DonateDialog")
            self._locked_config: LockedDonationConfig = LOCKED_DONATION
            self._amount_sek: Optional[Decimal] = None
            self._swish_payload: str = ""
            self._dark: bool = _detect_dark(parent)

            if callable(app_icon_path):
                try:
                    from PySide6.QtGui import QIcon as _QIcon
                    self.setWindowIcon(_QIcon(str(app_icon_path())))
                except Exception:
                    pass

            self.setWindowTitle(tr("donate.window_title"))
            self.setModal(True)
            self.setSizeGripEnabled(True)

            self._apply_dialog_styles()

            outer = QVBoxLayout(self)
            outer.setContentsMargins(10, 10, 10, 8)
            outer.setSpacing(6)

            scroll = QScrollArea(self)
            scroll.setObjectName("DonateScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._scroll = scroll

            content = QWidget(scroll)
            content.setObjectName("DonateContent")
            root = QVBoxLayout(content)
            root.setContentsMargins(2, 2, 4, 2)
            root.setSpacing(6)

            # ── 1. Hero-kort ──────────────────────────────────────────
            hero = QFrame(content)
            hero.setObjectName("DonateHero")
            hero_lay = QVBoxLayout(hero)
            hero_lay.setContentsMargins(12, 8, 12, 8)
            hero_lay.setSpacing(4)

            hero_top = QHBoxLayout()
            hero_top.setSpacing(10)

            if callable(app_icon_pixmap):
                pix_app = app_icon_pixmap(42)
                if not pix_app.isNull():
                    icon_badge = QLabel(hero)
                    icon_badge.setObjectName("DonateHeroIcon")
                    icon_badge.setPixmap(pix_app)
                    icon_badge.setFixedSize(52, 52)
                    icon_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    hero_top.addWidget(icon_badge, 0, Qt.AlignmentFlag.AlignTop)

            hero_text = QVBoxLayout()
            hero_text.setSpacing(3)

            eyebrow_row = QHBoxLayout()
            eyebrow_row.setContentsMargins(0, 0, 0, 0)
            eyebrow = QLabel(tr("donate.eyebrow"), hero)
            eyebrow.setObjectName("DonateHeroEyebrow")
            eyebrow_row.addWidget(eyebrow)
            eyebrow_row.addStretch(1)
            hero_text.addLayout(eyebrow_row)

            title = QLabel(tr("donate.title"), hero)
            title.setObjectName("DonateHeroTitle")
            title.setWordWrap(True)
            hero_text.addWidget(title)

            sub = QLabel(tr("donate.hero_sub"), hero)
            sub.setObjectName("DonateHeroSub")
            sub.setWordWrap(True)
            hero_text.addWidget(sub)

            hero_top.addLayout(hero_text, 1)
            hero_lay.addLayout(hero_top)

            pills_flow = _FlowLayout(spacing=6)
            for key in (
                "donate.pill_local",
                "donate.pill_noads",
                "donate.pill_commercial",
                "donate.pill_locked",
            ):
                pill = QLabel(tr(key), hero)
                pill.setObjectName("DonateHeroPill")
                pills_flow.addWidget(pill)
            hero_lay.addLayout(pills_flow)

            hero_ctas = _FlowLayout(spacing=7)
            btn_hero_swish = QPushButton(tr("donate.hero_cta_swish"), hero)
            btn_hero_swish.setObjectName("DonateHeroBtnSwish")
            btn_hero_swish.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_hero_swish.clicked.connect(
                lambda: self._scroll_to_widget(getattr(self, "_swish_card", None))
            )
            hero_ctas.addWidget(btn_hero_swish)

            self._btn_hero_paypal = QPushButton(tr("donate.hero_cta_paypal"), hero)
            self._btn_hero_paypal.setObjectName("DonateHeroBtnPayPal")
            self._btn_hero_paypal.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn_hero_paypal.clicked.connect(
                lambda: self._open(paypal_donate_url(self._amount_sek))
            )
            hero_ctas.addWidget(self._btn_hero_paypal)

            btn_hero_kofi = QPushButton(tr("donate.hero_cta_kofi"), hero)
            btn_hero_kofi.setObjectName("DonateHeroBtnKofi")
            btn_hero_kofi.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_hero_kofi.setToolTip(self._locked_config.kofi_url)
            btn_hero_kofi.clicked.connect(
                lambda: self._open(self._locked_config.kofi_url)
            )
            hero_ctas.addWidget(btn_hero_kofi)

            btn_hero_amt = QPushButton(tr("donate.hero_cta_amount"), hero)
            btn_hero_amt.setObjectName("DonateHeroBtnGhost")
            btn_hero_amt.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_hero_amt.clicked.connect(
                lambda: self._scroll_to_widget(getattr(self, "_amt_card", None))
            )
            hero_ctas.addWidget(btn_hero_amt)
            hero_lay.addLayout(hero_ctas)
            root.addWidget(hero)

            # ── 2. Personlig, varm text om stödet ─────────────────────
            msg_card = QFrame(content)
            msg_card.setObjectName("DonateMessageCard")
            msg_lay = QVBoxLayout(msg_card)
            msg_lay.setContentsMargins(12, 7, 12, 7)
            msg_lay.setSpacing(3)

            msg_kicker = QLabel(tr("donate.story_kicker"), msg_card)
            msg_kicker.setObjectName("DonateKicker")
            msg_lay.addWidget(msg_kicker)

            msg_title = QLabel(tr("donate.story_title"), msg_card)
            msg_title.setObjectName("DonateSectionTitle")
            msg_title.setWordWrap(True)
            msg_lay.addWidget(msg_title)

            msg_body = QLabel(tr("donate.story_body"), msg_card)
            msg_body.setObjectName("DonateStoryBody")
            msg_body.setTextFormat(Qt.TextFormat.RichText)
            msg_body.setWordWrap(True)
            msg_body.setOpenExternalLinks(False)
            msg_lay.addWidget(msg_body)
            root.addWidget(msg_card)

            # ── 3. Beloppsväljare (valfritt belopp till Swish & PayPal) ──
            amt_card = QFrame(content)
            amt_card.setObjectName("DonateAmountCard")
            self._amt_card = amt_card
            amt_lay = QVBoxLayout(amt_card)
            amt_lay.setContentsMargins(14, 9, 14, 9)
            amt_lay.setSpacing(5)

            amt_hdr = QHBoxLayout()
            amt_hdr.setSpacing(8)
            amt_kicker = QLabel(tr("donate.amount_kicker"), amt_card)
            amt_kicker.setObjectName("DonateKicker")
            amt_hdr.addWidget(amt_kicker)
            amt_hdr.addStretch(1)
            lock_chip = QLabel(tr("donate.locked_badge"), amt_card)
            lock_chip.setObjectName("DonateLockBadge")
            amt_hdr.addWidget(lock_chip)
            amt_lay.addLayout(amt_hdr)

            amt_title = QLabel(tr("donate.amount_title"), amt_card)
            amt_title.setObjectName("DonateSectionTitle")
            amt_title.setWordWrap(True)
            amt_lay.addWidget(amt_title)

            amt_hint = QLabel(tr("donate.amount_hint"), amt_card)
            amt_hint.setObjectName("DonateMuted")
            amt_hint.setWordWrap(True)
            amt_lay.addWidget(amt_hint)

            chips_flow = _FlowLayout(spacing=7)

            self._amount_group = QButtonGroup(self)
            self._amount_group.setExclusive(True)
            self._amount_buttons: dict[Optional[int], QPushButton] = {}

            btn_free = QPushButton(tr("donate.amount_free"), amt_card)
            btn_free.setObjectName("AmountChip")
            btn_free.setCheckable(True)
            btn_free.setChecked(True)
            btn_free.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_free.clicked.connect(lambda: self.set_amount_sek(None, from_chip=True))
            self._amount_group.addButton(btn_free)
            self._amount_buttons[None] = btn_free
            chips_flow.addWidget(btn_free)

            for kr in self._locked_config.preset_amounts_sek:
                chip = QPushButton(f"{kr} kr", amt_card)
                chip.setObjectName("AmountChip")
                chip.setCheckable(True)
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.clicked.connect(
                    lambda _checked=False, v=kr: self.set_amount_sek(v, from_chip=True)
                )
                self._amount_group.addButton(chip)
                self._amount_buttons[kr] = chip
                chips_flow.addWidget(chip)

            custom_wrap = QFrame(amt_card)
            custom_wrap.setObjectName("DonateCustomAmountWrap")
            custom_lay = QHBoxLayout(custom_wrap)
            custom_lay.setContentsMargins(10, 2, 10, 2)
            custom_lay.setSpacing(4)

            self._custom_amount_edit = QLineEdit(custom_wrap)
            self._custom_amount_edit.setObjectName("DonateCustomAmountEdit")
            self._custom_amount_edit.setPlaceholderText(
                tr("donate.amount_custom_ph")
            )
            self._custom_amount_edit.setFixedWidth(54)
            self._custom_amount_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._custom_amount_edit.setValidator(
                QRegularExpressionValidator(
                    QRegularExpression(r"^(?:[1-9]\d{0,4}(?:[.,]\d{1,2})?)?$"),
                    self._custom_amount_edit,
                )
            )
            self._custom_amount_edit.textEdited.connect(self._on_custom_amount_edited)
            custom_lay.addWidget(self._custom_amount_edit)

            kr_lbl = QLabel("kr", custom_wrap)
            kr_lbl.setObjectName("DonateCustomSuffix")
            custom_lay.addWidget(kr_lbl)
            chips_flow.addWidget(custom_wrap)
            amt_lay.addLayout(chips_flow)

            self._lbl_amount_info = QLabel("", amt_card)
            self._lbl_amount_info.setObjectName("DonateAmountInfo")
            self._lbl_amount_info.setWordWrap(True)
            amt_lay.addWidget(self._lbl_amount_info)
            root.addWidget(amt_card)

            # ── 4. Betalningskort (Swish QR + PayPal/Ko-fi) ──────────
            self._payments_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
            self._payments_layout.setSpacing(10)

            # Vänster kort: endast Swish QR (Swish-standard, låst mottagare)
            swish_card = QFrame(content)
            swish_card.setObjectName("DonateSwishCard")
            self._swish_card = swish_card
            swish_lay = QVBoxLayout(swish_card)
            swish_lay.setContentsMargins(14, 10, 14, 10)
            swish_lay.setSpacing(6)

            swish_hdr = QHBoxLayout()
            swish_hdr.setSpacing(6)
            swish_title = QLabel(tr("donate.swish_card_title"), swish_card)
            swish_title.setObjectName("DonateSectionTitle")
            swish_hdr.addWidget(swish_title)
            swish_hdr.addStretch(1)
            swish_lock = QLabel(tr("donate.swish_locked_pill"), swish_card)
            swish_lock.setObjectName("DonateSwishPill")
            swish_lock.setToolTip(tr("donate.pill_locked"))
            swish_hdr.addWidget(swish_lock)
            swish_lay.addLayout(swish_hdr)

            qr_box = QFrame(swish_card)
            qr_box.setObjectName("DonateQrBox")
            qr_lay = QVBoxLayout(qr_box)
            qr_lay.setContentsMargins(8, 8, 8, 8)
            qr_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self._lbl_swish_qr = QLabel(qr_box)
            self._lbl_swish_qr.setObjectName("DonateQrImage")
            self._lbl_swish_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._lbl_swish_qr.setToolTip(tr("donate.swish_qr_tip"))
            qr_lay.addWidget(self._lbl_swish_qr)
            swish_lay.addWidget(qr_box, 0, Qt.AlignmentFlag.AlignCenter)

            lbl_scan = QLabel(tr("donate.swish_scan"), swish_card)
            lbl_scan.setObjectName("DonateQrCaption")
            lbl_scan.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_scan.setWordWrap(True)
            swish_lay.addWidget(lbl_scan)

            lbl_qr_only = QLabel(tr("donate.swish_qr_only_note"), swish_card)
            lbl_qr_only.setObjectName("DonateMuted")
            lbl_qr_only.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_qr_only.setWordWrap(True)
            swish_lay.addWidget(lbl_qr_only)
            swish_lay.addStretch(1)

            self._payments_layout.addWidget(swish_card, 1)

            # Höger kort: PayPal & Ko-fi knappar + låst översikt (inga QR-koder för PayPal/Ko-fi)
            methods_card = QFrame(content)
            methods_card.setObjectName("DonateMethodsCard")
            methods_lay = QVBoxLayout(methods_card)
            methods_lay.setContentsMargins(14, 10, 14, 10)
            methods_lay.setSpacing(8)

            methods_title = QLabel(tr("donate.methods_title"), methods_card)
            methods_title.setObjectName("DonateSectionTitle")
            methods_title.setWordWrap(True)
            methods_lay.addWidget(methods_title)

            methods_hint = QLabel(tr("donate.methods_hint"), methods_card)
            methods_hint.setObjectName("DonateMuted")
            methods_hint.setWordWrap(True)
            methods_lay.addWidget(methods_hint)

            self._btn_paypal = QPushButton(tr("donate.paypal"), methods_card)
            self._btn_paypal.setObjectName("DonatePayPalBtn")
            self._btn_paypal.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn_paypal.setMinimumHeight(40)
            self._btn_paypal.clicked.connect(
                lambda: self._open(paypal_donate_url(self._amount_sek))
            )
            methods_lay.addWidget(self._btn_paypal)

            self._btn_kofi = QPushButton(tr("donate.kofi"), methods_card)
            self._btn_kofi.setObjectName("DonateKofiBtn")
            self._btn_kofi.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn_kofi.setToolTip(self._locked_config.kofi_url)
            self._btn_kofi.setMinimumHeight(40)
            self._btn_kofi.clicked.connect(
                lambda: self._open(self._locked_config.kofi_url)
            )
            methods_lay.addWidget(self._btn_kofi)

            # Låst & ej ändringsbar mottagarbox (helt skrivskyddad)
            lock_box = QFrame(methods_card)
            lock_box.setObjectName("DonateLockBox")
            lock_lay = QVBoxLayout(lock_box)
            lock_lay.setContentsMargins(10, 8, 10, 8)
            lock_lay.setSpacing(3)

            lock_box_title = QLabel(tr("donate.locked_box_title"), lock_box)
            lock_box_title.setObjectName("DonateLockBoxTitle")
            lock_box_title.setWordWrap(True)
            lock_lay.addWidget(lock_box_title)

            for line_text in (
                tr("donate.locked_line_swish"),
                tr("donate.locked_line_paypal", url=self._locked_config.paypal_url),
                tr("donate.locked_line_kofi", url=self._locked_config.kofi_url),
            ):
                line = QLabel(line_text, lock_box)
                line.setObjectName("DonateLockLine")
                line.setWordWrap(True)
                lock_lay.addWidget(line)

            methods_lay.addWidget(lock_box)
            methods_lay.addStretch(1)
            self._payments_layout.addWidget(methods_card, 1)

            root.addLayout(self._payments_layout)

            # ── 5. Varför din hjälp gör skillnad + förtroendemärken ──
            impact_card = QFrame(content)
            impact_card.setObjectName("DonateImpactCard")
            impact_lay = QVBoxLayout(impact_card)
            impact_lay.setContentsMargins(14, 10, 14, 11)
            impact_lay.setSpacing(6)

            imp_kicker = QLabel(tr("donate.impact_kicker"), impact_card)
            imp_kicker.setObjectName("DonateKicker")
            impact_lay.addWidget(imp_kicker)

            imp_title = QLabel(tr("donate.impact_title"), impact_card)
            imp_title.setObjectName("DonateSectionTitle")
            imp_title.setWordWrap(True)
            impact_lay.addWidget(imp_title)

            imp_intro = QLabel(tr("donate.impact_intro"), impact_card)
            imp_intro.setObjectName("DonateMuted")
            imp_intro.setWordWrap(True)
            impact_lay.addWidget(imp_intro)

            self._impact_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
            self._impact_layout.setSpacing(8)
            impact_specs = (
                ("🧾", "#1e8449", "donate.impact_1_title", "donate.impact_1_body"),
                ("⚙️", "#2980b9", "donate.impact_2_title", "donate.impact_2_body"),
                ("📄", "#b7791f", "donate.impact_3_title", "donate.impact_3_body"),
            )
            for ico, accent, t_key, b_key in impact_specs:
                item = QFrame(impact_card)
                item.setObjectName("DonateImpactItem")
                item_lay = QHBoxLayout(item)
                item_lay.setContentsMargins(10, 9, 10, 9)
                item_lay.setSpacing(9)

                ico_lbl = QLabel(ico, item)
                ico_lbl.setObjectName("DonateImpactIcon")
                ico_lbl.setFixedSize(34, 34)
                ico_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ico_lbl.setStyleSheet(
                    f"background-color: {accent}; color: #ffffff; "
                    "border-radius: 10px; font-size: 15px;"
                )
                item_lay.addWidget(ico_lbl, 0, Qt.AlignmentFlag.AlignTop)

                txt_col = QVBoxLayout()
                txt_col.setSpacing(2)
                raw_title = tr(t_key)
                if raw_title.startswith(ico):
                    raw_title = raw_title[len(ico):].lstrip()
                it_title = QLabel(raw_title, item)
                it_title.setObjectName("DonateImpactItemTitle")
                it_title.setWordWrap(True)
                txt_col.addWidget(it_title)
                it_body = QLabel(tr(b_key), item)
                it_body.setObjectName("DonateImpactItemBody")
                it_body.setWordWrap(True)
                txt_col.addWidget(it_body)
                item_lay.addLayout(txt_col, 1)
                self._impact_layout.addWidget(item, 1)
            impact_lay.addLayout(self._impact_layout)

            trust_flow = _FlowLayout(spacing=6)
            for t_key in (
                "donate.trust_1",
                "donate.trust_2",
                "donate.trust_3",
                "donate.trust_4",
            ):
                pill = QLabel(tr(t_key), impact_card)
                pill.setObjectName("DonateTrustPill")
                trust_flow.addWidget(pill)
            impact_lay.addLayout(trust_flow)
            root.addWidget(impact_card)

            # ── 6. Vanliga frågor (kollapsbara, lugnt & tryggt) ───────
            faq_card = QFrame(content)
            faq_card.setObjectName("DonateFaqCard")
            faq_lay = QVBoxLayout(faq_card)
            faq_lay.setContentsMargins(14, 10, 14, 11)
            faq_lay.setSpacing(6)

            faq_kicker = QLabel(tr("donate.faq_kicker"), faq_card)
            faq_kicker.setObjectName("DonateKicker")
            faq_lay.addWidget(faq_kicker)

            faq_title = QLabel(tr("donate.faq_title"), faq_card)
            faq_title.setObjectName("DonateSectionTitle")
            faq_title.setWordWrap(True)
            faq_lay.addWidget(faq_title)

            self._faq_items: list[tuple[QPushButton, QLabel, str]] = []
            for idx, (q_key, a_key) in enumerate((
                ("donate.faq_1_q", "donate.faq_1_a"),
                ("donate.faq_2_q", "donate.faq_2_a"),
                ("donate.faq_3_q", "donate.faq_3_a"),
                ("donate.faq_4_q", "donate.faq_4_a"),
            )):
                q_box = QFrame(faq_card)
                q_box.setObjectName("DonateFaqItem")
                q_lay = QVBoxLayout(q_box)
                q_lay.setContentsMargins(10, 6, 10, 7)
                q_lay.setSpacing(4)

                q_text = tr(q_key)
                btn_q = QPushButton(q_box)
                btn_q.setObjectName("DonateFaqBtn")
                btn_q.setCheckable(True)
                btn_q.setChecked(idx == 0)
                btn_q.setCursor(Qt.CursorShape.PointingHandCursor)

                lbl_a = QLabel(tr(a_key), q_box)
                lbl_a.setObjectName("DonateFaqAnswer")
                lbl_a.setWordWrap(True)
                lbl_a.setVisible(idx == 0)

                def _make_toggle(btn: QPushButton, ans: QLabel, title_txt: str):
                    def _update(checked: bool) -> None:
                        arrow = "▴" if checked else "▾"
                        btn.setText(f"{title_txt}   {arrow}")
                        ans.setVisible(bool(checked))
                    return _update

                updater = _make_toggle(btn_q, lbl_a, q_text)
                updater(idx == 0)
                btn_q.toggled.connect(updater)
                q_lay.addWidget(btn_q)
                q_lay.addWidget(lbl_a)
                self._faq_items.append((btn_q, lbl_a, q_text))
                faq_lay.addWidget(q_box)
            root.addWidget(faq_card)

            # ── 7. Avslutande stöd-kort (slut-CTA) ───────────────────
            footer_cta = QFrame(content)
            footer_cta.setObjectName("DonateFooterCta")
            fc_lay = QVBoxLayout(footer_cta)
            fc_lay.setContentsMargins(14, 12, 14, 12)
            fc_lay.setSpacing(6)

            fc_title = QLabel(
                f"💖  {tr('donate.footer_title')}", footer_cta
            )
            fc_title.setObjectName("DonateFooterTitle")
            fc_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fc_title.setWordWrap(True)
            fc_lay.addWidget(fc_title)

            fc_sub = QLabel(tr("donate.footer_sub"), footer_cta)
            fc_sub.setObjectName("DonateFooterSub")
            fc_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fc_sub.setWordWrap(True)
            fc_lay.addWidget(fc_sub)

            fc_row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
            self._footer_cta_row = fc_row
            fc_row.setSpacing(8)
            fc_row.addStretch(1)
            btn_fc_swish = QPushButton(tr("donate.hero_cta_swish"), footer_cta)
            btn_fc_swish.setObjectName("DonateHeroBtnSwish")
            btn_fc_swish.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_fc_swish.clicked.connect(
                lambda: self._scroll_to_widget(getattr(self, "_swish_card", None))
            )
            fc_row.addWidget(btn_fc_swish)

            self._btn_fc_paypal = QPushButton(
                tr("donate.hero_cta_paypal"), footer_cta
            )
            self._btn_fc_paypal.setObjectName("DonateHeroBtnPayPal")
            self._btn_fc_paypal.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn_fc_paypal.clicked.connect(
                lambda: self._open(paypal_donate_url(self._amount_sek))
            )
            fc_row.addWidget(self._btn_fc_paypal)

            btn_fc_kofi = QPushButton(tr("donate.hero_cta_kofi"), footer_cta)
            btn_fc_kofi.setObjectName("DonateHeroBtnKofi")
            btn_fc_kofi.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_fc_kofi.setToolTip(self._locked_config.kofi_url)
            btn_fc_kofi.clicked.connect(
                lambda: self._open(self._locked_config.kofi_url)
            )
            fc_row.addWidget(btn_fc_kofi)
            fc_row.addStretch(1)
            fc_lay.addLayout(fc_row)

            fc_note = QLabel(tr("donate.footer_note"), footer_cta)
            fc_note.setObjectName("DonateFooterNote")
            fc_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fc_note.setWordWrap(True)
            fc_lay.addWidget(fc_note)
            root.addWidget(footer_cta)

            scroll.setWidget(content)
            outer.addWidget(scroll, 1)

            # ── 5. Fast fotrad (alltid synlig) ────────────────────────
            footer = QHBoxLayout()
            footer.setSpacing(10)
            self._lbl_status = QLabel("", self)
            self._lbl_status.setObjectName("DonateStatus")
            self._lbl_status.setWordWrap(True)
            footer.addWidget(self._lbl_status, 1)

            btn_close = QPushButton(tr("common.close"), self)
            btn_close.setObjectName("DonateCloseBtn")
            btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_close.setMinimumHeight(34)
            btn_close.clicked.connect(self.accept)
            footer.addWidget(btn_close)
            outer.addLayout(footer)

            self.set_amount_sek(None, from_chip=True)

            if callable(fit_dialog_to_screen):
                fit_dialog_to_screen(
                    self,
                    780,
                    860,
                    minimum_width=440,
                    minimum_height=460,
                )
            else:
                self.setMinimumWidth(440)
                self.resize(780, 860)
            self._update_responsive_direction(self.width())

        def _apply_dialog_styles(self) -> None:
            if self._dark:
                dlg_bg = "#0c1218"
                card_bg = "#141c26"
                sub_card_bg = "#192432"
                border = "#2a3848"
                text_strong = "#ffffff"
                text_muted = "#c2cfde"
                chip_bg = "#1c2836"
                chip_text = "#e8eef7"
                chip_border = "#35475c"
                lock_bg = "#111b27"
                lock_accent = "#f0c24a"
                swish_pill_bg = "#123824"
                swish_pill_fg = "#74e8a3"
                amount_ok = "#6ae39c"
                scroll_bg = "#0c1218"
                scroll_handle = "#3a4a5c"
                close_bg = "#1c2836"
                close_fg = "#f4f7fb"
                close_hover = "#283648"
            else:
                dlg_bg = "#f4f1ea"
                card_bg = "#fffcf7"
                sub_card_bg = "#f8f4ec"
                border = "#ddd4c6"
                text_strong = "#0d1218"
                text_muted = "#434c57"
                chip_bg = "#ffffff"
                chip_text = "#1c2128"
                chip_border = "#cfc6b6"
                lock_bg = "#f4efe4"
                lock_accent = "#7a4e0b"
                swish_pill_bg = "#e8f8ee"
                swish_pill_fg = "#166534"
                amount_ok = "#166534"
                scroll_bg = "#f4f1ea"
                scroll_handle = "#cfc6b6"
                close_bg = "#fffcf7"
                close_fg = "#1c2128"
                close_hover = "#efe8dc"

            self.setStyleSheet(f"""
                QDialog#DonateDialog, QWidget#DonateContent {{
                    background-color: {dlg_bg};
                    color: {text_strong};
                }}
                QScrollArea#DonateScroll {{
                    background-color: transparent;
                    border: none;
                }}
                QDialog#DonateDialog QScrollBar:vertical {{
                    background: {scroll_bg};
                    width: 10px;
                    border-radius: 5px;
                    margin: 0;
                    border: none;
                }}
                QDialog#DonateDialog QScrollBar::handle:vertical {{
                    background: {scroll_handle};
                    min-height: 28px;
                    border-radius: 5px;
                }}
                QDialog#DonateDialog QScrollBar::add-line:vertical,
                QDialog#DonateDialog QScrollBar::sub-line:vertical {{
                    height: 0;
                    background: none;
                }}
                QDialog#DonateDialog QScrollBar::add-page:vertical,
                QDialog#DonateDialog QScrollBar::sub-page:vertical {{
                    background: none;
                }}
                QFrame#DonateHero {{
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:1,
                        stop:0 #14532d, stop:0.52 #1b7843, stop:1 #a15e0b
                    );
                    border-radius: 16px;
                    border: 1px solid #2b8a53;
                }}
                QLabel#DonateHeroIcon {{
                    background-color: #f6f3ee;
                    border-radius: 14px;
                    padding: 5px;
                }}
                QLabel#DonateHeroEyebrow {{
                    background-color: rgba(255, 255, 255, 0.20);
                    border: 1px solid rgba(255, 255, 255, 0.42);
                    border-radius: 10px;
                    padding: 3px 10px;
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: 800;
                }}
                QLabel#DonateHeroTitle {{
                    color: #ffffff;
                    font-size: 21px;
                    font-weight: 800;
                    background: transparent;
                }}
                QLabel#DonateHeroSub {{
                    color: #f4fff8;
                    font-size: 12px;
                    font-weight: 500;
                    background: transparent;
                }}
                QLabel#DonateHeroPill {{
                    background-color: rgba(12, 32, 22, 0.36);
                    border: 1px solid rgba(255, 255, 255, 0.32);
                    border-radius: 10px;
                    padding: 3px 9px;
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: 700;
                }}
                QFrame#DonateAmountCard, QFrame#DonateMessageCard,
                QFrame#DonateImpactCard, QFrame#DonateFaqCard {{
                    background-color: {card_bg};
                    border: 1px solid {border};
                    border-radius: 14px;
                }}
                QFrame#DonateImpactCard {{
                    border-top: 4px solid #1e8449;
                }}
                QFrame#DonateFaqCard {{
                    border-top: 4px solid #8e44ad;
                }}
                QFrame#DonateImpactItem, QFrame#DonateFaqItem {{
                    background-color: {sub_card_bg};
                    border: 1px solid {border};
                    border-radius: 11px;
                }}
                QLabel#DonateImpactItemTitle {{
                    color: {text_strong};
                    font-size: 12.5px;
                    font-weight: 800;
                    background: transparent;
                }}
                QLabel#DonateImpactItemBody {{
                    color: {text_muted};
                    font-size: 11.5px;
                    font-weight: 500;
                    background: transparent;
                }}
                QLabel#DonateTrustPill {{
                    background-color: {sub_card_bg};
                    border: 1px solid {border};
                    border-radius: 10px;
                    padding: 4px 10px;
                    color: {text_muted};
                    font-size: 11px;
                    font-weight: 700;
                }}
                QPushButton#DonateFaqBtn {{
                    background: transparent;
                    border: none;
                    color: {text_strong};
                    font-size: 12.5px;
                    font-weight: 800;
                    text-align: left;
                    padding: 2px 0;
                }}
                QLabel#DonateFaqAnswer {{
                    color: {text_muted};
                    font-size: 11.5px;
                    font-weight: 500;
                    background: transparent;
                    padding-top: 2px;
                }}
                QPushButton#DonateHeroBtnSwish {{
                    background-color: #00b06c;
                    color: #ffffff;
                    border: 1px solid #00915a;
                    border-radius: 10px;
                    font-size: 12px;
                    font-weight: 800;
                    padding: 6px 12px;
                }}
                QPushButton#DonateHeroBtnSwish:hover {{
                    background-color: #00c97c;
                }}
                QPushButton#DonateHeroBtnPayPal {{
                    background-color: #0070ba;
                    color: #ffffff;
                    border: 1px solid #005c99;
                    border-radius: 10px;
                    font-size: 12px;
                    font-weight: 800;
                    padding: 6px 12px;
                }}
                QPushButton#DonateHeroBtnPayPal:hover {{
                    background-color: #0b84d4;
                }}
                QPushButton#DonateHeroBtnKofi {{
                    background-color: #d94340;
                    color: #ffffff;
                    border: 1px solid #b3322f;
                    border-radius: 10px;
                    font-size: 12px;
                    font-weight: 800;
                    padding: 6px 12px;
                }}
                QPushButton#DonateHeroBtnKofi:hover {{
                    background-color: #ef5653;
                }}
                QPushButton#DonateHeroBtnGhost {{
                    background-color: rgba(255, 255, 255, 0.22);
                    color: #ffffff;
                    border: 1px solid rgba(255, 255, 255, 0.45);
                    border-radius: 10px;
                    font-size: 12px;
                    font-weight: 800;
                    padding: 6px 12px;
                }}
                QPushButton#DonateHeroBtnGhost:hover {{
                    background-color: rgba(255, 255, 255, 0.32);
                }}
                QFrame#DonateFooterCta {{
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:1,
                        stop:0 #22313f, stop:0.55 #17212c, stop:1 #27384a
                    );
                    border: 1px solid #35475c;
                    border-radius: 14px;
                }}
                QLabel#DonateFooterTitle {{
                    color: #ffffff;
                    font-size: 15px;
                    font-weight: 800;
                    background: transparent;
                }}
                QLabel#DonateFooterSub {{
                    color: #cbd5e1;
                    font-size: 12px;
                    font-weight: 500;
                    background: transparent;
                }}
                QLabel#DonateFooterNote {{
                    color: #94a3b8;
                    font-size: 11px;
                    font-weight: 600;
                    background: transparent;
                }}
                QLabel#DonateStoryBody {{
                    color: {text_muted};
                    font-size: 12.5px;
                    font-weight: 500;
                    background: transparent;
                }}
                QFrame#DonateSwishCard {{
                    background-color: {card_bg};
                    border: 1px solid {border};
                    border-top: 4px solid #1e8449;
                    border-radius: 14px;
                }}
                QFrame#DonateMethodsCard {{
                    background-color: {card_bg};
                    border: 1px solid {border};
                    border-top: 4px solid #d4a017;
                    border-radius: 14px;
                }}
                QLabel#DonateKicker {{
                    color: {lock_accent};
                    font-size: 11px;
                    font-weight: 800;
                    letter-spacing: 1px;
                    background: transparent;
                }}
                QLabel#DonateSectionTitle {{
                    color: {text_strong};
                    font-size: 15px;
                    font-weight: 800;
                    background: transparent;
                }}
                QLabel#DonateMuted {{
                    color: {text_muted};
                    font-size: 12px;
                    font-weight: 500;
                    background: transparent;
                }}
                QLabel#DonateLockBadge {{
                    background-color: {lock_bg};
                    border: 1px solid {border};
                    border-radius: 9px;
                    padding: 3px 9px;
                    color: {lock_accent};
                    font-size: 11px;
                    font-weight: 800;
                }}
                QLabel#DonateSwishPill {{
                    background-color: {swish_pill_bg};
                    color: {swish_pill_fg};
                    border-radius: 9px;
                    padding: 3px 9px;
                    font-size: 11px;
                    font-weight: 800;
                }}
                QPushButton#AmountChip {{
                    background-color: {chip_bg};
                    color: {chip_text};
                    border: 1.5px solid {chip_border};
                    border-radius: 15px;
                    padding: 5px 13px;
                    min-height: 22px;
                    font-size: 13px;
                    font-weight: 700;
                }}
                QPushButton#AmountChip:hover {{
                    border-color: #1e8449;
                }}
                QPushButton#AmountChip:checked {{
                    background-color: #1e8449;
                    color: #ffffff;
                    border-color: #14532d;
                }}
                QFrame#DonateCustomAmountWrap {{
                    background-color: {chip_bg};
                    border: 1.5px solid {chip_border};
                    border-radius: 13px;
                    min-height: 28px;
                }}
                QLineEdit#DonateCustomAmountEdit {{
                    background: transparent;
                    border: none;
                    color: {text_strong};
                    font-weight: 800;
                    font-size: 13px;
                    padding: 2px 2px;
                }}
                QLabel#DonateCustomSuffix {{
                    color: {text_muted};
                    font-size: 12px;
                    font-weight: 700;
                    background: transparent;
                }}
                QLabel#DonateAmountInfo {{
                    color: {amount_ok};
                    font-size: 12px;
                    font-weight: 700;
                    background: transparent;
                }}
                QFrame#DonateQrBox {{
                    background-color: #ffffff;
                    border: 2px solid #1e8449;
                    border-radius: 14px;
                }}
                QLabel#DonateQrImage {{
                    background-color: #ffffff;
                    color: #111827;
                }}
                QLabel#DonateQrCaption {{
                    color: {text_strong};
                    font-size: 13px;
                    font-weight: 800;
                    background: transparent;
                }}
                QPushButton#DonatePayPalBtn {{
                    background-color: #0070ba;
                    color: #ffffff;
                    border: 1px solid #005c99;
                    border-radius: 10px;
                    font-size: 14px;
                    font-weight: 800;
                    padding: 7px 14px;
                }}
                QPushButton#DonatePayPalBtn:hover {{
                    background-color: #0b84d4;
                }}
                QPushButton#DonateKofiBtn {{
                    background-color: #c93b38;
                    color: #ffffff;
                    border: 1px solid #a82e2b;
                    border-radius: 10px;
                    font-size: 14px;
                    font-weight: 800;
                    padding: 7px 14px;
                }}
                QPushButton#DonateKofiBtn:hover {{
                    background-color: #e04a46;
                }}
                QFrame#DonateLockBox {{
                    background-color: {sub_card_bg};
                    border: 1px solid {border};
                    border-radius: 10px;
                }}
                QLabel#DonateLockBoxTitle {{
                    color: {text_strong};
                    font-size: 12px;
                    font-weight: 800;
                    background: transparent;
                }}
                QLabel#DonateLockLine {{
                    color: {text_muted};
                    font-size: 11px;
                    font-weight: 600;
                    background: transparent;
                }}
                QLabel#DonateStatus {{
                    color: {amount_ok};
                    font-size: 12px;
                    font-weight: 700;
                    background: transparent;
                }}
                QPushButton#DonateCloseBtn {{
                    background-color: {close_bg};
                    color: {close_fg};
                    border: 1px solid {border};
                    border-radius: 8px;
                    font-weight: 700;
                    padding: 6px 16px;
                }}
                QPushButton#DonateCloseBtn:hover {{
                    background-color: {close_hover};
                }}
            """)

        def _update_responsive_direction(self, width: int) -> None:
            direction = (
                QBoxLayout.Direction.LeftToRight
                if width >= 580 else QBoxLayout.Direction.TopToBottom
            )
            self._payments_layout.setDirection(direction)
            if hasattr(self, "_impact_layout"):
                self._impact_layout.setDirection(
                    QBoxLayout.Direction.LeftToRight
                    if width >= 620 else QBoxLayout.Direction.TopToBottom
                )
            if hasattr(self, "_footer_cta_row"):
                self._footer_cta_row.setDirection(
                    QBoxLayout.Direction.LeftToRight
                    if width >= 480 else QBoxLayout.Direction.TopToBottom
                )

        def _scroll_to_widget(self, target: Optional[QWidget]) -> None:
            if target is not None and hasattr(self, "_scroll"):
                self._scroll.ensureWidgetVisible(target, 16, 20)

        def resizeEvent(self, event) -> None:
            super().resizeEvent(event)
            self._update_responsive_direction(self.width())

        def _on_custom_amount_edited(self, text: str) -> None:
            parsed = _parse_positive_sek(text)
            if parsed is None:
                if not text.strip():
                    btn_free = self._amount_buttons.get(None)
                    if btn_free is not None:
                        btn_free.setChecked(True)
                    self.set_amount_sek(None, from_chip=False)
                return
            self._amount_group.setExclusive(False)
            for btn in self._amount_buttons.values():
                btn.setChecked(False)
            self._amount_group.setExclusive(True)
            self.set_amount_sek(parsed, from_chip=False)

        def set_amount_sek(
            self,
            amount_sek: str | int | float | Decimal | None,
            *,
            from_chip: bool = False,
        ) -> None:
            """Uppdaterar valt donationsbelopp och regenererar Swish-QR + PayPal-URL/QR."""
            parsed = _parse_positive_sek(amount_sek)
            self._amount_sek = parsed
            if from_chip and hasattr(self, "_custom_amount_edit"):
                self._custom_amount_edit.blockSignals(True)
                self._custom_amount_edit.clear()
                self._custom_amount_edit.blockSignals(False)

            if parsed is None:
                display_amt = ""
            elif parsed == parsed.to_integral_value():
                display_amt = str(int(parsed))
            else:
                display_amt = f"{parsed:.2f}".replace(".", ",")

            # Uppdatera Swish-QR med låst mottagare från LOCKED_DONATION
            self._swish_payload = swish_qr_payload(
                self._locked_config.swish_number,
                amount=parsed if parsed is not None else "",
                message=self._locked_config.swish_message,
                lock_mask=6,
            )
            dpr = effective_dpr(self) if callable(effective_dpr) else 1.0
            pixmap = make_swish_qr_pixmap(
                self._swish_payload, size=132, dpr=dpr
            )
            if pixmap is not None:
                self._lbl_swish_qr.setPixmap(pixmap)
                self._lbl_swish_qr.setText("")
            else:
                self._lbl_swish_qr.setPixmap(QPixmap())
                self._lbl_swish_qr.setWordWrap(True)
                self._lbl_swish_qr.setText(tr("donate.swish_qr_missing"))

            # Uppdatera PayPal-knappen och info-raden (endast knappar för PayPal & Ko-fi)
            pp_url = paypal_donate_url(parsed)
            self._btn_paypal.setToolTip(pp_url)
            if hasattr(self, "_btn_hero_paypal"):
                self._btn_hero_paypal.setToolTip(pp_url)
            if hasattr(self, "_btn_fc_paypal"):
                self._btn_fc_paypal.setToolTip(pp_url)

            if display_amt:
                self._btn_paypal.setText(
                    tr("donate.paypal_amount", amount=display_amt)
                )
                self._lbl_amount_info.setText(
                    tr("donate.amount_selected_value", amount=display_amt)
                )
            else:
                self._btn_paypal.setText(tr("donate.paypal"))
                self._lbl_amount_info.setText(tr("donate.amount_selected_free"))

        # ── Aktioner ──────────────────────────────────────────────────
        def _open(self, url: str) -> None:
            if _open_url(url):
                self._lbl_status.setText(tr("donate.opened_ok"))
            else:
                self._lbl_status.setText(tr("donate.open_failed"))


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


def build_donate_menu(
    parent: QWidget,
    *,
    open_dialog_cb: Optional[Callable[[], None]] = None,
    open_url_cb: Optional[Callable[[str], None]] = None,
):
    """Bygger en låst toppmeny för donationer (Swish QR, PayPal, Ko-fi)."""
    if not _QT_AVAILABLE:
        return None
    from PySide6.QtGui import QAction

    cfg = locked_donation_config()
    on_dialog = open_dialog_cb or (lambda: open_donate_dialog(parent))
    on_url = open_url_cb or _open_url

    menu = QMenu(tr("menu.donate_bar"), parent)
    act_open = QAction(tr("menu.donate"), menu)
    act_open.setToolTip(tr("toolbar.donate_tip"))
    act_open.triggered.connect(on_dialog)
    menu.addAction(act_open)

    menu.addSeparator()

    act_swish = QAction(tr("menu.donate_swish_qr"), menu)
    act_swish.setToolTip(tr("donate.swish_qr_tip"))
    act_swish.triggered.connect(on_dialog)
    menu.addAction(act_swish)

    act_paypal = QAction(tr("menu.donate_paypal"), menu)
    act_paypal.setToolTip(cfg.paypal_url)
    act_paypal.triggered.connect(lambda _c=False, u=cfg.paypal_url: on_url(u))
    menu.addAction(act_paypal)

    act_kofi = QAction(tr("menu.donate_kofi"), menu)
    act_kofi.setToolTip(cfg.kofi_url)
    act_kofi.triggered.connect(lambda _c=False, u=cfg.kofi_url: on_url(u))
    menu.addAction(act_kofi)

    menu.addSeparator()

    act_locked = QAction(tr("menu.donate_locked"), menu)
    act_locked.setEnabled(False)
    menu.addAction(act_locked)
    return menu
