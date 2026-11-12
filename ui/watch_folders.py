# -*- coding: utf-8 -*-
"""
watch_folders — bevakade mappar för automatisk fakturaimport.

Idén: varje leverantör kan ha en egen mapp (t.ex. Pilkington,
Direktglas). När en ny fakturafil dyker upp i mappen:

  1. Filen hashas (sha256) — samma innehåll importeras aldrig två
     gånger, även om filen byter namn.
  2. Texten extraheras och tolkas (med leverantörsmallar!).
     Mappens leverantör används om den är angiven.
  3. Dubblett mot registret (samma leverantör + fakturanummer)
     stoppas alltid.
  4. Komplett faktura → registreras automatiskt (om auto-läget är
     på). När registreringen lyckas flyttas originalet till
     <bevakad mapp>/<fakturans år>/ och fakturans sökväg följer med.
     Ofullständiga/obekräftade filer stannar kvar för granskning.
  5. Ofullständig tolkning, eller komplett tolkning UTAN träff
     på en inlärd leverantörsmall → parkeras för granskning och
     manuell matchning i Import-vyn. Alla leverantörer har egen
     layout, så naken heuristik får aldrig registrera automatiskt
     — först när användaren lärt appen leverantören (mall), eller
     leverantörens format finns inbyggt efter manuell verifiering
     mot riktiga exempelfakturor, blir mappen automatisk.
     Aldrig tyst tappad, aldrig gissad.

Konfiguration + bearbetningsregister bor i
data/watch_folders.json. Allt loggas (SCAN_WATCH).
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QObject, QRunnable, QThreadPool, QTimer, Signal,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

try:
    from ui.i18n import tr
except Exception:  # pragma: no cover
    try:
        from i18n import tr  # type: ignore[no-redef]
    except Exception:
        def tr(key: str, **_f: object) -> str:  # type: ignore[no-redef]
            return key

log = logging.getLogger("WatchFolders")

import os
import re
import time

#: Hur länge en fil måste ha varit oförändrad mellan två kontroller innan
#: bevakningen öppnar och tolkar den. Nya filer får en separat, snabb
#: omkontroll i stället för att vänta på den ordinarie 30-sekunderspollningen.
FILE_STABILITY_SECONDS = 2.0
FILE_STABILITY_RECHECK_MS = 1500

#: Filtyper som bevakningen tar (PDF/bilder — .txt räknas inte,
#: extraktorn känner inte igen den).
SUPPORTED_SUFFIXES: tuple[str, ...] = (
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
)


def supported_file(path: Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


def supported_invoice_files(folder) -> list[Path]:
    """
    PDF/bild-filerna i en (bevakad) mapp — även i årsmappar
    (<år>/), sorterade på filnamn. Arkiv/ hoppas över: betalda
    original ska aldrig skannas om som nya fakturor.

    Används av bevakningen själv samt av lär-flödet (välj en
    exempelfaktura att visa appen) och för att avgöra om en
    mapp alls har något att lära från.
    """
    try:
        root = Path(str(folder))
        found = []
        for dirpath, dirs, names in os.walk(root):
            # Arkiv/ = betalda original — plocka bort hela trädet
            dirs[:] = [d for d in dirs if d.lower() != "arkiv"]
            for name in names:
                cand = Path(dirpath) / name
                if cand.is_file() and supported_file(cand):
                    found.append(cand)
        return sorted(found, key=lambda p: p.name.lower())
    except Exception:
        return []


def iter_invoice_files(folder):
    """Som supported_invoice_files, men en filsökväg i taget.

    Skanningen använder generatorn så att GUI-tråden kan ritas om
    mellan filerna i stället för att frysa under en hel mapptraversering.
    """
    try:
        root = Path(str(folder))
        for dirpath, dirs, names in os.walk(root):
            dirs[:] = [
                d for d in dirs
                if d.lower() != "arkiv" and not d.startswith(".")
            ]
            for name in sorted(names, key=str.lower):
                cand = Path(dirpath) / name
                if supported_file(cand):
                    yield cand
    except Exception:
        return


def file_hash(path: Path) -> str:
    """sha256 av filinnehållet (chunkad läsning)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def invoice_exists(
    invoices: list[dict], supplier: str, invoice_number: str
) -> bool:
    """Dubblettkontroll: samma leverantör + fakturanummer."""
    nr = str(invoice_number or "").strip().lower()
    if not nr:
        return False
    sup = str(supplier or "").strip().lower()
    for inv in invoices or []:
        if (
            str(inv.get("supplier", "")).strip().lower() == sup
            and str(inv.get("invoice_number", "")).strip().lower() == nr
        ):
            return True
    return False


def invoice_control_changes(inv: dict, parsed: dict) -> dict:
    """Jämför en nytolkning av originalet mot den registrerade
    fakturan: {fält: (registrerat, nytolkat)} för avvikelserna.

    Bara värden tolkningen läst med säkerhet räknas — det krävs
    att en mall gjort strikt anspråk på läsningen (mall satt,
    inget saknas), annars är originalet troligen en annan eller
    oläsbar faktura och jämförelsen påstår ingenting.
    Registrerade data ändras ALDRIG härifrån; jämförelsen
    rapporterar bara — rättningen gör användaren per faktura
    (Fakturor → högerklick → Skanna om faktura)."""
    changes: dict[str, tuple] = {}
    if not parsed.get("template") or parsed.get("missing"):
        return changes
    new_nr = str(parsed.get("invoice_number", "") or "").strip()
    old_nr = str(inv.get("invoice_number", "") or "").strip()
    if new_nr and new_nr.lower() != old_nr.lower():
        changes["invoice_number"] = (old_nr, new_nr)
    for field in ("date", "due_date"):
        new = str(parsed.get(field, "") or "").strip()
        old = str(inv.get(field, "") or "").strip()
        if new and new != old:
            changes[field] = (old, new)
    try:
        new_total = float(parsed.get("total_amount") or 0)
    except (TypeError, ValueError):
        new_total = 0.0
    try:
        old_total = float(inv.get("total_amount") or 0)
    except (TypeError, ValueError):
        old_total = 0.0
    if new_total and abs(new_total - old_total) > 0.005:
        changes["total_amount"] = (old_total, new_total)
    return changes


def _norm_path_key(path: str) -> str:
    """Sökväg som jämförelsenyckel: "D:/gewgg/f.pdf" och
    "D:\\gewgg\\f.pdf" är samma fil. Registrets sökvägar kan
    komma från fil dialogs (/) medan skanningen bygger dem med
    OS-separator — utan normalisering missar jämförelserna
    tyst fast originalet ligger mitt i den bevakade mappen.
    Båda snedstrecksslagen slås ihop på alla plattformar (inte
    bara Windows), så även felsökningsdiagnosens jämförelser
    blir likadana överallt."""
    raw = str(path or "").replace("\\", "/")
    parts: list[str] = []
    for seg in raw.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    key = "/".join(parts)
    if raw.startswith("/"):
        key = "/" + key
    return os.path.normcase(key)


def _norm_supplier_name(name: str) -> frozenset:
    """Namn som ordmängd utan bolagsform/tecken: "AB Martin G
    Anderson" och "Martin G" → samma respektive delmängd."""
    words = re.findall(r"[a-zåäö0-9]+", str(name or "").lower())
    return frozenset(
        w for w in words if w not in ("ab", "aktiebolag", "och", "&")
    )


def load_scan_module():
    """Importerar scan_import med plugins/ på sys.path.

    Ren modulimport (ingen QObject, ingen appdata): säker att anropa
    både från GUI-tråden och från tolkningsarbetaren.
    """
    import sys

    plugins = str(Path(__file__).resolve().parent.parent / "plugins")
    if plugins not in sys.path:
        sys.path.insert(0, plugins)
    import scan_import as si

    return si


def resolve_supplier_in(suppliers: list[dict], wanted: str) -> str:
    """Slår upp ett mappnamn mot registret tolerant.

    Mappen kan heta "Martin G" medan registerposten heter
    "AB Martin G Anderson" — exakt namnmatchning stoppade då
    registreringen. Namnen jämförs normaliserade (bolagsform/punkt
    borta, ordmängd): exakt eller entydig delmängd ger träff.
    """
    want = _norm_supplier_name(wanted)
    if not want:
        return ""
    candidates: list[str] = []
    for sup in suppliers or []:
        name = str(sup.get("name", "")).strip()
        have = _norm_supplier_name(name)
        if not have:
            continue
        if have == want:
            return name
        if want <= have or have <= want:
            candidates.append(name)
    return candidates[0] if len(candidates) == 1 else ""


def parse_watched_file(
    si: Any,
    path: Path,
    folder_supplier: str,
    suppliers: list[dict],
    templates: dict | None,
    learning: dict | None,
    extract_fn: Callable[[Path], tuple[str, str]] | None = None,
) -> tuple[str, str, dict]:
    """Textuttag + tolkning av EN fil, med mappens leverantör påtvingad.

    Allt tunga arbete (PDF-läsning, OCR, mallmatchning) sker här och
    använder bara de data som skickas in — aldrig appens register eller
    Qt-objekt. Därför kan funktionen köras i en arbetstråd så att
    GUI-tråden förblir svarande medan stora skanningar pågår.
    """
    if extract_fn is not None:
        text, method = extract_fn(path)
    else:
        text, method = si.extract_text(path)
    templates = templates or {}
    learning = learning or {}
    parse_file = getattr(si, "parse_invoice_file", None)
    if parse_file is not None:
        try:
            parsed = parse_file(
                path, text or "", suppliers,
                templates=templates, match_learning=learning,
            )
        except TypeError:
            parsed = parse_file(
                path, text or "", suppliers, templates=templates,
            )
    else:
        parsed = si.parse_invoice_text(
            text or "", suppliers, templates=templates,
            match_learning=learning,
        )
    folder_supplier = str(folder_supplier or "").strip()
    if folder_supplier:
        resolved = resolve_supplier_in(suppliers, folder_supplier)
        if resolved and resolved != folder_supplier:
            log.info(
                "SCAN_WATCH: mappens leverantör '%s' → "
                "registerposten '%s'",
                folder_supplier, resolved,
            )
            folder_supplier = resolved
        parsed_supplier = str(parsed.get("supplier", "") or "").strip()
        names_match = getattr(si, "_names_match", None)
        same_supplier = bool(
            parsed_supplier
            and (
                parsed_supplier.lower() == folder_supplier.lower()
                or (
                    callable(names_match)
                    and names_match(parsed_supplier, folder_supplier)
                )
            )
        )
        if parsed.get("match_uncertain"):
            # Mappens leverantör är bara ännu en kandidat när
            # tolkningen själv är osäker — den får inte tyst
            # avgöra valet åt användaren.
            candidates = [
                str(c).strip()
                for c in parsed.get("match_candidates", []) or []
                if str(c).strip()
            ]
            if folder_supplier.lower() not in {
                c.lower() for c in candidates
            }:
                candidates.append(folder_supplier)
            parsed["match_candidates"] = candidates
            parsed["folder_supplier_candidate"] = folder_supplier
            if "leverantör" not in parsed.get("missing", []):
                parsed.setdefault("missing", []).append("leverantör")
        elif parsed_supplier and not same_supplier:
            # Fakturans egen starka leverantörsträff och mappens
            # kopplade leverantör pekar åt olika håll. Det är en
            # konflikt användaren ska avgöra, inte något
            # mappinställningen får köra över i tysthet.
            parsed["supplier"] = ""
            parsed["match_uncertain"] = True
            parsed["match_candidates"] = [
                parsed_supplier, folder_supplier,
            ]
            parsed["match_reason"] = "competing"
            parsed["match_kind"] = "supplier"
            parsed["folder_supplier_candidate"] = folder_supplier
            if "leverantör" not in parsed.get("missing", []):
                parsed.setdefault("missing", []).append("leverantör")
        else:
            parsed["supplier"] = folder_supplier
            parsed["missing"] = [
                m for m in parsed.get("missing", [])
                if m != "leverantör"
            ]
    if "ocr-saknas" in str(method) or "ocr-fel" in str(method):
        parsed["ocr_warning"] = str(method)
    assessor = getattr(si, "assess_invoice_payment_details", None)
    if callable(assessor):
        parsed = assessor(
            parsed, text or "", suppliers,
            details=parsed.get("invoice_payment_details"),
        )
    template_guard = getattr(
        si, "require_template_confirmation", None
    )
    if callable(template_guard):
        parsed = template_guard(
            parsed, templates, learning, suppliers
        )
    return text, method, parsed


