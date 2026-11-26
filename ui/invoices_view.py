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
import inspect
import logging
import re
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QApplication,
    QTextEdit,
    QPlainTextEdit,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QScrollArea,
    QLabel,
    QFrame,
    QLineEdit,
    QComboBox,
    QPushButton,
    QTableView,
    QHeaderView,
    QAbstractItemView,
    QAbstractScrollArea,
    QMenu,
    QMessageBox,
    QCompleter,
    QDialog,
    QSizePolicy,
)
from PySide6.QtCore import (
    Qt, QTimer, Signal, QSize, QItemSelectionModel, QSortFilterProxyModel,
)

try:
    from ui.i18n import tr, tr_list, tr_status, tr_type
except ImportError:  # fristående körning av filen
    from i18n import tr, tr_list, tr_status, tr_type  # type: ignore[no-redef]
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut, QWheelEvent

# ═════════════════════════════════════════════════════════════════════
#  IMPORTER FRÅN HELPERS
# ═════════════════════════════════════════════════════════════════════

try:
    from ui.invoices_helpers import (
        INVOICE_STATUSES,
        HIDDEN_STATUSES,
        STATUS_COLORS,
        COLUMNS,
        COL_WIDTHS,
        COL_KEYS,
        ExportHistoryManager,
        ExportHistoryDialog,
        InvoiceDialog,
        due_within,
        due_window_filter,
        payment_info_text,
        is_dark_theme,
        make_btn,
        make_font,
        h_line,
        fit_table_columns,
        date_column_width,
        DATE_COLUMN_KEYS,
        fmt_amount,
        combine_invoices,
        plan_credit_settlement,
        chunk_settlement_rows,
        apply_credit_carryovers,
        build_chunk_carryovers,
        build_export_path,
        chunk_export_rows,
        get_export_base,
        EXPORT_MARK_LIMIT,
        open_file,
        open_folder,
        attachment_page_count,
        get_session_due_date_str,
        COPYRIGHT_YEAR,
    )
except ImportError:
    from invoices_helpers import (  # type: ignore[no-redef]
        INVOICE_STATUSES,
        HIDDEN_STATUSES,
        STATUS_COLORS,
        COLUMNS,
        COL_WIDTHS,
        COL_KEYS,
        ExportHistoryManager,
        ExportHistoryDialog,
        InvoiceDialog,
        due_within,
        due_window_filter,
        payment_info_text,
        make_btn,
        make_font,
        h_line,
        fit_table_columns,
        date_column_width,
        DATE_COLUMN_KEYS,
        fmt_amount,
        combine_invoices,
        plan_credit_settlement,
        chunk_settlement_rows,
        apply_credit_carryovers,
        build_chunk_carryovers,
        build_export_path,
        chunk_export_rows,
        get_export_base,
        EXPORT_MARK_LIMIT,
        open_file,
        open_folder,
        attachment_page_count,
        get_session_due_date_str,
        COPYRIGHT_YEAR,
    )

try:
    from ui.duplicate_archive import find_moved_original
except ImportError:  # fristående körning
    try:
        from duplicate_archive import (  # type: ignore[no-redef]
            find_moved_original,
        )
    except ImportError:  # pragma: no cover
        find_moved_original = None

try:
    from ui.design import (
        CONTROL_RADIUS_PX, FOCUS_RING_PX, FlowLayout, ICON_HEADER_PX,
        PANEL_RADIUS_PX, TABLE_CELL_PADDING_COMPACT_PX,
        TABLE_CELL_PADDING_COMFORTABLE_PX, TABLE_ROW_HEIGHT_COMPACT,
        TABLE_ROW_HEIGHT_COMFORTABLE, app_icon_pixmap, fit_dialog_to_screen,
    )
except Exception:  # pragma: no cover - fristående körning
    try:
        from design import (  # type: ignore[no-redef]
            CONTROL_RADIUS_PX, FOCUS_RING_PX, FlowLayout, ICON_HEADER_PX,
            PANEL_RADIUS_PX, TABLE_CELL_PADDING_COMPACT_PX,
            TABLE_CELL_PADDING_COMFORTABLE_PX, TABLE_ROW_HEIGHT_COMPACT,
            TABLE_ROW_HEIGHT_COMFORTABLE, app_icon_pixmap, fit_dialog_to_screen,
        )
    except Exception:
        ICON_HEADER_PX = 28  # type: ignore[no-redef]
        FlowLayout = QHBoxLayout  # type: ignore[misc, assignment]
        fit_dialog_to_screen = None  # type: ignore[assignment]
        CONTROL_RADIUS_PX = 7  # type: ignore[no-redef]
        PANEL_RADIUS_PX = 10  # type: ignore[no-redef]
        FOCUS_RING_PX = 2  # type: ignore[no-redef]
        TABLE_ROW_HEIGHT_COMPACT = 32  # type: ignore[no-redef]
        TABLE_ROW_HEIGHT_COMFORTABLE = 42  # type: ignore[no-redef]
        TABLE_CELL_PADDING_COMPACT_PX = 4  # type: ignore[no-redef]
        TABLE_CELL_PADDING_COMFORTABLE_PX = 7  # type: ignore[no-redef]

        def app_icon_pixmap(size: int = 28):  # type: ignore[no-redef]
            from PySide6.QtGui import QPixmap as _QP
            return _QP()

try:
    from ui.invoice_table_model import InvoiceTableModel, SORT_ROLE
except ImportError:  # pragma: no cover - standalone import
    from invoice_table_model import (  # type: ignore[no-redef]
        InvoiceTableModel, SORT_ROLE,
    )

try:
    from ui.icons import (
        attach_search_icon,
        bind_icon,
        qss_indicator_urls,
        refresh_bound_icons,
    )
except Exception:  # pragma: no cover - fristående körning
    try:
        from icons import (  # type: ignore[no-redef]
            attach_search_icon,
            bind_icon,
            qss_indicator_urls,
            refresh_bound_icons,
        )
    except Exception:
        def bind_icon(target: Any, *_a: Any, **_kw: Any) -> Any:  # type: ignore[no-redef]
            return target

        def attach_search_icon(target: Any, *_a: Any, **_kw: Any) -> Any:  # type: ignore[no-redef]
            return target

        def refresh_bound_icons(*_a: Any, **_kw: Any) -> None:  # type: ignore[no-redef]
            pass

        def qss_indicator_urls(*_a: Any, **_kw: Any) -> dict[str, str]:  # type: ignore[no-redef]
            return {}

try:
    from ui.typography import make_tabular_font, set_table_default_row_height
except ImportError:  # pragma: no cover - standalone import
    try:
        from typography import (  # type: ignore[no-redef]
            make_tabular_font, set_table_default_row_height,
        )
    except Exception:
        make_tabular_font = make_font  # type: ignore[assignment]
        from typography import set_table_default_row_height  # type: ignore[no-redef]

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

#: Sekundära fakturakolumner som döljs i kompakt läge (t.ex. 1000×720).
INVOICE_COMPACT_HIDDEN_KEYS: frozenset[str] = frozenset({
    "invoice_type", "payment_date", "currency",
    "category", "reference", "note", "pages",
})

