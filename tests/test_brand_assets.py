# -*- coding: utf-8 -*-
"""
Tester: ny ikon/logotyp (vektor för tryck) och systemfält per OS.

Kraven:
  • ikonen och logotypen ska finnas som riktig vektorgrafik (SVG) med
    banor — inga inbäddade typsnitt — så de kan användas för tryck,
  • logotypen ska finnas för ljus bakgrund, mörk bakgrund och svartvitt,
  • appikonens PNG/ICO ska vara byggda ur samma motiv,
  • systemfältets ikon ska väljas per OS (monokrom mask på macOS,
    färgad på Windows/Linux),
  • appens typsnitt ska väljas ur det som faktiskt finns installerat.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (
    str(PROJECT_DIR),
    str(PROJECT_DIR / "ui"),
    str(PROJECT_DIR / "plugins"),
):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import pytest  # noqa: E402


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


BRAND_SVGS = (
    "fakturabunten-ikon.svg",
    "fakturabunten-ikon-tryck-bleed.svg",
    "fakturabunten-ikon-monokrom.svg",
    "fakturabunten-logotyp.svg",
    "fakturabunten-logotyp-mork-bakgrund.svg",
    "fakturabunten-logotyp-svartvit.svg",
)


# ── Vektorgrafik för tryck ──────────────────────────────────────────

@pytest.mark.parametrize("name", BRAND_SVGS)
def test_brand_svg_is_real_vector_without_embedded_fonts(name):
    path = PROJECT_DIR / "brand" / name
    assert path.is_file(), name
    text = path.read_text(encoding="utf-8")

    # Ingen typsnittsberoende text och inga rasterbilder i filen.
    assert "<text" not in text.lower()
    assert "@font-face" not in text.lower()
    assert "<image" not in text.lower()
    # Riktiga vektorbanor + viewBox = skalbart för tryck.
    assert text.count("<path") >= 2
    assert 'viewBox="' in text
    assert 'xmlns="http://www.w3.org/2000/svg"' in text


@pytest.mark.parametrize("name", BRAND_SVGS)
def test_brand_svg_renders_with_qt(name):
    _qapp()
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(PROJECT_DIR / "brand" / name))
    assert renderer.isValid(), name
    size = renderer.defaultSize()
    assert size.width() > 0 and size.height() > 0


def test_print_version_has_bleed_around_the_mark():
    text = (
        PROJECT_DIR / "brand" / "fakturabunten-ikon-tryck-bleed.svg"
    ).read_text(encoding="utf-8")
    viewbox = re.search(r'viewBox="0 0 (\d+) (\d+)"', text)
    assert viewbox is not None
    width, height = int(viewbox.group(1)), int(viewbox.group(2))
    # 512 enheter = 56 mm → 5 mm bleed blir ca 46 enheter per sida.
    assert width == height
    assert width >= 512 + 2 * 40


def test_logotype_has_wordmark_and_tagline_as_paths():
    text = (
        PROJECT_DIR / "brand" / "fakturabunten-logotyp.svg"
    ).read_text(encoding="utf-8")
    assert text.count("<path") > 12  # ordbild + underrad, bokstav för bokstav
    assert "#12284b" in text          # ordbildens marinblå
    assert "#8a6b12" in text          # underradens mörka guld


# ── Appikonerna ─────────────────────────────────────────────────────

def test_app_icons_are_built_from_the_same_mark():
    from PIL import Image

    png = Image.open(PROJECT_DIR / "app_icon.png")
    assert png.size == (1024, 1024) and png.mode == "RGBA"
    assert png.getpixel((2, 2))[3] == 0        # genomskinligt hörn
    assert png.getpixel((512, 512))[3] > 0     # motiv i mitten

    ico = Image.open(PROJECT_DIR / "app_icon.ico")
    sizes = ico.info.get("sizes", set())
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes

    svg = (PROJECT_DIR / "app_icon.svg").read_text(encoding="utf-8")
    brand = (
        PROJECT_DIR / "brand" / "fakturabunten-ikon.svg"
    ).read_text(encoding="utf-8")
    # Samma motiv: ikonens SVG är varumärkesfilen (med egen titel).
    assert "#16305a" in svg and "#e0a526" in svg
    assert svg.count("<path") == brand.count("<path")


def test_tray_icon_is_monochrome_for_macos_menu_bar():
    from PIL import Image

    tray = Image.open(PROJECT_DIR / "app_icon_tray.png").convert("RGBA")
    assert tray.size[0] >= 64
    # Monokrom: alla synliga pixlar är svarta (alfan bär formen), så
    # macOS kan färga ikonen själv i ljust/mörkt läge.
    for r, g, b, a in tray.get_flattened_data():
        if a > 8:
            assert r < 8 and g < 8 and b < 8


def test_brand_files_are_part_of_the_release_package():
    import build_release as br

    for name in BRAND_SVGS:
        rel = f"brand/{name}"
        assert rel in br.RELEASE_FILES, rel
        assert (PROJECT_DIR / rel).is_file(), rel
    assert "brand/README.md" in br.RELEASE_FILES
    assert "app_icon_tray.png" in br.RELEASE_FILES
    assert br.validate_release_files(PROJECT_DIR) == []


# ── Per OS: ikon, typsnitt, systemfält ──────────────────────────────

def test_tray_icon_uses_mask_only_on_macos(monkeypatch):
    _qapp()
    from ui import design

    monkeypatch.setattr(design, "current_platform", lambda: "macos")
    icon = design.tray_icon()
    assert icon is not None and not icon.isNull()
    assert icon.isMask() is True

    monkeypatch.setattr(design, "current_platform", lambda: "windows")
    win_icon = design.tray_icon()
    assert win_icon is not None and not win_icon.isNull()
    assert win_icon.isMask() is False

    monkeypatch.setattr(design, "current_platform", lambda: "linux")
    linux_icon = design.tray_icon()
    assert linux_icon is not None and not linux_icon.isNull()


def test_logotype_pixmap_scales_the_vector():
    _qapp()
    from ui.design import logotype_pixmap

    pix = logotype_pixmap(440)
    assert not pix.isNull()
    assert pix.width() == 440
    # Liggande logotyp: bredden är klart större än höjden.
    assert pix.width() > pix.height() * 2

    dark = logotype_pixmap(300, dark_background=True)
    assert not dark.isNull()
    assert dark.width() == 300


def test_font_family_is_one_that_is_installed():
    _qapp()
    from ui import design

    family = design.ui_font_family()
    assert family, "ingen typsnittsfamilj vald"
    installed = design.installed_font_families()
    if installed:
        assert family in installed
    # Varje plattform har en egen kedja — ingen hårdkodad "Segoe UI".
    assert "Segoe UI" in design.FONT_STACKS["windows"][0]
    assert ".AppleSystemUIFont" in design.FONT_STACKS["macos"]
    assert "Noto Sans" in design.FONT_STACKS["linux"]


def test_make_font_uses_the_platform_chain():
    _qapp()
    from ui.invoices_helpers import make_font

    font = make_font(12, bold=True)
    assert font.bold() is True
    assert font.family()
