# -*- coding: utf-8 -*-
"""
Tester: Swish i donationsdialogen.

Riktiga numret (0721817177) bor i app.DONATE_SWISH (enda källan)
och QR-koden följer Swishs officiella C-format så den går att
skanna i Swish-appen: C<nummer>;<belopp>;<meddelande>;<mask 6>,
där numret är låst men belopp och meddelande är redigerbara —
som en donations-QR ska vara.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_swish_number_is_the_real_one():
    import app as core
    digits = "".join(c for c in core.DONATE_SWISH if c.isdigit())
    assert digits == "0721817177"


def test_payload_follows_official_swish_c_format():
    from ui.donate import (
        DONATE_SWISH_NUMBER, format_swish_number, swish_qr_payload,
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
    # +46-normalisering och meddelande URL-kodas
    assert swish_qr_payload(
        "+46 72 181 71 77", message="Tack så mycket!"
    ).startswith("C0721817177;;Tack%20s%C3%A5%20mycket%21;6")
    # Visningsformat
    assert format_swish_number("0721817177") == "072-181 71 77"


def test_dialog_shows_real_qr_pixmap():
    _qapp()
    from ui.donate import DonateDialog
    dlg = DonateDialog()
    assert dlg._lbl_swish_qr is not None
    pixmap = dlg._lbl_swish_qr.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.width() >= 100 and pixmap.height() >= 100
    dlg.reject()