#: Viktigaste kolumnerna som alltid förblir synliga i tabellen.
_INVOICE_LOCKED_KEYS: frozenset[str] = frozenset({
    "supplier", "invoice_number", "total_amount",
})

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
        # Exportmarkering per faktura-id: radmarkeringen i tabellen
        # ÄR exportvalet, men mängden bor här så markeringen
        # överlever filterbyte och refresh (återappliceras per id).
        self._marked_export_ids: set[str] = set()
        self._page_count_cache: dict[tuple, int] = {}
        self._displayed_ids: list[str] = []
        self._populating_table = False
        self._undo_stack: list[list[tuple[str, str, str]]] = []
        self._chip_mode: str = ""  # snabbfilter: "" / overdue / today / week
        self._current_theme: dict = {}
        self._favorite_names: set[str] = set()
        self._row_density = self._load_row_density()
        self._original_export_mode = self._load_original_export_mode()
        self._hidden_columns: set[str] = self._load_hidden_columns()
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
        self._apply_hidden_columns()

        # Ångra senaste statusändringen med Ctrl+Z
        self._sc_undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._sc_undo.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._sc_undo.activated.connect(self._undo_last_status)

        # Delete-tangenten tar bort markerad faktura (enstaka).
        # Fokusskydd i _on_delete_key: står man i ett textfält
        # (sök/dialog) ska Delete radera text som vanligt.
        self._sc_delete = QShortcut(
            QKeySequence.StandardKey.Delete, self
        )
        self._sc_delete.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._sc_delete.activated.connect(self._on_delete_key)

        # Snabb åtkomst till återkommande moment; tabellens egna piltangenter
        # fortsätter sköta radnavigeringen.
        self._sc_find = QShortcut(QKeySequence("Ctrl+F"), self)
        self._sc_add = QShortcut(QKeySequence("Ctrl+N"), self)
        self._sc_edit = QShortcut(QKeySequence("Ctrl+E"), self)
        self._sc_export = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        for shortcut in (
            self._sc_find, self._sc_add, self._sc_edit, self._sc_export,
        ):
            shortcut.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
        self._sc_find.activated.connect(self._focus_search)
        self._sc_add.activated.connect(self._add_invoice)
        self._sc_edit.activated.connect(self._edit_invoice)
        self._sc_export.activated.connect(self._export_selected_pdf)
        self._search.setToolTip(tr("invoices.search_shortcut_tip"))
        self._table.setToolTip(tr("invoices.table_keyboard_tip"))

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
        root.setContentsMargins(8, 4, 8, 2)
        root.setSpacing(4)
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
        supplier_layout.setContentsMargins(10, 5, 10, 5)
        supplier_layout.setSpacing(10)

        lbl_sup = QLabel(tr("invoices.choose_supplier"))
        self._lbl_sup = lbl_sup
        lbl_sup.setFont(make_font(12, True))
        lbl_sup.setStyleSheet("background:transparent;")

        self._sup_selector = QComboBox()
        self._sup_selector.setMinimumHeight(34)
        self._sup_selector.setMinimumWidth(160)
        self._sup_selector.setFont(make_font(13, True))
        self._sup_selector.setToolTip(
            tr("invoices.supplier_selector_tip")
        )
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
        root.addWidget(supplier_frame)

        # ── Huvudindelning: knappar/kontroller till VÄNSTER och
        # fakturatabellen tydlig till HÖGER. Sidokolumnen har fast
        # bredd och egen rullning, så inget täcks eller kläms ihop
        # när fönstret är smalt — tabellen får all återstående
        # bredd och anpassar sig efter fönstret.
        body = QHBoxLayout()
        body.setSpacing(8)
        root.addLayout(body, stretch=1)

        side_wrap = QWidget()
        side_wrap.setObjectName("SideControls")
        # Innehållet i rullområdet måste hålla sig inom spaltens
        # bredd — annars växer panelerna förbi spalten och knappar
        # hamnar under tabellen.
        side_wrap.setMinimumWidth(312)
        side_wrap.setMaximumWidth(326)
        side = QVBoxLayout(side_wrap)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(4)
        side_scroll = QScrollArea()
        side_scroll.setObjectName("SideScroll")
        side_scroll.setWidgetResizable(True)
        side_scroll.setWidget(side_wrap)
        side_scroll.setMinimumWidth(320)
        side_scroll.setMaximumWidth(334)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._side_scroll = side_scroll
        self._side_layout = side
        body.addWidget(side_scroll)

        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        self._right_pane = right_wrap
        self._right_layout = right_layout
        body.addWidget(right_wrap, stretch=1)

        # ── Sök + filter (egen panel: FilterBar) ───────────────────────
        filter_frame = QFrame()
        filter_frame.setObjectName("FilterBar")
        filter_layout = QVBoxLayout(filter_frame)
        filter_layout.setContentsMargins(8, 5, 8, 5)
        filter_layout.setSpacing(3)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("invoices.search_ph"))
        self._search.setMinimumHeight(0)
        self._search.setFont(make_font(12))
        self._search.setClearButtonEnabled(True)
        attach_search_icon(self._search, size=14)
        self._search.textChanged.connect(
            lambda *_: self._search_timer.start()
        )

        self._filter_type = QComboBox()
        self._filter_type.setMinimumHeight(0)
        self._filter_type.setMinimumWidth(0)
        self._filter_type.setFont(make_font(11))
        self._filter_type.addItem(tr("invoices.all_types"), "")
        self._filter_type.addItem(tr_type("Faktura"), "Faktura")
        self._filter_type.addItem(tr_type("Kreditfaktura"), "Kreditfaktura")
        self._filter_type.currentTextChanged.connect(
            lambda *_: self._search_timer.start()
        )

        self._filter_status = QComboBox()
        self._filter_status.setMinimumHeight(0)
        self._filter_status.setMinimumWidth(0)
        self._filter_status.setFont(make_font(11))
        self._filter_status.addItem(tr("invoices.active_only"), "__active__")
        self._filter_status.addItem(tr("invoices.all_statuses"), "__all__")
        for _st in INVOICE_STATUSES:
            self._filter_status.addItem(tr_status(_st), _st)
        self._filter_status.currentTextChanged.connect(
            lambda *_: self._search_timer.start()
        )

        self._filter_supplier = QComboBox()
        self._filter_supplier.setMinimumHeight(0)
        self._filter_supplier.setMinimumWidth(0)
        self._filter_supplier.setFont(make_font(11))
        self._filter_supplier.addItem(tr("invoices.all_suppliers"), "")
        self._filter_supplier.currentTextChanged.connect(
            lambda *_: self._search_timer.start()
        )

        filter_layout.addWidget(self._search)
        filter_layout.addWidget(self._filter_type)
        filter_layout.addWidget(self._filter_status)
        filter_layout.addWidget(self._filter_supplier)
        side.addWidget(filter_frame)

        # ── CRUD-knappar (kompakt panel: ActionsBar + Fler åtgärder-meny) ─
        actions_frame = QFrame()
        actions_frame.setObjectName("ActionsBar")
        actions_col = QVBoxLayout(actions_frame)
        actions_col.setContentsMargins(8, 5, 8, 5)
        actions_col.setSpacing(3)

        self._btn_add = make_btn(
            tr("invoices.add"),
            tr("invoices.add_tip"),
            accent=True,
        )
        bind_icon(self._btn_add, "add", size=14, role="on_accent")
        self._btn_add.clicked.connect(self._add_invoice)

        self._btn_edit = make_btn(
            tr("invoices.edit"), tr("invoices.edit_tip")
        )
        bind_icon(self._btn_edit, "edit", size=14)
        self._btn_edit.clicked.connect(self._edit_invoice)
        self._btn_edit.setEnabled(False)

        self._btn_mark_paid = make_btn(
            tr("invoices.mark_paid"),
            tr("invoices.mark_paid_tip"),
            success=True,
        )
        bind_icon(self._btn_mark_paid, "check", size=14, role="on_accent")
        self._btn_mark_paid.clicked.connect(self._mark_selected_paid)
        self._btn_mark_paid.setEnabled(False)

        self._btn_pay_today = make_btn(
            tr("invoices.pay_today"),
            tr("invoices.pay_today_tip"),
            success=True,
        )
        bind_icon(self._btn_pay_today, "zap", size=14, role="on_accent")
        self._btn_pay_today.clicked.connect(self._pay_today)

        self._btn_delete = make_btn(
            tr("invoices.delete"), tr("invoices.delete_tip"), danger=True
        )
        bind_icon(self._btn_delete, "delete", size=14, role="on_accent")
        self._btn_delete.clicked.connect(self._delete_invoice)
        self._btn_delete.setEnabled(False)

        self._btn_more_actions = make_btn(
            tr("invoices.more_actions"), tr("invoices.more_actions_tip")
        )
        bind_icon(self._btn_more_actions, "list", size=14)
        self._more_actions_menu = QMenu(self._btn_more_actions)
        if hasattr(self._more_actions_menu, "setToolTipsVisible"):
            self._more_actions_menu.setToolTipsVisible(True)

        self._btn_combine = QAction(tr("combine.button"), self)
        self._btn_combine.setToolTip(tr("combine.tip"))
        bind_icon(self._btn_combine, "combine", size=14)
        self._btn_combine.triggered.connect(self._show_combine_dialog)
        self._btn_combine.setEnabled(False)

        self._btn_duplicate = QAction(tr("invoices.duplicate"), self)
        self._btn_duplicate.setToolTip(tr("invoices.duplicate_tip"))
        bind_icon(self._btn_duplicate, "duplicate", size=14)
        self._btn_duplicate.triggered.connect(self._duplicate_invoice)
        self._btn_duplicate.setEnabled(False)

        self._btn_link_credit = QAction(tr("credit.link_button"), self)
        self._btn_link_credit.setToolTip(tr("credit.link_tip"))
        bind_icon(self._btn_link_credit, "link", size=14)
        self._btn_link_credit.triggered.connect(self._show_link_credit_dialog)
        self._btn_link_credit.setEnabled(False)

        self._btn_refresh = QAction(tr("invoices.refresh"), self)
        self._btn_refresh.setToolTip(tr("invoices.refresh_tip"))
        bind_icon(self._btn_refresh, "refresh", size=14)
        self._btn_refresh.triggered.connect(self._do_refresh)

        self._btn_undo = QAction(tr("invoices.undo"), self)
        self._btn_undo.setToolTip(tr("invoices.undo_tip"))
        bind_icon(self._btn_undo, "undo", size=14)
        self._btn_undo.triggered.connect(self._undo_last_status)

        self._btn_delete_all = QAction(tr("invoices.delete_all"), self)
        self._btn_delete_all.setToolTip(tr("invoices.delete_all_tip"))
        bind_icon(self._btn_delete_all, "delete", size=14)
        self._btn_delete_all.triggered.connect(self._delete_all_invoices)
        self._btn_delete_all.setEnabled(False)

        self._more_actions_menu.addAction(self._btn_combine)
        self._more_actions_menu.addAction(self._btn_duplicate)
        self._more_actions_menu.addAction(self._btn_link_credit)
        self._more_actions_menu.addSeparator()
        self._more_actions_menu.addAction(self._btn_refresh)
        self._more_actions_menu.addAction(self._btn_undo)
        self._more_actions_menu.addSeparator()
        self._more_actions_menu.addAction(self._btn_delete_all)
        self._btn_more_actions.setMenu(self._more_actions_menu)

        for _b in (
            self._btn_add,
            self._btn_edit,
            self._btn_mark_paid,
            self._btn_pay_today,
            self._btn_delete,
            self._btn_more_actions,
        ):
            _b.setMinimumWidth(0)

        act_r0 = QHBoxLayout()
        act_r0.setSpacing(4)
        act_r0.addWidget(self._btn_add, stretch=3)
        act_r0.addWidget(self._btn_edit, stretch=2)

        act_r1 = QHBoxLayout()
        act_r1.setSpacing(4)
        act_r1.addWidget(self._btn_mark_paid, stretch=1)
        act_r1.addWidget(self._btn_pay_today, stretch=1)

        act_r2 = QHBoxLayout()
        act_r2.setSpacing(4)
        act_r2.addWidget(self._btn_delete, stretch=2)
        act_r2.addWidget(self._btn_more_actions, stretch=3)

        actions_col.addLayout(act_r0)
        actions_col.addLayout(act_r1)
        actions_col.addLayout(act_r2)
        side.addWidget(actions_frame)

        # ── Export (egen panel: ExportBar) ─────────────────────────────
        export_frame = QFrame()
        export_frame.setObjectName("ExportBar")
        export_layout = QVBoxLayout(export_frame)
        export_layout.setContentsMargins(8, 5, 8, 5)
        export_layout.setSpacing(3)

        row_export_head = QHBoxLayout()
        row_export_head.setSpacing(6)
        self._lbl_export_heading = QLabel(tr("invoices.export_heading"))
        self._lbl_export_heading.setFont(make_font(11, True))
        self._lbl_export_heading.setStyleSheet("background:transparent;")
        self._lbl_history_count = QLabel("")
        self._lbl_history_count.setFont(make_font(10))
        self._lbl_history_count.setStyleSheet("background:transparent;")

        self._btn_export_menu = make_btn(
            tr("invoices.export_tools"), tr("invoices.export_tools_tip")
        )
        self._btn_export_menu.setMinimumWidth(0)
        bind_icon(self._btn_export_menu, "history", size=13)
        self._export_tools_menu = QMenu(self._btn_export_menu)
        self._export_tools_menu.setToolTipsVisible(True)

        self._btn_history = QAction(tr("invoices.history"), self)
        self._btn_history.setToolTip(tr("invoices.history_tip"))
        bind_icon(self._btn_history, "history", size=14)
        self._btn_history.triggered.connect(self._show_history)

        self._btn_open_export = QAction(
            tr("invoices.open_export_folder"), self
        )
        self._btn_open_export.setToolTip(tr("invoices.open_export_tip"))
        bind_icon(self._btn_open_export, "folder", size=14)
        self._btn_open_export.triggered.connect(
            lambda: open_folder(get_export_base())
        )
        self._export_tools_menu.addAction(self._btn_history)
        self._export_tools_menu.addAction(self._btn_open_export)
        self._btn_export_menu.setMenu(self._export_tools_menu)

        row_export_head.addWidget(self._lbl_export_heading)
        row_export_head.addWidget(self._lbl_history_count)
        row_export_head.addStretch()
        row_export_head.addWidget(self._btn_export_menu)
        export_layout.addLayout(row_export_head)

        row_original_options = QHBoxLayout()
        row_original_options.setSpacing(6)
        self._lbl_original_export = QLabel(
            tr("invoices.export_originals_mode")
        )
        self._combo_original_export = QComboBox()
        self._combo_original_export.setMinimumHeight(0)
        self._combo_original_export.setMinimumWidth(0)
        for mode, key in (
            ("all_pages", "invoices.export_originals_all_pages"),
            ("first_page", "invoices.export_originals_first_page"),
            ("none", "invoices.export_originals_none"),
        ):
            self._combo_original_export.addItem(tr(key), mode)
        self._combo_original_export.setAccessibleName(
            tr("invoices.export_originals_mode")
        )
        self._combo_original_export.setToolTip(
            tr("invoices.export_originals_tip")
        )
        self._combo_original_export.setCurrentIndex(
            max(0, self._combo_original_export.findData(
                self._original_export_mode
            ))
        )
        self._combo_original_export.currentIndexChanged.connect(
            self._on_export_original_mode_changed
        )
        row_original_options.addWidget(self._lbl_original_export)
        row_original_options.addWidget(self._combo_original_export, stretch=1)
        export_layout.addLayout(row_original_options)

        self._btn_export_selected = make_btn(
            tr("invoices.export_selected"),
            tr("invoices.export_selected_tip"),
            success=True,
        )
        bind_icon(self._btn_export_selected, "export", size=14, role="on_accent")
        self._btn_export_selected.clicked.connect(
            self._export_selected_pdf
        )
        self._btn_export_selected.setEnabled(False)

        self._btn_export_all = make_btn(
            tr("invoices.export_all"),
            tr("invoices.export_all_tip"),
            info=True,
        )
        bind_icon(self._btn_export_all, "export", size=14, role="on_accent")
        self._btn_export_all.clicked.connect(self._export_all_pdf)

        export_layout.addWidget(self._btn_export_selected)
        export_layout.addWidget(self._btn_export_all)

        # Markerbar: radmarkeringen ÄR exportvalet. Markeringen
        # bor per faktura-id och överlever filterbyte/refresh.
        self._lbl_export_selection = QLabel(
            tr("invoices.export_sel_none")
        )
        self._lbl_export_selection.setFont(make_tabular_font(10, True))
        self._lbl_export_selection.setWordWrap(True)
        self._lbl_export_selection.setMinimumWidth(0)
        self._lbl_export_selection.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._lbl_export_selection.setStyleSheet(
            "background:transparent;"
        )
        self._lbl_export_selection.setVisible(False)

        self._btn_mark_shown = make_btn(
            tr("invoices.mark_shown"),
            tr("invoices.mark_shown_tip"),
        )
        self._btn_mark_shown.setMinimumWidth(0)
        bind_icon(self._btn_mark_shown, "check", size=13)
        self._btn_mark_shown.clicked.connect(self._mark_all_shown)

        self._btn_clear_marked = make_btn(
            tr("invoices.clear_marked"),
            tr("invoices.clear_marked_tip"),
        )
        self._btn_clear_marked.setMinimumWidth(0)
        bind_icon(self._btn_clear_marked, "clear", size=13)
        self._btn_clear_marked.clicked.connect(
            self._clear_export_selection
        )
        self._btn_clear_marked.setEnabled(False)

        row_mark_btns = QHBoxLayout()
        row_mark_btns.setSpacing(4)
        row_mark_btns.addWidget(self._btn_mark_shown, stretch=1)
        row_mark_btns.addWidget(self._btn_clear_marked, stretch=1)
        export_layout.addLayout(row_mark_btns)
        export_layout.addWidget(self._lbl_export_selection)

        # Summering för BARA de markerade — visas kompakt när
        # minst en rad är ikryssad för export.
        self._marked_summary_wrap = QWidget()
        self._marked_summary_wrap.setStyleSheet("background:transparent;")
        row_marked = QVBoxLayout(self._marked_summary_wrap)
        row_marked.setContentsMargins(0, 2, 0, 0)
        row_marked.setSpacing(2)
        self._lbl_marked_cap = QLabel(tr("invoices.marked_label"))
        self._lbl_marked_cap.setFont(make_font(10, True))
        self._lbl_marked_cap.setStyleSheet("background:transparent;")
        self._lbl_marked_inv = QLabel("")
        self._lbl_marked_cred = QLabel("")
        self._lbl_marked_net = QLabel("")
        for _lbl in (
            self._lbl_marked_inv,
            self._lbl_marked_cred,
            self._lbl_marked_net,
        ):
            _lbl.setFont(make_tabular_font(10, True))
            _lbl.setStyleSheet("background:transparent;")
        row_marked_pair = QHBoxLayout()
        row_marked_pair.setSpacing(8)
        row_marked_pair.addWidget(self._lbl_marked_inv)
        row_marked_pair.addWidget(self._lbl_marked_cred)
        row_marked_pair.addStretch()
        row_marked.addWidget(self._lbl_marked_cap)
        row_marked.addLayout(row_marked_pair)
        row_marked.addWidget(self._lbl_marked_net)
        self._marked_summary_wrap.setVisible(False)
        export_layout.addWidget(self._marked_summary_wrap)
        side.addWidget(export_frame)
        side.addStretch()

        # ── Summering: tre beloppskort (ovanför tabellen, höger) ───────
        summary_frame = QFrame()
        summary_frame.setObjectName("SummaryStrip")
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(0, 2, 0, 2)
        summary_layout.setSpacing(4)
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        summary_layout.addLayout(cards_row)

        def _money_card(name: str, caption: str, value: QLabel) -> QFrame:
            card = QFrame()
            card.setObjectName(name)
            lay = QVBoxLayout(card)
            lay.setContentsMargins(14, 8, 14, 8)
            lay.setSpacing(2)
            cap = QLabel(caption)
            cap.setObjectName("MoneyCaption")
            self._money_caps[name] = cap
            cap.setFont(make_font(11, True))
            value.setFont(make_tabular_font(17, True))
            value.setObjectName("MoneyValue")
            lay.addWidget(cap)
            lay.addWidget(value)
            return card

        self._money_caps: dict[str, QLabel] = {}
        self._lbl_invoices = QLabel("0,00 SEK")
        self._lbl_credits = QLabel("0,00 SEK")
        self._lbl_att_betala = QLabel("0,00 SEK")
        cards_row.addWidget(
            _money_card("MoneyCard", tr("invoices.card_invoices"), self._lbl_invoices), 1
        )
        cards_row.addWidget(
            _money_card("MoneyCardCredit", tr("invoices.card_credits"), self._lbl_credits), 1
        )
        cards_row.addWidget(
            _money_card("MoneyCardTotal", tr("invoices.card_total"), self._lbl_att_betala), 1
        )
        self._cap_invoices = self._money_caps.get("MoneyCard")
        self._cap_credits = self._money_caps.get("MoneyCardCredit")
        self._cap_total = self._money_caps.get("MoneyCardTotal")

        meta = QHBoxLayout()
        meta.setSpacing(10)
        meta_stats = FlowLayout(spacing=12)
        self._lbl_count = QLabel(tr("invoices.rows", n=0, f=0, k=0))
        self._lbl_unpaid = QLabel(
            tr("invoices.unpaid", amount=fmt_amount(0))
        )
        self._lbl_overdue = QLabel(
            tr("invoices.overdue", amount=fmt_amount(0))
        )
        for lbl in (self._lbl_count, self._lbl_unpaid, self._lbl_overdue):
            lbl.setFont(make_tabular_font(11, True))
            lbl.setStyleSheet("background:transparent;")
            meta_stats.addWidget(lbl)
        meta.addLayout(meta_stats, stretch=1)
        self._density_label = QLabel(tr("invoices.table_density"))
        self._density_label.setObjectName("invoiceDensityLabel")
        self._density_selector = QComboBox()
        self._density_selector.setObjectName("invoiceDensitySelector")
        self._density_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self._density_selector.addItem(
            tr("invoices.density_comfortable"), "comfortable"
        )
        self._density_selector.addItem(
            tr("invoices.density_compact"), "compact"
        )
        self._density_selector.setAccessibleName(
            tr("invoices.table_density_accessible")
        )
        self._density_selector.setToolTip(
            tr("invoices.table_density_tip")
        )
        density_index = self._density_selector.findData(self._row_density)
        self._density_selector.setCurrentIndex(
            density_index if density_index >= 0 else 0
        )
        self._density_selector.currentIndexChanged.connect(
            self._on_row_density_changed
        )
        self._btn_columns = make_btn(
            tr("columns.button"), tr("columns.tip")
        )
        self._btn_columns.setObjectName("invoiceColumnsButton")
        bind_icon(self._btn_columns, "settings", size=14)
        self._btn_columns.clicked.connect(self._open_columns_menu)

        density_box = QHBoxLayout()
        density_box.setSpacing(6)
        density_box.addWidget(self._density_label)
        density_box.addWidget(self._density_selector)
        density_box.addWidget(self._btn_columns)
        meta.addLayout(density_box)
        summary_layout.addLayout(meta)
        self._right_layout.addWidget(summary_frame)

        # ── Snabbfilter-chips ovanför tabellen (frigör vänsterspalten) ──
        quick_frame = QFrame()
        quick_frame.setObjectName("QuickFilterBar")
        quick_layout = FlowLayout(
            quick_frame, spacing=6, margins=(8, 4, 8, 4)
        )
        self._lbl_quick_filter = QLabel(tr("invoices.quick_filter_label"))
        self._lbl_quick_filter.setFont(make_font(10, True))
        self._lbl_quick_filter.setMinimumHeight(26)
        self._lbl_quick_filter.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._lbl_quick_filter.setStyleSheet("background:transparent;")
        quick_layout.addWidget(self._lbl_quick_filter)

        self._chip_btns: dict[str, Any] = {}
        self._chip_icons: dict[str, str] = {}
        for mode, key, icon_name in (
            ("overdue", "invoices.chip_overdue", "alert"),
            ("today", "invoices.chip_today", "clock"),
            ("week", "invoices.chip_week", "calendar"),
        ):
            chip = make_btn(tr(key), tr(key))
            chip.setCheckable(True)
            chip.setMinimumWidth(0)
            bind_icon(chip, icon_name, size=13)
            chip.clicked.connect(
                lambda _checked=False, m=mode: self._on_chip(m)
            )
            self._chip_btns[mode] = chip
            self._chip_icons[mode] = icon_name
            quick_layout.addWidget(chip)
        self._right_layout.addWidget(quick_frame)

        # Beständig rad: markeringens summa (eller totalen att betala).
        # Ersätter den kortlivade statusradstexten så summan av det
        # man markerat alltid syns medan man arbetar.
        self._lbl_selection = QLabel("")
        self._lbl_selection.setFont(make_tabular_font(12, True))
        self._lbl_selection.setStyleSheet("background:transparent;")
        self._right_layout.addWidget(self._lbl_selection)

        # ── Tabell ─────────────────────────────────────────────────────
        # InvoiceTableModel äger endast presentationen av de synliga
        # raderna; QSortFilterProxyModel sköter sorteringen utan att
        # ändra eller kopiera fakturaregistret.
        self._invoice_model = InvoiceTableModel(
            page_counter=self._pages_for,
            status_row_bg=STATUS_ROW_BG,
            dark=self._is_dark(),
            parent=self,
        )
        self._invoice_proxy = QSortFilterProxyModel(self)
        self._invoice_proxy.setSourceModel(self._invoice_model)
        self._invoice_proxy.setSortRole(SORT_ROLE)
        self._invoice_proxy.setDynamicSortFilter(True)

        self._table = QTableView()
        self._table.setModel(self._invoice_proxy)
        self._table.setSortingEnabled(True)
        # Kolumner ska gå att flytta (dra i rubriken); sorteringen
        # sker via proxy-modellen med SORT_ROLE ovan.
        self._table.horizontalHeader().setSectionsMovable(True)
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
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._table.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self._table.setShowGrid(True)
        self._table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        self._invoice_model.exportMarkChanged.connect(
            self._on_export_mark_changed
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
        hh.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._column_header_menu)
        self._apply_row_density()
        QTimer.singleShot(0, self._fit_columns)

        # Mushjul-scroll direkt på tabellen
        self._table.wheelEvent = self._table_wheel  # type: ignore

        self._right_layout.addWidget(self._table, stretch=1)

        # ── Fast exportrad längst ner (alltid synlig) ──────────────────
        # Spegel av exportpanelen: valt antal + netto + knappen, så
        # man aldrig behöver skrolla upp i en lång lista för att se
        # vad som kommer att exporteras.
        sticky_frame = QFrame()
        sticky_frame.setObjectName("ExportStickyBar")
        sticky_layout = QHBoxLayout(sticky_frame)
        sticky_layout.setContentsMargins(10, 6, 10, 6)
        sticky_layout.setSpacing(10)
        self._lbl_sticky_selection = QLabel(
            tr("invoices.export_sel_none")
        )
        self._lbl_sticky_selection.setFont(make_tabular_font(12, True))
        self._lbl_sticky_selection.setWordWrap(True)
        self._lbl_sticky_selection.setStyleSheet(
            "background:transparent;"
        )
        self._btn_export_selected_sticky = make_btn(
            tr("invoices.export_selected"),
            tr("invoices.export_sticky_tip"),
            success=True,
        )
        self._btn_export_selected_sticky.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        bind_icon(self._btn_export_selected_sticky, "export", size=14, role="on_accent")
        self._btn_export_selected_sticky.clicked.connect(
            self._export_selected_pdf
        )
        self._btn_export_selected_sticky.setEnabled(False)
        sticky_layout.addWidget(self._lbl_sticky_selection, stretch=1)
        sticky_layout.addWidget(self._btn_export_selected_sticky)
        root.addWidget(sticky_frame)

        # ── Footer ─────────────────────────────────────────────────────
        root.addWidget(h_line())
        self._footer = QLabel(
            tr("common.footer_brand", year=COPYRIGHT_YEAR)
        )
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._footer.setFont(make_font(9))
        self._footer.setStyleSheet(
            "background:transparent;color:#718096;"
        )
        root.addWidget(self._footer)

    def _focus_search(self) -> None:
        """Ctrl+F: hoppa till sökfältet och markera befintlig text."""
        self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search.selectAll()

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
            # Fakturor-fliken visar BARA huvudregistret — det
            # exporterade/betalda bor i data/betalda/ och syns i
            # Historik-fliken i stället (aldrig i ATT BETALA).
            if hasattr(self._app, "get_active_invoices"):
                raw = self._app.get_active_invoices()
            else:
                raw = self._app.get_invoices()
            self._all_data = list(raw) if raw else []
        except Exception as exc:
            log.error("refresh error: %s", exc)
            self._all_data = []

        # Exportmarkeringen lever bara så länge posten finns kvar
        # i huvudregistret (exporterade/borttagna id:n städas bort).
        _valid = {str(r.get("id", "")) for r in self._all_data}
        self._marked_export_ids &= _valid

        self._refresh_supplier_selector()
        self._update_filter_supplier_combo()

        filtered = self._apply_filters()
        self._populate_table(filtered)
        self._update_summary(filtered)
        self._update_export_buttons()
        if hasattr(self, "_btn_link_credit"):
            has_credit = any(
                _to_float(r.get("total_amount")) < 0
                and str(r.get("status", "")) not in NON_UNPAID_STATUSES
                for r in self._all_data
            )
            self._btn_link_credit.setEnabled(has_credit)

    def _archive_exported(
        self, chunk: list[dict], payment_date: str = ""
    ) -> int:
        """Efter en LYCKAD delfil: posterna markeras Betald med
        exportens betalningsdatum och flyttas till leverantörens
        fil i data/betalda/ (Historik) — därifrån ser importens
        dubblettskydd dem, så de aldrig registreras igen.
        Faller tillbaka på app-fasaden om motormetoden saknas.
        Aldrig ett exportfel."""
        ids = [str(i.get("id", "")) for i in chunk if i.get("id")]
        if not ids:
            return 0
        engine = getattr(self._app, "invoices", None)
        if engine is not None and hasattr(
            engine, "mark_exported_paid"
        ):
            try:
                return int(
                    engine.mark_exported_paid(ids, payment_date)
                )
            except Exception as exc:
                log.warning("EXPORT mark_exported_paid: %s", exc)
        count = 0
        for rid in ids:
            try:
                self._app.update_invoice(
                    rid,
                    {
                        "status": "Betald",
                        "payment_date": payment_date,
                    },
                )
                count += 1
            except Exception:
                pass
        return count

    def _get_exportable(self) -> list[dict]:
        """
        Underlaget till "Exportera alla": obetalda och aktiva.

        Betald/Arkiverad/Makulerad är ALLTID uteslutna — markerar
        man en faktura som betald försvinner den alltså ur
        exporten och kan inte betalas dubbelt av misstag.
        (Exportknappens antal använder samma urval.)
        """
        return [
            r
            for r in self._all_data
            if r.get("status") not in NON_UNPAID_STATUSES
        ]

    def _get_selected_exportable(self) -> list[dict]:
        """Markerade för export: exportmarkeringen (per id, även
        rader som ett filter just nu döljer) ∩ exporterbara.
        Betald/Arkiverad/Makulerad ingår alltså aldrig, precis
        som i "Exportera alla"."""
        return [
            r
            for r in self._get_exportable()
            if str(r.get("id", "")) in self._marked_export_ids
        ]

    def _apply_table_selection(self) -> None:
        """Speglar exportmarkeringarna per faktura-id i tabellmodellen."""
        self._populating_table = True
        try:
            self._invoice_model.set_marked_export_ids(
                self._marked_export_ids
            )
        finally:
            self._populating_table = False
        self._update_export_buttons()
        self._update_buttons()

    def _on_export_mark_changed(self, rid: str, checked: bool) -> None:
        """Tar emot kryssrutans exportval från QAbstractTableModel."""
        if getattr(self, "_populating_table", False) or not rid:
            return
        if checked:
            if (
                rid not in self._marked_export_ids
                and len(self._marked_export_ids) >= EXPORT_MARK_LIMIT
            ):
                # Tak (användarkrav): högst 10 rader markerade samtidigt.
                self._apply_table_selection()
                self._status(tr(
                    "invoices.export_mark_limit", n=EXPORT_MARK_LIMIT,
                ))
                return
            self._marked_export_ids.add(str(rid))
        else:
            self._marked_export_ids.discard(str(rid))
        self._update_export_buttons()

    def _mark_all_shown(self) -> None:
        """Markerar rader som visas just nu för export — högst 10."""
        shown = [i for i in self._displayed_ids if i]
        room = max(0, EXPORT_MARK_LIMIT - len(self._marked_export_ids))
        picked = shown[:room]
        self._marked_export_ids |= set(picked)
        if len(shown) > len(picked):
            # Fler synliga än taket tillåter — säg det tydligt.
            self._status(tr(
                "invoices.export_mark_limit", n=EXPORT_MARK_LIMIT,
            ))
        self._apply_table_selection()

    def _clear_export_selection(self) -> None:
        """Rensar exportmarkeringen helt."""
        self._marked_export_ids = set()
        self._apply_table_selection()

    def _include_originals(self) -> bool:
        """Whether this user's export preference includes source invoices."""
        return self._original_export_mode != "none"

    def _original_first_page_only(self) -> bool:
        """Whether PDF originals should be limited to their first page."""
        return self._original_export_mode == "first_page"

    def _update_export_buttons(self) -> None:
        """Uppdaterar exportknappar (alla/markerade), markerings-
        raden och historikräknaren."""
        exportable = self._get_exportable()
        n = len(exportable)
        self._btn_export_all.setEnabled(n > 0)
        self._btn_export_all.setText(
            tr("invoices.export_all_n", n=n)
            if n > 0
            else tr("invoices.export_none")
        )
        selected = self._get_selected_exportable()
        if hasattr(self, "_btn_export_selected"):
            m = len(selected)
            self._btn_export_selected.setEnabled(m > 0)
            if m > 0:
                net = round(
                    sum(
                        _to_float(r.get("total_amount"))
                        for r in selected
                    ),
                    2,
                )
                self._btn_export_selected.setText(
                    tr(
                        "invoices.export_selected_n",
                        n=m,
                        amount=fmt_amount(net),
                    )
                )
            else:
                self._btn_export_selected.setText(
                    tr("invoices.export_selected")
                )
        if hasattr(self, "_lbl_export_selection"):
            if selected:
                net = round(
                    sum(
                        _to_float(r.get("total_amount"))
                        for r in selected
                    ),
                    2,
                )
                self._lbl_export_selection.setText(
                    tr(
                        "invoices.export_sel_info",
                        n=len(selected),
                        amount=fmt_amount(net),
                    )
                )
            else:
                self._lbl_export_selection.setText(
                    tr("invoices.export_sel_none")
                )
            self._lbl_export_selection.setVisible(bool(selected))
        if hasattr(self, "_btn_clear_marked"):
            self._btn_clear_marked.setEnabled(
                bool(self._marked_export_ids)
            )
        # Summering för bara de markerade (exportpanelen) — visas
        # kompakt när minst en rad är markerad + spegling till sticky.
        if hasattr(self, "_lbl_marked_cap"):
            # Räknare n/10 (besked 26): användaren ser direkt hur
            # många som är ikryssade och hur nära exporttaket hen är.
            self._lbl_marked_cap.setText(
                tr(
                    "invoices.marked_cap_count",
                    n=len(selected),
                    cap=EXPORT_MARK_LIMIT,
                )
                if selected
                else tr("invoices.marked_label")
            )
        if hasattr(self, "_lbl_marked_inv"):
            _amounts = [
                _to_float(r.get("total_amount")) for r in selected
            ]
            _inv_sum = round(
                sum(v for v in _amounts if v > 0), 2
            )
            _cred_sum = round(
                sum(v for v in _amounts if v < 0), 2
            )
            self._lbl_marked_inv.setText(
                f"{tr('invoices.card_invoices')}  "
                f"{fmt_amount(_inv_sum)}"
            )
            self._lbl_marked_cred.setText(
                f"{tr('invoices.card_credits')}  "
                f"{fmt_amount(_cred_sum)}"
            )
            self._lbl_marked_net.setText(
                f"{tr('invoices.card_total')}  "
                f"{fmt_amount(round(_inv_sum + _cred_sum, 2))}"
            )
        if hasattr(self, "_marked_summary_wrap"):
            self._marked_summary_wrap.setVisible(bool(selected))
        if hasattr(self, "_lbl_sticky_selection"):
            self._lbl_sticky_selection.setText(
                self._lbl_export_selection.text()
                if hasattr(self, "_lbl_export_selection") else ""
            )
        if hasattr(self, "_btn_export_selected_sticky"):
            self._btn_export_selected_sticky.setEnabled(
                self._btn_export_selected.isEnabled()
            )
            self._btn_export_selected_sticky.setText(
                self._btn_export_selected.text()
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

        # Dropdownen högst upp väljer både leverantör för nya fakturor
        # och leverantörsgruppen som visas i listan. Under filtren finns
        # ett extra leverantörsfilter; båda får kombineras.
        selector_supplier = self._supplier_selector_filter()
        if selector_supplier:
            wanted = selector_supplier.casefold()
            data = [
                r for r in data
                if str(r.get("supplier", "") or "").strip().casefold()
                == wanted
            ]

        # Leverantörs-filter ("" = alla; annars leverantörens namn)
        if sup_f:
            wanted = str(sup_f).strip().casefold()
            data = [
                r for r in data
                if str(r.get("supplier", "") or "").strip().casefold()
                == wanted
            ]

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
        """Synkar chip-tillstånd och ikonfärg utan att radera QSS-temat."""
        theme = getattr(self, "_current_theme", None) or None
        chip_icons = getattr(self, "_chip_icons", {})
        for mode, btn in getattr(self, "_chip_btns", {}).items():
            active = mode == self._chip_mode
            btn.setChecked(active)
            icon_name = chip_icons.get(mode)
            if icon_name:
                bind_icon(
                    btn,
                    icon_name,
                    role="on_accent" if active else "text_strong",
                    size=13,
                    theme=theme,
                )
            if theme is None:
                btn.setStyleSheet(
                    "background:#d4a017;color:#111111;font-weight:800;"
                    if active
                    else ""
                )

    # ══════════════════════════════════════════════════════════════════
    #  LEVERANTÖRSVÄLJARE
    # ══════════════════════════════════════════════════════════════════

    def _refresh_supplier_selector(self) -> None:
        """Uppdaterar leverantörer med antal aktiva fakturor per namn."""
        current = self._selected_supplier
        try:
            suppliers = self._app.get_suppliers()
        except Exception:
            suppliers = []
        counts: dict[str, int] = {}
        for invoice in self._all_data:
            name = str(invoice.get("supplier", "") or "").strip()
            if name:
                key = name.casefold()
                counts[key] = counts.get(key, 0) + 1

        favorites = sorted(
            (str(s.get("name", "")).strip()
             for s in suppliers
             if s.get("name") and s.get("favorite")),
            key=str.casefold,
        )
        others = sorted(
            (str(s.get("name", "")).strip()
             for s in suppliers
             if s.get("name") and not s.get("favorite")),
            key=str.casefold,
        )
        self._favorite_names = set(favorites)
        names = favorites + others

        self._sup_selector.blockSignals(True)
        self._sup_selector.clear()
        self._sup_selector.addItem("", "")
        for name in names:
            count = counts.get(name.casefold(), 0)
            self._sup_selector.addItem(
                tr("invoices.supplier_with_count", name=name, n=count),
                name,
            )
            index = self._sup_selector.count() - 1
            self._sup_selector.setItemData(
                index,
                tr("invoices.supplier_active_count_tip", n=count),
                Qt.ItemDataRole.ToolTipRole,
            )

        completer = QCompleter(names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._sup_selector.setCompleter(completer)

        idx = next(
            (i for i in range(self._sup_selector.count())
             if str(self._sup_selector.itemData(i) or "").strip().casefold()
             == current.strip().casefold()),
            -1,
        )
        if idx >= 0:
            self._sup_selector.setCurrentIndex(idx)
        else:
            # The selector stays editable for new supplier names. Preserve
            # partial/free-form text, but do not treat it as a filter.
            self._sup_selector.setCurrentIndex(0)
            if current:
                self._sup_selector.setCurrentText(current)
        self._sup_selector.blockSignals(False)

        self._update_supplier_info(self._selected_supplier)

    def _on_supplier_selector_changed(self, _name: str) -> None:
        """Visar kanoniskt namn och filtrerar fakturalistan vid val."""
        self._update_supplier_info(self._selected_supplier)
        if self._initialised:
            self._search_timer.start()

    def _update_supplier_info(self, name: str) -> None:
        """Visar leverantörsinfo (org.nr, BG/PG/IBAN) bredvid väljaren."""
        name = str(name or "").strip()
        if not name:
            self._lbl_supplier_info.setText(tr("invoices.none_chosen"))
            return

        try:
            suppliers = self._app.get_suppliers()
            sup = next(
                (
                    s
                    for s in suppliers
                    if str(s.get("name", "") or "").strip() == name
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
        """Kanoniskt namn endast när dropdownens rad faktiskt är vald."""
        current_text = self._sup_selector.currentText().strip()
        index = self._sup_selector.currentIndex()
        if (
            index >= 0
            and current_text.casefold()
            == self._sup_selector.itemText(index).strip().casefold()
        ):
            value = self._sup_selector.itemData(index)
            if value is not None:
                return str(value).strip()
        # I redigeringsläge kan currentIndex fortfarande peka på den
        # tidigare raden medan användaren skriver. Friformstexten måste
        # då förbli ofiltrerad tills den matchar ett registrerat namn.
        return current_text

    def _supplier_selector_filter(self) -> str:
        """Returnerar bara ett faktiskt registerval som tabellfilter.

        Dropdownen är redigerbar för nya leverantörsnamn. En ofärdig
        friformstext ska inte tömma fakturalistan medan användaren skriver.
        """
        selected = self._selected_supplier.casefold()
        if not selected:
            return ""
        for index in range(self._sup_selector.count()):
            option = str(
                self._sup_selector.itemData(index)
                or self._sup_selector.itemText(index)
            ).strip()
            if option and option.casefold() == selected:
                return option
        return ""

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
        """Uppdaterar InvoiceTableModel med synliga fakturor."""
        self._populating_table = True
        self._displayed_ids = [
            str(row.get("id", "")) for row in data if row.get("id")
        ]
        self._invoice_model.set_dark(self._is_dark())
        self._invoice_model.set_rows(data)
        self._invoice_model.set_marked_export_ids(
            self._marked_export_ids
        )
        self._fit_columns()
        self._populating_table = False
        # Exportmarkeringen är per id och ska överleva filterbyte,
        # sortering och datamodellens återställning.
        self._apply_table_selection()

    def _fit_columns(self) -> None:
        column_count = self._table.model().columnCount()
        if column_count == len(COL_WIDTHS) + 1:
            # Datumkolumnerna får aldrig bli så smala att bara årtalet
            # syns ("2021-…") — bredden mäts ur tabellfonten.
            date_width = date_column_width()
            mins = [44] + [
                date_width if key in DATE_COLUMN_KEYS else 36
                for key in COL_KEYS
            ]
            preferred = [44] + [
                max(width, date_width) if key in DATE_COLUMN_KEYS
                else width
                for key, width in zip(COL_KEYS, COL_WIDTHS)
            ]
            visible_pref = sum(
                w for i, w in enumerate(preferred)
                if not self._table.isColumnHidden(i)
            )
            vp = max(
                self._table.viewport().width(), self._table.width()
            )
            if vp >= visible_pref:
                fit_table_columns(self._table, preferred, mins)
                # fit_table_columns lägger eventuell överskottsbredd
                # på första synliga kolumnen — kryssrutan ska stanna på
                # 44 px, så överskottet flyttas till Leverantör
                # (kolumn 2).
                check_w = self._table.columnWidth(0)
                if check_w > 44:
                    target_col = next(
                        (
                            i for i in (2, 3, 1)
                            if i < column_count
                            and not self._table.isColumnHidden(i)
                        ),
                        2,
                    )
                    self._table.setColumnWidth(
                        target_col,
                        self._table.columnWidth(target_col)
                        + (check_w - 44),
                    )
                self._table.setColumnWidth(0, 44)
            else:
                # Smal viewport: BEHÅLL läsbara föredragna bredder
                # och låt horisontella rullisten ta resten — då
                # kläms/kapar tabellen aldrig kolumnerna oläsliga.
                for i, w in enumerate(preferred):
                    if not self._table.isColumnHidden(i):
                        self._table.setColumnWidth(i, w)
        else:
            fit_table_columns(
                self._table,
                COL_WIDTHS,
                [
                    date_column_width() if key in DATE_COLUMN_KEYS else 36
                    for key in COL_KEYS
                ],
            )

    def _load_hidden_columns(self) -> set[str]:
        raw = self._get_setting("invoice_hidden_columns", [])
        valid = set(COL_KEYS) - _INVOICE_LOCKED_KEYS
        return {str(k) for k in (raw or []) if str(k) in valid}

    def _save_hidden_columns(self) -> None:
        self._save_setting(
            "invoice_hidden_columns", sorted(self._hidden_columns)
        )

    def _apply_hidden_columns(self) -> None:
        self._hidden_columns -= _INVOICE_LOCKED_KEYS
        for idx, key in enumerate(COL_KEYS, start=1):
            self._table.setColumnHidden(idx, key in self._hidden_columns)

    def _set_column_visible(self, key: str, visible: bool) -> None:
        if key in _INVOICE_LOCKED_KEYS:
            return
        if visible:
            self._hidden_columns.discard(key)
        else:
            self._hidden_columns.add(key)
        self._save_hidden_columns()
        self._apply_hidden_columns()
        self._fit_columns()

    def _set_compact_columns(self, compact: bool) -> None:
        self._hidden_columns = (
            set(INVOICE_COMPACT_HIDDEN_KEYS) if compact else set()
        )
        self._save_hidden_columns()
        self._apply_hidden_columns()
        self._fit_columns()

    def _build_columns_menu(self) -> QMenu:
        menu = QMenu(self)
        act_compact = menu.addAction(tr("columns.compact"))
        if act_compact is not None:
            act_compact.setCheckable(True)
            act_compact.setChecked(
                self._hidden_columns == set(INVOICE_COMPACT_HIDDEN_KEYS)
            )
            act_compact.triggered.connect(
                lambda: self._set_compact_columns(True)
            )
        act_all = menu.addAction(tr("columns.show_all"))
        if act_all is not None:
            act_all.setCheckable(True)
            act_all.setChecked(not self._hidden_columns)
            act_all.triggered.connect(
                lambda: self._set_compact_columns(False)
            )
        menu.addSeparator()
        headers = tr_list("invoices.columns")
        if len(headers) != len(COL_KEYS):
            headers = [c[0] for c in COLUMNS]
        for key, label in zip(COL_KEYS, headers):
            if key in _INVOICE_LOCKED_KEYS:
                continue
            act = menu.addAction(label)
            if act is not None:
                act.setCheckable(True)
                act.setChecked(key not in self._hidden_columns)
                act.triggered.connect(
                    lambda checked, k=key: self._set_column_visible(k, checked)
                )
        return menu

    def _open_columns_menu(self) -> None:
        menu = self._build_columns_menu()
        pos = self._btn_columns.mapToGlobal(
            self._btn_columns.rect().bottomLeft()
        )
        menu.exec(pos)

    def _column_header_menu(self, pos) -> None:
        menu = self._build_columns_menu()
        menu.exec(self._table.horizontalHeader().mapToGlobal(pos))

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

    def _on_selection_changed(self, *_args: Any) -> None:
        # Radmarkeringen styr Redigera/Ta bort/Slå ihop/Markera
        # betald — exportvalet bor i kryssrutorna (kolumn 0) och
        # rörs INTE av radklick, så man kan titta på en enskild
        # faktura utan att tappa det man kryssat för export.
        self._update_export_buttons()
        self._update_buttons()
        inv = self._selected_invoice()
        if inv:
            self.invoice_selected.emit(inv)

    def _update_buttons(self) -> None:
        single = self._selected_id() is not None
        ids = self._selected_ids()
        multi = len(ids) > 0
        self._btn_edit.setEnabled(single)
        self._btn_delete.setEnabled(multi)
        self._btn_delete.setText(
            tr("invoices.delete_selected_n", n=len(ids))
            if len(ids) > 1 else tr("invoices.delete")
        )
        if hasattr(self, "_btn_delete_all"):
            self._btn_delete_all.setEnabled(bool(self._all_data))
        self._btn_duplicate.setEnabled(single)
        self._btn_mark_paid.setEnabled(multi)
        self._btn_combine.setEnabled(len(ids) >= 2)
        if hasattr(self, "_btn_link_credit"):
            has_credit = any(
                _to_float(r.get("total_amount")) < 0
                and str(r.get("status", "")) not in NON_UNPAID_STATUSES
                for r in self._all_data
            ) or any(
                _to_float(r.get("total_amount")) < 0
                for r in self._selected_invoices()
            )
            self._btn_link_credit.setEnabled(has_credit)
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
        indexes = self._table.selectionModel().selectedRows(0)
        if not indexes:
            return None
        uid = indexes[0].data(Qt.ItemDataRole.UserRole)
        return str(uid) if uid else None

    def _selected_ids(self) -> list[str]:
        """Unika id:n för alla markerade rader (ordningsbevarande)."""
        seen: set[str] = set()
        ids: list[str] = []
        for index in self._table.selectionModel().selectedRows(0):
            rid = index.data(Qt.ItemDataRole.UserRole)
            if rid and str(rid) not in seen:
                seen.add(str(rid))
                ids.append(str(rid))
        return ids

    def _selected_invoices(self) -> list[dict]:
        """Alla markerade fakturor (i markeringsordning)."""
        by_id = {str(r.get("id", "")): r for r in self._all_data}
        return [
            by_id[i] for i in self._selected_ids() if i in by_id
        ]

    def _selected_invoice(self) -> dict | None:
        sid = self._selected_id()
        if not sid:
            return None
        return next(
            (r for r in self._all_data if str(r.get("id", "")) == sid),
            None,
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

    def _get_setting(self, key: str, default: Any = None) -> Any:
        getter = getattr(self._app, "get_setting", None)
        if callable(getter):
            try:
                value = getter(key, default)
                if value is not None:
                    return value
            except TypeError:
                try:
                    value = getter(key)
                    if value is not None:
                        return value
                except Exception:
                    pass
            except Exception:
                pass
        try:
            return self._app.settings.get(key, default)
        except Exception:
            return default

    def _load_original_export_mode(self) -> str:
        include = bool(self._get_setting(
            "export_include_originals", True
        ))
        first_page = bool(self._get_setting(
            "export_original_first_page_only", False
        ))
        if not include:
            return "none"
        return "first_page" if first_page else "all_pages"

    def _save_setting(self, key: str, value: Any) -> None:
        setter = getattr(self._app, "set_setting", None)
        if callable(setter):
            try:
                setter(key, value)
                return
            except Exception as exc:
                log.debug("save setting %s: %s", key, exc)
        settings = getattr(self._app, "settings", None)
        try:
            setter = getattr(settings, "set", None)
            if callable(setter):
                setter(key, value)
            elif isinstance(settings, dict):
                settings[key] = value
        except Exception as exc:
            log.debug("save setting %s: %s", key, exc)

    def _on_export_original_mode_changed(self, index: int) -> None:
        combo = getattr(self, "_combo_original_export", None)
        if combo is None or index < 0:
            return
        mode = str(combo.itemData(index) or "")
        if mode not in {"all_pages", "first_page", "none"}:
            return
        self._original_export_mode = mode
        include = mode != "none"
        first_page = mode == "first_page"
        self._save_setting("export_include_originals", include)
        self._save_setting(
            "export_original_first_page_only", first_page
        )

    def _load_row_density(self) -> str:
        """Läser tabellens täthet utan att kräva en viss settings-fasad."""
        key = "invoice_table_density"
        value = None
        try:
            getter = getattr(self._app, "get_setting", None)
            if callable(getter):
                value = getter(key)
        except Exception:
            pass
        if value is None:
            try:
                value = self._app.settings.get(key)
            except Exception:
                value = None
        return "compact" if str(value or "").casefold() == "compact" \
            else "comfortable"

    def _save_row_density(self, density: str) -> None:
        key = "invoice_table_density"
        try:
            setter = getattr(self._app, "set_setting", None)
            if callable(setter):
                setter(key, density)
                return
        except Exception as exc:
            log.debug("save invoice density: %s", exc)
        settings = getattr(self._app, "settings", None)
        try:
            setter = getattr(settings, "set", None)
            if callable(setter):
                setter(key, density)
            elif isinstance(settings, dict):
                settings[key] = density
        except Exception as exc:
            log.debug("save invoice density: %s", exc)

    def _on_row_density_changed(self, index: int) -> None:
        density = str(self._density_selector.itemData(index) or "")
        if density not in {"compact", "comfortable"}:
            return
        if density == self._row_density:
            self._apply_row_density()
            return
        self._row_density = density
        self._apply_row_density()
        self._save_row_density(density)
        if self._current_theme:
            self.apply_theme(self._current_theme)

    def _apply_row_density(self) -> None:
        table = getattr(self, "_table", None)
        if table is None:
            return
        header = table.verticalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        set_table_default_row_height(
            table,
            TABLE_ROW_HEIGHT_COMPACT
            if self._row_density == "compact"
            else TABLE_ROW_HEIGHT_COMFORTABLE,
        )

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
        self._sup_selector.setToolTip(tr("invoices.supplier_selector_tip"))
        self._search.setPlaceholderText(tr("invoices.search_ph"))
        attach_search_icon(
            self._search, size=14,
            theme=getattr(self, "_current_theme", None) or None,
        )
        self._search.setToolTip(tr("invoices.search_shortcut_tip"))
        self._table.setToolTip(tr("invoices.table_keyboard_tip"))
        self._btn_add.setText(tr("invoices.add"))
        self._btn_add.setToolTip(tr("invoices.add_tip"))
        self._btn_edit.setText(tr("invoices.edit"))
        self._btn_edit.setToolTip(tr("invoices.edit_tip"))
        self._btn_delete.setText(tr("invoices.delete"))
        self._btn_duplicate.setText(tr("invoices.duplicate"))
        self._btn_duplicate.setToolTip(tr("invoices.duplicate_tip"))
        self._btn_mark_paid.setText(tr("invoices.mark_paid"))
        self._btn_mark_paid.setToolTip(tr("invoices.mark_paid_tip"))
        self._btn_pay_today.setText(tr("invoices.pay_today"))
        self._btn_pay_today.setToolTip(tr("invoices.pay_today_tip"))
        for _mode, _btn in getattr(self, "_chip_btns", {}).items():
            _btn.setText(tr(f"invoices.chip_{_mode}"))
            _btn.setToolTip(tr(f"invoices.chip_{_mode}"))
        if hasattr(self, "_lbl_quick_filter"):
            self._lbl_quick_filter.setText(tr("invoices.quick_filter_label"))
        if hasattr(self, "_btn_more_actions"):
            self._btn_more_actions.setText(tr("invoices.more_actions"))
            self._btn_more_actions.setToolTip(tr("invoices.more_actions_tip"))
        self._btn_combine.setText(tr("combine.button"))
        self._btn_combine.setToolTip(tr("combine.tip"))
        if hasattr(self, "_btn_link_credit"):
            self._btn_link_credit.setText(tr("credit.link_button"))
            self._btn_link_credit.setToolTip(tr("credit.link_tip"))
        if hasattr(self, "_btn_refresh"):
            self._btn_refresh.setText(tr("invoices.refresh"))
            self._btn_refresh.setToolTip(tr("invoices.refresh_tip"))
        if hasattr(self, "_btn_undo"):
            self._btn_undo.setText(tr("invoices.undo"))
            self._btn_undo.setToolTip(tr("invoices.undo_tip"))
        if hasattr(self, "_lbl_export_heading"):
            self._lbl_export_heading.setText(tr("invoices.export_heading"))
        if hasattr(self, "_btn_export_menu"):
            self._btn_export_menu.setText(tr("invoices.export_tools"))
            self._btn_export_menu.setToolTip(tr("invoices.export_tools_tip"))
        if hasattr(self, "_btn_export_selected"):
            self._btn_export_selected.setText(
                tr("invoices.export_selected")
            )
        if hasattr(self, "_btn_mark_shown"):
            self._btn_mark_shown.setText(tr("invoices.mark_shown"))
            self._btn_mark_shown.setToolTip(tr("invoices.mark_shown_tip"))
        if hasattr(self, "_btn_clear_marked"):
            self._btn_clear_marked.setText(
                tr("invoices.clear_marked")
            )
            self._btn_clear_marked.setToolTip(
                tr("invoices.clear_marked_tip")
            )
        if hasattr(self, "_btn_delete_all"):
            self._btn_delete_all.setText(tr("invoices.delete_all"))
            self._btn_delete_all.setToolTip(
                tr("invoices.delete_all_tip")
            )
        if hasattr(self, "_btn_delete"):
            self._btn_delete.setToolTip(tr("invoices.delete_tip"))
        self._btn_export_all.setText(tr("invoices.export_all"))
        self._btn_export_all.setToolTip(tr("invoices.export_all_tip"))
        self._btn_history.setText(tr("invoices.history"))
        self._btn_history.setToolTip(tr("invoices.history_tip"))
        self._btn_open_export.setText(tr("invoices.open_export_folder"))
        self._btn_open_export.setToolTip(tr("invoices.open_export_tip"))
        if hasattr(self, "_btn_columns"):
            self._btn_columns.setText(tr("columns.button"))
            self._btn_columns.setToolTip(tr("columns.tip"))
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
        if hasattr(self, "_lbl_marked_cap"):
            self._lbl_marked_cap.setText(tr("invoices.marked_label"))
        if hasattr(self, "_btn_export_selected_sticky"):
            self._btn_export_selected_sticky.setText(
                tr("invoices.export_selected")
            )
            self._btn_export_selected_sticky.setToolTip(
                tr("invoices.export_sticky_tip")
            )
        if hasattr(self, "_footer"):
            self._footer.setText(
                tr("common.footer_brand", year=COPYRIGHT_YEAR)
            )
        if hasattr(self, "_density_label"):
            self._density_label.setText(tr("invoices.table_density"))
            self._density_selector.setItemText(
                self._density_selector.findData("comfortable"),
                tr("invoices.density_comfortable"),
            )
            self._density_selector.setItemText(
                self._density_selector.findData("compact"),
                tr("invoices.density_compact"),
            )
            self._density_selector.setAccessibleName(
                tr("invoices.table_density_accessible")
            )
            self._density_selector.setToolTip(
                tr("invoices.table_density_tip")
            )
        if hasattr(self, "_lbl_original_export"):
            self._lbl_original_export.setText(
                tr("invoices.export_originals_mode")
            )
            for mode, key in (
                ("all_pages", "invoices.export_originals_all_pages"),
                ("first_page", "invoices.export_originals_first_page"),
                ("none", "invoices.export_originals_none"),
            ):
                idx = self._combo_original_export.findData(mode)
                if idx >= 0:
                    self._combo_original_export.setItemText(idx, tr(key))
            self._combo_original_export.setAccessibleName(
                tr("invoices.export_originals_mode")
            )
            self._combo_original_export.setToolTip(
                tr("invoices.export_originals_tip")
            )
            self._btn_export_selected.setToolTip(
                tr("invoices.export_selected_tip")
            )
        headers = tr_list("invoices.columns")
        if len(headers) == len(COLUMNS):
            self._invoice_model.set_headers(headers)
            self._refresh_supplier_selector()
        self._update_buttons()

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
                    tr("invoices.unknown_supplier_title"),
                    tr("invoices.unknown_supplier_body", name=name),
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
            dlg.setModal(True)
            dlg.setSizeGripEnabled(True)
            if callable(fit_dialog_to_screen):
                fit_dialog_to_screen(
                    dlg, 460, 340, minimum_width=360, minimum_height=260,
                )
            else:
                dlg.setMinimumWidth(380)

            root = QVBoxLayout(dlg)
            root.setSpacing(12)
            root.setContentsMargins(20, 16, 20, 16)
            root.addWidget(QLabel(tr("export.choose_for", n=n)))
            root.addWidget(
                QLabel(
                    tr(
                        "invoices.fallback_to_pay",
                        amount=fmt_amount(att_betala, currency),
                    )
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
        """Registrera ny faktura; välj leverantör här om topplistan är tom."""
        names = self._supplier_names_list()

        # Leverantörsregister tomt → hänvisa till leverantörsfliken
        if not names:
            reply = QMessageBox.question(
                self,
                tr("invoices.no_suppliers_title"),
                tr("invoices.no_suppliers_body"),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._switch_to_suppliers_tab()
            return

        # Ett toppval förifyller dialogen, men det är inget förvillkor.
        # Vid tom topp-lista visas en leverantörsväljare i dialogen.
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
                tr("invoices.duplicate_confirm_title"),
                tr(
                    "invoices.duplicate_confirm_body",
                    nr=data["invoice_number"],
                    supplier=data["supplier"],
                ),
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
                self, tr("common.error"), tr("invoices.add_failed", error=exc)
            )
            return

        self._do_refresh()
        self._status(
            f"✅  "
            + tr(
                "invoices.registered_status",
                nr=data["invoice_number"],
                amount=fmt_amount(data["total_amount"]),
            )
        )

    def _switch_to_suppliers_tab(self) -> None:
        """Byter till leverantörsfliken (visar den om den är dold)."""
        try:
            top = self.window()
            goto_tab = getattr(top, "_goto_tab", None)
            tab_title = getattr(top, "_tab_title", None)
            if callable(goto_tab) and callable(tab_title):
                goto_tab("suppliers", tab_title("suppliers"))
                return
            tabs = getattr(top, "tabs", None)
            if tabs is None:
                return
            for i in range(tabs.count()):
                if (
                    "Leverantör" in tabs.tabText(i)
                    or "Supplier" in tabs.tabText(i)
                ):
                    tabs.setCurrentIndex(i)
                    return
            show_fn = getattr(top, "_set_tab_visible", None)
            if callable(show_fn):
                show_fn("suppliers", tr("tab.suppliers"), True)
                for i in range(tabs.count()):
                    if (
                        "Leverantör" in tabs.tabText(i)
                        or "Supplier" in tabs.tabText(i)
                    ):
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
        before_inv = dict(inv)
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
                self,
                tr("common.error"),
                tr("invoices.update_failed", error=exc),
            )
            return
        learn_note = self._learn_from_edited_invoice(before_inv, data)
        self._do_refresh()
        msg = "✅  " + tr("invoices.updated_status", nr=data["invoice_number"])
        if learn_note:
            msg += f"  ·  {learn_note}"
        self._status(msg)

    def _sync_import_view_learning(self) -> None:
        """Synkar Import-flikens mall-/inlärningscache och prövar om parkerat."""
        try:
            win = self.window()
            if win is None or win is self:
                return
            for child in win.findChildren(QWidget):
                fn = getattr(child, "reload_learning_and_rescan", None)
                if callable(fn):
                    fn()
                    break
        except Exception:
            pass

    def _learn_from_edited_invoice(
        self, before_inv: dict, after_data: dict
    ) -> str:
        """Lär från redigering i Fakturor-fliken (t.ex. rättad automatchning)."""
        try:
            try:
                from ui.scan_import_view import _scan_module
            except ImportError:
                from scan_import_view import _scan_module  # type: ignore[no-redef]
            si = _scan_module()
            learn_fn = getattr(si, "learn_from_edited_auto_match", None)
            if not callable(learn_fn):
                return ""
            data_dir = self._scan_data_dir()
            learning_path = data_dir / "match_memory.json"
            templates_path = data_dir / "invoice_templates.json"
            templates = self._load_scan_templates(si)
            learning = si.load_match_learning(learning_path)
            try:
                suppliers = list(self._app.get_suppliers() or [])
            except Exception:
                suppliers = []
            att = str(
                after_data.get("attachment")
                or before_inv.get("attachment")
                or ""
            ).strip()
            res = learn_fn(
                templates,
                learning,
                str(before_inv.get("supplier") or ""),
                before_inv,
                after_data,
                path=att,
                suppliers=suppliers,
                templates_path=templates_path,
                learning_path=learning_path,
                source="invoices_edit",
            )
            if not res.get("changed"):
                return ""
            parts: list[str] = [tr("invoices.learn_updated")]
            if res.get("counter_reset"):
                parts.append(tr(
                    "scan.match_correction_reset",
                    supplier=before_inv.get("supplier", ""),
                    n=si.LEARNED_SUPPLIER_CONFIRMATIONS,
                ))
            if res.get("replaced_variants"):
                parts.append(tr(
                    "invoices.learn_replaced_variants",
                    n=len(res["replaced_variants"]),
                    count=res.get("template_count", 0),
                    max=si.MAX_TEMPLATES_PER_SUPPLIER,
                ))
            elif res.get("template_action") == "ny_variant_sparad":
                parts.append(tr(
                    "invoices.learn_new_variant",
                    count=res.get("template_count", 0),
                    max=si.MAX_TEMPLATES_PER_SUPPLIER,
                ))
            if res.get("unconfirmed_variants"):
                parts.append(tr("invoices.learn_unconfirmed_variants"))
            if res.get("auto_logo_saved"):
                parts.append(tr(
                    "scan.learned_logo_saved",
                    supplier=after_data.get("supplier", "") or before_inv.get("supplier", ""),
                ))
            if (
                res.get("template_action")
                or res.get("counter_reset")
                or res.get("replaced_variants")
                or res.get("unconfirmed_variants")
                or res.get("auto_logo_saved")
            ):
                self._sync_import_view_learning()
            return ", ".join(parts)
        except Exception as exc:
            log.debug("learn from edited invoice: %s", exc)
            return ""

    def _on_delete_key(self) -> None:
        """Delete-tangenten: ta bort markerad faktura eller radgrupp.

        Fokusskydd: står fokus i ett textfält (sökfält, dialogfält)
        ska Delete radera text som vanligt — aldrig en faktura.
        """
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return
        if fw is not None and hasattr(fw, "lineEdit"):
            try:
                if fw.lineEdit() is not None:
                    return  # redigerbar combobox — textläge
            except Exception:
                pass
        # Fallback-typnamn (träffar även subklasser som en enkel
        # isinstance på basklasserna ibland missar hos Qt-binärer)
        cls = type(fw).__name__ if fw is not None else ""
        if cls in (
            "QLineEdit", "QTextEdit", "QPlainTextEdit", "QComboBox",
            "QSpinBox", "QDoubleSpinBox", "QDateEdit", "QDateTimeEdit",
        ):
            return
        # Om någon dialog (t.ex. ur ett parallellt flöde) äger fokus
        # ska Delete aldrig nå fram till fakturalistan bakom.
        if fw is not None:
            try:
                if fw.window() is not self.window():
                    return
            except Exception:
                pass
        self._delete_invoice()

    def _delete_invoice(self) -> None:
        """Tar bort markerade rader efter tydlig, avböjningssäker fråga."""
        ids = self._selected_ids()
        if not ids:
            return
        by_id = {str(row.get("id", "")): row for row in self._all_data}
        rows = [by_id[rid] for rid in ids if rid in by_id]
        if not rows:
            return

        if len(rows) == 1:
            number = str(rows[0].get("invoice_number", "") or "—")
            title = tr("invoices.delete")
            body = tr("invoices.delete_confirm_single", nr=number)
        else:
            total = sum(_to_float(row.get("total_amount")) for row in rows)
            title = tr("invoices.delete_selected_title", n=len(rows))
            body = tr(
                "invoices.delete_confirm_multiple",
                n=len(rows), amount=fmt_amount(total),
            )
        reply = QMessageBox.question(
            self, title, body,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        removed: list[str] = []
        failed: list[str] = []
        for row in rows:
            rid = str(row.get("id", "") or "")
            try:
                self._app.delete_invoice(rid)
                removed.append(rid)
            except Exception as exc:
                log.error("delete_invoice %s: %s", rid, exc)
                failed.append(str(row.get("invoice_number", rid) or rid))
        self._marked_export_ids.difference_update(removed)
        self._do_refresh()
        if failed:
            QMessageBox.warning(
                self,
                tr("invoices.delete_partial_title"),
                tr(
                    "invoices.delete_partial_body",
                    removed=len(removed), failed=", ".join(failed),
                ),
            )
        elif len(rows) == 1:
            self._status(
                tr("invoices.deleted_one", nr=(
                    rows[0].get("invoice_number", "") or ""
                ))
            )
        else:
            self._status(tr("invoices.deleted_many", n=len(removed)))

    def _delete_all_invoices(self) -> None:
        """Rensa ALLA aktiva fakturor ur registret (knappen).

        Riktig borttagning via delete_invoice för varje post —
        INGEN markeras betald/exporterad och INGENTING flyttas
        till Historik/betalda-filerna. Originalfilerna på disk
        rörs aldrig. Historik (redan betalda) rörs inte heller.
        """
        rows = [r for r in self._all_data if r.get("id")]
        if not rows:
            return
        total = sum(_to_float(r.get("total_amount")) for r in rows)
        reply = QMessageBox.question(
            self,
            tr("invoices.delete_all_title"),
            tr(
                "invoices.delete_all_body",
                n=len(rows),
                amount=fmt_amount(total),
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = 0
        failed = 0
        for r in rows:
            try:
                if self._app.delete_invoice(r["id"]):
                    removed += 1
                else:
                    failed += 1
            except Exception as exc:
                log.warning("delete_all %s: %s", r.get("id"), exc)
                failed += 1
        self._marked_export_ids.clear()
        self._do_refresh()
        msg = tr("invoices.deleted_all_status_long", n=removed)
        if failed:
            msg += tr("invoices.deleted_failed_suffix", n=failed)
        self._status(msg)

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
            str(data.get("invoice_number", "")) + tr("common.copy_suffix")
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
                self._status(f"✅  {tr('invoices.duplicated_status')}")
            except Exception as exc:
                QMessageBox.critical(self, tr("common.error"), str(exc))

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
        dlg.setSizeGripEnabled(True)
        if callable(fit_dialog_to_screen):
            fit_dialog_to_screen(
                dlg, 580, 520, minimum_width=400, minimum_height=340,
            )
        else:
            dlg.setMinimumWidth(420)
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

        combine_plan = plan_credit_settlement(rows)
        if combine_plan["has_partial_credit"] and combine_plan["total_invoices"] > 0:
            lbl_rem = QLabel(
                tr(
                    "credit.export_remaining_line",
                    remaining=fmt_amount(combine_plan["remaining_credits"]),
                )
            )
            lbl_rem.setWordWrap(True)
            lbl_rem.setStyleSheet("color:#58a6ff;font-weight:700;")
            lay.addWidget(lbl_rem)

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
        if summary["n_credits"] > 0:
            btn_link = QPushButton(tr("credit.link_from_combine"))

            def _open_link() -> None:
                dlg.accept()
                self._show_link_credit_dialog(preselected_rows=rows)

            btn_link.clicked.connect(_open_link)
            row_btns.addWidget(btn_link)
        row_btns.addWidget(btn_export)
        row_btns.addStretch(1)
        row_btns.addWidget(btn_close)
        lay.addLayout(row_btns)
        dlg.exec()

    def _show_link_credit_dialog(
        self, _checked: bool = False, preselected_rows: list[dict] | None = None
    ) -> None:
        """Kopplar vald kreditfaktura till obetalda fakturor och behåller
        kvarvarande kreditbelopp på krediten till nästa koppling."""
        from PySide6.QtWidgets import QCheckBox, QScrollArea, QWidget as _QW

        if preselected_rows is not None:
            selected = list(preselected_rows)
        else:
            seen_ids: set[str] = set()
            selected = []
            for item in self._selected_invoices() + self._get_selected_exportable():
                iid = str(item.get("id", "") or "")
                if iid and iid in seen_ids:
                    continue
                if iid:
                    seen_ids.add(iid)
                selected.append(item)
        sel_credits = [
            r for r in selected
            if _to_float(r.get("total_amount")) < 0
            and str(r.get("status", "")) not in NON_UNPAID_STATUSES
        ]
        all_credits = [
            r for r in self._all_data
            if _to_float(r.get("total_amount")) < 0
            and str(r.get("status", "")) not in NON_UNPAID_STATUSES
        ]
        credits = sel_credits or all_credits
        if not credits:
            QMessageBox.information(
                self, tr("credit.link_title"), tr("credit.link_need_credit")
            )
            return

        # Om ingen specifik kredit valdes och flera finns, låt första valda
        # (eller samma leverantör som markerade fakturor) starta ikryssad,
        # men användaren kan ha valt fler i förhand.
        if not sel_credits and len(all_credits) > 1:
            credits = [all_credits[0]]

        unpaid_invoices = [
            r for r in self._all_data
            if _to_float(r.get("total_amount")) > 0
            and str(r.get("status", "")) not in NON_UNPAID_STATUSES
        ]
        if not unpaid_invoices:
            QMessageBox.information(
                self, tr("credit.link_title"), tr("credit.no_unpaid_invoices")
            )
            return

        credit_suppliers = {
            str(c.get("supplier", "") or "").strip().lower() for c in credits
        }
        unpaid_invoices.sort(
            key=lambda r: (
                str(r.get("supplier", "") or "").strip().lower() not in credit_suppliers,
                str(r.get("due_date", "") or "9999-99-99"),
                str(r.get("invoice_number", "") or ""),
            )
        )
        pre_pos_ids = {
            str(r.get("id", "")) for r in selected
            if _to_float(r.get("total_amount")) > 0 and r.get("id")
        }

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("credit.link_title"))
        dlg.setSizeGripEnabled(True)
        if callable(fit_dialog_to_screen):
            fit_dialog_to_screen(
                dlg, 660, 500, minimum_width=400, minimum_height=340,
            )
        else:
            dlg.setMinimumWidth(420)
            dlg.setMinimumHeight(340)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)

        cred_lines = [
            f"{c.get('supplier', '')} · {c.get('invoice_number', '')} · "
            f"{fmt_amount(_to_float(c.get('total_amount')))}"
            for c in credits
        ]
        lbl_cred = QLabel("  |  ".join(cred_lines))
        lbl_cred.setWordWrap(True)
        lbl_cred.setFont(make_font(12, bold=True))
        lbl_cred.setStyleSheet("color:#64b5f6;")
        lay.addWidget(lbl_cred)

        lay.addWidget(QLabel(tr("credit.pick_invoices_label")))

        scroll = QScrollArea(dlg)
        scroll.setWidgetResizable(True)
        holder = _QW(scroll)
        holder_lay = QVBoxLayout(holder)
        holder_lay.setContentsMargins(6, 6, 6, 6)
        holder_lay.setSpacing(4)
        checks: list[tuple[QCheckBox, dict]] = []
        for inv in unpaid_invoices:
            inv_id = str(inv.get("id", "") or "")
            due = str(inv.get("due_date", "") or "—")
            cb = QCheckBox(
                f"{due}   {inv.get('supplier', '')} · "
                f"{inv.get('invoice_number', '')} · "
                f"{fmt_amount(_to_float(inv.get('total_amount')))}"
            )
            cb.setChecked(inv_id in pre_pos_ids)
            checks.append((cb, inv))
            holder_lay.addWidget(cb)
        holder_lay.addStretch(1)
        scroll.setWidget(holder)
        lay.addWidget(scroll, stretch=1)

        lbl_summary = QLabel()
        lbl_summary.setWordWrap(True)
        lbl_summary.setFont(make_font(11, bold=True))
        lay.addWidget(lbl_summary)

        def _picked_invoices() -> list[dict]:
            return [inv for cb, inv in checks if cb.isChecked()]

        def _refresh_summary() -> None:
            picked = _picked_invoices()
            plan = plan_credit_settlement(credits + picked)
            lbl_summary.setText(
                tr(
                    "credit.link_summary",
                    credits=fmt_amount(plan["total_credits_original"]),
                    n=len(picked),
                    invoices=fmt_amount(plan["total_invoices"]),
                    used=fmt_amount(plan["used_credits"]),
                    remaining=fmt_amount(plan["remaining_credits"]),
                    net=fmt_amount(plan["net_to_pay"]),
                )
            )

        for cb, _inv in checks:
            cb.toggled.connect(_refresh_summary)
        _refresh_summary()

        row_btns = QHBoxLayout()
        btn_apply_paid = QPushButton(tr("credit.link_apply_paid"))
        btn_apply_export = QPushButton(tr("credit.link_apply_export"))
        btn_apply_export.setProperty("accent", True)
        btn_close = QPushButton(tr("combine.close"))
        btn_close.clicked.connect(dlg.reject)

        def _apply_paid_only() -> None:
            picked = _picked_invoices()
            if not picked:
                QMessageBox.information(
                    dlg, tr("credit.link_title"), tr("credit.need_one_invoice")
                )
                return
            combined = credits + picked
            plan = plan_credit_settlement(combined)
            self._record_undo([
                str(r.get("id", "")) for r in combined if r.get("id")
            ])
            settled = self._safe_mark_paid(plan["fully_settled_ids"])
            apply_credit_carryovers(self._app, plan["carryovers"])
            dlg.accept()
            self._do_refresh()
            self._status(
                tr(
                    "credit.settled_status",
                    n=settled,
                    remaining=fmt_amount(plan["remaining_credits"]),
                )
            )

        def _apply_and_export() -> None:
            picked = _picked_invoices()
            if not picked:
                QMessageBox.information(
                    dlg, tr("credit.link_title"), tr("credit.need_one_invoice")
                )
                return
            combined = credits + picked
            earliest = combine_invoices(combined)["earliest_due"]
            dlg.accept()
            self._export_invoices(
                combined,
                confirm_title=tr("credit.link_title"),
                default_payment_date=earliest,
                confirm=False,
            )

        btn_apply_paid.clicked.connect(_apply_paid_only)
        btn_apply_export.clicked.connect(_apply_and_export)
        row_btns.addWidget(btn_apply_paid)
        row_btns.addWidget(btn_apply_export)
        row_btns.addStretch(1)
        row_btns.addWidget(btn_close)
        lay.addLayout(row_btns)
        dlg.exec()

    def _mark_selected_paid(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        selected = self._selected_invoices()
        plan = plan_credit_settlement(selected)
        if plan["has_partial_credit"] and plan["total_invoices"] > 0.004:
            reply = QMessageBox.question(
                self,
                tr("invoices.mark_paid_title"),
                tr(
                    "credit.mark_paid_partial_confirm",
                    n=len(plan["settled_invoice_ids"]),
                    invoices=fmt_amount(plan["total_invoices"]),
                    credits=fmt_amount(plan["total_credits_original"]),
                    remaining=fmt_amount(plan["remaining_credits"]),
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._record_undo(ids)
            count = self._safe_mark_paid(plan["fully_settled_ids"])
            apply_credit_carryovers(self._app, plan["carryovers"])
            self._do_refresh()
            self._status(
                tr(
                    "credit.settled_status",
                    n=count,
                    remaining=fmt_amount(plan["remaining_credits"]),
                )
            )
            return

        reply = QMessageBox.question(
            self,
            tr("invoices.mark_paid_title"),
            tr("invoices.mark_paid_confirm_simple", n=len(ids)),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._record_undo(ids)
        count = self._safe_mark_paid(ids)
        self._do_refresh()
        self._status(tr("invoices.mark_paid_done_simple", n=count))

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

        # Sedan kryssas träffarna in i exportvalet (förslag 2);
        # radmarkeringen nedan bara visar vilka det rör sig om.
        self._marked_export_ids |= ids
        self._apply_table_selection()

        selection = self._table.selectionModel()
        table_model = self._table.model()
        flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        selection.clearSelection()
        for row in range(table_model.rowCount()):
            index = table_model.index(row, 0)
            if str(index.data(Qt.ItemDataRole.UserRole) or "") in ids:
                selection.select(index, flags)

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

    def _pages_for(self, inv: dict) -> int:
        """Sidantal för fakturans original (cachad per filversion)."""
        path = str(inv.get("attachment", "") or "")
        if not path:
            return 0
        try:
            st = Path(path).stat()
            cache_key = (path, st.st_mtime_ns, st.st_size)
        except OSError:
            return 0
        cached = self._page_count_cache.get(cache_key)
        if cached is None:
            cached = attachment_page_count(path)
            self._page_count_cache[cache_key] = cached
        return cached

    def _open_original_invoice(self) -> None:
        """Öppnar markerad fakturas original via högerklicksmenyn.

        Samma attachment-sökväg som exporten bifogar och Skriv ut
        använder. Saknas filen sägs det i statusraden — appen
        gissar aldrig fram en annan fil.
        """
        inv = self._selected_invoice()
        if not inv:
            return
        path = str(inv.get("attachment", "") or "")
        nr = str(inv.get("invoice_number", "") or "")
        if not path or not Path(path).exists():
            self._status(tr("invoices.open_missing", nr=nr))
            return
        open_file(path)
        self._status(
            tr("invoices.opened", file=Path(path).name)
        )
        log.info("INVOICE_OPEN: öppnade original %s", path)

    def _print_invoice(self) -> None:
        """Skriver ut markerad fakturas original (alla sidor).

        Originalets sökväg ligger i fakturans attachment-fält
        (samma fil som exporten bifogar) och skrivs ut orörd
        via systemets skrivardialog — samma utskriftsväg som
        Import-granskningens Skriv ut. Saknas originalet sägs
        det i statusraden i stället för att något gissas fram.
        """
        inv = self._selected_invoice()
        if not inv:
            return
        path = str(inv.get("attachment", "") or "")
        nr = str(inv.get("invoice_number", "") or "")
        name = Path(path).name if path else nr
        if not path or not Path(path).exists():
            self._status(tr("invoices.print_missing", nr=nr))
            return
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter

            try:
                from ui.scan_import_view import print_invoice_document
            except ImportError:
                from scan_import_view import (  # type: ignore[no-redef]
                    print_invoice_document,
                )
        except Exception as exc:
            self._status(tr("scan.print_failed", error=str(exc)))
            return
        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            dlg = QPrintDialog(printer, self)
            if not dlg.exec():
                return
            n = print_invoice_document(path, printer)
            if n:
                self._status(tr("scan.printed", file=name, n=n))
                log.info(
                    "INVOICE_PRINT: %s utskriven (%d sida/sidor)",
                    name, n,
                )
            else:
                self._status(
                    tr(
                        "scan.print_failed",
                        error=tr("scan.print_no_pages"),
                    )
                )
        except Exception as exc:
            log.warning("print invoice: %s", exc)
            self._status(tr("scan.print_failed", error=str(exc)))

    def _scan_data_dir(self) -> Path:
        """Datakatalogen där tolkningsmallarna och inlärnings-
        minnet bor (samma som Import-fliken använder)."""
        raw = ""
        try:
            raw = str(self._app.settings.get("db_path", "data"))
        except Exception:
            raw = str(self._app.get_setting("db_path", "data"))
        data_dir = Path(raw or "data")
        if not data_dir.is_absolute():
            data_dir = (
                Path(__file__).resolve().parent.parent / data_dir
            )
        return data_dir

    def _load_scan_templates(self, si: Any) -> dict:
        """Användarens inlärda mallar (samma fil som Import-fliken
        använder) — så omskanningen tolkar med dagens mallar."""
        try:
            return si.load_templates(
                self._scan_data_dir() / "invoice_templates.json"
            )
        except Exception as exc:
            log.debug("rescan templates: %s", exc)
            return {}

    def _rescan_invoice(self) -> None:
        """Skannar om markerad fakturas original med dagens
        tolkning och erbjuder att rätta fakturan.

        Originalet tolkas på nytt (mallar + säkerhetsregler
        precis som vid inläsning). Avviker nytolkningen från
        det registrerade visas gammalt → nytt per fält och
        fakturan uppdateras först när användaren bekräftar;
        stämmer allt — eller tolkningen är osäker — ändras
        ingenting."""
        inv = self._selected_invoice()
        if not inv:
            return
        path = str(inv.get("attachment", "") or "")
        nr = str(inv.get("invoice_number", "") or "")
        if not path or not Path(path).exists():
            self._status(tr("invoices.rescan_no_original", nr=nr))
            return
        try:
            try:
                from ui.scan_import_view import _scan_module
            except ImportError:
                from scan_import_view import _scan_module  # type: ignore[no-redef]
            si = _scan_module()
            text, _method = si.extract_text(Path(path))
            try:
                suppliers = list(self._app.get_suppliers() or [])
            except Exception:
                suppliers = []
            load_ml = getattr(si, "load_match_learning", None)
            learning = (
                load_ml(self._scan_data_dir() / "match_memory.json")
                if callable(load_ml) else None
            )
            parse_kwargs: dict[str, Any] = {
                "templates": self._load_scan_templates(si),
            }
            if learning is not None:
                try:
                    sig = inspect.signature(si.parse_invoice_file)
                    if "match_learning" in sig.parameters or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    ):
                        parse_kwargs["match_learning"] = learning
                except (TypeError, ValueError):
                    parse_kwargs["match_learning"] = learning
            parsed = si.parse_invoice_file(
                path, text or "", suppliers, **parse_kwargs
            )
        except Exception as exc:
            log.warning("rescan invoice %s: %s", nr, exc)
            self._status(tr("invoices.rescan_failed", nr=nr))
            return
        if not parsed.get("template") or parsed.get("missing"):
            missing = ", ".join(parsed.get("missing") or []) or "—"
            log.info(
                "SCAN_RESCAN: faktura %s kunde inte tolkas säkert "
                "(mall=%s, saknar=%s) — inget ändrat",
                nr, parsed.get("template") or "—", missing,
            )
            self._status(
                tr("invoices.rescan_uncertain", nr=nr, missing=missing)
            )
            return
        try:
            from ui.watch_folders import invoice_control_changes
        except ImportError:
            from watch_folders import invoice_control_changes  # type: ignore[no-redef]
        changes = invoice_control_changes(inv, parsed)
        if not changes:
            log.info(
                "SCAN_RESCAN: faktura %s stämmer med originalet "
                "— inget ändrat", nr,
            )
            self._status(tr("invoices.rescan_unchanged", nr=nr))
            return
        new_nr = changes.get("invoice_number", (None, None))[1]
        if new_nr:
            others = [
                r for r in self._all_data
                if r.get("id") != inv.get("id")
                and str(r.get("supplier", "")).strip().lower()
                == str(inv.get("supplier", "")).strip().lower()
                and str(r.get("invoice_number", "")).strip().lower()
                == str(new_nr).strip().lower()
            ]
            if others:
                self._status(
                    tr("invoices.rescan_number_taken", nr=nr, new=new_nr)
                )
                return
        labels = {
            "invoice_number": tr("invoices.rescan_field_number"),
            "date": tr("invoices.rescan_field_date"),
            "due_date": tr("invoices.rescan_field_due"),
            "total_amount": tr("invoices.rescan_field_total"),
        }

        def _fmt(field: str, value: Any) -> str:
            if field == "total_amount":
                try:
                    return fmt_amount(float(value))
                except (TypeError, ValueError):
                    return str(value)
            return str(value or "—")

        lines = "\n".join(
            f"• {labels.get(field, field)}: "
            f"{_fmt(field, old)} → {_fmt(field, new)}"
            for field, (old, new) in changes.items()
        )
        reply = QMessageBox.question(
            self,
            tr("invoices.rescan_title"),
            tr("invoices.rescan_confirm", nr=nr, lines=lines),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._status(tr("invoices.rescan_cancelled", nr=nr))
            return
        updates = {field: new for field, (_old, new) in changes.items()}
        try:
            self._app.update_invoice(inv["id"], updates)
        except Exception as exc:
            log.warning("rescan update %s: %s", nr, exc)
            self._status(tr("invoices.rescan_failed", nr=nr))
            return
        log.info(
            "SCAN_RESCAN: faktura %s uppdaterad efter omskanning "
            "av %s: %s",
            nr, Path(path).name,
            ", ".join(
                f"{f}: {o} → {n}" for f, (o, n) in changes.items()
            ),
        )
        self._do_refresh()
        self._status(tr("invoices.rescan_updated", nr=nr), timeout=8000)

    def _manual_template_match(self) -> None:
        """Högerklick: matcha fakturan mot en mall användaren väljer.

        "Skanna om faktura" väljer tolkningen själv — här väljer
        ANVÄNDAREN vilken leverantör/mall som gäller (för fakturor
        den automatiska matchningen missade). Originalet läses om
        med den valda mallen, ändringarna visas gammalt → nytt för
        kontroll, beloppet kan rättas i dialogen, och inget sparas
        förrän användaren bekräftar. Matchningen lär appen på
        samma sätt som Import-matchningarna (inlärningsminne +
        verifierad mall), så nästa faktura från leverantören
        matchas bättre.
        """
        inv = self._selected_invoice()
        if not inv:
            return
        path = str(inv.get("attachment", "") or "")
        nr = str(inv.get("invoice_number", "") or "")
        if not path or not Path(path).exists():
            self._status(tr("invoices.rescan_no_original", nr=nr))
            return
        try:
            try:
                from ui.scan_import_view import _scan_module
            except ImportError:
                from scan_import_view import _scan_module  # type: ignore[no-redef]
            si = _scan_module()
            text, _method = si.extract_text(Path(path))
        except Exception as exc:
            log.warning("manual match %s: %s", nr, exc)
            self._status(tr("invoices.rescan_failed", nr=nr))
            return
        if not text or not text.strip():
            self._status(tr("invoices.manual_match_no_text", nr=nr))
            return
        try:
            suppliers = list(self._app.get_suppliers() or [])
        except Exception:
            suppliers = []
        templates = self._load_scan_templates(si)
        try:
            template_learning = si.load_match_learning(
                self._scan_data_dir() / "match_memory.json"
            )
        except Exception:
            template_learning = {}
        try:
            pages = si.page_image_count(Path(path))
        except Exception:
            pages = 0

        options: list[str] = []
        seen_opts: set[str] = set()

        def _add(name: Any) -> None:
            name = str(name or "").strip()
            if name and name.lower() not in seen_opts:
                seen_opts.add(name.lower())
                options.append(name)

        for s in suppliers:
            _add(s.get("name", "") if isinstance(s, dict) else "")
        for name in templates.keys():
            _add(str(name))
        for fmt in getattr(si, "BUILTIN_FORMATS", []) or []:
            _add(str(fmt.get("name", "") or ""))
        if not options:
            QMessageBox.information(
                self, tr("invoices.manual_match_title"),
                tr("invoices.manual_match_no_options"),
            )
            return

        _nm = getattr(si, "_names_match", None)

        def _names_match(a: str, b: str) -> bool:
            if callable(_nm):
                try:
                    return bool(_nm(a, b))
                except Exception:
                    pass
            return str(a).strip().lower() == str(b).strip().lower()

        def _template_for(name: str):
            """Mallen för ett valt namn — egen mall först, annars
            det inbyggda formatets etikettskarta. None = ingen mall."""
            tmpl = si.find_template(templates, name, suppliers)
            if tmpl is not None:
                return tmpl
            for fmt in getattr(si, "BUILTIN_FORMATS", []) or []:
                names = [fmt.get("name", "")] + list(
                    fmt.get("aliases", []) or []
                )
                if any(
                    n and _names_match(name, str(n)) for n in names
                ):
                    return {"fields": dict(fmt.get("fields", {}) or {})}
            return None

        def _read(name: str) -> tuple[Any, dict, list[str]]:
            """Läser om fakturans fält med vald mall; generisk
            läsning fyller fält mallen inte träffar."""
            tmpl = _template_for(name)
            found: dict[str, Any] = {}
            if tmpl:
                try:
                    selector = getattr(si, "select_supplier_template", None)
                    if callable(selector):
                        sel = selector(
                            text, tmpl, path=path or None,
                            match_learning=template_learning,
                            supplier=name,
                        )
                        if not sel.get("ambiguous"):
                            found = dict(sel.get("found") or {})
                    else:
                        found = dict(si.apply_template(text, tmpl) or {})
                except Exception as exc:
                    log.debug("manual match apply: %s", exc)
                    found = {}
                if not found:
                    try:
                        fields = tmpl.get("fields", {}) or {}
                        if any(
                            isinstance(spec, dict) and spec.get("region")
                            for spec in fields.values()
                        ):
                            found.update(
                                si.template_values_from_regions(
                                    tmpl,
                                    si.extract_region_texts(path, tmpl),
                                )
                            )
                    except Exception as exc:
                        log.debug("manual match regions: %s", exc)
            try:
                base = si.parse_invoice_text(
                    text, suppliers, templates={}
                )
            except Exception:
                base = {}
            after: dict[str, Any] = {}
            for field in ("invoice_number", "date", "due_date", "ocr"):
                value = found.get(field)
                if value in (None, ""):
                    value = base.get(field, "")
                after[field] = str(value or "")
            total = found.get("total_amount")
            if total in (None, "", 0, 0.0):
                total = base.get("total_amount", 0)
            try:
                after["total_amount"] = float(total or 0)
            except (TypeError, ValueError):
                after["total_amount"] = 0.0
            return tmpl, after, list(found)

        def _parse_sv_amount(raw: str) -> float:
            """'13 480,00 SEK' → 13480.0 (tål valuta + tusental)."""
            t = re.sub(r"[^0-9,.\-]", "", str(raw or ""))
            if "," in t and "." in t:
                if t.rfind(",") > t.rfind("."):
                    t = t.replace(".", "").replace(",", ".")
                else:
                    t = t.replace(",", "")
            elif "," in t:
                t = t.replace(",", ".")
            try:
                return float(t)
            except ValueError:
                return 0.0

        cur_supplier = str(inv.get("supplier", "") or "")
        try:
            cur_amount = fmt_amount(float(inv.get("total_amount") or 0))
        except (TypeError, ValueError):
            cur_amount = str(inv.get("total_amount", "") or "—")
        field_labels = {
            "invoice_number": tr("invoices.rescan_field_number"),
            "date": tr("invoices.rescan_field_date"),
            "due_date": tr("invoices.rescan_field_due"),
            "total_amount": tr("invoices.rescan_field_total"),
            "ocr": tr("invoices.manual_match_field_ocr"),
        }

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("invoices.manual_match_title"))
        layout = QVBoxLayout(dlg)
        intro = QLabel(tr(
            "invoices.manual_match_intro",
            nr=nr or "—", supplier=cur_supplier or "—",
            amount=cur_amount,
        ))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(QLabel(tr("invoices.manual_match_pick")))
        combo = QComboBox(dlg)
        combo.addItems(options)
        start = next(
            (i for i, n in enumerate(options)
             if _names_match(n, cur_supplier)),
            -1,
        )
        combo.setCurrentIndex(start)
        combo.setPlaceholderText(tr("scan.match_ask_placeholder"))
        layout.addWidget(combo)
        if pages >= 2:
            note = QLabel(tr("scan.match_multipage_note", n=pages))
            note.setWordWrap(True)
            layout.addWidget(note)
        tmpl_lbl = QLabel(dlg)
        layout.addWidget(tmpl_lbl)
        preview = QLabel(dlg)
        preview.setWordWrap(True)
        layout.addWidget(preview)
        layout.addWidget(QLabel(tr("scan.match_amount_label")))
        amount_edit = QLineEdit(dlg)
        layout.addWidget(amount_edit)
        buttons = QHBoxLayout()
        btn_cancel = QPushButton(tr("common.cancel"))
        btn_cancel.clicked.connect(dlg.reject)
        btn_save = QPushButton(tr("invoices.manual_match_save"))
        btn_save.setDefault(True)
        buttons.addStretch()
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_save)
        layout.addLayout(buttons)

        state: dict[str, Any] = {
            "after": {}, "template": None, "template_fields": [],
        }

        def _refresh_preview() -> None:
            name = combo.currentText().strip()
            if combo.currentIndex() < 0 or not name:
                tmpl_lbl.setText("")
                preview.setText("")
                amount_edit.setText("")
                state["after"] = {}
                state["template"] = None
                state["template_fields"] = []
                return
            tmpl, after, template_fields = _read(name)
            state["after"] = after
            state["template"] = tmpl
            state["template_fields"] = template_fields
            template_label = (
                tr("invoices.manual_match_template_used", template=name)
                if tmpl else tr("invoices.manual_match_template_none")
            )
            if tmpl:
                template_entry = si.template_confirmation_entry(
                    template_learning, name, tmpl
                )
                try:
                    template_count = int(
                        template_entry.get("confirmed", 0) or 0
                    )
                except (TypeError, ValueError):
                    template_count = 0
                if template_count:
                    template_label += " · " + tr(
                        "scan.template_confirmation_count",
                        n=template_count,
                    )
                else:
                    template_label += tr(
                        "invoices.manual_match_template_unconfirmed"
                    )
            tmpl_lbl.setText(template_label)
            lines = []
            for field in (
                "invoice_number", "date", "due_date", "ocr",
                "total_amount",
            ):
                if field == "total_amount":
                    old_s = cur_amount
                    new_s = (
                        fmt_amount(after["total_amount"])
                        if after.get("total_amount") else "—"
                    )
                else:
                    old_s = str(inv.get(field, "") or "—")
                    new_s = str(after.get(field) or "—")
                mark = (
                    "  " + tr("invoices.manual_match_changes")
                    if new_s != old_s else ""
                )
                lines.append(
                    f"{field_labels[field]}: {old_s} → {new_s}{mark}"
                )
            preview.setText("\n".join(lines))
            amount_edit.setText(
                fmt_amount(after["total_amount"])
                if after.get("total_amount") else ""
            )

        def _accept() -> None:
            if combo.currentIndex() >= 0:
                dlg.accept()

        btn_save.clicked.connect(_accept)
        combo.currentIndexChanged.connect(
            lambda _i: _refresh_preview()
        )
        _refresh_preview()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = combo.currentText().strip()
        if not chosen:
            return
        after = dict(state.get("after") or {})
        resolved = next(
            (
                str(s.get("name", "")).strip()
                for s in suppliers
                if isinstance(s, dict)
                and str(s.get("name", "")).strip()
                and _names_match(str(s.get("name", "")), chosen)
            ),
            chosen,
        )
        new_nr = str(after.get("invoice_number", "") or "").strip()
        if new_nr and new_nr.lower() != nr.lower():
            others = [
                r for r in self._all_data
                if r.get("id") != inv.get("id")
                and str(r.get("supplier", "")).strip().lower()
                == resolved.strip().lower()
                and str(r.get("invoice_number", "")).strip().lower()
                == new_nr.lower()
            ]
            if others:
                self._status(tr(
                    "invoices.rescan_number_taken", nr=nr, new=new_nr
                ))
                return
        updates: dict[str, Any] = {}
        if resolved and not _names_match(resolved, cur_supplier):
            updates["supplier"] = resolved
        for field in ("invoice_number", "date", "due_date", "ocr"):
            new = str(after.get(field, "") or "").strip()
            if new and new != str(inv.get(field, "") or "").strip():
                updates[field] = new
        edited_total = _parse_sv_amount(amount_edit.text())
        final_total = edited_total
        if edited_total > 0:
            try:
                old_total = float(inv.get("total_amount") or 0)
            except (TypeError, ValueError):
                old_total = 0.0
            if abs(edited_total - old_total) > 0.005:
                updates["total_amount"] = edited_total
        elif after.get("total_amount"):
            final_total = float(after["total_amount"])
        final_nr = str(updates.get("invoice_number") or new_nr or nr)
        if updates:
            try:
                self._app.update_invoice(inv["id"], updates)
            except Exception as exc:
                log.warning("manual match update %s: %s", nr, exc)
                self._status(tr("invoices.rescan_failed", nr=nr))
                return
            self._do_refresh()
        confirmed_values = dict(after or {})
        confirmed_values["invoice_number"] = final_nr
        confirmed_values["total_amount"] = final_total
        learned = self._learn_manual_match(
            si, resolved, text, final_nr, final_total, pages, path,
            template=state.get("template"),
            template_fields=state.get("template_fields", []),
            template_name=combo.currentText().strip(),
            confirmed_values=confirmed_values,
        )
        log.info(
            "SCAN_MATCH: faktura %s matchad manuellt mot %s "
            "(ändringar: %s)",
            nr, resolved,
            ", ".join(updates) or "inga",
        )
        msg = (
            tr("invoices.manual_match_updated", nr=nr or final_nr,
               supplier=resolved)
            if updates else
            tr("invoices.manual_match_unchanged", nr=nr or final_nr,
               supplier=resolved)
        )
        if learned:
            msg += "  ·  " + learned
            self._sync_import_view_learning()
        self._status(msg, timeout=8000)

    def _learn_manual_match(
        self, si: Any, supplier: str, text: str,
        invoice_number: str, total: float, pages: int,
        path: str = "", template: dict | None = None,
        template_fields: list[str] | None = None,
        template_name: str = "",
        confirmed_values: dict | None = None,
    ) -> str:
        """Inlärning ur en manuell matchning i Fakturor-fliken —
        samma regler som i Import: bekräftelsen räknas i
        inlärningsminnet, och saknar leverantören både egen mall
        och inbyggt format härleds en VERIFIERAD mall ur de
        bekräftade värdena och sparas bland mallarna.
        Returnerar en statusnotis (eller "")."""
        try:
            data_dir = self._scan_data_dir()
            learning_path = data_dir / "match_memory.json"
            learning = si.load_match_learning(learning_path)
            templates = self._load_scan_templates(si)
            try:
                suppliers = list(self._app.get_suppliers() or [])
            except Exception:
                suppliers = []
            template_name = str(template_name or supplier).strip()
            confirmed = dict(confirmed_values or {})
            confirmed["invoice_number"] = str(invoice_number or "")
            confirmed["total_amount"] = total
            matched_template = (
                template if isinstance(template, dict)
                else si.find_template(templates, template_name, suppliers)
            )
            existing_template = (
                matched_template
                or si.find_template(templates, supplier, suppliers)
            )
            notes: list[str] = []
            matched_variant: dict | None = None
            if existing_template and text:
                sel = si.select_supplier_template(
                    text, existing_template, path=path or None,
                    match_learning=learning, supplier=supplier,
                )
                if not sel.get("ambiguous") and isinstance(
                    sel.get("variant"), dict
                ):
                    f = sel.get("found") or {}
                    nr_ok = (
                        str(f.get("invoice_number", "")).strip()
                        == str(invoice_number or "").strip()
                    )
                    try:
                        amt_ok = abs(
                            abs(float(f.get("total_amount") or 0))
                            - abs(float(total or 0))
                        ) <= 0.005
                    except (TypeError, ValueError):
                        amt_ok = False
                    if (nr_ok and amt_ok) or sel.get("claimed"):
                        matched_variant = sel["variant"]
            elif existing_template and si._template_has_core_fields(
                existing_template
            ):
                variants = si.template_variants(existing_template)
                matched_variant = variants[-1] if variants else existing_template

            if (
                matched_variant is None
                and text
                and str(invoice_number or "").strip()
                and abs(float(total or 0)) > 0
                and not si._builtin_format_extracts_confirmed(
                    text, supplier, str(invoice_number or ""), abs(float(total or 0))
                )
            ):
                try:
                    candidate = si.derive_template_from_confirmation(
                        text, invoice_number, total,
                        date=str(confirmed.get("date", "") or "").strip(),
                        due_date=str(confirmed.get("due_date", "") or "").strip(),
                        ocr=str(confirmed.get("ocr", "") or "").strip(),
                    )
                except TypeError:
                    candidate = si.derive_template_from_confirmation(
                        text, invoice_number, total
                    )
                if candidate:
                    replace_primary = bool(
                        existing_template is not None
                        and not si._template_has_core_fields(existing_template)
                    )
                    tkey, _saved, _added = si.store_supplier_template(
                        templates, supplier, candidate,
                        max_templates=si.MAX_TEMPLATES_PER_SUPPLIER,
                        replace_primary=replace_primary,
                    )
                    if si.save_templates(
                        data_dir / "invoice_templates.json", templates
                    ):
                        matched_variant = candidate
                        template_name = tkey or supplier
                        notes.append(tr(
                            "invoices.manual_match_learned",
                            supplier=supplier,
                        ))
            matched_template = matched_variant or existing_template
            found: dict = {}
            if matched_template:
                try:
                    found = si.template_values(
                        path or None, text, matched_template
                    )
                except Exception:
                    found = {}
            if template_fields:
                allowed_fields = {str(field) for field in template_fields}
                found = {
                    field: value for field, value in found.items()
                    if field in allowed_fields
                }
            accepted_fields = si.confirmed_template_fields(
                matched_template, found, confirmed
            ) if matched_template else []
            confirmation_id = si.match_confirmation_id(
                supplier, invoice_number, path=path,
                invoice_date=str(confirmed.get("date", "") or ""),
            )
            entry_before = si.learning_entry(learning, supplier)
            try:
                confirmations_before = int(
                    entry_before.get("confirmed", 0) or 0
                )
            except (TypeError, ValueError):
                confirmations_before = 0
            obs_fn = getattr(si, "observe_confirmed_supplier_logo", None)
            auto_logo_saved = False
            if callable(obs_fn):
                logo_signature, auto_logo_saved = obs_fn(
                    learning, templates, supplier, path,
                    confirmation_id=confirmation_id,
                    suppliers=suppliers,
                )
            else:
                logo_signature = si.confirmed_supplier_logo_signature(
                    path, supplier, templates, suppliers=suppliers
                )
            if auto_logo_saved:
                si.save_templates(
                    data_dir / "invoice_templates.json", templates
                )
                notes.append(tr("scan.learned_logo_saved", supplier=supplier))
            logo_count_before = int(
                (entry_before.get("logos", {}) or {}).get(
                    logo_signature, 0
                ) or 0
            ) if logo_signature else 0
            entry = si.record_match_confirmation(
                learning, supplier,
                multipage=int(pages or 0) >= 2, text=text,
                logo_signature=logo_signature,
                confirmation_id=confirmation_id, source_path=path,
                template_name=template_name,
                template=matched_template,
                template_fields=accepted_fields,
            )
            si.save_match_learning(learning_path, learning)
            confirmed_count = int(entry.get("confirmed", 0) or 0)
            try:
                ll = si._learning_logger() if hasattr(si, "_learning_logger") else None
                if ll is not None:
                    tcount = len(si.template_variants(
                        si.find_template(templates, supplier, suppliers)
                    ))
                    ll.log_manual_match(
                        source="invoices_manual_match",
                        file=Path(path).name if path else "",
                        pages=int(pages or 0),
                        supplier=supplier,
                        after=confirmed,
                        template_saved=bool(matched_variant and any(
                            "manual_match_learned" in str(n) or supplier in str(n)
                            for n in notes
                        )),
                        template_variant=matched_template,
                        template_count=tcount,
                        confirmations_before=confirmations_before,
                        confirmations_after=confirmed_count,
                        multipage_confirmed=int(entry.get("multipage_confirmed", 0) or 0),
                        graduated=(
                            confirmations_before < si.LEARNED_SUPPLIER_CONFIRMATIONS
                            <= confirmed_count
                        ),
                        logo_learned=bool(logo_signature),
                        logo_auto_saved=bool(auto_logo_saved),
                    )
            except Exception:
                pass
            notes.append(tr(
                "scan.learning_count", supplier=supplier,
                n=confirmed_count,
            ))
            if (
                confirmations_before < si.LEARNED_SUPPLIER_CONFIRMATIONS
                <= confirmed_count
            ):
                notes.append(tr(
                    "scan.learned_auto_supplier", supplier=supplier
                ))
            logo_count = int(
                (entry.get("logos", {}) or {}).get(logo_signature, 0) or 0
            ) if logo_signature else 0
            if (
                confirmed_count >= si.LEARNED_SUPPLIER_CONFIRMATIONS
                and logo_count >= si.LEARNED_IDENTIFIER_CONFIRMATIONS
                and not (
                    confirmations_before >= si.LEARNED_SUPPLIER_CONFIRMATIONS
                    and logo_count_before >= si.LEARNED_IDENTIFIER_CONFIRMATIONS
                )
            ):
                notes.append(tr(
                    "scan.learned_auto_logo", supplier=supplier
                ))
            if matched_template:
                template_entry = si.template_confirmation_entry(
                    learning, supplier, matched_template
                )
                try:
                    template_count = int(
                        template_entry.get("confirmed", 0) or 0
                    )
                except (TypeError, ValueError):
                    template_count = 0
                if template_count:
                    notes.append(tr(
                        "scan.template_confirmation_count",
                        n=template_count,
                    ))
            return " ".join(notes)
        except Exception as exc:
            log.warning("learn manual match: %s", exc)
        return ""

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
        """Sparar nuvarande status/betalningsdatum/belopp före en ändring."""
        by_id = {str(r.get("id")): r for r in self._all_data}
        batch: list[dict[str, Any]] = []
        for rid in ids:
            rec = by_id.get(str(rid))
            if rec is not None:
                snap: dict[str, Any] = {
                    "id": str(rid),
                    "status": str(rec.get("status", "")),
                    "payment_date": str(rec.get("payment_date", "") or ""),
                    "total_amount": _to_float(rec.get("total_amount")),
                    "note": str(rec.get("note", "") or ""),
                    "original_credit_amount": rec.get(
                        "original_credit_amount"
                    ),
                }
                batch.append(snap)
        if batch:
            self._undo_stack.append(batch)
            del self._undo_stack[:-20]  # max 20 ångringar bakåt

    def _undo_last_status(self) -> None:
        """Ångrar senaste statusändringen (markera betald / kreditkoppling)."""
        if not self._undo_stack:
            self._status(tr("invoices.undo_empty"))
            return
        batch = self._undo_stack.pop()
        count = 0
        for item in batch:
            if isinstance(item, dict):
                rid = str(item.get("id", "") or "")
                patch: dict[str, Any] = {
                    "status": str(item.get("status", "")),
                    "payment_date": str(item.get("payment_date", "") or ""),
                    "total_amount": item.get("total_amount", 0.0),
                    "note": str(item.get("note", "") or ""),
                }
                if "original_credit_amount" in item:
                    patch["original_credit_amount"] = item.get(
                        "original_credit_amount"
                    )
            else:
                rid, old_status, old_payment_date = item
                patch = {
                    "status": old_status,
                    "payment_date": old_payment_date,
                }
            try:
                self._app.update_invoice(rid, patch)
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

    def _export_selected_pdf(self) -> None:
        """Exporterar BARA de markerade fakturorna till PDF.

        Samma flöde och regler som "Exportera alla": bekräftelse,
        betalningsdatum, max 10 fakturor per fil (-delXavN),
        original som standard, krediter nettas — och efter lyckad
        export markeras posterna Betald i Historik/data/betalda.
        Inget markerat (eller bara betalda markerade) → ingen
        export och inget ändras."""
        self._export_invoices(
            self._get_selected_exportable(),
            confirm_title=tr("invoices.export_selected_title"),
        )

    def _ensure_export_originals(self, rows: list[dict]) -> int:
        """Ser till att ALLA original följer med när "inkludera
        original" är valt (användarkrav, besked 27).

        En sparad bilageväg som inte längre finns (filen årssorterad
        till Arkiv/<år>/, omkopplad disk) söks upp: först under den
        gamla mappen, sedan under övriga raders arkivmappar. Hittas
        filen uppdateras registret (självhelning) och raden, så
        exporten bifogar den. Returnerar antalet återfunna.
        """
        if find_moved_original is None:
            return 0
        rel_ok = 0
        search_roots: list[Path] = []
        for row in rows:
            raw = Path(str(row.get("attachment", "") or "").strip())
            if raw.is_dir():
                search_roots.append(raw)
            elif raw.parent.is_dir():
                search_roots.append(raw.parent)
        seen_roots: set[Path] = set()
        search_roots = [
            r for r in search_roots
            if not (r.resolve() in seen_roots or seen_roots.add(r.resolve()))
        ]
        for row in rows:
            raw = str(row.get("attachment", "") or "").strip()
            if not raw:
                continue
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = Path(".") / candidate
            if candidate.is_file():
                continue
            found = find_moved_original(raw, tuple(search_roots))
            if not found or Path(found) == candidate:
                continue
            rid = str(row.get("id", "") or "")
            relocated = False
            relocate = getattr(self._app, "relocate_invoice_attachment", None)
            if rid and callable(relocate):
                try:
                    relocated = bool(relocate(rid, found))
                except Exception as exc:
                    log.warning(
                        "relocate_invoice_attachment %s: %s", rid, exc
                    )
            row["attachment"] = found
            if relocated:
                rel_ok += 1
            log.info(
                "EXPORT: original återfunnet för %s — %s%s",
                row.get("invoice_number", "") or row.get("file", ""),
                found,
                " (registret uppdaterat)" if relocated else "",
            )
        return rel_ok

    def _export_invoices(
        self,
        exportable: list[dict],
        *,
        confirm_title: str = "",
        default_payment_date: str = "",
        confirm: bool = True,
    ) -> None:
        if not confirm_title:
            confirm_title = tr("invoices.export_all_title")
        if not exportable:
            QMessageBox.information(
                self, tr("common.export"), tr("invoices.export_no_active")
            )
            return

        # ── Beräkna summor (inkl. delavräknade kreditfakturor) ────────
        settlement = plan_credit_settlement(exportable)
        # Användarkrav (besked 27): när "inkludera original" är valt
        # ska ALLA original följa med — leta upp filer som flyttats
        # (årssortering/diskbyte) och självhela registret först.
        if self._include_originals():
            try:
                healed = self._ensure_export_originals(
                    settlement["export_rows"]
                )
                if healed:
                    self._status(tr(
                        "invoices.originals_relocated", n=healed,
                    ))
            except Exception as exc:
                log.warning("ensure_export_originals: %s", exc)
        has_partial_credit = bool(settlement["has_partial_credit"])
        total_invoices = settlement["total_invoices"]
        total_credits = (
            settlement["applied_credits"]
            if settlement["settled_credit_rows"] and total_invoices > 0.004
            else settlement["total_credits_original"]
        )
        att_betala = settlement["net_to_pay"]

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
        remaining_credit_note = (
            f"\n  {tr('credit.export_remaining_line', remaining=fmt_amount(settlement['remaining_credits']))}\n"
            if has_partial_credit and total_invoices > 0.004
            else ""
        )

        # ── Bekräftelsedialog ──────────────────────────────────────────
        reply = (
            QMessageBox.question(
                self,
                confirm_title,
                tr(
                    "invoices.export_confirm_body",
                    n=len(exportable),
                    n_inv=n_inv,
                    inv_sum=fmt_amount(total_invoices),
                    n_cre=n_cre,
                    cred_sum=fmt_amount(total_credits),
                    rule="─" * 38,
                    net=fmt_amount(att_betala),
                    rem=remaining_credit_note,
                    suppliers=", ".join(suppliers),
                ),
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
            exportable=settlement["export_rows"],
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
            self._status(tr("invoices.export_cancelled"))
            return

        log.info(
            "Export: betalningsdatum = %s, %d fakturor, att betala %s",
            payment_date or "ej angivet",
            len(exportable),
            fmt_amount(att_betala),
        )

        # ── Hämta PDF-exportern ────────────────────────────────────────
        exporter = getattr(self._app, "pdf_exporter", None)
        if exporter is None:
            QMessageBox.information(
                self,
                tr("common.export"),
                tr("invoices.export_no_exporter"),
            )
            return

        # ── Exportera i filer om MAX 10 fakturarader ───────────────────
        # Varje faktura är en egen rad i PDF:en; fler än 10 rader
        # delas i flera filer (…-del1avN.pdf, …-del2avN.pdf, …)
        # med originalen fördelade på sina egna fakturor. Samma
        # betalningsdatum gäller alla delfiler i exporten, och
        # historik + arkivering sker per fil. Misslyckas en delfil
        # stannar exporten där — resten förblir oexporterat.
        # Delavräknade kreditfakturor minskar med det avräknade beloppet
        # och behåller sitt kvarvarande saldo som Obetald till nästa gång.

        chunks = (
            chunk_settlement_rows(settlement)
            if settlement["settled_credit_rows"] and total_invoices > 0.004
            else chunk_export_rows(exportable)
        )
        live_credits_by_id = {
            str(r.get("id")): dict(r)
            for r in exportable
            if _to_float(r.get("total_amount")) < 0 and r.get("id")
        }
        made_files: list[str] = []
        total_included_att = 0
        n_missing_att = 0
        archived = 0
        export_pd = payment_date
        failed_note = ""
        aborted = False
        for idx, chunk in enumerate(chunks):
            chunk_suppliers = sorted(
                {
                    str(i.get("supplier", "")).strip()
                    for i in chunk if i.get("supplier")
                }
            )
            target_dir, filename = build_export_path(chunk_suppliers)
            if len(chunks) > 1:
                filename = (
                    f"{Path(filename).stem}"
                    f"-del{idx + 1}av{len(chunks)}.pdf"
                )
            full_path = target_dir / filename
            try:
                result = exporter.export_invoice_list(
                    chunk,
                    filename=str(full_path),
                    title=tr("invoices.export_title"),
                    check_duplicates=False,
                    mark_exported=True,
                    force_export=True,
                    payment_date=payment_date,
                    ask_payment_date=False,   # dialog redan visad ovan
                    include_originals=self._include_originals(),
                    original_first_page_only=(
                        self._original_first_page_only()
                    ),
                )
            except Exception as exc:
                failed_note = str(exc)
                break
            if not result.get("success"):
                if result.get("cancelled"):
                    aborted = True
                else:
                    failed_note = "\n".join(
                        result.get("errors", [tr("invoices.unknown_error")])
                    )
                break

            actual_path = result.get("file_path", str(full_path))
            made_files.append(actual_path)
            export_pd = result.get("payment_date", payment_date)
            total_included_att += int(
                result.get("attachments_included", 0) or 0
            )
            n_missing_att += int(
                result.get("attachments_missing", 0) or 0
            )

            settled_chunk_rows, chunk_carryovers = build_chunk_carryovers(
                chunk, live_credits_by_id
            )

            # Summor för just DENNA fil (historiken är per fil)
            c_inv = 0.0
            c_cred = 0.0
            for i in chunk:
                val = _to_float(i.get("total_amount"))
                if val > 0:
                    c_inv += val
                elif val < 0:
                    c_cred += val
            self._export_history.record_export(
                invoices=chunk,
                file_path=actual_path,
                total_inv=round(c_inv, 2),
                total_cred=round(c_cred, 2),
                att_betala=round(c_inv + c_cred, 2),
                suppliers=chunk_suppliers,
                payment_date=export_pd,   # betalningsdatum sparas
                credit_carryovers=chunk_carryovers,
            )

            # Arkivera bara de poster som slutbetalats; delavräknad
            # kreditfaktura ligger kvar som Obetald med kvarvarande saldo.
            archived += self._archive_exported(settled_chunk_rows, export_pd)
            if chunk_carryovers:
                apply_credit_carryovers(self._app, chunk_carryovers)
                for _co in chunk_carryovers:
                    if _co.get("id"):
                        self._marked_export_ids.discard(str(_co["id"]))

        if not made_files:
            if aborted:
                self._status(tr("invoices.export_cancelled"))
            else:
                QMessageBox.warning(
                    self,
                    tr("invoices.export_failed_title"),
                    failed_note or tr("invoices.unknown_error"),
                )
            return

        self._do_refresh()
        attach_note = ""
        if total_included_att:
            attach_note = tr(
                "invoices.attachments_note",
                n=total_included_att,
            )
        if n_missing_att:
            attach_note += (
                "  " + tr("invoices.attachments_missing", n=n_missing_att)
            )
        files_note = (
            tr("invoices.export_files_note", n=len(made_files))
            if len(made_files) > 1 else ""
        )
        rem_status = (
            f" · {tr('credit.export_remaining_line', remaining=fmt_amount(settlement['remaining_credits']))}"
            if has_partial_credit and total_invoices > 0.004
            else ""
        )
        pay_part = (
            tr("invoices.export_status_paydate", date=export_pd)
            if export_pd else ""
        )
        self._status(
            tr(
                "invoices.export_done_status_long",
                n=archived,
                files_note=files_note,
                net=fmt_amount(att_betala),
                pay_part=pay_part,
                rem_part=rem_status,
                attach_part=attach_note,
            )
        )

        # ── Resultatdialog: Öppna filen / Öppna mappen / Stäng ─────────
        payment_line = (
            tr("invoices.export_payment_line", date=export_pd)
            if export_pd else ""
        )
        missing_line = ""
        if n_missing_att:
            missing_line = (
                "\n\n  "
                + tr("invoices.attachments_missing", n=n_missing_att)
            )
        files_line = (
            tr("invoices.export_file_single", path=made_files[0])
            if len(made_files) == 1
            else tr(
                "invoices.export_files_multi",
                list="\n".join(f"  • {f}" for f in made_files),
            )
        )
        partial_line = (
            tr("invoices.export_partial_abort", reason=failed_note)
            if failed_note else ""
        )
        box = QMessageBox(self)
        box.setWindowTitle(tr("invoices.export_done_title"))
        box.setIcon(
            QMessageBox.Icon.Warning
            if (n_missing_att or partial_line)
            else QMessageBox.Icon.Information
        )
        box.setText(
            tr(
                "invoices.export_done_summary",
                n=archived,
                inv_sum=fmt_amount(total_invoices),
                cred_sum=fmt_amount(total_credits),
                rule="─" * 38,
                net=fmt_amount(att_betala),
                rem=remaining_credit_note,
                pay_line=payment_line,
                files_line=files_line,
                missing_line=missing_line,
                partial_line=partial_line,
            )
        )
        btn_open_file = box.addButton(
            tr("invoices.open_file_btn"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        btn_open_folder = box.addButton(
            tr("invoices.open_folder_btn"),
            QMessageBox.ButtonRole.ActionRole,
        )
        box.addButton(
            tr("invoices.close_btn"), QMessageBox.ButtonRole.RejectRole
        )
        box.exec()

        clicked = box.clickedButton()
        if clicked is btn_open_file:
            open_file(made_files[0])
        elif clicked is btn_open_folder:
            open_folder(Path(made_files[0]).parent)

        # Betalningsdatum nollställs implicit — variabeln payment_date
        # existerar bara i denna funktion. Nästa export frågar igen.
        log.info(
            "Export klar: %d fakturor markerade Betald i %d "
            "fil(er), betalningsdatum '%s' nollställt",
            archived,
            len(made_files),
            export_pd,
        )

    # ══════════════════════════════════════════════════════════════════
    #  EXPORTHISTORIK
    # ══════════════════════════════════════════════════════════════════

    def _show_history(self) -> None:
        """Visar exporthistoriken med återställningsmöjlighet."""
        if self._export_history.count() == 0:
            QMessageBox.information(
                self,
                tr("invoices.history_empty_title"),
                tr("invoices.history_empty_body"),
            )
            return
        dlg = ExportHistoryDialog(
            parent=self,
            history=self._export_history,
            theme=self._current_theme,
        )
        dlg.export_restored.connect(self._on_export_restored)
        dlg.credit_carryovers_restored.connect(
            self._on_credit_carryovers_restored
        )
        dlg.exec()

    def _on_export_restored(self, invoice_ids: list[str]) -> None:
        """
        Återställer arkiverade fakturor till Obetald.

        Anropas via ExportHistoryDialog.export_restored-signalen.
        """
        engine = getattr(self._app, "invoices", None)
        if engine is not None and hasattr(engine, "mark_status"):
            try:
                engine.mark_status(list(invoice_ids), "Obetald")
            except Exception:
                pass
        else:
            for iid in invoice_ids:
                try:
                    self._app.update_invoice(iid, {"status": "Obetald"})
                except Exception:
                    pass
        self._do_refresh()
        self._status(
            f"✅  {tr('invoices.export_restored_status', n=len(invoice_ids))}"
        )

    def _on_credit_carryovers_restored(self, carryovers: list[dict]) -> None:
        """Återställer delavräknat kreditbelopp när en export ångras."""
        if not carryovers:
            return
        from ui.invoices_helpers import _merge_credit_note

        engine = getattr(self._app, "invoices", None)
        by_id = {str(r.get("id", "")): r for r in self._all_data}
        for co in carryovers:
            cid = str(co.get("id", "") or "")
            used = abs(float(co.get("used_amount", 0.0) or 0.0))
            if not cid or used <= 0.004:
                continue
            if engine is not None and hasattr(engine, "restore_from_archive"):
                try:
                    if hasattr(engine, "_archive") and engine._archive.get(cid) is not None:
                        engine.restore_from_archive([cid])
                except Exception:
                    pass
            cur = (
                engine.get(cid) if engine is not None and hasattr(engine, "get")
                else by_id.get(cid)
            )
            cur_amt = _to_float(
                (cur or {}).get("total_amount"),
                default=float(co.get("remaining_amount", 0.0) or 0.0),
            )
            restored_amt = round(cur_amt - used, 2)
            orig = round(
                _to_float(
                    (cur or {}).get("original_credit_amount")
                    or co.get("original_credit_amount")
                    or restored_amt
                ),
                2,
            )
            patch: dict[str, Any] = {
                "status": "Obetald",
                "payment_date": "",
                "total_amount": restored_amt,
                "invoice_type": "Kreditfaktura",
            }
            if abs(restored_amt - orig) <= 0.004:
                patch["note"] = str(co.get("before_note", "") or "")
                patch["original_credit_amount"] = None
            else:
                cum_used = round(max(0.0, abs(orig) - abs(restored_amt)), 2)
                rem_note = tr(
                    "credit.remaining_note",
                    remaining=fmt_amount(restored_amt),
                    original=fmt_amount(orig),
                    used=fmt_amount(cum_used),
                )
                patch["note"] = _merge_credit_note(
                    str((cur or {}).get("note", "") or ""), rem_note
                )
                patch["original_credit_amount"] = orig
            try:
                self._app.update_invoice(cid, patch)
            except Exception as exc:
                log.warning("_on_credit_carryovers_restored %s: %s", cid, exc)
        self._do_refresh()

    # ══════════════════════════════════════════════════════════════════
    #  HÖGERKLICK-MENY
    # ══════════════════════════════════════════════════════════════════

    def _context_menu(self, pos) -> None:
        """
        Högerklick i tabellen.

        Markerar raden under muspekaren om den inte redan ingår i
        markeringen (befintlig multi-markering bevaras).
        """
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        rid = str(index.data(Qt.ItemDataRole.UserRole) or "")
        if not rid:
            return
        if rid not in self._selected_ids():
            self._table.selectRow(index.row())

        menu = QMenu(self)
        menu.addAction(tr("invoices.edit"), self._edit_invoice)
        menu.addAction(tr("invoices.duplicate"), self._duplicate_invoice)
        menu.addAction(
            tr("invoices.copy_payinfo"), self._copy_payment_info
        )
        menu.addAction(tr("invoices.ctx_print"), self._print_invoice)
        menu.addAction(
            tr("invoices.ctx_open_original"), self._open_original_invoice
        )
        menu.addAction(tr("invoices.ctx_rescan"), self._rescan_invoice)
        menu.addAction(
            tr("invoices.ctx_manual_match"),
            self._manual_template_match,
        )
        menu.addSeparator()

        status_menu = menu.addMenu(tr("invoices.ctx_status"))
        for s in INVOICE_STATUSES:
            act = status_menu.addAction(tr_status(s))
            act.triggered.connect(
                lambda checked=False, st=s: self._set_status_selected(st)
            )
        menu.addSeparator()

        menu.addAction(
            tr("invoices.mark_paid"), self._mark_selected_paid
        )
        if any(
            _to_float(r.get("total_amount")) < 0
            and str(r.get("status", "")) not in NON_UNPAID_STATUSES
            for r in self._all_data
        ) or any(
            _to_float(r.get("total_amount")) < 0
            for r in self._selected_invoices()
        ):
            menu.addAction(
                tr("credit.link_action"), self._show_link_credit_dialog
            )
        menu.addAction(
            tr("invoices.export_selected"),
            lambda checked=False, r=rid: self._export_with_row(r),
        )
        menu.addAction(
            tr("invoices.ctx_undo_status"), self._undo_last_status
        )
        menu.addSeparator()
        selected_count = len(self._selected_ids())
        delete_label = (
            tr("invoices.delete_selected_n", n=selected_count)
            if selected_count > 1 else tr("invoices.delete")
        )
        menu.addAction(delete_label, self._delete_invoice)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _export_with_row(self, rid: str) -> None:
        """Högerklicksexport: kryssa i raden under musen, lägg
        sedan allt ikryssat i exporten (som knappen)."""
        rid = str(rid or "")
        if rid:
            self._marked_export_ids.add(rid)
            self._apply_table_selection()
        self._export_selected_pdf()

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
        self._invoice_model.set_dark(dark)

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
                f"border-radius:{PANEL_RADIUS_PX}px;"
                f"border:1.5px solid {accent};}}"
            )
        strip = self.findChild(QFrame, "SummaryStrip")
        if strip:
            strip.setStyleSheet(
                "QFrame#SummaryStrip{background:transparent;border:none;}"
            )
        # Grupperingspanelerna (filter / åtgärder / export / snabbfilter) —
        # exportpanelen får guldkant så den aldrig missas.
        for _name in ("FilterBar", "ActionsBar", "ExportBar",
                      "ExportStickyBar", "QuickFilterBar"):
            _frame = self.findChild(QFrame, _name)
            if _frame:
                _edge = gold if _name in (
                    "ExportBar", "ExportStickyBar"
                ) else border_c
                _frame.setStyleSheet(
                    f"QFrame#{_name}{{background-color:{card};"
                    f"border-radius:{PANEL_RADIUS_PX}px;"
                    f"border:1.5px solid {_edge};}}"
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
        qss_urls = qss_indicator_urls(text_color)
        down_path = qss_urls.get("chevron_down", "")
        down_css = f"image: url({down_path});" if down_path else ""
        combo_arrow_qss = (
            f"QComboBox::drop-down{{border:none;width:24px;background:transparent;}}"
            f"QComboBox::down-arrow{{{down_css}width:12px;height:12px;}}"
        )
        input_style = (
            f"background-color:{input_bg};"
            f"color:{text_color};"
            f"border:1.5px solid {input_border};"
            f"border-radius:{CONTROL_RADIUS_PX}px;padding:4px 8px;"
            f"font-size:12px;font-weight:700;"
        )
        focus_border = f"border:{FOCUS_RING_PX}px solid {accent};"

        self._sup_selector.setStyleSheet(
            f"QComboBox{{{input_style}min-height:24px;font-size:13px;padding:5px 28px 5px 10px;}}"
            f"QComboBox:focus{{{focus_border}}}"
            f"{combo_arrow_qss}"
        )
        self._search.setStyleSheet(
            f"QLineEdit{{{input_style}min-height:20px;}}"
            f"QLineEdit:focus{{{focus_border}}}"
        )
        self._density_label.setStyleSheet(
            f"color:{muted_color};background:transparent;font-weight:700;"
        )
        self._lbl_original_export.setStyleSheet(
            f"color:{muted_color};background:transparent;font-weight:700;font-size:11px;"
        )
        self._density_selector.setStyleSheet(
            f"QComboBox{{{input_style}min-height:22px;padding-right:28px;}}"
            f"QComboBox:focus{{{focus_border}}}"
            f"{combo_arrow_qss}"
        )
        self._combo_original_export.setStyleSheet(
            f"QComboBox{{{input_style}min-height:19px;padding:3px 26px 3px 8px;}}"
            f"QComboBox:focus{{{focus_border}}}"
            f"{combo_arrow_qss}"
        )
        for combo in (
            self._filter_type,
            self._filter_status,
            self._filter_supplier,
        ):
            combo.setStyleSheet(
                f"QComboBox{{{input_style}min-height:19px;padding:3px 26px 3px 8px;}}"
                f"QComboBox:focus{{{focus_border}}}"
                f"{combo_arrow_qss}"
            )

        # ── Tabell ─────────────────────────────────────────────────────
        header_bg = t.get("header_bg", "#1f6feb" if dark else "#0969da")
        row_normal = t.get("row_normal", bg_color)
        row_alt = t.get("row_alt", "#161b22" if dark else "#f6f8fa")
        grid_c = t.get("table_grid", "#1f2e40" if dark else "#e5dfd5")
        scroll_bg = t.get(
            "scrollbar_bg", "#161b22" if dark else "#f6f8fa"
        )
        scroll_h = t.get(
            "scrollbar_handle", "#30363d" if dark else "#d0d7de"
        )

        row_padding = (
            TABLE_CELL_PADDING_COMPACT_PX
            if self._row_density == "compact"
            else TABLE_CELL_PADDING_COMFORTABLE_PX
        )
        self._table.setStyleSheet(f"""
            QTableView {{
                background-color           : {row_normal};
                color                      : {text_color};
                font-weight                : 600;
                font-size                  : 13px;
                gridline-color             : {grid_c};
                alternate-background-color : {row_alt};
                selection-background-color : {accent};
                selection-color            : #ffffff;
                border                     : 1px solid {border_c};
                border-radius              : {CONTROL_RADIUS_PX}px;
            }}
            QTableView:focus {{
                border : {FOCUS_RING_PX}px solid {accent};
            }}
            QTableView::item:focus {{
                border : 1px solid {accent};
            }}
            QHeaderView::section {{
                background-color : {header_bg};
                color            : #ffffff;
                font-weight      : 700;
                font-size        : 12px;
                padding          : 8px 10px;
                border           : none;
                border-right     : 1px solid rgba(255, 255, 255, 0.18);
                border-bottom    : 1px solid {border_c};
            }}
            QTableView::item {{
                padding : {row_padding}px 8px;
            }}
            QTableView::item:selected {{
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
            disabled_bg = t.get("bg_tertiary", "#1e2a38")
            disabled_text = t.get("text_disabled", "#9aa4b2")
        else:
            btn_bg = t.get("button_bg", "#f4f1ea")
            btn_hover = t.get("button_hover", "#eae5dc")
            btn_text = t.get("button_text", "#0d1218")
            disabled_bg = t.get("bg_tertiary", "#f0ebe2")
            disabled_text = t.get("text_disabled", "#57606a")

        btn_configs = [
            (self._btn_add,                    accent,    accent_hover, "#ffffff", 20),
            (self._btn_edit,                   btn_bg,    btn_hover,    btn_text,  20),
            (self._btn_delete,                 error_c,   "#c92a2a",    "#ffffff", 20),
            (self._btn_more_actions,           btn_bg,    btn_hover,    btn_text,  20),
            (self._btn_mark_paid,              success_c, "#1e874b",    "#ffffff", 20),
            (self._btn_pay_today,              success_c, "#1e874b",    "#ffffff", 20),
            (self._btn_export_selected,        success_c, "#1e874b",    "#ffffff", 20),
            (self._btn_export_all,             info_c,    accent_hover, "#ffffff", 20),
            (self._btn_export_menu,            btn_bg,    btn_hover,    btn_text,  18),
            (self._btn_mark_shown,             btn_bg,    btn_hover,    btn_text,  19),
            (self._btn_clear_marked,           btn_bg,    btn_hover,    btn_text,  19),
            (self._btn_columns,                btn_bg,    btn_hover,    btn_text,  22),
            (self._btn_export_selected_sticky, success_c, "#1e874b",    "#ffffff", 22),
        ]
        for btn, bg, hover, fg, min_h in btn_configs:
            has_menu = btn in (self._btn_more_actions, self._btn_export_menu)
            pad_right = "20px" if has_menu else "7px"
            menu_ind = (
                "QPushButton::menu-indicator {"
                "subcontrol-origin: padding;"
                "subcontrol-position: right center;"
                "right: 6px;"
                "width: 9px;"
                "}"
                if has_menu
                else ""
            )
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color : {bg};
                    color            : {fg};
                    font-weight      : 700;
                    font-size        : 11px;
                    border-radius    : {CONTROL_RADIUS_PX}px;
                    border           : 1px solid {border_c};
                    padding          : 4px {pad_right} 4px 7px;
                    min-height       : {min_h}px;
                }}
                QPushButton:hover {{
                    background-color : {hover};
                    border-color     : {accent};
                }}
                QPushButton:focus {{
                    border : {FOCUS_RING_PX}px solid {accent};
                }}
                QPushButton:pressed {{
                    background-color : {accent};
                    color            : #ffffff;
                }}
                QPushButton:disabled {{
                    background-color : {disabled_bg};
                    color            : {disabled_text};
                    border-color     : {border_c};
                }}
                {menu_ind}
            """)

        menu_style = f"""
            QMenu {{
                background-color : {card};
                color            : {text_color};
                border           : 1px solid {border_c};
                border-radius    : {CONTROL_RADIUS_PX}px;
                padding          : 4px;
            }}
            QMenu::item {{
                padding          : 6px 14px;
                border-radius    : 4px;
                font-weight      : 600;
            }}
            QMenu::item:selected {{
                background-color : {accent};
                color            : #ffffff;
            }}
            QMenu::item:disabled {{
                color            : {disabled_text};
            }}
            QMenu::separator {{
                height           : 1px;
                background       : {border_c};
                margin           : 4px 6px;
            }}
        """
        for _menu_attr in ("_more_actions_menu", "_export_tools_menu"):
            _menu = getattr(self, _menu_attr, None)
            if _menu is not None:
                _menu.setStyleSheet(menu_style)

        for chip in getattr(self, "_chip_btns", {}).values():
            chip.setStyleSheet(f"""
                QPushButton {{
                    background-color : {btn_bg};
                    color            : {btn_text};
                    font-weight      : 700;
                    font-size        : 11px;
                    border-radius    : 13px;
                    border           : 1px solid {border_c};
                    padding          : 3px 10px;
                    min-height       : 20px;
                    text-align       : center;
                }}
                QPushButton:hover {{
                    background-color : {btn_hover};
                    border-color     : {accent};
                }}
                QPushButton:checked {{
                    background-color : {accent};
                    color            : #ffffff;
                    border-color     : {accent};
                }}
            """)

        # ── Summary-labels ─────────────────────────────────────────────
        label_style = (
            f"color:{text_color};font-weight:700;background:transparent;"
        )
        for lbl in (
            self._lbl_count,
            self._lbl_unpaid,
            self._lbl_overdue,
        ):
            lbl.setStyleSheet(label_style)

        muted_style = f"color:{muted_color};background:transparent;"
        self._lbl_supplier_info.setStyleSheet(muted_style)
        self._footer.setStyleSheet(muted_style)
        self._lbl_history_count.setStyleSheet(muted_style)
        if hasattr(self, "_lbl_quick_filter"):
            self._lbl_quick_filter.setStyleSheet(
                f"color:{muted_color};font-weight:700;background:transparent;"
            )
        if hasattr(self, "_lbl_export_heading"):
            self._lbl_export_heading.setStyleSheet(
                f"color:{text_color};font-weight:700;background:transparent;"
            )
        if hasattr(self, "_lbl_export_selection"):
            self._lbl_export_selection.setStyleSheet(
                f"color:{text_color};font-weight:700;background:transparent;"
            )
        if hasattr(self, "_lbl_marked_cap"):
            self._lbl_marked_cap.setStyleSheet(
                f"color:{muted_color};font-weight:700;background:transparent;"
            )
        for _mlbl_attr in (
            "_lbl_marked_inv",
            "_lbl_marked_cred",
            "_lbl_marked_net",
        ):
            _mlbl = getattr(self, _mlbl_attr, None)
            if _mlbl is not None:
                _mlbl.setStyleSheet(label_style)
        self._sync_chip_styles()
        refresh_bound_icons(t)

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
