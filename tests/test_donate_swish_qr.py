# -*- coding: utf-8 -*-
"""
Tester: låst donationsmeny, Swish-QR (Swish-standard) och PayPal/Ko-fi i appen.

Riktiga numret (0721817177) bor i app.DONATE_SWISH / ui.donate.LOCKED_DONATION
och QR-koden följer Swishs officiella C-format så den går att skanna
i Swish-appen: C<nummer>;<belopp>;<meddelande>;<mask 6>, där mottagaren
är låst och numret aldrig visas i klartext i donationsdialogen.
"""
from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _decode_pixmap_qr(pixmap) -> str | None:
    try:
        from PIL import Image
        from PySide6.QtCore import QBuffer, QIODevice
        import zxingcpp
    except Exception:
        return None
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    assert pixmap.save(buf, "PNG")
    buf.close()
    import io
    img = Image.open(io.BytesIO(bytes(buf.data())))
    res = zxingcpp.read_barcode(img)
    return res.text if res else None


def test_swish_number_is_the_real_one():
    import app as core
    digits = "".join(c for c in core.DONATE_SWISH if c.isdigit())
    assert digits == "0721817177"


def test_donation_config_is_locked_and_cannot_be_mutated():
    from ui.donate import (
        DONATE_KOFI_URL,
        DONATE_PAYPAL_URL,
        DONATE_SWISH_NUMBER,
        LOCKED_DONATION,
        locked_donation_config,
    )

    cfg = locked_donation_config()
    assert cfg is LOCKED_DONATION
    assert cfg.locked is True
    assert cfg.swish_number == DONATE_SWISH_NUMBER == "0721817177"
    assert cfg.paypal_url == DONATE_PAYPAL_URL == "https://paypal.me/Rickard3dPrint"
    assert cfg.kofi_url == DONATE_KOFI_URL == "https://ko-fi.com/tokke2"
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        cfg.swish_number = "0700000000"  # type: ignore[misc]
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        cfg.paypal_url = "https://example.com"  # type: ignore[misc]
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        cfg.kofi_url = "https://example.com"  # type: ignore[misc]


def test_payload_follows_official_swish_c_format():
    from ui.donate import (
        DONATE_SWISH_NUMBER,
        format_swish_amount,
        format_swish_number,
        paypal_donate_url,
        swish_qr_payload,
    )
    assert DONATE_SWISH_NUMBER == "0721817177"
    # Donation: nummer låst, belopp + meddelande redigerbara (mask 6)
    assert swish_qr_payload("0721817177") == "C0721817177;;;6"
    assert swish_qr_payload(
        "0721817177", message="Donation"
    ) == "C0721817177;;Donation;6"
    # Belopp med decimalkomma enligt specifikationen
    assert swish_qr_payload(
        "0721817177", amount="100,00"
    ) == "C0721817177;100,00;;6"
    assert swish_qr_payload("0721817177", amount=50) == "C0721817177;50,00;;6"
    assert format_swish_amount("49.5") == "49,50"
    # Bit 0 (mottagare redigerbar) rensas alltid bort så numret förblir låst
    assert swish_qr_payload("0721817177", lock_mask=7) == "C0721817177;;;6"
    # +46-normalisering och meddelande URL-kodas
    assert swish_qr_payload(
        "+46 72 181 71 77", message="Tack så mycket!"
    ).startswith("C0721817177;;Tack%20s%C3%A5%20mycket%21;6")
    # Visningsformat
    assert format_swish_number("0721817177") == "072-181 71 77"
    assert paypal_donate_url(None) == "https://paypal.me/Rickard3dPrint"
    assert paypal_donate_url(50) == "https://paypal.me/Rickard3dPrint/50SEK"


