from __future__ import annotations

"""
Fakturabunten — Application Core
========================================
Fil    : Fakturabunten_/app.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Central applikationskärna: data-motorer, settings, plugin-laddare,
backup och JSON-lagring. Alla vyer och plugins pratar med denna fil.

PRINCIPER
---------
• Ingen momsberäkning — belopp sparas exakt som användaren anger.
• Användaren väljer + (faktura) eller − (kredit) i UI.
• total_amount: positivt = faktura, negativt = kreditfaktura.
• invoice_type sätts automatiskt: "Faktura" / "Kreditfaktura".
• Alla data sparas i JSON-filer (aldrig SQLite).
• Atomisk skrivning: skriv till .tmp → rename.
• UUID-baserad identitet — aldrig index-baserat CRUD.
• Senast ändrad post sorteras alltid SIST i alla listor (MUST-023).
• Settings sparas i settings.json.
• Backup skapas automatiskt vid start (om aktiverat) till mappen 'bak'.
• Restore är Zip Slip-säker.
• 4 teman: dark / light / auto / system.
• Multi-OS: Windows / Linux / macOS.
• Autostart med OS stöds och synkas korrekt (AutostartManager är MASTER).
• Systray-stöd: göm vid kryss, avsluta helt via meny.
• Plugin-arkitektur: register(app) → register_ui(main_window).
• session_due_date: sätts av main.py EN gång per session, sparas ALDRIG
  i JSON och nollställs automatiskt vid nästa programstart.

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import hashlib
import importlib.util
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

# ═════════════════════════════════════════════════════════════════════
#  LOGGING — rör aldrig en redan konfigurerad root-logger (main.py äger den)
# ═════════════════════════════════════════════════════════════════════

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  →  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

log = logging.getLogger("FakturaApp")

# ═════════════════════════════════════════════════════════════════════
#  SÖKVÄGAR & KONSTANTER
# ═════════════════════════════════════════════════════════════════════

APP_NAME: str = "Fakturabunten"
APP_SHORT_NAME: str = "Fakturabunten"
APP_VERSION: str = "1.0.0"

COPYRIGHT_YEAR: int = datetime.date.today().year
COPYRIGHT: str = f"© {COPYRIGHT_YEAR} Rickard Längkvist"

#: Donationsuppgifter. PayPal/Ko-fi ägs av ui/donate.py (dialogen);
#: Swish bor här. Används av ui/donate.py och Om-dialogen.
DONATE_SWISH: str = "0721817177"   # Swish-nummer för donationer
DONATE_PAYPAL: str = "https://paypal.me/Rickard3dPrint"
DONATE_KOFI: str = "https://ko-fi.com/tokke2"
DONATE_BMC: str = "https://ko-fi.com/tokke2"  # bakåtkompat: BMC → Ko-fi

#: Bakåtkompatibilitet (äldre kod/plugins som använder DONATE_URL).
DONATE_URL: str = DONATE_PAYPAL

BASE_DIR: Path = Path(__file__).parent.resolve()
#: Kanonisk datamapp: <appmappen>/data (strukturen på produktions-
#: maskiner). Äldre installationer kan ha data i ui/data — det
#: hanteras av FakturaApp via bakåtkompatibilitets-kontrollen.
DATA_DIR: Path = BASE_DIR / "data"
LEGACY_DATA_DIR: Path = BASE_DIR / "ui" / "data"
PLUGIN_DIR: Path = BASE_DIR / "plugins"
BACKUP_DIR: Path = BASE_DIR / "bak"
EXPORT_DIR: Path = BASE_DIR / "exports"
SETTINGS_FILE: Path = BASE_DIR / "settings.json"

VALID_THEMES: tuple[str, ...] = ("dark", "light", "auto", "system")

VALID_INVOICE_STATUSES: list[str] = [
    "Obetald",
    "Planerad",
    "Betalfil skapad",
    "Betald",
    "Förfallen",
    "Makulerad",
    "Arkiverad",
]

#: Statusar som INTE räknas som obetalda.
NON_UNPAID_STATUSES: tuple[str, ...] = ("Betald", "Makulerad", "Arkiverad")

#: Statusar som INTE räknas som aktiva.
NON_ACTIVE_STATUSES: tuple[str, ...] = ("Arkiverad", "Makulerad")


def get_platform() -> str:
    """Returnerar 'windows' | 'macos' | 'linux'."""
    p = platform.system().lower()
    if p == "darwin":
        return "macos"
    if p == "windows":
        return "windows"
    return "linux"


CURRENT_PLATFORM: str = get_platform()

# ═════════════════════════════════════════════════════════════════════
#  DEFAULT SETTINGS
# ═════════════════════════════════════════════════════════════════════

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme":            "dark",
    # Gränssnittsspråk: "sv" (standard) eller "en". Byts i menyn
    # 🌐 Språk och gäller direkt, utan omstart (ui/i18n.py).
    "language":         "sv",
    "hidden_tabs":      [],
    "window_width":     1280,
    "window_height":    800,
    "window_x":         -1,
    "window_y":         -1,
    "window_maximized": False,
    "font_size":        13,
    "startup":          False,
    "autostart_method": "auto",
    "start_minimized":  True,
    "close_to_tray":    True,
    "export_include_originals": True,
    "update_auto_check": True,
    "auto_batch":      False,
    "update_last_check": "",
    "last_opened":      None,
    "company_name":     "",
    "org_number":       "",
    "currency":         "SEK",
    # Relativa sökvägar. Löses mot appmappen vid start, aldrig mot
    # den mapp man råkar stå i. Då fungerar kopian på USB och efter
    # flytt, oavsett enhetsbeteckning.
    "backup_path":      "bak",
    "db_path":          "data",
    "export_path":      "exports",
    "notify_due_days":  3,
    "auto_backup":      True,
    "backup_keep":      10,
    # Dagar innan exporterade PDF:er auto-arkiveras till exports/Arkiv/
    # (0 = avstängt).
    "archive_exports_days": 10,
    # Dagar innan gamla backuper auto-arkiveras till bak/Arkiv/
    # (0 = avstängt).
    "archive_backups_days": 3,
    # Dagar innan __pycache__/*.pyc städas bort automatiskt (0 = av).
    "pycache_keep_days": 3,
    # Avrundning av ATT BETALA i PDF: exact / hel / 50 / 100.
    "pdf_rounding": "exact",
    # Schema-version för settings.json (auto-reparation vid uppgradering).
    "schema_version": 1,
    # TRACE-loggning: logga VARJE musklick/tangenttryck/fokus/scroll.
    # PÅ = standard ("logga precis allt"). Kan slås av i
    # Inställningar-menyn utan omstart.
    "log_trace": True,
    # SMART CACHE-RENSARE: töm appens cache (__pycache__, *.pyc,
    # *.tmp-lämmar) automatiskt när programmet avslutas.
    # Data, settings, loggar och backuper röras ALDRIG.
    "clean_cache_on_exit": True,
    # Plugin-hälsa: antal raka krascher per plugin (3-strikes-regeln).
    "plugin_strikes": {},
    # Plugins som avaktiverats efter 3 krascher (återställs via
    # Inställningar-fliken eller manuellt i filen).
    "disabled_plugins": [],
}

#: Aktuell schema-version för settings.json.
SETTINGS_SCHEMA_VERSION: int = int(DEFAULT_SETTINGS["schema_version"])

#: Värden som måste tillhöra en fast mängd.
SETTINGS_ALLOWED_VALUES: dict[str, tuple] = {
    "theme": ("dark", "light", "auto", "system"),
    "language": ("sv", "en"),
    "pdf_rounding": ("exact", "hel", "50", "100"),
}


def validate_settings(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """
    Validerar och REPARERAR settings-dict mot schemat (idén från
    PDF reader Pro SPEC v2.1, punkt 2.2).

    Regler:
    • Saknad nyckel        → standardvärdet återställs.
    • Fel typ              → standardvärdet återställs (rep. loggas).
    • Ogiltigt valevärde   → standardvärdet återställs (rep. loggas).
    • Okända nycklar       → behålls orörda (bakåtkompatibilitet).
    • Hela filen korrupt   → hanteras av SettingsManager.load()
                              (namnbyts till *.corrupt-<timestamp>).

    Returnerar (ren_dict, lista_med_reparationer).
    """
    repairs: list[str] = []
    clean: dict[str, Any] = {}

    if not isinstance(raw, dict):
        repairs.append("settings var ingen dict → alla standardvärden")
        raw = {}

    for key, default in DEFAULT_SETTINGS.items():
        if key not in raw:
            clean[key] = default
            continue
        value = raw[key]
        ok = True
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int):
                ok = False
        elif isinstance(default, float):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif isinstance(default, str):
            ok = isinstance(value, str)
        elif isinstance(default, list):
            ok = isinstance(value, list)
        elif isinstance(default, dict):
            ok = isinstance(value, dict)
        # default None → valfri typ tillåten
        if not ok:
            repairs.append(f"{key}: {value!r} → standard {default!r}")
            clean[key] = default
        else:
            clean[key] = value

    # Värden som måste ligga i en fast mängd
    for key, allowed in SETTINGS_ALLOWED_VALUES.items():
        if clean.get(key) not in allowed:
            repairs.append(
                f"{key}: {clean.get(key)!r} → standard {DEFAULT_SETTINGS[key]!r}"
            )
            clean[key] = DEFAULT_SETTINGS[key]

    # schema_version hålls alltid aktuellt
    clean["schema_version"] = SETTINGS_SCHEMA_VERSION

    # Okända nycklar bevaras (plugins/äldre versioner)
    for key, value in raw.items():
        if key not in clean:
            clean[key] = value

    return clean, repairs

# ═════════════════════════════════════════════════════════════════════
#  DATA-SCHEMAN  (standardvärden för varje entitet)
# ═════════════════════════════════════════════════════════════════════

INVOICE_SCHEMA: dict[str, Any] = {
    "id":             "",
    "invoice_type":   "Faktura",
    "supplier":       "",
    "invoice_number": "",
    "ocr":            "",
    "date":           "",
    "due_date":       "",
    "payment_date":   "",
    "total_amount":   0.0,
    "vat_amount":     0.0,
    "amount_ex_vat":  0.0,
    "vat_percent":    0,
    "currency":       "SEK",
    "status":         "Obetald",
    "category":       "",
    "reference":      "",
    "note":           "",
    "attachment":     "",
    "created_at":     "",
    "updated_at":     "",
}

SUPPLIER_SCHEMA: dict[str, Any] = {
    "id":             "",
    "name":           "",
    "org_number":     "",
    "bg":             "",
    "pg":             "",
    "iban":           "",
    "bic":            "",
        "payment_terms":  30,
        "favorite":       False,
        "contact_person": "",
    "email":          "",
    "phone":          "",
    "address":        "",
    "note":           "",
    "created_at":     "",
    "updated_at":     "",
}

PAYMENT_SCHEMA: dict[str, Any] = {
    "id":           "",
    "invoice_ids":  [],
    "payment_date": "",
    "total_amount": 0.0,
    "currency":     "SEK",
    "status":       "Planerad",
    "note":         "",
    "created_at":   "",
    "updated_at":   "",
}

# ═════════════════════════════════════════════════════════════════════
#  HJÄLPFUNKTIONER
# ═════════════════════════════════════════════════════════════════════


def _now_iso() -> str:
    """
    Aktuell tid som ISO-sträng (mikrosekundprecision).

    Mikrosekunder krävs för att MUST-023 ("senast ändrad sist") ska
    fungera även när två ändringar sker inom samma sekund —
    strängsortering ger då ändå korrekt ordning.
    """
    return datetime.datetime.now().isoformat(timespec="microseconds")


def _new_id() -> str:
    """Nytt UUID4 som sträng."""
    return str(uuid.uuid4())


def _ensure_dir(path: Path) -> None:
    """Skapar mapp (och föräldrar) om den saknas."""
    path.mkdir(parents=True, exist_ok=True)


def _abs_path(value: Any, fallback: Path) -> Path:
    """
    Gör en settings-sökväg absolut — relativa sökvägar löses alltid
    mot projektroten (BASE_DIR), ALDRIG mot aktuell arbetsmapp.

    Kritiskt på Windows: autostart via registret ger arbetsmappen
    C:\\Windows\\System32 — relativa mappar där = WinError 5.
    """
    try:
        p = Path(str(value)) if value not in (None, "") else fallback
    except Exception:
        p = fallback
    if not p.is_absolute():
        p = BASE_DIR / p
    return p


def _is_inside(path: Path, root: Path) -> bool:
    """True om path (efter resolve) ligger i root. Symlänk ut räknas inte."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def confine_to_app(value: Any, fallback: Path) -> Path:
    """
    Absolut sökväg som MÅSTE ligga i appmappen.

    Relativa sökvägar löses mot BASE_DIR. Ligger värdet utanför
    (eller går inte att lösa) används fallback, och en varning loggas.
    """
    fallback = fallback if fallback.is_absolute() else (BASE_DIR / fallback)
    try:
        fallback = fallback.resolve()
    except OSError:
        fallback = BASE_DIR / Path(str(fallback).replace("\\", "/")).name
    if not _is_inside(fallback, BASE_DIR):
        fallback = BASE_DIR.resolve()
    try:
        raw = Path(str(value)) if value not in (None, "") else fallback
    except Exception:
        log.warning("SÖKVÄG_UTANFÖR: ogiltig %r → %s", value, fallback)
        return fallback
    if not raw.is_absolute():
        raw = BASE_DIR / raw
    try:
        resolved = raw.resolve()
    except OSError:
        log.warning("SÖKVÄG_UTANFÖR: kan inte lösa %s → %s", raw, fallback)
        return fallback
    if not _is_inside(resolved, BASE_DIR):
        log.warning(
            "SÖKVÄG_UTANFÖR: %s ligger utanför appmappen → %s",
            resolved, fallback,
        )
        return fallback
    return resolved


def safe_app_root(name: str) -> Path:
    """
    Undermapp i appmappen. Följer inte en symlänk som pekar ut.
    """
    preferred = BASE_DIR / name
    try:
        if preferred.is_symlink() and not _is_inside(
            preferred.resolve(), BASE_DIR
        ):
            log.error(
                "SYMLÄNK_UTANFÖR: %s pekar utanför appmappen",
                preferred,
            )
            alt = BASE_DIR / f"{name}_inne"
            alt.mkdir(parents=True, exist_ok=True)
            return alt.resolve()
        preferred.mkdir(parents=True, exist_ok=True)
        resolved = preferred.resolve()
        if _is_inside(resolved, BASE_DIR):
            return resolved
    except OSError as exc:
        log.warning("safe_app_root(%s): %s", name, exc)
    preferred.mkdir(parents=True, exist_ok=True)
    return preferred


def confine_under(root_name: str, value: Any) -> Path:
    """Tvingar value att ligga i <appmappen>/<root_name>."""
    root = safe_app_root(root_name)
    candidate = confine_to_app(value, root)
    if not _is_inside(candidate, root):
        log.warning(
            "SÖKVÄG_FEL_UNDERMAPP: %s hör inte till %s → %s",
            candidate, root, root,
        )
        return root
    return candidate


