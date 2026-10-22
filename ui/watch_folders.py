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
     på). Originalfilen lämnas kvar i mappen — fakturan i JSON
     pekar på den där (ingen kopia). Betal-PDF:en hämtar
     originalet via sökvägen; saknas filen då varnar exporten.
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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal
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

#: Filtyper som bevakningen tar (PDF/bilder — .txt räknas inte,
#: extraktorn känner inte igen den).
SUPPORTED_SUFFIXES: tuple[str, ...] = (
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
)


def supported_file(path: Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


def _invoice_year(date_str) -> str:
    """
    Året ur fakturadatumet ("2023-06-16" → "2023"); "" om det
    saknas eller inte ser rimligt ut. Ingen gissning härifrån:
    utan år får originalet ligga kvar överst i mappen.
    """
    m = re.match(r"^(?:19|20)\d{2}", str(date_str or "").strip())
    return str(date_str or "").strip()[:4] if m else ""


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


def _norm_path_key(path: str) -> str:
    """Sökväg som jämförelsenyckel: "D:/gewgg/f.pdf" och
    "D:\\gewgg\\f.pdf" är samma fil. Registrets sökvägar kan
    komma från fil dialogs (/) medan skanningen bygger dem med
    OS-separator — utan normalisering missar årssorteringen
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


_PARK_REASON_SV = {
    "no-template": (
        "okänt format för leverantören — appen har ingen inlärd "
        "mall och inget inbyggt verifierat format träffar"
    ),
    "review": (
        "auto-registrering avstängd — väntar på manuell granskning"
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
            "{duplicate} dubbletter (fanns redan — rördes inte), "
            "{parked} parkerade, {already} redan bearbetade, "
            "{waiting} väntar i parkering".format(
                **{
                    k: int((stats or {}).get(k, 0) or 0)
                    for k in (
                        "imported", "duplicate", "parked", "already",
                        "waiting",
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


class WatchManager(QObject):
    """
    Bevakar mappar, tolkar nya filer och signalerar resultatet.

    Signaler:
      invoice_ready(parsed_row, källfil)  — komplett, kan skapas
      file_parked(info)                   — behöver granskning
      changed()                           — config/parkerade ändrats
    """

    invoice_ready = Signal(dict, str)
    file_parked = Signal(dict)
    changed = Signal()

    def __init__(
        self,
        config_file: Path,
        app: Any = None,
        templates_provider: Callable[[], dict] | None = None,
        extract_fn: Callable[[Path], tuple[str, str]] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_file = Path(config_file)
        self._app = app
        self._templates_provider = templates_provider
        self._extract_fn = extract_fn
        self._config: dict[str, Any] = self._load()
        self._warned_missing: set[str] = set()
        self._scan_stats: dict[str, int] = {
            "imported": 0, "duplicate": 0, "parked": 0, "already": 0,
            "waiting": 0,
        }
        self._waiting_reasons: dict[str, int] = {}
        self._last_logged_waiting: int = -1
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
        self._debounce.timeout.connect(self.scan_all)

        # Säkerhetspoll (nätverksdiskar missar ibland watcher-events)
        self._poll = QTimer(self)
        self._poll.setInterval(30_000)
        self._poll.timeout.connect(self.scan_all)
        self._poll.start()
        self._rewatch()
        QTimer.singleShot(2000, self.scan_all)

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
        self.scan_all()

    def set_auto_create(self, enabled: bool) -> None:
        self._config["auto_create"] = bool(enabled)
        self._save()
        self.changed.emit()
        if enabled:
            # Filer som bara väntade på att auto-registreringen
            # skulle slås på prövas direkt — annars låg de kvar
            # i parkeringen i evighet trots att formatet läses.
            self.scan_all()

    def unprocess(self, file_hash_value: str) -> None:
        """Tar bort en fil ur bearbetade-registret så nästa
        skanning prövar den igen. Används när registreringen av en
        tolkad faktura misslyckades: filen får ALDRIG bli kvar som
        'importerad' utan att fakturan faktiskt finns i registret
        — då skulle den varken synas eller någonsin prövas om."""
        if self._config.get("processed", {}).pop(file_hash_value, None) is not None:
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
        current = set(self._watcher.directories())
        wanted = {
            f["path"] for f in self.folders
            if Path(f["path"]).is_dir()
        }
        for gone in current - wanted:
            self._watcher.removePath(gone)
        for new in wanted - current:
            self._watcher.addPath(new)

    # ── Tolkning ──────────────────────────────────────────────────────

    def _scan_module(self):
        import sys

        plugins = str(
            Path(__file__).resolve().parent.parent / "plugins"
        )
        if plugins not in sys.path:
            sys.path.insert(0, plugins)
        import scan_import as si

        return si

    def _resolve_register_supplier(self, wanted: str) -> str:
        """Slår upp mappens leverantörsnamn mot registret tolerant.

        Mappen kan heta "Martin G" medan registerposten heter
        "AB Martin G Anderson" — exakt namnmatchning fick då
        registreringen att stoppa med "leverantör saknas" trots
        att användaren pekat ut rätt leverantör. Nu jämförs
        namnen normaliserade (bolagsform/punkt borta, ordmängd):
        exakt eller entydig delmängd ger träff, annars "".
        """
        want = _norm_supplier_name(wanted)
        if not want:
            return ""
        candidates = []
        for sup in self._suppliers():
            name = str(sup.get("name", "")).strip()
            have = _norm_supplier_name(name)
            if not have:
                continue
            if have == want:
                return name
            if want <= have or have <= want:
                candidates.append(name)
        return candidates[0] if len(candidates) == 1 else ""

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
        """Utfall av senaste skanning: nyregistrerade, dubblettar
        (fanns redan i registret — rörs inte), parkerade och filer
        som var bearbetade sedan tidigare. 'Bearbetad' ensamt säger
        ingenting: en dubblett skapar ingen ny faktura."""
        return dict(self._scan_stats)

    def scan_all(self) -> None:
        self._scan_stats = {
            "imported": 0, "duplicate": 0, "parked": 0, "already": 0,
            "waiting": 0,
        }
        self._waiting_reasons = {}
        self._heal_missing_imports()
        for entry in self.folders:
            try:
                self.scan_folder(entry)
            except Exception as exc:
                log.warning("SCAN_WATCH scan %s: %s", entry, exc)
        # Sammanfattningen loggas när något hände — eller när
        # antalet i parkering-väntar ändrats — så den aldrig är
        # tyst om varför filer inte läses in, men inte heller
        # loggar samma rad var 30:e sekund när inget ändrats.
        active = any(
            v for k, v in self._scan_stats.items() if k != "waiting"
        )
        waiting = self._scan_stats.get("waiting", 0)
        if active or waiting != self._last_logged_waiting:
            self._last_logged_waiting = waiting
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
                "%d väntar i parkering%s",
                self._scan_stats["imported"],
                self._scan_stats["duplicate"],
                self._scan_stats["parked"],
                self._scan_stats["already"],
                waiting,
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
            known_hashes: set[str] = set()
            known_numbers: set[tuple[str, str]] = set()
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
                    if Path(att).is_file():
                        try:
                            known_hashes.add(file_hash(Path(att)))
                        except Exception:
                            pass
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

            healed = 0
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
                if digest in known_hashes:
                    continue
                nr = str(
                    info.get("invoice_number", "") or ""
                ).strip().lower()
                if nr and (
                    _supplier_of(fpath), nr
                ) in known_numbers:
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

    def reprocess_parked(self, entry: dict | None = None) -> int:
        """Läser OM parkerade tolkningsfiler med dagens mallar.

        Det här är tillfället då filer som parkerats för tolkning
        (orsak "no-template" eller "missing: …") tolkas på nytt —
        anropas när användaren sparat en mall, så leverantörens
        övriga väntande fakturor prövas mot den direkt. Med
        `entry` bara den mappens filer, annars alla bevakade
        mappar. Returnerar antalet filer som lästes om.
        """
        folder_key = ""
        if entry is not None:
            folder_key = _norm_path_key(str(entry.get("path", "")))
        targets: list[dict] = []
        for parked in list(self._config.get("parked", [])):
            reason = str(parked.get("reason", "") or "")
            if not (
                reason == "no-template"
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
                "dagens mallar", len(targets),
            )
        if entry is not None:
            self.scan_folder(entry)
        else:
            self.scan_all()
        return len(targets)

    def scan_folder(self, entry: dict) -> None:
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
        self._sort_registered_backlog(folder)
        si = None
        for path in supported_invoice_files(folder):
            if not path.is_file():
                continue
            try:
                digest = file_hash(path)
            except Exception:
                continue
            if digest in self._config["processed"]:
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
            if si is None:
                si = self._scan_module()
            self._process_file(si, entry, path, digest)

    def _sort_registered_backlog(self, folder: Path) -> None:
        """
        Eftersortering: redan registrerade original som
        fortfarande ligger direkt i den bevakade mappen flyttas
        till sin årsmapp (<år>/ efter fakturadatum) och registrets
        sökväg pekas om. Parkerade rörs inte — sorteringen
        gäller bara registrerade fakturor, precis som valt.
        Kastar aldrig: ett sorteringsfel får inte stoppa
        skanningen.
        """
        try:
            invoices = self._invoices()
            if not invoices:
                return
            by_path = {
                _norm_path_key(
                    str(inv.get("attachment", "") or "")
                ): inv
                for inv in invoices
                if str(inv.get("attachment", "") or "")
            }
            if not by_path:
                return
            from invoices_helpers import sort_into_year_folder

            for child in sorted(folder.iterdir()):
                if not child.is_file() or not supported_file(child):
                    continue
                inv = by_path.get(_norm_path_key(str(child)))
                if inv is None:
                    continue
                year = _invoice_year(inv.get("date", ""))
                if not year:
                    continue
                new_path = sort_into_year_folder(
                    str(child), str(folder), year
                )
                if new_path == str(child):
                    continue
                try:
                    self._app.update_invoice(
                        inv["id"], {"attachment": new_path}
                    )
                    inv["attachment"] = new_path
                    by_path[new_path] = inv
                except Exception as exc:
                    log.warning(
                        "SCAN_WATCH årssortering registry-update"
                        " %s: %s", child.name, exc
                    )
        except Exception as exc:
            log.warning("SCAN_WATCH årssortering: %s", exc)

    def _process_file(self, si: Any, entry: dict, path: Path,
                      digest: str) -> None:
        if self._extract_fn is not None:
            text, method = self._extract_fn(path)
        else:
            text, method = si.extract_text(path)
        templates = {}
        if self._templates_provider is not None:
            try:
                templates = self._templates_provider() or {}
            except Exception:
                templates = {}
        parse_file = getattr(si, "parse_invoice_file", None)
        if parse_file is not None:
            parsed = parse_file(
                path, text or "", self._suppliers(),
                templates=templates,
            )
        else:
            parsed = si.parse_invoice_text(
                text or "", self._suppliers(), templates=templates
            )
        folder_supplier = str(entry.get("supplier", "")).strip()
        if folder_supplier:
            resolved = self._resolve_register_supplier(folder_supplier)
            if resolved and resolved != folder_supplier:
                log.info(
                    "SCAN_WATCH: mappens leverantör '%s' → "
                    "registerposten '%s'",
                    folder_supplier, resolved,
                )
                folder_supplier = resolved
            parsed["supplier"] = folder_supplier
            parsed["missing"] = [
                m for m in parsed.get("missing", [])
                if m != "leverantör"
            ]
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

        # Dubblett mot registret → markera bearbetad, importera inte
        if invoice_exists(
            self._invoices(),
            parsed.get("supplier", ""),
            parsed.get("invoice_number", ""),
        ):
            self._config["processed"][digest] = {
                **base_info, "result": "duplicate-invoice",
            }
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
        untaught = not parsed.get("template")
        if (
            parsed.get("missing") or possible_dup
            or not self.auto_create or untaught
        ):
            if parsed.get("missing"):
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

        # Årssortering: det nya originalet får sin årsmapp
        # direkt (<bevakad mapp>/<fakturaår>/) — innan raden
        # ens når registret, så alla sökvägar pekar rätt från
        # början. Utan läsbart år ligger det kvar överst.
        final_path = path
        year = _invoice_year(parsed.get("date", ""))
        if year:
            from invoices_helpers import sort_into_year_folder

            moved = sort_into_year_folder(
                str(path), str(Path(str(entry.get("path", "")))), year
            )
            if moved != str(path):
                final_path = Path(moved)

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
        self._save()
        self.invoice_ready.emit(row, str(final_path))
        self._scan_stats["imported"] += 1
        log.info(
            "SCAN_WATCH: %s tolkad (mall=%s) → registreras",
            path.name, parsed.get("template", "-"),
        )

    def scan_now(self) -> None:
        self.scan_all()


class WatchFolderDialog(QDialog):
    """Lägg till en bevakad mapp: leverantör + mapp."""

    def __init__(
        self, parent: QWidget | None, suppliers: list[str],
        supplier: str = "", path: str = "",
    ) -> None:
        super().__init__(parent)
        self.result_data: dict | None = None
        self.setWindowTitle(tr("watch.dialog_title"))
        self.setMinimumWidth(480)
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
