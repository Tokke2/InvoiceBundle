from __future__ import annotations

"""
FakturaRäknaren — Scan Import Plugin
==========================================
Fil    : FakturaRäknaren_/plugins/scan_import.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Läser in skannade fakturor (PDF/bild) och föreslår fält som sedan
bekräftas i Import-fliken innan fakturan registreras. Appens kärna
är oförändrad: ange fakturor → räkna ihop ATT BETALA. Inläsningen
är bara en snabbväg in till samma registrering.

Textkällor (i prioritetsordning, alla valfria beroenden):
    1. PDF med textlager   → pypdf (eller PyMuPDF som andrahandsval)
    2. Skannad bild/PDF    → Tesseract OCR (pytesseract, swe+eng)
    3. Manuell fallback    → klistra in text själv (alltid möjligt)

Tolkning (svenska fakturor):
    • ATT BETALA / TOTALT / SUMMA → belopp (största beloppet annars)
    • Fakturanr / Fakturanummer    → fakturanummer
    • Fakturadatum / Förfallodatum → datum (flera format)
    • OCR                          → OCR-nummer
    • Leverantör                   → matchas mot kända leverantörer
                                     (namn / org.nr / bg / pg)

Allt presenteras redigerbart i Import-fliken — inget sparas utan
användarens bekräftelse. Loggas som SCAN_IMPORT.

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("ScanImport")

# ── Valfria beroenden (fail-safe) ──────────────────────────────────────
HAS_PYPDF = False
try:
    from pypdf import PdfReader  # type: ignore

    HAS_PYPDF = True
except Exception:
    pass

HAS_FITZ = False
try:
    import fitz  # type: ignore  # PyMuPDF

    HAS_FITZ = True
except Exception:
    pass

HAS_TESS = False
try:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore

    HAS_TESS = True
except Exception:
    pass

COPYRIGHT_YEAR: int = datetime.date.today().year

#: Filtyper som kan läsas in
SCAN_EXTENSIONS: tuple[str, ...] = (
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
)


# ═════════════════════════════════════════════════════════════════════
#  TEXTEXTRAKTION
# ═════════════════════════════════════════════════════════════════════


def extract_pdf_text(path: Path) -> tuple[str, str]:
    """
    Extraherar text ur en PDF.

    Returnerar (text, metod) där metod är "textlager-pypdf",
    "textlager-pymupdf" eller ("", "saknas-stöd") vid fel.
    """
    if HAS_PYPDF:
        try:
            reader = PdfReader(str(path))
            parts = [p.extract_text() or "" for p in reader.pages]
            text = "\n".join(parts).strip()
            if text:
                return text, "textlager-pypdf"
        except Exception as exc:
            log.warning("pypdf: %s", exc)
    if HAS_FITZ:
        try:
            with fitz.open(str(path)) as doc:
                text = "\n".join(
                    p.get_text() for p in doc  # type: ignore
                ).strip()
            if text:
                return text, "textlager-pymupdf"
        except Exception as exc:
            log.warning("pymupdf: %s", exc)
    return "", "ingen-pdf-läsare"


def extract_image_text(path: Path) -> tuple[str, str]:
    """OCR av bild via Tesseract (swe+eng). ('', 'ocr-saknas') vid fel."""
    if not HAS_TESS:
        return "", "ocr-saknas"
    try:
        img = Image.open(str(path))
        text = pytesseract.image_to_string(img, lang="swe+eng")
        return (text or "").strip(), "ocr-tesseract"
    except Exception as exc:
        log.warning("tesseract: %s", exc)
        return "", "ocr-fel"


def extract_scanned_pdf_pages(path: Path) -> tuple[str, str]:
    """
    OCR av skannad PDF (inga textlager): renderar sidor till bild
    via PyMuPDF och OCR:ar dem med Tesseract.
    """
    if not (HAS_FITZ and HAS_TESS):
        return "", "ocr-saknas"
    try:
        texts: list[str] = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=300)
                img = Image.open(
                    __import__("io").BytesIO(pix.tobytes("png"))
                )
                texts.append(
                    pytesseract.image_to_string(img, lang="swe+eng")
                )
        return "\n".join(texts).strip(), "ocr-tesseract-pdf"
    except Exception as exc:
        log.warning("scannad pdf-ocr: %s", exc)
        return "", "ocr-fel"


def extract_text(path: Path) -> tuple[str, str]:
    """
    Huvudingång: väljer extraktionsmetod efter filtyp och innehåll.

    PDF  → textlager först; saknas text → OCR av sidorna.
    Bild → direkt OCR.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        text, method = extract_pdf_text(p)
        if text:
            return text, method
        return extract_scanned_pdf_pages(p)
    if suffix in SCAN_EXTENSIONS:
        return extract_image_text(p)
    return "", "okänd-filtyp"