_PARK_REASON_SV = {
    "no-template": (
        "okänt format för leverantören — appen har ingen inlärd "
        "mall och inget inbyggt verifierat format träffar"
    ),
    "review": (
        "auto-registrering avstängd — väntar på manuell granskning"
    ),
    "uncertain-supplier": (
        "osäker leverantörs- eller mallmatchning — appen frågar "
        "användaren i stället för att gissa"
    ),
    "ocr-warning": (
        "OCR saknas eller misslyckades på minst en sida — fakturan "
        "parkeras för kontroll och registreras inte automatiskt"
    ),
    "payment-details": (
        "Bankgiro, Plusgiro eller IBAN på fakturan avviker från "
        "leverantörens sparade uppgifter — kontrollera mottagaren"
    ),
}


def _park_reason_sv(reason: str) -> str:
    reason = str(reason or "").strip()
    if reason.startswith("missing:"):
        return "saknar uppgifter: " + reason.split(":", 1)[1].strip()
    if reason.startswith("possible-duplicate:"):
        return (
            "möjlig dubblett av redan registrerad faktura — "
            + reason.split(":", 1)[1].strip()
            + ". Registreras inte automatiskt; granska och avgör."
        )
    return _PARK_REASON_SV.get(reason, reason or "okänd orsak")


#: Fältnamn i malldiagnosen (som användaren ser dem).
_DIAG_FIELD_SV = {
    "invoice_number": "fakturanr",
    "total_amount": "att betala",
    "date": "fakturadatum",
    "due_date": "förfallodatum",
    "ocr": "OCR",
}

#: Högsta antal djupdiagnoser per felsökningspaket — paketet
#: ska gå att klistra in någonstans, inte vara en roman.
_DIAG_MAX_FILES = 10


def _template_diag_lines(
    path: str,
    suppliers: list[dict] | None,
    templates: dict | None,
) -> list[str]:
    """Malldiagnos för EN parkerad fil: per textuttag vilket
    format som var kandidat, vilka fält som hittades och exakt
    vilket krav som brast. Rent läsande (scan_import sköter
    analysen); fel här får aldrig kasta paketet."""
    import scan_import as si

    lines = ["      malldiagnos (varför ingen mall tog filen):"]
    try:
        diags = si.diagnose_invoice_file(
            path, suppliers or [], templates or {}
        )
    except Exception as exc:
        return [f"      malldiagnos: kunde inte köras ({exc})"]
    for d in diags:
        head = (
            f"        · uttag {d.get('method', '—')} "
            f"({int(d.get('chars', 0) or 0)} tecken)"
        )
        if d.get("claimed"):
            lines.append(
                head
                + " — mallen ”{}” TAR texten (fakturanr={}, "
                "att betala={})".format(
                    d.get("template") or d.get("candidate") or "?",
                    d.get("invoice_number") or "—",
                    d.get("total_amount") or "—",
                )
            )
        elif d.get("candidate"):
            bits = []
            for field, value in (d.get("fields") or {}).items():
                bits.append(
                    "{}={}".format(
                        _DIAG_FIELD_SV.get(field, field),
                        value if value not in (None, "") else "—",
                    )
                )
            failed = list(d.get("failed") or [])
            tail = ""
            if d.get("total_verified") is False:
                failed = [
                    f for f in failed if f != "total_amount"
                ]
                tail = (
                    " — brister: att betala (värdet {} stämmer "
                    "inte mot etikettens rad/värderad)".format(
                        (d.get("fields") or {}).get("total_amount")
                    )
                )
            if failed:
                names = ", ".join(
                    _DIAG_FIELD_SV.get(f, f) for f in failed
                )
                tail += (
                    (" — brister: " if not tail else ", ")
                    + names
                )
            lines.append(
                head
                + " — {} ”{}”: ".format(
                    d.get("candidate_kind") or "mall",
                    d.get("candidate"),
                )
                + (", ".join(bits) or "(inga fält)")
                + (
                    tail
                    or " — alla fält funna men anspråket "
                    "nekades ändå"
                )
            )
        else:
            lines.append(
                head + " — "
                + (
                    d.get("note")
                    or "ingen mall var kandidat för texten"
                )
            )
        preview = " ".join((d.get("preview") or "").split())
        if preview:
            lines.append(f"          textstart: {preview[:200]}")
    return lines


def watch_diagnostic_lines(
    config: dict | None,
    stats: dict | None = None,
    suppliers: list[dict] | None = None,
    templates: dict | None = None,
) -> list[str]:
    """Diagnosrader om bevakningen för felsökningspaketet.

    Det viktiga: inte bara ATT något inte lästs in, utan VARFÖR.
    Per bevakad mapp: finns den, hur många fakturafiler ser
    skanningen, senaste skanningens utfall, varje parkerad fil
    med sin orsak — och filer som setts men inte hunnit läsas.
    config är watch_folders-strukturen (folders/parked/processed)
    antingen från den levande WatchManager eller filen på disk.
    """
    cfg = config if isinstance(config, dict) else {}
    folders = [f for f in cfg.get("folders", []) if isinstance(f, dict)]
    parked = [p for p in cfg.get("parked", []) if isinstance(p, dict)]
    processed = cfg.get("processed", {}) or {}
    lines: list[str] = []
    if stats:
        lines.append(
            "senaste skanning: {imported} nya fakturor, "
            "{duplicate} dubbletter (redan registrerade; exakta original "
            "kan årsarkiveras), "
            "{parked} parkerade, {already} redan bearbetade, "
            "{waiting} väntar i parkering, {settling} skrivs ännu, "
            "{errors} läsfel".format(
                **{
                    k: int((stats or {}).get(k, 0) or 0)
                    for k in (
                        "imported", "duplicate", "parked", "already",
                        "waiting", "settling", "errors",
                    )
                }
            )
        )
    lines.append(
        "auto-registrering: "
        + ("PÅ" if cfg.get("auto_create", True) else "AV")
        + f" · bearbetade filer i registret: {len(processed)}"
        + f" · parkerade just nu: {len(parked)}"
    )
    parked_by_hash = {
        str(p.get("hash", "")): p for p in parked if p.get("hash")
    }
    parked_keys = {_norm_path_key(p.get("path", "")) for p in parked}
    shown_parked: set[str] = set()

    def _folder_of(entry_path: str) -> str:
        key = _norm_path_key(entry_path)
        for f in folders:
            root = _norm_path_key(f.get("path", ""))
            if root and (
                key == root or key.startswith(root + os.sep)
            ):
                return root
        return ""

    diag_used = 0
    for entry in folders:
        folder = Path(str(entry.get("path", "")))
        supplier = str(entry.get("supplier") or "?")
        if not folder.is_dir():
            lines.append(
                f"✗ {folder} (leverantör {supplier}) — MAPPEN "
                "SAKNAS eller kan inte öppnas; dess filer läses "
                "inte in alls"
            )
            continue
        try:
            files = [
                f for f in supported_invoice_files(folder) if f.is_file()
            ]
        except Exception as exc:
            lines.append(
                f"✗ {folder} (leverantör {supplier}) — kunde inte "
                f"lista filer: {exc}"
            )
            continue
        mine = [
            p for p in parked
            if _folder_of(str(p.get("path", "")))
            == _norm_path_key(str(folder))
        ]
        lines.append(
            f"• {folder} (leverantör {supplier}) — {len(files)} "
            f"fakturafil(er) sedda av skanningen, {len(mine)} "
            "parkerade här"
        )
        unread: list[str] = []
        for fpath in files:
            try:
                digest = file_hash(fpath)
            except Exception:
                continue
            if digest in processed or digest in parked_by_hash:
                continue
            if _norm_path_key(str(fpath)) in parked_keys:
                continue
            unread.append(fpath.name)
        for p in mine[:15]:
            shown_parked.add(_norm_path_key(p.get("path", "")))
            lines.append(
                "    parkerad: {} — {} (sedan {})".format(
                    p.get("file") or Path(
                        str(p.get("path", ""))
                    ).name,
                    _park_reason_sv(p.get("reason", "")),
                    str(p.get("ts", "") or "?")[:16],
                )
            )
            _parsed = p.get("parsed") or {}
            if _parsed or p.get("method"):
                lines.append(
                    "      tolkat: fakturanr={nr} belopp={amt} "
                    "mall={tpl} saknar={mis} (metod={met}, "
                    "{n} tecken text)".format(
                        nr=_parsed.get("invoice_number") or "—",
                        amt=_parsed.get("total_amount") or "—",
                        tpl=_parsed.get("template") or "—",
                        mis=(
                            ", ".join(_parsed.get("missing") or [])
                            or "—"
                        ),
                        met=p.get("method") or "—",
                        n=len(p.get("text", "") or ""),
                    )
                )
            _reason = str(p.get("reason", "") or "")
            if diag_used < _DIAG_MAX_FILES and (
                _reason == "no-template"
                or _reason.startswith("missing:")
                or (_parsed and not _parsed.get("template"))
            ):
                diag_used += 1
                _ppath = str(p.get("path", "") or "")
                if _ppath and Path(_ppath).is_file():
                    lines.extend(
                        _template_diag_lines(
                            _ppath, suppliers, templates
                        )
                    )
                else:
                    lines.append(
                        "      malldiagnos: filen finns inte "
                        "kvar på sökvägen"
                    )
        if len(mine) > 15:
            lines.append(
                f"    … och {len(mine) - 15} parkerade till "
                "(se Import-flikens parkerade filer)"
            )
        for name in unread[:10]:
            lines.append(
                f"    ej inläst ännu: {name} — skanningen har "
                "sett filen men inte läst in den; prövas vid "
                "nästa skanning (eller Import → 🔍 Skanna nu)"
            )
        if len(unread) > 10:
            lines.append(
                f"    … och {len(unread) - 10} filer till som "
                "väntar på inläsning"
            )
    stray = [
        p for p in parked
        if _norm_path_key(p.get("path", "")) not in shown_parked
        and not _folder_of(str(p.get("path", "")))
    ]
    for p in stray[:10]:
        lines.append(
            "parkerad (annan mapp): {} — {}".format(
                p.get("file") or "?",
                _park_reason_sv(p.get("reason", "")),
            )
        )
    if not folders:
        lines.append(
            "inga bevakade mappar konfigurerade — lägg till i "
            "Import-fliken; då läses inga filer in automatiskt"
        )
    return lines


