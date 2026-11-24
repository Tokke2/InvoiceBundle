# -*- coding: utf-8 -*-
"""Gemensam typografi, textskalning och tabellsiffror för InvoiceBundle."""
from __future__ import annotations

import re
import weakref
from typing import Any

try:
    import shiboken6 as _shiboken6
except Exception:  # pragma: no cover
    _shiboken6 = None  # type: ignore[assignment]


def _qt_valid(obj: Any) -> bool:
    if obj is None:
        return False
    if _shiboken6 is not None:
        try:
            return bool(_shiboken6.isValid(obj))
        except Exception:
            return False
    return True

FONT_SIZE_CHOICES: tuple[int, ...] = (11, 13, 15, 17)
DEFAULT_FONT_SIZE: int = 13
_MIN_FONT_SIZE: int = FONT_SIZE_CHOICES[0]
_MAX_FONT_SIZE: int = FONT_SIZE_CHOICES[-1]
_current_font_size: int = DEFAULT_FONT_SIZE
_font_scale_filters: dict[int, Any] = {}

# Metadata sparas i rena Python-strukturer (aldrig via QTableWidgetItem.data
# med oanvänd roll eller QObject.setProperty(..., QFont), vilket kan orsaka
# refcount-krascher i Shiboken/PySide6 6.12).
_WIDGET_META: weakref.WeakKeyDictionary[Any, dict[str, Any]] = (
    weakref.WeakKeyDictionary()
)
_ITEM_BASE_ATTR = "_invoicebundle_base_font"
_ITEM_BASE_FONT_ROLE = 0x0100 + 15  # behållen konstant för ev. referenser

_FONT_SIZE_RE = re.compile(
    r"(?P<prefix>\b(?:font-size|min-height|max-height)\s*:\s*)"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>px|pt)\b",
    re.IGNORECASE,
)


def _meta(obj: Any) -> dict[str, Any]:
    bucket = _WIDGET_META.get(obj)
    if bucket is None:
        bucket = {}
        _WIDGET_META[obj] = bucket
    return bucket


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
    if abs(scale - 1.0) < 0.001:
        return result
    point_size = result.pointSizeF()
    if point_size > 0:
        result.setPointSizeF(max(6.0, point_size * scale))
    else:
        pixel_size = result.pixelSize()
        if pixel_size > 0:
            result.setPixelSize(max(6, int(round(pixel_size * scale))))
    return result


def make_tabular_font(size: int = 12, bold: bool = False) -> Any:
    """UI-typsnitt med raka tabellsiffror för belopp, datum och fakturanummer."""
    from PySide6.QtGui import QFont

    try:
        from ui.design import crisp_hinting_preference, ui_font_family
    except ImportError:
        try:
            from design import (  # type: ignore[no-redef]
                crisp_hinting_preference,
                ui_font_family,
            )
        except ImportError:
            def ui_font_family() -> str:  # type: ignore[no-redef]
                return "Segoe UI"

            def crisp_hinting_preference():  # type: ignore[no-redef]
                return QFont.HintingPreference.PreferDefaultHinting

    font = QFont(ui_font_family(), max(6, int(size)))
    font.setWeight(
        QFont.Weight.Bold if bold else QFont.Weight.Medium
    )
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(crisp_hinting_preference())
    tag_cls = getattr(QFont, "Tag", None)
    if tag_cls is not None and hasattr(font, "setFeature"):
        try:
            tag = tag_cls.fromString("tnum")
            if isinstance(tag, tuple):
                tag = tag[0]
            if tag is not None:
                font.setFeature(tag, 1)
        except Exception:
            pass
    return font


def make_mono_font(size: int = 10, bold: bool = False) -> Any:
    """Monospaced typsnitt för loggdetaljer och felsökningskod."""
    from PySide6.QtGui import QFont

    try:
        from ui.design import mono_font_family
        family = mono_font_family()
    except ImportError:
        try:
            from design import mono_font_family  # type: ignore[no-redef]
            family = mono_font_family()
        except ImportError:
            family = "Consolas"
    font = QFont(family, max(6, int(size)))
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    try:
        from ui.design import crisp_hinting_preference
        font.setHintingPreference(crisp_hinting_preference())
    except Exception:
        pass
    font.setBold(bool(bold))
    return font


def set_item_font(item: Any, base_font: Any) -> None:
    """Sätter en QTableWidgetItem-font och sparar oskalad grundfont."""
    from PySide6.QtGui import QFont

    base = QFont(base_font)
    try:
        setattr(item, _ITEM_BASE_ATTR, base)
    except Exception:
        pass
    item.setFont(_scaled_qfont(base))


def _font_signature(font: Any) -> str:
    try:
        return str(font.toString())
    except Exception:
        return repr(font)


def _set_scaled_font(obj: Any, preference: int, *, force: bool = False) -> None:
    from PySide6.QtGui import QFont

    try:
        meta = _meta(obj)
        current = obj.font()
        base = meta.get("base_font")
        applied = meta.get("applied_font")
        if not isinstance(base, QFont) or (
            applied is not None
            and _font_signature(current) != _font_signature(applied)
        ):
            base = QFont(current)
        scaled = _scaled_qfont(base, preference)
        if force or _font_signature(current) != _font_signature(scaled):
            obj.setFont(scaled)
        meta["base_font"] = QFont(base)
        meta["applied_font"] = QFont(scaled)
    except Exception:
        return


def _set_scaled_stylesheet(obj: Any, preference: int) -> None:
    try:
        meta = _meta(obj)
        current = str(obj.styleSheet() or "")
        base = meta.get("base_stylesheet")
        applied = meta.get("applied_stylesheet")
        if not isinstance(base, str) or current != applied:
            base = current
        scaled = scale_stylesheet(base, preference)
        if current != scaled:
            obj.setStyleSheet(scaled)
        meta["base_stylesheet"] = base
        meta["applied_stylesheet"] = scaled
    except Exception:
        return