def test_dialog_shows_real_qr_pixmap_and_hides_plaintext_number():
    _qapp()
    from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton
    from ui.donate import DonateDialog

    dlg = DonateDialog()
    assert dlg._lbl_swish_qr is not None
    pixmap = dlg._lbl_swish_qr.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.width() >= 100 and pixmap.height() >= 100
    assert dlg._swish_payload == "C0721817177;;Fakturabunten;6"

    decoded = _decode_pixmap_qr(pixmap)
    if decoded is not None:
        assert decoded == "C0721817177;;Fakturabunten;6"

    # Endast Swish QR-kod — telefonnumret visas aldrig i klartext eller redigeringsfält
    for cls in (QLabel, QPushButton, QLineEdit):
        for widget in dlg.findChildren(cls):
            text = widget.text() if hasattr(widget, "text") else ""
            tip = widget.toolTip()
            assert "0721817177" not in text
            assert "072-181" not in text
            assert "0721817177" not in tip
            assert "072-181" not in tip
    dlg.reject()


def test_dialog_amount_chips_update_swish_qr_and_paypal():
    _qapp()
    from ui.donate import DonateDialog

    dlg = DonateDialog()
    dlg._amount_buttons[50].click()
    assert dlg._swish_payload == "C0721817177;50,00;Fakturabunten;6"
    assert dlg._btn_paypal.toolTip() == "https://paypal.me/Rickard3dPrint/50SEK"
    decoded = _decode_pixmap_qr(dlg._lbl_swish_qr.pixmap())
    if decoded is not None:
        assert decoded == "C0721817177;50,00;Fakturabunten;6"
    pp_decoded = _decode_pixmap_qr(dlg._lbl_paypal_qr.pixmap())
    if pp_decoded is not None:
        assert pp_decoded == "https://paypal.me/Rickard3dPrint/50SEK"

    dlg._custom_amount_edit.setText("125")
    dlg._custom_amount_edit.textEdited.emit("125")
    assert dlg._swish_payload == "C0721817177;125,00;Fakturabunten;6"
    assert dlg._btn_paypal.toolTip() == "https://paypal.me/Rickard3dPrint/125SEK"

    dlg._custom_amount_edit.setText("")
    dlg._custom_amount_edit.textEdited.emit("")
    assert dlg._swish_payload == "C0721817177;;Fakturabunten;6"
    assert dlg._btn_paypal.toolTip() == "https://paypal.me/Rickard3dPrint"
    dlg.reject()


def test_dialog_has_personal_message_and_optional_paypal_kofi_qr():
    _qapp()
    from PySide6.QtWidgets import QLabel
    from ui import i18n
    from ui.donate import DonateDialog

    for lang, needle in (("sv", "100 % gratis"), ("en", "100% free")):
        i18n.set_language(lang, notify=False)
        dlg = DonateDialog()
        dlg.show()
        _qapp().processEvents()

        story = dlg.findChild(QLabel, "DonateStoryBody")
        assert story is not None
        assert needle in story.text()

        # Valfri QR-vy för PayPal och Ko-fi är hopfälld från start och går att fälla ut
        assert dlg._web_qr_panel.isVisible() is False
        dlg._btn_toggle_web_qr.click()
        _qapp().processEvents()
        assert dlg._web_qr_panel.isVisible() is True

        pp_qr = dlg._lbl_paypal_qr.pixmap()
        kf_qr = dlg._lbl_kofi_qr.pixmap()
        assert pp_qr is not None and not pp_qr.isNull()
        assert kf_qr is not None and not kf_qr.isNull()
        pp_decoded = _decode_pixmap_qr(pp_qr)
        kf_decoded = _decode_pixmap_qr(kf_qr)
        if pp_decoded is not None:
            assert pp_decoded == "https://paypal.me/Rickard3dPrint"
        if kf_decoded is not None:
            assert kf_decoded == "https://ko-fi.com/tokke2"

        dlg._btn_toggle_web_qr.click()
        _qapp().processEvents()
        assert dlg._web_qr_panel.isVisible() is False

        # Hero CTA, Impact-kort, Trust-badges, FAQ-dragspel och Slut-CTA
        assert dlg.findChild(QLabel, "DonateTrustPill") is not None
        assert dlg.findChild(QLabel, "DonateImpactItemTitle") is not None
        assert dlg.findChild(QLabel, "DonateFooterTitle") is not None
        assert len(dlg._faq_items) == 4
        btn0, ans0, _ = dlg._faq_items[0]
        btn1, ans1, _ = dlg._faq_items[1]
        assert btn0.isChecked() is True and ans0.isVisible() is True
        assert btn1.isChecked() is False and ans1.isVisible() is False
        btn1.click()
        _qapp().processEvents()
        assert btn1.isChecked() is True and ans1.isVisible() is True
        btn1.click()
        _qapp().processEvents()
        assert btn1.isChecked() is False and ans1.isVisible() is False

        dlg._amount_buttons[100].click()
        assert dlg._btn_hero_paypal.toolTip() == "https://paypal.me/Rickard3dPrint/100SEK"
        assert dlg._btn_fc_paypal.toolTip() == "https://paypal.me/Rickard3dPrint/100SEK"
        dlg.reject()

    i18n.set_language("sv", notify=False)