# ═════════════════════════════════════════════════════════════════════
#  TOLKNING AV FAKTURATEXT
# ═════════════════════════════════════════════════════════════════════


def _norm_amount(raw: str) -> float:
    """'71 144,00' / '1 638.50' → float; 0.0 vid skräp."""
    t = re.sub(r"[ \u00a0\u2009]", "", raw or "")
    t = t.replace("kr", "").replace("SEK", "").strip()
    if t.count(",") == 1 and "." not in t:
        t = t.replace(",", ".")
    elif "," in t and "." in t:
        t = t.replace(",", "")          # 1,234.56-stil
    try:
        return abs(float(t))
    except ValueError:
        return 0.0


#: Etikettmönster för ATT BETALA-beloppet (prioriteras).
_TOTAL_PATTERNS: tuple[str, ...] = (
    r"ATT\s*BETALA[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"TOTALT\s*ATT\s*BETALA[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"SUMMA[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"TOTALT[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
)

_ALL_AMOUNTS = re.compile(r"\d{1,3}(?:[ .\u00a0]\d{3})+,\d{2}|\d+,\d{2}")


def parse_total(text: str) -> float:
    """
    Hittar ATT BETALA-beloppet: etikettmönster först, annars största
    beloppet i dokumentet (på svenska fakturor är totalen nästan
    alltid störst).
    """
    upper = text.upper()
    for pat in _TOTAL_PATTERNS:
        m = re.search(pat, upper)
        if m:
            v = _norm_amount(m.group(1))
            if v > 0:
                return round(v, 2)
    amounts = [_norm_amount(a) for a in _ALL_AMOUNTS.findall(text)]
    amounts = [a for a in amounts if a > 0]
    return round(max(amounts), 2) if amounts else 0.0


def _search(text: str, patterns: tuple[str, ...]) -> str:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def parse_invoice_number(text: str) -> str:
    return _search(text, (
        r"Fakturanr\.?\s*[:#]?\s*([A-Za-z0-9\-/ .]{2,25})",
        r"Fakturanummer\s*[:#]?\s*([A-Za-z0-9\-/ .]{2,25})",
        r"Invoice\s*no\.?\s*[:#]?\s*([A-Za-z0-9\-/ .]{2,25})",
        r"Vår\s*referens\s*[:#]?\s*([A-Za-z0-9\-/ .]{2,25})",
    ))


def parse_ocr(text: str) -> str:
    return re.sub(
        r"\s", "",
        _search(text, (r"OCR\s*[:#]?\s*(\d[\d \-]{4,24}\d)",)),
    )


def _parse_date(raw: str) -> str:
    """Normaliserar svenska datumformat till YYYY-MM-DD ('' vid fel)."""
    raw = (raw or "").strip()
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})$", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})$", raw)
    if m:
        d, mo, y = m.groups()
        y = ("20" + y) if len(y) == 2 else y
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return ""