def confine_export_file(path: str | Path) -> Path:
    """
    En exportfil får bara skapas under exports/.

    Ligger sökvägen utanför flyttas filen in. En lös fil direkt i
    exports/ läggs i dagens undermapp så roten förblir mappar.
    """
    root = safe_app_root("exports")
    raw = Path(path)
    if not raw.is_absolute():
        parts = [p for p in raw.parts if p not in ("", ".", "..")]
        candidate = root.joinpath(*parts) if parts else root / "fakturalista.pdf"
    else:
        candidate = raw
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = root / (raw.name or "fakturalista.pdf")
    if not _is_inside(resolved, root):
        safe = Path(raw.name or "fakturalista.pdf").name
        safe = "".join(
            c if c not in '<>:"|?*\\/' else "_" for c in safe
        )
        if not safe or safe in (".", ".."):
            safe = "fakturalista.pdf"
        lower = safe.lower()
        if not lower.endswith((".pdf", ".txt", ".json")):
            safe += ".pdf"
        dest = root / datetime.date.today().isoformat() / safe
        dest.parent.mkdir(parents=True, exist_ok=True)
        log.warning("EXPORT_FLYTTAD: %s → %s", path, dest)
        return dest
    if resolved.parent == root:
        day = root / datetime.date.today().isoformat()
        day.mkdir(parents=True, exist_ok=True)
        return day / resolved.name
    return resolved


def cleanup_pycache(root: Path | None = None, days: int = 3) -> int:
    """
    Rensar __pycache__-mappar och *.pyc-filer äldre än *days* dagar
    under *root* (standard: projektroten).

    Fail-safe: kastar aldrig undantag, hoppar över låsta filer.
    Färskt __pycache__ (t.ex. skrivet vid denna start) rörs inte.
    Returnerar antal borttagna objekt.
    """
    root = root or BASE_DIR
    if days <= 0:
        return 0
    cutoff = datetime.datetime.now().timestamp() - days * 86400
    removed = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            for d in list(dirnames):
                if d != "__pycache__":
                    continue
                dirnames.remove(d)   # traversera inte ner i den
                p = Path(dirpath) / d
                try:
                    if p.stat().st_mtime < cutoff:
                        shutil.rmtree(p, ignore_errors=True)
                        removed += 1
                except OSError:
                    pass
            for f in filenames:
                if f.endswith(".pyc"):
                    p = Path(dirpath) / f
                    try:
                        if p.stat().st_mtime < cutoff:
                            p.unlink(missing_ok=True)
                            removed += 1
                    except OSError:
                        pass
    except Exception as exc:
        log.warning("cleanup_pycache: %s", exc)
    if removed:
        log.info("Städade bort %d gamla __pycache__/pyc", removed)
    return removed


def clean_caches(root: Path | None = None) -> dict[str, Any]:
    """
    SMART CACHE-RENSARE — töm appens cache (körs normalt vid avslut).

    Rensar ENDAST regenererbara cache-filer inom appmappen:
        • Alla __pycache__-mappar
        • Alla *.pyc / *.pyo-filer
        • Kvarlämnade *.tmp-filer från (atomära) skrivningar

    Rör ALDRIG: JSON-data, settings.json, shortcuts.json, logs/,
    bak/, exports/, ikoner eller någon annan riktig fil.

    Returnerar en statistika-dict (antal + frigjorda bytes) som loggas.
    Fail-safe: kastar aldrig, hoppar över låsta filer (Windows).
    """
    root = root or BASE_DIR
    stats = {
        "pycache_mappar": 0,
        "pyc_filer": 0,
        "tmp_filer": 0,
        "frigjorda_bytes": 0,
    }
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # __pycache__-mappar: ta bort och traversera inte ner i dem
            for d in list(dirnames):
                if d != "__pycache__":
                    continue
                dirnames.remove(d)
                p = Path(dirpath) / d
                try:
                    size = sum(
                        f.stat().st_size for f in p.rglob("*")
                        if f.is_file()
                    )
                except OSError:
                    size = 0
                shutil.rmtree(p, ignore_errors=True)
                if not p.exists():
                    stats["pycache_mappar"] += 1
                    stats["frigjorda_bytes"] += size

            for f in filenames:
                lower = f.lower()
                p = Path(dirpath) / f
                is_pyc = lower.endswith((".pyc", ".pyo"))
                is_tmp = lower.endswith(".tmp") or ".tmp." in lower
                if not (is_pyc or is_tmp):
                    continue
                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0
                try:
                    p.unlink()
                except OSError:
                    continue  # låst fil (Windows) — hoppa över tyst
                if is_pyc:
                    stats["pyc_filer"] += 1
                else:
                    stats["tmp_filer"] += 1
                stats["frigjorda_bytes"] += size
    except Exception as exc:
        log.warning("clean_caches: %s", exc)

    if (
        stats["pycache_mappar"]
        or stats["pyc_filer"]
        or stats["tmp_filer"]
    ):
        log.info(
            "CACHE_CLEAN: %d __pycache__, %d pyc, %d tmp borttagna "
            "(%.1f KB frigjort)",
            stats["pycache_mappar"],
            stats["pyc_filer"],
            stats["tmp_filer"],
            stats["frigjorda_bytes"] / 1024.0,
        )
    else:
        log.debug("CACHE_CLEAN: cachen var redan tom")
    return stats


#: Kända legacy-loggfiler från ÄLDRE loggversioner (multi-file).
#: Nuvarande version skriver ENDAST logs/app.log — dessa städas bort
#: vid start så att appmappen hålls ren och en-fil-principen gäller.
LEGACY_LOG_FILES: tuple[str, ...] = (
    "app.log",                    # lös kopia i roten
    "logs/audit.log",
    "logs/errors.log",
    "logs/performance.log",
    "logs/structured.jsonl",
    "structured.jsonl",
)


def clean_legacy_logs(root: Path | None = None) -> int:
    """
    Tar bort legacy-loggfiler från äldre versioner (EN-fil-principen).

    Rör ALDRIG logs/app.log (den aktuenda enda loggen) eller logs/archive/.
    Returnerar antal borttagna filer. Fail-safe: kastar aldrig.
    """
    root = root or BASE_DIR
    removed = 0
    for rel in LEGACY_LOG_FILES:
        p = root / rel
        # Skydda den riktiga loggen om någon råkat hamna i listan
        if p.resolve() == LOG_FILE_ABS:
            continue
        try:
            if p.exists() and p.is_file():
                p.unlink()
                removed += 1
                log.info("LEGACY_LOG borttagen: %s", rel)
        except OSError:
            pass  # låst fil — hoppa över tyst
    # Töm logs/archive/ (gamla roterade filer) men behåll mappen
    archive_dir = root / "logs" / "archive"
    if archive_dir.exists():
        try:
            for f in archive_dir.iterdir():
                try:
                    if f.is_file():
                        f.unlink()
                        removed += 1
                except OSError:
                    pass
        except OSError:
            pass
    if removed:
        log.info("LEGACY_CLEAN: %d gamla loggfiler borttagna", removed)
    return removed


#: Absolut sökväg till den ENDA loggfilen (skyddas av clean_legacy_logs).
LOG_FILE_ABS: Path = (BASE_DIR / "logs" / "app.log").resolve()


def _load_json(path: Path, default: Any = None) -> Any:
    """Läser JSON-fil. Returnerar default vid fel eller saknad fil."""
    try:
        if path.exists():
            # utf-8-sig: Notepad++ sparar ofta BOM. Utan det blir filen
            # "trasig" och appen läser 0 poster trots att filen är full.
            with open(path, "r", encoding="utf-8-sig") as fh:
                return json.load(fh)
    except Exception as exc:
        log.error("JSON load error (%s): %s", path, exc)
    return default if default is not None else []


def read_json_any(path: Path) -> tuple[Any, str]:
    """
    Läser en JSON-fil utan att svälja felet tyst.

    Returnerar (data, status):
        missing | empty | ok | parse_error
    """
    try:
        if not path.exists() or not path.is_file():
            return None, "missing"
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        log.error("DATA_LÄSFEL: kan inte öppna %s (%s)", path, exc)
        return None, "parse_error"
    if not raw.strip():
        return None, "empty"
    try:
        return json.loads(raw), "ok"
    except json.JSONDecodeError as exc:
        log.error(
            "DATA_LÄSFEL: %s är inte giltig JSON (%s) — filen skrivs inte över",
            path, exc,
        )
        return None, "parse_error"


def unwrap_records(data: Any, filename: str = "") -> list[dict]:
    """
    Gör om olika JSON-former till en lista poster.

    Accepterar:
        [ {...}, {...} ]
        {"suppliers": [ ... ]}  (även invoices/payments/data/records)
        ett ensamt objekt med name / id / invoice_number
    """
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        stem = Path(filename).stem.lower() if filename else ""
        keys = (
            stem,
            "suppliers", "invoices", "payments",
            "data", "records", "items", "rows",
        )
        for key in keys:
            if key and isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
        if any(data.get(k) for k in ("name", "id", "invoice_number")):
            return [data]
    return []


def _record_identity(record: dict, kind: str) -> str:
    """Nyckel för sammanslagning. Samma leverantör ska inte bli två rader."""
    rid = str(record.get("id") or "").strip()
    if kind == "suppliers":
        name = str(record.get("name") or "").strip().casefold()
        return f"name:{name}" if name else f"id:{rid}"
    if kind == "invoices":
        num = str(record.get("invoice_number") or "").strip().casefold()
        sup = str(record.get("supplier") or "").strip().casefold()
        if num or sup:
            return f"inv:{sup}|{num}"
    return f"id:{rid}" if rid else ""


def _filled_score(record: dict) -> int:
    return sum(1 for v in record.values() if v not in ("", None, [], {}))


def merge_record_lists(
    groups: list[list[dict]], kind: str
) -> list[dict]:
    """Slår ihop listor. Samma identitet behåller den fylligaste posten."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for group in groups:
        for rec in group:
            if not isinstance(rec, dict):
                continue
            key = _record_identity(rec, kind)
            if not key or key in ("name:", "id:", "inv:|"):
                key = f"anon:{len(order)}:{id(rec)}"
            if key not in merged:
                merged[key] = dict(rec)
                order.append(key)
                continue
            old = merged[key]
            newer = str(rec.get("updated_at") or "") >= str(
                old.get("updated_at") or ""
            )
            if _filled_score(rec) > _filled_score(old) or newer:
                kept_id = old.get("id") or rec.get("id")
                merged[key] = dict(rec)
                if kept_id and not merged[key].get("id"):
                    merged[key]["id"] = kept_id
    return [merged[k] for k in order]


_DATA_SKIP_DIRS = {
    "bak", "exports", "logs", "plugins", "autostart", "tests",
    "__pycache__", ".git", "node_modules",
}


def discover_json_copies(app_root: Path, filename: str) -> list[Path]:
    """
    Hittar alla kopior av t.ex. suppliers.json inuti appmappen.
    data/ kommer först. Hoppar över backup, export och logg.
    """
    found: list[Path] = []
    root = app_root.resolve()
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in _DATA_SKIP_DIRS and not d.startswith(".")
            ]
            if filename in filenames:
                found.append(Path(dirpath) / filename)
    except OSError as exc:
        log.warning("discover_json_copies: %s", exc)
    canon = (root / "data" / filename).resolve()
    found.sort(key=lambda p: (p.resolve() != canon, str(p).lower()))
    return found


def adopt_store_file(
    app_root: Path, filename: str, kind: str
) -> dict[str, Any]:
    """
    Samlar alla kopior av en datafil in i <appmappen>/data/.

    En tom data/suppliers.json ([]) räknas inte som "vi har data".
    ui/data och andra kopior slås ihop in i data/. En oläsbar fil
    skrivs aldrig över.
    """
    canon = app_root / "data" / filename
    _ensure_dir(canon.parent)
    sources: list[tuple[str, int]] = []
    groups: list[list[dict]] = []
    unreadable: list[str] = []
    for path in discover_json_copies(app_root, filename):
        data, status = read_json_any(path)
        if status == "parse_error":
            unreadable.append(str(path))
            continue
        if status != "ok":
            continue
        recs = unwrap_records(data, filename)
        if recs:
            try:
                shown = str(path.resolve().relative_to(app_root.resolve()))
            except ValueError:
                shown = str(path)
            sources.append((shown, len(recs)))
            groups.append(recs)
    merged = merge_record_lists(groups, kind)
    wrote = False
    current_data, current_status = read_json_any(canon)
    current = (
        unwrap_records(current_data, filename)
        if current_status == "ok" else []
    )
    if merged and not _same_record_set(current, merged, kind):
        if current_status == "parse_error":
            log.error(
                "DATA_SKYDD: %s är oläsbar — skriver inte över den", canon
            )
        else:
            if _save_json(canon, merged):
                wrote = True
                log.info(
                    "DATA_MERGE: %s %d poster skrevs till %s från %s",
                    filename, len(merged), canon,
                    ", ".join(f"{p} ({n})" for p, n in sources),
                )
    log.info(
        "DATA_LOAD: %s %d poster, kanon=%s, källor=%s%s",
        filename,
        len(merged) if merged else len(current),
        canon,
        ", ".join(f"{p} ({n})" for p, n in sources) or "inga",
        f", oläsbar={unreadable}" if unreadable else "",
    )
    return {
        "file": str(canon),
        "count": len(merged) if merged else len(current),
        "sources": sources,
        "wrote": wrote,
        "unreadable": unreadable,
    }


def _same_record_set(
    left: list[dict], right: list[dict], kind: str
) -> bool:
    if len(left) != len(right):
        return False
    lk = {_record_identity(r, kind) for r in left}
    rk = {_record_identity(r, kind) for r in right}
    return lk == rk and len(lk) == len(left)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """
    Skriver en fil HELT atomärt med fsync:

        mkstemp → write → flush → fsync(fil) → os.replace → fsync(mapp)

    • En läsare ser ALDRIG en halvskriven fil.
    • Innehållet ligger på disk (fsync) INNAN rename — klarar strömavbrott.
    • Katalog-fsync görs best-effort (stöd saknas på Windows).

    Kastar undantag vid fel (anroparen hanterar).
    """
    _ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass  # ej kritiskt (bl.a. Windows)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _save_json(path: Path, data: Any) -> bool:
    """
    Atomisk JSON-skrivning med fsync (mkstemp → fsync → os.replace).

    En läsare ser aldrig en halvskriven fil och innehållet är
    uthålligt på disk innan bytet sker.
    """
    try:
        payload = json.dumps(
            data, indent=4, ensure_ascii=False, default=str
        ).encode("utf-8")
        _atomic_write_bytes(path, payload)
        return True
    except Exception as exc:
        log.error("JSON save error (%s): %s", path, exc)
        return False


def _timestamp_sort_key(record: dict[str, Any]) -> str:
    """
    Sorteringsnyckel: updated_at → created_at → "".

    Synkad med ui/core/calculator.py, ui/core/search.py och
    ui/core/storage.py (MUST-023: senast ändrad sist).
    """
    return str(record.get("updated_at") or record.get("created_at") or "")


def _sort_newest_last(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sorterar äldst → nyast. Senast ändrad post hamnar ALLTID sist."""
    return sorted(records, key=_timestamp_sort_key)


