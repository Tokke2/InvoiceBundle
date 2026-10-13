"""
Fakturabunten — bokstavshopp i rullistor och menyer
====================================================
Tryck D så hoppar markeringen till nästa post som börjar på D.
Samma bokstav igen går till nästa. Inom 0,7 s byggs ett prefix
(P sedan I → Pilkington).

Gäller alla QComboBox och öppna QMenu. Skriver inte i textfält.

Copyright © dynamiskt år Rickard Längkvist
"""

from __future__ import annotations

import logging
import time
import unicodedata

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QMenu,
    QTextEdit,
    QPlainTextEdit,
)

log = logging.getLogger("LetterJump")

_GAP = 0.7


def _fold(text: str) -> str:
    """Gemener, utan inledande symboler (★, emoji, mellanslag)."""
    raw = str(text or "").replace("&", "").strip().lower()
    raw = raw.replace("å", "a").replace("ä", "a").replace("ö", "o")
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    i = 0
    while i < len(raw) and not raw[i].isalnum():
        i += 1
    return raw[i:]


class _State:
    def __init__(self) -> None:
        self.buf = ""
        self.when = 0.0
        self.who = 0

    def take(self, who: int, ch: str) -> str:
        now = time.monotonic()
        piece = _fold(ch)
        if not piece:
            return ""
        if who != self.who or now - self.when > _GAP:
            self.buf = ""
        self.who = who
        self.when = now
        self.buf += piece
        return self.buf

    def reset_to(self, who: int, ch: str) -> str:
        self.who = who
        self.when = time.monotonic()
        self.buf = _fold(ch)
        return self.buf


_STATE = _State()


def _matches(labels: list[str], buf: str) -> list[int]:
    return [i for i, label in enumerate(labels) if _fold(label).startswith(buf)]


def _pick(matches: list[int], current: int, cycle: bool) -> int | None:
    if not matches:
        return None
    if cycle:
        later = [i for i in matches if i > current]
        return later[0] if later else matches[0]
    later = [i for i in matches if i >= current]
    return later[0] if later else matches[0]


def jump_in_combo(combo: QComboBox, ch: str, *, cycle: bool | None = None) -> bool:
    """Hoppar i en rullista. True om en post valdes."""
    labels = [combo.itemText(i) for i in range(combo.count())]
    enabled = [
        i for i in range(combo.count())
        if combo.model().flags(combo.model().index(i, 0)) & Qt.ItemFlag.ItemIsEnabled
    ]
    labels_on = [(i, labels[i]) for i in enabled]
    who = id(combo)
    buf = _STATE.take(who, ch)
    if not buf:
        return False
    pairs = [(i, lab) for i, lab in labels_on]
    found = [i for i, lab in pairs if _fold(lab).startswith(buf)]
    do_cycle = cycle if cycle is not None else (len(buf) == 1 and _STATE.buf == buf)
    # Samma ensamma bokstav direkt igen = nästa träff.
    if len(_fold(ch)) == 1 and buf == _fold(ch) * len(buf) and len(buf) > 1 and not found:
        buf = _STATE.reset_to(who, ch)
        found = [i for i, lab in pairs if _fold(lab).startswith(buf)]
        do_cycle = True
    if not found and len(buf) > 1:
        buf = _STATE.reset_to(who, ch)
        found = [i for i, lab in pairs if _fold(lab).startswith(buf)]
        do_cycle = True
    idx = _pick(found, combo.currentIndex(), do_cycle and buf == _fold(ch))
    if idx is None:
        return False
    combo.setCurrentIndex(idx)
    view = combo.view()
    model_index = combo.model().index(idx, combo.modelColumn())
    view.setCurrentIndex(model_index)
    if view.isVisible():
        view.scrollTo(model_index)
    log.info("BOKSTAVSHOPP: %r → %s", buf, combo.itemText(idx))
    return True


def jump_in_menu(menu: QMenu, ch: str) -> bool:
    actions = [
        act for act in menu.actions()
        if act.isEnabled() and act.isVisible() and not act.isSeparator() and act.text()
    ]
    if not actions:
        return False
    who = id(menu)
    buf = _STATE.take(who, ch)
    if not buf:
        return False
    labels = [act.text() for act in actions]
    found = _matches(labels, buf)
    if not found and len(buf) > 1:
        buf = _STATE.reset_to(who, ch)
        found = _matches(labels, buf)
    current = -1
    active = menu.activeAction()
    if active in actions:
        current = actions.index(active)
    pick = _pick(found, current, buf == _fold(ch))
    if pick is None:
        return False
    menu.setActiveAction(actions[pick])
    log.info("BOKSTAVSHOPP: %r → %s", buf, actions[pick].text())
    return True


def _combo_of(obj) -> QComboBox | None:
    widget = obj if hasattr(obj, "parent") else None
    while widget is not None:
        if isinstance(widget, QComboBox):
            return widget
        widget = widget.parent()
    app = QApplication.instance()
    if app is None:
        return None
    popup = app.activePopupWidget()
    if popup is None:
        return None
    for combo in app.findChildren(QComboBox):
        view = combo.view()
        if view is not None and view.isVisible() and view.window() is popup:
            return combo
    return None


def _typing_in_field(obj, combo: QComboBox | None) -> bool:
    if isinstance(obj, (QTextEdit, QPlainTextEdit)):
        return True
    if isinstance(obj, QLineEdit):
        if combo is not None and combo.isEditable() and obj is combo.lineEdit():
            return True
        if combo is None:
            return True
    return False


def handle_key(obj, event) -> bool:
    """True om tangenten användes till ett hopp."""
    if event.type() != QEvent.Type.KeyPress:
        return False
    if event.modifiers() & (
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.MetaModifier
    ):
        return False
    text = event.text()
    if not text or not text.strip() or not text.isprintable():
        return False
    if len(text) != 1:
        return False

    app = QApplication.instance()
    popup = app.activePopupWidget() if app is not None else None
    if isinstance(popup, QMenu):
        return jump_in_menu(popup, text)

    combo = _combo_of(obj)
    if combo is None:
        return False
    if not combo.property("_jump_hint") and not combo.isEditable():
        combo.setProperty("_jump_hint", True)
        extra = "Tryck en bokstav för att hoppa, t.ex. D."
        tip = combo.toolTip()
        if extra not in tip:
            combo.setToolTip((tip + "\n" + extra).strip() if tip else extra)
    if _typing_in_field(obj, combo):
        return False
    return jump_in_combo(combo, text)


class LetterJumpApplication(QApplication):
    """QApplication som ger bokstavshopp i alla rullistor och menyer."""

    def notify(self, receiver, event):  # noqa: N802
        try:
            if handle_key(receiver, event):
                return True
        except Exception as exc:
            log.debug("bokstavshopp: %s", exc)
        return super().notify(receiver, event)
