# -*- coding: utf-8 -*-
"""
Tester: läsbarhetskraven från designpassagen.

All text ska vara väl synlig i båda temana: stark (fet) svart
text mot ljus bakgrund och vit text mot mörk bakgrund. Vi mäter
med appens egen WCAG-kontrastmodul (ui/contrast.py) och kräver
minst 7:1 för brödtext och 4,5:1 för flikar — samt att
Dashboard-korten byter variant med temat.
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

from ui.contrast import contrast_ratio


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_theme_text_contrast_both_themes():
    from ui.main_window import THEMES
    for name in ("dark", "light"):
        t = THEMES[name]
        # Starka texten mot båda bakgrunderna: minst AAA-riktvärde 7:1
        assert contrast_ratio(t["text_strong"], t["bg"]) >= 7.0, name
        assert contrast_ratio(t["text_strong"], t["bg_secondary"]) >= 7
        # Vanlig text och fliktext: minst AA 4,5:1
        assert contrast_ratio(t["text"], t["bg"]) >= 4.5, name
        assert contrast_ratio(t["tab_text"], t["tab_bg"]) >= 4.5, name
        assert contrast_ratio(t["button_text"], t["button_bg"]) >= 7, name


def test_stylesheet_uses_bigger_bold_types():
    from ui.main_window import THEMES, build_stylesheet
    css = build_stylesheet(THEMES["light"])
    assert "font-size   : 14px" in css                 # grundstorlek
    assert "font-size     : 15px" in css               # flikar
    assert "QLabel {" in css and "font-weight : 600" in css
    css_dark = build_stylesheet(THEMES["dark"])
    assert "#0d1218" in build_stylesheet(THEMES["light"])
    assert "#ffffff" in css_dark                        # vit stark text


class _FakeApp:
    def get_invoices(self):
        return []

    def get_suppliers(self):
        return [{"name": "Pilkington"}]


def test_dashboard_cards_follow_theme():
    _qapp()
    from ui.dashboard_view import DashboardView
    view = DashboardView(_FakeApp())
    view.apply_theme({"name": "dark"})
    dark_value = view._card_pay._value.styleSheet()
    assert "#d4a017" in dark_value and "26px" in dark_value
    view.apply_theme({"name": "light"})
    light_value = view._card_pay._value.styleSheet()
    assert "#0f2140" in light_value                    # marinblå på vitt
    assert "#ffffff" in view._card_pay.styleSheet()    # vit kortbotten
    assert "#b3261e" in view._card_overdue._value.styleSheet()
    assert "font-size:13px" in view._lbl_hint.styleSheet()
