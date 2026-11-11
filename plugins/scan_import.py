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
import hashlib
import json
import logging
import os
import re
import shutil
import unicodedata
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


def _page_text_quality(text: str) -> int:
    """Ungefärligt innehållsmått: sidnummer ensamt räcker inte som OCR."""
    return len(re.findall(r"[^\W_]", str(text or ""), flags=re.UNICODE))


def _extract_pdf_page_text_sources(
    path: Path, *, include_all: bool = False,
) -> list[tuple[list[str], str]]:
    """Text per sida från PDF-läsarna; sidfel isoleras till just den sidan."""
    sources: list[tuple[list[str], str]] = []
    if HAS_PYPDF:
        try:
            reader = PdfReader(str(path), strict=False)
            pages: list[str] = []
            for index, page in enumerate(reader.pages):
                try:
                    pages.append(page.extract_text() or "")
                except Exception as exc:
                    log.warning("pypdf sida %d i %s: %s", index + 1, path, exc)
                    pages.append("")
            if any(text.strip() for text in pages):
                sources.append((pages, "textlager-pypdf"))
        except Exception as exc:
            log.warning("pypdf: %s", exc)

    # Normala, helt textbaserade PDF:er läses bara en gång. PyMuPDF
    # kompletterar vid tomma/tunna sidor och när pypdf inte kunde läsa.
    needs_fitz = (
        include_all
        or not sources
        or any(
            _page_text_quality(text) < 12
            for text in sources[0][0]
        )
    )
    if HAS_FITZ and needs_fitz:
        try:
            with fitz.open(str(path)) as doc:
                pages = []
                for index, page in enumerate(doc):
                    try:
                        pages.append(page.get_text() or "")
                    except Exception as exc:
                        log.warning(
                            "pymupdf sida %d i %s: %s",
                            index + 1, path, exc,
                        )
                        pages.append("")
            if any(text.strip() for text in pages):
                sources.append((pages, "textlager-pymupdf"))
        except Exception as exc:
            log.warning("pymupdf: %s", exc)
    return sources


def extract_pdf_texts(path: Path) -> list[tuple[str, str]]:
    """
    Alla tillgängliga PDF-textuttag, i prioritetsordning.

    Olika läsare lägger ut samma sidas text i olika ordning
    (innehållsström kontra sidposition). En kolumnlayout
    (rubrikrad + värderad) kan därför vara läsbar för den ena
    läsaren men staplad för den andra — tolkningen prövar
    alternativen innan en fil parkeras (se parse_invoice_file).
    """
    out: list[tuple[str, str]] = []
    for pages, method in _extract_pdf_page_text_sources(
        path, include_all=True
    ):
        text = "\n".join(pages).strip()
        if text:
            out.append((text, method))
    return out


def extract_pdf_text(path: Path) -> tuple[str, str]:
    """
    Extraherar text ur en PDF.

    Returnerar (text, metod) där metod är "textlager-pypdf",
    "textlager-pymupdf" eller ("", "saknas-stöd") vid fel.
    """
    texts = extract_pdf_texts(path)
    return texts[0] if texts else ("", "ingen-pdf-läsare")


def _configure_tesseract_binary() -> bool:
    """Hittar standardinstallationer även om Tesseract saknas i PATH."""
    if not HAS_TESS:
        return False
    engine = getattr(pytesseract, "pytesseract", None)
    command = str(getattr(engine, "tesseract_cmd", "tesseract") or "")
    if command and (shutil.which(command) or Path(command).is_file()):
        return True

    candidates: list[Path] = []
    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(variable, "")
            if root:
                candidates.append(
                    Path(root) / "Tesseract-OCR" / "tesseract.exe"
                )
        candidates.append(Path("C:/Program Files/Tesseract-OCR/tesseract.exe"))
    else:
        candidates.extend((
            Path("/opt/homebrew/bin/tesseract"),
            Path("/usr/local/bin/tesseract"),
            Path("/usr/bin/tesseract"),
            Path("/opt/local/bin/tesseract"),
        ))
    for candidate in candidates:
        if candidate.is_file():
            if engine is not None:
                engine.tesseract_cmd = str(candidate)
            return True
    return False


def tesseract_available() -> bool:
    """True bara när både pytesseract och själva Tesseract-programmet finns."""
    if not _configure_tesseract_binary():
        return False
    try:
        return bool(pytesseract.get_tesseract_version())
    except Exception:
        return False


def _ocr_image_text(image, *, engine_checked: bool = False) -> tuple[str, str]:
    """OCR:a en bild; prova vanliga språkdata utan att tappa sidan."""
    if not HAS_TESS:
        return "", "ocr-saknas"
    if not engine_checked and not tesseract_available():
        return "", "ocr-saknas"
    last_exc: Exception | None = None
    for language in ("swe+eng", "eng", "swe"):
        try:
            text = pytesseract.image_to_string(
                image, lang=language
            ) or ""
            return text.strip(), "ocr-tesseract"
        except Exception as exc:
            last_exc = exc
            log.debug("Tesseract %s misslyckades: %s", language, exc)
    if last_exc is not None:
        log.warning("tesseract: %s", last_exc)
    return "", "ocr-fel"


def extract_image_text(path: Path) -> tuple[str, str]:
    """OCR av bild via Tesseract (swe+eng, därefter eng)."""
    if not HAS_TESS or not tesseract_available():
        return "", "ocr-saknas"
    try:
        with Image.open(str(path)) as img:
            page_count = max(1, int(getattr(img, "n_frames", 1) or 1))
            texts: list[str] = []
            failed = False
            for index in range(page_count):
                try:
                    img.seek(index)
                    frame = img.copy()
                    try:
                        text, method = _ocr_image_text(
                            frame, engine_checked=True
                        )
                    finally:
                        frame.close()
                except Exception as exc:
                    log.warning(
                        "tesseract/bild %s sida %d: %s",
                        path, index + 1, exc,
                    )
                    text, method = "", "ocr-fel"
                texts.append(text)
                failed = failed or method == "ocr-fel"
            method = "ocr-tesseract"
            if failed:
                method += "+ocr-fel"
            return "\n".join(texts).strip(), method
    except Exception as exc:
        log.warning("tesseract/bild %s: %s", path, exc)
        return "", "ocr-fel"


def _ocr_pdf_page(page) -> tuple[str, str]:
    """Rendera och OCR:a en sida; fel i en sida påverkar inte resten."""
    try:
        import io

        pix = page.get_pixmap(dpi=300)
        with Image.open(io.BytesIO(pix.tobytes("png"))) as img:
            return _ocr_image_text(img, engine_checked=True)
    except Exception as exc:
        log.warning("scannad pdf-sida: %s", exc)
        return "", "ocr-fel"


def extract_scanned_pdf_pages(path: Path) -> tuple[str, str]:
    """
    OCR av skannad PDF (inga textlager): renderar och OCR:ar varje
    sida för sig, så en trasig sida inte tyst tar bort de andra.
    """
    if not HAS_FITZ or not tesseract_available():
        return "", "ocr-saknas"
    texts: list[str] = []
    failed = False
    try:
        with fitz.open(str(path)) as doc:
            for page in doc:
                text, method = _ocr_pdf_page(page)
                texts.append(text)
                failed = failed or method == "ocr-fel"
    except Exception as exc:
        log.warning("scannad pdf-ocr %s: %s", path, exc)
        return "", "ocr-fel"
    method = "ocr-tesseract-pdf"
    if failed:
        method += "+ocr-fel"
    return "\n".join(texts).strip(), method


def extract_pdf_pages(path: Path) -> tuple[str, str]:
    """Läs PDF sida för sida och OCR:a tomma eller mycket tunna sidor.

    Digitala sidor behåller textlagrets extraktion. I blandade PDF:er
    (text + skannade sidor) kompletteras bara de sidor som saknar
    användbar text; originalfilen öppnas endast för läsning.
    """
    sources = _extract_pdf_page_text_sources(path)
    if not sources:
        return extract_scanned_pdf_pages(path)

    page_count = max(len(pages) for pages, _method in sources)
    selected: list[tuple[str, str]] = []
    for index in range(page_count):
        candidates = [
            (pages[index].strip(), method)
            for pages, method in sources
            if index < len(pages) and pages[index].strip()
        ]
        selected.append(
            max(candidates, key=lambda item: _page_text_quality(item[0]))
            if candidates else ("", "")
        )

    needs_ocr = [
        index for index, (text, _method) in enumerate(selected)
        if _page_text_quality(text) < 12
    ]
    ocr_missing = False
    ocr_failed = False
    if needs_ocr:
        if HAS_FITZ and tesseract_available():
            try:
                with fitz.open(str(path)) as doc:
                    for index in needs_ocr:
                        if index >= len(doc):
                            ocr_failed = True
                            continue
                        text, method = _ocr_pdf_page(doc[index])
                        old_text, old_method = selected[index]
                        if _page_text_quality(text) > _page_text_quality(old_text):
                            selected[index] = (text, method)
                        ocr_failed = ocr_failed or method == "ocr-fel"
            except Exception as exc:
                log.warning("blandad pdf-ocr %s: %s", path, exc)
                ocr_failed = True
        else:
            ocr_missing = True

    used_methods: list[str] = []
    for _text, method in selected:
        if method and method not in used_methods:
            used_methods.append(method)
    if ocr_missing:
        used_methods.append("ocr-saknas")
    if ocr_failed:
        used_methods.append("ocr-fel")
    text = "\n".join(page_text for page_text, _method in selected).strip()
    return text, "+".join(used_methods) or "ingen-pdf-läsare"


def extract_text(path: Path) -> tuple[str, str]:
    """
    Huvudingång: väljer extraktionsmetod efter filtyp och innehåll.

    PDF  → textlager först; saknas text → OCR av sidorna.
    Bild → direkt OCR.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_pages(p)
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
    if "," in t and "." in t:
        # Båda skiljetecknen finns: det SISTA är decimaltecknet.
        # Svenskt 3.499,30 (punkt = tusental, t.ex. NSG/Pilkington)
        # och US-format 1,234.56 (komma = tusental) blir båda rätt.
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif t.count(",") == 1:
        t = t.replace(",", ".")
    try:
        return abs(float(t))
    except ValueError:
        return 0.0


#: Etikettmönster för ATT BETALA-beloppet (prioriteras).
_TOTAL_PATTERNS: tuple[str, ...] = (
    r"ATT\s*BETALA[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"SUMMA\s*ATT\s*BETALA[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"TOTALT\s*ATT\s*BETALA[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"AMOUNT\s*DUE[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"TOTAL\s*AMOUNT\s*DUE[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"BALANCE\s*DUE[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"TILLGODO[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"SUMMA[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
    r"TOTALT[^0-9]{0,12}(\d[\d .,\u00a0]{2,20})",
)

_ALL_AMOUNTS = re.compile(r"\d{1,3}(?:[ .\u00a0]\d{3})+,\d{2}|\d+,\d{2}")


def _amount_from_group(group: str) -> float:
    """
    Tolkar beloppsgruppen efter en total-etikett. Vissa layouter
    (Saint-Gobain) skriver "Summa Glas 1 2.642,50" — ett ensamt
    heltal (ANTAL) framför beloppet som annars klistras ihop
    till 12.642,50. Står ett ensamt heltal före det sista
    fullständiga beloppet är det sista beloppet det rätta.
    """
    g = (group or "").strip()
    hits = list(_ALL_AMOUNTS.finditer(g))
    if hits:
        last = hits[-1]
        if (
            last.start() > 0
            and last.end() == len(g)
            and re.fullmatch(r"[\d\s]+", g[: last.start()])
        ):
            return _norm_amount(last.group(0))
    return _norm_amount(g)


def _is_postal_code_group(group: str) -> bool:
    """True om beloppsgruppen i själva verket är ett svenskt
    postnummer ("701 17"/"70117" utan decimaler). Ett sådant
    får aldrig normaliseras till 70 117 kr — det är exakt så
    leverantörens postadress tidigare kunde bli fakturans
    att betala när etikett och värde hamnade på olika rader."""
    g = (group or "").strip()
    if "," in g or "." in g:
        return False
    digits = re.sub(r"[\s\u00a0]", "", g)
    return bool(re.fullmatch(r"\d{5}", digits))


def parse_total(text: str) -> float:
    """
    Hittar ATT BETALA-beloppet: etikettmönster först, annars största
    beloppet i dokumentet (på svenska fakturor är totalen nästan
    alltid störst). Postnummer-formade träffar efter en etikett
    hoppas över — sökningen fortsätter till nästa förekomst i
    stället för att postadressen blir belopp.

    Flersidiga fakturor: en etikett kan förekomma flera gånger
    (delsumma på sida 1, slutsumman på sista sidan). Då är det
    den SISTA giltiga träffen för mönstret som är totalen — den
    första kan vara en sidodellista (faktura 923682: sida 1 gav
    2 686,45 medan fakturans total på sida 2 var 6 176).
    """
    upper = text.upper()
    for pat in _TOTAL_PATTERNS:
        last = 0.0
        for m in re.finditer(pat, upper):
            group = m.group(1)
            if _is_postal_code_group(group):
                continue
            v = _amount_from_group(group)
            if v > 0:
                last = round(v, 2)
        if last > 0:
            return last
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
    for pat in (
        r"Fakturanr\.?\s*[:#]?\s*(\S{2,25})",
        r"Faktura\s*nr\.?\s*[:#]?\s*(\S{2,25})",
        r"Faktura\s*nummer\s*[:#]?\s*(\S{2,25})",
        r"Fakturanummer\s*[:#]?\s*(\S{2,25})",
        r"Invoice\s*(?:no\.?|number|#)\s*[:#]?\s*(\S{2,25})",
        r"Dokumentnummer\s*[:#]?\s*(\S{2,25})",
        r"Document\s*(?:no\.?|number)\s*[:#]?\s*(\S{2,25})",
        r"Vår\s*referens\s*[:#]?\s*(\S{2,25})",
    ):
        for m in re.finditer(pat, text, re.IGNORECASE):
            tok = _INVOICE_NR_RE.match(m.group(1))
            cand = tok.group(0) if tok else ""
            if len(cand) >= 2 and cand.upper() not in _INVOICE_NR_STOPWORDS:
                return cand
            # Siffrigt nummer separerat med streck ("NL-2026-0771"
            # via etiketten "Vår referens") är också ett nummer.
            num = re.match(r"\d[\d\-/]*\d|\d", m.group(1))
            if num and len(num.group(0)) >= 4:
                return num.group(0)
    return ""


def parse_ocr(text: str) -> str:
    # "OCR:", "OCR-nummer:" och "OCR nummer:" är samma fält på
    # svenska fakturor; bindestrecket fick tidigare träffen att missa.
    return re.sub(
        r"\s", "",
        _search(
            text,
            (r"OCR(?:[\s\-]*nummer)?\s*[:#]?\s*(\d[\d \-]{4,24}\d)",),
        ),
    )


def _parse_date(raw: str) -> str:
    """Normaliserar svenska datumformat till YYYY-MM-DD ('' vid fel)."""
    raw = (raw or "").strip()
    m = re.match(r"^(\d{4})[-./]?(\d{2})[-./]?(\d{2})$", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})$", raw)
    if m:
        d, mo, y = m.groups()
        y = ("20" + y) if len(y) == 2 else y
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return ""


#: Markörer för kreditdokument. Ordet "kreditfaktura/-nota" på
#: dokumentet är den pålitliga signalen — nakna siffror säger
#: inte om beloppet ska öka eller MINSKA att betala.
_CREDIT_MARKERS = (
    "kreditfaktura", "kreditnota",
    "credit note", "credit memo", "credit invoice",
)


def is_credit_note(text: str) -> bool:
    """True om dokumentet ser ut att vara en kreditfaktura/-nota."""
    t = (text or "").lower()
    return any(m in t for m in _CREDIT_MARKERS)

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


#: Bolagsformer/konjunktioner som inte bär identitet i ett
#: leverantörsnamn ("AB Martin G Anderson" = "Martin G Anderson").
_NAME_DROP_TOKENS = frozenset({
    "ab", "aktiebolag", "hb", "kb", "ek", "bolag",
    "och", "and", "the",
    # Fältetiketter som ofta förekommer på fakturor och därför inte
    # ensamma bör räcka som leverantörsnamn.
    "bg", "pg", "iban", "bic", "swift", "bankgiro", "plusgiro",
    "org", "orgnr", "organisationsnummer", "invoice", "faktura",
    "datum", "date", "total", "amount", "att", "betala",
})


def _fold_text(value: Any) -> str:
    """Viker text för namnmatchning: gemener, accenter bort
    (å/ä/ö → a/a/o), skiljetecken → mellanslag. "Saint-Gobain
    Autover" och "saint gobain autover" blir samma nyckel —
    OCR- och layoutvarianter ska inte avgöra matchningen."""
    raw = unicodedata.normalize("NFKD", str(value or "").lower())
    folded = "".join(
        ch for ch in raw if not unicodedata.combining(ch)
    )
    folded = folded.replace("&", " och ")
    folded = re.sub(r"[^a-z0-9]+", " ", folded)
    return " ".join(folded.split())


def _name_tokens(value: Any) -> list[str]:
    return [
        tok for tok in _fold_text(value).split()
        if tok not in _NAME_DROP_TOKENS
    ]


def _names_match(left: Any, right: Any) -> bool:
    """Samma leverantörsnamn trots variant? Sant vid vikt
    likhet, samma betydelsebärande ordmängd, eller när den ena
    sidans ord (minst två, eller ett långt särskiljande ord)
    alla finns i den andra ("Martin G" i "Martin G Anderson",
    "Nordlys Energi" i "Nordlys Energi AB")."""
    lf, rf = _fold_text(left), _fold_text(right)
    if not lf or not rf:
        return False
    if lf == rf:
        return True
    lt, rt = set(_name_tokens(left)), set(_name_tokens(right))
    if not lt or not rt:
        return False
    if lt == rt:
        return True
    small, large = (lt, rt) if len(lt) <= len(rt) else (rt, lt)
    if small <= large:
        return len(small) >= 2 or (
            len(small) == 1 and len(next(iter(small))) >= 5
        )
    return False


#: Registerfält som kan identifiera en leverantör på fakturan.
_SUPPLIER_ID_PROFILE_KEYS: dict[str, tuple[str, ...]] = {
    "org": ("org_number", "orgnr", "org"),
    "bg": ("bankgiro", "bg"),
    "pg": ("plusgiro", "pg"),
    "iban": ("iban",),
}


def _supplier_aliases(supplier: dict) -> list[str]:
    """Normaliserar manuellt angivna leverantörsnamn/handelsnamn.

    Äldre eller handredigerade JSON-poster kan ha alias som en
    semikolonseparerad sträng; det stöds utan att dela på kommatecken,
    som kan ingå i ett företagsnamn.
    """
    raw = supplier.get("aliases", [])
    if isinstance(raw, str):
        values = re.split(r"[\r\n;]+", raw)
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = []
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        alias = str(value or "").strip()
        key = _fold_text(alias)
        if alias and key and key not in seen:
            aliases.append(alias)
            seen.add(key)
    return aliases


def _registered_supplier_aliases(
    supplier_name: str, suppliers: list[dict] | None
) -> list[str]:
    """Entydiga alias för en registerpost, aldrig delade namn."""
    folded = _fold_text(supplier_name)
    if not folded:
        return []
    records = [
        supplier for supplier in (suppliers or [])
        if isinstance(supplier, dict)
        and _fold_text(supplier.get("name", "")) == folded
    ]
    if len(records) != 1:
        return []
    aliases = _supplier_aliases(records[0])
    other_names: list[str] = []
    for other in suppliers or []:
        if not isinstance(other, dict) or other is records[0]:
            continue
        other_name = str(other.get("name", "") or "").strip()
        if other_name:
            other_names.append(other_name)
        other_names.extend(_supplier_aliases(other))
    return [
        alias for alias in aliases
        if not any(_names_match(alias, other) for other in other_names)
    ]


def _same_registered_supplier_name(
    left: str, right: str, suppliers: list[dict] | None
) -> bool:
    """Samma registerleverantör via namnvariant eller manuellt alias."""
    if _names_match(left, right):
        return True
    return any(
        _names_match(alias, right)
        for alias in _registered_supplier_aliases(left, suppliers)
    )


def _normalize_supplier_identifier(field: str, value: Any) -> str:
    """Kanonisk nyckel för ett registrerat starkt kännetecken."""
    raw = str(value or "").upper()
    if field == "iban":
        normalized = re.sub(r"[^A-Z0-9]", "", raw)
        return normalized if _valid_iban_checksum(normalized) else ""
    digits = re.sub(r"\D", "", raw)
    if field == "org":
        # Svenska organisationsnummer lagras normalt med tio siffror;
        # tillåt även det vanliga 16-prefixet för juridiska personer.
        if len(digits) == 12 and digits.startswith("16"):
            digits = digits[2:]
        return (
            digits
            if len(digits) == 10 and _org_nr_checksum_ok(digits)
            else ""
        )
    if field == "bg":
        return digits if len(digits) in (7, 8) else ""
    if field == "pg":
        return digits if 2 <= len(digits) <= 10 else ""
    return ""


def _supplier_invoice_identifiers(text: str) -> dict[str, set[str]]:
    """Starka ID:n som faktiskt hittats i rätt fakturakontaktfält.

    Org.nr kräver giltig kontrollsiffra. BG/PG/IBAN måste stå efter sin
    egen etikett; ett likadant sifferblock i OCR-text eller fakturanummer
    räcker inte för att koppla en leverantör.
    """
    org_ids = _invoice_identifiers(text).get("org", set())
    details = extract_invoice_payment_details(text)
    values: dict[str, set[str]] = {
        "org": set(), "bg": set(), "pg": set(), "iban": set(),
    }
    for value in org_ids:
        normalized = _normalize_supplier_identifier("org", value)
        if normalized:
            values["org"].add(normalized)
    for field in ("bg", "pg", "iban"):
        for value in details.get(field, []):
            normalized = _normalize_supplier_identifier(field, value)
            if normalized:
                values[field].add(normalized)
    return values


def _supplier_match_candidates(
    text: str, suppliers: list[dict]
) -> list[dict[str, Any]]:
    """Alla leverantörer med någon positiv träff, starkast först.

    Varje kandidat bär poäng och vilka signaler som gav träffen.
    Listan används både för säkra val och för att kunna FRÅGA
    användaren vid svaga eller konkurrerande träffar — appen ska
    aldrig behöva dölja att flera alternativ var möjliga.
    """
    folded = _fold_text(text)
    folded_tokens = set(folded.split())
    invoice_ids = _supplier_invoice_identifiers(text or "")
    by_key: dict[str, dict[str, Any]] = {}
    for sup in suppliers or []:
        if not isinstance(sup, dict):
            continue
        name = str(sup.get("name", "")).strip()
        if not name:
            continue
        score = 0
        signals: list[str] = []
        name_fold = _fold_text(name)
        tokens = _name_tokens(name)
        token_set = set(tokens)
        if name_fold and f" {name_fold} " in f" {folded} ":
            score += 6
            signals.append("full_name")
        elif token_set and token_set <= folded_tokens and (
            len(token_set) >= 2
            or (tokens and len(tokens[0]) >= 4)
        ):
            score += 5
            signals.append("name_words")
        elif tokens and len(tokens[0]) >= 5 \
                and tokens[0] in folded_tokens:
            # Ensamt särskiljande förstanamn ("Pilkington Sverige
            # AB" på en faktura som bara trycker "Pilkington").
            # Det är en ledtråd, inte ett säkert val.
            score += 3
            signals.append("first_name_only")
        for alias in _supplier_aliases(sup):
            alias_fold = _fold_text(alias)
            alias_tokens = set(_name_tokens(alias))
            if alias_fold and f" {alias_fold} " in f" {folded} ":
                score += 6
                if "alias_full_name" not in signals:
                    signals.append("alias_full_name")
            elif alias_tokens and alias_tokens <= folded_tokens and (
                len(alias_tokens) >= 2
                or (
                    len(alias_tokens) == 1
                    and len(next(iter(alias_tokens))) >= 5
                )
            ):
                score += 5
                if "alias_words" not in signals:
                    signals.append("alias_words")
        for field, keys in _SUPPLIER_ID_PROFILE_KEYS.items():
            expected = {
                normalized
                for key in keys
                if (normalized := _normalize_supplier_identifier(
                    field, sup.get(key, "")
                ))
            }
            if expected.intersection(invoice_ids.get(field, set())):
                score += 5
                signals.append({
                    "org": "org_number",
                    "bg": "bankgiro",
                    "pg": "plusgiro",
                    "iban": "iban",
                }[field])
        if score <= 0:
            continue
        key = _fold_text(name)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = {
                "name": name,
                "score": score,
                "signals": signals,
            }
        else:
            existing["score"] = max(existing["score"], score)
            for signal in signals:
                if signal not in existing["signals"]:
                    existing["signals"].append(signal)
    return sorted(
        by_key.values(),
        key=lambda cand: (-int(cand["score"]), _fold_text(cand["name"])),
    )


def assess_supplier_match(
    text: str, suppliers: list[dict]
) -> dict[str, Any]:
    """Bedöm leverantörsmatchningen utan att gissa vid osäkerhet.

    Returnerar ``supplier`` bara vid en unik stark träff. En ensam
    svag förstanamnsträff, lika starka kandidater eller en annan
    stark kandidat ger ``uncertain=True`` och hela kandidatlistan,
    så att gränssnittet kan fråga användaren i stället.
    """
    candidates = _supplier_match_candidates(text, suppliers)
    if not candidates:
        return {
            "status": "none",
            "supplier": "",
            "candidates": [],
            "uncertain": False,
            "reason": "",
        }
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    if int(top["score"]) >= 5 and (
        second is None or int(second["score"]) < 5
    ):
        return {
            "status": "matched",
            "supplier": str(top["name"]),
            "candidates": candidates,
            "uncertain": False,
            "reason": "",
        }
    if second is not None and int(second["score"]) == int(top["score"]):
        reason = "ambiguous"
    elif second is not None and int(second["score"]) >= 5:
        reason = "competing"
    else:
        reason = "weak"
    return {
        "status": "uncertain",
        "supplier": "",
        "candidates": candidates,
        "uncertain": True,
        "reason": reason,
    }


def _merge_match_candidates(
    *candidate_lists: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Slå ihop kandidatlistor utan att tappa möjliga alternativ."""
    merged: dict[str, dict[str, Any]] = {}
    for candidates in candidate_lists:
        for cand in candidates or []:
            if not isinstance(cand, dict):
                continue
            name = str(cand.get("name", "")).strip()
            if not name:
                continue
            key = _fold_text(name)
            existing = merged.get(key)
            if existing is None:
                merged[key] = {
                    "name": name,
                    "score": int(cand.get("score", 0) or 0),
                    "signals": list(cand.get("signals", []) or []),
                }
            else:
                existing["score"] = max(
                    existing["score"], int(cand.get("score", 0) or 0)
                )
                for signal in cand.get("signals", []) or []:
                    if signal not in existing["signals"]:
                        existing["signals"].append(signal)
    return sorted(
        merged.values(),
        key=lambda cand: (-int(cand["score"]), _fold_text(cand["name"])),
    )