def _to_float(value: Any, default: float = 0.0) -> float:
    """Säker float-konvertering."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ═════════════════════════════════════════════════════════════════════
#  AUTOSTART MANAGER  (multi-OS — MASTER för all autostart)
# ═════════════════════════════════════════════════════════════════════


class AutostartManager:
    """
    Hanterar OS-nivå autostart på Windows, macOS och Linux.

    METODER (settings "autostart_method", väljs i Inställningar-menyn)
    ─────────────────────────────────────────────────────────────────
    auto      → direct (standard). OS-posten startar Python direkt.
                INGEN VBS, ingen startfil. main.py gör själv
                os.chdir(BASE_DIR) vid start, så arbetsmappen är
                alltid appmappen även från registret/System32 —
                VBS-tricket behövs inte längre.
    direct    → samma som auto.
    launcher  → klassiska startfilen i appmappen
                (autostart/start_hidden.vbs på Windows, .sh annars)
                som dessutom väntar upp till 90 s på att disken
                (t.ex. E:) ska bli redo. För portabla USB-installationer.

    Båda metoderna startar gömt (--minimized → pythonw på Windows).

    Windows : HKCU Run-nyckel (direct: pythonw main.pyw;
              launcher: wscript → start_hidden.vbs)
    Linux   : ~/.config/autostart/Fakturabunten.desktop (Path=)
    macOS   : ~/Library/LaunchAgents/com.fakturabunten.plist
              (WorkingDirectory)
    """

    #: Giltiga autostart-metoder.
    METHODS: tuple[str, ...] = ("auto", "direct", "launcher")

    _app_name: str = APP_NAME
    _WIN_RUN_KEY: str = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _WAIT_SECONDS: int = 90

    def __init__(self, method: str = "auto") -> None:
        self.method: str = self.normalize_method(method)
        self._python_exe, self._main_py = self._detect_paths()
        log.debug(
            "AutostartManager: python=%s  main=%s  cwd=%s",
            self._python_exe,
            self._main_py,
            BASE_DIR,
        )

    # ── Sökvägar ─────────────────────────────────────────────────────────

    @staticmethod
    def _detect_paths() -> tuple[str, str]:
        """(python_executable, main_py). Windows föredrar pythonw + main.pyw."""
        main_pyw = BASE_DIR / "main.pyw"
        main_py = str(BASE_DIR / "main.py")
        if getattr(sys, "frozen", False):
            return str(sys.executable), ""
        script = str(main_pyw) if main_pyw.exists() else main_py
        # Lokal python\ används om den finns. Annars system-Python
        # som Installera senaste Python.bat lagt på datorn.
        local = BASE_DIR / "python"
        if CURRENT_PLATFORM == "windows":
            for name in ("pythonw.exe", "python.exe"):
                candidate = local / name
                if candidate.is_file():
                    return str(candidate), script
            pythonw = Path(sys.executable).parent / "pythonw.exe"
            if pythonw.is_file():
                return str(pythonw), script
            return str(sys.executable), script
        for name in ("python", "python3"):
            candidate = local / "bin" / name
            if candidate.is_file():
                return str(candidate), main_py
        return str(sys.executable), main_py

    def working_directory(self) -> Path:
        """Autostart får aldrig lämna appen i en annan mapp."""
        return BASE_DIR.resolve()

    def _launcher_path(self) -> Path:
        folder = BASE_DIR / "autostart"
        if CURRENT_PLATFORM == "windows":
            return folder / "start_hidden.vbs"
        return folder / "start_hidden.sh"

    @staticmethod
    def _wscript_exe() -> str:
        windir = os.environ.get("SystemRoot", r"C:\Windows")
        return str(Path(windir) / "System32" / "wscript.exe")

    def _app_command(self) -> str:
        """Kommandot som faktiskt startar appen, alltid med --minimized."""
        if self._main_py:
            return f'"{self._python_exe}" "{self._main_py}" --minimized'
        return f'"{self._python_exe}" --minimized'

    def starts_minimized(self) -> bool:
        return "--minimized" in self._app_command()

    def pins_working_directory(self) -> bool:
        return True

    @staticmethod
    def normalize_method(method: str) -> str:
        """Okänd metod → 'auto'."""
        m = str(method or "auto").strip().lower()
        return m if m in AutostartManager.METHODS else "auto"

    def resolved_method(self) -> str:
        """Effektiv metod: 'auto' betyder 'direct' på alla plattformar."""
        return "launcher" if self.method == "launcher" else "direct"

    def build_command(self) -> str:
        """
        Kommandot som skrivs till OS.

        direct   → Python direkt (ingen VBS/startfil).
        launcher → startfilen i appmappen (VBS/.sh).
        Skriver inga filer (det gör set_enabled / verify).
        """
        if self.resolved_method() == "direct":
            return self._app_command()
        launcher = self._launcher_path()
        if CURRENT_PLATFORM == "windows":
            return f'"{self._wscript_exe()}" //nologo //B "{launcher}"'
        return f'/bin/sh "{launcher}"'

    def _build_command(self) -> str:
        return self.build_command()

    def get_command(self) -> str:
        return self.build_command()

    def plan(self) -> dict[str, Any]:
        resolved = self.resolved_method()
        return {
            "platform": CURRENT_PLATFORM,
            "method": self.method,
            "resolved_method": resolved,
            "uses_launcher": resolved == "launcher",
            "working_directory": str(self.working_directory()),
            "app_command": self._app_command(),
            "os_command": self.build_command(),
            "launcher": (
                str(self._launcher_path())
                if resolved == "launcher" else ""
            ),
            "starts_minimized": self.starts_minimized(),
            "waits_for_drive_seconds": (
                self._WAIT_SECONDS if resolved == "launcher" else 0
            ),
        }

    def user_message(self, enabled: bool) -> str:
        if not enabled:
            return (
                "Autostart är av.\n"
                "Programmet startar inte längre vid inloggning."
            )
        p = self.plan()
        if p["resolved_method"] == "direct":
            return (
                "Autostart är på (direktstart, utan VBS).\n\n"
                "Vid inloggning:\n"
                "• OS startar Python direkt — ingen startfil behövs\n"
                "• startar gömd i systemfältet, utan konsolfönster\n"
                "• arbetsmapp = appmappen, aldrig System32\n\n"
                f"Arbetsmapp: {p['working_directory']}\n"
                f"Kommando: {p['os_command']}"
            )
        return (
            "Autostart är på.\n\n"
            "Vid inloggning:\n"
            "• väntar upp till 90 sekunder om disken inte är redo "
            "(t.ex. om E: inte hunnit monteras)\n"
            "• startar gömd i systemfältet, utan konsolfönster\n"
            "• arbetsmapp = appmappen, aldrig System32\n\n"
            f"Arbetsmapp: {p['working_directory']}\n"
            f"Startfil: {p['launcher']}"
        )

    # ── Startfil i appmappen ─────────────────────────────────────────────

    def _write_launcher(self) -> Path:
        """Skriver startfilen. Alltid inuti appmappen."""
        path = self._launcher_path()
        _ensure_dir(path.parent)
        _ensure_dir(BASE_DIR / "logs")
        if CURRENT_PLATFORM == "windows":
            path.write_text(self._vbs_text(), encoding="utf-16")
        else:
            path.write_text(self._sh_text(), encoding="utf-8")
            try:
                os.chmod(path, 0o755)
            except OSError:
                pass
        note = path.parent / "LAS_MIG.txt"
        note.write_text(
            "Startfil för autostart. Skapas av programmet.\n"
            "OS-posten pekar bara hit. Logg: logs/autostart.log\n"
            "Exporter och data skrivs aldrig här.\n"
            "Startfilen hittar appmappen själv (ingen fast sökväg).\n"
            "Saknas Python: kör Installera senaste Python.bat.\n",
            encoding="utf-8",
        )
        log.info("AUTOSTART_LAUNCHER: %s", path)
        return path

    def _launcher_is_current(self) -> bool:
        path = self._launcher_path()
        if not path.exists():
            return False
        try:
            if path.suffix.lower() == ".vbs":
                text = path.read_text(encoding="utf-16")
            else:
                text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        # Startfilen får inte innehålla en fast enhetsbeteckning.
        # Den hittar mappen själv (PORTABEL) så USB-bokstaven kan bytas.
        return (
            "PORTABEL" in text
            and "--minimized" in text
            and (
                "ScriptFullName" in text
                or "dirname" in text
            )
        )

    @staticmethod
    def _sh_quote(value: str) -> str:
        return "'" + value.replace("'", "'\"'\"'") + "'"

    def _sh_text(self) -> str:
        wait = self._WAIT_SECONDS // 2
        # PORTABEL: mappen är alltid föräldern till den här filen.
        return (
            "#!/bin/sh\n"
            "# Fakturabunten — gömd autostart. PORTABEL.\n"
            "HERE=$(CDPATH= cd -- \"$(dirname \"$0\")\" && pwd)\n"
            "APP_DIR=$(CDPATH= cd -- \"$HERE/..\" && pwd)\n"
            "LOG=\"$APP_DIR/logs/autostart.log\"\n"
            "i=0\n"
            f"while [ \"$i\" -lt {wait} ]; do\n"
            "  if [ -d \"$APP_DIR\" ] && [ -f \"$APP_DIR/main.py\" ]; then\n"
            "    break\n"
            "  fi\n"
            "  i=$((i + 1))\n"
            "  sleep 2\n"
            "done\n"
            "if [ ! -f \"$APP_DIR/main.py\" ]; then\n"
            "  mkdir -p \"$(dirname \"$LOG\")\" 2>/dev/null\n"
            "  echo \"$(date '+%Y-%m-%d %H:%M:%S')  FAIL appmappen inte redo: $APP_DIR\" >> \"$LOG\" 2>/dev/null\n"
            "  exit 1\n"
            "fi\n"
            "cd \"$APP_DIR\" || exit 1\n"
            "mkdir -p \"$APP_DIR/logs\"\n"
            "PY=\"\"\n"
            "if [ -x \"$APP_DIR/python/bin/python3\" ]; then\n"
            "  PY=\"$APP_DIR/python/bin/python3\"\n"
            "elif [ -x \"$APP_DIR/python/bin/python\" ]; then\n"
            "  PY=\"$APP_DIR/python/bin/python\"\n"
            "elif command -v python3 >/dev/null 2>&1; then\n"
            "  PY=python3\n"
            "else\n"
            "  PY=python\n"
            "fi\n"
            "echo \"$(date '+%Y-%m-%d %H:%M:%S')  OK cwd=$APP_DIR --minimized\" >> \"$LOG\"\n"
            "exec \"$PY\" \"$APP_DIR/main.py\" --minimized\n"
        )

    def _vbs_text(self) -> str:
        """VBS utan fast enhetsbeteckning. Hittar mappen via scriptet."""
        loops = self._WAIT_SECONDS // 2
        return (
            "' Fakturabunten — gömd autostart. PORTABEL.\n"
            "Option Explicit\n"
            "Dim fso, sh, appDir, autoDir, pythonw, script, logFile, i, ready, cmd, q\n"
            "Dim localW, pyRoot, folder, name, candidate, ver, bestVer\n"
            "Set fso = CreateObject(\"Scripting.FileSystemObject\")\n"
            "Set sh = CreateObject(\"WScript.Shell\")\n"
            "autoDir = fso.GetParentFolderName(WScript.ScriptFullName)\n"
            "appDir = fso.GetParentFolderName(autoDir)\n"
            "logFile = appDir & \"\\logs\\autostart.log\"\n"
            "q = Chr(34)\n"
            "\n"
            "Sub WriteLog(msg)\n"
            "    On Error Resume Next\n"
            "    Dim ts, folder\n"
            "    folder = fso.GetParentFolderName(logFile)\n"
            "    If Not fso.FolderExists(folder) Then\n"
            "        If fso.FolderExists(appDir) Then fso.CreateFolder folder\n"
            "    End If\n"
            "    If fso.FolderExists(folder) Then\n"
            "        Set ts = fso.OpenTextFile(logFile, 8, True)\n"
            "        ts.WriteLine Year(Now) & \"-\" & Right(\"0\" & Month(Now), 2) & \"-\" & Right(\"0\" & Day(Now), 2) & \" \" & Right(\"0\" & Hour(Now), 2) & \":\" & Right(\"0\" & Minute(Now), 2) & \":\" & Right(\"0\" & Second(Now), 2) & \"  \" & msg\n"
            "        ts.Close\n"
            "    End If\n"
            "End Sub\n"
            "\n"
            "ready = False\n"
            f"For i = 1 To {loops}\n"
            "    If fso.FolderExists(appDir) Then\n"
            "        If fso.FileExists(appDir & \"\\main.py\") Or fso.FileExists(appDir & \"\\main.pyw\") Then\n"
            "            ready = True\n"
            "            Exit For\n"
            "        End If\n"
            "    End If\n"
            "    WScript.Sleep 2000\n"
            "Next\n"
            "\n"
            "If Not ready Then\n"
            "    WriteLog \"FAIL: appmappen inte redo efter 90s: \" & appDir\n"
            "    WScript.Quit 1\n"
            "End If\n"
            "\n"
            "script = appDir & \"\\main.pyw\"\n"
            "If Not fso.FileExists(script) Then script = appDir & \"\\main.py\"\n"
            "pythonw = \"\"\n"
            "localW = appDir & \"\\python\\pythonw.exe\"\n"
            "If fso.FileExists(localW) Then pythonw = localW\n"
            "If pythonw = \"\" Then\n"
            "    bestVer = 0\n"
            "    pyRoot = sh.ExpandEnvironmentStrings(\"%LocalAppData%\") & \"\\Programs\\Python\"\n"
            "    If fso.FolderExists(pyRoot) Then\n"
            "        For Each folder In fso.GetFolder(pyRoot).SubFolders\n"
            "            candidate = folder.Path & \"\\pythonw.exe\"\n"
            "            If fso.FileExists(candidate) Then\n"
            "                ver = 0\n"
            "                On Error Resume Next\n"
            "                ver = CLng(Replace(folder.Name, \"Python\", \"\"))\n"
            "                On Error GoTo 0\n"
            "                If ver > bestVer Then\n"
            "                    bestVer = ver\n"
            "                    pythonw = candidate\n"
            "                End If\n"
            "            End If\n"
            "        Next\n"
            "    End If\n"
            "End If\n"
            "\n"
            "sh.CurrentDirectory = appDir\n"
            "If pythonw = \"\" Then\n"
            "    WriteLog \"FAIL: Python saknas på datorn. Kör Installera senaste Python.bat\"\n"
            "    WScript.Quit 1\n"
            "End If\n"
            "\n"
            "cmd = q & pythonw & q & \" \" & q & script & q & \" --minimized\"\n"
            "sh.Run cmd, 0, False\n"
            "WriteLog \"OK cwd=\" & appDir & \" cmd=\" & cmd\n"
        )

    # ── Läs OS-status ────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        try:
            if CURRENT_PLATFORM == "windows":
                return self._win_check()
            if CURRENT_PLATFORM == "linux":
                return self._linux_path().exists()
            if CURRENT_PLATFORM == "macos":
                return self._macos_path().exists()
        except Exception as exc:
            log.warning("AutostartManager.is_enabled: %s", exc)
        return False

    def get_registered_command(self) -> str:
        if CURRENT_PLATFORM != "windows":
            return ""
        try:
            import winreg

            key = None
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    self._WIN_RUN_KEY,
                    0,
                    winreg.KEY_READ,
                )
                val, _ = winreg.QueryValueEx(key, self._app_name)
                return str(val)
            finally:
                if key is not None:
                    winreg.CloseKey(key)
        except Exception:
            return ""

    # ── Ändra OS-status ──────────────────────────────────────────────────

    def legacy_is_enabled(self) -> bool:
        """True om en gammal autostart-post från förra namnet finns."""
        if CURRENT_PLATFORM == "windows":
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, self._WIN_RUN_KEY, 0,
                    winreg.KEY_READ,
                )
                try:
                    for old in (
                        "FakturaBetalaren Pro",
                        "FakturaBetalarenPro",
                        "FakturaRäknaren",
                        "FakturaRaknaren",
                    ):
                        try:
                            val, _ = winreg.QueryValueEx(key, old)
                            if val:
                                return True
                        except FileNotFoundError:
                            pass
                finally:
                    winreg.CloseKey(key)
            except Exception:
                return False
        old_desk = Path.home() / ".config" / "autostart" / "FakturaBetalaren.desktop"
        old_plist = (
            Path.home() / "Library" / "LaunchAgents"
            / "com.fakturabetalarenpro.plist"
        )
        return old_desk.exists() or old_plist.exists()

    def migrate_legacy_if_present(self) -> None:
        """Flyttar gammal autostart till Fakturabunten, tar bort dubletten."""
        if self.legacy_is_enabled() and not self.is_enabled():
            log.info("AUTOSTART: flyttar gammal post till %s", self._app_name)
            self.set_enabled(True)
        else:
            self._retire_legacy_autostart()

    def _retire_legacy_autostart(self) -> None:
        """Tar bort gamla poster från namnet FakturaBetalaren Pro."""
        if CURRENT_PLATFORM == "windows":
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    self._WIN_RUN_KEY,
                    0,
                    winreg.KEY_SET_VALUE,
                )
                try:
                    for old in ("FakturaBetalaren Pro", "FakturaBetalarenPro"):
                        if old == self._app_name:
                            continue
                        try:
                            winreg.DeleteValue(key, old)
                            log.info("AUTOSTART: gammal registerpost borttagen: %s", old)
                        except FileNotFoundError:
                            pass
                finally:
                    winreg.CloseKey(key)
            except Exception as exc:
                log.debug("AUTOSTART legacy windows: %s", exc)
        for old in (
            Path.home() / ".config" / "autostart" / "FakturaBetalaren.desktop",
            Path.home() / ".config" / "autostart" / "FakturaBetalarenPro.desktop",
            Path.home() / ".config" / "autostart" / "FakturaRaknaren.desktop",
        ):
            try:
                if old.exists() and old != self._linux_path():
                    old.unlink()
                    log.info("AUTOSTART: gammal .desktop borttagen: %s", old)
            except OSError:
                pass
        for old_plist in (
            Path.home() / "Library" / "LaunchAgents" / "com.fakturabetalarenpro.plist",
            Path.home() / "Library" / "LaunchAgents" / "com.fakturaraknaren.plist",
        ):
            try:
                if old_plist.exists() and old_plist != self._macos_path():
                    self._launchctl("unload", old_plist)
                    old_plist.unlink()
                    log.info("AUTOSTART: gammal plist borttagen")
            except OSError:
                pass

    def set_enabled(self, enable: bool) -> bool:
        try:
            self._retire_legacy_autostart()
            if enable and self.resolved_method() == "launcher":
                self._write_launcher()
            if CURRENT_PLATFORM == "windows":
                ok = self._win_set(enable)
            elif CURRENT_PLATFORM == "linux":
                ok = self._linux_set(enable)
            elif CURRENT_PLATFORM == "macos":
                ok = self._macos_set(enable)
            else:
                log.warning(
                    "AutostartManager: okänd plattform %s",
                    CURRENT_PLATFORM,
                )
                return False
            if ok:
                log.info(
                    "AUTOSTART: %s (%s) cwd=%s launcher=%s os=%s",
                    "på" if enable else "av",
                    CURRENT_PLATFORM,
                    self.working_directory(),
                    self._launcher_path(),
                    self.build_command() if enable else "–",
                )
            return ok
        except Exception as exc:
            log.error("AutostartManager.set_enabled: %s", exc)
            return False

    def enable(self) -> bool:
        return self.set_enabled(True)

    def disable(self) -> bool:
        return self.set_enabled(False)

    def toggle(self) -> bool:
        new_state = not self.is_enabled()
        self.set_enabled(new_state)
        return new_state

    def verify_and_update(self) -> bool:
        """
        Om OS-posten eller startfilen är gammal (t.ex. pythonw direkt,
        utan arbetsmapp) skrivs den om till startfilen i appmappen.
        """
        self._retire_legacy_autostart()
        if not self.is_enabled():
            return False
        if not self._launcher_is_current():
            log.info("AUTOSTART: startfil saknas eller är gammal → skriver om")
            self._write_launcher()

        if CURRENT_PLATFORM == "windows":
            expected = self.build_command()
            current = self.get_registered_command()
            if current != expected:
                log.info(
                    "AUTOSTART: register pekar fel\n  Nuvarande: %s\n  Korrekt  : %s",
                    current,
                    expected,
                )
                return self._win_set(True)
            log.debug("AUTOSTART: register OK %s", expected)

        if CURRENT_PLATFORM == "linux":
            p = self._linux_path()
            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                content = ""
            expected_exec = f"Exec={self.build_command()}"
            expected_path = f"Path={BASE_DIR}"
            if expected_exec not in content or expected_path not in content:
                log.info("AUTOSTART: .desktop föråldrad → uppdaterar")
                return self._linux_set(True)

        if CURRENT_PLATFORM == "macos":
            p = self._macos_path()
            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                content = ""
            if (
                "<string>--minimized</string>" not in content
                and "--minimized" not in content
            ) or f"<string>{BASE_DIR}</string>" not in content:
                log.info("AUTOSTART: plist föråldrad → uppdaterar")
                return self._macos_set(True)
        return True

    # ── Windows ──────────────────────────────────────────────────────────

    def _win_check(self) -> bool:
        try:
            import winreg

            key = None
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    self._WIN_RUN_KEY,
                    0,
                    winreg.KEY_READ,
                )
                val, _ = winreg.QueryValueEx(key, self._app_name)
                return bool(val)
            finally:
                if key is not None:
                    winreg.CloseKey(key)
        except Exception:
            return False

    def _win_set(self, enable: bool) -> bool:
        try:
            import winreg

            key = None
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    self._WIN_RUN_KEY,
                    0,
                    winreg.KEY_SET_VALUE,
                )
                if enable:
                    cmd = self.build_command()
                    winreg.SetValueEx(
                        key, self._app_name, 0, winreg.REG_SZ, cmd
                    )
                    log.info(
                        "Windows registry SET:\n  Nyckel: %s\n  Värde : %s",
                        self._app_name,
                        cmd,
                    )
                else:
                    try:
                        winreg.DeleteValue(key, self._app_name)
                        log.info("Windows registry DELETE: %s", self._app_name)
                    except FileNotFoundError:
                        log.debug("Registry DELETE: nyckel fanns inte")
                return True
            finally:
                if key is not None:
                    winreg.CloseKey(key)
        except PermissionError as exc:
            log.error("_win_set: Åtkomst nekad: %s", exc)
            return False
        except Exception as exc:
            log.error("_win_set: %s", exc)
            return False

    # ── Linux ────────────────────────────────────────────────────────────

    @staticmethod
    def _linux_path() -> Path:
        return (
            Path.home() / ".config" / "autostart"
            / "Fakturabunten.desktop"
        )

    def _linux_set(self, enable: bool) -> bool:
        p = self._linux_path()
        if enable:
            if self.resolved_method() == "launcher":
                self._write_launcher()
            _ensure_dir(p.parent)
            icon = BASE_DIR / "app_icon.png"
            icon_line = f"Icon={icon}\n" if icon.exists() else ""
            p.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Version=1.0\n"
                f"Name={self._app_name}\n"
                f"Exec={self.build_command()}\n"
                f"Path={BASE_DIR}\n"
                f"{icon_line}"
                "Terminal=false\n"
                "StartupNotify=false\n"
                "X-GNOME-Autostart-enabled=true\n"
                "X-GNOME-Autostart-Delay=8\n"
                "X-KDE-Autostart=true\n"
                "Hidden=false\n"
                f"Comment={self._app_name} startar gömd från appmappen\n",
                encoding="utf-8",
            )
            try:
                os.chmod(p, 0o755)
            except OSError:
                pass
        else:
            p.unlink(missing_ok=True)
        return True

    # ── macOS ────────────────────────────────────────────────────────────

    @staticmethod
    def _macos_path() -> Path:
        return (
            Path.home() / "Library" / "LaunchAgents"
            / "com.fakturabunten.plist"
        )

    def _macos_set(self, enable: bool) -> bool:
        p = self._macos_path()
        if enable:
            if self.resolved_method() == "launcher":
                self._write_launcher()
            _ensure_dir(p.parent)
            launcher = self._launcher_path()
            p.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
                '  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0">\n'
                "<dict>\n"
                "  <key>Label</key>\n"
                "  <string>com.fakturabunten</string>\n"
                "  <key>ProgramArguments</key>\n"
                "  <array>\n"
                + (
                    "    <string>/bin/sh</string>\n"
                    f"    <string>{launcher}</string>\n"
                    if self.resolved_method() == "launcher"
                    else f"    <string>{self._python_exe}</string>\n"
                    + (
                        f"    <string>{self._main_py}</string>\n"
                        if self._main_py else ""
                    )
                    + "    <string>--minimized</string>\n"
                )
                + "  </array>\n"
                "  <key>WorkingDirectory</key>\n"
                f"  <string>{BASE_DIR}</string>\n"
                "  <key>RunAtLoad</key>\n"
                "  <true/>\n"
                "  <key>KeepAlive</key>\n"
                "  <false/>\n"
                "  <key>LimitLoadToSessionType</key>\n"
                "  <string>Aqua</string>\n"
                "  <key>StandardOutPath</key>\n"
                f"  <string>{BASE_DIR / 'logs' / 'autostart.log'}</string>\n"
                "  <key>StandardErrorPath</key>\n"
                f"  <string>{BASE_DIR / 'logs' / 'autostart.log'}</string>\n"
                "</dict>\n"
                "</plist>\n",
                encoding="utf-8",
            )
            self._launchctl("load", p)
        else:
            self._launchctl("unload", p)
            p.unlink(missing_ok=True)
        return True

    @staticmethod
    def _launchctl(action: str, plist: Path) -> None:
        try:
            subprocess.Popen(
                ["launchctl", action, str(plist)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            log.debug("launchctl %s: %s", action, exc)

    def status(self) -> dict[str, Any]:
        info = self.plan()
        info["enabled"] = self.is_enabled()
        info["registered_command"] = self.get_registered_command()
        info["target"] = (
            "HKCU\\" + self._WIN_RUN_KEY
            if CURRENT_PLATFORM == "windows"
            else str(
                self._linux_path()
                if CURRENT_PLATFORM == "linux"
                else self._macos_path()
            )
        )
        return info

# ═════════════════════════════════════════════════════════════════════
#  SETTINGS MANAGER
# ═════════════════════════════════════════════════════════════════════


class SettingsManager:
    """
    Hanterar appinställningar i settings.json (trådsäker).

    AUTOSTART-SYNK VID START (load):
        • startup=True  + OS saknas   → registrera med OS
        • startup=True  + OS felaktig → uppdatera registret
        • startup=False + OS finns    → synka settings till True
        • startup=False + OS saknas   → inget

    set("startup", True/False) synkar ALLTID direkt med OS.
    autostart-property läser FAKTISK OS-status.
    """

    def __init__(self, path: Path = SETTINGS_FILE) -> None:
        self._path: Path = path
        self._data: dict[str, Any] = {}
        self._callbacks: list[Callable] = []
        self._lock = threading.RLock()
        self._autostart = AutostartManager()
        self.load()
        self._sync_autostart_method()

    def _sync_autostart_method(self) -> None:
        """Håller AutostartManager.method = settings autostart_method."""
        try:
            self._autostart.method = AutostartManager.normalize_method(
                str(self.get("autostart_method", "auto"))
            )
        except Exception:
            pass

    # ── Läs / spara ──────────────────────────────────────────────────────

    def _read_raw(self) -> dict[str, Any]:
        """
        Läser settings.json rå.

        Korrupt JSON (trasig/halvskriven fil) → filen namnbyts till
        settings.json.corrupt-<timestamp> så att inget går förlorat,
        och appen startar vidare med standardvärden.
        """
        if not self._path.exists():
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            corrupt = self._path.with_name(
                self._path.name + f".corrupt-{stamp}"
            )
            try:
                self._path.rename(corrupt)
                log.error(
                    "SETTINGS_CORRUPT: %s är trasig (%s) → sparad som "
                    "%s, startar med standardvärden",
                    self._path.name, exc, corrupt.name,
                )
            except OSError:
                log.error(
                    "SETTINGS_CORRUPT: %s är trasig (%s) och kunde "
                    "inte namnbytas", self._path.name, exc,
                )
            return {}

    def load(self) -> None:
        """
        Laddar settings med schema-validering + auto-reparation och
        synkar autostart-status mot OS.
        """
        with self._lock:
            raw = self._read_raw()
            clean, repairs = validate_settings(raw)
            self._data = clean
            if repairs:
                _save_json(self._path, self._data)

        if repairs:
            log.warning(
                "SETTINGS_REPAIR: %d värde(n) reparerade — %s",
                len(repairs), "; ".join(repairs),
            )

        # Gammal registerpost (FakturaBetalaren Pro) flyttas till det nya namnet
        # så autostart inte startar två gånger.
        try:
            self._autostart.migrate_legacy_if_present()
        except Exception as exc:
            log.debug("AUTOSTART migrate: %s", exc)

        startup_in_settings = bool(self._data.get("startup", False))
        startup_in_os = self._autostart.is_enabled()

        if startup_in_settings:
            if not startup_in_os:
                log.info(
                    "Autostart: settings=True, OS-post saknas "
                    "→ registrerar nu"
                )
                self._autostart.set_enabled(True)
            else:
                self._autostart.verify_and_update()
        elif startup_in_os:
            log.info(
                "Autostart: OS-post finns men settings=False "
                "→ synkar settings till True"
            )
            with self._lock:
                self._data["startup"] = True

    def save(self) -> None:
        """Sparar till disk och notifierar callbacks."""
        with self._lock:
            _save_json(self._path, self._data)
        self._notify()

    # ── CRUD ─────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            old = self._data.get(key)
            self._data[key] = value
        if key == "startup" and value != old:
            if not self._autostart.set_enabled(bool(value)):
                log.warning(
                    "AutostartManager.set_enabled(%s) misslyckades", value
                )
        self.save()

    def update(self, mapping: dict[str, Any]) -> None:
        startup_changed: bool | None = None
        with self._lock:
            for k, v in mapping.items():
                old = self._data.get(k)
                self._data[k] = v
                if k == "startup" and v != old:
                    startup_changed = bool(v)
        if startup_changed is not None:
            self._autostart.set_enabled(startup_changed)
        self.save()

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def reset(self) -> None:
        with self._lock:
            self._data = DEFAULT_SETTINGS.copy()
        self.save()

    # ── Callbacks ────────────────────────────────────────────────────────

    def on_change(self, callback: Callable) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def _notify(self) -> None:
        snapshot = self.all()
        for cb in self._callbacks:
            try:
                cb(snapshot)
            except Exception as exc:
                log.warning("Settings callback error: %s", exc)

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def theme(self) -> str:
        t = self._data.get("theme", "dark")
        return t if t in VALID_THEMES else "dark"

    @theme.setter
    def theme(self, value: str) -> None:
        self.set("theme", value if value in VALID_THEMES else "dark")

    @property
    def autostart(self) -> bool:
        """Returnerar FAKTISK OS-status (inte bara settings-värdet)."""
        return self._autostart.is_enabled()

    @autostart.setter
    def autostart(self, value: bool) -> None:
        self.set("startup", value)

    @property
    def start_minimized(self) -> bool:
        return bool(self._data.get("start_minimized", True))

    @property
    def close_to_tray(self) -> bool:
        return bool(self._data.get("close_to_tray", True))

    def get_autostart_manager(self) -> AutostartManager:
        self._sync_autostart_method()
        return self._autostart


# ═════════════════════════════════════════════════════════════════════
#  CHANGE LOG
# ═════════════════════════════════════════════════════════════════════


class ChangeLog:
    """Append-only ändringslogg lagrad i changelog.json."""

    def __init__(self, path: Path) -> None:
        self._path = path
        _ensure_dir(path.parent)

    def record(
        self,
        action: str,
        entity: str,
        entity_id: str,
        details: dict | None = None,
    ) -> None:
        entry = {
            "timestamp": _now_iso(),
            "action":    action,
            "entity":    entity,
            "id":        entity_id,
            "details":   details or {},
            "platform":  CURRENT_PLATFORM,
        }
        existing = _load_json(self._path, [])
        if not isinstance(existing, list):
            existing = []
        existing.append(entry)
        _save_json(self._path, existing)

    def all(self) -> list[dict]:
        result = _load_json(self._path, [])
        return result if isinstance(result, list) else []

    def recent(self, n: int = 50) -> list[dict]:
        return self.all()[-n:]

    def clear(self) -> None:
        _save_json(self._path, [])


# ═════════════════════════════════════════════════════════════════════
#  JSON DATA STORE
# ═════════════════════════════════════════════════════════════════════


class DataStore:
    """
    Generisk JSON-lagrad CRUD-store.

    • UUID-identitet — aldrig index-baserat CRUD.
    • Atomisk skrivning (.tmp → rename).
    • Change-loggning av alla mutationer.
    • on_change-callbacks för vyer/plugins.
    • Senast ändrad post sist i all()/search()/filter_by() (MUST-023).
    • Trådsäker via RLock.
    """

    def __init__(
        self,
        name: str,
        db_path: Path,
        schema: dict[str, Any],
        changelog: ChangeLog,
    ) -> None:
        self._name = name
        self._file = db_path / f"{name}.json"
        self._schema = schema
        self._log = changelog
        self._records: list[dict] = []
        self._callbacks: list[Callable] = []
        self._lock = threading.RLock()
        #: False om filen inte gick att läsa — då får _save inte tömma den.
        self._load_ok: bool = True
        self._load()

    @property
    def file(self) -> Path:
        """JSON-filen den här storen läser och skriver."""
        return self._file

    # ── Persistens ───────────────────────────────────────────────────────

    def _load(self) -> None:
        data, status = read_json_any(self._file)
        if status == "parse_error":
            self._load_ok = False
            log.error(
                "DataStore[%s] behåller minnet — %s kunde inte läsas",
                self._name, self._file,
            )
            return
        records = unwrap_records(data, self._file.name) if status == "ok" else []
        with self._lock:
            self._records = records
            self._load_ok = True
            count = len(self._records)
        log.info(
            "DataStore[%s] laddade %d poster från %s",
            self._name, count, self._file,
        )

    def _save(self) -> None:
        if not self._load_ok and not self._records:
            log.error(
                "DATA_SKYDD: skriver inte tom lista över oläsbar fil %s",
                self._file,
            )
            return
        with self._lock:
            _save_json(self._file, self._records)
        self._load_ok = True
        self._notify()

    def reload(self) -> None:
        """Läser om från disk (t.ex. efter backup-restore)."""
        self._load()
        self._notify()

    # ── Callbacks ────────────────────────────────────────────────────────

    def on_change(self, callback: Callable) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def _notify(self) -> None:
        with self._lock:
            snapshot = list(self._records)
        for cb in self._callbacks:
            try:
                cb(self._name, snapshot)
            except Exception as exc:
                log.warning(
                    "DataStore[%s] callback error: %s", self._name, exc
                )

    # ── CRUD ─────────────────────────────────────────────────────────────

    def add(self, data: dict) -> dict:
        """Lägger till post. UUID + timestamps sätts automatiskt."""
        with self._lock:
            record = dict(self._schema)
            record.update(data)
            if not record.get("id"):
                record["id"] = _new_id()
            record["created_at"] = record.get("created_at") or _now_iso()
            record["updated_at"] = _now_iso()
            self._records.append(record)
        self._save()
        self._log.record("ADD", self._name, record["id"], data)
        return dict(record)

    def update(self, record_id: str, data: dict) -> dict | None:
        """Uppdaterar post. updated_at sätts automatiskt."""
        with self._lock:
            for record in self._records:
                if record.get("id") == record_id:
                    record.update(data)
                    record["id"] = record_id
                    record["updated_at"] = _now_iso()
                    result = dict(record)
                    break
            else:
                result = None
        if result is None:
            log.warning(
                "DataStore[%s] UPDATE — ej funnen: %s",
                self._name,
                record_id,
            )
            return None
        self._save()
        self._log.record("UPDATE", self._name, record_id, data)
        return result

    def delete(self, record_id: str) -> bool:
        """Tar bort post. Returnerar True om något togs bort."""
        with self._lock:
            before = len(self._records)
            self._records = [
                r for r in self._records if r.get("id") != record_id
            ]
            deleted = len(self._records) < before
        if deleted:
            self._save()
            self._log.record("DELETE", self._name, record_id)
            return True
        log.warning(
            "DataStore[%s] DELETE — ej funnen: %s", self._name, record_id
        )
        return False

    def bulk_add(self, items: list[dict]) -> list[dict]:
        """Lägger till flera poster i EN skrivning."""
        now = _now_iso()
        added: list[dict] = []
        with self._lock:
            for data in items:
                record = dict(self._schema)
                record.update(data)
                if not record.get("id"):
                    record["id"] = _new_id()
                record["created_at"] = record.get("created_at") or now
                record["updated_at"] = now
                self._records.append(record)
                added.append(dict(record))
        self._save()
        return added

    def clear(self) -> None:
        """Tömmer hela store:n."""
        with self._lock:
            self._records = []
        self._save()
        log.warning("DataStore[%s] TÖMD", self._name)

    # ── Läsning (senast ändrad sist, MUST-023) ───────────────────────────

    def get(self, record_id: str) -> dict | None:
        with self._lock:
            for r in self._records:
                if r.get("id") == record_id:
                    return dict(r)
        return None

    def all(self) -> list[dict]:
        """Alla poster — senast ändrad sist."""
        with self._lock:
            records = [dict(r) for r in self._records]
        return _sort_newest_last(records)

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def is_empty(self) -> bool:
        return self.count() == 0

    def search(
        self, query: str, fields: list[str] | None = None
    ) -> list[dict]:
        """Enkel contains-sökning i valda fält. Senast ändrad sist."""
        q = query.strip().lower()
        fields = fields or list(self._schema.keys())
        if not q:
            return self.all()
        with self._lock:
            matches = [
                dict(r)
                for r in self._records
                if any(q in str(r.get(f, "")).lower() for f in fields)
            ]
        return _sort_newest_last(matches)

    def filter_by(self, **kwargs: Any) -> list[dict]:
        """Exakt matchning på ett eller flera fält. Senast ändrad sist."""
        with self._lock:
            results = list(self._records)
            for key, value in kwargs.items():
                results = [r for r in results if r.get(key) == value]
            matches = [dict(r) for r in results]
        return _sort_newest_last(matches)

    def find_one(
        self, predicate: Callable[[dict], bool]
    ) -> dict | None:
        with self._lock:
            for r in self._records:
                if predicate(r):
                    return dict(r)
        return None

    def find_duplicates(
        self,
        match_fields: list[str],
        candidate: dict,
        exclude_id: str = "",
    ) -> list[dict]:
        """Hittar poster som matchar candidate i alla match_fields."""

        def _eq(a: Any, b: Any) -> bool:
            return str(a).lower().strip() == str(b).lower().strip()

        with self._lock:
            matches = [
                dict(r)
                for r in self._records
                if r.get("id") != exclude_id
                and all(
                    _eq(r.get(f, ""), candidate.get(f, ""))
                    for f in match_fields
                )
            ]
        return _sort_newest_last(matches)

    # ── Export / import / integritet ─────────────────────────────────────

    def checksum(self) -> str:
        """MD5 över innehållet — för ändringsdetektering."""
        with self._lock:
            raw = json.dumps(
                self._records, sort_keys=True, ensure_ascii=False
            )
        return hashlib.md5(raw.encode()).hexdigest()

    def export_json(self) -> str:
        with self._lock:
            return json.dumps(
                self._records, indent=4, ensure_ascii=False, default=str
            )

    def import_json(self, raw: str) -> int:
        """Importerar JSON-lista. Returnerar antal tillagda poster."""
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return len(self.bulk_add(data))
        except Exception as exc:
            log.error("import_json: %s", exc)
        return 0


# ═════════════════════════════════════════════════════════════════════
#  INVOICE ENGINE — affärslogik ovanpå DataStore
# ═════════════════════════════════════════════════════════════════════


class InvoiceEngine:
    """Faktura-affärslogik: typer, filter, summor, status, dubbletter."""

    def __init__(self, store: DataStore) -> None:
        self._store = store

    # ── CRUD ─────────────────────────────────────────────────────────────

    def add(self, data: dict) -> dict:
        data.setdefault("status", "Obetald")
        data.setdefault("invoice_type", "Faktura")
        self._sync_type(data)
        return self._store.add(data)

    def update(self, record_id: str, data: dict) -> dict | None:
        if "total_amount" in data:
            self._sync_type(data)
        return self._store.update(record_id, data)

    def delete(self, record_id: str) -> bool:
        return self._store.delete(record_id)

    def get(self, record_id: str) -> dict | None:
        return self._store.get(record_id)

    def all(self) -> list[dict]:
        return self._store.all()

    def count(self) -> int:
        return self._store.count()

    def search(self, query: str) -> list[dict]:
        return self._store.search(
            query,
            fields=[
                "supplier",
                "invoice_number",
                "ocr",
                "invoice_type",
                "reference",
                "note",
                "category",
                "status",
                "payment_date",
            ],
        )

    # ── Typsynk ──────────────────────────────────────────────────────────

    @staticmethod
    def _sync_type(data: dict) -> None:
        """
        Sätter invoice_type utifrån total_amount och normaliserar beloppet.

        Positivt belopp → "Faktura"
        Negativt belopp → "Kreditfaktura"
        """
        total = _to_float(data.get("total_amount", 0))
        data["total_amount"] = total
        if total < 0:
            data["invoice_type"] = "Kreditfaktura"
        elif total > 0:
            data["invoice_type"] = "Faktura"

    # ── Filter ───────────────────────────────────────────────────────────

    def active(self) -> list[dict]:
        """Alla utom Arkiverad / Makulerad."""
        return [
            r for r in self.all() if r.get("status") not in NON_ACTIVE_STATUSES
        ]

    def archived(self) -> list[dict]:
        return [r for r in self.all() if r.get("status") == "Arkiverad"]

    def unpaid(self) -> list[dict]:
        """Alla utom Betald / Makulerad / Arkiverad."""
        return [
            r for r in self.all() if r.get("status") not in NON_UNPAID_STATUSES
        ]

    def overdue(self) -> list[dict]:
        """Obetalda med passerat förfallodatum (tomt datum = ej förfallen)."""
        today = datetime.date.today().isoformat()
        return [
            r
            for r in self.unpaid()
            if (r.get("due_date") or "") and r["due_date"] < today
        ]

    def due_today(self) -> list[dict]:
        today = datetime.date.today().isoformat()
        return [r for r in self.unpaid() if r.get("due_date") == today]

    def due_this_week(self) -> list[dict]:
        today = datetime.date.today()
        today_s = today.isoformat()
        end = (today + datetime.timedelta(days=7)).isoformat()
        return [
            r
            for r in self.unpaid()
            if today_s <= (r.get("due_date") or "9999") <= end
        ]

    def due_this_month(self) -> list[dict]:
        today = datetime.date.today()
        start = today.replace(day=1).isoformat()
        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1)
        else:
            end = today.replace(month=today.month + 1, day=1)
        end_s = end.isoformat()
        return [
            r
            for r in self.unpaid()
            if start <= (r.get("due_date") or "9999") < end_s
        ]

    def invoices_only(self) -> list[dict]:
        return [r for r in self.all() if _to_float(r.get("total_amount")) >= 0]

    def credits_only(self) -> list[dict]:
        return [r for r in self.all() if _to_float(r.get("total_amount")) < 0]

    def by_status(self, status: str) -> list[dict]:
        return self._store.filter_by(status=status)

    def by_supplier(self, supplier: str) -> list[dict]:
        target = supplier.lower().strip()
        return [
            r
            for r in self.all()
            if r.get("supplier", "").lower().strip() == target
        ]

    # ── Summor (Fakturor + / Krediter − / NETTO) ─────────────────────────

    def total_amount(self, records: list[dict] | None = None) -> float:
        """Summa av alla belopp (fakturor + krediter = NETTO)."""
        data = records if records is not None else self.all()
        return round(sum(_to_float(r.get("total_amount")) for r in data), 2)

    def total_positive(self, records: list[dict] | None = None) -> float:
        """Summa av enbart fakturor (positiva belopp)."""
        data = records if records is not None else self.all()
        return round(
            sum(
                amt
                for amt in (_to_float(r.get("total_amount")) for r in data)
                if amt > 0
            ),
            2,
        )

    def total_negative(self, records: list[dict] | None = None) -> float:
        """Summa av enbart krediter (negativa belopp)."""
        data = records if records is not None else self.all()
        return round(
            sum(
                amt
                for amt in (_to_float(r.get("total_amount")) for r in data)
                if amt < 0
            ),
            2,
        )

    def total_unpaid(self) -> float:
        return self.total_amount(self.unpaid())

    def total_overdue(self) -> float:
        return self.total_amount(self.overdue())

    def att_betala(self) -> float:
        """ATT BETALA = netto av alla AKTIVA fakturor + krediter."""
        return round(self.total_amount(self.active()), 2)

    # ── Sammanställningar ────────────────────────────────────────────────

    def summary_by_supplier(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for r in self.all():
            s = r.get("supplier") or "Okänd"
            amt = _to_float(r.get("total_amount"))
            row = result.setdefault(
                s,
                {"count": 0, "invoices": 0.0, "credits": 0.0,
                 "netto": 0.0, "unpaid": 0.0},
            )
            row["count"] += 1
            if amt >= 0:
                row["invoices"] = round(row["invoices"] + amt, 2)
            else:
                row["credits"] = round(row["credits"] + amt, 2)
            row["netto"] = round(row["invoices"] + row["credits"], 2)
            if r.get("status") not in NON_UNPAID_STATUSES:
                row["unpaid"] = round(row["unpaid"] + amt, 2)
        return result

    def summary_by_month(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for r in self.all():
            month = str(r.get("date", ""))[:7]
            if len(month) < 7:
                month = "Okänd"
            amt = _to_float(r.get("total_amount"))
            row = result.setdefault(
                month,
                {"count": 0, "invoices": 0.0, "credits": 0.0, "netto": 0.0},
            )
            row["count"] += 1
            if amt >= 0:
                row["invoices"] = round(row["invoices"] + amt, 2)
            else:
                row["credits"] = round(row["credits"] + amt, 2)
            row["netto"] = round(row["invoices"] + row["credits"], 2)
        return dict(sorted(result.items()))

    def count_by_status(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for r in self.all():
            s = r.get("status", "Okänd")
            result[s] = result.get(s, 0) + 1
        return result

    def count_by_type(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for r in self.all():
            t = r.get("invoice_type") or "Faktura"
            result[t] = result.get(t, 0) + 1
        return result

    # ── Dubblettkontroller ───────────────────────────────────────────────

    def check_duplicate_number(
        self,
        invoice_number: str,
        supplier: str,
        exclude_id: str = "",
    ) -> list[dict]:
        """Samma fakturanummer + leverantör = möjlig dubblett."""
        return self._store.find_duplicates(
            ["invoice_number", "supplier"],
            {"invoice_number": invoice_number, "supplier": supplier},
            exclude_id=exclude_id,
        )

    def check_duplicate_amount(
        self,
        supplier: str,
        total_amount: float,
        exclude_id: str = "",
    ) -> list[dict]:
        """
        Samma belopp + samma leverantör = möjlig dubblett.

        Jämför numeriskt (±0.005) i stället för som strängar —
        100 och 100.0 räknas som samma belopp.
        """
        target = _to_float(total_amount, default=float("nan"))
        supplier_norm = str(supplier).lower().strip()
        matches: list[dict] = []
        for r in self.all():
            if exclude_id and r.get("id") == exclude_id:
                continue
            if str(r.get("supplier", "")).lower().strip() != supplier_norm:
                continue
            if abs(_to_float(r.get("total_amount")) - target) <= 0.005:
                matches.append(r)
        return matches

    # ── Statusändringar ──────────────────────────────────────────────────

    def mark_paid(self, ids: list[str], payment_date: str = "") -> int:
        """Markerar fakturor som Betalda + sätter betalningsdatum."""
        date = payment_date or datetime.date.today().isoformat()
        count = 0
        for rid in ids:
            if self.update(rid, {"status": "Betald", "payment_date": date}):
                count += 1
        return count

    def mark_archived(self, ids: list[str]) -> int:
        """Arkiverar fakturor (sätts automatiskt efter PDF-export)."""
        count = 0
        for rid in ids:
            if self.update(rid, {"status": "Arkiverad"}):
                count += 1
        return count

    def restore_from_archive(self, ids: list[str]) -> int:
        """Återställer Arkiverade fakturor till Obetald."""
        count = 0
        for rid in ids:
            rec = self.get(rid)
            if rec and rec.get("status") == "Arkiverad":
                if self.update(rid, {"status": "Obetald"}):
                    count += 1
        return count

    def mark_status(self, ids: list[str], status: str) -> int:
        """Sätter valfri giltig status på flera fakturor."""
        if status not in VALID_INVOICE_STATUSES:
            raise ValueError(f"Ogiltig status: {status}")
        count = 0
        for rid in ids:
            if self.update(rid, {"status": status}):
                count += 1
        return count

    # ── Session-betalningsdatum helpers ──────────────────────────────────

    @staticmethod
    def format_session_due_date(
        session_due: datetime.date | None,
    ) -> str:
        """
        Formaterar session_due_date till YYYY-MM-DD-sträng.

        Returnerar '' om None. Används av InvoicesView för att sätta
        default i QDateEdit.
        """
        if session_due is None:
            return ""
        return session_due.isoformat()

    @staticmethod
    def parse_due_date(value: str) -> datetime.date | None:
        """Parsar YYYY-MM-DD till datetime.date. None vid fel."""
        try:
            return datetime.date.fromisoformat(value.strip())
        except Exception:
            return None


# ═════════════════════════════════════════════════════════════════════
#  PAYMENT ENGINE — betalbatchar
# ═════════════════════════════════════════════════════════════════════


class PaymentEngine:
    """Hanterar betalbatchar (grupper av fakturor med betalningsdatum)."""

    def __init__(
        self, store: DataStore, invoice_engine: InvoiceEngine
    ) -> None:
        self._store = store
        self._invoices = invoice_engine

    def create_batch(
        self,
        invoice_ids: list[str],
        payment_date: str = "",
        note: str = "",
    ) -> dict:
        """Skapar en betalbatch och markerar fakturorna som Planerade."""
        date = payment_date or datetime.date.today().isoformat()

        invoices: list[dict] = []
        for i in invoice_ids:
            inv = self._invoices.get(i)
            if inv:
                invoices.append(inv)

        total = self._invoices.total_amount(invoices)
        batch = self._store.add(
            {
                "invoice_ids":  invoice_ids,
                "payment_date": date,
                "total_amount": total,
                "status":       "Planerad",
                "note":         note,
            }
        )
        self._invoices.mark_status(invoice_ids, "Planerad")
        log.info(
            "Betalbatch: %d fakturor, totalt %s", len(invoice_ids), total
        )
        return batch

    def all(self) -> list[dict]:
        return self._store.all()

    def get(self, batch_id: str) -> dict | None:
        return self._store.get(batch_id)

    def count(self) -> int:
        return self._store.count()


# ═════════════════════════════════════════════════════════════════════
#  BACKUP MANAGER
# ═════════════════════════════════════════════════════════════════════


class BackupManager:
    """
    Skapar och hanterar ZIP-backuper av datamappen.

    • Backup-filer hamnar i mappen 'bak' (eller settings backup_path).
    • Restore är Zip Slip-säker (inga sökvägar utanför målmappen).
    """

    def __init__(self, settings: SettingsManager) -> None:
        self._settings = settings

    def _backup_dir(self) -> Path:
        p = confine_under("bak", self._settings.get("backup_path"))
        _ensure_dir(p)
        return p

    def _db_dir(self) -> Path:
        return confine_to_app(self._settings.get("db_path"), DATA_DIR)

    def create(self, label: str = "") -> Path | None:
        """Skapar en ZIP-backup. Returnerar sökvägen, eller None vid fel."""
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"backup_{ts}" + (f"_{label}" if label else "")
            arc = self._backup_dir() / name
            result = shutil.make_archive(
                str(arc), "zip", str(self._db_dir())
            )
            log.info("Backup skapad: %s", result)
            self._prune()
            return Path(result)
        except Exception as exc:
            log.error("Backup misslyckades: %s", exc)
            return None

    def _prune(self) -> None:
        """Behåller högst backup_keep antal backuper (äldst tas bort)."""
        keep = int(self._settings.get("backup_keep", 10))
        archives = sorted(self._backup_dir().glob("backup_*.zip"))
        while len(archives) > keep:
            old = archives.pop(0)
            old.unlink(missing_ok=True)
            log.debug("Rensade backup: %s", old.name)

    def archive_old(self, days: int | None = None) -> int:
        """
        Flyttar backuper äldre än *days* dagar (settings:
        archive_backups_days, standard 3) till egen mapp:
        <backup_dir>/Arkiv/.

        0 = avstängt. Returnerar antal flyttade filer.
        Fail-safe: kastar aldrig.
        """
        if days is None:
            try:
                days = int(self._settings.get("archive_backups_days", 3))
            except Exception:
                days = 3
        if days <= 0:
            return 0

        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        archive_dir = self._backup_dir() / "Arkiv"
        moved = 0
        try:
            for bak in sorted(self._backup_dir().glob("backup_*.zip")):
                try:
                    mtime = datetime.datetime.fromtimestamp(
                        bak.stat().st_mtime
                    )
                except OSError:
                    continue
                if mtime < cutoff:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    bak.rename(archive_dir / bak.name)
                    moved += 1
        except Exception as exc:
            log.warning("archive_old (backuper): %s", exc)
        if moved:
            log.info(
                "Arkiverade %d gamla backuper till %s", moved, archive_dir
            )
        return moved

    def list_backups(self) -> list[Path]:
        """Alla backuper, nyast först."""
        return sorted(
            self._backup_dir().glob("backup_*.zip"), reverse=True
        )

    def restore(
        self, archive: Path, target: Path | None = None
    ) -> bool:
        """
        Återställer en backup (Zip Slip-säker).

        Varje arkivmedlems sökväg verifieras mot målmappen INNAN
        uppackning — poster som pekar utanför blockeras.
        """
        import zipfile

        try:
            dst = (target or self._db_dir()).resolve()
            base = str(dst)
            with zipfile.ZipFile(str(archive)) as zf:
                for member in zf.namelist():
                    member_path = (dst / member).resolve()
                    inside = str(member_path) == base or str(
                        member_path
                    ).startswith(base + os.sep)
                    if not inside:
                        log.error(
                            "Restore BLOCKERAD (Zip Slip): %s", member
                        )
                        return False
                zf.extractall(dst)
            log.info("Restore klar: %s → %s", archive, dst)
            return True
        except Exception as exc:
            log.error("Restore misslyckades: %s", exc)
            return False


# ═════════════════════════════════════════════════════════════════════
#  PLUGIN LOADER
# ═════════════════════════════════════════════════════════════════════


class PluginLoader:
    """
    Laddar Python-plugins från plugins/.

    • Hoppar över filer som börjar med '_' eller slutar '_helpers.py'
      (hjälpmoduler registreras inte som egna plugins).
    • Ett plugin som kraschar stoppar aldrig de andra (fail-safe).
    • 3-STRIKES-RECOVERY (idén från PDF reader Pro SPEC v2.1, punkt 2.7):
      varje plugin har en kraschräknare i settings.json (plugin_strikes).
      När samma plugin kraschar 3 gånger avaktiveras det permanent
      (disabled_plugins) tills användaren återställer det via
      Inställningar-fliken. Vid lyckad laddning nollställs räknaren.
    """

    #: Antal raka krascher innan ett plugin avaktiveras.
    MAX_STRIKES: int = 3

    def __init__(
        self,
        plugin_dir: Path = PLUGIN_DIR,
        settings: "SettingsManager | None" = None,
    ) -> None:
        self._dir = plugin_dir
        self._settings = settings
        self._modules: list = []
        _ensure_dir(plugin_dir)

    # ── Strike-hantering ─────────────────────────────────────────────

    def _strikes(self) -> dict[str, int]:
        if self._settings is None:
            return {}
        try:
            data = self._settings.get("plugin_strikes", {})
            return {str(k): int(v) for k, v in (data or {}).items()}
        except Exception:
            return {}

    def _disabled(self) -> list[str]:
        if self._settings is None:
            return []
        try:
            return [str(x) for x in self._settings.get("disabled_plugins", []) or []]
        except Exception:
            return []

    def _bump_strike(self, name: str) -> int:
        """Ökar kraschräknaren. Avaktiverar vid MAX_STRIKES."""
        if self._settings is None:
            return 0
        strikes = self._strikes()
        strikes[name] = strikes.get(name, 0) + 1
        count = strikes[name]
        self._settings.set("plugin_strikes", strikes)
        if count >= self.MAX_STRIKES:
            disabled = self._disabled()
            if name not in disabled:
                disabled.append(name)
                self._settings.set("disabled_plugins", disabled)
            log.error(
                "PLUGIN_DISABLED: '%s' har kraschat %d gånger i rad "
                "→ avaktiverat tills det återställs via Inställningar",
                name, count,
            )
        return count

    def _clear_strike(self, name: str) -> None:
        """Nollställer kraschräknaren efter lyckad laddning."""
        if self._settings is None:
            return
        strikes = self._strikes()
        if name in strikes:
            strikes.pop(name)
            self._settings.set("plugin_strikes", strikes)

    def reenable_all(self) -> None:
        """Återställer alla avaktiverade plugins (nästa start försöker igen)."""
        if self._settings is not None:
            self._settings.set("plugin_strikes", {})
            self._settings.set("disabled_plugins", [])
        log.info("PLUGIN_REENABLE: alla avaktiverade plugins återställda")

    def status(self) -> dict[str, Any]:
        """Diagnostik: laddade plugins, strikes, avaktiverade."""
        return {
            "loaded": [getattr(m, "__name__", "?") for m in self._modules],
            "strikes": self._strikes(),
            "disabled": self._disabled(),
        }

    # ── Laddning ─────────────────────────────────────────────────────

    def load_all(self) -> list:
        self._modules = []
        if not self._dir.exists():
            return self._modules
        disabled = set(self._disabled())
        for f in sorted(self._dir.glob("*.py")):
            if f.name.startswith("_") or f.name.endswith("_helpers.py"):
                log.debug("PluginLoader hoppar över: %s", f.name)
                continue
            if f.stem in disabled:
                log.warning(
                    "PLUGIN_DISABLED: '%s' laddas inte (3-strikes, "
                    "återställ via Inställningar)", f.stem,
                )
                continue
            self._load_one(f)
        log.info(
            "PluginLoader: %d plugin(s) från %s",
            len(self._modules),
            self._dir,
        )
        return self._modules

    def _load_one(self, path: Path) -> None:
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if spec is None or spec.loader is None:
                log.warning("Kan inte ladda plugin: %s", path.name)
                return
            module = importlib.util.module_from_spec(spec)
            # Registrera i sys.modules under sitt namn så att andra
            # moduler (main.py, självtest) kan importera/hitta DETTA
            # plugin via `import advanced_logger` utan dublett-laddning.
            sys.modules[path.stem] = module
            try:
                spec.loader.exec_module(module)  # type: ignore
            except Exception:
                # Halvladdad modul ska aldrig bli kvar i sys.modules
                if sys.modules.get(path.stem) is module:
                    sys.modules.pop(path.stem, None)
                raise
            self._modules.append(module)
            self._clear_strike(path.stem)
            log.info("Plugin laddad: %s", path.name)
        except Exception as exc:
            count = self._bump_strike(path.stem)
            log.error(
                "Plugin load error (%s) — strike %d/%d: %s",
                path.name, count, self.MAX_STRIKES, exc,
            )

    def register_all(self, app: "FakturaApp") -> None:
        """Fas 1: register(app) för alla plugins."""
        for m in self._modules:
            if hasattr(m, "register"):
                try:
                    m.register(app)
                    log.info(
                        "Plugin registrerat (fas 1): %s",
                        getattr(m, "__name__", "?"),
                    )
                except Exception as exc:
                    log.error(
                        "Plugin register error (%s): %s",
                        getattr(m, "__name__", "?"),
                        exc,
                    )

    def register_ui_all(self, main_window: Any) -> None:
        """Fas 2: register_ui(main_window) för alla plugins."""
        for m in self._modules:
            if hasattr(m, "register_ui"):
                try:
                    m.register_ui(main_window)
                    log.info(
                        "Plugin UI registrerat (fas 2): %s",
                        getattr(m, "__name__", "?"),
                    )
                except Exception as exc:
                    log.error(
                        "Plugin register_ui error (%s): %s",
                        getattr(m, "__name__", "?"),
                        exc,
                    )

    @property
    def modules(self) -> list:
        return list(self._modules)


# ═════════════════════════════════════════════════════════════════════
#  STAGETIMER — init-mätning (idén från PDF reader Pro SPEC v2.1 §2.10)
# ═════════════════════════════════════════════════════════════════════


class StageTimer:
    """
    Mäter och loggar hur lång tid varje initieringsfas tar.

    Användning:
        t = StageTimer("settings")
        ... arbete ...
        t.stop()          → loggar INIT_STAGE settings klar på N.N ms
    """

    def __init__(self, stage: str) -> None:
        self.stage = stage
        self._t0 = time.perf_counter()

    def stop(self) -> float:
        ms = (time.perf_counter() - self._t0) * 1000.0
        log.info("INIT_STAGE %s klar på %.1f ms", self.stage, ms)
        return ms


# ═════════════════════════════════════════════════════════════════════
#  FREEZEWATCHDOG — GUI-frysningsvakt (idén från PDF reader Pro §2.9)
# ═════════════════════════════════════════════════════════════════════


class FreezeWatchdog:
    """
    Varnar om GUI-händelseslingan fryser.

    GUI-tråden anropar beat() via en QTimer (var 5:e sekund). En egen
    daemon-tråd kontrollerar att beat fortsätter komma. Om GUI-tråden
    hängt sig (oändlig loop, blockerande I/O på UI-tråden) uteblir
    beat → GUI_FREEZE loggas med tystnadens längd. När beat kommer
    tillbaka loggas GUI_RECOVER automatiskt.

    Vakten AVSLUTAR aldrig programmet — den ger bara spårbarhet i
    loggen (en AI/utvecklare kan se exakt när och hur länge det frös).
    """

    def __init__(self, interval: float = 5.0, limit: float = 30.0) -> None:
        self._interval = float(interval)
        self._limit = float(limit)
        self._last_beat = time.monotonic()
        self._running = False
        self._reported = False
        self._thread: threading.Thread | None = None

    def beat(self) -> None:
        """Hjärtat slag — anropas från GUI-trådens QTimer."""
        self._last_beat = time.monotonic()
        if self._reported:
            self._reported = False
            log.info("GUI_RECOVER: händelseslingan svarar igen")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._last_beat = time.monotonic()
        self._thread = threading.Thread(
            target=self._run, name="FreezeWatchdog", daemon=True
        )
        self._thread.start()
        log.debug(
            "FreezeWatchdog startad (kontroll var %.0f s, gräns %.0f s)",
            self._interval, self._limit,
        )

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        while self._running:
            time.sleep(self._interval)
            if not self._running:
                break
            silent = time.monotonic() - self._last_beat
            if silent >= self._limit and not self._reported:
                self._reported = True
                log.warning(
                    "GUI_FREEZE: händelseslingan har inte svarat på "
                    "%.0f s (gräns %.0f s) — möjlig frysning",
                    silent, self._limit,
                )


# ═════════════════════════════════════════════════════════════════════
#  SHORTCUT MANAGER — konfigurerbara kortkommandon i shortcuts.json
#  (idén från PDF reader Pro SPEC v2.1, punkt 2.7)
# ═════════════════════════════════════════════════════════════════════

#: Standardkortkommandon + svenska etiketter för Inställningar-fliken.
DEFAULT_SHORTCUTS: dict[str, str] = {
    "ny_leverantor":  "Ctrl+L",
    "ny_faktura":     "Ctrl+N",
    "skapa_backup":   "Ctrl+B",
    "exportera_pdf":  "Ctrl+E",
    "uppdatera":      "F5",
    "avsluta":        "Ctrl+Q",
    "tab_dashboard":  "Ctrl+1",
    "tab_fakturor":   "Ctrl+2",
    "tab_leverantorer": "Ctrl+3",
    "tab_betalningar":  "Ctrl+4",
    "tab_import":     "Ctrl+5",
    "tab_rapporter":  "Ctrl+6",
    "tab_installningar": "Ctrl+7",
    "tab_logg":       "Ctrl+8",
}

SHORTCUT_LABELS: dict[str, str] = {
    "ny_leverantor":    "Ny leverantör",
    "ny_faktura":       "Ny faktura",
    "skapa_backup":     "Skapa backup",
    "exportera_pdf":    "Exportera alla aktiva till PDF",
    "uppdatera":        "Uppdatera alla vyer",
    "avsluta":          "Avsluta programmet helt",
    "tab_logg":         "Hoppa till Logg",
    "tab_dashboard":    "Hoppa till Dashboard",
    "tab_fakturor":     "Hoppa till Fakturor",
    "tab_leverantorer": "Hoppa till Leverantörer",
    "tab_betalningar":  "Hoppa till Betalningar",
    "tab_import":       "Hoppa till Import",
    "tab_rapporter":    "Hoppa till Rapporter",
    "tab_installningar": "Hoppa till Inställningar",
}


class ShortcutManager:
    """
    Konfigurerbara kortkommandon lagrade i shortcuts.json (appmappen).

    • get(action)    → aktuell sekvens (standard om ej ändrad)
    • set(action, s) → ändrar + sparar atomärt
    • reset_all()    → återställer alla till standard
    Ogiltiga/tomma sekvenser ignoreras alltid (fail-safe).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = Path(path) if path else BASE_DIR / "shortcuts.json"
        self._data: dict[str, str] = dict(DEFAULT_SHORTCUTS)
        self._load()

    def _load(self) -> None:
        stored = _load_json(self._path, {})
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULT_SHORTCUTS and isinstance(value, str):
                    if value.strip():
                        self._data[key] = value
                    else:
                        # Tom sträng = "ingen tangent" — tillåtet val
                        self._data[key] = ""

    def get(self, action: str) -> str:
        return self._data.get(action, DEFAULT_SHORTCUTS.get(action, ""))

    def set(self, action: str, sequence: str) -> None:
        if action not in DEFAULT_SHORTCUTS:
            log.warning("ShortcutManager: okänd åtgärd '%s'", action)
            return
        self._data[action] = str(sequence or "")
        self._save()
        log.info(
            "SHORTCUT_SET: %s → '%s'", action, self._data[action] or "(ingen)"
        )

    def reset_all(self) -> None:
        self._data = dict(DEFAULT_SHORTCUTS)
        self._save()
        log.info("SHORTCUT_RESET: alla kortkommandon återställda")

    def all(self) -> dict[str, str]:
        return dict(self._data)

    def _save(self) -> bool:
        return _save_json(self._path, self._data)


