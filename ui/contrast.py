from __future__ import annotations

"""
FakturaRäknaren — WCAG-kontrastverktyg
==============================================
Fil    : FakturaRäknaren_/ui/contrast.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Tillgänglighetskontroll enligt WCAG 2.1 (idén från PDF reader Pro
SPEC v2.1, punkt 2.6):

• relative_luminance() : W3C:s formel för relativ luminans
• contrast_ratio()     : kontrastförhåll mellan två färger (1–21)
• passes_aa()          : ≥ 4.5:1 (normal text, AA)
• passes_aa_large()    : ≥ 3.0:1 (stor text / UI-komponenter)
• best_text_on()       : väljer mest läsbara textfärg mot en bakgrund
• enforce_theme_contrast(): rättar ett tema så att viktiga par
                           håller AA-nivå — loggar CONTRAST_ADJUST

Används av main_window.resolve_theme() så att ALLA teman (även
framtida) garanterat är läsbara. Inga beroenden utöver stdlib.

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import logging

log = logging.getLogger("Theme")

COPYRIGHT: str = f"© {datetime.date.today().year} Rickard Längkvist"

#: Minsta tillåtna kontrastförhåll (WCAG AA, normal text).
MIN_RATIO: float = 4.5

#: Minsta kontrast för stor text / grafiska komponenter (WCAG AA).
MIN_RATIO_LARGE: float = 3.0

#: Universella fallback-färger (ren vit / ren svart — båda ger
#: maximal kontrast mot motsatt bakgrund).
FALLBACK_TEXT: tuple[str, ...] = ("#ffffff", "#000000")


# ═════════════════════════════════════════════════════════════════════
#  GRUND Funktioner
# ═════════════════════════════════════════════════════════════════════


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    """
    '#rrggbb' / 'rgb(r,g,b)' → (r, g, b).

    Kastar ValueError vid okänt format.
    """
    c = str(color).strip()
    if c.startswith("#"):
        h = c.lstrip("#")
        if len(h) == 3:                       # kortform #abc → #aabbcc
            h = "".join(ch * 2 for ch in h)
        if len(h) != 6:
            raise ValueError(f"Ogiltig hexfärg: {color!r}")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if c.lower().startswith("rgb"):
        inner = c[c.index("(") + 1 : c.rindex(")")]
        parts = [int(x.strip()) for x in inner.split(",")[:3]]
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
    raise ValueError(f"Ogiltigt färgformat: {color!r}")


def _channel(v: int) -> float:
    """Lineariserar en sRGB-kanal (0–255) enligt W3C."""
    s = v / 255.0
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """Relativ luminans 0.0 (svart) – 1.0 (vitt) enligt WCAG 2.1."""
    r, g, b = hex_to_rgb(color)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(color_a: str, color_b: str) -> float:
    """
    Kontrastförhåll mellan två färger (1.0 – 21.0).

    Ordningen spelar ingen roll: ratio(a, b) == ratio(b, a).
    """
    try:
        la = relative_luminance(color_a)
        lb = relative_luminance(color_b)
    except ValueError:
        return 1.0
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def passes_aa(bg: str, fg: str) -> bool:
    """True om paret klarar WCAG AA för normal text (≥ 4.5:1)."""
    return contrast_ratio(bg, fg) >= MIN_RATIO


def passes_aa_large(bg: str, fg: str) -> bool:
    """True om paret klarar WCAG AA för stor text (≥ 3.0:1)."""
    return contrast_ratio(bg, fg) >= MIN_RATIO_LARGE


def best_text_on(bg: str, candidates: tuple[str, ...] = FALLBACK_TEXT) -> str:
    """Returnerar den kandidatfärg med högst kontrast mot bakgrunden."""
    best = candidates[0]
    best_ratio = -1.0
    for c in candidates:
        r = contrast_ratio(bg, c)
        if r > best_ratio:
            best, best_ratio = c, r
    return best


# ═════════════════════════════════════════════════════════════════════
#  TEMA-VALIDERING
# ═════════════════════════════════════════════════════════════════════

#: (bakgrundsnyckel, textnycklar som måste vara läsbara mot den)
_THEME_PAIRS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bg",            ("text", "text_strong")),
    ("bg_secondary",  ("text", "text_strong")),
    ("card_bg",       ("text", "text_strong")),
    ("input_bg",      ("text_strong",)),
    ("menu_bg",       ("menu_text",)),
    ("tooltip_bg",    ("tooltip_text",)),
)


def enforce_theme_contrast(theme: dict) -> dict:
    """
    Säkerställer att temats textfärger håller WCAG AA mot sina
    bakgrunder. Returnerar en KPIA av temat med rättade färger.

    • Klarar paret redan ≥ 4.5:1 → oförändrat.
    • Annars byts textfärgen till vit/svart — den som ger bäst
      kontrast — och en CONTRAST_ADJUST-rad loggas.
    """
    out = dict(theme)
    for bg_key, text_keys in _THEME_PAIRS:
        bg = out.get(bg_key)
        if not bg:
            continue
        for text_key in text_keys:
            fg = out.get(text_key)
            if not fg:
                continue
            if passes_aa(bg, fg):
                continue
            new_fg = best_text_on(bg)
            ratio_before = round(contrast_ratio(bg, fg), 2)
            ratio_after = round(contrast_ratio(bg, new_fg), 2)
            out[text_key] = new_fg
            log.info(
                "CONTRAST_ADJUST: %s på %s %s → %s  "
                "(ratio %.2f → %.2f, krav ≥ %.1f)",
                text_key, bg_key, fg, new_fg,
                ratio_before, ratio_after, MIN_RATIO,
            )
    return out


# ═════════════════════════════════════════════════════════════════════
#  SELF-TEST  (python ui/core/contrast.py)
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("WCAG-kontrastverktyg — självtest")
    print(f"  {COPYRIGHT}")
    print(f"  svart/vit ratio : {contrast_ratio('#000000', '#ffffff'):.2f}  (ska vara 21.00)")
    print(f"  vit/vit   ratio : {contrast_ratio('#ffffff', '#ffffff'):.2f}  (ska vara 1.00)")
    print(f"  AA-koll  #0d1117/#c9d1d9 : {passes_aa('#0d1117', '#c9d1d9')}")
    print(f"  AA-koll  #ffffff/#d0d7de : {passes_aa('#ffffff', '#d0d7de')}  (ska vara False)")
    print(f"  Bästa text på #0969da    : {best_text_on('#0969da')}")
    t = enforce_theme_contrast(
        {"bg": "#ffffff", "text": "#d0d7de", "text_strong": "#24292f"}
    )
    print(f"  Reparerat tema-text      : {t['text']}")
    print("✅  klart")