def test_donate_menu_is_locked_and_has_no_separate_page():
    _qapp()
    from PySide6.QtWidgets import QMainWindow
    from ui import i18n
    from ui.donate import build_donate_menu

    win = QMainWindow()
    for lang, locked_needle in (("sv", "låst"), ("en", "locked")):
        i18n.set_language(lang, notify=False)
        menu = build_donate_menu(win)
        assert menu is not None
        actions = [a for a in menu.actions() if not a.isSeparator()]
        assert len(actions) == 5
        assert actions[-1].isEnabled() is False
        assert locked_needle in actions[-1].text().lower()
        assert all("0721817177" not in a.text() for a in actions)
    i18n.set_language("sv", notify=False)
    win.close()

    # Ingen separat webbsida ska läggas till i projektet
    assert not any(
        (PROJECT_DIR / name).exists()
        for name in ("stod.html", "donate.html", "support.html")
    )


def test_dialog_renders_in_dark_and_light_and_small_screens():
    _qapp()
    from PySide6.QtWidgets import QWidget
    from ui.donate import DonateDialog

    class _DarkHost(QWidget):
        _dark = True

    class _LightHost(QWidget):
        _dark = False

    for host in (_DarkHost(), _LightHost()):
        dlg = DonateDialog(host)
        dlg.resize(460, 480)
        dlg.show()
        _qapp().processEvents()
        assert dlg.width() >= 440
        dlg.reject()
        host.close()


def test_main_window_places_donations_dialog_under_help_menu(monkeypatch):
    _qapp()
    from PySide6.QtWidgets import QMainWindow
    from ui import i18n, main_window

    opened = []
    monkeypatch.setattr(main_window, "open_donate_dialog", lambda p=None: opened.append(p) or True)

    class _Settings:
        def get(self, _k, default=None):
            return default

    class _Win(main_window.MainWindow):
        def __init__(self):
            QMainWindow.__init__(self)
            self._settings = _Settings()
            self._hidden = {}
            self._custom_icon = None
            self._TAB_DEFS = ()

        def _shortcut_seq(self, _name, default):
            return default

        def _read_autostart_status(self):
            return False

    win = _Win()
    for lang, help_title, donate_label in (
        ("sv", "Hjälp", "Donationer"),
        ("en", "Help", "Donations"),
    ):
        i18n.set_language(lang, notify=False)
        win.menuBar().clear()
        win._build_menu_bar()
        menus = [act.text() for act in win.menuBar().actions()]
        assert any(help_title in text for text in menus), menus
        # Renare menyrad: ingen separat toppmeny för Stöd/Support
        assert not any(
            word in text for text in menus for word in ("Stöd", "Support")
        ), menus
        assert win._donate_menu is None
        help_actions = [a.text() for a in win._help_menu.actions() if not a.isSeparator()]
        assert any(donate_label in t for t in help_actions), help_actions
        assert donate_label in win._help_donate_action.text()
        assert "0721817177" not in i18n.tr(
            "about.body_html",
            app="Fakturabunten", version="1.0.0", year=2026,
            swish="", paypal=main_window.DONATE_PAYPAL, kofi=main_window.DONATE_BMC,
            platform="linux", python="3.11", autostart="off",
        )
    before = len(opened)
    win._help_donate_action.trigger()
    win._copy_swish()
    assert len(opened) == before + 2
    i18n.set_language("sv", notify=False)
    win.close()
