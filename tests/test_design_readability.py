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


def test_font_choice_before_qapplication_does_not_abort():
    """Import av ui.main_window utan QApplication får inte krascha.

    QFontDatabase avbryter processen om den anropas innan appen finns;
    typsnittsvalet måste därför kontrollera instansen först. Körs i en
    egen process eftersom felet är en abort, inte en Python-undantag.
    """
    import subprocess

    script = (
        "import ui.design as d;"
        "assert d.installed_font_families() == set();"
        "name = d.ui_font_family();"
        "assert isinstance(name, str) and name;"
        "import ui.main_window;"
        "print('ok')"
    )
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(PROJECT_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "ok" in proc.stdout


def test_history_view_has_single_apply_theme_and_updates_styles():
    """#13: HistoryView.apply_theme ska inte vara dubblerad/skuggad och ska
    styla räknarchip, tomläge, sökfält, filter och tabell i båda temana."""
    import ast
    from ui.history_view import HistoryView
    from ui.main_window import THEMES

    tree = ast.parse((PROJECT_DIR / "ui" / "history_view.py").read_text("utf-8"))
    hv_cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "HistoryView"
    )
    apply_defs = [
        n for n in hv_cls.body
        if isinstance(n, ast.FunctionDef) and n.name == "apply_theme"
    ]
    assert len(apply_defs) == 1, f"Förväntade 1 apply_theme, hittade {len(apply_defs)}"

    app = _qapp()

    class _HistApp:
        def get_archived_invoices(self):
            return []

    hv = HistoryView(_HistApp())
    try:
        hv.apply_theme(THEMES["light"])
        assert THEMES["light"]["tab_selected"] in hv._lbl_count.styleSheet()
        assert THEMES["light"]["text_muted"] in hv._lbl_empty.styleSheet()
        assert "rgba(255, 255, 255, 0.18)" in hv._table.styleSheet()

        hv.apply_theme(THEMES["dark"])
        assert THEMES["dark"]["tab_selected"] in hv._lbl_count.styleSheet()
        assert THEMES["dark"]["text_muted"] in hv._lbl_empty.styleSheet()
        assert THEMES["dark"]["header_bg"] in hv._table.styleSheet()
    finally:
        hv.close()
        hv.deleteLater()
        app.processEvents()


def test_sharper_design_stylesheet_and_no_hardcoded_muted_grey():
    """GroupBox-titlar smälter in i bg_secondary, tabellrubriker har diskreta
    avgränsare och ScanImportView/InvoiceDialog saknar hårdkodad #8b949e."""
    from ui.main_window import THEMES, build_stylesheet

    for mode in ("dark", "light"):
        t = THEMES[mode]
        css = build_stylesheet(t)
        assert f"background          : {t['bg_secondary']};" in css
        assert "border-right     : 1px solid rgba(255, 255, 255, 0.18);" in css
        assert "QPushButton:focus" in css
        assert "QTableWidget:focus, QTableView:focus" in css

    scan_src = (PROJECT_DIR / "ui" / "scan_import_view.py").read_text("utf-8")
    assert "color:#8b949e" not in scan_src
    helpers_src = (PROJECT_DIR / "ui" / "invoices_helpers.py").read_text("utf-8")
    assert "color:#8b949e" not in helpers_src

    app = _qapp()
    from PySide6.QtWidgets import QHeaderView
    from ui.dashboard_view import DashboardView

    dash = DashboardView(_FakeApp())
    try:
        hh = dash._table.horizontalHeader()
        assert hh.sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch
        assert not hh.stretchLastSection()
    finally:
        dash.close()
        dash.deleteLater()
        app.processEvents()