def _assess_supplier_and_templates(
    text: str,
    suppliers: list[dict] | None,
    templates: dict | None,
) -> dict[str, Any]:
    """Gemensam bedömning av registerleverantörer och mallnamn.

    En mallnyckel kan identifiera en leverantör som ännu inte finns
    i registret, men ett starkt registerresultat och ett annat
    starkt mallnamn är en konflikt — inte något appen får avgöra
    själv.
    """
    registry = assess_supplier_match(text, suppliers or [])
    if not templates:
        return registry
    template_match = assess_supplier_match(
        text, [{"name": str(name)} for name in templates.keys()]
    )
    if registry["status"] == "matched":
        accepted = str(registry["supplier"])
        if (
            template_match["status"] == "matched"
            and not _same_registered_supplier_name(
                accepted, str(template_match["supplier"]), suppliers
            )
        ):
            return {
                "status": "uncertain",
                "supplier": "",
                "candidates": _merge_match_candidates(
                    registry["candidates"], template_match["candidates"]
                ),
                "uncertain": True,
                "reason": "competing",
            }
        if template_match["status"] == "uncertain":
            rivals = [
                cand for cand in template_match["candidates"]
                if not _same_registered_supplier_name(
                    accepted, str(cand.get("name", "")), suppliers
                )
            ]
            if rivals:
                return {
                    "status": "uncertain",
                    "supplier": "",
                    "candidates": _merge_match_candidates(
                        registry["candidates"], rivals
                    ),
                    "uncertain": True,
                    "reason": "competing",
                }
        return registry
    if template_match["status"] == "matched":
        if registry["status"] == "uncertain":
            return {
                "status": "uncertain",
                "supplier": "",
                "candidates": _merge_match_candidates(
                    registry["candidates"], template_match["candidates"]
                ),
                "uncertain": True,
                "reason": "competing",
            }
        return template_match
    if registry["status"] == "uncertain" or \
            template_match["status"] == "uncertain":
        return {
            "status": "uncertain",
            "supplier": "",
            "candidates": _merge_match_candidates(
                registry["candidates"], template_match["candidates"]
            ),
            "uncertain": True,
            "reason": (
                "ambiguous"
                if registry["reason"] == "ambiguous"
                or template_match["reason"] == "ambiguous"
                else template_match["reason"] or registry["reason"]
            ),
        }
    return registry


def match_supplier(text: str, suppliers: list[dict]) -> str:
    """
    Matchar texten mot kända leverantörer och returnerar namnet
    eller "" (inget gissas vid tvetydighet eller svag träff).

    Starka träffar: giltigt org.nr eller etiketterat BG/PG/IBAN,
    leverantörens namn eller manuellt registrerat alias — vikt så
    att "AB Martin G Anderson",
    "Martin G. Anderson" och OCR-varianten utan prickar är samma
    leverantör. Ordmängden räcker också (alla betydelsebärande
    ord på fakturan), vilket klarar bolagsform före/efter namnet
    och annan ordning. En ensam förstanamnsträff är numera bara
    en kandidat i parse-resultatets matchbedömning: den kan vara
    rätt, men är för svag för att appen ska välja själv.
    """
    return str(assess_supplier_match(text, suppliers)["supplier"])


def template_candidate_names(
    templates: dict, supplier: str
) -> list[str]:
    """Mallnycklar som kan höra till leverantören, utan gissning.

    Exakt nyckel vinner; annars vikt lika nyckel, annars alla
    vikt namnträffar. Flera nycklar betyder att mallvalet är
    osäkert och ska avgöras av användaren.
    """
    if not templates or not supplier:
        return []
    if supplier in templates:
        folded = _fold_text(supplier)
        case_variants = [
            str(name) for name in templates
            if name != supplier and _fold_text(name) == folded
        ]
        return [supplier, *case_variants]
    folded = _fold_text(supplier)
    exact = [
        str(name) for name in templates.keys()
        if _fold_text(name) == folded
    ]
    if exact:
        return exact
    return [
        str(name) for name in templates.keys()
        if _names_match(name, supplier)
    ]


def supplier_template_candidate_names(
    templates: dict | None,
    supplier: str,
    suppliers: list[dict] | None = None,
) -> list[str]:
    """Mallnycklar för registerleverantören och dess sparade alias.

    En aliasnyckel är inte ett konkurrerande företag när den uttryckligen
    finns på samma entydiga registerpost. Om flera mallar (t.ex. både
    juridiskt namn och handelsnamn) matchar returneras samtliga så att
    anroparen kan fråga i stället för att välja en layout på måfå.
    """
    if not templates or not supplier:
        return []
    candidates = template_candidate_names(templates, supplier)
    for alias in _registered_supplier_aliases(supplier, suppliers):
        candidates.extend(template_candidate_names(templates, alias))
    unique: list[str] = []
    seen: set[str] = set()
    for name in candidates:
        key = str(name)
        if key and key not in seen:
            unique.append(key)
            seen.add(key)
    return unique


def _math_line_amount(text: str, label: str) -> float | None:
    """Beloppet på etikettens EGEN rad, försiktigt valt.

    Rader där etiketten bara nämns i förbifarten ("Pris exkl
    moms: …") hoppas över, och en etikett som inleder sin rad
    vinner över en som står mitt i en summarrad. Bara belopp på
    samma rad accepteras — i kolumnlayouter (rubrikrad +
    värderad) blir svaret None i stället för fel kolumn.
    """
    flat = re.sub(r"[ \t]+", " ", text or "")
    lab = re.sub(r"\s+", " ", str(label)).strip().rstrip(":#").strip()
    if not lab:
        return None
    best: float | None = None
    for m in re.finditer(re.escape(lab), flat, re.IGNORECASE):
        line_start = flat.rfind("\n", 0, m.start()) + 1
        prefix = flat[line_start:m.start()].strip().lower()
        if "exkl" in prefix or "pris" in prefix:
            continue  # omnämnande, inte summarraden
        rest = flat[m.end():].split("\n", 1)[0]
        hit = _extract_kind(rest, "amount", m.group(0))
        if not hit:
            continue
        try:
            value = float(hit)
        except (TypeError, ValueError):
            continue
        if not prefix:
            return value  # etiketten inleder raden — starkast
        if best is None:
            best = value
    return best


#: Etiketter för räknekontrollen (netto/moms/öresavrundning).
#: Samma försiktighet som överallt: bara värden på etikettens
#: egen rad används, annars "okänt" — aldrig fel kolumn.
_MATH_NET_LABELS = (
    "Summa netto", "Netto exkl. moms", "Summa exkl. moms",
    "Exkl. moms", "Netto",
)
_MATH_VAT_LABELS = (
    "Moms 25 %", "Moms 25%", "Mervärdesskatt", "Moms", "VAT",
)
_MATH_ROUND_LABELS = ("Öresavrundning", "Oresavrundning", "Avrundning")


def invoice_math_check(text: str, total: float) -> dict[str, Any]:
    """Räknekontroll: stämmer netto + moms (+ öresavrundning)
    mot att betala?

    Returnerar {"status": "ok"/"mismatch"/"unknown", "net",
    "vat", "rounding", "expected", "diff"}. Både netto och
    moms måste stå på sina etiketters egna rader för att
    kontrollen alls ska uttala sig — annars "unknown", så
    kolumnlayouter och enkla fakturor aldrig falsklarmar.
    """
    try:
        tot = abs(float(total or 0))
    except (TypeError, ValueError):
        tot = 0.0
    net = vat = rounding = None
    for lab in _MATH_NET_LABELS:
        net = _math_line_amount(text or "", lab)
        if net is not None:
            break
    for lab in _MATH_VAT_LABELS:
        vat = _math_line_amount(text or "", lab)
        if vat is not None:
            break
    for lab in _MATH_ROUND_LABELS:
        rounding = _math_line_amount(text or "", lab)
        if rounding is not None:
            break
    out: dict[str, Any] = {
        "status": "unknown",
        "net": net,
        "vat": vat,
        "rounding": rounding,
        "expected": None,
        "diff": None,
    }
    if tot <= 0 or net is None or vat is None:
        return out
    expected = round(net + vat + (rounding or 0.0), 2)
    diff = round(tot - expected, 2)
    out["expected"] = expected
    out["diff"] = diff
    out["status"] = (
        "ok"
        if abs(diff) <= max(1.0, tot * 0.005)
        else "mismatch"
    )
    return out


def _iso_date_or_none(value: Any) -> Any:
    try:
        return datetime.date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None


def invoice_date_check(date: str, due: str) -> dict[str, Any]:
    """Datumlogik: förfaller fakturan EFTER fakturadatumet och
    med en rimlig betalfrist?

    Returnerar {"status": "ok"/"warning"/"unknown",
    "problems": [...], "term_days": n}. Problemen är koder:
    "due_before_date" (förfallodatum före fakturadatum —
    troligt avläsningsfel), "term_long" (frist över 120
    dagar) och "date_future" (fakturadatum mer än 30 dagar
    framåt). Saknas datum blir svaret "unknown".
    """
    d = _iso_date_or_none(date)
    u = _iso_date_or_none(due)
    problems: list[str] = []
    term = None
    if d is not None and u is not None:
        term = (u - d).days
        if term < 0:
            problems.append("due_before_date")
        elif term > 120:
            problems.append("term_long")
    if d is not None and d > (
        datetime.date.today() + datetime.timedelta(days=30)
    ):
        problems.append("date_future")
    status = (
        "warning"
        if problems
        else ("ok" if (d is not None and u is not None) else "unknown")
    )
    return {"status": status, "problems": problems, "term_days": term}


#: Leverantörsinställning: OCR-numret är samma nummer som fakturanumret.
OCR_AS_INVOICE_NUMBER_KEY = "ocr_same_as_invoice_number"


def _supplier_aliases(supplier: dict) -> list[str]:
    raw = supplier.get("aliases")
    if isinstance(raw, str):
        return [part.strip() for part in re.split(r"[;\n]", raw)]
    if isinstance(raw, (list, tuple, set)):
        return [str(part).strip() for part in raw]
    return []


def supplier_ocr_as_invoice_number(
    suppliers: list[dict] | None, name: Any
) -> bool:
    """Har leverantören valt att OCR-numret är fakturanumret?"""
    wanted = str(name or "").strip()
    if not wanted:
        return False
    for supplier in suppliers or []:
        if not isinstance(supplier, dict):
            continue
        if not supplier.get(OCR_AS_INVOICE_NUMBER_KEY):
            continue
        if _names_match(supplier.get("name", ""), wanted):
            return True
        if any(
            _names_match(alias, wanted)
            for alias in _supplier_aliases(supplier)
            if alias
        ):
            return True
    return False


def apply_supplier_ocr_rule(
    parsed: dict[str, Any], suppliers: list[dict] | None
) -> dict[str, Any]:
    """Fyller OCR med fakturanumret för leverantörer som valt det.

    Bara när OCR-fältet är tomt: ett nummer som faktiskt står på
    fakturan vinner alltid. Leverantören måste redan vara entydigt
    matchad — regeln gissar aldrig en leverantör och påverkar
    därför inte auto-registrering eller osäkra träffar.
    """
    result = parsed if isinstance(parsed, dict) else {}
    if not result or result.get("match_uncertain"):
        return result
    if str(result.get("ocr") or "").strip():
        return result
    number = str(result.get("invoice_number") or "").strip()
    if not number:
        return result
    if not supplier_ocr_as_invoice_number(suppliers, result.get("supplier")):
        return result
    result["ocr"] = number
    result["ocr_source"] = "supplier_rule"
    log.info(
        "SCAN_IMPORT: OCR = fakturanummer (%s) enligt leverantörens "
        "inställning", number,
    )
    return result


