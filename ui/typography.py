# -*- coding: utf-8 -*-
"""Gemensam typografi, textskalning och tabellsiffror för InvoiceBundle."""
from __future__ import annotations

import re
from typing import Any

FONT_SIZE_CHOICES: tuple[int, ...] = (11, 13, 15, 17)
DEFAULT_FONT_SIZE: int = 13
_MIN_FONT_SIZE: int = FONT_SIZE_CHOICES[0]
_MAX_FONT_SIZE: int = FONT_SIZE_CHOICES[-1]
_current_font_size: int = DEFAULT_FONT_SIZE
_font_scale_filters: dict[int, Any] = {}

# En egen item-data-roll. Post-ID lagras i UserRole; hjälparnas radroller
# ligger på +11…+14.
_ITEM_BASE_FONT_ROLE = 0x0100 + 15  # Qt.UserRole + 15
_FONT_BASE_PROPERTY = "_invoicebundle_base_font"
_FONT_APPLIED_PROPERTY = "_invoicebundle_applied_font"
_STYLE_BASE_PROPERTY = "_invoicebundle_base_stylesheet"
_STYLE_APPLIED_PROPERTY = "_invoicebundle_applied_stylesheet"
_GEOMETRY_BASE_PROPERTY = "_invoicebundle_base_height_limits"
_GEOMETRY_APPLIED_PROPERTY = "_invoicebundle_applied_height_limits"
_TABLE_SCALE_PROPERTY = "_invoicebundle_applied_table_scale"
_TABLE_BASE_ROW_HEIGHT_PROPERTY = "_invoicebundle_base_row_height"
_APP_BASE_FONT_PROPERTY = "_invoicebundle_base_application_font"

_FONT_SIZE_RE = re.compile(
    r"(?P<prefix>\b(?:font-size|min-height|max-height)\s*:\s*)"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>px|pt)\b",
    re.IGNORECASE,
)


def normalize_font_size(value: Any) -> int:
    """Väljer närmaste stödda storlek och håller värdet inom säkra gränser."""
    try:
        size = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        size = DEFAULT_FONT_SIZE
    size = min(_MAX_FONT_SIZE, max(_MIN_FONT_SIZE, size))
    return min(FONT_SIZE_CHOICES, key=lambda candidate: abs(candidate - size))


def current_font_size() -> int:
    return _current_font_size


def font_scale(size: Any = None) -> float:
    normalized = normalize_font_size(
        _current_font_size if size is None else size
    )
    return normalized / float(DEFAULT_FONT_SIZE)


def set_current_font_size(size: Any) -> int:
    """Sätter storleken som framtida celler och dialoger ska använda."""
    global _current_font_size
    _current_font_size = normalize_font_size(size)
    return _current_font_size


def scaled_point_size(size: int | float, preference: Any = None) -> int:
    """Skalar en grundstorlek till heltals-punktstorlek för Qt."""
    try:
        base = float(size)
    except (TypeError, ValueError):
        base = 12.0
    return max(6, int(round(base * font_scale(preference))))


def scale_stylesheet(stylesheet: str, preference: Any = None) -> str:
    """Skalar QSS-font- och höjdstorlekar utan att påverka färger/kanter."""
    source = str(stylesheet or "")
    scale = font_scale(preference)
    if scale == 1.0 or not source:
        return source

    def _replace(match: re.Match) -> str:
        value = float(match.group("value"))
        scaled = max(6, int(round(value * scale)))
        return (
            f"{match.group('prefix')}{scaled}"
            f"{match.group('unit')}"
        )

    return _FONT_SIZE_RE.sub(_replace, source)


def _scaled_qfont(font: Any, preference: Any = None) -> Any:
    from PySide6.QtGui import QFont

    result = QFont(font)
    scale = font_scale(preference)
    point_size = result.pointSizeF()
    if point_size > 0:
        result.setPointSizeF(max(6.0, point_size * scale))
    else:
        pixel_size = result.pixelSize()
        if pixel_size > 0:
            result.setPixelSize(max(6, int(round(pixel_size * scale))))
    return result


def make_tabular_font(size: int = 12, bold: bool = False) -> Any:
    """Monospace-siffror för belopp, fakturanummer och betalnings-ID:n."""
    from PySide6.QtGui import QFont

    font = QFont("monospace", max(6, int(size)))
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setBold(bool(bold))
    return font