# ═════════════════════════════════════════════════════════════════════
#  DIAGNOSTIK — "Kopiera diagnostik" (idén från PDF reader Pro §2.3)
# ═════════════════════════════════════════════════════════════════════


def collect_diagnostics(app_core: Any) -> str:
    """
    Samlar ALL relevant diagnostik till en text som kan kopieras till
    urklipp och klistras in i en felrapport/AI-chatt.

    Innehåll: versioner, plattform, tema, sökvägar + status,
    dataantal, plugin-hälsa, inställningar och de senaste loggraderna.
    """
    lines: list[str] = []
    add = lines.append

    add(f"{APP_NAME} — DIAGNOSTIK")
    add(f"Genererad : {_now_iso()}")
    add(f"Copyright : {COPYRIGHT}")
    add(f"Version   : {APP_VERSION}")
    add(f"Plattform : {CURRENT_PLATFORM} ({platform.platform()})")
    add(f"Python    : {sys.version.split()[0]} ({sys.executable})")

    try:
        import PySide6

        add(f"PySide6   : {getattr(PySide6, '__version__', '?')}")
    except Exception:
        add("PySide6   : ej installerad")

    # ── Sökvägar & status ────────────────────────────────────────────
    add("")
    add("── Sökvägar ──")
    add(f"Appmapp   : {BASE_DIR}")
    try:
        usage = shutil.disk_usage(str(BASE_DIR))
        add(f"Disk ledigt: {usage.free / (1024 ** 3):.1f} GB")
    except OSError:
        pass

    settings: SettingsManager | None = getattr(app_core, "settings", None)
    if settings is not None:
        for key in ("db_path", "backup_path", "export_path"):
            p = confine_to_app(settings.get(key), BASE_DIR)
            inside = "inne" if _is_inside(p, BASE_DIR) else "UTANFÖR"
            add(f"{key:10}: {p}  ({'finns' if p.exists() else 'SAKNAS'}, {inside})")
        try:
            plan = settings.get_autostart_manager().plan()
            add(
                "Autostart : "
                f"cwd={plan['working_directory']}  "
                f"väntar={plan['waits_for_drive_seconds']}s  "
                f"startfil={plan['launcher']}"
            )
        except Exception:
            pass
        log_file = BASE_DIR / "logs" / "app.log"
        add(f"{'log_path':10}: {log_file}  "
            f"({'finns' if log_file.exists() else 'SAKNAS'})")

    # ── Data ─────────────────────────────────────────────────────────
    add("")
    add("── Data ──")
    try:
        add(f"Fakturor      : {app_core.invoices.count()}")
        add(f"Leverantörer  : {app_core.suppliers_store.count()}")
        add(f"Betalbatchar  : {app_core.payments_store.count()}")
        add(f"Ändringslogg  : {len(app_core.changelog.all())} rader")
    except Exception as exc:
        add(f"Data räknare  : fel — {exc}")

    # ── Plugins (3-strikes-hälsa) ────────────────────────────────────
    add("")
    add("── Plugins ──")
    try:
        status = app_core.plugin_loader.status()
        add(f"Laddade     : {', '.join(status['loaded']) or '(inga)'}")
        if status["strikes"]:
            add(f"Strikes     : {status['strikes']}")
        if status["disabled"]:
            add(f"Avaktiverade: {', '.join(status['disabled'])}")
        else:
            add("Avaktiverade: (inga)")
    except Exception as exc:
        add(f"Pluginstatus: fel — {exc}")

    # ── Inställningar ────────────────────────────────────────────────
    add("")
    add("── Inställningar ──")
    if settings is not None:
        data = settings.all()
        # Skriv inte ut fönstergeometri-brus — bara meningsfulla nycklar
        for key in (
            "theme", "pdf_rounding", "startup", "start_minimized",
            "close_to_tray", "auto_backup", "backup_keep",
            "archive_backups_days", "archive_exports_days",
            "pycache_keep_days", "notify_due_days", "font_size",
            "schema_version", "log_trace", "clean_cache_on_exit",
        ):
            add(f"{key:20}: {data.get(key)}")
        add(f"hidden_tabs         : {data.get('hidden_tabs', [])}")
        add(f"company_name        : {data.get('company_name', '')!r}")

    # ── Autostart ────────────────────────────────────────────────────
    add("")
    add("── Autostart ──")
    try:
        mgr = settings.get_autostart_manager() if settings else None
        if mgr is not None:
            add(f"OS-registrerad: {mgr.is_enabled()}")
            add(f"Kommando      : {mgr.build_command()}")
    except Exception as exc:
        add(f"Autostart     : fel — {exc}")

    # ── Senaste loggrader ────────────────────────────────────────────
    add("")
    add("── Senaste 5 loggrader (logs/app.log) ──")
    log_file = BASE_DIR / "logs" / "app.log"
    try:
        if log_file.exists():
            tail = log_file.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()[-5:]
            for row in tail:
                add(row[:400])
        else:
            add("(loggen saknas)")
    except OSError as exc:
        add(f"(kunde inte läsa loggen: {exc})")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