def parse_invoice_text(
    text: str,
    suppliers: list[dict] | None = None,
    templates: dict | None = None,
    region_texts: dict | None = None,
    region_texts_by_template: dict | None = None,
    match_learning: dict | None = None,
) -> dict[str, Any]:
    """
    Tolkar en fakturatext och returnerar kandidater:

        {"total_amount", "invoice_number", "ocr", "date", "due_date",
         "supplier", "missing": [..]} (+ "template" vid mallträff)

    Inget gissas ohämmat: saknas ett fält blir det tomt och listas i
    "missing" så att användaren ser vad som ska kompletteras.

    Finns en leverantörsmall (templates) för den igenkända
    leverantören körs den FÖRST för sina fält — användarens egna
    etiketter vinner alltid över den generiska heuristiken. Mallens
    leverantörsnamn kan också kännas igen direkt i texten, även om
    leverantören inte finns i registret än.

    Saknas egen mall prövas de inbyggda, verifierade formaten
    (BUILTIN_FORMATS): leverantörer vars layout matchats mot
    riktiga exempelfakturor i förväg. De identifieras via
    org.nr/bankgiro eller tryckt namn på själva fakturan och
    kräver fakturanummer + belopp ur formatet för att räknas —
    annars parkeras filen som vanligt.
    """
    total = parse_total(text or "")
    inv_nr = parse_invoice_number(text or "")
    ocr = parse_ocr(text or "")
    date, due = parse_dates(text or "")
    supplier_assessment = _assess_supplier_and_templates(
        text or "", suppliers or [], templates
    )
    supplier = str(supplier_assessment.get("supplier", "") or "")
    match_uncertain = bool(supplier_assessment.get("uncertain"))
    match_candidates = [
        str(cand.get("name", "")).strip()
        for cand in supplier_assessment.get("candidates", []) or []
        if str(cand.get("name", "")).strip()
    ]
    match_reason = str(supplier_assessment.get("reason", "") or "")
    match_kind = "supplier" if match_uncertain else ""
    # Inlärd koppling: hittade den vanliga bedömningen ingen
    # leverantör alls får appen använda det den lärt sig av
    # användarens egna matchningar — ett kännetecken (org.nr/
    # bankgiro) som upprepade gånger bekräftats för EN leverantör
    # kopplar fakturan dit. Flera kvalificerade leverantörer är
    # däremot en fråga, aldrig en gissning. En redan osäker
    # bedömning löses aldrig upp av inlärningen i tysthet.
    learned_connect = ""
    if not supplier and not match_uncertain and match_learning:
        learned = learned_supplier_candidates(
            text or "", match_learning
        )
        if len(learned) == 1:
            supplier = learned[0]
            learned_connect = supplier
            log.info(
                "SCAN_IMPORT: inlärd koppling — fakturan kopplas "
                "till %s på sina kännetecken (appen har lärt sig "
                "leverantören av användarens matchningar)",
                supplier,
            )
        elif len(learned) > 1:
            match_uncertain = True
            match_candidates = learned
            match_reason = "learned_ambiguous"
            match_kind = "supplier"
    template_name = ""
    template_fields: list[str] = []
    template_key = ""

    if templates:
        template = None
        selected_region_texts = region_texts
        if supplier and not match_uncertain:
            candidate_names = supplier_template_candidate_names(
                templates, supplier, suppliers
            )
            if len(candidate_names) > 1:
                match_uncertain = True
                match_candidates = candidate_names
                match_reason = "template_ambiguous"
                match_kind = "template"
            elif len(candidate_names) == 1:
                template_key = candidate_names[0]
                template = templates.get(template_key)

        # Regionsmallar (användaren har pekat ut värdena på
        # fakturabilden) bedöms kandidat för kandidat. Först när
        # exakt EN mall själv läser fakturanummer + att betala
        # får rutorna identifiera leverantören; flera sådana
        # träffar är en fråga till användaren, inte första bästa.
        if region_texts or region_texts_by_template:
            credit = is_credit_note(text or "")
            region_claims: list[tuple[str, dict, dict, dict]] = []
            for cand_name, cand in templates.items():
                if not isinstance(cand, dict):
                    continue
                cand_texts = None
                if region_texts_by_template is not None:
                    cand_texts = region_texts_by_template.get(
                        str(cand_name)
                    )
                elif template_key and str(cand_name) == template_key:
                    # Enskild region_texts hör till den redan valda
                    # mallen — den får aldrig prövas mot alla mallar.
                    cand_texts = region_texts
                elif len(templates) == 1:
                    cand_texts = region_texts
                if not cand_texts:
                    continue
                found_regions = template_values_from_regions(
                    cand, cand_texts
                )
                if found_regions.get("invoice_number") and (
                    found_regions.get("total_amount") or credit
                ):
                    region_claims.append((
                        str(cand_name), cand, found_regions,
                        dict(cand_texts),
                    ))
            if len(region_claims) > 1:
                match_uncertain = True
                match_candidates = [
                    claim[0] for claim in region_claims
                ]
                match_reason = "region_ambiguous"
                match_kind = "template"
                template = None
                template_key = ""
            elif len(region_claims) == 1:
                claim_name, claim_template, _found, claim_texts = (
                    region_claims[0]
                )
                if supplier and not _same_registered_supplier_name(
                    supplier, claim_name, suppliers
                ):
                    match_uncertain = True
                    match_candidates = [supplier, claim_name]
                    match_reason = "competing"
                    match_kind = "template"
                    template = None
                    template_key = ""
                else:
                    template = claim_template
                    template_key = claim_name
                    selected_region_texts = claim_texts
                    if not supplier:
                        supplier = claim_name
                    # En enda regionsmall som själv läser de
                    # avgörande fälten är uttrycklig, utpekad
                    # bevisning — den får avgöra även om bara
                    # namnet i löptexten var svagt/tvetydigt.
                    match_uncertain = False
                    match_candidates = []
                    match_reason = ""
                    match_kind = ""
        if template:
            found = apply_template(text or "", template)
            if selected_region_texts:
                # Utpekade rutor på fakturabilden vinner över
                # etikettläsningen — platsen är explicit angiven.
                found.update(
                    template_values_from_regions(
                        template, selected_region_texts
                    )
                )
            for field, value in found.items():
                if field == "total_amount":
                    total = float(value)
                elif field == "invoice_number":
                    inv_nr = str(value)
                elif field == "ocr":
                    ocr = str(value)
                elif field == "date":
                    date = str(value)
                elif field == "due_date":
                    due = str(value)
                template_fields.append(field)
            if found.get("invoice_number") and (
                found.get("total_amount") or is_credit_note(text or "")
            ):
                # Mallanspråk kräver att mallen SJÄLV läser
                # fakturanummer + att betala (kreditnotor:
                # Tillgodo-vägen i stället). En mall som bara
                # fyller enstaka fält får aldrig låta en generisk
                # beloppsgissning registreras automatiskt —
                # delträffarna visas för granskning, men filen
                # parkeras som mallös tills mallen verkligen tar den.
                template_name = supplier

    if not template_name:
        builtin_candidates = _builtin_format_candidates(text or "")
        if len(builtin_candidates) > 1:
            # Flera inbyggda format känner igen olika delar av
            # samma faktura. Att bara ta det första i listan vore
            # en gissning — lämna valet till användaren.
            match_uncertain = True
            match_candidates = [
                str(cand["name"]) for cand in builtin_candidates
            ]
            match_reason = "builtin_ambiguous"
            match_kind = "template"
        elif len(builtin_candidates) == 1:
            builtin_candidate = builtin_candidates[0]
            bname = str(builtin_candidate["name"])
            btmpl = builtin_candidate["template"]
            found = apply_template(text or "", btmpl)
            # Strikt krav: fakturanummer OCH att betala måste
            # komma ur själva formatet (på kreditnotor ger
            # Tillgodo-vägen beloppet i stället). Att betala
            # måste dessutom stå på SAMMA RAD som sin etikett:
            # i en radvis/kolumnbruten text (rubrikrad följd av
            # värderad) är första beloppet efter etiketten en
            # annan kolumn (netto/exkl. moms) och får aldrig
            # bokföras. Sådan text parkeras som förut — gissade
            # värden registreras aldrig automatiskt.
            total_label = str(
                btmpl.get("fields", {})
                .get("total_amount", {}).get("label", "")
            )
            # Att betala verifieras mot sin rad: parvis layout
            # lägger beloppet på etikettens egen rad, kolumn-
            # layouten på värderaden under rubriken. Annat
            # innehåll mellan etikett och belopp (fel kolumn)
            # accepteras aldrig.
            total_ok = (
                "total_amount" in found
                and (
                    _label_same_line_amount(text or "", total_label)
                    == found["total_amount"]
                    or _label_below_amount(text or "", total_label)
                    == found["total_amount"]
                )
            )
            builtin_claim = "invoice_number" in found and (
                total_ok or is_credit_note(text or "")
            )
            if supplier and not _builtin_format_matches_supplier(
                builtin_candidate["format"], supplier
            ):
                # Det inbyggda formatet pekar på en annan
                # leverantör än den starka registerträffen.
                # Vilken som har rätt får användaren avgöra.
                match_uncertain = True
                match_candidates = [supplier, bname]
                match_reason = "competing"
                match_kind = "template"
            elif builtin_claim:
                for field, value in found.items():
                    if field == "total_amount":
                        total = float(value)
                    elif field == "invoice_number":
                        inv_nr = str(value)
                    elif field == "ocr":
                        ocr = str(value)
                    elif field == "date":
                        date = str(value)
                    elif field == "due_date":
                        due = str(value)
                    template_fields.append(field)
                if not supplier:
                    supplier = bname
                template_name = supplier

    missing = [
        label for ok, label in (
            (total > 0, "belopp"),
            (bool(inv_nr), "fakturanummer"),
            (bool(supplier), "leverantör"),
        ) if not ok
    ]
    # Kreditfaktura/-nota: beloppet ska MINSKA att betala,
    # aldrig öka den. Missbedömningen sker lätt annars eftersom
    # både heuristiken och mallarna bara ser nakna siffror.
    if total > 0 and is_credit_note(text or ""):
        total = -total
    result: dict[str, Any] = {
        "total_amount": total,
        "invoice_number": inv_nr,
        "ocr": ocr,
        "date": date,
        "due_date": due,
        "supplier": supplier,
        "missing": missing,
    }
    if template_name:
        result["template"] = template_name
        result["template_fields"] = template_fields
    # Matchbedömningen följer alltid med resultatet. Vid osäker
    # leverantörs- eller mallmatchning får anroparen därmed veta
    # exakt vilka alternativ som finns och kan fråga användaren,
    # i stället för att bara se en tom leverantör eller en fil
    # som parkerats utan förklaring.
    if match_uncertain and match_kind == "supplier":
        result["supplier_match"] = {
            "status": "uncertain",
            "supplier": "",
            "candidates": supplier_assessment.get("candidates", []),
            "uncertain": True,
            "reason": match_reason,
        }
    elif supplier:
        result["supplier_match"] = {
            "status": "matched",
            "supplier": supplier,
            "candidates": supplier_assessment.get("candidates", []),
            "uncertain": False,
            "reason": "",
        }
    else:
        result["supplier_match"] = supplier_assessment
    if learned_connect:
        # Inlärd koppling märks som sådan — den är varken en
        # registerträff eller en gissning, utan frukten av
        # användarens egna bekräftade matchningar.
        result["supplier_match"] = {
            "status": "matched", "supplier": learned_connect,
            "candidates": [], "uncertain": False,
            "reason": "learned",
        }
    result["template_match"] = {
        "status": (
            "uncertain" if match_uncertain and match_kind != "supplier"
            else ("matched" if template_name else "none")
        ),
        "template": template_name,
        "candidates": match_candidates if match_uncertain else [],
        "uncertain": bool(match_uncertain and match_kind != "supplier"),
        "reason": match_reason if match_kind != "supplier" else "",
    }
    if match_learning and template_name:
        try:
            confirmed_template = (
                (templates or {}).get(template_key)
                if template_key
                else find_template(templates or {}, template_name, suppliers)
            )
            confirmations = template_confirmation_entry(
                match_learning, template_name, confirmed_template
            )
            if confirmed_template and confirmations:
                result["template_match"]["confirmed"] = int(
                    confirmations.get("confirmed", 0) or 0
                )
        except Exception:
            pass
    if match_uncertain:
        result["match_uncertain"] = True
        result["match_candidates"] = match_candidates
        result["match_reason"] = match_reason
        result["match_kind"] = match_kind
    # Kontrollerna är rådgivande: de ändrar aldrig värdena,
    # men flaggar räkne-/datumfel för granskning och logg.
    result["math_check"] = invoice_math_check(text or "", total)
    result["date_check"] = invoice_date_check(date, due)
    return apply_supplier_ocr_rule(
        assess_invoice_payment_details(result, text or "", suppliers),
        suppliers,
    )


def _apply_supplier_logo_match(
    result: dict[str, Any],
    path: Any,
    text: str,
    templates: dict,
    match_learning: dict | None,
) -> dict[str, Any]:
    """Använd sparade PDF-logotyper som kandidater, aldrig som gissning.

    Innan samma leverantör bekräftats fem gånger och logotypen setts
    i minst två manuella bekräftelser blir logotypen en fråga. En
    redan osäker text-/mallträff blir aldrig tyst säker av loggan.
    """
    candidates = supplier_logo_match_candidates(path, templates)
    if not candidates:
        return result
    # Transient evidence used by the match dialog for real invoice-logo
    # thumbnails. It is not a confirmation, save, or learning signal.
    result["_logo_match_candidates"] = candidates

    logo_names: list[str] = []
    for candidate in candidates:
        name = str(candidate.get("name", "") or "").strip()
        if name and not any(_names_match(name, old) for old in logo_names):
            logo_names.append(name)

    current = str(result.get("supplier", "") or "").strip()
    if result.get("match_uncertain"):
        existing: list[dict[str, Any]] = []
        for raw in result.get("match_candidates", []) or []:
            if isinstance(raw, dict):
                existing.append(raw)
            elif str(raw or "").strip():
                existing.append({"name": str(raw).strip()})
        additions = [
            {
                "name": str(candidate["name"]),
                "score": max(
                    6,
                    25 - int(candidate.get("distance", 999)),
                ),
                "signals": ["supplier_logo"],
            }
            for candidate in candidates
        ]
        merged = _merge_match_candidates(existing, additions)
        result["match_candidates"] = merged
        supplier_match = dict(result.get("supplier_match", {}) or {})
        supplier_match.update({
            "status": "uncertain", "supplier": "",
            "candidates": merged, "uncertain": True,
        })
        if logo_names and not supplier_match.get("reason"):
            supplier_match["reason"] = "supplier_logo"
        result["supplier_match"] = supplier_match
        return result

    conflicts = [
        name for name in logo_names
        if current and not _names_match(name, current)
    ]
    if current and not conflicts:
        # Text/BG och logotyp bekräftar samma leverantör.
        return result

    if current and conflicts:
        possible = [current, *conflicts]
        reason = "logo_conflict"
    else:
        possible = logo_names
        reason = "supplier_logo"

    # En enda unik, redan inlärd logotyp får koppla automatiskt —
    # men bara vid mycket stark likhet och utan annan träff.
    if (
        not current and len(possible) == 1
        and int(candidates[0].get("distance", 999))
        <= SUPPLIER_LOGO_AUTO_MAX_DISTANCE
    ):
        supplier = possible[0]
        candidate = next(
            (cand for cand in candidates
             if _names_match(str(cand.get("name", "")), supplier)),
            None,
        )
        signature = str(candidate.get("dhash", "")) if candidate else ""
        if learned_supplier_logo(match_learning, supplier, signature):
            template_names = template_candidate_names(templates, supplier)
            if len(template_names) == 1:
                template_name = template_names[0]
                template = templates.get(template_name, {})
                found = template_values(path, text, template)
                for field in (
                    "invoice_number", "total_amount", "date",
                    "due_date", "ocr",
                ):
                    if found.get(field) not in (None, "", 0, 0.0):
                        result[field] = found[field]
                if result.get("total_amount") and is_credit_note(text):
                    result["total_amount"] = -abs(
                        float(result["total_amount"])
                    )
                result["supplier"] = supplier
                result["template"] = template_name
                result["template_fields"] = list(found)
                result["math_check"] = invoice_math_check(
                    text or "", float(result.get("total_amount") or 0)
                )
                result["date_check"] = invoice_date_check(
                    str(result.get("date", "") or ""),
                    str(result.get("due_date", "") or ""),
                )
                result["supplier_match"] = {
                    "status": "matched", "supplier": supplier,
                    "candidates": [], "uncertain": False,
                    "reason": "learned_logo",
                }
                result["template_match"] = {
                    "status": "matched", "template": template_name,
                    "candidates": [], "uncertain": False,
                    "reason": "learned_logo",
                }
                result.pop("match_uncertain", None)
                result.pop("match_candidates", None)
                result.pop("match_reason", None)
                result.pop("match_kind", None)
                result["missing"] = [
                    label for ok, label in (
                        (float(result.get("total_amount") or 0) != 0,
                         "belopp"),
                        (bool(result.get("invoice_number")),
                         "fakturanummer"),
                        (bool(supplier), "leverantör"),
                    ) if not ok
                ]
                log.info(
                    "SCAN_IMPORT: inlärd logotyp kopplade fakturan "
                    "till %s (starkt hash-avstånd %s)",
                    supplier, candidate.get("distance"),
                )
                return result

    # Alla ej inlärda eller konkurrerande logoträffar ska avgöras
    # av användaren — inte av den första kandidaten i listan.
    logo_additions = [
        {
            "name": str(candidate["name"]),
            "score": max(6, 25 - int(candidate.get("distance", 999))),
            "signals": ["supplier_logo"],
        }
        for candidate in candidates
    ]
    merged = _merge_match_candidates(
        [{"name": current}] if current else [],
        logo_additions,
    )
    result["supplier"] = ""
    result["match_uncertain"] = True
    result["match_candidates"] = merged
    result["match_reason"] = reason
    result["match_kind"] = "supplier"
    result["supplier_match"] = {
        "status": "uncertain", "supplier": "",
        "candidates": merged, "uncertain": True,
        "reason": reason,
    }
    result["missing"] = [
        label for ok, label in (
            (float(result.get("total_amount") or 0) != 0, "belopp"),
            (bool(result.get("invoice_number")), "fakturanummer"),
            (False, "leverantör"),
        ) if not ok
    ]
    return result


def parse_invoice_file(
    path: Any,
    text: str,
    suppliers: list[dict] | None = None,
    templates: dict | None = None,
    match_learning: dict | None = None,
) -> dict[str, Any]:
    """Tolkning av en FIL: löptext + eventuella regionsmallar.

    Mallar vars fält pekar ut rutor på fakturabilden (region)
    läses ur själva filen (textlager i rutan, annars OCR) och
    får avgöra fälten. Första mallen vars rutor ger ett
    fakturanummer eller ett att betala-belopp används — resten
    av tolkningen är exakt densamma som för ren text.

    `match_learning` (inlärningsminnet ur match_memory.json)
    används bara av flersidighetsvakten: en leverantör vars
    flersidiga fakturor bekräftats upprepade gånger av användaren
    OCH vars total dessutom stäms av mot texten får passera utan
    ny bekräftelse — alla andra flersidiga fakturor flaggas så
    att appen ber användaren matcha dem manuellt (se
    _apply_multipage_guard).
    """
    tpl = templates or {}
    region_texts_by_template: dict[str, dict] = {}
    for _name, cand in tpl.items():
        if not isinstance(cand, dict):
            continue
        fields = cand.get("fields", {}) or {}
        if not any(
            isinstance(spec, dict) and spec.get("region")
            for spec in fields.values()
        ):
            continue
        region_texts_by_template[str(_name)] = extract_region_texts(
            path, cand
        )
    if region_texts_by_template:
        # Varje regionsmall bedöms för sig: exakt en mall som
        # själv läser fakturanummer + att betala får avgöra.
        # Flera träffar blir en fråga till användaren — aldrig
        # första mallen i listan.
        result = parse_invoice_text(
            text, suppliers, tpl,
            region_texts_by_template=region_texts_by_template,
            match_learning=match_learning,
        )
        result = _apply_supplier_logo_match(
            result, path, text, tpl, match_learning
        )
        result = _apply_multipage_guard(
            result, path, text, match_learning
        )
        return apply_supplier_ocr_rule(
            assess_invoice_payment_details(
                result, text, suppliers,
                details=result.get("invoice_payment_details"),
            ),
            suppliers,
        )
    result = _parse_with_reader_fallback(
        path, text, suppliers, tpl, match_learning=match_learning
    )
    result = _apply_supplier_logo_match(
        result, path, text, tpl, match_learning
    )
    result = _apply_multipage_guard(result, path, text, match_learning)
    return apply_supplier_ocr_rule(
        assess_invoice_payment_details(
            result, text, suppliers,
            details=result.get("invoice_payment_details"),
        ),
        suppliers,
    )


def _parse_with_reader_fallback(
    path: Any,
    text: str,
    suppliers: list[dict] | None,
    templates: dict,
    match_learning: dict | None = None,
) -> dict[str, Any]:
    """Tolka texten; utan mallträff prövas övriga PDF-läsares text.

    En leverantörsmall (egen eller inbyggd verifierad) som känner
    igen fakturan på ett alternativt textuttag vinner ALLTID över
    en mallös tolkning — aldrig tvärtom, och de strikta
    anspråksreglerna gäller oförändrade för varje uttag. Säger
    ingen läsares text något om formatet gäller den första
    tolkningen orörd (filen parkeras som förut).
    """
    result = parse_invoice_text(
        text, suppliers, templates, match_learning=match_learning
    )
    if result.get("template") or result.get("match_uncertain"):
        # Ett osäkert resultat får aldrig ersättas av ett annat
        # textuttag i tysthet — osäkerheten ska nå användaren.
        return result
    try:
        p = Path(path) if path else None
    except Exception:
        p = None
    if p is None or p.suffix.lower() != ".pdf":
        return result
    seen = re.sub(r"\s+", " ", text or "").strip()
    for alt_text, method in extract_pdf_texts(p):
        if re.sub(r"\s+", " ", alt_text).strip() == seen:
            continue
        alt = parse_invoice_text(
            alt_text, suppliers, templates,
            match_learning=match_learning,
        )
        learned_supplier = (
            (alt.get("supplier_match") or {}).get("reason") == "learned"
        )
        if not alt.get("match_uncertain") and (
            alt.get("template") or learned_supplier
        ):
            log.info(
                "SCAN_IMPORT: %s kände igen fakturan via "
                "alternativt textuttag (%s): %s",
                "inlärningen" if learned_supplier else "mallen",
                method,
                alt.get("supplier") or alt.get("template"),
            )
            return alt
    return result


