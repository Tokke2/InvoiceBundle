from __future__ import annotations

"""
Fakturabunten — Import-vy för skannade fakturor
======================================================
Fil    : Fakturabunten_/ui/scan_import_view.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Import-fliken: läser in skannade fakturor (PDF/bild), visar vad som
tolkades och låter användaren bekräfta/rätta INNAN fakturan skapas.

Kärnan i appen är oförändrad — ange fakturor, räkna ihop ATT BETALA.
Den här vyn är bara en snabbväg in till samma registrering.

Flöde
─────
    1. Dra in filer / välj filer / klistra in text
    2. "Läs in och tolka"  → visar tabell med kandidater
    3. Markera rad → "Skapa faktura" → fakturan registreras
       (belopp läggs till ATT BETALA precis som vid manuell inmatning)

Allt loggas som SCAN_IMPORT / SCAN_CREATE i logs/app.log.

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import logging
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QTextEdit, QMessageBox, QFileDialog, QFrame,
    QComboBox, QLineEdit, QCheckBox, QSplitter, QApplication,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QCursor, QPixmap

log = logging.getLogger("ScanImportView")

try:
    from ui.i18n import tr
except Exception:  # pragma: no cover
    try:
        from i18n import tr  # type: ignore[no-redef]
    except Exception:
        def tr(key: str, **_fmt: object) -> str:  # type: ignore[no-redef]
            return key

COPYRIGHT_YEAR: int = datetime.date.today().year

#: Kolumner i tolkningstabellen: (rubrik, nyckel, bredd, justering)
COLUMNS: list[tuple[str, str, int, Any]] = [
    ("Fil",            "file",           170, Qt.AlignmentFlag.AlignLeft),
    ("Leverantör",     "supplier",       140, Qt.AlignmentFlag.AlignLeft),
    ("Fakturanr",      "invoice_number", 100, Qt.AlignmentFlag.AlignLeft),
    ("Datum",          "date",            90, Qt.AlignmentFlag.AlignLeft),
    ("Förfaller",      "due_date",        90, Qt.AlignmentFlag.AlignLeft),
    ("OCR",            "ocr",            110, Qt.AlignmentFlag.AlignLeft),
    ("Belopp",         "total_amount",   100, Qt.AlignmentFlag.AlignRight),
    ("Metod",          "method",         120, Qt.AlignmentFlag.AlignLeft),
    ("Status",         "status",         110, Qt.AlignmentFlag.AlignLeft),
]


def _fmt_amount(value: float) -> str:
    """45546.0 → '45 546,00' (svenskt format)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    kr = int(v)
    frac = int(round((v - kr) * 100))
    return f"{kr:,}".replace(",", " ") + f",{frac:02d}"


def _parse_amount(text: str) -> float:
    """Tolerant parsning av '45 546,00' / '45546.50' → float."""
    t = (text or "").replace(" ", "").replace("\u00a0", "")
    t = t.replace("kr", "").replace("SEK", "").replace(",", ".")
    try:
        return abs(float(t))
    except ValueError:
        return 0.0