def set_item_font(item: Any, base_font: Any) -> None:
    """Sätter en QTableWidgetItem-font och sparar oskalad grundfont."""
    from PySide6.QtGui import QFont

    base = QFont(base_font)
    item.setData(_ITEM_BASE_FONT_ROLE, base)
    item.setFont(_scaled_qfont(base))


def _font_signature(font: Any) -> str:
    try:
        return str(font.toString())
    except Exception:
        return repr(font)


def _set_scaled_font(obj: Any, preference: int, *, force: bool = False) -> None:
    from PySide6.QtGui import QFont

    try:
        current = obj.font()
        base = obj.property(_FONT_BASE_PROPERTY)
        applied = obj.property(_FONT_APPLIED_PROPERTY)
        if not isinstance(base, QFont) or (
            applied is not None
            and _font_signature(current) != _font_signature(applied)
        ):
            base = QFont(current)
        scaled = _scaled_qfont(base, preference)
        if force or _font_signature(current) != _font_signature(scaled):
            obj.setFont(scaled)
        obj.setProperty(_FONT_BASE_PROPERTY, QFont(base))
        obj.setProperty(_FONT_APPLIED_PROPERTY, QFont(scaled))
    except Exception:
        return


def _set_scaled_stylesheet(obj: Any, preference: int) -> None:
    try:
        current = str(obj.styleSheet() or "")
        base = obj.property(_STYLE_BASE_PROPERTY)
        applied = obj.property(_STYLE_APPLIED_PROPERTY)
        if not isinstance(base, str) or current != applied:
            # A theme/view just supplied a fresh, unscaled stylesheet.
            base = current
        scaled = scale_stylesheet(base, preference)
        if current != scaled:
            obj.setStyleSheet(scaled)
        obj.setProperty(_STYLE_BASE_PROPERTY, base)
        obj.setProperty(_STYLE_APPLIED_PROPERTY, scaled)
    except Exception:
        return


def _scale_widget_height_limits(widget: Any, preference: int) -> None:
    """Skalar kontrollernas min-/maxhöjd med typsnittet."""
    try:
        current = (int(widget.minimumHeight()), int(widget.maximumHeight()))
        current_key = f"{current[0]},{current[1]}"
        base_raw = widget.property(_GEOMETRY_BASE_PROPERTY)
        applied = widget.property(_GEOMETRY_APPLIED_PROPERTY)
        if not isinstance(base_raw, str) or current_key != applied:
            base = current
        else:
            base = tuple(int(part) for part in base_raw.split(",", 1))
        scale = font_scale(preference)
        base_min, base_max = int(base[0]), int(base[1])
        min_h = max(0, int(round(base_min * scale))) if base_min else 0
        # Qt's large sentinel means "unlimited"; leave it untouched.
        if base_max >= 16_000_000:
            max_h = base_max
        else:
            max_h = max(min_h, int(round(base_max * scale)))
        if widget.isWindow():
            # Keep saved window/dialog geometry independent of text scale;
            # child controls and layouts still grow to fit the larger text.
            min_h, max_h = base_min, base_max
        try:
            widget.setMaximumHeight(max_h)
            widget.setMinimumHeight(min_h)
        except Exception:
            pass
        widget.setProperty(
            _GEOMETRY_BASE_PROPERTY, f"{int(base[0])},{int(base[1])}"
        )
        widget.setProperty(
            _GEOMETRY_APPLIED_PROPERTY, f"{min_h},{max_h}"
        )
    except Exception:
        return


def _scale_table(table: Any, preference: int) -> None:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QTableView, QTableWidget

    try:
        if isinstance(table, QTableWidget):
            count = int(table.rowCount())
            for row in range(count):
                for col in range(int(table.columnCount())):
                    item = table.item(row, col)
                    if item is None:
                        continue
                    base = item.data(_ITEM_BASE_FONT_ROLE)
                    if isinstance(base, QFont):
                        item.setFont(_scaled_qfont(base, preference))
        elif isinstance(table, QTableView):
            model = table.model()
            count = int(model.rowCount()) if model is not None else 0
        else:
            count = int(table.rowCount())

        new_scale = font_scale(preference)
        base_height = table.property(_TABLE_BASE_ROW_HEIGHT_PROPERTY)
        if isinstance(table, QTableView) and base_height is not None:
            height = max(16, int(round(float(base_height) * new_scale)))
            table.verticalHeader().setDefaultSectionSize(height)
            for row in range(count):
                table.setRowHeight(row, height)
            table.setProperty(_TABLE_SCALE_PROPERTY, new_scale)
            return

        old_scale = table.property(_TABLE_SCALE_PROPERTY)
        old_scale = float(old_scale) if old_scale else 1.0
        ratio = new_scale / old_scale if old_scale else 1.0
        if abs(ratio - 1.0) > 0.001:
            header = table.verticalHeader()
            default_height = int(header.defaultSectionSize())
            if default_height > 0:
                header.setDefaultSectionSize(
                    max(16, int(round(default_height * ratio)))
                )
            for row in range(count):
                height = int(table.rowHeight(row))
                if height > 0:
                    table.setRowHeight(
                        row, max(16, int(round(height * ratio)))
                    )
        table.setProperty(_TABLE_SCALE_PROPERTY, new_scale)
    except Exception:
        return