def _multipage_total_corroborated(
    result: dict, text: str, learning: dict | None
) -> bool:
    """Får en flersidig total passera utan användarens ögon?

    Bara när appen LÄRT SIG leverantören av användarens egna
    bekräftelser (≥2 bekräftade flersidiga fakturor) OCH den
    generiska etikettläsningen av hela texten ger exakt samma
    total OCH räknekontrollen inte protesterar. Allt annat är
    en gissning i en flersidig faktura — och gissningar om
    delsummor på sida 1 är precis felet detta vaktar mot.
    """
    if not learning:
        return False
    name = str(
        result.get("supplier") or result.get("template") or ""
    ).strip()
    if not name or not learning_graduated(learning, name):
        return False
    try:
        total = float(result.get("total_amount") or 0)
    except (TypeError, ValueError):
        return False
    if total <= 0:
        return False
    if abs(parse_total(text or "") - total) > 0.005:
        return False
    if (result.get("math_check") or {}).get("status") == "mismatch":
        return False
    return True


def _apply_multipage_guard(
    result: dict, path: Any, text: str,
    learning: dict | None = None,
) -> dict:
    """Flersidig faktura = användaren bekräftar matchningen.

    Sidtexterna limmas ihop utan sidmarkörer, så tolkaren kan
    aldrig bevisa att ett avläst belopp är slutsumman och inte
    en delsumma på en tidig sida (921040: 857,25 på sida 1 mot
    13 480 på sida 3). Därför flaggas varje komplett tolkad
    flersidig faktura som OSÄKER matchning: Import frågar och
    bevakningen parkerar i stället för att auto-registrera.
    Enda undantaget är den inlärda, avstämda leverantören (se
    _multipage_total_corroborated) — det är så appen blir
    bättre av varje manuell matchning utan att någonsin gissa.
    """
    if not isinstance(result, dict):
        return result
    try:
        pages = page_image_count(path)
    except Exception:
        pages = 0
    if pages:
        result["pages"] = pages
    if pages < 2 or result.get("match_uncertain"):
        return result
    try:
        total = float(result.get("total_amount") or 0)
    except (TypeError, ValueError):
        total = 0.0
    name = str(
        result.get("supplier") or result.get("template") or ""
    ).strip()
    if total <= 0 or not name:
        return result
    if _multipage_total_corroborated(result, text, learning):
        return result
    result["match_uncertain"] = True
    result["match_kind"] = "multipage"
    result["match_reason"] = "multipage"
    result["match_candidates"] = [name]
    result["supplier_match"] = {
        "status": "uncertain", "supplier": "",
        "candidates": [{"name": name}], "uncertain": True,
        "reason": "multipage",
    }
    if result.get("template"):
        result["template_match"] = {
            "status": "uncertain", "template": "",
            "candidates": [name], "uncertain": True,
            "reason": "multipage",
        }
    log.info(
        "SCAN_IMPORT: flersidig faktura (%d sidor, %s) — "
        "användaren får bekräfta matchningen i stället för "
        "att totalen litas på blint",
        pages, name,
    )
    return result