#  FAKTURA APP — central singleton
# ═════════════════════════════════════════════════════════════════════


class FakturaApp:
    """
    Centralt applikationsobjekt — singleton.

    SESSION-BETALNINGSDATUM
    ───────────────────────
    • session_due_date (datetime.date | None) sätts av main.py via
      set_session_due_date() EN gång per programstart.
    • Lagras ALDRIG i JSON — nollställs automatiskt vid nästa start.
    • InvoicesView läser värdet som default-förfallodatum i dialogen.
    • Läs som sträng via session_due_date_str (YYYY-MM-DD).
    """

    _instance: "FakturaApp | None" = None

    def __new__(cls) -> "FakturaApp":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        # Session-betalningsdatum: None = ej satt ännu
        # (InvoicesView faller tillbaka på idag).
        self.session_due_date: datetime.date | None = None

        _init_start = time.perf_counter()
        log.info(
            "%s v%s startar på %s …",
            APP_NAME,
            APP_VERSION,
            CURRENT_PLATFORM,
        )

        # ── Settings + autostart ─────────────────────────────────────────
        _t = StageTimer("settings")
        self.settings = SettingsManager(SETTINGS_FILE)
        _t.stop()

        # ── Kortkommandon (shortcuts.json) ──────────────────────────────
        _t = StageTimer("genvagar")
        self.shortcuts = ShortcutManager()
        _t.stop()

        # ── Datalager ────────────────────────────────────────────────────
        _t = StageTimer("data")
        # Alltid <appmappen>/data. En tom data/suppliers.json ([])
        # är inte "vi har data" — ui/data och andra kopior slås ihop
        # in i data/ innan storen öppnas.
        db_path = DATA_DIR
        _ensure_dir(db_path)
        self.data_report = {}
        for fname, kind in (
            ("suppliers.json", "suppliers"),
            ("invoices.json", "invoices"),
            ("payments.json", "payments"),
        ):
            try:
                self.data_report[kind] = adopt_store_file(
                    BASE_DIR, fname, kind
                )
            except Exception as exc:
                log.error("DATA_LOAD %s: %s", fname, exc)

        self.changelog = ChangeLog(db_path / "changelog.json")
        self.invoices_store = DataStore(
            "invoices", db_path, INVOICE_SCHEMA, self.changelog
        )
        self.suppliers_store = DataStore(
            "suppliers", db_path, SUPPLIER_SCHEMA, self.changelog
        )
        self.payments_store = DataStore(
            "payments", db_path, PAYMENT_SCHEMA, self.changelog
        )
        _t.stop()

        # ── Motorer ──────────────────────────────────────────────────────
        self.invoices = InvoiceEngine(self.invoices_store)
        self.payments = PaymentEngine(self.payments_store, self.invoices)

        # ── Backup + plugins (3-strikes-recovery) ───────────────────────
        _t = StageTimer("plugins")
        self.backup = BackupManager(self.settings)
        self.plugin_loader = PluginLoader(PLUGIN_DIR, self.settings)
        self.plugin_loader.load_all()
        self.plugin_loader.register_all(self)
        _t.stop()

        # ── Auto-backup vid start ────────────────────────────────────────
        if self.settings.get("auto_backup", True):
            self.backup.create()

        # ── Exportmapp + auto-arkivering av gamla exporter ─────────────
        # Alltid <appmappen>/exports — aldrig en sökväg utanför.
        _ensure_dir(safe_app_root("exports"))
        self._archive_old_exports()

        # ── Självreparera settings: alla sökvägar inom appmappen ──────
        try:
            self._normalize_settings_paths()
        except Exception as exc:
            log.warning("Normalisering av settings-sökvägar: %s", exc)

        # ── Arkivera gamla backuper (3 d) + städa __pycache__ (3 d) ──
        _t = StageTimer("hushall")
        try:
            self.backup.archive_old()
        except Exception as exc:
            log.warning("Backup-arkivering: %s", exc)
        try:
            cleanup_pycache(
                BASE_DIR,
                int(self.settings.get("pycache_keep_days", 3)),
            )
        except Exception as exc:
            log.warning("pycache-städning: %s", exc)
        # Legacy-loggar från äldre versioner (audit/errors/performance/
        # structured + lös app.log i roten) — en-fil-principen.
        try:
            clean_legacy_logs()
        except Exception as exc:
            log.warning("legacy-loggrensning: %s", exc)
        _t.stop()

        self.init_ms = (time.perf_counter() - _init_start) * 1000.0
        log.info(
            "INIT_DONE: %s redo på %.0f ms (data=%s, plugins=%d, "
            "autostart=%s)",
            APP_NAME,
            self.init_ms,
            db_path,
            len(self.plugin_loader.modules),
            self.settings.autostart,
        )

    def register_plugins_ui(self, main_window: Any) -> None:
        """Fas 2 för alla plugins — anropas av main.py."""
        self.plugin_loader.register_ui_all(main_window)

    def reenable_plugins(self) -> None:
        """Återställer alla 3-strikes-avaktiverade plugins."""
        self.plugin_loader.reenable_all()

    def diagnostics(self) -> str:
        """Komplett diagnostiktext (för 'Kopiera diagnostik'-knappen)."""
        return collect_diagnostics(self)

    def clean_caches_on_exit(self) -> dict[str, Any]:
        """
        SMART CACHE-RENSARE vid avslut (settings: clean_cache_on_exit).

        Tömmer __pycache__/*.pyc/tmp-lämmar så att appmappen hålls ren
        mellan sessionerna. Data, settings, loggar och backuper röras
        aldrig. Returnerar statistik (tom dict om avstängt).
        """
        try:
            enabled = bool(self.settings.get("clean_cache_on_exit", True))
        except Exception:
            enabled = True
        if not enabled:
            log.debug("CACHE_CLEAN: avstängt i settings, hoppar över")
            return {}
        try:
            return clean_caches(BASE_DIR)
        except Exception as exc:
            log.warning("clean_caches_on_exit: %s", exc)
            return {}

    # ── Session-betalningsdatum API ──────────────────────────────────────

    def set_session_due_date(
        self, value: datetime.date | str | None
    ) -> None:
        """
        Sätter session-betalningsdatum för denna körning.

        Accepterar:
            • datetime.date     → används direkt
            • str (YYYY-MM-DD)  → parsas till datetime.date
            • None              → nollställer

        Sparar ALDRIG i JSON. Nollställs automatiskt vid nästa start.
        """
        if value is None:
            self.session_due_date = None
            log.info("session_due_date: nollställd")
            return
        if isinstance(value, datetime.datetime):
            value = value.date()
        if isinstance(value, datetime.date):
            self.session_due_date = value
            log.info("session_due_date: %s", value)
            return
        if isinstance(value, str):
            parsed = InvoiceEngine.parse_due_date(value)
            if parsed:
                self.session_due_date = parsed
                log.info("session_due_date (parsad): %s", parsed)
            else:
                log.warning(
                    "set_session_due_date: kunde inte parsa '%s'", value
                )
            return
        log.warning("set_session_due_date: okänd typ %s", type(value))

    @property
    def session_due_date_str(self) -> str:
        """session_due_date som YYYY-MM-DD ('' om ej satt)."""
        return InvoiceEngine.format_session_due_date(self.session_due_date)

    @property
    def has_session_due_date(self) -> bool:
        """True om session_due_date är satt."""
        return self.session_due_date is not None

    # ── Fakturor ─────────────────────────────────────────────────────────

    def add_invoice(self, data: dict) -> dict:
        return self.invoices.add(data)

    def update_invoice(self, record_id: str, data: dict) -> dict | None:
        return self.invoices.update(record_id, data)

    def delete_invoice(self, record_id: str) -> bool:
        return self.invoices.delete(record_id)

    def get_invoices(self) -> list[dict]:
        return self.invoices.all()

    def get_invoice(self, record_id: str) -> dict | None:
        return self.invoices.get(record_id)

    def search_invoices(self, query: str) -> list[dict]:
        return self.invoices.search(query)

    # ── Leverantörer ─────────────────────────────────────────────────────

    def add_supplier(self, data: dict) -> dict:
        return self.suppliers_store.add(data)

    def update_supplier(self, record_id: str, data: dict) -> dict | None:
        return self.suppliers_store.update(record_id, data)

    def delete_supplier(self, record_id: str) -> bool:
        return self.suppliers_store.delete(record_id)

    def get_suppliers(self) -> list[dict]:
        return self.suppliers_store.all()

    def rescan_data(self) -> str:
        """
        Läser om data/ från disk och slår ihop kopior (ui/data m.fl.).

        Anropas av Uppdatera och när filen ändras utanför appen
        (t.ex. sparad i Notepad++).
        """
        parts: list[str] = []
        for fname, kind, store_name in (
            ("suppliers.json", "suppliers", "suppliers_store"),
            ("invoices.json", "invoices", "invoices_store"),
            ("payments.json", "payments", "payments_store"),
        ):
            try:
                report = adopt_store_file(BASE_DIR, fname, kind)
                self.data_report[kind] = report
                store = getattr(self, store_name, None)
                if store is not None:
                    store.reload()
                parts.append(f"{kind} {report.get('count', 0)}")
            except Exception as exc:
                log.error("rescan_data %s: %s", fname, exc)
                parts.append(f"{kind} fel")
        summary = "Läste om data/: " + ", ".join(parts)
        log.info("DATA_RESCAN: %s", summary)
        return summary

    def data_load_summary(self) -> str:
        """Kort text till statusfältet: var leverantörerna lästes ifrån."""
        report = getattr(self, "data_report", {}) or {}
        sup = report.get("suppliers") or {}
        count = sup.get("count", 0)
        sources = sup.get("sources") or []
        if not sources:
            return (
                f"Leverantörer: {count} — data/suppliers.json är tom. "
                "Spara filen och tryck Uppdatera."
            )
        where = ", ".join(f"{p} ({n})" for p, n in sources)
        return f"Leverantörer: {count} från {where}"

    def get_supplier(self, record_id: str) -> dict | None:
        return self.suppliers_store.get(record_id)

    def search_suppliers(self, query: str) -> list[dict]:
        return self.suppliers_store.search(
            query, ["name", "org_number", "email", "phone"]
        )

    # ── Betalningar ──────────────────────────────────────────────────────

    def create_payment_batch(
        self,
        invoice_ids: list[str],
        payment_date: str = "",
        note: str = "",
    ) -> dict:
        return self.payments.create_batch(invoice_ids, payment_date, note)

    def get_payments(self) -> list[dict]:
        return self.payments.all()

    def get_payment(self, batch_id: str) -> dict | None:
        return self.payments.get(batch_id)

    # ── Dashboard ────────────────────────────────────────────────────────

    def dashboard_data(self) -> dict[str, Any]:
        """Alla nyckeltal för dashboard-vyn i en dict."""
        overdue = self.invoices.overdue()
        paid = self.invoices_store.filter_by(status="Betald")
        active = self.invoices.active()
        archived = self.invoices.archived()

        return {
            # Belopp
            "total_invoices":      self.invoices.total_positive(),
            "total_credits":       self.invoices.total_negative(),
            "netto":               self.invoices.total_amount(),
            "att_betala":          self.invoices.att_betala(),
            "total_unpaid":        self.invoices.total_unpaid(),
            "total_overdue":       self.invoices.total_overdue(),
            # Antal
            "count":               self.invoices.count(),
            "count_active":        len(active),
            "count_archived":      len(archived),
            "count_invoices":      len(self.invoices.invoices_only()),
            "count_credits":       len(self.invoices.credits_only()),
            "count_unpaid":        len(self.invoices.unpaid()),
            "count_overdue":       len(overdue),
            "count_paid":          len(paid),
            "count_by_status":     self.invoices.count_by_status(),
            "count_by_type":       self.invoices.count_by_type(),
            # Förfallna / kommande
            "due_today":           self.invoices.due_today(),
            "due_this_week":       self.invoices.due_this_week(),
            "due_this_month":      self.invoices.due_this_month(),
            "overdue_invoices":    overdue,
            # Senast registrerade (nyast först)
            "recent_invoices":     sorted(
                self.invoices.all(),
                key=lambda r: r.get("created_at", ""),
                reverse=True,
            )[:10],
            # Sammanställningar
            "summary_by_supplier": self.invoices.summary_by_supplier(),
            "summary_by_month":    self.invoices.summary_by_month(),
            # Session
            "session_due_date":    self.session_due_date_str,
            "platform":            CURRENT_PLATFORM,
            "generated_at":        _now_iso(),
        }

    # ── Settings ─────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self.settings.set(key, value)

    def get_all_settings(self) -> dict[str, Any]:
        return self.settings.all()

    # ── Changelog / Backup ───────────────────────────────────────────────

    def get_changelog(self) -> list[dict]:
        return self.changelog.all()

    def get_recent_changes(self, n: int = 50) -> list[dict]:
        return self.changelog.recent(n)

    def create_backup(self, label: str = "") -> Path | None:
        return self.backup.create(label)

    def list_backups(self) -> list[Path]:
        return self.backup.list_backups()

    def restore_backup(self, archive: Path) -> bool:
        """Återställer backup och laddar om alla stores."""
        success = self.backup.restore(archive)
        if success:
            self.invoices_store.reload()
            self.suppliers_store.reload()
            self.payments_store.reload()
            log.info("Alla stores omladdade efter backup-restore")
        return success

    # ── Export ───────────────────────────────────────────────────────────

    def export_data(self, fmt: str = "json") -> str | None:
        """Exporterar all data till JSON i exportmappen."""
        if fmt != "json":
            return None
        data = {
            "invoices":    self.get_invoices(),
            "suppliers":   self.get_suppliers(),
            "payments":    self.get_payments(),
            "settings":    self.get_all_settings(),
            "exported_at": _now_iso(),
            "app_version": APP_VERSION,
            "platform":    CURRENT_PLATFORM,
        }
        export_dir = confine_under("exports", self.settings.get("export_path"))
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = confine_export_file(
            export_dir / "Data" / datetime.date.today().isoformat()
            / f"data_export_{ts}.json"
        )
        if _save_json(path, data):
            log.info("Data exporterad: %s", path)
            return str(path)
        return None

    # ── Auto-arkivering av gamla exporter ────────────────────────────────

    def archive_old_exports(self, days: int | None = None) -> int:
        """
        Flyttar exporterade PDF:er äldre än *days* dagar till
        exports/Arkiv/ (settings: archive_exports_days, standard 10).

        0 = avstängt. Returnerar antal flyttade filer.
        """
        if days is None:
            days = int(self.settings.get("archive_exports_days", 10))
        if days <= 0:
            return 0

        export_dir = confine_under("exports", self.settings.get("export_path"))
        if not export_dir.exists():
            return 0

        archive_dir = export_dir / "Arkiv"
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        moved = 0
        try:
            for pdf in export_dir.rglob("*.pdf"):
                if "Arkiv" in pdf.parts:
                    continue
                try:
                    mtime = datetime.datetime.fromtimestamp(
                        pdf.stat().st_mtime
                    )
                except OSError:
                    continue
                if mtime < cutoff:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    pdf.rename(archive_dir / pdf.name)
                    moved += 1
        except Exception as exc:
            log.warning("archive_old_exports: %s", exc)
        if moved:
            log.info(
                "Arkiverade %d gamla exporter till %s", moved, archive_dir
            )
        return moved

    def _archive_old_exports(self) -> None:
        """Auto-arkivering vid start (fel får aldrig stoppa starten)."""
        try:
            self.archive_old_exports()
        except Exception as exc:
            log.warning("Auto-arkivering av exporter: %s", exc)

    def _normalize_settings_paths(self) -> None:
        """
        ALLT ska köras inom appmappen, oavsett var mappen ligger.

        settings.json sparar RELATIVA namn (data, bak, exports).
        En gammal absolut sökväg från en annan dator eller en annan
        USB-bokstav skrivs om. Då följer datan med mappen.
        """
        relative = {
            "db_path": "data",
            "backup_path": "bak",
            "export_path": "exports",
        }
        # Säkerställ att mapparna finns här, inte på den gamla platsen.
        confine_to_app(self.settings.get("db_path"), DATA_DIR)
        self.backup._backup_dir()
        safe_app_root("exports")
        updates: dict[str, str] = {}
        for key, rel in relative.items():
            if str(self.settings.get(key) or "") != rel:
                updates[key] = rel
        if updates:
            self.settings.update(updates)
            log.info(
                "SÖKVÄG_PORTABEL: %s (relativt appmappen, inte en fast disk)",
                ", ".join(f"{k}={v}" for k, v in updates.items()),
            )

    # ── App-info ─────────────────────────────────────────────────────────

    @staticmethod
    def app_info() -> dict[str, str]:
        return {
            "name":      APP_NAME,
            "version":   APP_VERSION,
            "copyright": COPYRIGHT,
            "platform":  CURRENT_PLATFORM,
            "python":    sys.version.split()[0],
        }