def parse_dates(text: str) -> tuple[str, str]:
    """
    Returnerar (fakturadatum, förfallodatum).

    Mönstren är toleranta mot OCR-varianten "Forfallodatum" (utan ö)
    och mot versaler.
    """
    inv = _parse_date(_search(text, (
        r"Fakturadatum\s*[:#]?\s*([0-9\-/.]{6,12})",
        r"Faktura\s*datum\s*[:#]?\s*([0-9\-/.]{6,12})",
        r"Invoice\s*date\s*[:#]?\s*([0-9\-/.]{6,12})",
    )))
    due = _parse_date(_search(text, (
        r"F[öo]rfallodatum\s*[:#]?\s*([0-9\-/.]{6,12})",
        r"F[öo]rfaller\s*[:#]?\s*([0-9\-/.]{6,12})",
        r"F[öo]rfaller\s*den\s*([0-9\-/.]{6,12})",
        r"Sista\s*betalningsdag\s*[:#]?\s*([0-9\-/.]{6,12})",
        r"Betalningsdatum\s*[:#]?\s*([0-9\-/.]{6,12})",
        r"Due\s*date\s*[:#]?\s*([0-9\-/.]{6,12})",
    )))
    return inv, due


def match_supplier(text: str, suppliers: list[dict]) -> str:
    """
    Matchar texten mot kända leverantörer: namn (skiftlägesoberoende)
    eller sifferföljder (org.nr / bankgiro / plusgiro) som förekommer
    i texten. Returnerar leverantörsnamn eller "".
    """
    digits = re.sub(r"\D", "", text)
    flat = text.lower()
    best, best_score = "", 0
    for sup in suppliers or []:
        name = str(sup.get("name", "")).strip()
        if not name:
            continue
        score = 0
        if name.lower() in flat:
            score += 5
        else:
            # första betydelsebärande ordet, t.ex. "Pilkington" i
            # "Pilkington Sverige AB"
            first = name.split()[0].lower() if name.split() else ""
            if first and len(first) > 3 and first in flat:
                score += 3
        for key in ("org_number", "bg", "pg"):
            num = re.sub(r"\D", "", str(sup.get(key, "") or ""))
            if len(num) >= 6 and num in digits:
                score += 4
        if score > best_score:
            best, best_score = name, score
    return best


def parse_invoice_text(
    text: str, suppliers: list[dict] | None = None
) -> dict[str, Any]:
    """
    Tolkar en fakturatext och returnerar kandidater:

        {"total_amount", "invoice_number", "ocr", "date", "due_date",
         "supplier", "missing": [..]}

    Inget gissas ohämmat: saknas ett fält blir det tomt och listas i
    "missing" så att användaren ser vad som ska kompletteras.
    """
    total = parse_total(text or "")
    inv_nr = parse_invoice_number(text or "")
    ocr = parse_ocr(text or "")
    date, due = parse_dates(text or "")
    supplier = match_supplier(text or "", suppliers or [])

    missing = [
        label for ok, label in (
            (total > 0, "belopp"),
            (bool(inv_nr), "fakturanummer"),
            (bool(supplier), "leverantör"),
        ) if not ok
    ]
    return {
        "total_amount": total,
        "invoice_number": inv_nr,
        "ocr": ocr,
        "date": date,
        "due_date": due,
        "supplier": supplier,
        "missing": missing,
    }


# ═════════════════════════════════════════════════════════════════════
#  PLUGIN-REGISTRERING
# ═════════════════════════════════════════════════════════════════════


def register(app: Any) -> None:
    """Fas 1: inget tungt jobb här — bara statuslogg."""
    stöd = []
    if HAS_PYPDF:
        stöd.append("pypdf")
    if HAS_FITZ:
        stöd.append("pymupdf")
    if HAS_TESS:
        stöd.append("tesseract")
    log.info(
        "scan_import registered (stöd: %s)",
        ", ".join(stöd) if stöd else "endast manuell text",
    )


def register_ui(main_window: Any) -> None:
    """Fas 2: monterar Import-vyn i import_tab-fliken."""
    try:
        from ui.scan_import_view import ScanImportView

        view = ScanImportView(
            app=getattr(main_window, "_app", None), parent=main_window
        )
        if hasattr(main_window, "replace_tab_content"):
            main_window.replace_tab_content("import_tab", view)
            log.info("ScanImport-vy monterad i Import-fliken")
        else:
            main_window.add_plugin_tab(view, "📥  Import", "import_tab")
        if hasattr(main_window, "theme_changed"):
            main_window.theme_changed.connect(view.apply_theme)
    except Exception as exc:
        log.error("scan_import register_ui: %s", exc, exc_info=True)