def _diag_preview(text: str, limit: int = 320) -> str:
    """Första biten av en text för felsökningspaketet."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + " …"


def _diag_fill_fields(
    diag: dict[str, Any], fields_spec: Any, found: dict
) -> None:
    """Fyll diag["fields"]/["failed"] ur en malls träffar."""
    fields: dict[str, Any] = {}
    failed: list[str] = []
    for field in (fields_spec or {}):
        if field not in TEMPLATE_FIELD_KINDS:
            continue
        value = found.get(field)
        fields[field] = value
        if value in (None, ""):
            failed.append(field)
    diag["fields"] = fields
    diag["failed"] = failed


def diagnose_invoice_file(
    path: Any,
    suppliers: list[dict] | None = None,
    templates: dict | None = None,
) -> list[dict[str, Any]]:
    """Malldiagnos per textuttag, för felsökningspaketet.

    Varje uttag gås igenom för sig (varje PDF-läsare för sig,
    annars filens enda textkälla): vilken mall var kandidat
    (egen mall eller inbyggt verifierat format), vilka av dess
    fält som hittades, och vilket krav som brast — inklusive
    om det lästa att betala-beloppet stämmer mot etikettens
    egen rad/värderaden. Diagnosen är rent läsande: den
    tolkar ingenting vidare och gissar ingenting. Returnerar
    en post per uttag; nycklarna "fields" (fält → värde/None),
    "failed" (fält som saknas), "total_verified" och
    "claimed" bär facit, "preview" första textbiten.
    """
    tpl = templates or {}
    try:
        p = Path(path) if path else None
    except Exception:
        p = None
    texts: list[tuple[str, str]] = []
    if p is not None and p.suffix.lower() == ".pdf":
        texts = extract_pdf_texts(p)
    if not texts:
        if p is not None:
            texts = [extract_text(p)]
        else:
            texts = [("", "—")]
    out: list[dict[str, Any]] = []
    region_cache: dict[int, dict] = {}
    for text, method in texts:
        text = text or ""
        parsed = parse_invoice_text(text, suppliers, tpl)
        diag: dict[str, Any] = {
            "method": method,
            "chars": len(text),
            "preview": _diag_preview(text),
            "invoice_number": parsed.get("invoice_number", ""),
            "total_amount": parsed.get("total_amount", 0),
            "date": parsed.get("date", ""),
            "due_date": parsed.get("due_date", ""),
            "missing": list(parsed.get("missing", []) or []),
            "template": parsed.get("template", ""),
            "candidate": "",
            "candidate_kind": "",
            "fields": {},
            "failed": [],
            "total_verified": None,
            "claimed": bool(parsed.get("template")),
            "note": "",
        }
        # Kandidat 1: egen mall (samma matchning som tolkningen).
        cand_name, cand_tpl = "", None
        if tpl:
            sup = match_supplier(text, suppliers or [])
            if not sup:
                sup = match_supplier(
                    text, [{"name": n} for n in tpl.keys()]
                )
            if sup:
                for key, val in tpl.items():
                    if not isinstance(val, dict):
                        continue
                    try:
                        if find_template({key: val}, sup, suppliers) is val:
                            cand_name, cand_tpl = str(key), val
                            break
                    except Exception:
                        continue
        if cand_tpl is not None:
            diag["candidate"] = cand_name
            diag["candidate_kind"] = "egen mall"
            found = apply_template(text, cand_tpl)
            spec = cand_tpl.get("fields", {}) or {}
            if p is not None and any(
                isinstance(s, dict) and s.get("region")
                for s in spec.values()
            ):
                # Regionsmall: värdena ligger i utpekade bild-
                # rutor, inte i löptexten — läs dem ur filen.
                cache_key = id(cand_tpl)
                if cache_key not in region_cache:
                    region_cache[cache_key] = (
                        template_values_from_regions(
                            cand_tpl, extract_region_texts(p, cand_tpl)
                        )
                    )
                found.update(region_cache[cache_key])
            _diag_fill_fields(diag, spec, found)
            if found.get("invoice_number") and (
                found.get("total_amount") or is_credit_note(text)
            ):
                # Samma anspråksregel som tolkningen: mallen
                # måste själv läsa fakturanummer + att betala.
                diag["claimed"] = True
        else:
            # Kandidat 2: inbyggt verifierat format.
            builtin = builtin_template_for(text)
            if builtin:
                bname, btmpl = builtin
                diag["candidate"] = bname
                diag["candidate_kind"] = "inbyggt format"
                found = apply_template(text, btmpl)
                if "total_amount" in found:
                    label = str(
                        btmpl.get("fields", {})
                        .get("total_amount", {})
                        .get("label", "")
                    )
                    tot = found["total_amount"]
                    diag["total_verified"] = bool(
                        _label_same_line_amount(text, label) == tot
                        or _label_below_amount(text, label) == tot
                        or is_credit_note(text)
                    )
                _diag_fill_fields(
                    diag, btmpl.get("fields", {}), found
                )
                if (
                    diag["total_verified"] is False
                    and "total_amount" in found
                    and "total_amount" not in diag["failed"]
                ):
                    diag["failed"].append("total_amount")
            else:
                diag["note"] = (
                    "inget format kände igen leverantören "
                    "(org.nr/bankgiro/tryckt namn saknas i texten)"
                )
        out.append(diag)
    return out


#: Etikettkandidater för mallreparation, per fält: vanliga
#: formuleringar som prövas i ordning mot fakturans egen text.
_REPAIR_LABELS: dict[str, tuple[str, ...]] = {
    "invoice_number": (
        "Fakturanr.", "Fakturanr", "Faktura nr", "Fakturanummer",
        "Faktura-nr", "Nummer", "Dokumentnummer", "Invoice number",
    ),
    "total_amount": (
        "Att betala", "Summa att betala", "Totalt att betala",
        "Att Betala (SEK)", "ATT BETALA", "Att betala SEK",
        "Totalt", "Slutsumma", "Amount due",
    ),
    "date": (
        "Fakturadatum", "Faktura datum", "Utfärdandedatum",
        "Utfärdad", "Datum (tax point)", "Datum", "Invoice date",
    ),
    "due_date": (
        "Förfallodatum", "Förfaller", "Betalas senast",
        "Förfallodag", "Due date",
    ),
    "ocr": ("OCR-nummer", "OCR nummer", "OCR", "Referens"),
}


def suggest_template_repairs(
    text: str, template: dict
) -> list[dict[str, Any]]:
    """Föreslå ny etikett för mallfält som slutat träffa.

    Malldriftsassistenten: leverantören har bytt formulering
    på fakturan, så mallens etikett hittar inget längre. För
    varje sådant fält prövas vanliga alternativa etiketter mot
    fakturans egen text; första kandidaten som faktiskt läser
    ett värde av rätt typ föreslås, med värdet som bevis.
    Fält mallen fortfarande läser rörs aldrig, och rutfält
    (regioner på bilden) föreslås inga etiketter för — dem
    pekar användaren ut själv. Returnerar en lista med
    {field, old_label, new_label, value}; appen frågar alltid
    innan något sparas.
    """
    fields = (template or {}).get("fields", {}) or {}
    if not text or not fields:
        return []
    found = apply_template(text, template)
    suggestions: list[dict[str, Any]] = []
    for field, spec in fields.items():
        kind = TEMPLATE_FIELD_KINDS.get(field)
        if kind is None or not isinstance(spec, dict):
            continue
        if spec.get("region"):
            continue
        if field in found:
            continue
        old_label = str(spec.get("label", "") or "")
        for cand in _REPAIR_LABELS.get(field, ()):
            if cand.lower() == old_label.strip().lower():
                continue
            raw = extract_with_label(text, cand, kind)
            below = False
            if not raw:
                raw = _extract_below_label(text, cand, kind)
                below = bool(raw)
            if not raw:
                continue
            value: Any = float(raw) if field == "total_amount" else raw
            suggestions.append({
                "field": field,
                "old_label": old_label,
                "new_label": cand,
                "value": value,
                "below": below,
            })
            break
    return suggestions


def template_field_label_candidates(
    text: str, field: str
) -> list[dict[str, Any]]:
    """Alla etikett/värde-kandidater för ett fält, utan att välja åt användaren."""
    kind = TEMPLATE_FIELD_KINDS.get(field)
    if not text or kind is None:
        return []
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for label in _REPAIR_LABELS.get(field, ()):
        # "Referens" kan avse kundens beställningsreferens, inte OCR.
        if field == "ocr" and _fold_text(label) == "referens":
            continue
        raw = extract_with_label(text, label, kind)
        below = False
        if not raw:
            raw = _extract_below_label(text, label, kind)
            below = bool(raw)
        if not raw:
            continue
        value: Any = float(raw) if field == "total_amount" else raw
        value_key = (
            f"{float(value):.2f}"
            if field == "total_amount"
            else str(value).strip().casefold()
        )
        identity = (_fold_text(label), value_key)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append({
            "field": field,
            "label": label,
            "value": value,
            "below": below,
        })
    return candidates


def suggest_template_fields(
    text: str, template: dict | None = None
) -> list[dict[str, Any]]:
    """Föreslå etikettregler när kandidaterna ger samma lästa värde.

    Fungerande fält och bildregioner lämnas orörda. Om olika etiketter
    ger olika värden returneras inget automatiskt för fältet; anroparen
    kan visa kandidaterna för ett uttryckligt användarval. Förslag sparas
    aldrig här.
    """
    if not text:
        return []
    raw_fields = (
        (template or {}).get("fields", {})
        if isinstance(template, dict) else {}
    )
    fields = raw_fields if isinstance(raw_fields, dict) else {}
    working = {"fields": fields}
    found = apply_template(text, working) if fields else {}
    suggestions: list[dict[str, Any]] = []

    for field in TEMPLATE_FIELD_KINDS:
        spec = fields.get(field, {})
        if isinstance(spec, dict) and spec.get("region"):
            continue
        if field in found:
            continue
        candidates = template_field_label_candidates(text, field)
        if not candidates:
            continue
        value_keys = {
            (
                f"{float(candidate['value']):.2f}"
                if field == "total_amount"
                else str(candidate["value"]).strip().casefold()
            )
            for candidate in candidates
        }
        if len(value_keys) != 1:
            continue
        # Likvärdiga träffar: välj den mest särskiljande etiketten.
        chosen = max(
            enumerate(candidates),
            key=lambda item: (
                len(_fold_text(item[1]["label"])), -item[0]
            ),
        )[1]
        suggestions.append(dict(chosen))
    return suggestions


# ═════════════════════════════════════════════════════════════════════
#  LEVERANTÖRSMALLAR (egen layout per leverantör)
#
#  Fakturor har olika layout per leverantör. En mall talar om för
#  tolkaren VILKEN ETIKETT som står framför varje värde på just den
#  leverantörens fakturor, t.ex. {"label": "Att betala", ...}.
#  Användaren skapar mallen i Import-fliken genom att markera ett
#  värde i fakturatexten — etiketten härleds automatiskt.
#
#  Format (data/invoice_templates.json):
#    {"Elgiganten AB": {"fields": {
#        "total_amount": {"label": "Att betala"},
#        "invoice_number": {"label": "Fakturanr"},
#        "due_date": {"label": "Förfallodatum"}}}}
# ═════════════════════════════════════════════════════════════════════

#: Fält som kan ingå i en mall → extraktor-typ.
TEMPLATE_FIELD_KINDS: dict[str, str] = {
    "invoice_number": "token",
    "total_amount": "amount",
    "date": "date",
    "due_date": "date",
    "ocr": "digits",
}

_AMOUNT_AFTER = re.compile(
    r"\d{1,3}(?:[ .\u00a0]\d{3})+(?:[,.]\d{2})?|\d+[,.]\d{2}"
)
_DATE_AFTER = re.compile(r"\d{4}[-./]?\d{2}[-./]?\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}")
_TOKEN_AFTER = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/.]{1,29}")
#: Ett fakturanummer är EN token (inga mellanslag) — annars följer
#: resten av raden med, eller nästa kolumnrubrik vid radvis text.
_INVOICE_NR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/.]*")
#: Ord som aldrig är ett fakturanummer (kolumnrubriker vid radvis
#: extraktion: "Fakturanr. Fakturadatum Kundnr." → nästa rubrik).
_INVOICE_NR_STOPWORDS = frozenset({
    "FAKTURADATUM", "FAKTURANR", "FAKTURANUMMER", "KUNDNR",
    "KUNDNUMMER", "ORDERNR", "ORDERNUMMER", "DATUM", "SIDA",
})
_DIGITS_AFTER = re.compile(r"\d[\d \-]{4,28}\d")


def extract_with_label(text: str, label: str, kind: str) -> str:
    """
    Hittar etiketten i texten (skiftlägesoberoende) och extraherar
    värdet av rätt typ EFTER etiketten — först på samma rad, annars
    inom de närmaste 160 tecknen. Returnerar strängvärde (belopp
    som float-sträng, datum som YYYY-MM-DD) eller "".

    För BELOPP vinner den SISTA förekomsten i dokumentet: i en
    flersidig faktura kan delsummor stå under samma etikett på
    tidigare sidor, medan dokumentets slutsumma alltid står sist.
    Övriga typer (nummer/datum/OCR) behåller första träffen —
    sidhuvuden upprepar dem oförändrade sida för sida.
    """
    if not text or not label:
        return ""
    flat = re.sub(r"[ \t]+", " ", text)
    lab = re.sub(r"\s+", " ", str(label)).strip().rstrip(":#").strip()
    if not lab:
        return ""
    last_hit = ""
    for m in re.finditer(re.escape(lab), flat, re.IGNORECASE):
        window = flat[m.end(): m.end() + 160]
        same_line = window.split("\n", 1)[0]
        hit = _extract_kind(same_line, kind, m.group(0))
        if not hit and not (same_line.strip() and kind != "token") \
                and kind != "token":
            hit = _extract_kind(window, kind, m.group(0))
        if hit:
            if kind != "amount":
                return hit
            # Belopp: kom ihåg träffen men fortsätt — en senare
            # förekomst i dokumentet är slutsumman (se docstring).
            last_hit = hit
    return last_hit


def _extract_kind(chunk: str, kind: str, label: str = "") -> str:
    if not chunk:
        return ""
    if kind == "token":
        parts = chunk.strip().lstrip(":#").strip().split(None, 1)
        line = parts[0] if parts else ""
        if label and line.rstrip(":#").lower() == label.rstrip(":#").lower():
            # Fönsterformen direkt efter etiketten ("Fakturanr:
            # 906178"): första biten ÄR rubriken — nästa bit är
            # värdet. Bara när chunk börjar med etiketten.
            rest = chunk[len(line):]
            if not rest or not (rest[0].isalnum()):
                parts = rest.strip().split(None, 1)
                line = parts[0] if parts else ""
        tok = _INVOICE_NR_RE.match(line)
        cand = tok.group(0) if tok else ""
        if len(cand) >= 2 and cand.upper() not in _INVOICE_NR_STOPWORDS:
            return cand
        # Siffrigt nummer separerat med streck/snedstreck
        # ("NL-2026-0771" via "Er ref hos oss"/"Vår referens").
        num = re.match(r"\d[\d\-/]*\d|\d", line)
        if num and len(num.group(0)) >= 4:
            return num.group(0)
        return ""
    if kind == "amount":
        m = _AMOUNT_AFTER.search(chunk)
        if m:
            v = _norm_amount(m.group(0))
            if v > 0:
                return f"{v:.2f}"
        return ""
    if kind == "date":
        m = _DATE_AFTER.search(chunk)
        return _parse_date(m.group(0)) if m else ""
    if kind == "digits":
        m = _DIGITS_AFTER.search(chunk)
        return re.sub(r"\s", "", m.group(0)) if m else ""
    m = _TOKEN_AFTER.search(chunk)
    return m.group(0).strip(" .") if m else ""


#: En datumtoken ("2024-05-08") får aldrig tas för ett
#: fakturanummer i en värderad under kolumnrubriker.
_DATE_TOKEN = re.compile(
    r"\d{4}[-./]\d{2}[-./]\d{2}|\d{1,2}[-./]\d{1,2}[-./]\d{2,4}"
)


def _extract_below_line(line: str, kind: str) -> str:
    """Värdet av given typ i en VÄRDERAD (raden under rubrikerna).

    Rubrikerna styr vilken typ varje fält läser — aldrig "första
    beloppet efter etiketten" (det är nästan alltid fel kolumn):
    belopp = SISTA beloppet på raden (Att betala är sista
    kolumnen i summablocket), datum = datumtoken, nummer =
    första nummertoken som inte är ett datum.
    """
    line = (line or "").strip()
    if not line:
        return ""
    if kind == "amount":
        hits = _AMOUNT_AFTER.findall(line)
        if hits:
            v = _norm_amount(hits[-1])
            if v > 0:
                return f"{v:.2f}"
        return ""
    if kind == "date":
        m = _DATE_AFTER.search(line)
        return _parse_date(m.group(0)) if m else ""
    if kind == "digits":
        m = _DIGITS_AFTER.search(line)
        return re.sub(r"\s", "", m.group(0)) if m else ""
    if kind == "token":
        for tok in line.split():
            tok = tok.strip(" .,;:#")
            if not tok or not any(c.isdigit() for c in tok):
                continue
            if _DATE_TOKEN.fullmatch(tok):
                continue
            if _INVOICE_NR_RE.fullmatch(tok) is None:
                continue
            if len(tok) >= 2 and tok.upper() not in _INVOICE_NR_STOPWORDS:
                return tok
        return ""
    m = _TOKEN_AFTER.search(line)
    return m.group(0).strip(" .") if m else ""


def _extract_below_label(text: str, label: str, kind: str) -> str:
    """Värdet på raden UNDER etikettens rubrikrad, eller "".

    För layouten där etiketterna står som kolumnrubriker i en
    rubrikrad ("Fakturanr. Fakturadatum Kundnr." / "… Summa
    netto Moms Öresavrundning Att betala") och alla värden
    samlade på raden under. Radvis/kolumnvis extraktion (PDF/
    OCR) kan aldrig para etikett+värde på samma rad där.

    Villkor (samma försiktighet som alltid): etikettens egen
    rad får INTE innehålla ett värde av typen (då är det en
    vanlig etikett+värde-rad, ingen rubrikrad) och värdet
    måste stå i den omedelbart följande icke-tomma raden.
    """
    if not text or not label:
        return ""
    flat = re.sub(r"[ \t]+", " ", text)
    lab = re.sub(r"\s+", " ", str(label)).strip().rstrip(":#").strip()
    if not lab:
        return ""
    lines = flat.split("\n")
    amount_hits: list[float] = []
    for m in re.finditer(re.escape(lab), flat, re.IGNORECASE):
        rest_line = flat[m.end():].split("\n", 1)[0]
        same_hit = _extract_kind(rest_line, kind, m.group(0))
        if same_hit:
            if kind != "amount":
                # Vanlig etikett+värde-rad — aldrig rubrikrad.
                continue
            # Flersidig faktura: etiketten kan stå parvis på en
            # sida ("Att betala 2 686,45") och som kolumnrubrik
            # på en annan. Båda formerna är kandidater för
            # beloppet — dokumentets SISTA kandidat är
            # slutsumman, tidigare är delsummor.
            try:
                amount_hits.append(float(same_hit))
            except (TypeError, ValueError):
                pass
            continue
        lineno = flat.count("\n", 0, m.end())
        for below in lines[lineno + 1:]:
            if not below.strip():
                continue
            hit = _extract_below_line(below, kind)
            if hit:
                if kind != "amount":
                    return hit
                try:
                    amount_hits.append(float(hit))
                except (TypeError, ValueError):
                    pass
            break
    if amount_hits:
        # Sista kandidaten i dokumentordning vinner — INTE den
        # största: en artikelrad kan undantagsvis överstiga totalen,
        # men slutsumman står alltid efter delsummorna.
        return f"{amount_hits[-1]:.2f}"
    return ""


def _label_below_amount(text: str, label: str) -> float | None:
    """Etikettens dokument-sista belopp ("Att betala"): värdet i
    kolumnen under rubriken eller parvis på etikettens rad —
    vid flera förekomster är den sista slutsumman."""
    hit = _extract_below_label(text, label, "amount")
    return float(hit) if hit else None


def _label_key(label: Any) -> str:
    """Normaliserad etikettnyckel för radjämförelser."""
    lab = re.sub(r"\s+", " ", str(label or "")).strip()
    return lab.rstrip(":#.").strip().lower()


def _stacked_template_values(
    text: str, fields: dict
) -> dict[str, Any]:
    """Värden när textuttaget STAPLAR etiketterna och värdena.

    Vissa PDF-läsare/OCR-motorer lägger först alla rubriker på
    varsin rad och därefter alla värden på varsin rad:

        Fakturanr.
        Fakturadatum
        Kundnr.
        916336
        2024-05-08
        103

    Varken etikett+värde på samma rad eller rubrikrad/värderad
    träffar då. Här paras i stället den ihopliggande etikett-
    sekvensen med värdesekvensen direkt efter — i samma
    ordning, fält för fält, och varje värde måste vara av rätt
    typ (nummer/datum/belopp). Minst två etiketter i följd och
    ett läst fakturanummer krävs; annars gissas ingenting.
    Icke-mallrubriker i sekvensen (t.ex. Kundnr.) förbrukar sitt
    värde så kolumnerna inte förskjuts.
    """
    if not text or not fields:
        return {}
    specs: dict[str, tuple[str, str]] = {}
    for field, spec in fields.items():
        kind = TEMPLATE_FIELD_KINDS.get(field)
        if kind is None or not isinstance(spec, dict):
            continue
        if spec.get("region"):
            continue  # rutfält pekas ut på bilden, aldrig i text
        label = _label_key(spec.get("label", ""))
        if label:
            specs[field] = (label, kind)
    if len(specs) < 2:
        return {}
    label_to_field: dict[str, str] = {}
    for field, (label, _kind) in specs.items():
        label_to_field.setdefault(label, field)
    known_labels = set(label_to_field)
    for labels in _REPAIR_LABELS.values():
        known_labels.update(_label_key(lab) for lab in labels)
    known_labels.update({
        "kundnr", "kundnummer", "ordernr", "ordernummer",
        "antal", "styckpris", "summa", "vår referens", "er referens",
    })

    lines = [
        re.sub(r"[ \t]+", " ", line).strip()
        for line in str(text).splitlines()
    ]
    found: dict[str, Any] = {}
    for start in range(len(lines)):
        seq: list[str | None] = []
        i = start
        while i < len(lines):
            key = _label_key(lines[i])
            if not key or key not in known_labels:
                break
            seq.append(label_to_field.get(key))
            i += 1
        if len(seq) < 2 or not any(seq):
            continue
        values: list[str] = []
        j = i
        while j < len(lines) and len(values) < len(seq):
            if lines[j]:
                values.append(lines[j])
            j += 1
        if len(values) < len(seq):
            continue
        cand: dict[str, Any] = {}
        for field, line in zip(seq, values):
            if field is None or field in cand:
                continue
            kind = specs[field][1]
            raw = _extract_below_line(line, kind)
            if raw:
                cand[field] = (
                    float(raw) if field == "total_amount" else raw
                )
        if "invoice_number" in cand and len(cand) >= 2:
            for field, value in cand.items():
                found.setdefault(field, value)
    return found


def apply_template(text: str, template: dict) -> dict[str, Any]:
    """Kör en leverantörsmall på texten → {fält: värde} för träffar."""
    fields = (template or {}).get("fields", {})
    found: dict[str, Any] = {}
    for field, spec in fields.items():
        kind = TEMPLATE_FIELD_KINDS.get(field)
        if kind is None or not isinstance(spec, dict):
            continue
        label = str(spec.get("label", ""))
        raw = extract_with_label(text or "", label, kind)
        if spec.get("below"):
            # Verifierad kolumnlayout (rubrikrad + värderad,
            # t.ex. Martin G:s nyare fakturor): värdet på raden
            # under rubriken VINNER över vanlig etikettläsning —
            # annars norpar den första beloppet efter etiketten
            # ur fel kolumn (t.ex. Total vikt i stället för Att
            # betala). Saknas värderaden gäller vanlig läsning.
            below_raw = _extract_below_label(text or "", label, kind)
            if below_raw:
                raw = below_raw
        if raw == "":
            continue
        found[field] = float(raw) if field == "total_amount" else raw
    if len(found) < len(fields):
        # Staplat textuttag (rubrikerna för sig, värdena för
        # sig) träffas varken av etikettläsningen eller av
        # rubrikrad/värderad — para sekvenserna i stället.
        # Staplingen fyller bara fält som annars saknas.
        for field, value in _stacked_template_values(
            text or "", fields
        ).items():
            found.setdefault(field, value)
    return found


# ── Regionsmallar: värden pekas ut på fakturabilden ──────────
# En malls fält kan i stället för etikett bära en RUTA på sidan:
#   {"region": [x0, y0, x1, y1], "page": 0}
# Koordinaterna är andelar (0–1) av sidans bredd/höjd, så samma
# mall fungerar oavsett filens upplösning. Läsningen sker i
# första hand ur PDF:ens textlager inuti rutan (PyMuPDF, pypdf
# som reserv), annars OCR av den utklippta rutan. Poängen är
# inlärningsdialogens bildmarkering: användaren drar en ruta
# runt värdet — appen behöver inte gissa etiketter alls.


def _value_from_region(raw: str, kind: str) -> str:
    """Tolkar värdet ur en markerad rutas råtext.

    Rutan ska innehålla i huvudsak själva värdet, men lite
    etikett-text tolereras: nummer = första nummertoken som
    inte är ett datum/rubrikord, belopp = sista fullständiga
    beloppet, datum = första datumtoken, OCR = sifferserien.
    """
    text = " ".join(str(raw or "").split())
    if not text:
        return ""
    if kind == "amount":
        hits = _AMOUNT_AFTER.findall(text)
        if hits:
            v = _norm_amount(hits[-1])
            if v > 0:
                return f"{v:.2f}"
        return ""
    if kind == "date":
        m = _DATE_AFTER.search(text)
        return _parse_date(m.group(0)) if m else ""
    if kind == "digits":
        m = _DIGITS_AFTER.search(text)
        if m:
            return re.sub(r"\s", "", m.group(0))
        digits = re.sub(r"\D", "", text)
        return digits if len(digits) >= 4 else ""
    if kind == "token":
        return _extract_below_line(text, "token")
    parts = text.split()
    return parts[0] if parts else ""


def _region_specs(template: dict | None) -> dict[str, dict]:
    """{fält: spec} för fält i mallen som har en giltig ruta."""
    out: dict[str, dict] = {}
    for field, spec in ((template or {}).get("fields", {}) or {}).items():
        if field not in TEMPLATE_FIELD_KINDS:
            continue
        if not isinstance(spec, dict):
            continue
        region = spec.get("region")
        if (
            isinstance(region, (list, tuple))
            and len(region) == 4
            and all(
                isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0
                for v in region
            )
        ):
            out[field] = spec
    return out


def template_values_from_regions(
    template: dict | None, region_texts: dict | None
) -> dict[str, Any]:
    """{fält: tolkat värde} ur rutornas råtexter."""
    found: dict[str, Any] = {}
    texts = region_texts or {}
    for field, spec in _region_specs(template).items():
        raw = _value_from_region(
            str(texts.get(field, "") or ""),
            TEMPLATE_FIELD_KINDS[field],
        )
        if raw == "":
            continue
        found[field] = (
            float(raw) if field == "total_amount" else raw
        )
    return found


def template_values(
    path: Any, text: str, template: dict | None
) -> dict[str, Any]:
    """Mallens fältvärden för en konkret fil: etikettläsning ur
    texten + bildrutorna (rutorna vinner — de är utpekade)."""
    found = apply_template(text or "", template or {})
    if path:
        found.update(
            template_values_from_regions(
                template, extract_region_texts(path, template or {})
            )
        )
    return found


def _clamp_rect(region: Any) -> tuple[float, float, float, float]:
    vals = [min(1.0, max(0.0, float(v))) for v in region]
    x0, y0, x1, y1 = vals
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _words_in_region_fitz(
    path: Path, page_index: int, rect: tuple
) -> str:
    x0, y0, x1, y1 = rect
    try:
        with fitz.open(str(path)) as doc:
            if not len(doc):
                return ""
            page = doc[min(max(page_index, 0), len(doc) - 1)]
            w_pt, h_pt = page.rect.width, page.rect.height
            if not w_pt or not h_pt:
                return ""
            hits = []
            for word in page.get_text("words"):
                wx0, wy0, wx1, wy1, text = (
                    word[0], word[1], word[2], word[3], word[4],
                )
                cx = (wx0 + wx1) / 2 / w_pt
                cy = (wy0 + wy1) / 2 / h_pt
                if (
                    x0 - 0.004 <= cx <= x1 + 0.004
                    and y0 - 0.004 <= cy <= y1 + 0.004
                ):
                    hits.append((wy0, wx0, text))
            hits.sort(key=lambda h: (round(h[0] / 4.0), h[1]))
            return " ".join(h[2] for h in hits).strip()
    except Exception as exc:
        log.warning("region-fitz %s: %s", path, exc)
        return ""


def _words_in_region_pypdf(
    path: Path, page_index: int, rect: tuple
) -> str:
    x0, y0, x1, y1 = rect
    try:
        reader = PdfReader(str(path))
        if not reader.pages:
            return ""
        page = reader.pages[
            min(max(page_index, 0), len(reader.pages) - 1)
        ]
        w_pt = float(page.mediabox.width)
        h_pt = float(page.mediabox.height)
        if not w_pt or not h_pt:
            return ""
        hits: list[str] = []

        def _visitor(text, cm, tm, _font, _size):
            chunk = " ".join(str(text or "").split())
            if not chunk:
                return
            ux = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            uy = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            fx, fy = ux / w_pt, 1.0 - uy / h_pt
            if (
                x0 - 0.006 <= fx <= x1 + 0.006
                and y0 - 0.006 <= fy <= y1 + 0.006
            ):
                hits.append(chunk)

        page.extract_text(visitor_text=_visitor)
        return " ".join(hits).strip()
    except Exception as exc:
        log.warning("region-pypdf %s: %s", path, exc)
        return ""


def _ocr_crop_text(path: Path, page_index: int, rect: tuple) -> str:
    """OCR av den utklippta rutan (bildfil eller skannad PDF)."""
    if not HAS_TESS:
        return ""
    x0, y0, x1, y1 = rect
    try:
        import io

        if path.suffix.lower() == ".pdf":
            if not HAS_FITZ:
                return ""
            with fitz.open(str(path)) as doc:
                if not len(doc):
                    return ""
                page = doc[min(max(page_index, 0), len(doc) - 1)]
                clip = fitz.Rect(
                    x0 * page.rect.width, y0 * page.rect.height,
                    x1 * page.rect.width, y1 * page.rect.height,
                )
                pix = page.get_pixmap(dpi=300, clip=clip)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
        else:
            img = Image.open(str(path))
            img = img.crop((
                int(x0 * img.width), int(y0 * img.height),
                int(x1 * img.width), int(y1 * img.height),
            ))
        text = pytesseract.image_to_string(img, lang="swe+eng")
        return (text or "").strip()
    except Exception as exc:
        log.warning("region-ocr %s: %s", path, exc)
        return ""


def extract_region_texts(
    path: Any, template: dict | None
) -> dict[str, str]:
    """{fält: råtext i rutan} för mallens regionsfält.

    Textlager i rutan först (PyMuPDF, därefter pypdf); saknas
    träffar provas OCR av den utklippta rutan. Aldrig undantag
    utåt — misslyckad läsning ger bara färre nycklar.
    """
    specs = _region_specs(template)
    if not specs or not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for field, spec in specs.items():
        rect = _clamp_rect(spec.get("region"))
        page_index = 0
        try:
            page_index = int(spec.get("page", 0) or 0)
        except (TypeError, ValueError):
            page_index = 0
        raw = ""
        if p.suffix.lower() == ".pdf":
            if HAS_FITZ:
                raw = _words_in_region_fitz(p, page_index, rect)
            if not raw and HAS_PYPDF:
                raw = _words_in_region_pypdf(p, page_index, rect)
        if not raw:
            raw = _ocr_crop_text(p, page_index, rect)
        if raw:
            out[field] = raw
    return out


def page_image_count(path: Any) -> int:
    """Antal sidor som kan visas som bild (0 = kan inte visas)."""
    p = Path(path or "")
    if not p.exists():
        return 0
    if p.suffix.lower() == ".pdf":
        try:
            if HAS_FITZ:
                with fitz.open(str(p)) as doc:
                    return len(doc)
            if HAS_PYPDF:
                return len(PdfReader(str(p)).pages)
        except Exception as exc:
            log.warning("sidor %s: %s", p, exc)
        return 0
    if p.suffix.lower() not in SCAN_EXTENSIONS:
        return 0
    try:
        from PIL import Image as PILImage

        with PILImage.open(str(p)) as image:
            return max(1, int(getattr(image, "n_frames", 1) or 1))
    except ImportError:
        # Bildvisning kan fortfarande fungera via Qt när Pillow saknas.
        return 1
    except Exception as exc:
        log.warning("bildsidor %s: %s", p, exc)
        return 0


def render_page_image(
    path: Any, page_index: int = 0, dpi: int = 150
) -> bytes | None:
    """Sidans bild som PNG-bytes (PDF via PyMuPDF; bildfilen
    själv). None när sidan inte kan renderas."""
    p = Path(path or "")
    if not p.exists():
        return None
    if p.suffix.lower() == ".pdf":
        if not HAS_FITZ:
            return None
        try:
            with fitz.open(str(p)) as doc:
                if not len(doc):
                    return None
                page = doc[min(max(page_index, 0), len(doc) - 1)]
                return page.get_pixmap(dpi=dpi).tobytes("png")
        except Exception as exc:
            log.warning("rendera %s: %s", p, exc)
            return None
    if p.suffix.lower() in SCAN_EXTENSIONS:
        try:
            import io
            from PIL import Image as PILImage

            with PILImage.open(str(p)) as source:
                count = max(1, int(getattr(source, "n_frames", 1) or 1))
                source.seek(min(max(int(page_index), 0), count - 1))
                frame = source.copy()
            try:
                if "A" in frame.getbands():
                    rgba = frame.convert("RGBA")
                    background = PILImage.new(
                        "RGBA", rgba.size, (255, 255, 255, 255)
                    )
                    background.alpha_composite(rgba)
                    rendered = background.convert("RGB")
                    rgba.close()
                    background.close()
                else:
                    rendered = frame.convert("RGB")
                buffer = io.BytesIO()
                rendered.save(buffer, format="PNG")
                rendered.close()
                return buffer.getvalue()
            finally:
                frame.close()
        except ImportError:
            try:
                return p.read_bytes()
            except Exception as exc:
                log.warning("bild %s: %s", p, exc)
        except Exception as exc:
            log.warning("rendera bild %s: %s", p, exc)
    return None


_SUPPLIER_LOGO_HASH_PREFIX = "dhash128-v1:"
SUPPLIER_LOGO_CANDIDATE_MAX_DISTANCE = 20
SUPPLIER_LOGO_AUTO_MAX_DISTANCE = 8


def _supplier_logo_hash_from_png(
    png: bytes, region: Any
) -> str:
    """Visuell 128-bit dHash av en markerad logotypyta.

    Hashen lagrar inte själva logotypbilden. En detaljfattig/tom
    markering avvisas, så en vit ruta aldrig blir en identifierare.
    """
    try:
        import io
        from PIL import Image as PILImage, ImageOps

        rect = _clamp_rect(region)
        with PILImage.open(io.BytesIO(png)) as source:
            image = ImageOps.grayscale(source)
            width, height = image.size
            left = max(0, min(width - 1, int(rect[0] * width)))
            top = max(0, min(height - 1, int(rect[1] * height)))
            right = max(left + 1, min(width, int(rect[2] * width)))
            bottom = max(top + 1, min(height, int(rect[3] * height)))
            crop = image.crop((left, top, right, bottom))
            if crop.width < 8 or crop.height < 8:
                return ""
            lo, hi = crop.getextrema()
            if hi - lo < 24:
                return ""
            resampling = getattr(PILImage, "Resampling", PILImage)
            tiny = ImageOps.autocontrast(crop).resize(
                (9, 9), resampling.LANCZOS
            )
            get_flattened_data = getattr(tiny, "get_flattened_data", None)
            pixels = list(
                get_flattened_data() if callable(get_flattened_data)
                else tiny.getdata()
            )
        horizontal = 0
        vertical = 0
        for y in range(8):
            for x in range(8):
                horizontal = (horizontal << 1) | int(
                    pixels[y * 9 + x] > pixels[y * 9 + x + 1]
                )
                vertical = (vertical << 1) | int(
                    pixels[y * 9 + x] > pixels[(y + 1) * 9 + x]
                )
        if horizontal == 0 and vertical == 0:
            return ""
        return (
            _SUPPLIER_LOGO_HASH_PREFIX
            + f"{horizontal:016x}{vertical:016x}"
        )
    except Exception as exc:
        log.debug("supplier logo hash: %s", exc)
        return ""


def supplier_logo_signature(
    path: Any, page_index: int, region: Any
) -> str:
    """Hashar den användarmarkerade logoytan på en PDF-/bildsida."""
    png = render_page_image(path, page_index, dpi=150)
    return _supplier_logo_hash_from_png(png, region) if png else ""


def supplier_logo_region_candidates(
    path: Any, *, max_candidates: int = 12, max_pages: int = 5,
) -> list[dict[str, Any]]:
    """Hitta möjliga logoområden i PDF:en för användarens granskning.

    Rasterbilder och kompakta vektorgrafikgrupper prioriteras. En
    helsideskannad PDF får bara två tydligt märkta header-områden som
    manuella ledtrådar. Inget väljs automatiskt, sparas eller kopplas
    till en leverantör här; UI:t visar varje ruta innan användaren
    eventuellt bekräftar den.
    """
    if not HAS_FITZ or not path:
        return []
    pdf_path = Path(path)
    if pdf_path.suffix.casefold() != ".pdf":
        return []
    candidates: list[dict[str, Any]] = []
    try:
        document = fitz.open(str(pdf_path))
    except Exception as exc:
        log.debug("supplier logo regions open %s: %s", pdf_path, exc)
        return []

    def _add_candidate(
        page_index: int, page_rect, source: str, box,
        base_score: int, *, header_fallback: bool = False,
    ) -> None:
        try:
            rect = fitz.Rect(box) & page_rect
            page_width = float(page_rect.width)
            page_height = float(page_rect.height)
            width = float(rect.width)
            height = float(rect.height)
            page_area = page_width * page_height
            if (
                page_area <= 0 or width < 8 or height < 6
                or rect.is_empty or rect.is_infinite
            ):
                return
            area_ratio = (width * height) / page_area
            if not header_fallback and (
                area_ratio < 0.00025 or area_ratio > 0.22
            ):
                return
            aspect = width / max(height, 0.01)
            if not header_fallback and not 0.08 <= aspect <= 16:
                return
            # A few points of margin protect anti-aliased edges without
            # turning a small logo candidate into a large page region.
            pad_x = min(7.0, max(1.0, width * 0.035))
            pad_y = min(7.0, max(1.0, height * 0.035))
            rect = fitz.Rect(
                max(page_rect.x0, rect.x0 - pad_x),
                max(page_rect.y0, rect.y0 - pad_y),
                min(page_rect.x1, rect.x1 + pad_x),
                min(page_rect.y1, rect.y1 + pad_y),
            )
            region = [
                round((float(rect.x0) - float(page_rect.x0)) / page_width, 4),
                round((float(rect.y0) - float(page_rect.y0)) / page_height, 4),
                round((float(rect.x1) - float(page_rect.x0)) / page_width, 4),
                round((float(rect.y1) - float(page_rect.y0)) / page_height, 4),
            ]
            if not (
                0.0 <= region[0] < region[2] <= 1.0
                and 0.0 <= region[1] < region[3] <= 1.0
            ):
                return
            y_top = region[1]
            score = int(base_score)
            score += max(0, 12 - int(page_index) * 3)
            score += 18 if y_top < 0.28 else 9 if y_top < 0.48 else -10
            score += 8 if 0.35 <= aspect <= 5.5 else 0
            if not header_fallback:
                score += 8 if area_ratio <= 0.08 else -8
            candidate = {
                "page": int(page_index), "region": region,
                "source": str(source), "score": score,
            }
            candidate_area = max(
                1e-9,
                (region[2] - region[0]) * (region[3] - region[1]),
            )
            for index, old in enumerate(candidates):
                if old["page"] != candidate["page"]:
                    continue
                old_region = old["region"]
                intersection = max(
                    0.0, min(region[2], old_region[2])
                    - max(region[0], old_region[0]),
                ) * max(
                    0.0, min(region[3], old_region[3])
                    - max(region[1], old_region[1]),
                )
                old_area = max(
                    1e-9,
                    (old_region[2] - old_region[0])
                    * (old_region[3] - old_region[1]),
                )
                if intersection / min(candidate_area, old_area) >= 0.82:
                    if candidate["score"] > old["score"]:
                        candidates[index] = candidate
                    return
            candidates.append(candidate)
        except Exception:
            return

    try:
        page_limit = min(len(document), max(1, int(max_pages)))
        for page_index in range(page_limit):
            page = document[page_index]
            page_rect = fitz.Rect(page.rect)
            before_page = len(candidates)
            page_width = float(page_rect.width)
            page_height = float(page_rect.height)

            # XObject-/imagebaserade loggor finns som separata bildrutor
            # i PDF:en. Helsidesbilder (vanlig skannad faktura) filtreras
            # här bort och hanteras med header-förslag nedan.
            image_infos: list[dict] = []
            try:
                image_infos = list(page.get_image_info(xrefs=True) or [])
            except Exception:
                try:
                    for image in page.get_images(full=True) or []:
                        xref = int(image[0])
                        image_width = int(image[2])
                        image_height = int(image[3])
                        for image_rect in page.get_image_rects(xref) or []:
                            image_infos.append({
                                "bbox": image_rect, "width": image_width,
                                "height": image_height,
                            })
                except Exception as exc:
                    log.debug("supplier logo image info: %s", exc)
            for info in image_infos:
                bbox = info.get("bbox") if isinstance(info, dict) else None
                if bbox is None:
                    continue
                try:
                    box = fitz.Rect(bbox)
                    source_width = float(info.get("width", 0) or 0)
                    source_height = float(info.get("height", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if source_width and source_height:
                    # Ignore tiny tracking marks and low-resolution
                    # artifacts while allowing a printed small logo.
                    if source_width < 20 or source_height < 12:
                        continue
                _add_candidate(
                    page_index, page_rect, "embedded_image", box, 62
                )

            # Vector/SVG artwork is represented by drawing paths instead
            # of image XObjects. Cluster nearby compact paths into one
            # inspectable region rather than offering every tiny path.
            drawings: list[tuple[Any, int]] = []
            try:
                for drawing in page.get_drawings() or []:
                    try:
                        rect = fitz.Rect(drawing.get("rect"))
                        item_count = len(drawing.get("items", []) or [])
                    except Exception:
                        continue
                    area_ratio = (
                        float(rect.width) * float(rect.height)
                        / max(1.0, page_width * page_height)
                    )
                    if (
                        rect.is_empty or rect.width < 2 or rect.height < 2
                        or rect.width > page_width * 0.72
                        or rect.height > page_height * 0.32
                        or area_ratio > 0.055
                        or rect.width / max(float(rect.height), 0.01) > 18
                        or rect.height / max(float(rect.width), 0.01) > 18
                    ):
                        continue
                    drawings.append((rect, item_count))
            except Exception as exc:
                log.debug("supplier logo vector info: %s", exc)

            # Bound worst-case work on pages with thousands of PDF paths.
            drawings = drawings[:500]
            parents = list(range(len(drawings)))

            def _find(index: int) -> int:
                while parents[index] != index:
                    parents[index] = parents[parents[index]]
                    index = parents[index]
                return index

            def _union(left: int, right: int) -> None:
                root_left, root_right = _find(left), _find(right)
                if root_left != root_right:
                    parents[root_right] = root_left

            gap_x = max(5.0, page_width * 0.018)
            gap_y = max(5.0, page_height * 0.012)
            for left in range(len(drawings)):
                a = drawings[left][0]
                for right in range(left + 1, len(drawings)):
                    b = drawings[right][0]
                    dx = max(0.0, max(a.x0, b.x0) - min(a.x1, b.x1))
                    dy = max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))
                    if dx <= gap_x and dy <= gap_y:
                        _union(left, right)
            groups: dict[int, list[int]] = {}
            for index in range(len(drawings)):
                groups.setdefault(_find(index), []).append(index)
            for indexes in groups.values():
                rect = fitz.Rect(drawings[indexes[0]][0])
                total_items = 0
                for index in indexes:
                    rect |= drawings[index][0]
                    total_items += drawings[index][1]
                if len(indexes) < 2 and total_items < 4:
                    continue
                if (
                    rect.width > page_width * 0.78
                    or rect.height > page_height * 0.36
                ):
                    continue
                _add_candidate(
                    page_index, page_rect, "vector_art", rect, 48
                )

            page_candidates = [
                item for item in candidates[before_page:]
                if item["page"] == page_index
                and item["source"] != "header_area"
            ]
            has_upper_candidate = any(
                item["region"][1] < 0.52 for item in page_candidates
            )
            if page_index == 0 and not has_upper_candidate:
                try:
                    has_content = bool(
                        page.get_text("text").strip()
                        or page.get_images(full=True)
                        or page.get_drawings()
                    )
                except Exception:
                    has_content = True
                if has_content:
                    # This is a clearly labelled navigation aid for
                    # scanned/vector layouts, not an asserted logo crop.
                    top = page_rect.y0 + page_height * 0.025
                    bottom = page_rect.y0 + page_height * 0.23
                    _add_candidate(
                        page_index, page_rect, "header_area",
                        fitz.Rect(
                            page_rect.x0 + page_width * 0.025, top,
                            page_rect.x0 + page_width * 0.46, bottom,
                        ), 18, header_fallback=True,
                    )
                    _add_candidate(
                        page_index, page_rect, "header_area",
                        fitz.Rect(
                            page_rect.x0 + page_width * 0.54, top,
                            page_rect.x0 + page_width * 0.975, bottom,
                        ), 18, header_fallback=True,
                    )
    except Exception as exc:
        log.debug("supplier logo region candidates %s: %s", pdf_path, exc)
    finally:
        try:
            document.close()
        except Exception:
            pass
    return sorted(
        candidates,
        key=lambda item: (
            -int(item["score"]), int(item["page"]),
            float(item["region"][1]), float(item["region"][0]),
        ),
    )[:max(1, int(max_candidates))]


def supplier_logo_distance(left: str, right: str) -> int | None:
    """Hammingavstånd mellan två kompatibla logotyphashar."""
    if not (
        str(left or "").startswith(_SUPPLIER_LOGO_HASH_PREFIX)
        and str(right or "").startswith(_SUPPLIER_LOGO_HASH_PREFIX)
    ):
        return None
    try:
        a = int(str(left).split(":", 1)[1], 16)
        b = int(str(right).split(":", 1)[1], 16)
        return bin(a ^ b).count("1")
    except (TypeError, ValueError):
        return None


def supplier_logo_specs(template: dict | None) -> list[dict[str, Any]]:
    """Alla sparade logotypvarianter, även äldre enkelmallsformat.

    `supplier_logo` är den äldre primärnyckeln. Nya mallar kan också
    innehålla `supplier_logos`, en lista med flera sid-/regionsignaturer.
    Dubbletten mellan primärnyckeln och listans första objekt tas bort.
    """
    if not isinstance(template, dict):
        return []
    raw: list[Any] = []
    legacy = template.get("supplier_logo")
    if isinstance(legacy, dict):
        raw.append(legacy)
    variants = template.get("supplier_logos", [])
    if isinstance(variants, dict):
        raw.append(variants)
    elif isinstance(variants, (list, tuple)):
        raw.extend(variants)

    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for candidate in raw:
        if not isinstance(candidate, dict):
            continue
        signature = str(candidate.get("dhash", "") or "").strip()
        if not signature.startswith(_SUPPLIER_LOGO_HASH_PREFIX):
            continue
        try:
            page = max(0, int(candidate.get("page", 0) or 0))
        except (TypeError, ValueError):
            page = 0
        region = candidate.get("region", ())
        try:
            normalized_region = tuple(
                round(float(value), 4) for value in region
            )
            if len(normalized_region) != 4:
                normalized_region = ()
        except (TypeError, ValueError):
            normalized_region = ()
        key = (page, normalized_region, signature)
        if key in seen:
            continue
        seen.add(key)
        spec = dict(candidate)
        spec["page"] = page
        spec["dhash"] = signature
        if normalized_region:
            spec["region"] = list(normalized_region)
        out.append(spec)
    return out


def supplier_logo_match_candidates(
    path: Any,
    templates: dict | None,
    max_distance: int = SUPPLIER_LOGO_CANDIDATE_MAX_DISTANCE,
) -> list[dict[str, Any]]:
    """Hitta riktiga logotyper även när de flyttats på fakturasidan.

    Först jämförs varje sparad ruta på samma sidkoordinater som mallen.
    För PDF:er jämförs därefter också inbäddade bilder och kompakta
    vektorgrafiker som hittats på andra positioner. Generiska header-rutor
    används aldrig som automatisk logotypträff. Varje leverantör returneras
    högst en gång; svaga träffar lämnas bort och val måste fortfarande
    bekräftas enligt de befintliga säkerhetsreglerna.

    Träffarna innehåller sid-/regionsinformation för att dialogen ska kunna
    visa den faktiska beskurna logotypen ur den aktuella originalfakturan.
    """
    specs_by_supplier = [
        (str(name), supplier_logo_specs(template))
        for name, template in (templates or {}).items()
    ]
    specs_by_supplier = [
        (name, specs) for name, specs in specs_by_supplier if specs
    ]
    if not path or not specs_by_supplier:
        return []

    page_images: dict[int, bytes | None] = {}
    region_hashes: dict[tuple[int, tuple], str] = {}

    def _region_hash(page: int, region: Any) -> str:
        try:
            normalized = tuple(round(float(value), 4) for value in region)
        except (TypeError, ValueError):
            return ""
        if len(normalized) != 4 or not (
            0 <= normalized[0] < normalized[2] <= 1
            and 0 <= normalized[1] < normalized[3] <= 1
        ):
            return ""
        key = (int(page), normalized)
        if key not in region_hashes:
            if page not in page_images:
                page_images[page] = render_page_image(
                    path, page, dpi=150
                )
            png = page_images[page]
            region_hashes[key] = (
                _supplier_logo_hash_from_png(png, normalized)
                if png else ""
            )
        return region_hashes[key]

    # Endast tydligt avgränsade bilder och vektorgrafiker kan användas
    # som sökträffar. "header_area" är en manuell ledtråd, inte ett logo-ID.
    observed_regions: list[dict[str, Any]] = []
    try:
        detected = supplier_logo_region_candidates(path)
    except Exception as exc:
        log.debug("supplier logo region scan %s: %s", path, exc)
        detected = []
    for candidate in detected:
        source = str(candidate.get("source", "") or "")
        if source not in ("embedded_image", "vector_art"):
            continue
        try:
            page = max(0, int(candidate.get("page", 0) or 0))
            region = tuple(
                round(float(value), 4)
                for value in candidate.get("region", ())
            )
        except (TypeError, ValueError):
            continue
        if len(region) != 4:
            continue
        observed = _region_hash(page, region)
        if observed:
            observed_regions.append({
                "page": page, "region": list(region),
                "source": source, "score": int(
                    candidate.get("score", 0) or 0
                ),
                "dhash": observed,
            })

    out: list[dict[str, Any]] = []
    for name, specs in specs_by_supplier:
        best: dict[str, Any] | None = None
        best_key: tuple[int, int, int] | None = None

        def _consider(
            observed_signature: str, signature: str, page: int,
            region: Any, *, match_mode: str, source: str,
            region_score: int = 0,
        ) -> None:
            nonlocal best, best_key
            distance = supplier_logo_distance(
                observed_signature, signature
            )
            if distance is None or distance > max_distance:
                return
            # At equal distance prefer the template's known location; it
            # is a stronger basis for learned auto-matching than discovery.
            key = (
                int(distance),
                0 if match_mode == "saved_region" else 1,
                -int(region_score),
            )
            if best_key is None or key < best_key:
                best_key = key
                best = {
                    "name": name, "distance": int(distance),
                    "dhash": str(signature), "page": int(page),
                    "region": list(region), "match_mode": match_mode,
                    "source": source,
                }

        for spec in specs:
            try:
                page = max(0, int(spec.get("page", 0) or 0))
            except (TypeError, ValueError):
                page = 0
            signature = str(spec.get("dhash", "") or "").strip()
            region = spec.get("region", ())
            observed_signature = _region_hash(page, region)
            if observed_signature:
                _consider(
                    observed_signature, signature, page, region,
                    match_mode="saved_region", source="saved_region",
                )
            for observed in observed_regions:
                observed_signature = str(observed.get("dhash", "") or "")
                _consider(
                    observed_signature, signature,
                    int(observed["page"]),
                    observed["region"],
                    match_mode="detected_region",
                    source=str(observed.get("source", "")),
                    region_score=int(observed.get("score", 0) or 0),
                )
        if best is not None:
            out.append(best)
    return sorted(
        out,
        key=lambda item: (
            int(item["distance"]), _fold_text(item["name"]),
        ),
    )


def supplier_logo_preview_png(
    path: Any, page_index: int, region: Any,
    max_size: tuple[int, int] = (144, 84),
) -> bytes | None:
    """Beskär en riktig logotyp ur originalfakturan för matchningsdialogen.

    Endast en visningskopia skapas; inga filer eller mallar sparas här.
    """
    png = render_page_image(path, page_index, dpi=150)
    if not png:
        return None
    try:
        import io
        from PIL import Image as PILImage

        normalized = _clamp_rect(region)
        with PILImage.open(io.BytesIO(png)) as source:
            width, height = source.size
            left = max(0, min(width - 1, int(normalized[0] * width)))
            top = max(0, min(height - 1, int(normalized[1] * height)))
            right = max(left + 1, min(width, int(normalized[2] * width)))
            bottom = max(top + 1, min(height, int(normalized[3] * height)))
            crop = source.crop((left, top, right, bottom)).convert("RGB")
        target_width = max(32, min(320, int(max_size[0])))
        target_height = max(24, min(240, int(max_size[1])))
        resampling = getattr(PILImage, "Resampling", PILImage)
        crop.thumbnail((target_width - 8, target_height - 8), resampling.LANCZOS)
        canvas = PILImage.new("RGB", (target_width, target_height), "white")
        canvas.paste(
            crop,
            ((target_width - crop.width) // 2,
             (target_height - crop.height) // 2),
        )
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception as exc:
        log.debug("supplier logo preview %s: %s", path, exc)
        return None


def find_template(
    templates: dict,
    supplier: str,
    suppliers: list[dict] | None = None,
) -> dict | None:
    """Hitta mallen med registernamn/alias; tvetydighet ger None.

    Utan *suppliers* behålls den äldre namnvariantmatchningen.
    Med registret kan en mall sparad under ett manuellt angivet alias
    användas för samma leverantör, men flera aliasmallar väljs aldrig
    automatiskt.
    """
    names = (
        supplier_template_candidate_names(templates, supplier, suppliers)
        if suppliers is not None
        else template_candidate_names(templates, supplier)
    )
    if len(names) != 1:
        return None
    return templates.get(names[0])


def confirmed_supplier_logo_signature(
    path: Any,
    supplier: str,
    templates: dict | None,
    max_distance: int = SUPPLIER_LOGO_CANDIDATE_MAX_DISTANCE,
    *,
    suppliers: list[dict] | None = None,
) -> str:
    """Sparad logotypsignatur som matchade efter manuell bekräftelse.

    Använder samma positionstoleranta sökning som matchdialogen, men
    returnerar bara en redan sparad signatur. Ett nytt upptäckt område
    lärs aldrig in automatiskt och räknas först efter användarens val.
    """
    if not path or not supplier:
        return ""
    template = find_template(templates or {}, supplier, suppliers)
    if not template:
        return ""
    matches = supplier_logo_match_candidates(
        path, {supplier: template}, max_distance=max_distance
    )
    return str(matches[0].get("dhash", "") or "") if matches else ""


#: Inbyggda, verifierade leverantörsformat. Varje format har
#: matchats manuellt mot riktiga exempelfakturor tillsammans
#: med användaren INNAN det byggdes in — det är den manuella
#: matchningen som annars sker i inlärningsdialogen. Därför
#: får bevakningen registrera dem automatiskt utan att
#: användaren lär appen samma leverantör en gång till.
#: Identifiering sker via org.nr/bankgiro eller det tryckta
#: namnet på fakturan (aldrig via registerpostens namn, som
#: kan heta något annat — t.ex. Direktglas på Saint-Gobain-
#: papper). Användarens egna mallar har alltid företräde.
BUILTIN_FORMATS: list[dict] = [
    {
        "name": "Martin G Anderson",
        "aliases": [
            "Martin G Anderson", "AB Martin G Anderson", "Martin G",
        ],
        "org": "5568245806",
        "bg": "7280811",
        "printed": ["martin g anderson"],
        "fields": {
            # Nya layouten (2024−, verifierad mot faktura 916336
            # i chatten): rubrikrad + värderad — "below". Äldre
            # parvis layout träffas av vanlig etikettläsning.
            "invoice_number": {"label": "Fakturanr.", "below": True},
            "total_amount": {"label": "Att betala", "below": True},
            "date": {"label": "Fakturadatum", "below": True},
            "due_date": {"label": "Förfallodatum"},
        },
    },
    {
        "name": "Saint-Gobain Autover Sverige AB",
        "aliases": [
            "Direktglas", "Saint-Gobain",
            "Saint-Gobain Autover Sverige AB",
        ],
        "org": "5562746114",
        "bg": "9422817",
        "printed": ["saint-gobain autover", "saint-gobain"],
        "fields": {
            "invoice_number": {"label": "Nummer"},
            "total_amount": {"label": "Att Betala (SEK)"},
            "date": {"label": "Datum"},
            "due_date": {"label": "Förfallodatum"},
        },
    },
    {
        "name": "Pilkington",
        "aliases": [
            "Pilkington", "Pilkington Sverige AB",
            "Pilkington Automotive Sweden AB", "Pilkington Glas AB",
        ],
        "org": "",
        "bg": "5723457",
        "printed": ["pilkington automotive", "pilkington nsg"],
        "fields": {
            "invoice_number": {"label": "Nummer"},
            "total_amount": {"label": "TOTALT FAKTURABELOPP"},
            "date": {"label": "Datum (tax point)"},
            "due_date": {"label": "T.o.m."},
        },
    },
    {
        "name": "Swede Glass United",
        "aliases": [
            "Swede Glass United", "Swede Glass",
        ],
        "org": "5566371588",
        "bg": "55921449",
        "printed": ["swede glass united"],
        "fields": {
            "invoice_number": {"label": "Fakturanummer / Kundnummer"},
            "total_amount": {"label": "ATT BETALA"},
            "date": {"label": "Fakturadatum"},
            "due_date": {"label": "Förfallodatum"},
        },
    },
    {
        "name": "AAG Automotive AB",
        "aliases": [
            "AAG Automotive AB", "AAG Automotive",
        ],
        "org": "5591400816",
        "bg": "4030706",
        "printed": ["aag automotive"],
        "fields": {
            "invoice_number": {"label": "Fakturanr"},
            "total_amount": {"label": "ATT BETALA"},
            "date": {"label": "Fakturadatum"},
            "due_date": {"label": "Förfallodatum"},
        },
    },
]


def _builtin_format_matches_supplier(fmt: dict, supplier: str) -> bool:
    """Hör det inbyggda formatet till den här leverantören?

    Registerpostens namn kan vara ett alias (Direktglas för
    Saint-Gobain-papper) — därför jämförs mot formatets alla
    kända alias, aldrig tvärtom med gissningar.
    """
    if not supplier:
        return False
    return any(
        _names_match(supplier, str(alias))
        for alias in fmt.get("aliases", []) or []
    ) or _names_match(supplier, str(fmt.get("name", "")))


def _builtin_format_candidates(text: str) -> list[dict[str, Any]]:
    """ALLA inbyggda format som känner igen texten.

    Flera kandidater betyder att appen inte får välja själv —
    anroparen markerar matchningen som osäker och frågar
    användaren i stället för att ta första formatet i listan.
    """
    if not text:
        return []
    digits = re.sub(r"\D", "", text)
    flat = _fold_text(text)
    out: list[dict[str, Any]] = []
    for fmt in BUILTIN_FORMATS:
        hit = bool(
            (fmt.get("org") and fmt["org"] in digits)
            or (fmt.get("bg") and fmt["bg"] in digits)
            or any(
                _fold_text(p) in flat for p in fmt.get("printed", [])
            )
        )
        if hit:
            out.append({
                "name": str(fmt.get("name", "")),
                "template": {"fields": dict(fmt.get("fields", {}))},
                "format": fmt,
            })
    return out


def builtin_template_for(text: str) -> tuple[str, dict] | None:
    """
    Inbyggt verifierat format för texten → (namn, mall) eller
    None. Träff kräver org.nr/bankgiro i texten eller det
    tryckta leverantörsnamnet — registerpostens namn används
    aldrig (det kan vara ett helt annat, t.ex. Direktglas).
    Bevarad för äldre anropare; tolkningen använder
    _builtin_format_candidates och väljer aldrig vid flera träffar.
    """
    candidates = _builtin_format_candidates(text)
    if len(candidates) != 1:
        return None
    cand = candidates[0]
    return str(cand["name"]), cand["template"]


def _label_same_line_amount(text: str, label: str) -> float | None:
    """Beloppet på SAMMA RAD som etiketten, eller None.

    Skiljer en äkta etikett+värde-rad ("ATT BETALA 706,00")
    från en kolumnrubrikrad där värdena står på nästa rad i
    kolumner — där är första beloppet efter etiketten nästan
    alltid fel kolumn (netto i stället för att betala).
    """
    if not text or not label:
        return None
    flat = re.sub(r"[ \t]+", " ", text)
    lab = re.sub(r"\s+", " ", str(label)).strip().rstrip(":#").strip()
    if not lab:
        return None
    last: float | None = None
    for m in re.finditer(re.escape(lab), flat, re.IGNORECASE):
        same_line = flat[m.end():].split("\n", 1)[0]
        hit = _extract_kind(same_line, "amount", m.group(0))
        if hit:
            # SISTA förekomsten: i flersidiga fakturor kan en
            # delsumma stå under samma etikett på en tidigare
            # sida — verifieringen ska spegla slutsumman, annars
            # "bekräftar" den första sidans felaktiga belopp.
            last = float(hit)
    return last


def has_builtin_format(supplier: str) -> bool:
    """True om leverantörsnamnet har ett inbyggt verifierat
    format (namnvarianter tillåts, t.ex. 'AB Martin G Anderson'
    för registerposten och 'Martin G Anderson' i formatet)."""
    if len(_fold_text(supplier)) < 4:
        return False
    return any(
        _names_match(supplier, alias)
        for fmt in BUILTIN_FORMATS
        for alias in fmt["aliases"]
    )


def load_templates(path: Path) -> dict:
    """Läser mall-JSON tolerant ({} vid saknad/trasig fil)."""
    try:
        import json as _json

        data = _json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_templates(path: Path, templates: dict) -> bool:
    """Skriver mall-JSON (atomärt via tmp-fil)."""
    try:
        import json as _json

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            _json.dumps(templates, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        tmp.replace(target)
        return True
    except Exception as exc:
        log.warning("save_templates: %s", exc)
        return False


# ── Inlärningsminne: appen blir bättre av varje matchning ────
# Varje gång ANVÄNDAREN matchar/bekräftar en faktura (fråge-
# dialogen eller högerklickets manuella matchning) noteras det
# i match_memory.json bredvid mallfilen:
#   {leverantör: {"confirmed": n, "multipage_confirmed": m,
#                 "identifiers": {"org"/"bg": {värde: n}},
#                 "logos": {bildhash: n}, "last_confirmed": "…"}}
# Varje uttrycklig manuell matchning lägger till ny evidens; räknarna
# nollställs inte när automatisk koppling börjar, så senare bekräftelser
# och nya kännetecken fortsätter att stärka inlärningen. Minnet gissar
# aldrig något självt — det räknar bara användarens egna bekräftelser. Vid
# MULTIPAGE_CONFIRMATIONS_TO_GRADUATE bekräftade flersidiga
# fakturor för samma leverantör får den leverantörens flersidiga
# fakturor passera flersidighetsvakten UTAN ny fråga, men bara
# när totalen dessutom stäms av mot texten (se
# _multipage_total_corroborated). Så lär sig appen av matchning
# efter matchning, utan att någonsin sluta vara försiktig på
# ett obeprövat format.

MULTIPAGE_CONFIRMATIONS_TO_GRADUATE = 2

#: Efter så här många av användaren bekräftade matchningar mot
#: samma leverantör får appen koppla nya fakturor till den
#: leverantören SJÄLV — när fakturan bär ett kännetecken appen
#: lärt sig av de bekräftade fakturorna (användarens tumregel:
#: 5–10 fakturor, sedan ska det sitta).
LEARNED_SUPPLIER_CONFIRMATIONS = 5

#: Ett kännetecken (org.nr/bankgiro) måste ha setts i minst så
#: här många bekräftade fakturor innan det får koppla — ett
#: enstaka nummer på en faktura kan tillhöra någon annan
#: (kundens eget org.nr, en underleverantör i texten …).
LEARNED_IDENTIFIER_CONFIRMATIONS = 2


def _org_nr_checksum_ok(num: str) -> bool:
    """Kontrollsiffran (Luhn) på ett svenskt organisationsnummer."""
    if len(num) != 10 or not num.isdigit():
        return False
    total = 0
    for i, ch in enumerate(num):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_BANKGIRO_LABEL_RE = re.compile(
    r"\b(?:bank[\s-]*giro\w*|bg)\b[^0-9]{0,16}"
    r"(\d[\d\s\-]{4,14}\d)",
    re.IGNORECASE,
)


def _invoice_identifiers(text: str) -> dict[str, set[str]]:
    """Fakturans starka kännetecken: org.nr (med giltig
    kontrollsiffra) och bankgiro vid sin etikett.

    Bara signaler som är svåra att träffa av en slump tas med —
    det är dessa appen lär sig koppla leverantörer med när
    användaren matchat tillräckligt många fakturor för hand.
    """
    ids: dict[str, set[str]] = {"org": set(), "bg": set()}
    flat = str(text or "")
    for m in re.finditer(
        r"(?<!\d)(?:(16)[-\s]?)?(\d{6})[-\s]?(\d{4})(?!\d)",
        flat,
    ):
        raw_number = (m.group(1) or "") + m.group(2) + m.group(3)
        number = _normalize_supplier_identifier("org", raw_number)
        if number:
            ids["org"].add(number)
    for m in _BANKGIRO_LABEL_RE.finditer(flat):
        num = re.sub(r"\D", "", m.group(1))
        if 7 <= len(num) <= 8:
            ids["bg"].add(num)
    return ids


def invoice_org_number_values(text: str) -> list[str]:
    """Giltiga svenska organisationsnummer som hittats i fakturatexten."""
    return sorted(_supplier_invoice_identifiers(text).get("org", set()))


def invoice_bankgiro_values(text: str) -> list[str]:
    """Bankgironummer som hittats vid en uttrycklig BG-etikett."""
    return sorted(_supplier_invoice_identifiers(text).get("bg", set()))


_PAYMENT_DETAIL_LABELS = {
    "bg": re.compile(
        r"\b(?:bank[\s-]*giro(?:t)?|bg)"
        r"(?:[\s-]*(?:nr\.?|nummer|konto))?\b",
        re.IGNORECASE,
    ),
    "pg": re.compile(
        r"\b(?:plus[\s-]*giro(?:t)?|pg)"
        r"(?:[\s-]*(?:nr\.?|nummer|konto))?\b",
        re.IGNORECASE,
    ),
    "iban": re.compile(r"\bIBAN\b", re.IGNORECASE),
}

_IBAN_LENGTHS = {
    "AT": 20, "BE": 16, "CH": 21, "CZ": 24, "DE": 22,
    "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FR": 27,
    "GB": 22, "GR": 27, "IE": 22, "IS": 26, "IT": 27,
    "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27,
    "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25,
    "RO": 24, "SE": 24, "SI": 19, "SK": 24, "TR": 26,
}


def _valid_iban_checksum(value: str) -> bool:
    """Kontrollerar IBAN:s mod-97-summa utan stora heltal."""
    iban = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if not (15 <= len(iban) <= 34 and re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", iban)):
        return False
    rearranged = iban[4:] + iban[:4]
    remainder = 0
    for char in rearranged:
        token = str(ord(char) - 55) if char.isalpha() else char
        for digit in token:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def _iban_after_label(fragment: str) -> str:
    """Hämtar ett IBAN efter etiketten; föredrar giltig kontrollsumma."""
    match = re.search(
        r"(?<![A-Z0-9])([A-Z]{2}\s*\d{2}[A-Z0-9\s-]{10,40})",
        str(fragment or ""), re.IGNORECASE,
    )
    if not match:
        return ""
    compact = re.sub(r"[^A-Z0-9]", "", match.group(1).upper())
    country_length = _IBAN_LENGTHS.get(compact[:2])
    candidate_lengths = []
    if country_length:
        candidate_lengths.append(country_length)
    candidate_lengths.extend(
        length for length in range(min(34, len(compact)), 14, -1)
        if length not in candidate_lengths
    )
    for length in candidate_lengths:
        if length <= len(compact):
            candidate = compact[:length]
            if _valid_iban_checksum(candidate):
                return candidate
    # OCR kan förvanska en kontrollsiffra. Behåll ändå ett tydligt,
    # landskodat IBAN-värde så det visas för manuell kontroll.
    if country_length and len(compact) >= country_length:
        return compact[:country_length]
    if 15 <= len(compact) <= 34:
        return compact
    return ""


def extract_invoice_payment_details(text: str) -> dict[str, list[str]]:
    """Extraherar BG/PG/IBAN enbart vid motsvarande fakturaetikett.

    Värdena normaliseras för jämförelse men sparas inte automatiskt i
    leverantörsregistret. En avvikelse är endast en varning till användaren.
    """
    result: dict[str, set[str]] = {"bg": set(), "pg": set(), "iban": set()}
    lines = str(text or "").splitlines()
    for field, label_re in _PAYMENT_DETAIL_LABELS.items():
        for index, line in enumerate(lines):
            for label in label_re.finditer(line):
                fragments = [line[label.end():]]
                if index + 1 < len(lines):
                    fragments.append(lines[index + 1])
                for fragment in fragments:
                    value = ""
                    if field == "iban":
                        value = _iban_after_label(fragment)
                    else:
                        cleaned = re.sub(
                            r"^\s*(?:nr\.?|nummer|konto|no\.?|account(?:\s+number)?)"
                            r"\s*[:#.-]?\s*",
                            "", fragment, flags=re.IGNORECASE,
                        )
                        number_match = re.match(
                            r"\s*[:#=]?\s*(\d[\d\s\u00a0-]{1,20}\d)",
                            cleaned,
                        )
                        if number_match:
                            value = re.sub(r"\D", "", number_match.group(1))
                            minimum, maximum = (7, 8) if field == "bg" else (2, 10)
                            if not minimum <= len(value) <= maximum:
                                value = ""
                    if value:
                        result[field].add(value)
                        break
    return {field: sorted(values) for field, values in result.items()}


def _normalize_payment_value(field: str, value: Any) -> str:
    raw = str(value or "").upper()
    if field == "iban":
        return re.sub(r"[^A-Z0-9]", "", raw)
    return re.sub(r"\D", "", raw)


def payment_detail_warnings(
    text: str,
    supplier_name: str,
    suppliers: list[dict] | None,
    *,
    observed: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Compare invoice-labelled account details with the saved supplier.

    Blank saved fields are not treated as a change. Supplier names must match
    exactly (case-insensitively); an uncertain supplier match is never guessed.
    """
    supplier_key = str(supplier_name or "").strip().casefold()
    if not supplier_key:
        return []
    records = [
        item for item in (suppliers or [])
        if isinstance(item, dict)
        and str(item.get("name", "") or "").strip().casefold() == supplier_key
    ]
    if len(records) != 1:
        return []
    supplier = records[0]
    observed = (
        observed if isinstance(observed, dict)
        else extract_invoice_payment_details(text)
    )
    warnings: list[dict[str, Any]] = []
    profile_keys = {"bg": ("bg", "bankgiro"), "pg": ("pg", "plusgiro"), "iban": ("iban",)}
    for field, keys in profile_keys.items():
        expected = next(
            (
                _normalize_payment_value(field, supplier.get(key))
                for key in keys
                if str(supplier.get(key, "") or "").strip()
            ),
            "",
        )
        raw_values = observed.get(field, [])
        values = (
            [str(value) for value in raw_values]
            if isinstance(raw_values, (list, tuple, set)) else []
        )
        if expected and values and any(value != expected for value in values):
            warnings.append({
                "field": field,
                "registered": expected,
                "invoice_values": list(values),
            })
    return warnings


def assess_invoice_payment_details(
    parsed: dict[str, Any],
    text: str,
    suppliers: list[dict] | None,
    *,
    supplier_name: str | None = None,
    details: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Attach detected account values and a non-destructive mismatch warning."""
    result = dict(parsed or {})
    observed = (
        details if isinstance(details, dict)
        else extract_invoice_payment_details(text)
    )
    result["invoice_payment_details"] = observed
    supplier = str(
        supplier_name if supplier_name is not None else result.get("supplier", "")
    ).strip()
    supplier_match = result.get("supplier_match")
    supplier_uncertain = bool(
        result.get("match_kind") == "supplier"
        or (
            isinstance(supplier_match, dict)
            and (
                (
                    supplier_match.get("uncertain")
                    or supplier_match.get("status") == "uncertain"
                )
                and supplier_match.get("reason") != "multipage"
            )
        )
    )
    if supplier_uncertain and supplier_name is None:
        warnings: list[dict[str, Any]] = []
    else:
        warnings = payment_detail_warnings(
            text, supplier, suppliers, observed=observed
        )
    if warnings:
        result["payment_details_warning"] = warnings
    else:
        result.pop("payment_details_warning", None)
    return result


def suppliers_matching_bankgiro(
    text: str, suppliers: list[dict] | None
) -> list[dict[str, str]]:
    """Registerleverantörer vars BG finns på fakturan.

    Träffen kräver BG-etikett på dokumentet och exakt nummer i
    registret. Returnerar aldrig en fuzzy/partiell matchning.
    """
    invoice_bgs = set(invoice_bankgiro_values(text))
    if not invoice_bgs:
        return []
    matches: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for supplier in suppliers or []:
        if not isinstance(supplier, dict):
            continue
        name = str(supplier.get("name", "") or "").strip()
        if not name:
            continue
        for key in ("bankgiro", "bg"):
            number = _normalize_supplier_identifier("bg", supplier.get(key, ""))
            identity = (name.casefold(), number)
            if number and number in invoice_bgs and identity not in seen:
                matches.append({"name": name, "bankgiro": number})
                seen.add(identity)
    return sorted(matches, key=lambda item: item["name"].casefold())


def suppliers_matching_org_number(
    text: str, suppliers: list[dict] | None
) -> list[dict[str, str]]:
    """Registerleverantörer vars giltiga org.nr finns i fakturan.

    Både faktura och registervärde normaliseras och kontrollsiffran
    kontrolleras; endast ett exakt nummer räknas som träff.
    """
    invoice_orgs = set(invoice_org_number_values(text))
    if not invoice_orgs:
        return []
    matches: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for supplier in suppliers or []:
        if not isinstance(supplier, dict):
            continue
        name = str(supplier.get("name", "") or "").strip()
        if not name:
            continue
        for key in _SUPPLIER_ID_PROFILE_KEYS["org"]:
            number = _normalize_supplier_identifier("org", supplier.get(key, ""))
            identity = (name.casefold(), number)
            if number and number in invoice_orgs and identity not in seen:
                matches.append({"name": name, "org_number": number})
                seen.add(identity)
    return sorted(
        matches,
        key=lambda item: (item["name"].casefold(), item["org_number"]),
    )


def suppliers_matching_identifiers(
    text: str, suppliers: list[dict] | None
) -> list[dict[str, str]]:
    """Exact supplier matches by invoice org.nr and/or labelled BG.

    Results carry both identifiers when a supplier record matches both,
    so the template editor can show the evidence and can ask the user to
    choose if several registered suppliers share a number.
    """
    invoice_ids = _supplier_invoice_identifiers(text)
    matches: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for supplier in suppliers or []:
        if not isinstance(supplier, dict):
            continue
        name = str(supplier.get("name", "") or "").strip()
        if not name:
            continue
        identifiers: dict[str, list[str]] = {"org_number": [], "bankgiro": []}
        for key in _SUPPLIER_ID_PROFILE_KEYS["org"]:
            number = _normalize_supplier_identifier("org", supplier.get(key, ""))
            if number and number in invoice_ids["org"]:
                identifiers["org_number"].append(number)
        for key in _SUPPLIER_ID_PROFILE_KEYS["bg"]:
            number = _normalize_supplier_identifier("bg", supplier.get(key, ""))
            if number and number in invoice_ids["bg"]:
                identifiers["bankgiro"].append(number)
        org_number = ", ".join(sorted(set(identifiers["org_number"])))
        bankgiro = ", ".join(sorted(set(identifiers["bankgiro"])))
        if not org_number and not bankgiro:
            continue
        identity = (name.casefold(), org_number, bankgiro)
        if identity in seen:
            continue
        matches.append({
            "name": name,
            "org_number": org_number,
            "bankgiro": bankgiro,
        })
        seen.add(identity)
    return sorted(
        matches,
        key=lambda item: (
            item["name"].casefold(), item["org_number"], item["bankgiro"]
        ),
    )


def load_match_learning(path: Path) -> dict:
    """Läser inlärningsminnet tolerant ({} vid saknad/trasig fil)."""
    try:
        import json as _json

        data = _json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_match_learning(path: Path, learning: dict) -> bool:
    """Skriver inlärningsminnet (atomärt via tmp-fil)."""
    try:
        import json as _json

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            _json.dumps(learning, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        tmp.replace(target)
        return True
    except Exception as exc:
        log.warning("save_match_learning: %s", exc)
        return False


def learning_entry(learning: dict | None, supplier: str) -> dict:
    """Minnesposten för en leverantör (namnvarianter tillåts)."""
    if not learning or not supplier:
        return {}
    entry = learning.get(supplier)
    if isinstance(entry, dict):
        return entry
    for name, cand in learning.items():
        if isinstance(cand, dict) and _names_match(
            str(supplier), str(name)
        ):
            return cand
    return {}


def _confirmation_path_key(path: str) -> str:
    """Normaliserar en källsökväg för stabila bekräftelse-ID:n."""
    try:
        return str(Path(path).resolve(strict=False)).casefold()
    except Exception:
        return str(path).replace("\\\\", "/").casefold()


def _legacy_path_confirmation_id(supplier: str, path: str) -> str:
    """Äldre leverantörsbundet ID, för deduplicering efter uppgradering."""
    source = _confirmation_path_key(path)
    if not source:
        return ""
    identity = f"{_fold_text(str(supplier or ''))}|path:{source}"
    return "match-v1:" + hashlib.sha256(
        identity.encode("utf-8", errors="replace")
    ).hexdigest()


def match_confirmation_id(
    supplier: str, invoice_number: str = "", *, path: str = "",
    invoice_date: str = "",
) -> str:
    """Stabilt ID så samma faktura inte räknas som flera träningsprov."""
    supplier_key = _fold_text(str(supplier or ""))
    number = _fold_text(str(invoice_number or ""))
    date = _fold_text(str(invoice_date or ""))
    if path:
        # A physical source file is the identity, not the current supplier
        # choice: changing the supplier must not turn one invoice into a new
        # training sample. The learning store deduplicates this ID across
        # suppliers as well as within one supplier. v2 avoids colliding with
        # legacy, supplier-bound path IDs in existing learning files.
        source = _confirmation_path_key(path)
        identity = f"path:{source}"
        version = "match-v2"
    elif number:
        # Without a source path, include supplier to avoid treating two
        # suppliers' commonly reused invoice numbers as the same document.
        identity = f"{supplier_key}|{number}|{date}"
        version = "match-v1"
    else:
        return ""
    return version + ":" + hashlib.sha256(
        identity.encode("utf-8", errors="replace")
    ).hexdigest()


def template_confirmation_signature(template: dict | None) -> str:
    """Fingerprint för exakt version av en mall; logotyper hålls isär."""
    fields = (template or {}).get("fields", {}) or {}
    if not isinstance(fields, dict) or not fields:
        return ""
    try:
        payload = json.dumps(
            fields, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str,
        )
    except Exception:
        return ""
    return "template-v1:" + hashlib.sha256(
        payload.encode("utf-8", errors="replace")
    ).hexdigest()


def template_confirmation_entry(
    learning: dict | None, supplier: str, template: dict | None
) -> dict:
    """Bekräftelser för den exakta sparade mallversionen."""
    signature = template_confirmation_signature(template)
    entry = learning_entry(learning, supplier)
    templates = entry.get("templates", {}) if isinstance(entry, dict) else {}
    if not signature or not isinstance(templates, dict):
        return {}
    confirmed = templates.get(signature, {})
    return confirmed if isinstance(confirmed, dict) else {}


def confirmed_template_fields(
    template: dict | None, extracted: dict | None,
    confirmed_values: dict | None,
) -> list[str]:
    """Fält vars mallavläsning stämmer exakt med användarens bekräftelse."""
    template_fields = (template or {}).get("fields", {}) or {}
    if not isinstance(template_fields, dict):
        return []
    found = extracted or {}
    confirmed = confirmed_values or {}
    if not isinstance(found, dict) or not isinstance(confirmed, dict):
        return []
    accepted: list[str] = []
    for field, value in found.items():
        if field not in template_fields or field not in confirmed:
            continue
        expected = confirmed.get(field)
        if value in (None, "", 0, 0.0) or expected in (None, "", 0, 0.0):
            continue
        if field == "total_amount":
            try:
                matches = abs(float(value) - float(expected)) <= 0.005
            except (TypeError, ValueError):
                matches = False
        else:
            matches = str(value).strip() == str(expected).strip()
        if matches:
            accepted.append(str(field))
    return accepted


def _remember_confirmation_id(entry: dict, confirmation_id: str) -> bool:
    """True för ett nytt manuellt prov; behåll ett begränsat ID-fönster."""
    identity = str(confirmation_id or "").strip()
    if not identity:
        return True
    ids = entry.get("confirmation_ids", [])
    if not isinstance(ids, list):
        ids = []
    entry["confirmation_ids"] = ids
    if identity in ids:
        return False
    ids.append(identity)
    if len(ids) > 1000:
        del ids[:-1000]
    return True


def _confirmation_owner(
    learning: dict, confirmation_id: str, source_path: str = "",
) -> str:
    """Leverantören som redan tränats på samma stabila faktura-ID.

    Vid uppgradering jämförs även det tidigare leverantörsbundna
    path-ID:t, så en gammal bekräftelse inte räknas en gång till.
    """
    identity = str(confirmation_id or "").strip()
    if not identity and not source_path:
        return ""
    for name, entry in learning.items():
        if not isinstance(entry, dict):
            continue
        ids = entry.get("confirmation_ids", [])
        if not isinstance(ids, list):
            continue
        if identity and identity in ids:
            return str(name)
        if source_path:
            legacy_id = _legacy_path_confirmation_id(
                str(name), source_path
            )
            if legacy_id and legacy_id in ids:
                return str(name)
    return ""


def record_template_confirmation(
    learning: dict, supplier: str, template_name: str,
    template: dict | None, *, confirmation_id: str = "",
    source_path: str = "",
    template_fields: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Sparar en uttrycklig granskning av en viss mallversion.

    Används bland annat av den separata säkerhetskontrollen när
    användaren väljer "Ser rätt ut". Den räknar inte i sig som en
    ny leverantörsmatchning; automatiska leverantörströsklar ändras
    bara av den vanliga manuella matchningsvägen.
    """
    name = str(supplier or "").strip()
    signature = template_confirmation_signature(template)
    if not name or not signature:
        return {}
    key = name
    entry = learning.get(key)
    if not isinstance(entry, dict):
        for existing, candidate in learning.items():
            if isinstance(candidate, dict) and _names_match(
                name, str(existing)
            ):
                key = str(existing)
                entry = candidate
                break
    if not isinstance(entry, dict):
        entry = {}
        learning[key] = entry

    template_entries = entry.setdefault("templates", {})
    if not isinstance(template_entries, dict):
        template_entries = {}
        entry["templates"] = template_entries
    template_entry = template_entries.get(signature)
    if not isinstance(template_entry, dict):
        template_entry = {}
        template_entries[signature] = template_entry
    ids = template_entry.get("confirmation_ids", [])
    legacy_ids = {
        _legacy_path_confirmation_id(candidate, source_path)
        for candidate in (name, key)
        if source_path
    }
    legacy_seen = bool(
        isinstance(ids, list) and any(legacy_id in ids for legacy_id in legacy_ids)
    )
    new_template_confirmation = _remember_confirmation_id(
        template_entry, confirmation_id
    )
    if legacy_seen:
        # Migrate the new source-only ID into the existing list without
        # counting the same file again under this template version.
        new_template_confirmation = False
    if new_template_confirmation:
        template_entry["name"] = str(template_name or name)
        template_entry["confirmed"] = int(
            template_entry.get("confirmed", 0) or 0
        ) + 1
        fields = (template or {}).get("fields", {}) or {}
        accepted_fields = template_fields or []
        if isinstance(fields, dict) and accepted_fields:
            counts = template_entry.setdefault("fields", {})
            if not isinstance(counts, dict):
                counts = {}
                template_entry["fields"] = counts
            for field in accepted_fields:
                field_name = str(field)
                if field_name in fields:
                    counts[field_name] = int(
                        counts.get(field_name, 0) or 0
                    ) + 1
        template_entry["last_confirmed"] = (
            datetime.datetime.now().isoformat(timespec="seconds")
        )
    return template_entry


def record_match_confirmation(
    learning: dict, supplier: str, *, multipage: bool = False,
    text: str = "", logo_signature: str = "",
    confirmation_id: str = "", source_path: str = "",
    template_name: str = "", template: dict | None = None,
    template_fields: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Noterar att användaren bekräftat en matchning.

    Returnerar leverantörens uppdaterade post. Enda författaren
    till minnet är användarens egna val — appen noterar aldrig
    sina automatiska träffar som "inlärda". Org.nr/bankgiro ur
    fakturatexten och en verifierad logotypsignatur räknas per
    leverantör vid varje manuell bekräftelse; nya identifierare
    fortsätter samlas även efter att automatisk koppling börjat.
    """
    name = str(supplier or "").strip()
    if not name:
        return {}
    key = name
    if key not in learning:
        for existing in learning:
            if _names_match(name, str(existing)):
                key = str(existing)
                break
    entry = learning.get(key)
    if not isinstance(entry, dict):
        entry = {}
        learning[key] = entry
    owner = _confirmation_owner(
        learning, confirmation_id, source_path=source_path
    )
    same_owner = bool(
        owner and (owner == key or _names_match(name, owner))
    )
    reassigned_source = bool(owner and not same_owner)
    new_confirmation = not owner
    if new_confirmation:
        _remember_confirmation_id(entry, confirmation_id)
    elif same_owner:
        # When the same supplier's old path ID was found, remember the new
        # source-only ID too, but do not count the invoice a second time.
        _remember_confirmation_id(entry, confirmation_id)
    if new_confirmation:
        entry["confirmed"] = int(entry.get("confirmed", 0) or 0) + 1
        if multipage:
            entry["multipage_confirmed"] = (
                int(entry.get("multipage_confirmed", 0) or 0) + 1
            )
        if text:
            identifiers = entry.setdefault("identifiers", {})
            if not isinstance(identifiers, dict):
                identifiers = {}
                entry["identifiers"] = identifiers
            for kind, values in _invoice_identifiers(text).items():
                bucket = identifiers.setdefault(kind, {})
                if not isinstance(bucket, dict):
                    bucket = {}
                    identifiers[kind] = bucket
                for value in values:
                    bucket[value] = int(bucket.get(value, 0) or 0) + 1
        signature = str(logo_signature or "").strip()
        if signature.startswith(_SUPPLIER_LOGO_HASH_PREFIX):
            logos = entry.setdefault("logos", {})
            if not isinstance(logos, dict):
                logos = {}
                entry["logos"] = logos
            logos[signature] = int(logos.get(signature, 0) or 0) + 1
        entry["last_confirmed"] = datetime.datetime.now().isoformat(
            timespec="seconds"
        )

    if not reassigned_source:
        record_template_confirmation(
            learning, name, template_name or name, template,
            confirmation_id=confirmation_id, source_path=source_path,
            template_fields=template_fields,
        )
    return entry


def require_template_confirmation(
    parsed: dict, templates: dict | None, learning: dict | None,
    suppliers: list[dict] | None = None,
) -> dict:
    """Gör en oprövad egen mall till en synlig, osäker matchning.

    En sparad mall får inte i sig räknas som bekräftelse. Tills minst
    en explicit granskning av just den här mallversionen finns, måste
    Import/bevakningen lämna raden för kontroll. Inbyggda verifierade
    format påverkas inte eftersom de inte finns i användarens mallfil.
    """
    if not isinstance(parsed, dict):
        return parsed
    template_name = str(parsed.get("template", "") or "").strip()
    if not template_name:
        return parsed
    templates = templates if isinstance(templates, dict) else {}
    template = templates.get(template_name)
    if not isinstance(template, dict):
        template = find_template(templates, template_name, suppliers)
    if not isinstance(template, dict):
        return parsed

    supplier = str(parsed.get("supplier", "") or template_name).strip()
    confirmation = template_confirmation_entry(
        learning or {}, supplier, template
    )
    if not confirmation and supplier.casefold() != template_name.casefold():
        confirmation = template_confirmation_entry(
            learning or {}, template_name, template
        )
    try:
        confirmed = int(confirmation.get("confirmed", 0) or 0)
    except (TypeError, ValueError):
        confirmed = 0

    match = parsed.get("template_match")
    if not isinstance(match, dict):
        match = {}
        parsed["template_match"] = match
    match["confirmed"] = confirmed
    match["unconfirmed"] = confirmed <= 0
    if confirmed > 0 or parsed.get("match_uncertain"):
        return parsed

    match.update({
        "status": "uncertain", "template": template_name,
        "candidates": [template_name], "uncertain": True,
        "reason": "template_unconfirmed",
    })
    parsed["match_uncertain"] = True
    parsed["match_candidates"] = [template_name]
    parsed["match_reason"] = "template_unconfirmed"
    parsed["match_kind"] = "template"
    return parsed


def learning_graduated(learning: dict | None, supplier: str) -> bool:
    """True när leverantörens flersidiga fakturor bekräftats av
    användaren tillräckligt många gånger för att få passera
    flersidighetsvakten (med avstämning mot texten)."""
    entry = learning_entry(learning, supplier)
    try:
        count = int(entry.get("multipage_confirmed", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    return count >= MULTIPAGE_CONFIRMATIONS_TO_GRADUATE


def learned_supplier_candidates(
    text: str, learning: dict | None
) -> list[str]:
    """Leverantörer appen LÄRT SIG koppla till den här fakturan.

    En leverantör kvalificerar sig först när användaren själv
    matchat LEARNED_SUPPLIER_CONFIRMATIONS fakturor till den —
    och bara via ett kännetecken (org.nr/bankgiro) som setts i
    minst LEARNED_IDENTIFIER_CONFIRMATIONS av de bekräftade
    fakturorna. Samma kännetecken hos FLERA leverantörer kopplar
    aldrig (det är förorenat — lika gärna fel som rätt) och två
    kvalificerade leverantörer på samma faktura ger båda som
    kandidater, så anroparen frågar i stället för att gissa.
    """
    if not learning or not text:
        return []
    ids = _invoice_identifiers(text)
    if not any(ids.values()):
        return []
    owners: dict[tuple[str, str], set[str]] = {}
    confirmed: dict[str, int] = {}
    for name, entry in learning.items():
        if not isinstance(entry, dict):
            continue
        try:
            confirmed[str(name)] = int(entry.get("confirmed", 0) or 0)
        except (TypeError, ValueError):
            confirmed[str(name)] = 0
        buckets = entry.get("identifiers", {}) or {}
        if not isinstance(buckets, dict):
            continue
        for kind, bucket in buckets.items():
            if not isinstance(bucket, dict):
                continue
            for value, count in bucket.items():
                try:
                    seen = int(count or 0)
                except (TypeError, ValueError):
                    seen = 0
                if seen >= LEARNED_IDENTIFIER_CONFIRMATIONS:
                    owners.setdefault(
                        (str(kind), str(value)), set()
                    ).add(str(name))
    out: list[str] = []
    for kind, values in ids.items():
        for value in sorted(values):
            names = owners.get((kind, value), set())
            if len(names) != 1:
                continue  # okänt eller förorenat kännetecken
            name = next(iter(names))
            if confirmed.get(name, 0) < LEARNED_SUPPLIER_CONFIRMATIONS:
                continue  # för få bekräftade fakturor än
            if name not in out:
                out.append(name)
    return out


def learned_supplier_logo(
    learning: dict | None, supplier: str, signature: str
) -> bool:
    """Logo får auto-koppla först efter samma säkra inlärningströskel.

    Kräver fem manuellt bekräftade fakturor för leverantören,
    logotypen sedd minst två gånger och ett starkt visuellt hash-avstånd.
    """
    if not signature:
        return False
    entry = learning_entry(learning, supplier)
    try:
        confirmations = int(entry.get("confirmed", 0) or 0)
        logo_count = int(
            (entry.get("logos", {}) or {}).get(signature, 0) or 0
        )
    except (TypeError, ValueError, AttributeError):
        return False
    return (
        confirmations >= LEARNED_SUPPLIER_CONFIRMATIONS
        and logo_count >= LEARNED_IDENTIFIER_CONFIRMATIONS
    )


def derive_template_from_confirmation(
    text: str, invoice_number: str, total: Any
) -> dict | None:
    """Härled en leverantörsmall ur användarens BEKRÄFTADE värden.

    När en faktura matchats för hand och leverantören saknar mall
    prövas vanliga etiketter mot fakturans egen text: en etikett
    som läser tillbaka EXAKT de värden användaren just bekräftat
    (fakturanummer + att betala) får bli leverantörens mall.
    Verifieringen är hela poängen — kan etiketterna inte läsa
    tillbaka de bekräftade värdena lär sig appen ingenting alls
    (None), i stället för att spara en gissad mall.
    """
    if not text:
        return None
    want_nr = str(invoice_number or "").strip()
    try:
        want_total = float(total or 0)
    except (TypeError, ValueError):
        return None
    if not want_nr or want_total <= 0:
        return None
    fields: dict[str, dict] = {}
    for field, want in (
        ("invoice_number", want_nr), ("total_amount", None),
    ):
        kind = TEMPLATE_FIELD_KINDS[field]
        for cand in _REPAIR_LABELS.get(field, ()):
            spec: dict[str, Any] = {"label": cand}
            raw = extract_with_label(text, cand, kind)
            if not _confirmed_value_matches(raw, kind, want, want_total):
                below = _extract_below_label(text, cand, kind)
                if not _confirmed_value_matches(
                    below, kind, want, want_total
                ):
                    continue
                spec["below"] = True
            fields[field] = spec
            break
    if set(fields) != {"invoice_number", "total_amount"}:
        return None
    template = {"fields": fields}
    # Hela mallen måste läsa tillbaka de bekräftade värdena —
    # annars är den ingen inlärning, bara en ny gissning.
    found = apply_template(text, template)
    if str(found.get("invoice_number", "")).strip() != want_nr:
        return None
    try:
        if abs(float(found.get("total_amount") or 0) - want_total) > 0.005:
            return None
    except (TypeError, ValueError):
        return None
    return template


def _confirmed_value_matches(
    raw: str, kind: str, want_nr: str, want_total: float
) -> bool:
    """Stämmer en avläsning med det användaren bekräftade?"""
    if not raw:
        return False
    if kind == "amount":
        try:
            return abs(float(raw) - want_total) <= 0.005
        except (TypeError, ValueError):
            return False
    return str(raw).strip() == want_nr


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