def set_table_default_row_height(table: Any, height: int) -> None:
    """Sets a density baseline that continues to follow the text-size choice."""
    try:
        base_height = max(16, int(height))
        scale = font_scale()
        scaled_height = max(16, int(round(base_height * scale)))
        table.setProperty(_TABLE_BASE_ROW_HEIGHT_PROPERTY, base_height)
        table.verticalHeader().setDefaultSectionSize(scaled_height)
        model = table.model()
        count = int(model.rowCount()) if model is not None else 0
        for row in range(count):
            table.setRowHeight(row, scaled_height)
        table.setProperty(_TABLE_SCALE_PROPERTY, scale)
    except Exception:
        return


def _scale_widget_tree(root: Any, preference: int) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableView, QWidget

    if not isinstance(root, QWidget):
        return
    try:
        widgets = [root, *root.findChildren(QWidget)]
    except Exception:
        return
    for widget in widgets:
        try:
            if widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
                _set_scaled_font(widget, preference)
            _set_scaled_stylesheet(widget, preference)
            _scale_widget_height_limits(widget, preference)
            if isinstance(widget, QTableView):
                _scale_table(widget, preference)
        except Exception:
            continue


class _FontScaleEventFilter:
    """Lazily installs a QObject event filter without import-time Qt use."""

    def __new__(cls, app: Any) -> Any:
        from PySide6.QtCore import QObject, QEvent, QTimer
        from PySide6.QtWidgets import QWidget

        class _Filter(QObject):
            def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802
                try:
                    if (
                        event.type() == QEvent.Type.Show
                        and isinstance(watched, QWidget)
                    ):
                        target = watched
                        preference = current_font_size()
                        QTimer.singleShot(
                            0,
                            lambda w=target, s=preference:
                                _scale_widget_tree(w, s),
                        )
                except Exception:
                    pass
                return False

        return _Filter(app)


def apply_font_size(app: Any, size: Any) -> int:
    """Applicerar textstorlek omedelbart på appen, befintliga vyer och tabeller."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QTableView, QWidget

    old_size = _current_font_size
    preference = set_current_font_size(size)

    # Qt:s standardfont täcker kontroller som inte har en egen font.
    try:
        base = app.property(_APP_BASE_FONT_PROPERTY)
        applied = app.property(_FONT_APPLIED_PROPERTY)
        current = app.font()
        if not isinstance(base, QFont) or (
            applied is not None
            and _font_signature(current) != _font_signature(applied)
        ):
            base = QFont(current)
        scaled = _scaled_qfont(base, preference)
        app.setFont(scaled)
        app.setProperty(_APP_BASE_FONT_PROPERTY, QFont(base))
        app.setProperty(_FONT_APPLIED_PROPERTY, QFont(scaled))
    except Exception:
        pass

    # Skala programmets globala QSS samt lokala stilark i alla öppna fönster.
    _set_scaled_stylesheet(app, preference)
    try:
        for widget in list(app.allWidgets()):
            if not isinstance(widget, QWidget):
                continue
            if widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
                _set_scaled_font(widget, preference)
            _set_scaled_stylesheet(widget, preference)
            _scale_widget_height_limits(widget, preference)
            if isinstance(widget, QTableView):
                _scale_table(widget, preference)
    except Exception:
        pass

    # Eventfiltern håller framtida dialoger och dynamiskt skapade kontroller
    # i samma skala. En Python-referens behålls så wrappern inte samlas in.
    try:
        key = id(app)
        event_filter = _font_scale_filters.get(key)
        if event_filter is None:
            event_filter = _FontScaleEventFilter(app)
            app.installEventFilter(event_filter)
            _font_scale_filters[key] = event_filter
    except Exception:
        pass
    return preference
