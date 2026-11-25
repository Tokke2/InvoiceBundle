# -*- coding: utf-8 -*-
"""
Tester: utökat vektorikonset (v2) i ui/icons.py.

Nya ikoner (shield_check, bank, qr, scan, scissors, bell, eye_off,
filter, sliders, printer, share, send, mail, users, gauge,
trending_up/down, pie, hash, percent, lock, cpu, package,
calendar_check/x, x_circle, banknote) följer samma 24×24
linjedragsregler som övriga bibliotek: giltig geometri i 24-rutan,
ingen rasterbild, ingen text-element, och de färgas av temat via
stroke="currentColor" (ingen hårdkodad ikonfärg i geometrin).

Källnivåtesterna läser _SVG_PATHS via AST (ingen Qt-import krävs —
modulen importerar PySide6 och kan inte laddas i miljöer utan
systembibliotek). Djuptestet renderar via _VectorIconEngine och
skippar där Qt inte kan importeras.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

NEW_ICONS = (
    "shield_check", "bank", "banknote", "qr", "scan", "scissors",
    "bell", "eye_off", "filter", "sliders", "printer", "share",
    "send", "mail", "users", "gauge", "trending_up", "trending_down",
    "pie", "hash", "percent", "lock", "cpu", "package",
    "calendar_check", "calendar_x", "x_circle",
)


def _icon_paths() -> dict[str, str]:
    """Parsar _SVG_PATHS ur källkoden via AST (Qt-fri)."""
    source = (PROJECT_DIR / "ui" / "icons.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        target_id = None
        if isinstance(node, ast.Assign) and node.targets:
            target_id = getattr(node.targets[0], "id", None)
        elif (isinstance(node, ast.AnnAssign)
              and isinstance(node.target, ast.Name)):
            target_id = node.target.id
        if target_id == "_SVG_PATHS" and isinstance(node.value, ast.Dict):
            out: dict[str, str] = {}
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and isinstance(
                    value, ast.Constant
                ):
                    out[str(key.value)] = str(value.value)
            return out
    raise AssertionError("_SVG_PATHS hittades inte i ui/icons.py")


_SVG_ELEMENT_RE = re.compile(r"<[a-z]+")


def test_new_icon_names_exist_in_library():
    paths = _icon_paths()
    for name in NEW_ICONS:
        assert name in paths, name


def test_library_is_large_after_expansion():
    assert len(_icon_paths()) >= 75


def test_new_icons_are_24_viewbox_line_art():
    paths = _icon_paths()
    for name in NEW_ICONS:
        body = paths[name]
        assert "<image" not in body, name
        assert "<text" not in body, name
        # Geometrin ligger i 24×24-koordinater (renderas med
        # viewBox="-1 -1 26 26") — alla tal inom [-26, 26].
        numbers = [abs(float(v)) for v in
                   re.findall(r"-?\d+(?:\.\d+)?", body)]
        assert numbers, name
        assert max(numbers) <= 26, f"{name}: koordinat utanför 24-rutan"
        # Minst ett ritelement.
        assert _SVG_ELEMENT_RE.search(body), name


def test_no_icon_carries_a_hardcoded_paint_color():
    """Färgsättningen ska ske via stroke='{color}'-ersättningen."""
    paths = _icon_paths()
    for name, body in paths.items():
        # 'currentColor' tillåts (ersätts av _svg_markup); färgliteraler
        # i geometrin skulle bryta temafärgningen.
        for color in ("#000", "#fff", "black", "white"):
            assert color.lower() not in body.lower(), name


def test_icon_markup_renders_as_valid_svg_for_new_names():
    pytest = __import__("pytest")
    try:
        import xml.etree.ElementTree as ET

        import ui.icons as icons  # kräver PySide6
    except ImportError as exc:  # Qt saknas i miljön (t.ex. libGL)
        pytest.skip(f"ui.icons kräver Qt: {exc}")

    for name in NEW_ICONS:
        markup = icons._svg_markup(name, "#ffffff")
        ET.fromstring(markup)  # välformad XML
        assert 'stroke="#ffffff"' in markup


def test_icon_engine_renders_new_names_distinctly():
    """Djuptest: ikonerna renderar och skiljer sig åt (Normal vs Disabled)."""
    pytest = __import__("pytest")
    try:
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        from ui.icons import vector_icon
    except ImportError as exc:  # libGL m.m.
        pytest.skip(f"QtWidgets ej importerbar i denna miljö: {exc}")

    for name in NEW_ICONS[:6]:
        ico = vector_icon(name, color="#ffffff", size=16)
        pm = ico.pixmap(QSize(16, 16), QIcon.Mode.Normal)
        pm_d = ico.pixmap(QSize(16, 16), QIcon.Mode.Disabled)
        assert not pm.isNull(), name
        assert pm.toImage() != pm_d.toImage(), name
