"""Small screens should keep dialogs and their action rows reachable."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _directory in (
    str(PROJECT_DIR), str(PROJECT_DIR / "ui"), str(PROJECT_DIR / "plugins")
):
    if _directory not in sys.path:
        sys.path.insert(0, _directory)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_fit_dialog_to_available_screen_clamps_size():
    from ui.design import fit_dialog_to_screen

    class _Geometry:
        def width(self):
            return 620

        def height(self):
            return 460

    class _Screen:
        def availableGeometry(self):
            return _Geometry()

    class _Dialog:
        def __init__(self):
            self.minimum = None
            self.size = None

        def screen(self):
            return _Screen()

        def setMinimumSize(self, width, height):
            self.minimum = (width, height)

        def resize(self, width, height):
            self.size = (width, height)

    dialog = _Dialog()
    assert fit_dialog_to_screen(
        dialog, 900, 800, minimum_width=700, minimum_height=700, margin=40
    ) == (580, 420)
    assert dialog.size == (580, 420)
    assert dialog.minimum == (580, 420)


def test_fit_dialog_keeps_preferred_size_when_screen_is_large():
    from ui.design import fit_dialog_to_screen

    class _Geometry:
        def width(self):
            return 1920

        def height(self):
            return 1080

    class _Screen:
        def availableGeometry(self):
            return _Geometry()

    class _Dialog:
        def screen(self):
            return _Screen()

        def setMinimumSize(self, width, height):
            self.minimum = (width, height)

        def resize(self, width, height):
            self.size = (width, height)

    dialog = _Dialog()
    assert fit_dialog_to_screen(
        dialog, 580, 620, minimum_width=460, minimum_height=430
    ) == (580, 620)
    assert dialog.minimum == (460, 430)
    assert dialog.size == (580, 620)
