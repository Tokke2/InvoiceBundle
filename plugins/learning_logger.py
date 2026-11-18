# -*- coding: utf-8 -*-
"""
plugins/learning_logger.py — avancerad loggning av appens självlärande.

Skriver en strukturerad, lättläst revisionslogg över:
  • alla malljämförelser vid skanning (1-sidiga och flersidiga, alla varianter 1..15)
  • manuella matchningar och direktsparade/härledda mallar
  • redigerade automatchningar (både leverantörsbyten och fälträttningar)
    inklusive fältdiffar, inlärningsomräkning och korta textutdrag runt
    de rättade värdena i fakturan (för diagnos via chatten)
  • batch-skanningar (max 15 åt gången + 10 nya vid flytt till Fakturor)

Allt skrivs trådsäkert till ``logs/sjalvlarande.jsonl`` + läsbara rader
till ``logs/sjalvlarande.log`` och sammanfattas till ``FakturaLearn``
så händelserna också syns direkt i Logg-fliken och felsökningspaketet.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("FakturaLearn")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JSONL_NAME = "sjalvlarande.jsonl"
TEXT_NAME = "sjalvlarande.log"
MAX_LOG_BYTES = 5 * 1024 * 1024

_LOCK = threading.Lock()
_LOG_DIR_OVERRIDE: Path | None = None


def set_learning_log_dir(path: str | Path | None) -> None:
    """Pekar om loggmappen (används främst i tester)."""
    global _LOG_DIR_OVERRIDE
    _LOG_DIR_OVERRIDE = Path(path) if path else None


def learning_log_dir(root: Path | None = None) -> Path:
    if _LOG_DIR_OVERRIDE is not None:
        return _LOG_DIR_OVERRIDE
    env = os.environ.get("FAKTURA_LEARNING_LOG_DIR", "").strip()
    if env:
        return Path(env)
    return (Path(root) if root else PROJECT_ROOT) / "logs"


def learning_jsonl_path(root: Path | None = None) -> Path:
    return learning_log_dir(root) / JSONL_NAME


def learning_text_path(root: Path | None = None) -> Path:
    return learning_log_dir(root) / TEXT_NAME


def _rotate_if_large(path: Path) -> None:
    try:
        if path.is_file() and path.stat().st_size > MAX_LOG_BYTES:
            backup = path.with_name(path.name + ".1")
            if backup.exists():
                backup.unlink()
            os.replace(str(path), str(backup))
    except OSError:
        pass


def _append_event(event: dict[str, Any], summary_line: str) -> None:
    payload = dict(event or {})
    payload.setdefault(
        "ts", datetime.datetime.now().isoformat(timespec="seconds")
    )
    with _LOCK:
        try:
            ldir = learning_log_dir()
            ldir.mkdir(parents=True, exist_ok=True)
            jpath = ldir / JSONL_NAME
            tpath = ldir / TEXT_NAME
            _rotate_if_large(jpath)
            _rotate_if_large(tpath)
            with jpath.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        payload, ensure_ascii=False, default=str
                    ) + "\n"
                )
            with tpath.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"{payload['ts']}  [{payload.get('event', 'learn')}]  "
                    f"{summary_line}\n"
                )
        except Exception:
            pass


def _amount_search_forms(amount: Any) -> list[str]:
    try:
        val = abs(float(amount))
    except (TypeError, ValueError):
        return []
    if val <= 0:
        return []
    base_dot = f"{val:.2f}"
    base_comma = base_dot.replace(".", ",")
    whole, dec = base_comma.split(",")
    forms = [base_comma, base_dot]
    if len(whole) > 3:
        spaced = re.sub(r"(?<=\d)(?=(\d{3})+$)", " ", whole)
        dotted = re.sub(r"(?<=\d)(?=(\d{3})+$)", ".", whole)
        forms.extend([f"{spaced},{dec}", f"{dotted},{dec}"])
    if val == int(val):
        w = str(int(val))
        forms.append(w)
        if len(w) > 3:
            forms.append(re.sub(r"(?<=\d)(?=(\d{3})+$)", " ", w))
    return list(dict.fromkeys(forms))


def extract_text_evidence(
    text: str,
    values: dict[str, Any] | None = None,
    *,
    max_lines: int = 8,
) -> dict[str, list[dict[str, str]]]:
    """Extraherar korta rader/kontext ur fakturatexten runt rättade värden.

    Lägger alltid med raden ovanför träffen så att rubrikrad + värderad
    syns tydligt om loggen klistras in i chatten för förbättring av mallen.
    """
    raw = str(text or "")
    if not raw or not isinstance(values, dict):
        return {}
    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    evidence: dict[str, list[dict[str, str]]] = {}

    for field in ("invoice_number", "total_amount", "date", "due_date", "ocr"):
        val = values.get(field)
        if val in (None, "", 0, 0.0):
            continue
        if field == "total_amount":
            needles = _amount_search_forms(val)
        else:
            s = str(val).strip()
            if len(s) < 2:
                continue
            needles = [s]
            if field in ("date", "due_date") and len(s) == 10 and "-" in s:
                needles.append(s.replace("-", "."))
                needles.append(s.replace("-", "/"))
                needles.append(s[2:])
        hits: list[dict[str, str]] = []
        seen_idx: set[int] = set()
        for idx, line in enumerate(lines):
            low = line.casefold()
            if any(needle.casefold() in low for needle in needles):
                if idx in seen_idx:
                    continue
                seen_idx.add(idx)
                hits.append({
                    "prev_line": (lines[idx - 1][:160] if idx > 0 else ""),
                    "line": line[:180],
                    "next_line": (
                        lines[idx + 1][:160] if idx + 1 < len(lines) else ""
                    ),
                })
                if len(hits) >= max_lines:
                    break
        if hits:
            evidence[field] = hits
    return evidence


def _compact_variant_summary(variant: dict | None) -> dict[str, Any]:
    if not isinstance(variant, dict):
        return {}
    fields = variant.get("fields") or {}
    out_fields: dict[str, Any] = {}
    if isinstance(fields, dict):
        for fname, spec in fields.items():
            if not isinstance(spec, dict):
                continue
            if spec.get("region"):
                out_fields[str(fname)] = {
                    "kind": "region",
                    "page": int(spec.get("page", 0) or 0) + 1,
                    "from_end": spec.get("from_end"),
                    "region": list(spec.get("region") or []),
                }
            elif spec.get("label"):
                out_fields[str(fname)] = {
                    "kind": "label",
                    "label": str(spec.get("label", "")),
                    "below": bool(spec.get("below")),
                }
    return {
        "fields": out_fields,
        "logos": len(variant.get("supplier_logos") or []),
    }


def log_template_evaluation(
    *,
    file: str = "",
    pages: int = 0,
    supplier_candidates: list[Any] | None = None,
    templates_checked: list[dict[str, Any]] | None = None,
    selected_supplier: str = "",
    selected_template: str = "",
    variant_index: int | None = None,
    variant_count: int = 0,
    reader_used: str = "primary",
    outcome: str = "",
    parsed: dict[str, Any] | None = None,
) -> None:
    parsed = parsed or {}
    checked = list(templates_checked or [])
    summary = (
        f"fil={file or '?'} sidor={pages} läsare={reader_used} "
        f"leverantör={selected_supplier or '-'} mall={selected_template or '-'} "
        f"(variant={(variant_index + 1) if variant_index is not None else '-'}/"
        f"{variant_count or len(checked)}) utfall={outcome or '?'} "
        f"nr={parsed.get('invoice_number') or '-'} "
        f"belopp={parsed.get('total_amount', 0)}"
    )
    _append_event(
        {
            "event": "scan_template_eval",
            "file": str(file or ""),
            "pages": int(pages or 0),
            "reader": reader_used,
            "supplier_candidates": list(supplier_candidates or [])[:8],
            "templates_checked": checked[:20],
            "selected_supplier": str(selected_supplier or ""),
            "selected_template": str(selected_template or ""),
            "variant_index": variant_index,
            "variant_count": int(variant_count or 0),
            "outcome": str(outcome or ""),
            "parsed": {
                "invoice_number": str(parsed.get("invoice_number") or ""),
                "total_amount": parsed.get("total_amount", 0.0),
                "date": str(parsed.get("date") or ""),
                "due_date": str(parsed.get("due_date") or ""),
                "ocr": str(parsed.get("ocr") or ""),
                "missing": list(parsed.get("missing") or []),
                "match_uncertain": bool(parsed.get("match_uncertain")),
                "match_reason": str(parsed.get("match_reason") or ""),
            },
        },
        summary,
    )
    log.debug(
        "[SJÄLVLÄRANDE] Malljämförelse %s",
        summary,
        extra={"action": "SELF_LEARN_EVAL"},
    )


def log_manual_match(
    *,
    source: str,
    file: str = "",
    pages: int = 0,
    supplier: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    template_saved: bool = False,
    template_variant: dict | None = None,
    template_count: int = 0,
    confirmations_before: int = 0,
    confirmations_after: int = 0,
    multipage_confirmed: int = 0,
    graduated: bool = False,
    identifiers_learned: dict[str, Any] | None = None,
    logo_learned: bool = False,
) -> None:
    summary = (
        f"källa={source} fil={file or '-'} sidor={pages} leverantör={supplier} "
        f"bekräftelser={confirmations_before}->{confirmations_after} "
        f"mallar={template_count}/15 ny_mall={template_saved} "
        f"flersidig={multipage_confirmed} auto_redo={graduated} logo={logo_learned}"
    )
    _append_event(
        {
            "event": "manual_match",
            "source": str(source or ""),
            "file": str(file or ""),
            "pages": int(pages or 0),
            "supplier": str(supplier or ""),
            "before": dict(before or {}),
            "after": dict(after or {}),
            "template_saved": bool(template_saved),
            "template_count": int(template_count or 0),
            "template_summary": _compact_variant_summary(template_variant),
            "confirmations_before": int(confirmations_before or 0),
            "confirmations_after": int(confirmations_after or 0),
            "multipage_confirmed": int(multipage_confirmed or 0),
            "graduated": bool(graduated),
            "identifiers_learned": dict(identifiers_learned or {}),
            "logo_learned": bool(logo_learned),
        },
        summary,
    )
    log.info(
        "[SJÄLVLÄRANDE] Manuell matchning: %s",
        summary,
        extra={"action": "SELF_LEARN_MATCH"},
    )


def log_auto_match_edit(
    *,
    source: str,
    file: str = "",
    pages: int = 0,
    supplier_before: str = "",
    supplier_after: str = "",
    field_diffs: dict[str, dict[str, Any]] | None = None,
    counter_reset: bool = False,
    template_action: str = "",
    template_count: int = 0,
    template_summary: dict | None = None,
    text_evidence: dict[str, Any] | None = None,
) -> None:
    diffs = dict(field_diffs or {})
    diff_str = ", ".join(
        f"{k}: {v.get('before', '')}->{v.get('after', '')}"
        for k, v in diffs.items()
    ) or "inga"
    summary = (
        f"källa={source} fil={file or '-'} sidor={pages} "
        f"lev={supplier_before or '-'}->{supplier_after or '-'} "
        f"ändringar=[{diff_str}] reset={counter_reset} "
        f"mall={template_action or 'ingen'} ({template_count}/15)"
    )
    _append_event(
        {
            "event": "auto_match_edit",
            "source": str(source or ""),
            "file": str(file or ""),
            "pages": int(pages or 0),
            "supplier_before": str(supplier_before or ""),
            "supplier_after": str(supplier_after or ""),
            "field_diffs": diffs,
            "counter_reset": bool(counter_reset),
            "template_action": str(template_action or ""),
            "template_count": int(template_count or 0),
            "template_summary": (
                _compact_variant_summary(template_summary)
                if isinstance(template_summary, dict) else {}
            ),
            "text_evidence": dict(text_evidence or {}),
        },
        summary,
    )
    log.info(
        "[SJÄLVLÄRANDE] Rättad automatchning: %s",
        summary,
        extra={"action": "SELF_LEARN_EDIT"},
    )


def log_batch_scan(
    *,
    mode: str,
    batch_limit: int,
    scanned: int,
    queued_remaining: int,
    trigger: str = "",
) -> None:
    summary = (
        f"läge={mode} gräns={batch_limit} inlästa={scanned} "
        f"kvar_i_kö={queued_remaining} orsak={trigger or '-'}"
    )
    _append_event(
        {
            "event": "batch_scan",
            "mode": str(mode or ""),
            "batch_limit": int(batch_limit or 0),
            "scanned": int(scanned or 0),
            "queued_remaining": int(queued_remaining or 0),
            "trigger": str(trigger or ""),
        },
        summary,
    )
    log.info(
        "[SJÄLVLÄRANDE] Batchskanning: %s",
        summary,
        extra={"action": "SELF_LEARN_BATCH"},
    )


def read_recent_events(
    limit: int = 50, root: Path | None = None
) -> list[dict[str, Any]]:
    path = learning_jsonl_path(root)
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-max(1, limit * 2):]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out[-limit:]


def format_learning_report(
    learning: dict | None = None,
    templates: dict | None = None,
    suppliers: list[dict] | None = None,
    *,
    root: Path | None = None,
    max_events: int = 35,
) -> str:
    """Bygger en tydlig sammanställning av självlärandet för chatten."""
    learning = learning if isinstance(learning, dict) else {}
    templates = templates if isinstance(templates, dict) else {}
    suppliers = suppliers if isinstance(suppliers, list) else []

    lines: list[str] = []
    lines.append("═══ FAKTURABUNTEN — SJÄLVLÄRANDERAPPORT FÖR CHATT ═══")
    lines.append(
        f"Genererad: {datetime.datetime.now().isoformat(timespec='seconds')}"
    )
    lines.append(
        f"Leverantörer i register: {len(suppliers)}  ·  "
        f"Leverantörer med sparad mall: {len(templates)}  ·  "
        f"Leverantörer i inlärningsminnet: {len(learning)}"
    )
    lines.append(f"Loggfil (JSONL): {learning_jsonl_path(root)}")

    # Per-leverantör översikt (mallar 1..15 + inlärningsstatus)
    all_names: list[str] = []
    seen_cf: set[str] = set()
    for name in list(templates.keys()) + list(learning.keys()):
        n = str(name or "").strip()
        cf = n.casefold()
        if n and cf not in seen_cf:
            seen_cf.add(cf)
            all_names.append(n)

    lines.append("")
    lines.append(f"── Leverantörsmallar & minne ({len(all_names)}) ──")
    if not all_names:
        lines.append("(inga sparade mallar eller inlärda matchningar ännu)")
    for name in sorted(all_names, key=str.casefold):
        t_entry = templates.get(name) if isinstance(templates.get(name), dict) else {}
        variants: list[dict] = []
        if isinstance(t_entry.get("variants"), list):
            variants.extend(v for v in t_entry["variants"] if isinstance(v, dict))
        if isinstance(t_entry.get("fields"), dict) and t_entry["fields"]:
            if not variants:
                variants.append({"fields": t_entry["fields"]})
        l_entry = learning.get(name) if isinstance(learning.get(name), dict) else {}
        confirmed = int(l_entry.get("confirmed", 0) or 0)
        mp_conf = int(l_entry.get("multipage_confirmed", 0) or 0)
        corrections = int(l_entry.get("corrections", 0) or 0)
        logos = len(l_entry.get("logos") or {}) if isinstance(l_entry.get("logos"), dict) else 0
        ids = l_entry.get("identifiers") or {}
        id_count = sum(
            len(b) for b in ids.values() if isinstance(b, dict)
        ) if isinstance(ids, dict) else 0
        lines.append(
            f"• {name}: bekräftelser={confirmed}/5, flersidiga={mp_conf}, "
            f"rättningar={corrections}, mallvarianter={len(variants)}/15, "
            f"kännetecken={id_count}, logotyper={logos}"
        )
        for idx, var in enumerate(variants, start=1):
            fields = var.get("fields") or {}
            parts = []
            for fname, spec in fields.items():
                if not isinstance(spec, dict):
                    continue
                if spec.get("region"):
                    p = int(spec.get("page", 0) or 0) + 1
                    fe = spec.get("from_end")
                    tag = f"s.{p}" + (f"(från slut -{fe})" if fe is not None else "")
                    parts.append(f"{fname}=ruta@{tag}")
                elif spec.get("label"):
                    b = "↓" if spec.get("below") else ""
                    parts.append(f"{fname}='{spec['label']}'{b}")
            lines.append(f"    variant {idx}: {', '.join(parts) or '(tom)'}")

    events = read_recent_events(max_events, root=root)
    lines.append("")
    lines.append(f"── Senaste självlärandehändelser ({len(events)}) ──")
    if not events:
        lines.append("(inga händelser loggade ännu)")
    for ev in events:
        etype = ev.get("event", "?")
        ts = ev.get("ts", "")
        if etype == "auto_match_edit":
            lines.append(
                f"{ts}  [RÄTTAD AUTOMATCH] {ev.get('file', '-')} "
                f"(sidor={ev.get('pages', 0)}, {ev.get('source', '')}) "
                f"lev={ev.get('supplier_before', '-')}->{ev.get('supplier_after', '-')} "
                f"reset={ev.get('counter_reset')} mall={ev.get('template_action', '-')}"
            )
            for fname, diff in (ev.get("field_diffs") or {}).items():
                lines.append(
                    f"    diff {fname}: {diff.get('before', '')!r} -> {diff.get('after', '')!r}"
                )
            for fname, snippets in (ev.get("text_evidence") or {}).items():
                for sn in snippets[:2]:
                    prev_l = sn.get("prev_line", "")
                    curr_l = sn.get("line", "")
                    lines.append(
                        f"    textbevis[{fname}]: "
                        + (f"föreg={prev_l!r} | " if prev_l else "")
                        + f"rad={curr_l!r}"
                    )
        elif etype == "manual_match":
            lines.append(
                f"{ts}  [MANUELL MATCHNING] {ev.get('file', '-')} "
                f"(sidor={ev.get('pages', 0)}, {ev.get('source', '')}) "
                f"lev={ev.get('supplier', '-')} "
                f"bekräftelser={ev.get('confirmations_before', 0)}->{ev.get('confirmations_after', 0)} "
                f"mallar={ev.get('template_count', 0)}/15 ny_mall={ev.get('template_saved')}"
            )
        elif etype == "scan_template_eval":
            p = ev.get("parsed") or {}
            lines.append(
                f"{ts}  [MALLJÄMFÖRELSE] {ev.get('file', '-')} "
                f"(sidor={ev.get('pages', 0)}, {ev.get('reader', 'primary')}) "
                f"lev={ev.get('selected_supplier') or '-'} "
                f"mall={ev.get('selected_template') or '-'} "
                f"utfall={ev.get('outcome', '-')} "
                f"nr={p.get('invoice_number') or '-'} "
                f"belopp={p.get('total_amount', 0)}"
            )
            for chk in (ev.get("templates_checked") or [])[:6]:
                lines.append(
                    f"    kandidat: {chk.get('supplier', '?')} "
                    f"var={chk.get('variant', '?')} "
                    f"typ={chk.get('kind', '?')} claimed={chk.get('claimed')} "
                    f"fält={chk.get('fields', [])}"
                )
        elif etype == "batch_scan":
            lines.append(
                f"{ts}  [BATCHSKANNING] läge={ev.get('mode')} "
                f"inlästa={ev.get('scanned')}/{ev.get('batch_limit')} "
                f"kvar_i_kö={ev.get('queued_remaining')} "
                f"orsak={ev.get('trigger', '-')}"
            )
        else:
            lines.append(f"{ts}  [{etype}] {json.dumps(ev, ensure_ascii=False)}")
    lines.append("═══ SLUT SJÄLVLÄRANDERAPPORT ═══")
    return "\n".join(lines)
