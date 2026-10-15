from __future__ import annotations

"""
Fakturabunten — Invoices View
=====================================
Fil    : Fakturabunten_/ui/invoices_view.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Huvudvy för leverantörsfakturor.

Funktioner
----------
• Persistent leverantörsväljare (dropdown, stannar kvar tills man byter)
• Förenklad registrering: fakturanummer + belopp (+/−)
• Betalningsdatum per export-batch (frågas ALLTID innan varje export)
• Exportera ALLA aktiva fakturor till PDF
• ATT BETALA visas tydligt (Fakturor + / Krediter − / NETTO)
• Export sparas i exports/<Leverantör>/<YYYY-MM-DD>/
• Exporterad PDF öppnas automatiskt
• Knapp för att öppna exportmappen
• Historik med möjlighet att återställa export
• Arkiverade fakturor döljs i standardvyn men kan visas via filter
• Sök + filter (typ / status / leverantör) med debounce
• Tema-anpassning för dark / light / auto / system
• Mushjul-scroll fungerar direkt på tabellen
• Dynamisk fönsterstorlek, responsivt UI
• Multi-OS: Windows / Linux / macOS

Betalningsdatum per export
--------------------------
• Innan varje export visas ask_export_payment_date() som frågar
  om betalningsdatum JUST FÖR DENNA export-batch.
• session_due_date (från main.py) används som default i dialogen.
• Användaren bekräftar → datumet visas i PDF och sparas i historik.
• Användaren avbryter → export avbryts.
• Datumet nollställs automatiskt efter exporten.
• Nästa export → frågar igen.

Samarbetar med
--------------
• main.py / ui/main_window.py      – MainWindow (laddas som builtin-vy)
• app.py                           – FakturaApp (data, CRUD, settings,
                                     session_due_date, session_due_date_str)
• ui/invoices_helpers.py           – hjälpklasser, dialoger, konstanter,
                                     get_session_due_date_str()
• ui/suppliers_view.py             – leverantörshantering
• plugins/pdf_export.py            – PDF-export (export_invoice_list)
• plugins/pdf_export_helpers.py    – ask_export_payment_date()
• plugins/advanced_logger.py       – loggning

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import logging
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QLineEdit,
    QComboBox,
    QTableWidget,
    QHeaderView,
    QAbstractItemView,
    QAbstractScrollArea,
    QMenu,
    QMessageBox,
    QCompleter,
    QDialog,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal, QSize, QItemSelectionModel

try:
    from ui.i18n import tr, tr_list, tr_status, tr_type
except ImportError:  # fristående körning av filen
    from i18n import tr, tr_list, tr_status, tr_type  # type: ignore[no-redef]
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QWheelEvent

# ═════════════════════════════════════════════════════════════════════
#  IMPORTER FRÅN HELPERS
# ═════════════════════════════════════════════════════════════════════

try:
    from ui.invoices_helpers import (
        INVOICE_STATUSES,
        HIDDEN_STATUSES,
        STATUS_COLORS,
        COLUMNS,
        COL_LABELS,
        COL_KEYS,
        COL_WIDTHS,
        COL_ALIGN,
        ExportHistoryManager,
        ExportHistoryDialog,
        InvoiceDialog,
        due_within,
        due_window_filter,
        payment_info_text,
        is_dark_theme,
        make_btn,
        make_cell,
        make_font,
        h_line,
        fit_table_columns,
        fmt_amount,
        combine_invoices,
        build_export_path,
        get_export_base,
        open_file,
        open_folder,
        get_session_due_date_str,
        COPYRIGHT_YEAR,
    )
except ImportError:
    from invoices_helpers import (  # type: ignore[no-redef]
        INVOICE_STATUSES,
        HIDDEN_STATUSES,
        STATUS_COLORS,
        COLUMNS,
        COL_LABELS,
        COL_KEYS,
        COL_WIDTHS,
        COL_ALIGN,
        ExportHistoryManager,
        ExportHistoryDialog,
        InvoiceDialog,
        due_within,
        due_window_filter,
        payment_info_text,
        make_btn,
        make_cell,
        make_font,
        h_line,
        fit_table_columns,
        fmt_amount,
        combine_invoices,
        build_export_path,
        get_export_base,
        open_file,
        open_folder,
        get_session_due_date_str,
        COPYRIGHT_YEAR,
    )

try:
    from ui.design import ICON_HEADER_PX, app_icon_pixmap
except Exception:  # pragma: no cover - fristående körning
    try:
        from design import ICON_HEADER_PX, app_icon_pixmap  # type: ignore[no-redef]
    except Exception:
        ICON_HEADER_PX = 28  # type: ignore[no-redef]

        def app_icon_pixmap(size: int = 28):  # type: ignore[no-redef]
            from PySide6.QtGui import QPixmap as _QP
            return _QP()

log = logging.getLogger("InvoicesView")

#: Fält som snabbsökningen omfattar.
SEARCH_FIELDS: tuple[str, ...] = (
    "supplier",
    "invoice_number",
    "ocr",
    "reference",
    "note",
    "category",
    "invoice_type",
    "payment_date",
)

#: Statusar som inte räknas som obetalda.
NON_UNPAID_STATUSES: tuple[str, ...] = ("Betald", "Makulerad", "Arkiverad")

#: Radfärgkodning per status: (mörkt tema, ljust tema).
#: Hela raden färgas — snabb överblick (röd/gul/grön-principen).
STATUS_ROW_BG: dict[str, tuple[str, str]] = {
    "Obetald":         ("#332b00", "#fff8e1"),
    "Planerad":        ("#0d2b4a", "#e3f2fd"),
    "Betalfil skapad": ("#2a1a3a", "#f3e5f5"),
    "Betald":          ("#0f2e17", "#e8f5e9"),
    "Förfallen":       ("#3b1113", "#fdecea"),
    "Makulerad":       ("#232323", "#eeeeee"),
    "Arkiverad":       ("#102a2e", "#e0f7fa"),
}


# ═════════════════════════════════════════════════════════════════════
#  HJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def _to_float(value: Any, default: float = 0.0) -> float:
    """Säker float-konvertering."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_ask_export_payment_date():
    """
    Laddar ask_export_payment_date() från pdf_export_helpers.

    Prövar i ordning:
        1. from plugins.pdf_export_helpers import …
        2. from pdf_export_helpers import …
        3. Direkt filimport via importlib

    Returnerar funktionen eller None om den inte kan laddas.
    """
    try:
        from plugins.pdf_export_helpers import ask_export_payment_date

        return ask_export_payment_date
    except ImportError:
        pass

    try:
        from pdf_export_helpers import ask_export_payment_date  # type: ignore

        return ask_export_payment_date
    except ImportError:
        pass

    # Tredje försök: direkt filimport
    try:
        import importlib.util

        candidate = (
            Path(__file__).parent.parent
            / "plugins"
            / "pdf_export_helpers.py"
        )
        if candidate.exists():
            spec = importlib.util.spec_from_file_location(
                "pdf_export_helpers", str(candidate)
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore
                fn = getattr(mod, "ask_export_payment_date", None)
                if fn is not None:
                    return fn
    except Exception:
        pass

    return None


# ═════════════════════════════════════════════════════════════════════
#  INVOICES VIEW
# ═════════════════════════════════════════════════════════════════════


class InvoicesView(QWidget):
    """
    Huvudvy för leverantörsfakturor.

    Flöde
    ─────
    1. Välj leverantör i dropdown (stannar kvar tills du byter).
    2. Registrera faktura via förenklad dialog (fakturanummer + belopp).
    3. Exportera ALLA aktiva fakturor till PDF.
       → Betalningsdatum frågas ALLTID innan export via dialog.
       → session_due_date används som default i dialogen.
       → Datumet nollställs automatiskt efter exporten.
    4. Efter export sätts status till Arkiverad.
    5. Exporthistorik sparas och kan återställas.
    """

    invoice_selected = Signal(dict)

    def __init__(
        self, app: Any, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._all_data: list[dict] = []
        self._undo_stack: list[list[tuple[str, str, str]]] = []
        self._chip_mode: str = ""  # snabbfilter: "" / overdue / today / week
        self._current_theme: dict = {}
        self._favorite_names: set[str] = set()
        self._initialised = False

        # Debounce-timer för sökning / filter (220 ms)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self._do_refresh)

        # Exporthistorik
        try:
            data_dir = Path(self._app.settings.get("db_path", "data"))
        except Exception:
            data_dir = Path("data")
        if not data_dir.is_absolute():
            data_dir = Path(__file__).parent.parent / data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self._export_history = ExportHistoryManager(data_dir)

        # Bygg UI + initial data
        self._build_ui()

        # Ångra senaste statusändringen med Ctrl+Z
        self._sc_undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._sc_undo.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._sc_undo.activated.connect(self._undo_last_status)

        self._do_refresh()

        # Lyssna på dataändringar (säker koppling)
        self._connect_store("invoices_store")
        self._connect_store("suppliers_store")

        self._initialised = True
        log.info("InvoicesView initialiserad")

    # ── Säker store-koppling ─────────────────────────────────────────────

    def _connect_store(self, store_name: str) -> None:
        """Kopplar on_change-callback till en DataStore om den finns."""
        try:
            store = getattr(self._app, store_name, None)
            if store is not None and hasattr(store, "on_change"):
                store.on_change(self._on_store_changed)
                log.debug("Kopplad till %s.on_change", store_name)
        except Exception as exc:
            log.debug("Kunde inte koppla %s: %s", store_name, exc)

    # ══════════════════════════════════════════════════════════════════
    #  UI-BYGGNAD
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 4)
        root.setSpacing(6)
        self.setMinimumWidth(0)

        # ── Header ─────────────────────────────────────────────────────
        self._header_label = QLabel(tr("invoices.title"))
        self._header_label.setFont(make_font(17, True))
        head = QHBoxLayout()
        head.setSpacing(8)
        _pix = app_icon_pixmap(ICON_HEADER_PX)
        if not _pix.isNull():
            mark = QLabel()
            mark.setPixmap(_pix)
            mark.setStyleSheet("background:transparent;")
            head.addWidget(mark)
        head.addWidget(self._header_label)
        head.addStretch()
        root.addLayout(head)
        root.addWidget(h_line())

        # ── Leverantörsväljare (persistent) ────────────────────────────
        supplier_frame = QFrame()
        supplier_frame.setObjectName("SupplierBar")
        supplier_layout = QHBoxLayout(supplier_frame)
        supplier_layout.setContentsMargins(10, 8, 10, 8)
        supplier_layout.setSpacing(10)

        lbl_sup = QLabel(tr("invoices.choose_supplier"))
        self._lbl_sup = lbl_sup
        lbl_sup.setFont(make_font(12, True))
        lbl_sup.setStyleSheet("background:transparent;")

        self._sup_selector = QComboBox()
        self._sup_selector.setMinimumHeight(40)
        self._sup_selector.setMinimumWidth(160)
        self._sup_selector.setFont(make_font(13, True))
        self._sup_selector.setEditable(True)
        self._sup_selector.setPlaceholderText(tr("invoices.choose_ph"))
        self._sup_selector.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._sup_selector.currentTextChanged.connect(
            self._on_supplier_selector_changed
        )

        self._lbl_supplier_info = QLabel("")
        self._lbl_supplier_info.setFont(make_font(10))
        self._lbl_supplier_info.setStyleSheet(
            "color:#718096;background:transparent;"
        )

        supplier_layout.addWidget(lbl_sup)
        supplier_layout.addWidget(self._sup_selector, stretch=1)
        supplier_layout.addWidget(self._lbl_supplier_info)
        supplier_layout.addStretch()
        root.addWidget(supplier_frame)

        # ── Sök + filter ───────────────────────────────────────────────
        row_search = QHBoxLayout()
        row_search.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("invoices.search_ph"))
        self._search.setMinimumHeight(38)
        self._search.setFont(make_font(12))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(
            lambda *_: self._search_timer.start()
        )

        self._filter_type = QComboBox()
        self._filter_type.setMinimumHeight(38)
        self._filter_type.setMinimumWidth(0)
        self._filter_type.setFont(make_font(12))
        self._filter_type.addItem(tr("invoices.all_types"), "")
        self._filter_type.addItem(tr_type("Faktura"), "Faktura")
        self._filter_type.addItem(tr_type("Kreditfaktura"), "Kreditfaktura")
        self._filter_type.currentTextChanged.connect(
            lambda *_: self._search_timer.start()
        )

        self._filter_status = QComboBox()
        self._filter_status.setMinimumHeight(38)
        self._filter_status.setMinimumWidth(0)
        self._filter_status.setFont(make_font(12))
        self._filter_status.addItem(tr("invoices.active_only"), "__active__")
        self._filter_status.addItem(tr("invoices.all_statuses"), "__all__")
        for _st in INVOICE_STATUSES:
            self._filter_status.addItem(tr_status(_st), _st)
        self._filter_status.currentTextChanged.connect(
            lambda *_: self._search_timer.start()
        )

        self._filter_supplier = QComboBox()
        self._filter_supplier.setMinimumHeight(38)
        self._filter_supplier.setMinimumWidth(0)
        self._filter_supplier.setFont(make_font(12))
        self._filter_supplier.addItem(tr("invoices.all_suppliers"), "")
        self._filter_supplier.currentTextChanged.connect(
            lambda *_: self._search_timer.start()
        )

        row_search.addWidget(self._search, stretch=1)
        row_search.addWidget(self._filter_type)
        row_search.addWidget(self._filter_status)
        row_search.addWidget(self._filter_supplier)
        root.addLayout(row_search)

        # ── Snabbfilter-chips: förfallofönster ──────────────────────
        row_chips = QHBoxLayout()
        row_chips.setSpacing(8)
        self._chip_btns: dict[str, Any] = {}
        for mode, key in (
            ("overdue", "invoices.chip_overdue"),
            ("today", "invoices.chip_today"),
            ("week", "invoices.chip_week"),
        ):
            chip = make_btn(tr(key), tr(key))
            chip.setCheckable(True)
            chip.clicked.connect(
                lambda _checked=False, m=mode: self._on_chip(m)
            )
            self._chip_btns[mode] = chip
            row_chips.addWidget(chip)
        row_chips.addStretch()
        root.addLayout(row_chips)

        # ── CRUD-knappar ───────────────────────────────────────────────
        row_actions = QHBoxLayout()
        row_actions.setSpacing(8)

        self._btn_add = make_btn(
            tr("invoices.add"),
            "Registrera faktura för vald leverantör",
            accent=True,
        )
        self._btn_add.clicked.connect(self._add_invoice)

        self._btn_edit = make_btn(
            tr("invoices.edit"), "Redigera markerad faktura"
        )
        self._btn_edit.clicked.connect(self._edit_invoice)
        self._btn_edit.setEnabled(False)

        self._btn_delete = make_btn(
            tr("invoices.delete"), "Ta bort markerad faktura", danger=True
        )
        self._btn_delete.clicked.connect(self._delete_invoice)
        self._btn_delete.setEnabled(False)

        self._btn_duplicate = make_btn(
            tr("invoices.duplicate"), "Duplicera markerad faktura"
        )
        self._btn_duplicate.clicked.connect(self._duplicate_invoice)
        self._btn_duplicate.setEnabled(False)

        self._btn_mark_paid = make_btn(
            tr("invoices.mark_paid"),
            "Markera markerade fakturor som betalda",
            success=True,
        )
        self._btn_mark_paid.clicked.connect(self._mark_selected_paid)
        self._btn_mark_paid.setEnabled(False)

        self._btn_combine = make_btn(
            tr("combine.button"),
            tr("combine.tip"),
            info=True,
        )
        self._btn_combine.clicked.connect(self._show_combine_dialog)
        self._btn_combine.setEnabled(False)

        row_actions.addWidget(self._btn_add)
        row_actions.addWidget(self._btn_edit)
        row_actions.addWidget(self._btn_delete)
        row_actions.addWidget(self._btn_duplicate)
        row_actions.addWidget(self._btn_mark_paid)
        row_actions.addWidget(self._btn_combine)

        self._btn_pay_today = make_btn(
            tr("invoices.pay_today"),
            tr("invoices.pay_today_tip"),
            success=True,
        )
        self._btn_pay_today.clicked.connect(self._pay_today)
        row_actions.addWidget(self._btn_pay_today)
        row_actions.addStretch()

        self._btn_refresh = make_btn("🔄", "Uppdatera vyn", width=50)
        self._btn_refresh.clicked.connect(self._do_refresh)
        row_actions.addWidget(self._btn_refresh)

        self._btn_undo = make_btn(
            "↩", tr("invoices.undo_tip"), width=50
        )
        self._btn_undo.clicked.connect(self._undo_last_status)
        row_actions.addWidget(self._btn_undo)
        root.addLayout(row_actions)

        # ── Export-rad ─────────────────────────────────────────────────
        row_export = QHBoxLayout()
        row_export.setSpacing(10)

        self._btn_export_all = make_btn(
            tr("invoices.export_all"),
            "Exportera alla aktiva fakturor till PDF-fil\n"
            "Du tillfrågas om betalningsdatum innan export.",
            info=True,
        )
        self._btn_export_all.clicked.connect(self._export_all_pdf)

        self._btn_history = make_btn(
            tr("invoices.history"),
            "Visa tidigare exporter och återställ vid behov",
        )
        self._btn_history.clicked.connect(self._show_history)

        self._btn_open_export = make_btn(
            tr("invoices.open_export_folder"),
            "Öppna exports/-mappen i filhanteraren",
        )
        self._btn_open_export.clicked.connect(
            lambda: open_folder(get_export_base())
        )

        self._lbl_history_count = QLabel("")
        self._lbl_history_count.setFont(make_font(10))
        self._lbl_history_count.setStyleSheet(
            "color:#888;background:transparent;"
        )

        row_export.addWidget(self._btn_export_all)
        row_export.addWidget(self._btn_history)
        row_export.addWidget(self._btn_open_export)
        row_export.addWidget(self._lbl_history_count)
        row_export.addStretch()
        root.addLayout(row_export)

        # ── Summering: tre beloppskort ─────────────────────────────────
        summary_frame = QFrame()
        summary_frame.setObjectName("SummaryStrip")
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(0, 2, 0, 2)
        summary_layout.setSpacing(10)

        def _money_card(name: str, caption: str, value: QLabel) -> QFrame:
            card = QFrame()
            card.setObjectName(name)
            lay = QVBoxLayout(card)
            lay.setContentsMargins(14, 8, 14, 8)
            lay.setSpacing(0)
            cap = QLabel(caption)
            cap.setObjectName("MoneyCaption")
            self._money_caps[name] = cap
            cap.setFont(make_font(11, True))
            value.setFont(make_font(16, True))
            value.setObjectName("MoneyValue")
            lay.addWidget(cap)
            lay.addWidget(value)
            return card

        self._money_caps: dict[str, QLabel] = {}
        self._lbl_invoices = QLabel("0,00 SEK")
        self._lbl_credits = QLabel("0,00 SEK")
        self._lbl_att_betala = QLabel("0,00 SEK")
        summary_layout.addWidget(
            _money_card("MoneyCard", tr("invoices.card_invoices"), self._lbl_invoices), 1
        )
        summary_layout.addWidget(
            _money_card("MoneyCardCredit", tr("invoices.card_credits"), self._lbl_credits), 1
        )
        summary_layout.addWidget(
            _money_card("MoneyCardTotal", tr("invoices.card_total"), self._lbl_att_betala), 1
        )
        self._cap_invoices = self._money_caps.get("MoneyCard")
        self._cap_credits = self._money_caps.get("MoneyCardCredit")
        self._cap_total = self._money_caps.get("MoneyCardTotal")

        meta = QVBoxLayout()
        meta.setSpacing(2)
        self._lbl_count = QLabel("Poster: 0")
        self._lbl_unpaid = QLabel("Obetalt: 0,00 SEK")
        self._lbl_overdue = QLabel("Förfallet: 0,00 SEK")
        for lbl in (self._lbl_count, self._lbl_unpaid, self._lbl_overdue):
            lbl.setFont(make_font(11, True))
            lbl.setStyleSheet("background:transparent;")
            meta.addWidget(lbl)
        meta.addStretch()
        summary_layout.addLayout(meta)
        root.addWidget(summary_frame)

        # Beständig rad: markeringens summa (eller totalen att betala).
        # Ersätter den kortlivade statusradstexten så summan av det
        # man markerat alltid syns medan man arbetar.
        self._lbl_selection = QLabel("")
        self._lbl_selection.setFont(make_font(12, True))
        self._lbl_selection.setStyleSheet("background:transparent;")
        root.addWidget(self._lbl_selection)

        # ── Tabell ─────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(len(COLUMNS))
        _headers = tr_list("invoices.columns")
        self._table.setHorizontalHeaderLabels(
            _headers if len(_headers) == len(COLUMNS) else COL_LABELS
        )
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(False)
        self._table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._table.setMinimumWidth(0)
        self._table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._table.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self._table.setShowGrid(True)
        self._table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.itemSelectionChanged.connect(
            self._on_selection_changed
        )
        self._table.doubleClicked.connect(self._edit_invoice)
        self._table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(36)
        hh.setTextElideMode(Qt.TextElideMode.ElideRight)
        full = {
            "Fakturanr": "Fakturanummer",
            "Förfaller": "Förfallodatum",
            "Betaldatum": "Betalningsdatum",
            "Notering": "Anteckning",
        }
        for i, label in enumerate(COL_LABELS):
            item = self._table.horizontalHeaderItem(i)
            if item is not None:
                item.setToolTip(full.get(label, label))
        QTimer.singleShot(0, self._fit_columns)
        self._table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        # Mushjul-scroll direkt på tabellen
        self._table.wheelEvent = self._table_wheel  # type: ignore

        root.addWidget(self._table, stretch=1)

        # ── Footer ─────────────────────────────────────────────────────
        root.addWidget(h_line())
        self._footer = QLabel(
            f"© {COPYRIGHT_YEAR} Rickard Längkvist"
            f"  —  Fakturabunten"
        )
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._footer.setFont(make_font(9))
        self._footer.setStyleSheet(
            "background:transparent;color:#718096;"
        )
        root.addWidget(self._footer)

    def _table_wheel(self, event: QWheelEvent) -> None:
        """Mushjul-scroll i tabellen."""
        sb = self._table.verticalScrollBar()
        sb.setValue(sb.value() - (event.angleDelta().y() // 40))
        event.accept()

    # ══════════════════════════════════════════════════════════════════
    #  DATA / REFRESH
    # ══════════════════════════════════════════════════════════════════

    def _on_store_changed(self, *_args: Any) -> None:
        """Callback från DataStore.on_change() — triggar refresh."""
        QTimer.singleShot(50, self._do_refresh)

    def _do_refresh(self) -> None:
        """Hämtar data, uppdaterar väljare, filter, tabell och summering."""
        try:
            raw = self._app.get_invoices()
            self._all_data = list(raw) if raw else []
        except Exception as exc:
            log.error("refresh error: %s", exc)
            self._all_data = []

        self._refresh_supplier_selector()
        self._update_filter_supplier_combo()

        filtered = self._apply_filters()
        self._populate_table(filtered)
        self._update_summary(filtered)
        self._update_export_buttons()

    def _get_exportable(self) -> list[dict]:
        """Alla fakturor som är aktiva (ej arkiverade/makulerade)."""
        return [
            r
            for r in self._all_data
            if r.get("status") not in HIDDEN_STATUSES
        ]

    def _include_originals(self) -> bool:
        """Inställningen export_include_originals (standard: av)."""
        try:
            if hasattr(self._app, "get_setting"):
                return bool(
                    self._app.get_setting(
                        "export_include_originals", False
                    )
                )
            return bool(
                self._app.settings.get(
                    "export_include_originals", False
                )
            )
        except Exception:
            return False

    def _update_export_buttons(self) -> None:
        """Uppdaterar exportknapp + historikräknare."""
        exportable = self._get_exportable()
        n = len(exportable)
        self._btn_export_all.setEnabled(n > 0)
        self._btn_export_all.setText(
            tr("invoices.export_all_n", n=n)
            if n > 0
            else tr("invoices.export_none")
        )
        hist_count = self._export_history.count()
        self._lbl_history_count.setText(
            tr("invoices.history_count", n=hist_count)
        )

    # ══════════════════════════════════════════════════════════════════
    #  FILTER
    # ══════════════════════════════════════════════════════════════════

    def _apply_filters(self) -> list[dict]:
        """Applicerar sök + typ/status/leverantörs-filter."""
        query = self._search.text().strip().lower()
        type_f = self._filter_type.currentData() or ""
        status_f = self._filter_status.currentData() or ""
        sup_f = self._filter_supplier.currentData()
        if sup_f is None:
            sup_f = self._filter_supplier.currentText()

        data = list(self._all_data)

        # Status-filter (kanoniska värden via itemData)
        if status_f == "__active__":
            data = [
                r
                for r in data
                if r.get("status") not in HIDDEN_STATUSES
            ]
        elif status_f and status_f != "__all__":
            data = [r for r in data if r.get("status") == status_f]

        # Fritextsökning
        if query:
            data = [
                r
                for r in data
                if any(
                    query in str(r.get(k, "")).lower()
                    for k in SEARCH_FIELDS
                )
            ]

        # Typ-filter
        if type_f == "Kreditfaktura":
            data = [
                r
                for r in data
                if r.get("invoice_type") == "Kreditfaktura"
                or _to_float(r.get("total_amount")) < 0
            ]
        elif type_f == "Faktura":
            data = [
                r
                for r in data
                if r.get("invoice_type", "Faktura") == "Faktura"
                and _to_float(r.get("total_amount")) >= 0
            ]

        # Leverantörs-filter ("" = alla; annars leverantörens namn)
        if sup_f:
            data = [r for r in data if r.get("supplier") == sup_f]

        # Snabbfilter (chips): förfallofönster ovanpå övriga filter
        mode = getattr(self, "_chip_mode", "")
        if mode:
            data = due_window_filter(data, mode, datetime.date.today())

        return data

    # ══════════════════════════════════════════════════════════════════
    #  SNABBFILTER-CHIPS
    # ══════════════════════════════════════════════════════════════════

    def _on_chip(self, mode: str) -> None:
        """Växlar snabbfilter — samma chip igen stänger av filtret."""
        self._chip_mode = "" if self._chip_mode == mode else mode
        self._sync_chip_styles()
        self._do_refresh()

    def _sync_chip_styles(self) -> None:
        """Aktivt chip i guld (syns i både ljust och mörkt tema)."""
        for mode, btn in getattr(self, "_chip_btns", {}).items():
            active = mode == self._chip_mode
            btn.setChecked(active)
            btn.setStyleSheet(
                "background:#d4a017;color:#111111;font-weight:800;"
                if active
                else ""
            )

    # ══════════════════════════════════════════════════════════════════
    #  LEVERANTÖRSVÄLJARE
    # ══════════════════════════════════════════════════════════════════

    def _refresh_supplier_selector(self) -> None:
        """
        Uppdaterar leverantörs-dropdownen (bevarar aktuellt val).

        Favoriter (favorite=True i leverantörsregistret) hamnar
        ALLTID överst i listan.
        """
        current = self._sup_selector.currentText()
        try:
            suppliers = self._app.get_suppliers()
        except Exception:
            suppliers = []
        favorites = sorted(
            s.get("name", "")
            for s in suppliers
            if s.get("name") and s.get("favorite")
        )
        others = sorted(
            s.get("name", "")
            for s in suppliers
            if s.get("name") and not s.get("favorite")
        )
        self._favorite_names = set(favorites)
        names = favorites + others

        self._sup_selector.blockSignals(True)
        self._sup_selector.clear()
        self._sup_selector.addItem("")
        self._sup_selector.addItems(names)

        completer = QCompleter(names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._sup_selector.setCompleter(completer)

        idx = self._sup_selector.findText(current)
        self._sup_selector.setCurrentIndex(max(idx, 0))
        self._sup_selector.blockSignals(False)

        self._on_supplier_selector_changed(
            self._sup_selector.currentText()
        )

    def _on_supplier_selector_changed(self, name: str) -> None:
        """Visar leverantörsinfo (org.nr, BG/PG/IBAN) bredvid väljaren."""
        name = name.strip()
        if not name:
            self._lbl_supplier_info.setText(tr("invoices.none_chosen"))
            return

        try:
            suppliers = self._app.get_suppliers()
            sup = next(
                (
                    s
                    for s in suppliers
                    if s.get("name", "").strip() == name
                ),
                None,
            )
            if sup:
                parts: list[str] = []
                if sup.get("favorite"):
                    parts.append(tr("invoices.favorite"))
                if sup.get("org_number"):
                    parts.append(sup["org_number"])
                if sup.get("bg"):
                    parts.append(f"BG {sup['bg']}")
                if sup.get("pg"):
                    parts.append(f"PG {sup['pg']}")
                if sup.get("iban"):
                    parts.append(f"IBAN {sup['iban'][:12]}…")
                self._lbl_supplier_info.setText(
                    "  |  ".join(parts) if parts else ""
                )
            else:
                self._lbl_supplier_info.setText("")
        except Exception:
            self._lbl_supplier_info.setText("")

    @property
    def _selected_supplier(self) -> str:
        """Aktuellt valt leverantörsnamn."""
        return self._sup_selector.currentText().strip()

    def _update_filter_supplier_combo(self) -> None:
        """Uppdaterar leverantörs-filtret (bevarar aktuellt val)."""
        current = self._filter_supplier.currentText()
        names = sorted(
            {
                r.get("supplier", "")
                for r in self._all_data
                if r.get("supplier")
            }
        )
        self._filter_supplier.blockSignals(True)
        self._filter_supplier.clear()
        self._filter_supplier.addItem(tr("invoices.all_suppliers"), "")
        self._filter_supplier.addItems(names)
        idx = self._filter_supplier.findText(current)
        if idx >= 0:
            self._filter_supplier.setCurrentIndex(idx)
        self._filter_supplier.blockSignals(False)

    # ══════════════════════════════════════════════════════════════════
    #  TABELL
    # ══════════════════════════════════════════════════════════════════

    def _populate_table(self, data: list[dict]) -> None:
        """Ritar tabellen med statusfärger och kredit-markering."""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(data))
        dark = self._is_dark()

        for row, inv in enumerate(data):
            for col, key in enumerate(COL_KEYS):
                raw = inv.get(key, "")
                align = COL_ALIGN[col]

                if key == "total_amount":
                    val = _to_float(raw)
                    text = fmt_amount(val, "").strip()
                elif key == "invoice_type":
                    text = tr_type(str(raw) if raw else "Faktura")
                elif key == "status":
                    text = tr_status(str(raw)) if raw else ""
                else:
                    text = str(raw) if raw not in ("", None) else ""

                fg = ""
                if key == "status":
                    pair = STATUS_COLORS.get(str(raw or ""), ("", ""))
                    fg = pair[0] if dark else pair[1]
                elif key == "invoice_type" and str(raw) == "Kreditfaktura":
                    fg = "#64b5f6" if dark else "#1565c0"
                elif key == "total_amount" and _to_float(raw) < 0:
                    fg = "#64b5f6" if dark else "#1565c0"

                item = make_cell(
                    text,
                    align,
                    bold=True,
                    fg=fg,
                    numeric=key == "total_amount",
                )
                item.setData(Qt.ItemDataRole.UserRole, inv.get("id", ""))
                if text:
                    item.setToolTip(text)
                self._table.setItem(row, col, item)

            # Radfärgkodning på HELA raden enligt status
            pair = STATUS_ROW_BG.get(str(inv.get("status", "")))
            if pair:
                row_bg = QColor(pair[0] if dark else pair[1])
                for col in range(len(COL_KEYS)):
                    cell = self._table.item(row, col)
                    if cell is not None:
                        cell.setBackground(row_bg)

        self._table.setSortingEnabled(True)
        self._table.resizeRowsToContents()
        self._fit_columns()
        self._update_buttons()

    def _fit_columns(self) -> None:
        fit_table_columns(self._table, COL_WIDTHS)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_columns()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_columns)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 200)

    # ══════════════════════════════════════════════════════════════════
    #  SUMMERING
    # ══════════════════════════════════════════════════════════════════

    def _update_summary(self, rows: list[dict]) -> None:
        """Uppdaterar summeringsraden: Fakturor + / Krediter − / NETTO."""
        total_invoices = 0.0
        total_credits = 0.0
        unpaid = 0.0
        overdue = 0.0

        for r in rows:
            val = _to_float(r.get("total_amount"))
            if val > 0:
                total_invoices += val
            elif val < 0:
                total_credits += val

            status = r.get("status", "")
            if status not in NON_UNPAID_STATUSES:
                unpaid += val
            if status == "Förfallen":
                overdue += val

        att_betala = round(total_invoices + total_credits, 2)

        n_inv = sum(
            1 for r in rows if _to_float(r.get("total_amount")) >= 0
        )
        n_cre = len(rows) - n_inv

        if len(rows) != len(self._all_data):
            count_label = tr(
                "invoices.rows_of", shown=len(rows),
                total=len(self._all_data), f=n_inv, k=n_cre,
            )
        else:
            count_label = tr(
                "invoices.rows", n=len(rows), f=n_inv, k=n_cre
            )

        self._lbl_count.setText(count_label)
        self._lbl_invoices.setText(fmt_amount(total_invoices))
        self._lbl_credits.setText(fmt_amount(total_credits))
        self._lbl_att_betala.setText(fmt_amount(att_betala))
        self._lbl_unpaid.setText(
            tr("invoices.unpaid", amount=fmt_amount(unpaid))
        )
        self._lbl_overdue.setText(
            tr("invoices.overdue", amount=fmt_amount(overdue))
        )
        self._refresh_selection_label()

    # ══════════════════════════════════════════════════════════════════
    #  MARKERING
    # ══════════════════════════════════════════════════════════════════

    def _on_selection_changed(self) -> None:
        self._update_buttons()
        inv = self._selected_invoice()
        if inv:
            self.invoice_selected.emit(inv)

    def _update_buttons(self) -> None:
        single = self._selected_id() is not None
        ids = self._selected_ids()
        multi = len(ids) > 0
        self._btn_edit.setEnabled(single)
        self._btn_delete.setEnabled(single)
        self._btn_duplicate.setEnabled(single)
        self._btn_mark_paid.setEnabled(multi)
        self._btn_combine.setEnabled(len(ids) >= 2)
        if len(ids) >= 2:
            summary = combine_invoices(self._selected_invoices())
            if summary["earliest_due"]:
                self._status(
                    tr(
                        "combine.status",
                        n=summary["count"],
                        amount=fmt_amount(summary["net"]),
                        due=summary["earliest_due"],
                    ),
                    timeout=6000,
                )
            else:
                self._status(
                    tr(
                        "combine.status_no_due",
                        n=summary["count"],
                        amount=fmt_amount(summary["net"]),
                    ),
                    timeout=6000,
                )
        self._refresh_selection_label()

    def _selected_id(self) -> str | None:
        items = self._table.selectedItems()
        if not items:
            return None
        uid = items[0].data(Qt.ItemDataRole.UserRole)
        return uid if uid else None

    def _selected_ids(self) -> list[str]:
        """Unika id:n för alla markerade rader (ordningsbevarande)."""
        seen: set[str] = set()
        ids: list[str] = []
        for item in self._table.selectedItems():
            rid = item.data(Qt.ItemDataRole.UserRole)
            if rid and rid not in seen:
                seen.add(rid)
                ids.append(rid)
        return ids

    def _selected_invoices(self) -> list[dict]:
        """Alla markerade fakturor (i markeringsordning)."""
        by_id = {r.get("id"): r for r in self._all_data}
        return [
            by_id[i] for i in self._selected_ids() if i in by_id
        ]

    def _selected_invoice(self) -> dict | None:
        sid = self._selected_id()
        if not sid:
            return None
        return next(
            (r for r in self._all_data if r.get("id") == sid), None
        )

    # ══════════════════════════════════════════════════════════════════
    #  HJÄLPARE
    # ══════════════════════════════════════════════════════════════════

    def _supplier_names_list(self) -> list[str]:
        """Sorterade leverantörsnamn från appen."""
        try:
            suppliers = self._app.get_suppliers()
            if suppliers:
                return sorted(
                    s.get("name", "")
                    for s in suppliers
                    if s.get("name")
                )
        except Exception as exc:
            log.debug("_supplier_names_list: %s", exc)
        return []

    def _default_currency(self) -> str:
        """Standardvaluta från settings."""
        try:
            return self._app.get_setting("currency") or "SEK"
        except Exception:
            try:
                return self._app.settings.get("currency", "SEK")
            except Exception:
                return "SEK"

    def _is_dark(self) -> bool:
        """True om aktuellt tema är mörkt (temanamn → luminans)."""
        return is_dark_theme(self._current_theme)

    def retranslate(self) -> None:
        """Uppdaterar vyns texter efter språkbyte (utan omstart)."""
        self._header_label.setText(tr("invoices.title"))
        self._lbl_sup.setText(tr("invoices.choose_supplier"))
        self._sup_selector.setPlaceholderText(tr("invoices.choose_ph"))
        self._search.setPlaceholderText(tr("invoices.search_ph"))
        self._btn_add.setText(tr("invoices.add"))
        self._btn_edit.setText(tr("invoices.edit"))
        self._btn_delete.setText(tr("invoices.delete"))
        self._btn_duplicate.setText(tr("invoices.duplicate"))
        self._btn_mark_paid.setText(tr("invoices.mark_paid"))
        self._btn_pay_today.setText(tr("invoices.pay_today"))
        self._btn_pay_today.setToolTip(tr("invoices.pay_today_tip"))
        for _mode, _btn in getattr(self, "_chip_btns", {}).items():
            _btn.setText(tr(f"invoices.chip_{_mode}"))
            _btn.setToolTip(tr(f"invoices.chip_{_mode}"))
        self._btn_combine.setText(tr("combine.button"))
        self._btn_combine.setToolTip(tr("combine.tip"))
        self._btn_export_all.setText(tr("invoices.export_all"))
        self._btn_history.setText(tr("invoices.history"))
        self._btn_open_export.setText(tr("invoices.open_export_folder"))
        for attr, key in (
            ("_cap_invoices", "invoices.card_invoices"),
            ("_cap_credits", "invoices.card_credits"),
            ("_cap_total", "invoices.card_total"),
        ):
            cap = getattr(self, attr, None)
            if cap is not None:
                cap.setText(tr(key))
        # Filterrullistor: visningstext från kanoniskt itemData-värde
        for i in range(self._filter_type.count()):
            data = self._filter_type.itemData(i)
            self._filter_type.setItemText(
                i, tr("invoices.all_types") if not data else tr_type(data)
            )
        for i in range(self._filter_status.count()):
            data = self._filter_status.itemData(i)
            if data == "__active__":
                txt = tr("invoices.active_only")
            elif data == "__all__":
                txt = tr("invoices.all_statuses")
            else:
                txt = tr_status(data or "")
            self._filter_status.setItemText(i, txt)
        if self._filter_supplier.count() >= 1:
            self._filter_supplier.setItemText(
                0, tr("invoices.all_suppliers")
            )
        self._update_summary(self._apply_filters())
        self._update_export_buttons()
        headers = tr_list("invoices.columns")
        if len(headers) == len(COLUMNS):
            self._table.setHorizontalHeaderLabels(headers)

    def _status(self, msg: str, timeout: int = 5000) -> None:
        """Visar ett meddelande i huvudfönstrets statusrad."""
        try:
            top = self.window()
            if hasattr(top, "statusBar"):
                top.statusBar().showMessage(msg, timeout)
        except Exception:
            pass

    def _ensure_supplier(self, name: str) -> None:
        """Kontrollerar om leverantören finns — erbjuder annars att skapa."""
        if not name:
            return
        try:
            known = [
                s.get("name", "").lower()
                for s in self._app.get_suppliers()
            ]
            if name.lower() not in known:
                reply = QMessageBox.question(
                    self,
                    "Okänd leverantör",
                    f"'{name}' finns inte i leverantörsregistret.\n\n"
                    f"Vill du lägga till den?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._app.add_supplier({"name": name})
                    self._refresh_supplier_selector()
        except Exception as exc:
            log.debug("_ensure_supplier: %s", exc)

    def _check_duplicate_number(self, inv_nr: str, supplier: str) -> bool:
        """Kontrollerar dubblett: samma fakturanummer + leverantör."""
        try:
            invoices_engine = getattr(self._app, "invoices", None)
            if invoices_engine and hasattr(
                invoices_engine, "check_duplicate_number"
            ):
                return bool(
                    invoices_engine.check_duplicate_number(
                        inv_nr, supplier
                    )
                )
        except Exception:
            pass
        try:
            for inv in self._all_data:
                if (
                    inv.get("invoice_number", "").strip() == inv_nr
                    and inv.get("supplier", "").strip() == supplier
                ):
                    return True
        except Exception:
            pass
        return False

    def _safe_mark_paid(self, ids: list[str]) -> int:
        """Markerar fakturor som betalda (engine först, fallback CRUD)."""
        try:
            invoices_engine = getattr(self._app, "invoices", None)
            if invoices_engine and hasattr(invoices_engine, "mark_paid"):
                return invoices_engine.mark_paid(ids)
        except Exception:
            pass

        count = 0
        today = datetime.date.today().isoformat()
        for rid in ids:
            try:
                self._app.update_invoice(
                    rid, {"status": "Betald", "payment_date": today}
                )
                count += 1
            except Exception as exc:
                log.error("mark_paid %s: %s", rid, exc)
        return count

    # ══════════════════════════════════════════════════════════════════
    #  BETALNINGSDATUM PER EXPORT
    # ══════════════════════════════════════════════════════════════════

    def _ask_payment_date_for_export(
        self,
        exportable: list[dict],
        total_invoices: float,
        total_credits: float,
        att_betala: float,
        default_date: str = "",
    ) -> tuple[str, bool]:
        """
        Frågar efter betalningsdatum för DENNA export-batch.

        Regler
        ──────
        • Visas ALLTID innan export (inte per session).
        • Default = session_due_date om satt, annars idag.
        • OK       → returnerar (datum_str, True)
        • Avbryt   → returnerar ("", False) → export stoppas

        Använder ask_export_payment_date() från pdf_export_helpers.
        Faller tillbaka till en inbyggd dialog om modulen saknas.
        """
        # Förslag: explicit standard (t.ex. tidigaste förfallodatum
        # vid sammanslagning) vinner över sessionens datum.
        session_due_str = (
            default_date or get_session_due_date_str(self._app)
        )
        currency = self._default_currency()

        suppliers = sorted(
            {
                str(i.get("supplier", "")).strip()
                for i in exportable
                if i.get("supplier")
            }
        )

        ask_fn = _load_ask_export_payment_date()
        if ask_fn is not None:
            try:
                return ask_fn(
                    invoice_count=len(exportable),
                    supplier_names=suppliers,
                    total_amount=att_betala,
                    currency=currency,
                    session_due_date=session_due_str,
                    parent=self,
                )
            except Exception as exc:
                log.warning(
                    "_ask_payment_date_for_export (ask_fn): %s", exc
                )

        # Fallback: inbyggd dialog
        log.warning(
            "ask_export_payment_date ej tillgänglig — "
            "använder inbyggd fallback-dialog"
        )
        return self._ask_payment_date_fallback(
            session_due_str=session_due_str,
            att_betala=att_betala,
            currency=currency,
            n=len(exportable),
        )

    def _ask_payment_date_fallback(
        self,
        session_due_str: str,
        att_betala: float,
        currency: str,
        n: int,
    ) -> tuple[str, bool]:
        """Inbyggd fallback-dialog om pdf_export_helpers saknas."""
        try:
            from PySide6.QtWidgets import (
                QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                QPushButton, QFrame,
            )
            from PySide6.QtCore import QDate

            from ui.date_picker import (
                NiceDateEdit, date_preview_label, quick_pick_row,
            )

            dlg = QDialog(self)
            dlg.setWindowTitle(tr("export.date_window_title"))
            dlg.setMinimumWidth(430)
            dlg.setModal(True)

            root = QVBoxLayout(dlg)
            root.setSpacing(12)
            root.setContentsMargins(20, 16, 20, 16)
            root.addWidget(QLabel(tr("export.choose_for", n=n)))
            root.addWidget(
                QLabel(
                    f"ATT BETALA: {fmt_amount(att_betala, currency)}"
                )
            )

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFrameShadow(QFrame.Shadow.Sunken)
            root.addWidget(sep)

            date_row = QHBoxLayout()
            lbl_d = QLabel(tr("export.payment_date"))
            lbl_d.setFont(make_font(11, True))
            date_row.addWidget(lbl_d)

            date_edit = NiceDateEdit()

            default_date = QDate.currentDate()
            if session_due_str:
                try:
                    parsed = QDate.fromString(
                        session_due_str, "yyyy-MM-dd"
                    )
                    if parsed.isValid():
                        default_date = parsed
                except Exception:
                    pass
            date_edit.setDate(default_date)
            date_row.addWidget(date_edit)
            date_row.addStretch()
            root.addLayout(date_row)
            root.addWidget(quick_pick_row(date_edit, dlg))
            root.addWidget(date_preview_label(date_edit, dlg))

            btn_row = QHBoxLayout()
            btn_ok = QPushButton(tr("export.export_btn"))
            btn_ok.setDefault(True)
            btn_ok.clicked.connect(dlg.accept)
            btn_cancel = QPushButton(f"✖  {tr('common.cancel')}")
            btn_cancel.clicked.connect(dlg.reject)
            btn_row.addWidget(btn_ok)
            btn_row.addWidget(btn_cancel)
            root.addLayout(btn_row)

            if dlg.exec() == QDialog.DialogCode.Accepted:
                q = date_edit.date()
                chosen = (
                    f"{q.year():04d}-{q.month():02d}-{q.day():02d}"
                )
                log.info(
                    "Fallback-dialog: betalningsdatum = %s", chosen
                )
                return chosen, True
            return "", False
        except Exception as exc:
            log.error("_ask_payment_date_fallback: %s", exc)
            return "", False

    # ══════════════════════════════════════════════════════════════════
    #  CRUD — REGISTRERA
    # ══════════════════════════════════════════════════════════════════

    def _add_invoice(self) -> None:
        """Registrera ny faktura. Kräver vald leverantör."""
        names = self._supplier_names_list()

        # Leverantörsregister tomt → hänvisa till leverantörsfliken
        if not names:
            reply = QMessageBox.question(
                self,
                "Inga leverantörer",
                "Det finns inga leverantörer registrerade.\n\n"
                "Vill du lägga till en leverantör först?\n\n"
                "Gå till fliken 🏢 Leverantörer.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._switch_to_suppliers_tab()
            return

        # Leverantör måste väljas innan faktura kan registreras
        if not self._selected_supplier:
            QMessageBox.information(
                self,
                "Välj leverantör",
                "Välj en leverantör i rutan ovanför\n"
                "innan du kan registrera en faktura.",
            )
            self._sup_selector.setFocus()
            return

        dlg = InvoiceDialog(
            parent=self,
            supplier_name=self._selected_supplier,
            supplier_names=names,
            default_currency=self._default_currency(),
            app_core=self._app,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        data = dlg.get_data()

        # Dubblettskydd: samma fakturanummer + leverantör
        if self._check_duplicate_number(
            data["invoice_number"], data["supplier"]
        ):
            reply = QMessageBox.question(
                self,
                "Möjlig dublett",
                f"Fakturanummer '{data['invoice_number']}' från\n"
                f"'{data['supplier']}' finns redan registrerad.\n\n"
                f"Registrera ändå?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._ensure_supplier(data["supplier"])

        try:
            self._app.add_invoice(data)
            log.info(
                "Registrerad %s: %s / %s / %s",
                data.get("invoice_type", "Faktura"),
                data["invoice_number"],
                data["supplier"],
                fmt_amount(data["total_amount"]),
            )
        except Exception as exc:
            log.error("add_invoice: %s", exc)
            QMessageBox.critical(
                self, "Fel", f"Kunde inte registrera fakturan:\n{exc}"
            )
            return

        self._do_refresh()
        self._status(
            f"✅  '{data['invoice_number']}' registrerad"
            f" ({fmt_amount(data['total_amount'])})"
        )

    def _switch_to_suppliers_tab(self) -> None:
        """Byter till leverantörsfliken (visar den om den är dold)."""
        try:
            top = self.window()
            tabs = getattr(top, "tabs", None)
            if tabs is None:
                return
            for i in range(tabs.count()):
                if "Leverantör" in tabs.tabText(i):
                    tabs.setCurrentIndex(i)
                    return
            # Fliken dold → visa den först
            show_fn = getattr(top, "_set_tab_visible", None)
            if callable(show_fn):
                show_fn("suppliers", "🏢  Leverantörer", True)
                for i in range(tabs.count()):
                    if "Leverantör" in tabs.tabText(i):
                        tabs.setCurrentIndex(i)
                        return
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════
    #  CRUD — REDIGERA / TA BORT / DUPLICERA
    # ══════════════════════════════════════════════════════════════════

    def _edit_invoice(self) -> None:
        inv = self._selected_invoice()
        if not inv:
            return
        dlg = InvoiceDialog(
            parent=self,
            existing=inv,
            supplier_name=inv.get("supplier", ""),
            supplier_names=self._supplier_names_list(),
            default_currency=self._default_currency(),
            app_core=self._app,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        try:
            self._app.update_invoice(inv["id"], data)
        except Exception as exc:
            QMessageBox.critical(
                self, "Fel", f"Kunde inte uppdatera:\n{exc}"
            )
            return
        self._do_refresh()
        self._status(f"✅  '{data['invoice_number']}' uppdaterad")

    def _delete_invoice(self) -> None:
        inv = self._selected_invoice()
        if not inv:
            return
        nr = inv.get("invoice_number", "")
        reply = QMessageBox.question(
            self,
            "Ta bort faktura",
            f"Är du säker på att du vill ta bort\n"
            f"faktura '{nr}'?\n\nDetta kan inte ångras.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._app.delete_invoice(inv["id"])
        except Exception as exc:
            QMessageBox.critical(
                self, "Fel", f"Kunde inte ta bort:\n{exc}"
            )
            return
        self._do_refresh()
        self._status(f"🗑  '{nr}' borttagen")

    def _duplicate_invoice(self) -> None:
        inv = self._selected_invoice()
        if not inv:
            return
        data = {
            k: v
            for k, v in inv.items()
            if k not in ("id", "created_at", "updated_at")
        }
        data["invoice_number"] = (
            str(data.get("invoice_number", "")) + " (kopia)"
        )
        data["status"] = "Obetald"

        dlg = InvoiceDialog(
            parent=self,
            existing=data,
            supplier_name=data.get("supplier", ""),
            supplier_names=self._supplier_names_list(),
            default_currency=self._default_currency(),
            app_core=self._app,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self._app.add_invoice(dlg.get_data())
                self._do_refresh()
                self._status("✅  Faktura duplicerad")
            except Exception as exc:
                QMessageBox.critical(self, "Fel", str(exc))

    # ══════════════════════════════════════════════════════════════════
    #  CRUD — MARKERA BETALD / STATUS
    # ══════════════════════════════════════════════════════════════════

    # ── Slå ihop markerade ────────────────────────────────────────────
    @staticmethod
    def _due_relative(due_str: str) -> str:
        """'om 5 dagar' / 'förfaller idag!' / 'förfallen sedan 2 dagar!'."""
        import datetime as _dt

        try:
            due = _dt.date.fromisoformat(str(due_str)[:10])
        except (ValueError, TypeError):
            return ""
        delta = (due - _dt.date.today()).days
        if delta == 0:
            return tr("combine.due_today")
        if delta > 0:
            return tr("combine.due_in", d=delta)
        return tr("combine.due_overdue", d=-delta)

    def _show_combine_dialog(self) -> None:
        """Visar ihopslagna markerade: summa + tidigaste förfallodatum,
        med kopia- och exportknappar (exporten förifyller tidigaste
        förfallodatumet som betalningsdatum)."""
        from PySide6.QtWidgets import (
            QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
            QPushButton, QVBoxLayout,
        )

        rows = self._selected_invoices()
        if len(rows) < 2:
            QMessageBox.information(
                self, tr("combine.button"), tr("combine.need_two")
            )
            return
        summary = combine_invoices(rows)
        earliest = summary["earliest_due"]

        def _inv_line(r: dict) -> str:
            due = str(r.get("due_date", "") or "—")
            return (
                f"{due}   {r.get('supplier', '')} · "
                f"{r.get('invoice_number', '')} · "
                f"{fmt_amount(_to_float(r.get('total_amount')))}"
            )

        ordered = sorted(
            rows,
            key=lambda r: (not r.get("due_date"),
                           str(r.get("due_date", ""))),
        )
        lines = [_inv_line(r) for r in ordered]
        earliest_row = summary["earliest_invoice"] or {}
        if earliest:
            earliest_text = tr(
                "combine.earliest",
                date=earliest,
                supplier=earliest_row.get("supplier", ""),
                nr=earliest_row.get("invoice_number", ""),
            ) + f"  ·  {self._due_relative(earliest)}"
        else:
            earliest_text = tr("combine.earliest_none")

        copy_text = "\n".join(
            [
                tr("combine.title", n=summary["count"]),
                f"{tr('combine.invoices_line', n=summary['n_invoices'])} "
                f"{fmt_amount(summary['total_invoices'])}",
                f"{tr('combine.credits_line', n=summary['n_credits'])} "
                f"{fmt_amount(summary['total_credits'])}",
                f"{tr('combine.total')} {fmt_amount(summary['net'])}",
                earliest_text,
                "",
                *lines,
            ]
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("combine.title", n=summary["count"]))
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)

        lbl_total = QLabel(
            f"{tr('combine.total')}  {fmt_amount(summary['net'])}"
        )
        lbl_total.setFont(make_font(16, bold=True))
        lbl_total.setStyleSheet("color:#d4a017;")
        lay.addWidget(lbl_total)

        lbl_detail = QLabel(
            f"{tr('combine.invoices_line', n=summary['n_invoices'])} "
            f"{fmt_amount(summary['total_invoices'])}    ·    "
            f"{tr('combine.credits_line', n=summary['n_credits'])} "
            f"{fmt_amount(summary['total_credits'])}"
        )
        lay.addWidget(lbl_detail)

        lbl_earliest = QLabel(earliest_text)
        lbl_earliest.setFont(make_font(12, bold=True))
        lay.addWidget(lbl_earliest)

        if summary["missing_due"]:
            lbl_warn = QLabel(
                tr("combine.missing_due", n=summary["missing_due"])
            )
            lbl_warn.setStyleSheet("color:#e8a13a;")
            lay.addWidget(lbl_warn)

        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText("\n".join(lines))
        txt.setMaximumHeight(220)
        lay.addWidget(txt)

        row_btns = QHBoxLayout()
        btn_copy = QPushButton(tr("combine.copy"))

        def _copy() -> None:
            QApplication.clipboard().setText(copy_text)
            self._status(tr("combine.copied"))

        btn_copy.clicked.connect(_copy)
        btn_export = QPushButton(tr("combine.export_sel"))
        btn_export.setProperty("accent", True)

        def _export() -> None:
            dlg.accept()
            self._export_invoices(
                rows,
                confirm_title=tr("combine.export_title"),
                default_payment_date=earliest,
                confirm=False,
            )

        btn_export.clicked.connect(_export)
        btn_close = QPushButton(tr("combine.close"))
        btn_close.clicked.connect(dlg.reject)
        row_btns.addWidget(btn_copy)
        row_btns.addWidget(btn_export)
        row_btns.addStretch(1)
        row_btns.addWidget(btn_close)
        lay.addLayout(row_btns)
        dlg.exec()

    def _mark_selected_paid(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        reply = QMessageBox.question(
            self,
            "Markera som betald",
            f"Markera {len(ids)} faktura(or) som betalda?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._record_undo(ids)
        count = self._safe_mark_paid(ids)
        self._do_refresh()
        self._status(
            f"✅  {count} faktura(or) markerad(e) som betalda"
        )

    def _set_status_selected(self, status: str) -> None:
        """Sätter status på alla markerade fakturor."""
        ids = self._selected_ids()
        self._record_undo(ids)
        for rid in ids:
            try:
                self._app.update_invoice(rid, {"status": status})
            except Exception as exc:
                log.error("_set_status_selected %s: %s", rid, exc)
        self._do_refresh()

    # ══════════════════════════════════════════════════════════════════
    #  BETALA IDAG / KOPIERA BETALINFO / ÅNGRA
    # ══════════════════════════════════════════════════════════════════

    def _refresh_selection_label(self) -> None:
        """Beständig summarad: markerat netto, annars totalen att betala."""
        lbl = getattr(self, "_lbl_selection", None)
        if lbl is None:
            return
        ids = self._selected_ids()
        if ids:
            picked = self._selected_invoices()
            summary = combine_invoices(picked)
            if summary["earliest_due"]:
                lbl.setText(
                    tr(
                        "invoices.selected_sum",
                        n=summary["count"],
                        amount=fmt_amount(summary["net"]),
                        due=summary["earliest_due"],
                    )
                )
            else:
                lbl.setText(
                    tr(
                        "invoices.selected_sum_no_due",
                        n=summary["count"],
                        amount=fmt_amount(summary["net"]),
                    )
                )
        else:
            unpaid = sum(
                _to_float(r.get("total_amount"))
                for r in self._all_data
                if str(r.get("status", "")) not in NON_UNPAID_STATUSES
            )
            lbl.setText(
                tr(
                    "invoices.att_betala_total",
                    amount=fmt_amount(round(unpaid, 2)),
                )
            )

    def _pay_today(self) -> None:
        """Ett klick: markerar allt som förfaller idag eller i morgon."""
        targets = due_within(
            self._all_data, datetime.date.today(), horizon_days=1
        )
        ids = {str(i.get("id")) for i in targets if i.get("id")}
        if not ids:
            self._status(tr("invoices.pay_today_none"), timeout=6000)
            return
        # Visa alla träffar: nollställ sök/filter först
        try:
            self._search.setText("")
            self._filter_type.setCurrentIndex(0)
            idx = self._filter_status.findData("__active__")
            if idx >= 0:
                self._filter_status.setCurrentIndex(idx)
            self._filter_supplier.setCurrentIndex(0)
        except Exception as exc:
            log.debug("_pay_today filterreset: %s", exc)
        self._do_refresh()

        model = self._table.selectionModel()
        flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        model.clearSelection()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and str(
                item.data(Qt.ItemDataRole.UserRole)
            ) in ids:
                model.select(self._table.model().index(row, 0), flags)

        picked = self._selected_invoices()
        net = combine_invoices(picked)["net"] if picked else 0.0
        self._status(
            tr(
                "invoices.pay_today_found",
                n=len(picked),
                amount=fmt_amount(net),
            ),
            timeout=8000,
        )
        if len(picked) >= 2:
            self._show_combine_dialog()

    def _copy_payment_info(self) -> None:
        """Kopierar BG/PG/IBAN + OCR + belopp för markerad faktura."""
        inv = self._selected_invoice()
        if not inv:
            return
        sup = None
        try:
            target = str(inv.get("supplier", "")).strip().casefold()
            for rec in self._app.get_suppliers():
                if str(rec.get("name", "")).strip().casefold() == target:
                    sup = rec
                    break
        except Exception as exc:
            log.debug("_copy_payment_info leverantör: %s", exc)
        QApplication.clipboard().setText(payment_info_text(inv, sup))
        self._status(
            tr(
                "invoices.payinfo_copied",
                nr=inv.get("invoice_number", ""),
            ),
            timeout=6000,
        )

    def _record_undo(self, ids: list[str]) -> None:
        """Sparar nuvarande status/betalningsdatum före en ändring."""
        by_id = {str(r.get("id")): r for r in self._all_data}
        batch: list[tuple[str, str, str]] = []
        for rid in ids:
            rec = by_id.get(str(rid))
            if rec is not None:
                batch.append(
                    (
                        str(rid),
                        str(rec.get("status", "")),
                        str(rec.get("payment_date", "") or ""),
                    )
                )
        if batch:
            self._undo_stack.append(batch)
            del self._undo_stack[:-20]  # max 20 ångringar bakåt

    def _undo_last_status(self) -> None:
        """Ångrar senaste statusändringen (markera betald m.m.)."""
        if not self._undo_stack:
            self._status(tr("invoices.undo_empty"))
            return
        batch = self._undo_stack.pop()
        count = 0
        for rid, old_status, old_payment_date in batch:
            try:
                self._app.update_invoice(
                    rid,
                    {
                        "status": old_status,
                        "payment_date": old_payment_date,
                    },
                )
                count += 1
            except Exception as exc:
                log.error("_undo_last_status %s: %s", rid, exc)
        self._do_refresh()
        self._status(tr("invoices.undo_done", n=count))

    # ══════════════════════════════════════════════════════════════════
    #  EXPORTERA ALLA TILL PDF — med betalningsdatum per export
    # ══════════════════════════════════════════════════════════════════

    def _export_all_pdf(self) -> None:
        """
        Exportflöde:
        1. Kontrollera att det finns fakturor att exportera.
        2. Visa bekräftelsedialog (antal, belopp, leverantörer).
        3. Fråga om betalningsdatum via ask_export_payment_date().
           → Avbryt → stoppa export.
           → OK     → fortsätt med valt datum.
        4. Bygg PDF med betalningsdatum i rubriken.
        5. Arkivera fakturor.
        6. Spara i historik (inkl betalningsdatum).
        7. Öppna PDF-filen.
        8. Nollställ betalningsdatum (implicit — nästa export frågar igen).
        """
        self._export_invoices(self._get_exportable())

    def _export_invoices(
        self,
        exportable: list[dict],
        *,
        confirm_title: str = "Exportera alla fakturor",
        default_payment_date: str = "",
        confirm: bool = True,
    ) -> None:
        if not exportable:
            QMessageBox.information(
                self, "Export", "Inga aktiva fakturor att exportera."
            )
            return

        # ── Beräkna summor ─────────────────────────────────────────────
        total_invoices = 0.0
        total_credits = 0.0
        for i in exportable:
            val = _to_float(i.get("total_amount"))
            if val > 0:
                total_invoices += val
            elif val < 0:
                total_credits += val
        att_betala = round(total_invoices + total_credits, 2)

        n_inv = sum(
            1 for i in exportable if _to_float(i.get("total_amount")) >= 0
        )
        n_cre = len(exportable) - n_inv
        suppliers = sorted(
            {
                str(i.get("supplier", "")).strip()
                for i in exportable
                if i.get("supplier")
            }
        )

        # ── Bekräftelsedialog ──────────────────────────────────────────
        reply = (
            QMessageBox.question(
                self,
                confirm_title,
            f"Exportera {len(exportable)} poster till PDF?\n\n"
            f"  Fakturor ({n_inv}):   {fmt_amount(total_invoices)}\n"
            f"  Krediter ({n_cre}):   {fmt_amount(total_credits)}\n"
            f"  {'─' * 38}\n"
            f"  ATT BETALA:       {fmt_amount(att_betala)}\n\n"
            f"Leverantörer: {', '.join(suppliers)}\n\n"
            f"Du tillfrågas om betalningsdatum i nästa steg.\n"
            f"Fakturorna arkiveras efter export.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm else QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # ── Fråga om betalningsdatum (ALLTID innan export) ─────────────
        # session_due_date används som default i dialogen.
        # Avbryt → export stoppas. Datumet nollställs automatiskt
        # efter exporten (finns bara i denna lokala variabel).
        payment_date, confirmed = self._ask_payment_date_for_export(
            exportable=exportable,
            total_invoices=total_invoices,
            total_credits=total_credits,
            att_betala=att_betala,
            default_date=default_payment_date,
        )
        if not confirmed:
            log.info(
                "Export avbruten — användaren stängde "
                "betalningsdatum-dialogen"
            )
            self._status("Export avbruten.")
            return

        log.info(
            "Export: betalningsdatum = %s, %d fakturor, att betala %s",
            payment_date or "ej angivet",
            len(exportable),
            fmt_amount(att_betala),
        )

        # ── Bygg filsökväg: exports/<Leverantör>/<YYYY-MM-DD>/ ─────────
        target_dir, filename = build_export_path(suppliers)
        full_path = target_dir / filename

        # ── Hämta PDF-exportern ────────────────────────────────────────
        exporter = getattr(self._app, "pdf_exporter", None)
        if exporter is None:
            QMessageBox.information(
                self,
                "PDF-modul saknas",
                "PDF-exportmodulen är inte laddad.\n\n"
                "Kontrollera att plugins/pdf_export.py finns.",
            )
            return

        # ── Exportera till PDF ─────────────────────────────────────────
        try:
            result = exporter.export_invoice_list(
                exportable,
                filename=str(full_path),
                title=tr("invoices.export_title"),
                check_duplicates=False,
                mark_exported=True,
                force_export=True,
                payment_date=payment_date,
                ask_payment_date=False,   # dialog redan visad ovan
                include_originals=self._include_originals(),
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Export-fel", f"PDF-export misslyckades:\n{exc}"
            )
            return

        if not result.get("success"):
            if result.get("cancelled"):
                self._status("Export avbruten.")
                return
            QMessageBox.warning(
                self,
                "Export misslyckades",
                "\n".join(result.get("errors", ["Okänt fel"])),
            )
            return

        actual_path = result.get("file_path", str(full_path))
        export_pd = result.get("payment_date", payment_date)

        # ── Spara i exporthistorik (inkl betalningsdatum) ──────────────
        self._export_history.record_export(
            invoices=exportable,
            file_path=actual_path,
            total_inv=total_invoices,
            total_cred=total_credits,
            att_betala=att_betala,
            suppliers=suppliers,
            payment_date=export_pd,   # betalningsdatum sparas
        )

        # ── Arkivera alla exporterade fakturor ─────────────────────────
        archived = 0
        for inv in exportable:
            try:
                self._app.update_invoice(
                    inv["id"], {"status": "Arkiverad"}
                )
                archived += 1
            except Exception:
                pass

        self._do_refresh()
        attach_note = ""
        if result.get("attachments_included"):
            attach_note = tr(
                "invoices.attachments_note",
                n=result["attachments_included"],
            )
        self._status(
            f"📄  {archived} poster exporterade"
            f" → {fmt_amount(att_betala)}"
            + (f"  (betaldatum: {export_pd})" if export_pd else "")
            + attach_note
        )

        # ── Resultatdialog: Öppna filen / Öppna mappen / Stäng ─────────
        payment_line = (
            f"  Betalningsdatum: {export_pd}\n" if export_pd else ""
        )
        box = QMessageBox(self)
        box.setWindowTitle("Export klar")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            f"✅  {archived} poster exporterade och arkiverade.\n\n"
            f"  Fakturor  (+)    {fmt_amount(total_invoices)}\n"
            f"  Krediter  (−)    {fmt_amount(total_credits)}\n"
            f"  {'─' * 38}\n"
            f"  ATT BETALA       {fmt_amount(att_betala)}\n"
            f"{payment_line}\n"
            f"Fil: {actual_path}"
        )
        btn_open_file = box.addButton(
            "📄  Öppna filen", QMessageBox.ButtonRole.AcceptRole
        )
        btn_open_folder = box.addButton(
            "📂  Öppna mappen", QMessageBox.ButtonRole.ActionRole
        )
        box.addButton("✖  Stäng", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked is btn_open_file:
            open_file(actual_path)
        elif clicked is btn_open_folder:
            open_folder(Path(actual_path).parent)

        # Betalningsdatum nollställs implicit — variabeln payment_date
        # existerar bara i denna funktion. Nästa export frågar igen.
        log.info(
            "Export klar: %d fakturor arkiverade, "
            "betalningsdatum '%s' nollställt",
            archived,
            export_pd,
        )

    # ══════════════════════════════════════════════════════════════════
    #  EXPORTHISTORIK
    # ══════════════════════════════════════════════════════════════════

    def _show_history(self) -> None:
        """Visar exporthistoriken med återställningsmöjlighet."""
        if self._export_history.count() == 0:
            QMessageBox.information(
                self, "Exporthistorik", "Ingen exporthistorik ännu."
            )
            return
        dlg = ExportHistoryDialog(
            parent=self,
            history=self._export_history,
            theme=self._current_theme,
        )
        dlg.export_restored.connect(self._on_export_restored)
        dlg.exec()

    def _on_export_restored(self, invoice_ids: list[str]) -> None:
        """
        Återställer arkiverade fakturor till Obetald.

        Anropas via ExportHistoryDialog.export_restored-signalen.
        """
        for iid in invoice_ids:
            try:
                self._app.update_invoice(iid, {"status": "Obetald"})
            except Exception:
                pass
        self._do_refresh()
        self._status(
            f"✅  {len(invoice_ids)} fakturor återställda från arkiv"
        )

    # ══════════════════════════════════════════════════════════════════
    #  HÖGERKLICK-MENY
    # ══════════════════════════════════════════════════════════════════

    def _context_menu(self, pos) -> None:
        """
        Högerklick i tabellen.

        Markerar raden under muspekaren om den inte redan ingår i
        markeringen (befintlig multi-markering bevaras).
        """
        item = self._table.itemAt(pos)
        if item is None:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        if rid not in self._selected_ids():
            self._table.selectRow(item.row())

        menu = QMenu(self)
        menu.addAction("✏️  Redigera", self._edit_invoice)
        menu.addAction("📋  Duplicera", self._duplicate_invoice)
        menu.addAction(
            tr("invoices.copy_payinfo"), self._copy_payment_info
        )
        menu.addSeparator()

        status_menu = menu.addMenu("📊  Ändra status")
        for s in INVOICE_STATUSES:
            act = status_menu.addAction(s)
            act.triggered.connect(
                lambda checked=False, st=s: self._set_status_selected(st)
            )
        menu.addSeparator()

        menu.addAction(
            "✅  Markera betald", self._mark_selected_paid
        )
        menu.addAction("↩  Ångra statusändring", self._undo_last_status)
        menu.addSeparator()
        menu.addAction("🗑  Ta bort", self._delete_invoice)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ══════════════════════════════════════════════════════════════════
    #  TEMA
    # ══════════════════════════════════════════════════════════════════

    def apply_theme(self, theme: dict) -> None:
        """
        Applicera tema på hela vyn.

        Mörkt tema = vit fet text. Ljust tema = mörk fet text.
        """
        if not theme:
            return
        self._current_theme = theme
        t = theme
        dark = self._is_dark()

        text_color = t.get(
            "text_strong", "#f0f6fc" if dark else "#1c2128"
        )
        muted_color = t.get("text", "#c9d1d9" if dark else "#24292f")
        bg_color = t.get("bg", "#0d1117" if dark else "#ffffff")
        accent = t.get("accent", "#58a6ff" if dark else "#0969da")
        accent_hover = t.get(
            "accent_hover", "#388bfd" if dark else "#0550ae"
        )
        border_c = t.get("border", "#30363d" if dark else "#d0d7de")

        # ── Header ─────────────────────────────────────────────────────
        self._header_label.setStyleSheet(
            f"color:{text_color};font-weight:700;background:transparent;"
        )

        # ── Frames ─────────────────────────────────────────────────────
        card = t.get("card_bg", t.get("row_alt", "#161b22"))
        gold = t.get("gold", "#e8b030")
        gold_bg = t.get("gold_bg", card)
        success = t.get("success", "#3ecf8e")
        error = t.get("error", "#f07178")

        supplier = self.findChild(QFrame, "SupplierBar")
        if supplier:
            supplier.setStyleSheet(
                f"QFrame#SupplierBar{{background-color:{card};"
                f"border-radius:10px;border:1.5px solid {accent};}}"
            )
        strip = self.findChild(QFrame, "SummaryStrip")
        if strip:
            strip.setStyleSheet(
                "QFrame#SummaryStrip{background:transparent;border:none;}"
            )
        for obj_name, bg in (
            ("MoneyCard", card),
            ("MoneyCardCredit", card),
            ("MoneyCardTotal", gold_bg),
        ):
            frame = self.findChild(QFrame, obj_name)
            if frame:
                edge = gold if obj_name == "MoneyCardTotal" else border_c
                frame.setStyleSheet(
                    f"QFrame#{obj_name}{{background:{bg};"
                    f"border:1px solid {edge};border-radius:12px;}}"
                )
        self._lbl_invoices.setStyleSheet(
            f"color:{success};background:transparent;font-weight:800;"
        )
        self._lbl_credits.setStyleSheet(
            f"color:{error};background:transparent;font-weight:800;"
        )
        self._lbl_att_betala.setStyleSheet(
            f"color:{gold};background:transparent;font-weight:800;font-size:18px;"
        )

        # ── Inputs ─────────────────────────────────────────────────────
        input_bg = t.get("input_bg", "#0d1117" if dark else "#ffffff")
        input_border = t.get(
            "input_border", "#30363d" if dark else "#d0d7de"
        )
        input_style = (
            f"background-color:{input_bg};"
            f"color:{text_color};"
            f"border:1.5px solid {input_border};"
            f"border-radius:7px;padding:5px 10px;"
            f"font-size:13px;font-weight:700;"
        )
        focus_border = f"border-color:{accent};"

        self._sup_selector.setStyleSheet(
            f"QComboBox{{{input_style}min-height:38px;font-size:14px;}}"
            f"QComboBox:focus{{{focus_border}}}"
        )
        self._search.setStyleSheet(
            f"QLineEdit{{{input_style}}}"
            f"QLineEdit:focus{{{focus_border}}}"
        )
        for combo in (
            self._filter_type,
            self._filter_status,
            self._filter_supplier,
        ):
            combo.setStyleSheet(
                f"QComboBox{{{input_style}min-height:36px;}}"
                f"QComboBox:focus{{{focus_border}}}"
            )

        # ── Tabell ─────────────────────────────────────────────────────
        header_bg = t.get("header_bg", "#1f6feb" if dark else "#0969da")
        row_normal = t.get("row_normal", bg_color)
        row_alt = t.get("row_alt", "#161b22" if dark else "#f6f8fa")
        scroll_bg = t.get(
            "scrollbar_bg", "#161b22" if dark else "#f6f8fa"
        )
        scroll_h = t.get(
            "scrollbar_handle", "#30363d" if dark else "#d0d7de"
        )

        self._table.setStyleSheet(f"""
            QTableWidget {{
                background-color           : {row_normal};
                color                      : {text_color};
                font-weight                : 700;
                font-size                  : 13px;
                gridline-color             : {border_c};
                alternate-background-color : {row_alt};
                selection-background-color : {accent};
                selection-color            : #ffffff;
                border                     : 1px solid {border_c};
                border-radius              : 6px;
                outline                    : none;
            }}
            QHeaderView::section {{
                background-color : {header_bg};
                color            : #ffffff;
                font-weight      : 800;
                font-size        : 12px;
                padding          : 7px 10px;
                border           : none;
                border-right     : 1px solid {border_c};
                border-bottom    : 1px solid {border_c};
            }}
            QTableWidget::item {{ padding: 5px 8px; }}
            QTableWidget::item:selected {{
                background-color : {accent};
                color            : #ffffff;
            }}
            QScrollBar:vertical {{
                background    : {scroll_bg};
                width         : 10px;
                border-radius : 5px;
            }}
            QScrollBar::handle:vertical {{
                background    : {scroll_h};
                border-radius : 5px;
                min-height    : 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {accent}; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        # ── Knappar ────────────────────────────────────────────────────
        error_c = t.get("error", "#f85149" if dark else "#cf222e")
        success_c = t.get("success", "#3fb950" if dark else "#1a7f37")
        info_c = t.get("info", "#58a6ff" if dark else "#0969da")

        if dark:
            btn_bg = t.get("button_bg", "#21262d")
            btn_hover = t.get("button_hover", "#30363d")
            btn_text = t.get("button_text", "#f0f6fc")
        else:
            btn_bg = t.get("button_bg", "#6e7781")
            btn_hover = t.get("button_hover", "#57606a")
            btn_text = t.get("button_text", "#ffffff")

        btn_configs = [
            (self._btn_add,         accent,    accent_hover, "#ffffff"),
            (self._btn_edit,        btn_bg,    btn_hover,    btn_text),
            (self._btn_delete,      error_c,   "#da3633",    "#ffffff"),
            (self._btn_duplicate,   btn_bg,    btn_hover,    btn_text),
            (self._btn_mark_paid,   success_c, "#2ea043",    "#ffffff"),
            (self._btn_export_all,  info_c,    accent_hover, "#ffffff"),
            (self._btn_history,     btn_bg,    btn_hover,    btn_text),
            (self._btn_open_export, btn_bg,    btn_hover,    btn_text),
            (self._btn_refresh,     btn_bg,    btn_hover,    btn_text),
        ]
        for btn, bg, hover, fg in btn_configs:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color : {bg};
                    color            : {fg};
                    font-weight      : 700;
                    font-size        : 12px;
                    border-radius    : 7px;
                    border           : 1px solid {border_c};
                    padding          : 7px 16px;
                    min-height       : 36px;
                }}
                QPushButton:hover {{
                    background-color : {hover};
                    border-color     : {accent};
                }}
                QPushButton:pressed {{
                    background-color : {accent};
                    color            : #ffffff;
                }}
                QPushButton:disabled {{
                    background-color : {border_c};
                    color            : #666666;
                    border-color     : {border_c};
                }}
            """)

        # ── Summary-labels ─────────────────────────────────────────────
        label_style = (
            f"color:{text_color};font-weight:700;background:transparent;"
        )
        for lbl in (
            self._lbl_count,
            self._lbl_invoices,
            self._lbl_credits,
            self._lbl_unpaid,
            self._lbl_overdue,
        ):
            lbl.setStyleSheet(label_style)

        self._lbl_att_betala.setStyleSheet(
            f"color:{success_c};font-weight:800;font-size:14px;"
            f"background:transparent;"
        )

        muted_style = f"color:{muted_color};background:transparent;"
        self._lbl_supplier_info.setStyleSheet(muted_style)
        self._footer.setStyleSheet(muted_style)
        self._lbl_history_count.setStyleSheet(muted_style)

        if self._initialised:
            filtered = self._apply_filters()
            self._populate_table(filtered)

    # ══════════════════════════════════════════════════════════════════
    #  PUBLIKT API
    # ══════════════════════════════════════════════════════════════════

    def refresh(self) -> None:
        """Extern refresh — anropas av MainWindow._refresh_all()."""
        self._do_refresh()

    def _add_export_action(self) -> None:
        """Hook för pdf_export.py register_ui() — kan utökas vid behov."""
        pass


# ═════════════════════════════════════════════════════════════════════
#  PLUGIN HOOKS
# ═════════════════════════════════════════════════════════════════════


def register(app: Any) -> None:
    """Fas 1: app-nivå-registrering — ingenting att göra här."""
    log.debug("invoices_view register (fas 1) — OK")


def register_ui(main_window: Any) -> None:
    """
    Fas 2: monterar InvoicesView i MainWindow-fliken 'invoices'.

    Kontrollerar först om InvoicesView redan laddats som builtin
    (MainWindow._load_builtin_views) för att undvika dubbelregistrering.
    """
    try:
        existing = None
        if hasattr(main_window, "get_invoices_view"):
            existing = main_window.get_invoices_view()

        if existing and isinstance(existing, InvoicesView):
            try:
                main_window.theme_changed.connect(existing.apply_theme)
                existing.apply_theme(main_window.current_theme_dict())
            except Exception:
                pass
            log.info(
                "InvoicesView redan laddad av builtin "
                "— hoppar över dubblering"
            )
            return

        app = getattr(main_window, "_app", None)
        if app is None:
            log.error("register_ui: main_window._app saknas")
            return

        view = InvoicesView(app, parent=main_window)
        main_window.replace_tab_content("invoices", view)
        try:
            main_window.theme_changed.connect(view.apply_theme)
            view.apply_theme(main_window.current_theme_dict())
        except Exception:
            pass
        log.info("InvoicesView monterad via register_ui (fallback)")
    except Exception as exc:
        log.error(
            "invoices_view register_ui error: %s", exc, exc_info=True
        )