# ═════════════════════════════════════════════════════════════════════
#  SELF-TEST  (python app.py)
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 65)
    print(f"  {APP_NAME} v{APP_VERSION} — app.py självtest")
    print(f"  {COPYRIGHT}")
    print(f"  Platform : {CURRENT_PLATFORM}")
    print(f"  Python   : {sys.version.split()[0]}")
    print("=" * 65)

    fa = FakturaApp()

    # ── Session-betalningsdatum ────────────────────────────────────────
    print("\n  ── Session-betalningsdatum ──")
    print(f"  Initialt         : {fa.session_due_date}")
    print(f"  has_session_due  : {fa.has_session_due_date}")
    fa.set_session_due_date("2026-06-30")
    print(f"  Efter set (str)  : {fa.session_due_date}")
    print(f"  Som sträng       : {fa.session_due_date_str}")
    fa.set_session_due_date(datetime.date(2026, 7, 15))
    print(f"  Efter set (date) : {fa.session_due_date}")
    fa.set_session_due_date(None)
    print(f"  Efter nollst.    : {fa.session_due_date}")
    print(f"  has_session_due  : {fa.has_session_due_date}")

    # ── Autostart ──────────────────────────────────────────────────────
    mgr = fa.settings.get_autostart_manager()
    print("\n  ── Autostart ──")
    print(f"  Kommando         : {mgr.build_command()}")
    print(f"  Python-exe       : {mgr._python_exe}")
    print(f"  main.py          : {mgr._main_py}")
    print(f"  OS-registrerad   : {mgr.is_enabled()}")
    if CURRENT_PLATFORM == "windows":
        current = mgr.get_registered_command()
        print(f"  Registry-värde   : {current or '(ej registrerad)'}")
        expected = mgr.build_command()
        if current == expected:
            print("  Status           : ✔ Korrekt")
        elif current:
            print("  Status           : ✘ Felaktig sökväg!")
            print(f"  Korrekt          : {expected}")
        else:
            print("  Status           : – Ej registrerad")

    # ── Datastatus ─────────────────────────────────────────────────────
    print("\n  ── Data ──")
    print(f"  Settings startup : {fa.settings.get('startup')}")
    print(f"  Autostart (OS)   : {fa.settings.autostart}")
    print(f"  Fakturor         : {fa.invoices.count()}")
    print(f"  Leverantörer     : {len(fa.get_suppliers())}")
    print(f"  Plugins          : {len(fa.plugin_loader.modules)}")

    print("\n✅  app.py självtest klart.")
