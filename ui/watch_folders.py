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
        except Exception:
            pass
        return {
            "folders": [], "auto_create": True,
            "processed": {}, "parked": [],
        }

    def _save(self) -> None:
        try:
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

    def set_folders(self, folders: list[dict]) -> None:
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

    def scan_all(self) -> None:
        for entry in self.folders:
            try:
                self.scan_folder(entry)
            except Exception as exc:
                log.warning("SCAN_WATCH scan %s: %s", entry, exc)

    def scan_folder(self, entry: dict) -> None:
        folder = Path(str(entry.get("path", "")))
        if not folder.is_dir():
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
                continue
            if any(
                p.get("hash") == digest
                for p in self._config.get("parked", [])
            ):
                continue
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
                str(inv.get("attachment", "") or ""): inv
                for inv in invoices
                if str(inv.get("attachment", "") or "")
            }
            if not by_path:
                return
            from invoices_helpers import sort_into_year_folder

            for child in sorted(folder.iterdir()):
                if not child.is_file() or not supported_file(child):
                    continue
                inv = by_path.get(str(child))
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
        parsed = si.parse_invoice_text(
            text or "", self._suppliers(), templates=templates
        )
        folder_supplier = str(entry.get("supplier", "")).strip()
        if folder_supplier:
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
            log.info(
                "SCAN_WATCH: %s redan registrerad (dubblett) — hoppar",
                path.name,
            )
            return

        # Auto-registrering kräver en inlärd leverantörsmall
        # som faktiskt träffar på filen (se punkt 5 ovan).
        untaught = not parsed.get("template")
        if parsed.get("missing") or not self.auto_create or untaught:
            if parsed.get("missing"):
                reason = "missing: " + ", ".join(
                    parsed.get("missing", [])
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
            log.info(
                "SCAN_WATCH: %s parkerad för granskning (%s)",
                path.name, reason,
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
        }
        self._config["processed"][digest] = {
            **base_info, "path": str(final_path),
            "result": "imported",
        }
        self._save()
        self.invoice_ready.emit(row, str(final_path))
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
        self._cmb_supplier.setEditable(True)
        self._cmb_supplier.addItems(suppliers)
        if supplier:
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
