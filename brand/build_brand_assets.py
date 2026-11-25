# -*- coding: utf-8 -*-
"""Bygger om Fakturabunten-märket (v2, städad stack + guldfält + bocksegl)
i alla varianter. Körs med appens venv:  python brand/build_brand_assets.py

Märket: städad fakturastack (tre ark i jämn visp) med tydligt
totalstreck i guld och en guldringförsänglad bocksegl — samma
färgpalett (#16305a / #e0a526 / papper) som varumärket kräver.

Producerar:
  app_icon.svg                        vektormärket (512)
  brand/fakturabunten-ikon.svg        varumärkesversion (samma banor)
  brand/fakturabunten-ikon-monokrom.svg  siluett med vita detaljer
  brand/fakturabunten-ikon-tryck-bleed.svg  604×604 med 5 mm bleed
  app_icon.png                        1024×1024 RGBA (ur SVG:n)
  app_icon.ico                        16/20/24/32/48/64/128/256
  app_icon_tray.png                   svart siluett (macOS-menylinje)
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf
from PIL import Image

PROJECT = str(Path(__file__).resolve().parent.parent)

# ── Märkets geometri (delad av alla varianter) ──────────────────────
FRONT = (
    "M176 100H314L384 170V396A28 28 0 0 1 356 424H176"
    "A28 28 0 0 1 148 396V128A28 28 0 0 1 176 100Z"
)
FOLD = "M314 100L384 170H314Z"
CHECK = "M334 372l20 22 36-42"
BACK = '<g transform="rotate(-7 230 282)"><rect x="124" y="148" width="212" height="268" rx="18" fill="{c}"/></g>'
MID = '<g transform="rotate(-3 244 270)"><rect x="138" y="134" width="212" height="272" rx="18" fill="{c}"/></g>'
CONTENT = (
    '<g fill="#16305a">'
    '<rect x="182" y="138" width="112" height="32" rx="9"/>'
    '<rect x="182" y="190" width="150" height="24" rx="8"/>'
    '<rect x="182" y="228" width="118" height="24" rx="8"/>'
    '</g>'
)
TOTAL = '<rect x="182" y="282" width="168" height="36" rx="9" fill="#e0a526"/>'


def mark_body(plate: str = "#16305a", gold: str = "#e0a526") -> str:
    """Färgade märket (512×512-ruta), delad av app-/brand-ikon."""
    return (
        f'<rect x="10" y="10" width="492" height="492" rx="116" fill="{plate}"/>'
        + BACK.format(c="#c6d8ee")
        + MID.format(c="#e4eefb")
        + f'<path d="{FRONT}" fill="#ffffff"/>'
        + f'<path d="{FOLD}" fill="#cbdcef"/>'
        + CONTENT
        + TOTAL
        + f'<circle cx="362" cy="372" r="50" fill="#ffffff" stroke="{gold}" stroke-width="12"/>'
        + f'<path d="{CHECK}" fill="none" stroke="#16305a" stroke-width="17" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )


def mono_body() -> str:
    """Monokrom siluett (tryck/menylines): svarta former, vita detaljer."""
    return (
        '<g transform="translate(0 -4)">'
        + BACK.format(c="#000000").replace('fill="#000000"', 'fill="#000000" opacity="0.5"')
        + MID.format(c="#000000").replace('fill="#000000"', 'fill="#000000" opacity="0.75"')
        + f'<path d="{FRONT}" fill="#000000"/>'
        + f'<path d="{FOLD}" fill="#ffffff"/>'
        + CONTENT.replace("#16305a", "#ffffff")
        + '<circle cx="362" cy="372" r="50" fill="#ffffff"/>'
        + f'<path d="{CHECK}" fill="none" stroke="#000000" stroke-width="17" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '</g>'
    )


def tray_body() -> str:
    """Helsvart siluett (macOS-menylinje): former utan detaljer."""
    return (
        '<g transform="translate(0 -4)">'
        + BACK.format(c="#000000")
        + MID.format(c="#000000")
        + f'<path d="{FRONT}" fill="#000000"/>'
        + '<circle cx="362" cy="372" r="56" fill="#000000"/>'
        '</g>'
    )


def svg(viewbox: int, body: str, title: str, label: str,
        extra_open: str = "", extra_close: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {viewbox} {viewbox}" '
        f'width="{viewbox}" height="{viewbox}" role="img" aria-label="{label}">\n'
        f'  <title>{title}</title>\n'
        f'{extra_open}'
        f'{body}\n'
        f'{extra_close}'
        '</svg>\n'
    )


# ── Filerna ──────────────────────────────────────────────────────────
app_icon_svg = svg(
    512, mark_body(),
    "Fakturabunten — appikon", "Fakturabunten",
    extra_open=(
        "  <!-- Vektorversion av appikonen (samma motiv som app_icon.png/.ico).\n"
        "       Redigera hellre brand/fakturabunten-ikon.svg och kopiera hit. -->\n"
    ),
)
brand_svg = svg(
    512, mark_body(), "Fakturabunten", "Fakturabunten",
)
mono_svg = svg(
    512, mono_body(),
    "Fakturabunten — monokrom ikon (systemfält/menylinje)",
    "Fakturabunten (monokrom)",
    extra_open=(
        "  <!-- Används där OS:et själv färgar ikonen (macOS-menylinjen):\n"
        "       svart siluett med vita detaljer; PNG:en för menylinjen är\n"
        "       den rena helsvarta varianten (app_icon_tray.png). -->\n"
    ),
)
bleed_inner = (
    '<rect x="0" y="0" width="604" height="604" fill="#16305a"/>\n'
    '<g transform="translate(46 46)">\n'
    + mark_body() + "\n"
    + "</g>"
)
bleed_svg = svg(
    604, bleed_inner,
    "Fakturabunten — ikon för tryck (5 mm bleed)",
    "Fakturabunten — tryckfil med bleed",
)

with open(f"{PROJECT}/app_icon.svg", "w", encoding="utf-8") as fh:
    fh.write(app_icon_svg)
with open(f"{PROJECT}/brand/fakturabunten-ikon.svg", "w", encoding="utf-8") as fh:
    fh.write(brand_svg)
with open(f"{PROJECT}/brand/fakturabunten-ikon-monokrom.svg", "w", encoding="utf-8") as fh:
    fh.write(mono_svg)
with open(f"{PROJECT}/brand/fakturabunten-ikon-tryck-bleed.svg", "w", encoding="utf-8") as fh:
    fh.write(bleed_svg)


# ── Logotyperna: byt märkesgruppen, behåll ord bildens banor ────────
import re as _re

LOGO_MARK_OPEN = '  <g transform="translate(28 30) scale(0.46875)">\n'
#: Ord-bildens grupp är unik per logotyp (translate 312,176).
_WORDMARK_RE = _re.compile(
    r'^  <g fill="[^"]+" transform="translate\(312\.00 176\.00\)">$',
    _re.MULTILINE,
)


def _logo_mark_body(name: str) -> str:
    if "svartvit" in name:
        return mono_body()
    if "mork-bakgrund" in name:
        return mark_body(plate="#24467c", gold="#f0c24a")
    return mark_body()


def update_logotype(name: str) -> None:
    path = Path(PROJECT) / "brand" / name
    text = path.read_text(encoding="utf-8")
    start = text.index(LOGO_MARK_OPEN) + len(LOGO_MARK_OPEN)
    m = _WORDMARK_RE.search(text, start)
    assert m is not None, name
    end = m.start()
    # Mellan start och ord-bilden ligger märkesgruppens avslutande </g>.
    tail = text[start:end]
    assert tail.rstrip().endswith("</g>"), name
    new = (
        text[:start]
        + _logo_mark_body(name) + "\n"
        + "  </g>\n"
        + text[end:]
    )
    import xml.etree.ElementTree as ET

    ET.fromstring(new)  # välformad XML
    path.write_text(new, encoding="utf-8")
    print("uppdaterad:", name)


for _logo in ("fakturabunten-logotyp.svg",
              "fakturabunten-logotyp-mork-bakgrund.svg",
              "fakturabunten-logotyp-svartvit.svg"):
    update_logotype(_logo)


# ── Raster ur vektorn ────────────────────────────────────────────────
def render(svg_text: str, px: int, alpha: bool = True) -> Image.Image:
    """Renderar SVG-text till PIL-bild (MuPDF, mjukvara — ingen GPU)."""
    doc = pymupdf.open(stream=svg_text.encode("utf-8"), filetype="svg")
    page = doc[0]
    scale = px / page.rect.width
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), alpha=alpha, annots=False,
    )
    img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    doc.close()
    return img


# app_icon.png — 1024×1024 RGBA
png = render(app_icon_svg, 1024)
png.save(f"{PROJECT}/app_icon.png")
print("app_icon.png:", png.size, png.mode)

# app_icon.ico — flera storlekar i en fil
png.save(
    f"{PROJECT}/app_icon.ico",
    format="ICO",
    sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48),
           (64, 64), (128, 128), (256, 256)],
)
print("app_icon.ico skrivet")

# app_icon_tray.png — helsvart siluett (128 px, >= 64 krävs)
tray = render(svg(512, tray_body(), "t", "t"), 128)
tray.save(f"{PROJECT}/app_icon_tray.png")
print("app_icon_tray.png:", tray.size)

# ── Självkontroller enligt tests/test_brand_assets.py ────────────────
chk = Image.open(f"{PROJECT}/app_icon.png")
assert chk.size == (1024, 1024) and chk.mode == "RGBA"
assert chk.getpixel((2, 2))[3] == 0, "hörnet ska vara genomskinligt"
assert chk.getpixel((512, 512))[3] > 0, "mitten ska vara ogenomskinlig"
ico = Image.open(f"{PROJECT}/app_icon.ico")
have = ico.info.get("sizes", set())
assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= have, have
traychk = Image.open(f"{PROJECT}/app_icon_tray.png").convert("RGBA")
assert traychk.size[0] >= 64
bad = [
    (r, g, b) for r, g, b, a in traychk.get_flattened_data()
    if a > 8 and not (r < 8 and g < 8 and b < 8)
]
assert not bad, f"icke-svarta pixlar i tray: {bad[:3]}"
app_txt = open(f"{PROJECT}/app_icon.svg", encoding="utf-8").read()
brand_txt = open(f"{PROJECT}/brand/fakturabunten-ikon.svg", encoding="utf-8").read()
assert app_txt.count("<path") == brand_txt.count("<path")
assert "#16305a" in app_txt and "#e0a526" in app_txt
for name in ("fakturabunten-ikon.svg", "fakturabunten-ikon-monokrom.svg",
             "fakturabunten-ikon-tryck-bleed.svg"):
    t = open(f"{PROJECT}/brand/{name}", encoding="utf-8").read()
    assert "<text" not in t.lower() and "<image" not in t.lower()
    assert t.count("<path") >= 2 and 'viewBox="' in t
    ET.fromstring(t)  # välformad XML
print("Alla självlundingar OK")
