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
            v = _amount_from_group(m.group(1))
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
    return re.sub(
        r"\s", "",
        _search(text, (r"OCR\s*[:#]?\s*(\d[\d \-]{4,24}\d)",)),
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
_SUPPLIER_ID_KEYS = (
    "org_number", "orgnr", "org",
    "bankgiro", "bg", "plusgiro", "pg",
)


def match_supplier(text: str, suppliers: list[dict]) -> str:
    """
    Matchar texten mot kända leverantörer och returnerar namnet
    eller "" (inget gissas vid tvetydighet).

    Starka träffar: org.nr/bankgiro/plusgiro i texten, eller
    leverantörens namn — vikt så att "AB Martin G Anderson",
    "Martin G. Anderson" och OCR-varianten utan prickar är samma
    leverantör. Ordmängden räcker också (alla betydelsebärande
    ord på fakturan), vilket klarar bolagsform före/efter namnet
    och annan ordning. Delad förstanamns-träff ("Pilkington ...")
    används bara om den är ensam om bästa poäng.
    """
    digits = re.sub(r"\D", "", text or "")
    folded = _fold_text(text)
    folded_tokens = set(folded.split())
    best: list[str] = []
    best_score = 0
    for sup in suppliers or []:
        name = str(sup.get("name", "")).strip()
        if not name:
            continue
        score = 0
        name_fold = _fold_text(name)
        tokens = _name_tokens(name)
        token_set = set(tokens)
        if name_fold and name_fold in folded:
            score += 6
        elif token_set and token_set <= folded_tokens and (
            len(token_set) >= 2
            or (tokens and len(tokens[0]) >= 4)
        ):
            score += 5
        elif tokens and len(tokens[0]) >= 5 \
                and tokens[0] in folded_tokens:
            # Ensamt särskiljande förstanamn ("Pilkington Sverige
            # AB" på en faktura som bara trycker "Pilkington").
            score += 3
        for key in _SUPPLIER_ID_KEYS:
            num = re.sub(r"\D", "", str(sup.get(key, "") or ""))
            if len(num) >= 6 and num in digits:
                score += 5
                break
        if score > best_score:
            best, best_score = [name], score
        elif score == best_score and score > 0:
            best.append(name)
    if best_score >= 5 and len(best) == 1:
        return best[0]
    if best_score == 3 and len(best) == 1:
        return best[0]
    return ""


def parse_invoice_text(
    text: str,
    suppliers: list[dict] | None = None,
    templates: dict | None = None,
    region_texts: dict | None = None,
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
    supplier = match_supplier(text or "", suppliers or [])
    template_name = ""
    template_fields: list[str] = []

    if templates:
        if not supplier:
            supplier = match_supplier(
                text or "", [{"name": n} for n in templates.keys()]
            )
        template = find_template(templates, supplier) if supplier else None
        if template is None and region_texts:
            # Regionsmall (användaren har pekat ut värdena på
            # fakturabilden): mallens ruttexter gav träffar —
            # mallen identifierar då leverantören själv, även
            # när löptexten saknar igenkännbart namn/nummer.
            for cand_name, cand in templates.items():
                if not isinstance(cand, dict):
                    continue
                if template_values_from_regions(
                    cand, region_texts
                ):
                    template = cand
                    if not supplier:
                        supplier = str(cand_name)
                    break
        if template:
            found = apply_template(text or "", template)
            if region_texts:
                # Utpekade rutor på fakturabilden vinner över
                # etikettläsningen — platsen är explicit angiven.
                found.update(
                    template_values_from_regions(
                        template, region_texts
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
            if found:
                template_name = supplier

    if not template_name:
        builtin = builtin_template_for(text or "")
        if builtin:
            bname, btmpl = builtin
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
            if "invoice_number" in found and (
                total_ok or is_credit_note(text or "")
            ):
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
    return result


def parse_invoice_file(
    path: Any,
    text: str,
    suppliers: list[dict] | None = None,
    templates: dict | None = None,
) -> dict[str, Any]:
    """Tolkning av en FIL: löptext + eventuella regionsmallar.

    Mallar vars fält pekar ut rutor på fakturabilden (region)
    läses ur själva filen (textlager i rutan, annars OCR) och
    får avgöra fälten. Första mallen vars rutor ger ett
    fakturanummer eller ett att betala-belopp används — resten
    av tolkningen är exakt densamma som för ren text.
    """
    tpl = templates or {}
    for _name, cand in tpl.items():
        if not isinstance(cand, dict):
            continue
        fields = cand.get("fields", {}) or {}
        if not any(
            isinstance(spec, dict) and spec.get("region")
            for spec in fields.values()
        ):
            continue
        rtext = extract_region_texts(path, cand)
        vals = template_values_from_regions(cand, rtext)
        if vals.get("invoice_number") or vals.get("total_amount"):
            return parse_invoice_text(
                text, suppliers, tpl, region_texts=rtext
            )
    return parse_invoice_text(text, suppliers, tpl)


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
    första värdet av rätt typ EFTER etiketten — först på samma rad,
    annars inom de närmaste 120 tecknen. Returnerar strängvärde
    (belopp som float-sträng, datum som YYYY-MM-DD) eller "".
    """
    if not text or not label:
        return ""
    flat = re.sub(r"[ \t]+", " ", text)
    lab = re.sub(r"\s+", " ", str(label)).strip().rstrip(":#").strip()
    if not lab:
        return ""
    for m in re.finditer(re.escape(lab), flat, re.IGNORECASE):
        window = flat[m.end(): m.end() + 160]
        same_line = window.split("\n", 1)[0]
        hit = _extract_kind(same_line, kind, m.group(0))
        if hit:
            return hit
        if same_line.strip() and kind != "token":
            # Text finns på etikettens rad men värdet saknas —
            # troligen en kolumnrubrik i en rubrikrad ("Fakturanr.
            # Fakturadatum Kundnr."): nästa förekomst. För token
            # gäller rubrik-hoppet i stället (stopporden) — ett
            # nummer kan aldrig stå på nästa rad i radvis text.
            continue
        if kind != "token":
            hit = _extract_kind(window, kind, m.group(0))
            if hit:
                return hit
    return ""


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
    for m in re.finditer(re.escape(lab), flat, re.IGNORECASE):
        rest_line = flat[m.end():].split("\n", 1)[0]
        if _extract_kind(rest_line, kind, m.group(0)):
            # Vanlig etikett+värde-rad — aldrig rubrikrad.
            continue
        lineno = flat.count("\n", 0, m.end())
        for below in lines[lineno + 1:]:
            if not below.strip():
                continue
            hit = _extract_below_line(below, kind)
            if hit:
                return hit
            break
    return ""


def _label_below_amount(text: str, label: str) -> float | None:
    """Beloppet i kolumnen under etiketten ("Att betala")."""
    hit = _extract_below_label(text, label, "amount")
    return float(hit) if hit else None


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
    return 1 if p.suffix.lower() in SCAN_EXTENSIONS else 0


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
            return p.read_bytes()
        except Exception as exc:
            log.warning("bild %s: %s", p, exc)
    return None


def find_template(templates: dict, supplier: str) -> dict | None:
    """Mall för leverantörsnamn: exakt först, annars vikt
    namnmatchning ("AB Nordlys Energi" hittar mallen för
    "Nordlys Energi AB"). Tvetydighet ger None — fel leverantörs
    mall får aldrig användas av misstag."""
    if not templates or not supplier:
        return None
    if supplier in templates:
        return templates[supplier]
    folded = _fold_text(supplier)
    exact = [
        tmpl for name, tmpl in templates.items()
        if _fold_text(name) == folded
    ]
    if len(exact) == 1:
        return exact[0]
    hits = [
        tmpl for name, tmpl in templates.items()
        if _names_match(name, supplier)
    ]
    return hits[0] if len(hits) == 1 else None


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


def builtin_template_for(text: str) -> tuple[str, dict] | None:
    """
    Inbyggt verifierat format för texten → (namn, mall) eller
    None. Träff kräver org.nr/bankgiro i texten eller det
    tryckta leverantörsnamnet — registerpostens namn används
    aldrig (det kan vara ett helt annat, t.ex. Direktglas).
    """
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    flat = _fold_text(text)
    for fmt in BUILTIN_FORMATS:
        if fmt["org"] and fmt["org"] in digits:
            return fmt["name"], {"fields": dict(fmt["fields"])}
        if fmt["bg"] and fmt["bg"] in digits:
            return fmt["name"], {"fields": dict(fmt["fields"])}
        if any(_fold_text(p) in flat for p in fmt["printed"]):
            return fmt["name"], {"fields": dict(fmt["fields"])}
    return None


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
    for m in re.finditer(re.escape(lab), flat, re.IGNORECASE):
        same_line = flat[m.end():].split("\n", 1)[0]
        hit = _extract_kind(same_line, "amount", m.group(0))
        if hit:
            return float(hit)
    return None


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