class ScanImportView(QWidget):
    """
    Import-vy för skannade fakturor.

    Integritet: läser bara filer användaren själv väljer, skickar
    aldrig något över nätet, sparar inget förrän användaren klickar
    "Skapa faktura".
    """

    def __init__(self, app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._app = app
        self._rows: list[dict] = []       # tolkade rader
        self._paths: list[Path] = []      # valda filer
        self._dark = True
        self._build_ui()
        self._log_status()

    # ══════════════════════════════════════════════════════════════════
    #  UI
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        hdr = QLabel(tr("scan.title"))
        self._hdr_label = hdr
        hdr.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        head = QHBoxLayout()
        head.setSpacing(8)
        _icon = Path(__file__).resolve().parent.parent / "app_icon.png"
        if _icon.is_file():
            mark = QLabel()
            mark.setPixmap(
                QPixmap(str(_icon)).scaled(
                    28, 28,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            mark.setStyleSheet("background:transparent;")
            head.addWidget(mark)
        head.addWidget(hdr)
        head.addStretch()
        root.addLayout(head)

        info = QLabel(tr("scan.info"))
        self._info_label = info
        info.setWordWrap(True)
        info.setStyleSheet("color:#8b949e;background:transparent;")
        root.addWidget(info)
        root.addWidget(self._hline())

        # ── 1. Välj filer ─────────────────────────────────────────────
        box_files = QGroupBox(tr("scan.step1"))
        self._box_files = box_files
        bf = QVBoxLayout(box_files)
        bf.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        btn_pick = QPushButton(tr("scan.pick"))
        self._btn_pick = btn_pick
        btn_pick.clicked.connect(self._pick_files)
        btn_clear = QPushButton(tr("scan.clear"))
        self._btn_clear = btn_clear
        btn_clear.clicked.connect(self._clear_paths)
        self._lbl_files = QLabel(tr("scan.no_files"))
        self._lbl_files.setStyleSheet("color:#8b949e;background:transparent;")
        row1.addWidget(btn_pick)
        row1.addWidget(btn_clear)
        row1.addWidget(self._lbl_files, stretch=1)
        bf.addLayout(row1)

        self._txt_paths = QTextEdit()
        self._txt_paths.setReadOnly(True)
        self._txt_paths.setMaximumHeight(70)
        self._txt_paths.setPlaceholderText(
            "Valda filer visas här (du kan också klistra in sökvägar, "
            "en per rad)"
        )
        bf.addWidget(self._txt_paths)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        btn_scan = QPushButton(tr("scan.scan"))
        self._btn_scan = btn_scan
        btn_scan.setProperty("accent", True)
        btn_scan.setMinimumHeight(42)
        btn_scan.clicked.connect(self._scan_files)
        self._lbl_status = QLabel()
        self._lbl_status.setStyleSheet("color:#8b949e;background:transparent;")
        row2.addWidget(btn_scan)
        row2.addWidget(self._lbl_status, stretch=1)
        bf.addLayout(row2)
        root.addWidget(box_files)

        # ── 2. Klistra in text (manuell fallback) ─────────────────────
        box_txt = QGroupBox(tr("scan.step2"))
        self._box_txt = box_txt
        bt = QVBoxLayout(box_txt)
        bt.setSpacing(6)
        self._txt_paste = QTextEdit()
        self._txt_paste.setPlaceholderText(
            "Klistra in texten från fakturan här om OCR inte är "
            "installerat eller misslyckas.\n\n"
            "Exempel:\nFakturanr: 2026-144\nFakturadatum: 2026-08-17\n"
            "Förfallodatum: 2026-09-16\nAtt betala: 45 546,00"
        )
        self._txt_paste.setMaximumHeight(110)
        bt.addWidget(self._txt_paste)

        rowt = QHBoxLayout()
        rowt.setSpacing(8)
        btn_parse = QPushButton(tr("scan.parse"))
        self._btn_parse = btn_parse
        btn_parse.clicked.connect(self._scan_pasted)
        self._chk_auto = QCheckBox(tr("scan.auto_open"))
        self._chk_auto.setChecked(False)
        rowt.addWidget(btn_parse)
        rowt.addWidget(self._chk_auto)
        rowt.addStretch(1)
        bt.addLayout(rowt)
        root.addWidget(box_txt)

        # ── 3. Tolkade rader ──────────────────────────────────────────
        box_res = QGroupBox(tr("scan.step3"))
        self._box_res = box_res
        br = QVBoxLayout(box_res)
        br.setSpacing(8)

        self._tbl = QTableWidget(0, len(COLUMNS))
        self._tbl.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setAlternatingRowColors(True)
        self._tbl.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._tbl.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._tbl.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._tbl.setWordWrap(False)
        self._tbl.doubleClicked.connect(self._open_row_dialog)
        hh = self._tbl.horizontalHeader()
        for i, (_lbl, _key, width, _al) in enumerate(COLUMNS):
            self._tbl.setColumnWidth(i, width)
            hh.setSectionResizeMode(
                i, QHeaderView.ResizeMode.Interactive
            )
        hh.setStretchLastSection(True)
        self._tbl.setMinimumHeight(220)
        br.addWidget(self._tbl, stretch=1)

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        btn_create = QPushButton(tr("scan.create"))
        self._btn_create = btn_create
        btn_create.setProperty("success", True)
        btn_create.setMinimumHeight(42)
        btn_create.clicked.connect(self._create_invoices)
        btn_open_dlg = QPushButton(tr("scan.open_dialog"))
        self._btn_open_dlg = btn_open_dlg
        btn_open_dlg.clicked.connect(self._open_row_dialog)
        btn_del = QPushButton(tr("scan.remove_row"))
        self._btn_del = btn_del
        btn_del.clicked.connect(self._remove_row)
        self._lbl_sum = QLabel()
        self._lbl_sum.setStyleSheet(
            "background:transparent;font-weight:700;"
        )
        row3.addWidget(btn_create)
        row3.addWidget(btn_open_dlg)
        row3.addWidget(btn_del)
        row3.addWidget(self._lbl_sum, stretch=1)
        br.addLayout(row3)
        root.addWidget(box_res, stretch=1)

        # ── Logg-utdrag ───────────────────────────────────────────────
        self._lbl_log = QLabel()
        self._lbl_log.setStyleSheet(
            "color:#8b949e;background:transparent;font-size:11px;"
        )
        self._lbl_log.setWordWrap(True)
        root.addWidget(self._lbl_log)

        footer = QLabel(
            f"© {COPYRIGHT_YEAR} Rickard Längkvist  —  "
            f"Fakturabunten  ·  allt körs lokalt"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("color:#8b949e;background:transparent;")
        root.addWidget(footer)

    def retranslate(self) -> None:
        """Uppdaterar vyns texter efter språkbyte (utan omstart)."""
        self._hdr_label.setText(tr("scan.title"))
        self._info_label.setText(tr("scan.info"))
        self._box_files.setTitle(tr("scan.step1"))
        self._box_txt.setTitle(tr("scan.step2"))
        self._box_res.setTitle(tr("scan.step3"))
        self._btn_pick.setText(tr("scan.pick"))
        self._btn_clear.setText(tr("scan.clear"))
        if not self._paths:
            self._lbl_files.setText(tr("scan.no_files"))
        self._btn_scan.setText(tr("scan.scan"))
        self._btn_parse.setText(tr("scan.parse"))
        self._chk_auto.setText(tr("scan.auto_open"))
        self._btn_create.setText(tr("scan.create"))
        self._btn_open_dlg.setText(tr("scan.open_dialog"))
        self._btn_del.setText(tr("scan.remove_row"))

    @staticmethod
    def _hline() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color:#30363d;")
        return f

    # ══════════════════════════════════════════════════════════════════
    #  STATUS / LOGG
    # ══════════════════════════════════════════════════════════════════

    def _log_status(self) -> None:
        """Visar vilka textkällor som är tillgängliga på maskinen."""
        try:
            import sys

            sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
            import scan_import as si

            stöd = []
            if si.HAS_PYPDF:
                stöd.append("pypdf")
            if si.HAS_FITZ:
                stöd.append("PyMuPDF")
            if si.HAS_TESS:
                stöd.append("Tesseract OCR")
            txt = (
                "Textkällor: " + ", ".join(stöd)
                if stöd
                else "Ingen PDF/OCR-modul hittad — klistra in fakturatexten "
                     "i ruta 2 (fungerar alltid)"
            )
            self._lbl_log.setText(txt)
        except Exception as exc:
            log.warning("status: %s", exc)

    # ══════════════════════════════════════════════════════════════════
    #  FILVAL
    # ══════════════════════════════════════════════════════════════════

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Välj skannade fakturor",
            "",
            "Fakturor (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp);;"
            "Alla filer (*)",
        )
        if files:
            self._set_paths([Path(f) for f in files])

    def _set_paths(self, paths: list[Path]) -> None:
        self._paths = [p for p in paths if p.exists()]
        self._txt_paths.setPlainText(
            "\n".join(str(p) for p in self._paths)
        )
        n = len(self._paths)
        self._lbl_files.setText(
            f"{n} fil(er) valda" if n else "Inga filer valda"
        )

    def _clear_paths(self) -> None:
        self._paths = []
        self._txt_paths.clear()
        self._lbl_files.setText("Inga filer valda")

    # ══════════════════════════════════════════════════════════════════
    #  TOLKNING
    # ══════════════════════════════════════════════════════════════════

    def _suppliers(self) -> list[dict]:
        try:
            return self._app.get_suppliers() if self._app else []
        except Exception:
            return []

    def _scan_files(self) -> None:
        """Läser och tolkar valda filer."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
        import scan_import as si

        # Tolerera inklistrade sökvägar i textrutan
        if self._txt_paths.toPlainText().strip():
            pasted = [
                Path(line.strip())
                for line in self._txt_paths.toPlainText().splitlines()
                if line.strip()
            ]
            if pasted:
                self._paths = [p for p in pasted if p.exists()] or self._paths

        if not self._paths:
            QMessageBox.information(
                self, "Import",
                "Välj en eller flera filer först (ruta 1).",
            )
            return

        suppliers = self._suppliers()
        new_rows: list[dict] = []
        for path in self._paths:
            try:
                text, method = si.extract_text(path)
            except Exception as exc:
                log.error("extract %s: %s", path.name, exc)
                text, method = "", "fel"
            parsed = si.parse_invoice_text(text, suppliers)
            parsed["file"] = path.name
            parsed["_path"] = str(path)
            parsed["method"] = method
            parsed["_text"] = (text or "")[:4000]
            status = (
                "redo" if not parsed["missing"]
                else "saknas: " + ", ".join(parsed["missing"])
            )
            if not text:
                status = "ingen text hittad"
            parsed["status"] = status
            new_rows.append(parsed)
            log.info(
                "SCAN_IMPORT: %s → metod=%s belopp=%s fakturanr=%s status=%s",
                path.name, method, parsed["total_amount"],
                parsed["invoice_number"] or "-", status,
            )

        self._rows.extend(new_rows)
        self._refresh_table()
        ok = sum(1 for r in new_rows if not r["missing"])
        self._lbl_status.setText(
            f"{len(new_rows)} fil(er) tolkade — {ok} kompletta, "
            f"{len(new_rows) - ok} behöver kompletteras"
        )

    def _scan_pasted(self) -> None:
        """Tolkar inklistrad fakturatext (fallback utan OCR)."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
        import scan_import as si

        text = self._txt_paste.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Import", "Klistra in fakturatext i ruta 2 först."
            )
            return

        parsed = si.parse_invoice_text(text, self._suppliers())
        parsed["file"] = "(inklistrad text)"
        parsed["_path"] = ""
        parsed["method"] = "manuell text"
        parsed["_text"] = text[:4000]
        parsed["status"] = (
            "redo" if not parsed["missing"]
            else "saknas: " + ", ".join(parsed["missing"])
        )
        self._rows.append(parsed)
        self._refresh_table()
        log.info(
            "SCAN_IMPORT (inklistrad): belopp=%s fakturanr=%s",
            parsed["total_amount"], parsed["invoice_number"] or "-",
        )
        self._lbl_status.setText("Inklistrad text tolkad")

    # ══════════════════════════════════════════════════════════════════
    #  TABELL
    # ══════════════════════════════════════════════════════════════════

    def _refresh_table(self) -> None:
        self._tbl.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            for c, (_lbl, key, _w, align) in enumerate(COLUMNS):
                if key == "total_amount":
                    text = _fmt_amount(row.get(key, 0.0))
                else:
                    text = str(row.get(key, "") or "")
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    align | Qt.AlignmentFlag.AlignVCenter
                )
                if key == "status":
                    if "saknas" in text or "ingen" in text:
                        item.setForeground(
                            QApplication.palette().mid()
                        )
                    else:
                        item.setForeground(
                            QApplication.palette().link()
                        )
                self._tbl.setItem(r, c, item)
        self._update_sum()
        self._tbl.resizeRowsToContents()
        self._tbl.resizeRowsToContents()

    def _update_sum(self) -> None:
        total = sum(float(r.get("total_amount", 0.0)) for r in self._rows)
        self._lbl_sum.setText(
            f"{len(self._rows)} rad(er)  ·  summa {_fmt_amount(total)} kr"
        )

    def _selected_rows(self) -> list[int]:
        idxs = sorted({i.row() for i in self._tbl.selectedIndexes()})
        if not idxs and self._tbl.currentRow() >= 0:
            idxs = [self._tbl.currentRow()]
        return [i for i in idxs if 0 <= i < len(self._rows)]

    def _remove_row(self) -> None:
        for i in reversed(self._selected_rows()):
            self._rows.pop(i)
        self._refresh_table()

    # ══════════════════════════════════════════════════════════════════
    #  RÄTTA I FAKTURADIALOGEN
    # ══════════════════════════════════════════════════════════════════

    def _open_row_dialog(self, *_args: Any) -> None:
        """
        Öppnar den vanliga fakturadialogen förifylld med tolkade
        värden — användaren rättar och godkänner; fakturan registreras
        av dialogen (samma väg som manuell registrering).
        """
        idxs = self._selected_rows()
        if not idxs:
            QMessageBox.information(self, "Import", "Markera en rad först.")
            return
        row = self._rows[idxs[0]]
        try:
            from ui.invoices_helpers import InvoiceDialog

            sup_names = [s.get("name", "") for s in self._suppliers()]
            dlg = InvoiceDialog(
                parent=self,
                supplier_name=row.get("supplier", "") or "",
                supplier_names=sup_names,
                app_core=self._app,
            )
            if row.get("total_amount"):
                dlg.f_total.setValue(float(row["total_amount"]))
            if row.get("invoice_number"):
                dlg.f_inv_nr.setText(str(row["invoice_number"]))
            if row.get("ocr"):
                dlg.f_ocr.setText(str(row["ocr"]))
            if row.get("date"):
                from PySide6.QtCore import QDate

                qd = QDate.fromString(str(row["date"]), "yyyy-MM-dd")
                if qd.isValid():
                    dlg.f_date.setDate(qd)
            if row.get("due_date"):
                from PySide6.QtCore import QDate

                qd = QDate.fromString(str(row["due_date"]), "yyyy-MM-dd")
                if qd.isValid():
                    dlg.f_due_date.setDate(qd)

            if dlg.exec() == QDialogAccepted:
                data = dlg.get_data()
                self._save_invoice(data, source=row.get("file", ""))
                self._rows.pop(idxs[0])
                self._refresh_table()
        except Exception as exc:
            log.error("SCAN_OPEN_DIALOG: %s", exc, exc_info=True)
            QMessageBox.warning(
                self, "Import", f"Kunde inte öppna dialogen:\n{exc}"
            )

    # ══════════════════════════════════════════════════════════════════
    #  SKAPA FAKTUROR
    # ══════════════════════════════════════════════════════════════════

    def _create_invoices(self) -> None:
        """Registrerar markerade rader som fakturor (belopp → summan)."""
        idxs = self._selected_rows()
        if not idxs:
            QMessageBox.information(self, "Import", "Markera rader först.")
            return

        ready = [i for i in idxs if not self._rows[i]["missing"]]
        not_ready = [i for i in idxs if self._rows[i]["missing"]]
        if not_ready:
            QMessageBox.warning(
                self, "Import",
                "Dessa rader saknar obligatoriska uppgifter och kan inte "
                "registreras direkt:\n\n"
                + "\n".join(
                    f"• {self._rows[i]['file']}: "
                    f"{', '.join(self._rows[i]['missing'])}"
                    for i in not_ready
                )
                + "\n\nAnvänd 'Öppna i fakturadialogen' för att komplettera.",
            )
        if not ready:
            return

        created = 0
        for i in sorted(ready, reverse=True):
            row = self._rows[i]
            if not self._supplier_exists(row.get("supplier", "")):
                QMessageBox.warning(
                    self, "Import",
                    f"Leverantören '{row.get('supplier') or '(okänd)'}' "
                    f"finns inte i registret.\n\n"
                    f"Skapa leverantören först, eller använd "
                    f"'Öppna i fakturadialogen'.",
                )
                continue
            data = {
                "supplier": str(row.get("supplier", "")),
                "invoice_number": str(row.get("invoice_number", "")),
                "ocr": str(row.get("ocr", "")),
                "date": str(row.get("date", ""))
                or datetime.date.today().isoformat(),
                "due_date": str(row.get("due_date", "")),
                "payment_date": "",
                "total_amount": round(float(row.get("total_amount", 0.0)), 2),
                "vat_amount": 0.0,
                "amount_ex_vat": round(
                    float(row.get("total_amount", 0.0)), 2
                ),
                "vat_percent": 0,
                "currency": "SEK",
                "status": "Obetald",
                "category": "",
                "reference": "",
                "note": f"Importerad från {row.get('file', '')}"
                        f" ({row.get('method', '')})",
                "attachment": row.get("_path", ""),
            }
            if self._save_invoice(data, source=row.get("file", "")):
                created += 1
                self._rows.pop(i)

        self._refresh_table()
        if created:
            self._lbl_status.setText(f"{created} faktura(or) registrerade")
            QMessageBox.information(
                self, "Import",
                f"✅  {created} faktura{'r' if created != 1 else ''} "
                f"registrerade och inräknade i ATT BETALA.",
            )

    def _supplier_exists(self, name: str) -> bool:
        target = str(name or "").strip().lower()
        if not target:
            return False
        return any(
            str(s.get("name", "")).strip().lower() == target
            for s in self._suppliers()
        )

    def _save_invoice(self, data: dict, source: str = "") -> bool:
        """Sparar via app-kärnan (samma väg som manuell registrering)."""
        try:
            if self._app is None:
                QMessageBox.warning(self, "Import", "App-kärnan saknas.")
                return False
            rec = self._app.add_invoice(data)
            log.info(
                "SCAN_CREATE: faktura skapad från %s → id=%s nummer=%s "
                "belopp=%s",
                source or "(dialog)",
                rec.get("id", "?"),
                rec.get("invoice_number", "?"),
                rec.get("total_amount"),
            )
            return True
        except Exception as exc:
            log.error("SCAN_CREATE misslyckades: %s", exc, exc_info=True)
            QMessageBox.warning(
                self, "Import", f"Kunde inte spara fakturan:\n{exc}"
            )
            return False

    # ══════════════════════════════════════════════════════════════════
    #  TEMA
    # ══════════════════════════════════════════════════════════════════

    def apply_theme(self, theme: dict) -> None:
        """Anpassar små detaljer efter aktivt tema."""
        try:
            bg = str(theme.get("bg", "#0d1117")).lower()
            self._dark = bg not in (
                "#ffffff", "#f6f8fa", "#eaeef2", "#f5f7fa",
            )
        except Exception:
            pass


#: importeras sent för att undvika cirkulär import vid modulladdning
try:
    from PySide6.QtWidgets import QDialog

    QDialogAccepted = QDialog.DialogCode.Accepted
except Exception:  # pragma: no cover
    QDialogAccepted = 1