#: Hur många filsignaturer (sökväg → storlek/tid/hash) som cachas.
#: Cachen gör att en 30-sekunderspoll inte hashar om tusentals
#: oförändrade original — det var den största orsaken till att
#: appen kunde stå still i minuter vid stora mappar.
HASH_CACHE_MAX = 6000

#: En fil som tar längre tid än så att tolka avbryter skanningen i
#: stället för att hänga appen för alltid. Filen prövas nästa gång.
ANALYSIS_TIMEOUT_MS = 180_000

#: Hur länge skanningen får arbeta innan den lämnar tillbaka till
#: GUI-tråden (mellan filer, aldrig inuti en tolkning).
SCAN_SLICE_SECONDS = 0.05


class _AnalysisSignals(QObject):
    """Signaler från tolkningsarbetaren tillbaka till GUI-tråden."""

    finished = Signal(int, object)
    failed = Signal(int, str)


class _AnalyzeFileTask(QRunnable):
    """Tolkar EN fil (textutdrag, OCR, mallmatchning) i en arbetstråd.

    Arbetaren rör aldrig appens register, konfiguration eller Qt-vyer;
    den får en eller flera kopior av leverantörer/mallar/inlärning och
    returnerar resultatet som en signal. Alla beslut och alla
    registerskrivningar sker därefter i GUI-tråden.
    """

    def __init__(
        self,
        token: int,
        path: Path,
        folder_supplier: str,
        suppliers: list[dict],
        templates: dict,
        learning: dict,
        signals: _AnalysisSignals,
        extract_fn: Callable[[Path], tuple[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._token = int(token)
        self._path = Path(path)
        self._folder_supplier = str(folder_supplier or "")
        self._suppliers = suppliers
        self._templates = templates
        self._learning = learning
        self._signals = signals
        self._extract_fn = extract_fn

    def run(self) -> None:  # pragma: no cover - kräver Qt-tråd
        try:
            si = load_scan_module()
            result = parse_watched_file(
                si,
                self._path,
                self._folder_supplier,
                self._suppliers,
                self._templates,
                self._learning,
                extract_fn=self._extract_fn,
            )
        except BaseException as exc:  # noqa: BLE001 - rapporteras till tråden
            try:
                self._signals.failed.emit(
                    self._token, f"{type(exc).__name__}: {exc}"
                )
            except Exception:
                pass
            return
        try:
            self._signals.finished.emit(self._token, result)
        except Exception:
            pass


class WatchManager(QObject):
    """
    Bevakar mappar, tolkar nya filer och signalerar resultatet.

    Signaler:
      invoice_ready(parsed_row, källfil)  — komplett, kan skapas
      file_parked(info)                   — behöver granskning
      file_error(info)                    — originalläsfel, visa i Import
      file_recovered(path)                — tidigare läsfel löstes
      changed()                           — config/parkerade ändrats
    """

    invoice_ready = Signal(dict, str)
    file_parked = Signal(dict)
    file_error = Signal(dict)
    file_recovered = Signal(str)
    changed = Signal()
    scan_started = Signal()
    scan_finished = Signal(dict)

    def __init__(
        self,
        config_file: Path,
        app: Any = None,
        templates_provider: Callable[[], dict] | None = None,
        extract_fn: Callable[[Path], tuple[str, str]] | None = None,
        learning_provider: Callable[[], dict] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_file = Path(config_file)
        self._app = app
        self._templates_provider = templates_provider
        self._extract_fn = extract_fn
        self._learning_provider = learning_provider
        self._config: dict[str, Any] = self._load()
        self._warned_missing: set[str] = set()
        self._scan_stats: dict[str, int] = {
            "imported": 0, "duplicate": 0, "parked": 0, "already": 0,
            "waiting": 0, "settling": 0, "changed": 0, "errors": 0,
        }
        self._reported_file_errors: dict[str, tuple] = {}
        self._control_diffs: list[dict] = []
        self._waiting_reasons: dict[str, int] = {}
        self._last_logged_scan_summary: tuple | None = None
        self._last_logged_control_signature: tuple | None = None
        self._last_scan_at = ""
        self._stability_samples: dict[
            str, tuple[tuple[int, int, int], float]
        ] = {}
        self._stable_signatures: dict[str, tuple[int, int, int]] = {}
        self._watch_targets_by_root: dict[str, set[str]] = {}
        # Sökväg → (storlek, mtime, ctime, sha256). Gör att oförändrade
        # original inte behöver hashas om vid varje poll.
        self._hash_cache: OrderedDict[
            str, tuple[tuple[int, int, int], str]
        ] = OrderedDict()
        self._processed_path_keys: set[str] = set()
        # Bakgrundsskanningens tillstånd. Allt tungt arbete sker i en
        # arbetstråd; generatorn nedan håller bara bokföringen och
        # återupptas i GUI-tråden när en fil är färdigtolkad.
        self._scan_running = False
        self._scan_force = False
        self._scan_again = False
        self._scan_again_force = False
        self._scan_generator = None
        self._scan_folders: list[dict] = []
        self._scan_token = 0
        self._scan_pending_token = 0
        # Varje skanning har en egen epok. Redan köade
        # händelseloop-anrop från en avbruten/ersatt skanning ignoreras,
        # så två pumpar aldrig kan mata samma generator samtidigt.
        self._scan_epoch = 0
        self._scan_context: dict[str, Any] = {}
        self._last_scan_force = False
        self._analysis_signals = _AnalysisSignals(self)
        self._analysis_signals.finished.connect(self._on_scan_analysis)
        self._analysis_signals.failed.connect(
            self._on_scan_analysis_failed
        )
        log.info(
            "SCAN_WATCH: bevakning startad — %d mapp(ar): %s",
            len(self._config.get("folders", [])),
            ", ".join(
                f"{f.get('supplier') or '?'} → {f.get('path', '')}"
                for f in self._config.get("folders", [])
            ) or "inga",
        )

        from PySide6.QtCore import QFileSystemWatcher

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(
            lambda _p: self._debounce.start()
        )
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(1200)
        self._debounce.timeout.connect(self.start_scan)

        # Om en fil fortfarande växer görs en riktad snabb kontroll.
        # Vi blockerar aldrig GUI-tråden med sleep och behöver därför
        # inte invänta säkerhetspollningen på 30 sekunder.
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(FILE_STABILITY_RECHECK_MS)
        self._settle_timer.timeout.connect(self.start_scan)

        # Säkerhetspoll (nätverksdiskar missar ibland watcher-events)
        self._poll = QTimer(self)
        self._poll.setInterval(30_000)
        self._poll.timeout.connect(self.start_scan)
        self._poll.start()

        # Vakt: en fil som hänger i OCR får aldrig låsa appen för alltid.
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_scan_watchdog)

        self._rewatch()
        QTimer.singleShot(2000, self.start_scan)

    # ── Konfiguration ─────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(
                self._config_file.read_text(encoding="utf-8")
            )
            if isinstance(data, dict):
                data.setdefault("folders", [])
                data.setdefault("auto_create", True)
                data.setdefault("processed", {})
                data.setdefault("parked", [])
                return data
        except Exception as exc:
            # Saknad fil är normalt vid allra första körningen;
            # en OLIKLIG fil varnas däremot — den får aldrig
            # tyst nollställa bevakningen.
            if self._config_file.exists():
                log.warning(
                    "SCAN_WATCH: kunde inte läsa %s (%s) — "
                    "startar med tom bevakning",
                    self._config_file, exc,
                )
        return {
            "folders": [], "auto_create": True,
            "processed": {}, "parked": [],
        }

    def _save(self) -> None:
        try:
            # Skydd: en instans som aldrig satt mapparna själv
            # får inte skriva över mappar som finns på disk
            # (t.ex. tillagda i en annan vy/session) med en
            # tom lista. Uttrycklig borttagning via set_folders
            # sätter _folders_touched och gäller alltid.
            if (
                not self._config.get("folders")
                and not getattr(self, "_folders_touched", False)
                and self._config_file.exists()
            ):
                try:
                    disk = json.loads(
                        self._config_file.read_text(encoding="utf-8")
                    )
                    disk_folders = (
                        disk.get("folders", [])
                        if isinstance(disk, dict) else []
                    )
                    if disk_folders:
                        log.warning(
                            "SCAN_WATCH: behöll %d mapp(ar) från "
                            "disk i stället för att skriva över "
                            "med tom lista",
                            len(disk_folders),
                        )
                        self._config["folders"] = disk_folders
                except Exception:
                    pass
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._config_file.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._config, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            tmp.replace(self._config_file)
        except Exception as exc:
            log.warning("WatchManager._save: %s", exc)

    @property
    def folders(self) -> list[dict]:
        return list(self._config.get("folders", []))

    @property
    def auto_create(self) -> bool:
        return bool(self._config.get("auto_create", True))

    @property
    def parked(self) -> list[dict]:
        return list(self._config.get("parked", []))

    @property
    def processed(self) -> dict:
        return dict(self._config.get("processed", {}))

    def set_folders(self, folders: list[dict]) -> None:
        self._folders_touched = True
        self._config["folders"] = [
            {"supplier": str(f.get("supplier", "")),
             "path": str(f.get("path", ""))}
            for f in folders if str(f.get("path", "")).strip()
        ]
        self._save()
        self._rewatch()
        self.changed.emit()
        self.start_scan()

    def set_auto_create(self, enabled: bool) -> None:
        self._config["auto_create"] = bool(enabled)
        self._save()
        self.changed.emit()
        if enabled:
            # Filer som bara väntade på att auto-registreringen
            # skulle slås på prövas direkt — annars låg de kvar
            # i parkeringen i evighet trots att formatet läses.
            self.start_scan()

    def unprocess(self, file_hash_value: str) -> None:
        """Tar bort en fil ur bearbetade-registret så nästa
        skanning prövar den igen. Används när registreringen av en
        tolkad faktura misslyckades: filen får ALDRIG bli kvar som
        'importerad' utan att fakturan faktiskt finns i registret
        — då skulle den varken synas eller någonsin prövas om."""
        removed = self._config.get("processed", {}).pop(
            file_hash_value, None
        )
        if removed is not None:
            self._processed_path_keys.discard(
                _norm_path_key(str(removed.get("path", "")))
            )
            self._save()
            self.changed.emit()

    def archive_processed_file(
        self, raw_path: str | Path, invoice_date: str = "",
    ) -> str:
        """Move a successfully imported watched file into its invoice-year folder.

        The archive is ``<watched folder>/<YYYY>/``. Call only after a
        successful registration; incomplete/uncertain rows remain at their
        source path for review.
        """
        source = Path(str(raw_path or ""))
        if not source.is_file():
            return str(source)
        source_key = _norm_path_key(str(source))
        matching_root: Path | None = None
        for folder in self._config.get("folders", []):
            root = Path(str(folder.get("path", "") or ""))
            root_key = _norm_path_key(str(root))
            if not root_key:
                continue
            if source_key == root_key or source_key.startswith(root_key + "/"):
                if matching_root is None or len(root_key) > len(
                    _norm_path_key(str(matching_root))
                ):
                    matching_root = root
        if matching_root is None:
            return str(source)

        raw_date = str(invoice_date or "").strip()
        try:
            year = datetime.fromisoformat(raw_date[:10]).year
        except (TypeError, ValueError):
            log.warning(
                "SCAN_WATCH: invoice date missing/invalid for %s; "
                "year archive skipped until a fallback is supplied",
                source,
            )
            return str(source)
        if year < 1900 or year > 9999:
            log.warning(
                "SCAN_WATCH: invoice year out of range for %s; "
                "year archive skipped",
                source,
            )
            return str(source)

        archive_dir = matching_root / f"{year:04d}"
        try:
            if source.parent.resolve() == archive_dir.resolve():
                return str(source)
            archive_dir.mkdir(parents=True, exist_ok=True)
            target = archive_dir / source.name
            if target.exists():
                stem, suffix = source.stem, source.suffix
                number = 2
                while target.exists():
                    target = archive_dir / f"{stem} ({number}){suffix}"
                    number += 1
            os.replace(str(source), str(target))
        except Exception as exc:
            log.warning(
                "SCAN_WATCH: kunde inte årsarkivera %s: %s; originalet "
                "lämnas på ursprunglig plats",
                source, exc,
            )
            return str(source)

        old_key = _norm_path_key(str(source))
        new_path = str(target)
        new_key = _norm_path_key(new_path)
        for info in self._config.get("processed", {}).values():
            if _norm_path_key(str(info.get("path", ""))) == old_key:
                info["path"] = new_path
                info["file"] = target.name
        for parked in self._config.get("parked", []):
            if _norm_path_key(str(parked.get("path", ""))) == old_key:
                parked["path"] = new_path
                parked["file"] = target.name
        self._refresh_processed_paths()
        self._save()
        self.changed.emit()
        log.info(
            "SCAN_WATCH: original årsarkiverat %s → %s", source, target
        )
        return new_path

    def _archive_existing_registered_original(
        self, path: Path, parsed: dict,
    ) -> str:
        """Back-sort only an exact registered attachment, never a duplicate copy."""
        source_key = _norm_path_key(str(path))
        supplier = str(parsed.get("supplier", "") or "").strip().casefold()
        number = str(parsed.get("invoice_number", "") or "").strip().casefold()
        if not supplier or not number:
            return str(path)
        for invoice in self._invoices():
            if (
                str(invoice.get("supplier", "") or "").strip().casefold()
                != supplier
                or str(invoice.get("invoice_number", "") or "")
                .strip().casefold() != number
                or _norm_path_key(str(invoice.get("attachment", "") or ""))
                != source_key
            ):
                continue
            update_fn = getattr(self._app, "update_invoice", None)
            invoice_id = str(invoice.get("id", "") or "")
            if not callable(update_fn) or not invoice_id:
                return str(path)
            archive_date = str(invoice.get("date", "") or "").strip()
            try:
                parsed_date = datetime.fromisoformat(archive_date[:10])
                if not 1900 <= parsed_date.year <= 9999:
                    raise ValueError("invoice year out of archive range")
            except (TypeError, ValueError):
                archive_date = ""
                try:
                    try:
                        default_year = datetime.fromtimestamp(
                            path.stat().st_mtime
                        ).year
                    except (OSError, OverflowError, ValueError):
                        default_year = datetime.now().year
                    parent = self.parent()
                    if not isinstance(parent, QWidget):
                        parent = None
                    year, accepted = QInputDialog.getInt(
                        parent,
                        tr("watch.archive_year_title"),
                        tr("watch.archive_year_prompt"),
                        default_year,
                        1900,
                        9999,
                        1,
                    )
                    if accepted and 1900 <= int(year) <= 9999:
                        archive_date = f"{int(year):04d}-01-01"
                except Exception as prompt_exc:
                    log.warning(
                        "SCAN_WATCH: could not ask for an archive year "
                        "for %s: %s", path, prompt_exc,
                    )
            archived = self.archive_processed_file(path, archive_date)
            if _norm_path_key(archived) == source_key:
                return str(path)
            try:
                updated = update_fn(invoice_id, {"attachment": archived})
                if not updated:
                    refreshed = next(
                        (
                            item for item in self._invoices()
                            if str(item.get("id", "") or "") == invoice_id
                        ),
                        None,
                    )
                    if (
                        refreshed is None
                        or _norm_path_key(str(
                            refreshed.get("attachment", "") or ""
                        )) != _norm_path_key(archived)
                    ):
                        raise RuntimeError(
                            "invoice attachment path was not persisted"
                        )
                invoice["attachment"] = archived
                log.info(
                    "SCAN_WATCH: already-registered original sorted "
                    "%s → %s", path, archived,
                )
                return archived
            except Exception as exc:
                self.restore_archived_file(archived, path)
                log.error(
                    "SCAN_WATCH: registry path update failed after archive "
                    "%s → %s: %s", path, archived, exc,
                )
                return str(path)
        return str(path)

    def restore_archived_file(
        self, archived_path: str | Path, source_path: str | Path,
    ) -> None:
        """Restore a moved file if its registered attachment path fails to persist."""
        archived = Path(str(archived_path or ""))
        source = Path(str(source_path or ""))
        if not archived.is_file() or source.exists():
            return
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(archived), str(source))
        except Exception as exc:
            log.error(
                "SCAN_WATCH: rollback av årsarkiv misslyckades %s → %s: %s",
                archived, source, exc,
            )
            return
        old_key = _norm_path_key(str(archived))
        for info in self._config.get("processed", {}).values():
            if _norm_path_key(str(info.get("path", ""))) == old_key:
                info["path"] = str(source)
                info["file"] = source.name
        for parked in self._config.get("parked", []):
            if _norm_path_key(str(parked.get("path", ""))) == old_key:
                parked["path"] = str(source)
                parked["file"] = source.name
        self._refresh_processed_paths()
        self._save()
        self.changed.emit()

    def remove_parked(self, file_hash_value: str) -> None:
        self._config["parked"] = [
            p for p in self._config.get("parked", [])
            if p.get("hash") != file_hash_value
        ]
        self._save()
        self.changed.emit()

    def _rewatch(self) -> None:
        """Bevaka rotmappar och befintliga undermappar.

        Nya undermappar kopplas in efter nästa skanning. QFileSystemWatcher
        kan ha operativsystemsgränser eller saknas på nätverksdiskar; den
        återkommande rekursiva pollningen är därför alltid reservvägen.
        """
        current = set(self._watcher.directories())
        targets_by_root: dict[str, set[str]] = {}
        wanted: set[str] = set()
        for entry in self.folders:
            root = Path(str(entry.get("path", "")))
            root_key = _norm_path_key(str(root))
            targets: set[str] = set()
            if root.is_dir():
                for dirpath, dirs, _names in os.walk(root):
                    dirs[:] = [d for d in dirs if d.lower() != "arkiv"]
                    targets.add(str(Path(dirpath)))
                wanted.update(targets)
            targets_by_root[root_key] = targets

        for gone in current - wanted:
            self._watcher.removePath(gone)
        # Lägg till föräldrar först, så en systemgräns aldrig lämnar roten
        # obeakad till förmån för ett stort antal djupa undermappar.
        for new in sorted(
            wanted - current,
            key=lambda path: (path.count(os.sep), path.casefold()),
        ):
            if not self._watcher.addPath(new):
                log.debug(
                    "SCAN_WATCH: katalogbevakning misslyckades för %s; "
                    "säkerhetspollningen täcker katalogen ändå",
                    new,
                )
        self._watch_targets_by_root = targets_by_root

    # ── Tolkning ──────────────────────────────────────────────────────

    def _scan_module(self):
        return load_scan_module()

    def _resolve_register_supplier(self, wanted: str) -> str:
        """Slår upp mappens leverantörsnamn mot registret tolerant."""
        return resolve_supplier_in(self._suppliers(), wanted)

    def _suppliers(self) -> list[dict]:
        try:
            return list(self._app.get_suppliers()) if self._app else []
        except Exception:
            return []

    def _invoices(self) -> list[dict]:
        try:
            return list(self._app.get_invoices()) if self._app else []
        except Exception:
            return []

    def status_lines(self) -> list[str]:
        """Diagnosrader till felsökningspaketet (Logg-fliken):
        varför filer i bevakade mappar inte lästs in."""
        templates: dict = {}
        if self._templates_provider is not None:
            try:
                templates = self._templates_provider() or {}
            except Exception:
                templates = {}
        return watch_diagnostic_lines(
            self._config,
            self.last_scan_stats,
            suppliers=self._suppliers(),
            templates=templates,
        )

    @property
    def last_scan_stats(self) -> dict[str, int]:
        """Utfall av senaste skanning, inklusive filer som väntar på
        att skrivningen ska bli klar. Läsfel lämnar originalen orörda."""
        return dict(self._scan_stats)

    @property
    def last_scan_at(self) -> str:
        """Lokal tid för när den senaste kontrollomgången avslutades."""
        return self._last_scan_at

    @property
    def active_error_count(self) -> int:
        """Antal felvägar som ännu inte har lästs in korrekt."""
        return len(self._reported_file_errors)

    @property
    def folder_watch_statuses(self) -> list[dict[str, Any]]:
        """Status per rotmapp, inklusive rekursiva watcher-kataloger.

        Säkerhetspollningen skannar alltid hela trädet även om ett
        operativsystem eller en nätverksdisk inte kan bevaka varje katalog.
        """
        current = {
            _norm_path_key(path) for path in self._watcher.directories()
        }
        statuses = []
        for entry in self.folders:
            root = Path(str(entry.get("path", "")))
            key = _norm_path_key(str(root))
            targets = self._watch_targets_by_root.get(key, set())
            watched = len({
                _norm_path_key(path) for path in targets
            } & current)
            statuses.append({
                "path": str(root),
                "exists": root.is_dir(),
                "directories": len(targets),
                "watched": watched,
                "fallback": max(0, len(targets) - watched),
            })
        return statuses

    @property
    def last_control_diffs(self) -> list[dict]:
        """Avvikelser från senaste kontrollskanningen: en post per
        redan inläst faktura vars original tolkningen nu läser
        annorlunda ({file, invoice_id, invoice_number, changes}).
        Registrerade data ändrades inte — bara rapporten."""
        return [dict(d) for d in self._control_diffs]

    # ── Hash-cache ─────────────────────────────────────────────────────

    def _cached_digest(
        self, path: Path, signature: tuple[int, int, int]
    ) -> str | None:
        """Tidigare beräknad sha256 för exakt samma filversion."""
        key = _norm_path_key(str(path))
        cached = self._hash_cache.get(key)
        if cached is None or cached[0] != signature:
            return None
        self._hash_cache.move_to_end(key)
        return cached[1]

    def _remember_digest(
        self,
        path: Path,
        signature: tuple[int, int, int],
        digest: str,
    ) -> None:
        if not digest:
            return
        key = _norm_path_key(str(path))
        self._hash_cache[key] = (signature, digest)
        self._hash_cache.move_to_end(key)
        while len(self._hash_cache) > HASH_CACHE_MAX:
            self._hash_cache.popitem(last=False)

    def _file_digest(self, path: Path) -> str:
        """sha256 med cache: oförändrade filer hashas bara en gång."""
        try:
            stat = Path(path).stat()
        except OSError:
            return ""
        signature = (
            int(stat.st_size),
            int(stat.st_mtime_ns),
            int(stat.st_ctime_ns),
        )
        digest = self._cached_digest(Path(path), signature)
        if digest:
            return digest
        try:
            digest = file_hash(Path(path))
        except Exception:
            return ""
        self._remember_digest(Path(path), signature, digest)
        return digest

    # ── Skanningsmotor ─────────────────────────────────────────────────

    def _refresh_processed_paths(self) -> None:
        self._processed_path_keys = {
            _norm_path_key(str(info.get("path", "")))
            for info in self._config.get("processed", {}).values()
            if info.get("path")
        }

    def _reset_scan_stats(self) -> None:
        self._refresh_processed_paths()
        self._scan_stats = {
            "imported": 0, "duplicate": 0, "parked": 0, "already": 0,
            "waiting": 0, "settling": 0, "changed": 0, "errors": 0,
        }
        self._waiting_reasons = {}
        self._control_diffs = []

    @property
    def is_scanning(self) -> bool:
        """True medan en bakgrundsskanning pågår."""
        return bool(self._scan_running)

    @property
    def last_scan_force(self) -> bool:
        """Utfördes den senaste skanningen som kontrollskanning?"""
        return bool(self._last_scan_force)

    def scan_all(self, force: bool = False) -> None:
        """Skanning som körs färdigt direkt i anropande tråd.

        Används av tester och av interna flöden som måste ha resultatet
        innan de går vidare. Den återkommande bevakningen använder
        i stället start_scan(), som aldrig blockerar GUI-tråden.
        """
        self._abort_async_scan()
        self._reset_scan_stats()
        self._last_scan_force = bool(force)
        self._heal_missing_imports()
        for entry in self.folders:
            try:
                self.scan_folder(entry, force=force)
            except Exception as exc:
                self._record_scan_error(
                    str(entry.get("path", "?")), "folder", "", exc
                )
        self._complete_scan(announce=True)

    def start_scan(self, force: bool = False) -> None:
        """Startar en skanning som inte låser appen.

        Tolkningen av varje fil (PDF-läsning, OCR, mallmatchning) körs i
        en arbetstråd. GUI-tråden sköter bokföringen en fil i taget och
        hinner därför rita om fönstret och svara på klick under hela
        skanningen. En begäran som kommer medan en skanning pågår slås
        ihop med den pågående i stället för att starta en till.
        """
        if self._scan_running:
            self._scan_again = True
            self._scan_again_force = self._scan_again_force or bool(force)
            log.debug(
                "SCAN_WATCH: skanning pågår — ny begäran köas (force=%s)",
                bool(force),
            )
            return
        self._reset_scan_stats()
        self._scan_running = True
        self._scan_force = bool(force)
        self._last_scan_force = bool(force)
        self._scan_again = False
        self._scan_again_force = False
        self._scan_generator = None
        self._scan_token += 1
        self._scan_pending_token = 0
        self._scan_folders = list(self.folders)
        self._scan_context = self._scan_context_snapshot()
        try:
            self._heal_missing_imports()
        except Exception as exc:
            log.warning("SCAN_WATCH självläkning: %s", exc)
        self.scan_started.emit()
        epoch = self._scan_epoch
        QTimer.singleShot(
            0, lambda: self._drive_scan(None, epoch=epoch)
        )

    def _scan_context_snapshot(self) -> dict[str, Any]:
        """Kopior som arbetstråden får läsa — aldrig appens live-objekt."""
        suppliers: list[dict] = []
        templates: dict = {}
        learning: dict = {}
        try:
            suppliers = [dict(s) for s in self._suppliers()]
        except Exception:
            suppliers = []
        if self._templates_provider is not None:
            try:
                templates = dict(self._templates_provider() or {})
            except Exception:
                templates = {}
        if self._learning_provider is not None:
            try:
                learning = dict(self._learning_provider() or {})
            except Exception:
                learning = {}
        return {
            "suppliers": suppliers,
            "templates": templates,
            "learning": learning,
            # Endast test-/integrationskrok; normalt None och då görs
            # den riktiga PDF-/OCR-extraktionen i arbetstråden.
            "extract_fn": self._extract_fn,
        }

    def _abort_async_scan(self) -> None:
        """Avbryter en pågående bakgrundsskanning (t.ex. före scan_all)."""
        try:
            self._watchdog.stop()
        except Exception:
            pass
        self._scan_running = False
        self._scan_again = False
        self._scan_again_force = False
        self._scan_pending_token = 0
        self._scan_generator = None
        self._scan_folders = []
        self._scan_epoch += 1

    def _drive_scan(
        self,
        send_value: Any,
        throw_exc: Exception | None = None,
        epoch: int | None = None,
    ) -> None:
        """Mata skanningsgeneratorn tills nästa fil behöver tolkning."""
        if not self._scan_running:
            return
        if epoch is not None and epoch != self._scan_epoch:
            return
        deadline = time.monotonic() + SCAN_SLICE_SECONDS
        while True:
            if self._scan_generator is None:
                if not self._scan_folders:
                    self._finish_scan()
                    return
                entry = self._scan_folders.pop(0)
                self._scan_generator = self._iter_scan_folder(
                    entry, force=self._scan_force
                )
                send_value, throw_exc = None, None
            try:
                if throw_exc is not None:
                    request = self._scan_generator.throw(throw_exc)
                else:
                    request = self._scan_generator.send(send_value)
            except StopIteration:
                self._scan_generator = None
                send_value, throw_exc = None, None
                continue
            except Exception:
                log.error(
                    "SCAN_WATCH: skanningen avbröts för en mapp",
                    exc_info=True,
                )
                self._scan_generator = None
                send_value, throw_exc = None, None
                continue
            send_value, throw_exc = None, None
            kind = request.get("kind") if isinstance(request, dict) else ""
            if kind == "analyze":
                self._submit_analysis(request)
                return
            # "pause": lämna tillbaka till händelseloopen så att
            # fönstret hinner rita om och ta emot klick.
            if kind == "pause":
                epoch = self._scan_epoch
                QTimer.singleShot(
                    0, lambda: self._drive_scan(None, epoch=epoch)
                )
                return
            if time.monotonic() >= deadline:
                epoch = self._scan_epoch
                QTimer.singleShot(
                    0, lambda: self._drive_scan(None, epoch=epoch)
                )
                return

    def _submit_analysis(self, request: dict) -> None:
        """Skicka EN fil till tolkningsarbetaren."""
        self._scan_token += 1
        token = self._scan_token
        self._scan_pending_token = token
        context = self._scan_context or {}
        entry = request.get("entry") or {}
        task = _AnalyzeFileTask(
            token,
            Path(str(request.get("path", ""))),
            str(entry.get("supplier", "") or ""),
            list(context.get("suppliers") or []),
            dict(context.get("templates") or {}),
            dict(context.get("learning") or {}),
            self._analysis_signals,
            extract_fn=context.get("extract_fn"),
        )
        self._arm_scan_watchdog()
        try:
            QThreadPool.globalInstance().start(task)
        except Exception as exc:
            log.warning("SCAN_WATCH: kunde inte starta tolkning: %s", exc)
            self._scan_pending_token = 0
            self._watchdog.stop()
            QTimer.singleShot(
                0,
                lambda: self._drive_scan(
                    None,
                    RuntimeError(f"tolkningen kunde inte startas: {exc}"),
                ),
            )

    def _on_scan_analysis(self, token: int, result: object) -> None:
        if not self._scan_running or token != self._scan_pending_token:
            return
        self._scan_pending_token = 0
        self._watchdog.stop()
        self._drive_scan(result)

    def _on_scan_analysis_failed(self, token: int, message: str) -> None:
        if not self._scan_running or token != self._scan_pending_token:
            return
        self._scan_pending_token = 0
        self._watchdog.stop()
        self._drive_scan(None, RuntimeError(str(message or "okänt fel")))

    def _arm_scan_watchdog(self) -> None:
        if self._scan_pending_token:
            self._watchdog.start(ANALYSIS_TIMEOUT_MS)

    def _on_scan_watchdog(self) -> None:
        """En tolkning har hängt — avbryt hellre än att låsa appen."""
        if not self._scan_running:
            return
        log.error(
            "SCAN_WATCH: en fil tog mer än %d sekunder att tolka — "
            "skanningen avbryts och filen prövas nästa gång",
            ANALYSIS_TIMEOUT_MS // 1000,
        )
        self._scan_pending_token = 0
        self._scan_token += 1
        self._scan_stats["errors"] = self._scan_stats.get("errors", 0) + 1
        if self._scan_generator is not None:
            try:
                self._scan_generator.close()
            except Exception:
                pass
        self._scan_generator = None
        self._scan_folders = []
        self._finish_scan()

    def _finish_scan(self) -> None:
        self._watchdog.stop()
        again = bool(self._scan_again)
        again_force = bool(self._scan_again_force)
        self._scan_running = False
        self._scan_generator = None
        self._scan_folders = []
        self._scan_again = False
        self._scan_again_force = False
        self._complete_scan(announce=True)
        if again:
            self.start_scan(force=again_force)

    def _complete_scan(self, announce: bool = True) -> None:
        """Loggar sammanfattningen och meddelar vyn att skanningen är klar."""
        # Sammanfattningen loggas bara när själva utfallet ändras.
        # "already" räknas om vid varje 30-sekunderspoll och får inte
        # i sig göra att samma statusrad fylls på om och om igen.
        waiting = self._scan_stats.get("waiting", 0)
        reason_signature = tuple(sorted(
            (str(k), int(v)) for k, v in self._waiting_reasons.items()
        ))
        summary = (
            self._scan_stats["imported"],
            self._scan_stats["duplicate"],
            self._scan_stats["parked"],
            self._scan_stats["already"],
            waiting,
            self._scan_stats.get("settling", 0),
            self._scan_stats.get("errors", 0),
            reason_signature,
            bool(self.auto_create),
        )
        if summary != self._last_logged_scan_summary:
            self._last_logged_scan_summary = summary
            reason_txt = ""
            if self._waiting_reasons:
                reason_txt = " (" + ", ".join(
                    f"{_park_reason_sv(k)} ×{n}"
                    for k, n in sorted(self._waiting_reasons.items())
                ) + ")"
            log.info(
                "SCAN_WATCH skanning: %d nya registrerade, %d "
                "dubblett(er) (fanns redan i registret), %d "
                "parkerade, %d redan bearbetade sedan tidigare, "
                "%d väntar i parkering, %d filer väntar på skrivslut, "
                "%d läsfel%s",
                self._scan_stats["imported"],
                self._scan_stats["duplicate"],
                self._scan_stats["parked"],
                self._scan_stats["already"],
                waiting,
                self._scan_stats.get("settling", 0),
                self._scan_stats.get("errors", 0),
                reason_txt,
            )
            if (
                self._waiting_reasons.get("review")
                and not self.auto_create
            ):
                log.info(
                    "SCAN_WATCH: auto-registrering är AV — %d "
                    "fil(er) ligger i parkering tills den slås "
                    "på i Import-fliken (Bevakade mappar)",
                    self._waiting_reasons["review"],
                )
        changed = self._scan_stats.get("changed", 0)
        if changed:
            control_signature = tuple(
                (
                    str(diff.get("file", "")),
                    str(diff.get("invoice_number", "")),
                    json.dumps(
                        diff.get("changes", {}),
                        ensure_ascii=False, sort_keys=True, default=str,
                    ),
                )
                for diff in self._control_diffs
            )
            if control_signature != self._last_logged_control_signature:
                log.warning(
                    "SCAN_WATCH kontroll: %d redan inläst(a) faktura/"
                    "fakturor avviker mot nytolkningen av "
                    "originalen — inget ändrades automatiskt; "
                    "rätta per faktura i Fakturor-fliken "
                    "(högerklicka → Skanna om faktura)",
                    changed,
                )
            self._last_logged_control_signature = control_signature
        else:
            self._last_logged_control_signature = None
        self._last_scan_at = datetime.now().astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        try:
            # En nyskapad undermapp får en QFileSystemWatcher när
            # efterföljande rekursiv skanning har upptäckt den. Pollningen
            # täcker fortfarande hela trädet om katalogbevakning saknas.
            self._rewatch()
        except Exception as exc:
            log.debug(
                "SCAN_WATCH: kunde inte uppdatera katalogbevakning: %s",
                exc,
            )
        # Uppdatera senast kontrollerad tid och fel-/väntestatus även när
        # skanningen inte hittade någon ny faktura.
        self.changed.emit()
        if announce:
            self.scan_finished.emit(dict(self._scan_stats))

    def _record_scan_error(
        self, path: str, stage: str, digest: str, exc: Exception,
    ) -> None:
        """Räkna fel per fil och logga traceback en gång per feltyp/hash."""
        key = str(path or "?")
        signature = (
            str(stage), str(digest or ""), type(exc).__name__, str(exc)
        )
        self._scan_stats["errors"] = self._scan_stats.get("errors", 0) + 1
        if stage in {"hasha", "läsa/tolka", "kontrolläsa"}:
            try:
                source = Path(key)
                detail = str(exc)
                parsed = {
                    "file": source.name or key,
                    "supplier": "", "invoice_number": "",
                    "date": "", "due_date": "", "ocr": "",
                    "total_amount": 0.0,
                    "missing": [
                        "belopp", "fakturanummer", "leverantör",
                    ],
                    "status": "scan_error",
                    "method": f"läsfel ({stage})",
                    "_path": key, "_text": "",
                    "_scan_error": True,
                    "error_detail": detail,
                }
                self.file_error.emit({
                    "hash": str(digest or ""), "path": key,
                    "file": source.name or key,
                    "reason": "read-error", "stage": str(stage),
                    "error": detail, "method": parsed["method"],
                    "parsed": parsed,
                })
            except Exception as emit_exc:
                log.debug(
                    "SCAN_WATCH: kunde inte visa fellrad %s: %s",
                    key, emit_exc,
                )
        if self._reported_file_errors.get(key) == signature:
            return
        self._reported_file_errors[key] = signature
        log.error(
            "SCAN_WATCH: kunde inte %s originalfil %s (hash=%s): %s",
            stage, key, digest or "—", exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    def _heal_missing_imports(self) -> None:
        """Självläkning: filer som står som importerade i
        bearbetade-registret men saknar faktura i registret prövas
        igen. Äldre versioner markerade filen som importerad innan
        sparandet bekräftats — misslyckades det fanns varken
        faktura eller omprövning. Nu rättas det vid nästa
        skanning i stället för att fakturan är borta för alltid.

        En fil anses höra till en registerfaktura om NÅGOT av:
        sökvägen (normaliserad) = fakturans original, filens hash
        = originalets hash (samma fil under annat namn), eller
        samma leverantör (efter mappens koppling) + fakturanummer.
        Kastar aldrig: ett läkningsfel får inte stoppa skanningen."""
        try:
            invoices = self._invoices()
            known_paths: set[str] = set()
            known_numbers: set[tuple[str, str]] = set()
            attachment_paths: list[str] = []
            for inv in invoices:
                sup_l = str(
                    inv.get("supplier", "") or ""
                ).strip().lower()
                nr_l = str(
                    inv.get("invoice_number", "") or ""
                ).strip().lower()
                if sup_l and nr_l:
                    known_numbers.add((sup_l, nr_l))
                att = str(inv.get("attachment", "") or "")
                if att:
                    known_paths.add(_norm_path_key(att))
                    attachment_paths.append(att)
            folder_supplier: dict[str, str] = {}
            for f in self._config.get("folders", []) or []:
                sup = self._resolve_register_supplier(
                    str(f.get("supplier", "") or "")
                )
                folder_supplier[
                    _norm_path_key(str(f.get("path", "") or ""))
                ] = str(sup or "").strip().lower()

            def _supplier_of(fpath: str) -> str:
                key = _norm_path_key(fpath)
                return next(
                    (
                        sup_name
                        for fkey, sup_name in folder_supplier.items()
                        if fkey and key.startswith(fkey)
                    ),
                    "",
                )

            # Steg 1: hitta de få poster som alls kan behöva självläkas.
            # Att hasha alla registrerade original vid varje poll var
            # dyrt (tusentals filer) och gav appen frysningar. Hasharna
            # beräknas nu bara om någon post faktiskt saknar en
            # sökvägs-/nummerkoppling.
            pending: list[tuple[str, dict, str, str]] = []
            for digest, info in list(
                self._config.get("processed", {}).items()
            ):
                if info.get("result") != "imported":
                    continue
                fpath = str(info.get("path", "") or "")
                if not fpath or not Path(fpath).is_file():
                    continue
                if _norm_path_key(fpath) in known_paths:
                    continue
                nr = str(
                    info.get("invoice_number", "") or ""
                ).strip().lower()
                if nr and (_supplier_of(fpath), nr) in known_numbers:
                    continue
                pending.append((digest, info, fpath, nr))
            known_hashes: set[str] = set()
            if pending:
                known_hashes = {
                    digest
                    for digest in (
                        self._file_digest(Path(att))
                        for att in attachment_paths
                    )
                    if digest
                }

            healed = 0
            for digest, info, fpath, nr in pending:
                if digest in known_hashes:
                    continue
                if nr and (_supplier_of(fpath), nr) in known_numbers:
                    continue
                log.warning(
                    "SCAN_WATCH: %s står som importerad men "
                    "fakturan saknas i registret — prövar "
                    "registreringen igen",
                    info.get("file", fpath),
                )
                self.unprocess(digest)
                healed += 1
            if healed:
                log.warning(
                    "SCAN_WATCH: %d fil(er) omprövas efter "
                    "tidigare missad registrering", healed,
                )
        except Exception as exc:
            log.warning("SCAN_WATCH självläkning: %s", exc)

    def _should_retry_parked(self, parked_entry: dict,
                             digest: str) -> bool:
        """Ska en parkerad fil prövas igen av en VANLIG skanning?

        Filer som importerats för tolkning (mall saknas eller
        uppgifter saknas) skannas ALDRIG om automatiskt — de är
        redan inlästa för granskning och ska ligga still tills
        användaren sparar en mall; DÅ läses de om explicit via
        reprocess_parked(). Enda undantaget: filer som parkerades
        enbart för att auto-registreringen var avstängd ("review")
        prövas igen så fort den slås på — det är ett medvetet
        användarval, inte en omskanning.
        """
        reason = str(parked_entry.get("reason", ""))
        if reason == "review":
            return self.auto_create
        return False

    def reprocess_parked(
        self, entry: dict | None = None, background: bool = False,
    ) -> int:
        """Läser OM parkerade tolkningsfiler med dagens mallar.

        Det här är tillfället då filer som parkerats för tolkning
        (orsak "no-template" eller "missing: …") tolkas på nytt —
        anropas när användaren sparat en mall eller matchat en
        faktura manuellt, så leverantörens övriga väntande
        fakturor prövas mot det appen just lärt sig. Med
        `entry` bara den mappens filer, annars alla bevakade
        mappar. Returnerar antalet filer som lästes om.

        ``background=True`` lägger skanningen i bakgrunden
        (``start_scan``) i stället för att läsa färdigt i
        anropande tråd — GUI:t får aldrig vänta på tolkningen.
        Bakgrundsläget går genom alla bevakade mappar, eftersom det
        är samma bakgrundsskanning som bevakningen använder.
        """
        folder_key = ""
        if entry is not None:
            folder_key = _norm_path_key(str(entry.get("path", "")))
        targets: list[dict] = []
        for parked in list(self._config.get("parked", [])):
            reason = str(parked.get("reason", "") or "")
            if not (
                reason == "no-template"
                or reason == "uncertain-supplier"
                or reason == "ocr-warning"
                or reason == "payment-details"
                or reason.startswith("missing")
            ):
                continue
            if folder_key:
                pkey = _norm_path_key(str(parked.get("path", "")))
                if pkey != folder_key and not pkey.startswith(
                    folder_key + "/"
                ):
                    continue
            targets.append(parked)
        for parked in targets:
            self._config["parked"].remove(parked)
        if targets:
            self._save()
            log.info(
                "SCAN_WATCH: läser om %d parkerade filer med "
                "dagens mallar%s", len(targets),
                " (i bakgrunden)" if background else "",
            )
        if background:
            # Aldrig blockera GUI-tråden: samma bakgrundsskanning
            # som den återkommande bevakningen använder.
            self.start_scan()
        elif entry is not None:
            self.scan_folder(entry)
        else:
            self.scan_all()
        return len(targets)

    def _schedule_stability_check(self) -> None:
        if not self._settle_timer.isActive():
            self._settle_timer.start(FILE_STABILITY_RECHECK_MS)

    def _file_is_stable(
        self, path: Path, signature: tuple[int, int, int],
        known: bool = False,
    ) -> bool:
        """Require an unchanged size/time signature over a quiet interval.

        Samples are cached after a successful stability check, so regular
        polls do not add a delay to files already known to be unchanged.
        A changed signature invalidates that cache and starts a fresh wait.

        ``known`` betyder att exakt den här filversionen redan har hashats
        (finns i hash-cachen) — då är den per definition färdigskriven och
        behöver varken väntetid eller ny kontroll.
        """
        key = _norm_path_key(str(path))
        if known or self._stable_signatures.get(key) == signature:
            self._stability_samples.pop(key, None)
            self._stable_signatures[key] = signature
            return True
        if FILE_STABILITY_SECONDS <= 0:
            self._stability_samples.pop(key, None)
            self._stable_signatures[key] = signature
            return True

        now = time.monotonic()
        previous = self._stability_samples.get(key)
        if previous and previous[0] == signature:
            if now - previous[1] >= FILE_STABILITY_SECONDS:
                self._stability_samples.pop(key, None)
                self._stable_signatures[key] = signature
                return True
        else:
            self._stability_samples[key] = (signature, now)

        self._scan_stats["settling"] = (
            self._scan_stats.get("settling", 0) + 1
        )
        self._schedule_stability_check()
        return False

    def scan_folder(self, entry: dict, force: bool = False) -> None:
        """Skanning av EN mapp, färdig innan anropet returnerar.

        Driver samma stegvisa skanning som bakgrundsläget, men tolkar
        filerna direkt i den här tråden. Används av scan_all(),
        reprocess_parked() och tester; den återkommande bevakningen
        använder start_scan() som aldrig blockerar GUI-tråden.
        """
        generator = self._iter_scan_folder(entry, force=force)
        si = None
        try:
            request = next(generator)
            while True:
                if (
                    isinstance(request, dict)
                    and request.get("kind") == "analyze"
                ):
                    if si is None:
                        si = self._scan_module()
                    try:
                        result = self._parse_file(
                            si, entry, Path(str(request.get("path", "")))
                        )
                    except Exception as exc:
                        request = generator.throw(exc)
                    else:
                        request = generator.send(result)
                else:
                    request = next(generator)
        except StopIteration:
            return

    def _iter_scan_folder(self, entry: dict, force: bool = False):
        """Stegvis skanning av en mapp.

        Yieldar ``{"kind": "analyze", ...}`` när en fil behöver tolkas
        (tung OCR/textutdrag) och tar emot ``(text, metod, tolkning)``
        via ``send()``. ``{"kind": "pause"}`` ger GUI-tråden en chans att
        rita om mellan filerna. All bokföring — stabilitet, hash-cache,
        parkering, statistik — sker i den här generatorn.
        """
        folder = Path(str(entry.get("path", "")))
        if not folder.is_dir():
            key = str(folder)
            if key not in self._warned_missing:
                self._warned_missing.add(key)
                log.warning(
                    "SCAN_WATCH: bevakad mapp saknas — %s "
                    "(leverantör %s) hoppas över",
                    folder, entry.get("supplier", "?"),
                )
            return
        seen = 0
        last_pause = time.monotonic()
        for path in iter_invoice_files(folder):
            seen += 1
            if seen % 20 == 0 or time.monotonic() - last_pause > 0.02:
                last_pause = time.monotonic()
                yield {"kind": "pause"}
            try:
                before = path.stat()
            except FileNotFoundError:
                # En fil kan försvinna mellan os.walk och stat.
                continue
            except OSError as exc:
                self._record_scan_error(str(path), "hasha", "", exc)
                continue
            signature = (
                int(before.st_size),
                int(before.st_mtime_ns),
                int(before.st_ctime_ns),
            )
            path_key = _norm_path_key(str(path))
            # Redan hashad version → ingen väntan på skrivslut och ingen
            # omhashning. Det här är vad som gör pollningen billig även
            # med tusentals redan inlästa original.
            digest = self._cached_digest(path, signature)
            # Redan registrerade original behöver ingen väntan på
            # skrivslut — de ska bara hashas (ur cachen när de är
            # oförändrade) och räknas som redan bearbetade.
            if not self._file_is_stable(
                path,
                signature,
                known=(
                    digest is not None
                    or path_key in self._processed_path_keys
                ),
            ):
                continue
            if digest is None:
                try:
                    digest = file_hash(path)
                    after = path.stat()
                except FileNotFoundError:
                    self._stable_signatures.pop(path_key, None)
                    continue
                except Exception as exc:
                    self._record_scan_error(str(path), "hasha", "", exc)
                    continue
                after_signature = (
                    int(after.st_size),
                    int(after.st_mtime_ns),
                    int(after.st_ctime_ns),
                )
                if after_signature != signature:
                    # Filen började ändras medan hashen lästes. Kasta
                    # resultatet och starta om stabilitetsfönstret.
                    self._stable_signatures.pop(path_key, None)
                    self._stability_samples[path_key] = (
                        after_signature, time.monotonic()
                    )
                    self._scan_stats["settling"] = (
                        self._scan_stats.get("settling", 0) + 1
                    )
                    self._schedule_stability_check()
                    continue
                self._remember_digest(path, signature, digest)

            if digest in self._config["processed"]:
                if force:
                    info = (
                        self._config["processed"].get(digest) or {}
                    )
                    inv = self._find_invoice_for_file(
                        entry, path, digest, info
                    )
                    if inv is None:
                        log.info(
                            "SCAN_WATCH kontroll: %s är bearbetad men "
                            "fakturan saknas i registret — läses in "
                            "på nytt",
                            path.name,
                        )
                        self.unprocess(digest)
                    else:
                        try:
                            text, method, parsed = yield {
                                "kind": "analyze",
                                "path": str(path),
                                "entry": entry,
                                "stage": "kontrolläsa",
                            }
                        except Exception as exc:
                            self._record_scan_error(
                                str(path), "kontrolläsa", digest, exc
                            )
                            continue
                        self._control_check_parsed(inv, path, digest, parsed)
                        continue
                else:
                    self._reported_file_errors.pop(str(path), None)
                    self.file_recovered.emit(str(path))
                    self._scan_stats["already"] += 1
                    continue
            parked_entry = next(
                (
                    p for p in self._config.get("parked", [])
                    if p.get("hash") == digest
                ),
                None,
            )
            if parked_entry is not None:
                if not self._should_retry_parked(parked_entry, digest):
                    # Aldrig tyst: skanningen räknar filen bland
                    # "väntar i parkering" och sammanfattningen
                    # säger varför (orsaken syns också i
                    # felsökningspaketet per fil).
                    self._scan_stats["waiting"] = (
                        self._scan_stats.get("waiting", 0) + 1
                    )
                    raw_reason = str(
                        parked_entry.get("reason", "") or ""
                    )
                    bucket = (
                        "missing"
                        if raw_reason.startswith("missing")
                        else (raw_reason or "?")
                    )
                    self._waiting_reasons[bucket] = (
                        self._waiting_reasons.get(bucket, 0) + 1
                    )
                    continue
                log.info(
                    "SCAN_WATCH: %s var parkerad (%s) — prövar "
                    "igen, appen kan ha lärt sig formatet",
                    path.name, parked_entry.get("reason", ""),
                )
                self._config["parked"].remove(parked_entry)
                self._save()
            try:
                text, method, parsed = yield {
                    "kind": "analyze",
                    "path": str(path),
                    "entry": entry,
                    "stage": "läsa/tolka",
                }
            except Exception as exc:
                # Ett trasigt/skyddat original får aldrig stoppa resten av
                # mappen eller markeras som bearbetat. Nästa skanning prövar
                # filen igen; övriga original fortsätter normalt.
                self._record_scan_error(str(path), "läsa/tolka", digest, exc)
                continue
            self._process_parsed(entry, path, digest, text, method, parsed)
            self._reported_file_errors.pop(str(path), None)
            self.file_recovered.emit(str(path))

    def _parse_file(
        self, si: Any, entry: dict, path: Path
    ) -> tuple[str, str, dict]:
        """Textuttag + tolkning av en fil, med mappens leverantör
        påtvingad. Returnerar (text, metod, tolkning) — samma
        väg som registreringen använder, så en kontrolläsning
        bedöms exakt som den ursprungliga inläsningen."""
        suppliers = self._suppliers()
        templates: dict = {}
        if self._templates_provider is not None:
            try:
                templates = self._templates_provider() or {}
            except Exception:
                templates = {}
        # Missing/corrupt learning memory means zero confirmations,
        # never implicit trust in a saved custom template.
        learning: dict = {}
        if self._learning_provider is not None:
            try:
                learning = self._learning_provider() or {}
            except Exception:
                learning = {}
        return parse_watched_file(
            si,
            path,
            str(entry.get("supplier", "") or ""),
            suppliers,
            templates,
            learning,
            extract_fn=self._extract_fn,
        )

    def _find_invoice_for_file(
        self, entry: dict, path: Path, digest: str, info: dict
    ) -> dict | None:
        """Registerfakturan som hör till en redan bearbetad fil:
        originalsökvägen pekar på den, samma filinnehåll under
        den, eller mappens leverantör + fakturanumret som
        bearbetningsregistret sparade."""
        invoices = self._invoices()
        target = _norm_path_key(str(path))
        for inv in invoices:
            att = str(inv.get("attachment", "") or "")
            if att and _norm_path_key(att) == target:
                return inv
        for inv in invoices:
            att = str(inv.get("attachment", "") or "")
            if att and Path(att).is_file():
                if self._file_digest(Path(att)) == digest:
                    return inv
        supplier = self._resolve_register_supplier(
            str(entry.get("supplier", "") or "")
        ).strip().lower()
        nr = str(info.get("invoice_number", "") or "").strip().lower()
        if supplier and nr:
            for inv in invoices:
                if (
                    str(inv.get("supplier", "") or "").strip().lower()
                    == supplier
                    and str(
                        inv.get("invoice_number", "") or ""
                    ).strip().lower() == nr
                ):
                    return inv
        return None

    def _control_check_file(
        self, si: Any, entry: dict, path: Path, digest: str
    ) -> bool:
        """Kontrolläs en REDAN bearbetad fil mot registret (synkront).

        Tolkningen kan också köras i arbetstråden; den här varianten
        finns för scan_all(), reprocess_parked() och tester. Returnerar
        True när filen är färdigkontrollerad; False när ingen faktura
        hör till filen längre (bearbetningsmarkeringen tas då bort och
        anroparen läser in filen som ny)."""
        info = self._config.get("processed", {}).get(digest, {}) or {}
        inv = self._find_invoice_for_file(entry, path, digest, info)
        if inv is None:
            log.info(
                "SCAN_WATCH kontroll: %s är bearbetad men "
                "fakturan saknas i registret — läses in på nytt",
                path.name,
            )
            self.unprocess(digest)
            return False
        try:
            _text, _method, parsed = self._parse_file(si, entry, path)
        except Exception as exc:
            self._record_scan_error(
                str(path), "kontrolläsa", digest, exc
            )
            return True
        self._control_check_parsed(inv, path, digest, parsed)
        return True

    def _control_check_parsed(
        self, inv: dict, path: Path, digest: str, parsed: dict
    ) -> None:
        """Jämför en färdigtolkad fil med den registrerade fakturan.

        Registrerade data ändras ALDRIG härifrån; avvikelser räknas och
        loggas (last_control_diffs) för rättning per faktura i
        Fakturor-fliken."""
        self._reported_file_errors.pop(str(path), None)
        changes = invoice_control_changes(inv, parsed)
        self.file_recovered.emit(str(path))
        if not changes:
            self._scan_stats["already"] = (
                self._scan_stats.get("already", 0) + 1
            )
            return
        self._scan_stats["changed"] = (
            self._scan_stats.get("changed", 0) + 1
        )
        self._control_diffs.append({
            "file": path.name,
            "invoice_id": str(inv.get("id", "") or ""),
            "invoice_number": str(inv.get("invoice_number", "") or ""),
            "changes": {
                field: [old, new]
                for field, (old, new) in changes.items()
            },
        })
        detail = ", ".join(
            f"{field}: {old} → {new}"
            for field, (old, new) in changes.items()
        )
        log.warning(
            "SCAN_WATCH kontroll: %s (faktura %s) avviker mot "
            "registret — %s. Inget ändrat; rätta via Fakturor "
            "→ högerklicka → Skanna om faktura.",
            path.name,
            inv.get("invoice_number", "?"), detail,
        )

    def _process_file(self, si: Any, entry: dict, path: Path,
                      digest: str) -> None:
        """Tolkar och hanterar en fil synkront (scan_all/tester)."""
        text, method, parsed = self._parse_file(si, entry, path)
        self._process_parsed(entry, path, digest, text, method, parsed)

    def _process_parsed(self, entry: dict, path: Path, digest: str,
                        text: str, method: str, parsed: dict) -> None:
        """Klassificerar en färdigtolkad fil (körs alltid i GUI-tråden).

        Registreringen/parkeringen sker här, aldrig i arbetstråden, så
        att konfiguration, register och vyer bara rörs från en tråd.
        """
        # Leverantören måste finnas i registret för auto-registrering,
        # annars parkeras filen för granskning i stället.
        known = {
            str(x.get("name", "")).strip().lower()
            for x in self._suppliers()
        }
        if (
            known
            and parsed.get("supplier")
            and str(parsed["supplier"]).strip().lower() not in known
            and "leverantör" not in parsed["missing"]
        ):
            parsed["missing"].append("leverantör")

        # Räkne-/datumkontrollerna är rådgivande: värdena
        # registreras som tolkade, men avvikelser loggas så de
        # syns i felsökningspaketet och kan granskas i Import.
        _mc = parsed.get("math_check") or {}
        if isinstance(_mc, dict) and _mc.get("status") == "mismatch":
            log.warning(
                "SCAN_WATCH: %s — räknekontrollen avviker: netto "
                "%s + moms %s = %s, men att betala är %s "
                "(diff %s kr)",
                path.name, _mc.get("net"), _mc.get("vat"),
                _mc.get("expected"), parsed.get("total_amount"),
                _mc.get("diff"),
            )
        _dc = parsed.get("date_check") or {}
        if isinstance(_dc, dict) and _dc.get("problems"):
            log.warning(
                "SCAN_WATCH: %s — datumkontrollen varnar: %s "
                "(fakturadatum %s, förfallodatum %s)",
                path.name, ", ".join(_dc["problems"]),
                parsed.get("date", ""), parsed.get("due_date", ""),
            )

        now = datetime.now().isoformat(timespec="seconds")
        base_info = {
            "hash": digest, "path": str(path), "file": path.name,
            "ts": now,
        }

        # Dubblett mot registret → importera inte. Om originalet redan
        # är exakt länkat till registerposten kan den gamla placeringen
        # årsarkiveras säkert och attachment-sökvägen uppdateras.
        if invoice_exists(
            self._invoices(),
            parsed.get("supplier", ""),
            parsed.get("invoice_number", ""),
        ):
            final_path = self._archive_existing_registered_original(
                path, parsed
            )
            self._config["processed"][digest] = {
                **base_info,
                "path": final_path,
                "file": Path(final_path).name,
                "result": "duplicate-invoice",
            }
            self._processed_path_keys.add(
                _norm_path_key(str(final_path))
            )
            self._save()
            self._scan_stats["duplicate"] += 1
            log.info(
                "SCAN_WATCH: %s redan registrerad (dubblett) — hoppar",
                path.name,
            )
            return

        # Möjlig dubblett (nästan samma nummer + samma belopp/
        # datum, eller numret i annan separatorform) registreras
        # ALDRIG automatiskt — filen parkeras och användaren får
        # varningen + avgörandet. Exakt dubblett är redan stoppad
        # ovan; det här fångar inskanning-igen med OCR-avvikelse.
        possible_dup = None
        if not parsed.get("missing"):
            try:
                try:
                    from ui.invoices_helpers import (
                        find_possible_duplicate,
                    )
                except Exception:
                    from invoices_helpers import (  # type: ignore
                        find_possible_duplicate,
                    )
                possible_dup = find_possible_duplicate(
                    self._invoices(), parsed
                )
            except Exception as exc:
                log.debug("possible-duplicate check: %s", exc)
                possible_dup = None

        # Auto-registrering kräver en inlärd leverantörsmall
        # som faktiskt träffar på filen (se punkt 5 ovan).
        # Osäker leverantörs-/mallmatchning parkeras alltid med
        # sin egen orsak så att Import-vyn kan FRÅGA användaren —
        # appen gissar aldrig och registrerar aldrig automatiskt.
        untaught = not parsed.get("template")
        uncertain = bool(parsed.get("match_uncertain"))
        ocr_warning = bool(parsed.get("ocr_warning"))
        payment_warning = bool(parsed.get("payment_details_warning"))
        if (
            uncertain or ocr_warning or payment_warning or parsed.get("missing")
            or possible_dup or not self.auto_create or untaught
        ):
            if uncertain:
                reason = "uncertain-supplier"
            elif payment_warning:
                reason = "payment-details"
            elif ocr_warning:
                reason = "ocr-warning"
            elif parsed.get("missing"):
                reason = "missing: " + ", ".join(
                    parsed.get("missing", [])
                )
            elif possible_dup:
                inv = possible_dup.get("invoice", {}) or {}
                reason = (
                    "possible-duplicate: "
                    f"faktura {inv.get('invoice_number', '')} "
                    f"({possible_dup.get('reason', '')})"
                )
            elif not self.auto_create:
                reason = "review"
            else:
                reason = "no-template"
            parked = {
                **base_info, "reason": reason,
                # Flersidiga fakturor: betalblocket ligger ofta på
                # sista sidan — spara hela texten (3-sidorsbudget)
                "text": (text or "")[:30_000],
                "parsed": parsed, "method": method,
            }
            self._config["parked"].append(parked)
            self._save()
            self.file_parked.emit(parked)
            self.changed.emit()
            self._scan_stats["parked"] += 1
            log.info(
                "SCAN_WATCH: %s parkerad för granskning (%s) — "
                "tolkat: fakturanr=%s, belopp=%s, saknar=%s, "
                "textuttag=%s (%d tecken)",
                path.name, reason,
                parsed.get("invoice_number") or "—",
                parsed.get("total_amount") or "—",
                ", ".join(parsed.get("missing", [])) or "—",
                method or "—", len(text or ""),
            )
            return

        # Originalet ligger kvar på källsökvägen tills den faktiska
        # registerposten sparas. ScanImportView årsarkiverar därefter
        # filen utifrån fakturadatum och sparar den nya sökvägen.
        final_path = path

        row = {
            **parsed,
            "file": path.name, "_path": str(final_path),
            "method": method, "_text": (text or "")[:30_000],
            "_hash": digest,
        }
        self._config["processed"][digest] = {
            **base_info, "path": str(final_path),
            "result": "imported",
            "invoice_number": str(parsed.get("invoice_number", "") or ""),
        }
        self._processed_path_keys.add(_norm_path_key(str(final_path)))
        self._save()
        self.invoice_ready.emit(row, str(final_path))
        self._scan_stats["imported"] += 1
        log.info(
            "SCAN_WATCH: %s tolkad (mall=%s) → registreras",
            path.name, parsed.get("template", "-"),
        )

    def scan_now(self) -> None:
        self.start_scan()


class WatchFolderDialog(QDialog):
    """Lägg till en bevakad mapp: leverantör + mapp."""

    def __init__(
        self, parent: QWidget | None, suppliers: list[str],
        supplier: str = "", path: str = "",
    ) -> None:
        super().__init__(parent)
        self.result_data: dict | None = None
        self.setWindowTitle(tr("watch.dialog_title"))
        root = QVBoxLayout(self)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel(tr("watch.supplier")))
        self._cmb_supplier = QComboBox()
        # INTE redigerbar: leverantören VÄLJS ur registret.
        # Fri text ("AAG Automotive" mot registerpostens
        # "AAG Automotive AB") gjorde att kopplingen aldrig
        # tog — mappens namn spelar ingen roll, bara vilken
        # registerpost man kopplar den till.
        self._cmb_supplier.setEditable(False)
        self._cmb_supplier.addItems(suppliers)
        if supplier:
            if self._cmb_supplier.findText(supplier) < 0:
                # Redan kopplat namn som saknas i registret —
                # visa det som det är (bevakningen slår upp
                # registerposten tolerant vid skanning).
                self._cmb_supplier.addItem(supplier)
            self._cmb_supplier.setCurrentText(supplier)
        row1.addWidget(self._cmb_supplier, stretch=1)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel(tr("watch.folder")))
        self._edit_path = QLineEdit(path)
        row2.addWidget(self._edit_path, stretch=1)
        btn_browse = QPushButton(tr("watch.browse"))
        btn_browse.clicked.connect(self._browse)
        row2.addWidget(btn_browse)
        root.addLayout(row2)

        self._lbl_hint = QLabel()
        root.addWidget(self._lbl_hint)

        row3 = QHBoxLayout()
        row3.addStretch()
        btn_cancel = QPushButton(f"✖  {tr('common.cancel')}")
        btn_cancel.clicked.connect(self.reject)
        row3.addWidget(btn_cancel)
        btn_ok = QPushButton(tr("watch.add"))
        btn_ok.setProperty("success", True)
        btn_ok.clicked.connect(self._accept)
        row3.addWidget(btn_ok)
        root.addLayout(row3)
        try:
            from ui.design import fit_dialog_to_screen
            fit_dialog_to_screen(
                self, 500, 220, minimum_width=420, minimum_height=180,
            )
        except Exception:
            self.setMinimumWidth(480)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, tr("watch.folder"), self._edit_path.text()
        )
        if chosen:
            self._edit_path.setText(chosen)

    def _accept(self) -> None:
        path = self._edit_path.text().strip()
        if not path or not Path(path).is_dir():
            self._lbl_hint.setText(tr("watch.need_folder"))
            return
        self.result_data = {
            "supplier": self._cmb_supplier.currentText().strip(),
            "path": path,
        }
        self.accept()