def _scale_widget_height_limits(widget: Any, preference: int) -> None:
    """Skalar kontrollernas min-/maxhöjd med typsnittet."""
    try:
        meta = _meta(widget)
        current = (int(widget.minimumHeight()), int(widget.maximumHeight()))
        base = meta.get("base_height_limits")
        applied = meta.get("applied_height_limits")
        if not isinstance(base, tuple) or current != applied:
            base = current
        scale = font_scale(preference)
        base_min, base_max = int(base[0]), int(base[1])
        min_h = max(0, int(round(base_min * scale))) if base_min else 0
        if base_max >= 16_000_000:
            max_h = base_max
        else:
            max_h = max(min_h, int(round(base_max * scale)))
        if widget.isWindow():
            min_h, max_h = base_min, base_max
        if (min_h, max_h) != current:
            try:
                widget.setMaximumHeight(max_h)
                widget.setMinimumHeight(min_h)
            except Exception:
                pass
        meta["base_height_limits"] = base
        meta["applied_height_limits"] = (min_h, max_h)
    except Exception:
        return


def _scale_table(table: Any, preference: int) -> None:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QTableView, QTableWidget

    try:
        meta = _meta(table)
        if isinstance(table, QTableWidget):
            count = int(table.rowCount())
            cols = int(table.columnCount())
            for row in range(count):
                for col in range(cols):
                    item = table.item(row, col)
                    if item is None:
                        continue
                    base = getattr(item, _ITEM_BASE_ATTR, None)
                    if isinstance(base, QFont):
                        item.setFont(_scaled_qfont(base, preference))
        elif isinstance(table, QTableView):
            model = table.model()
            count = int(model.rowCount()) if model is not None else 0
        else:
            count = int(table.rowCount())

        new_scale = font_scale(preference)
        base_height = meta.get("table_base_row_height")
        if isinstance(table, QTableView) and base_height is not None:
            height = max(16, int(round(float(base_height) * new_scale)))
            table.verticalHeader().setDefaultSectionSize(height)
            for row in range(count):
                table.setRowHeight(row, height)
            meta["table_scale"] = new_scale
            return

        old_scale = float(meta.get("table_scale") or 1.0)
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
        meta["table_scale"] = new_scale
    except Exception:
        return


def set_table_default_row_height(table: Any, height: int) -> None:
    """Sets a density baseline that continues to follow the text-size choice."""
    try:
        meta = _meta(table)
        base_height = max(16, int(height))
        scale = font_scale()
        scaled_height = max(16, int(round(base_height * scale)))
        meta["table_base_row_height"] = base_height
        table.verticalHeader().setDefaultSectionSize(scaled_height)
        model = table.model()
        count = int(model.rowCount()) if model is not None else 0
        for row in range(count):
            table.setRowHeight(row, scaled_height)
        meta["table_scale"] = scale
    except Exception:
        return


def _scale_widget_tree(root: Any, preference: int) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableView, QWidget

    if not _qt_valid(root) or not isinstance(root, QWidget):
        return
    try:
        widgets = [root, *root.findChildren(QWidget)]
    except Exception:
        return
    for widget in widgets:
        if not _qt_valid(widget):
            continue
        try:
            _meta(widget)["scaled_pref"] = preference
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
                        _qt_valid(watched)
                        and event.type() == QEvent.Type.Show
                        and isinstance(watched, QWidget)
                    ):
                        preference = current_font_size()
                        meta = _meta(watched)
                        if (
                            preference == DEFAULT_FONT_SIZE
                            and meta.get("scaled_pref", DEFAULT_FONT_SIZE)
                            == DEFAULT_FONT_SIZE
                        ):
                            return False
                        meta["scaled_pref"] = preference
                        ref = weakref.ref(watched)
                        QTimer.singleShot(
                            0,
                            lambda r=ref, s=preference: (
                                _scale_widget_tree(r(), s)
                                if _qt_valid(r()) else None
                            ),
                        )
                except Exception:
                    pass
                return False

        return _Filter(app)


def apply_font_size(app: Any, size: Any) -> int:
    """Applicerar textstorlek omedelbart på appen, befintliga vyer och tabeller."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QWidget

    prev_pref = current_font_size()
    preference = set_current_font_size(size)
    if not _qt_valid(app):
        return preference

    try:
        meta = _meta(app)
        base = meta.get("app_base_font")
        applied = meta.get("applied_font")
        current = app.font()
        if not isinstance(base, QFont) or (
            applied is not None
            and _font_signature(current) != _font_signature(applied)
        ):
            base = QFont(current)
        scaled = _scaled_qfont(base, preference)
        if _font_signature(current) != _font_signature(scaled):
            app.setFont(scaled)
        meta["app_base_font"] = QFont(base)
        meta["applied_font"] = QFont(scaled)
        app_scaled_pref = int(meta.get("app_scaled_pref", DEFAULT_FONT_SIZE))
        meta["app_scaled_pref"] = preference
    except Exception:
        app_scaled_pref = prev_pref

    _set_scaled_stylesheet(app, preference)
    needs_tree_walk = (
        preference != DEFAULT_FONT_SIZE
        or prev_pref != preference
        or app_scaled_pref != preference
    )
    if needs_tree_walk:
        try:
            for top in list(app.topLevelWidgets()):
                if _qt_valid(top) and isinstance(top, QWidget):
                    _scale_widget_tree(top, preference)
        except Exception:
            pass

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
