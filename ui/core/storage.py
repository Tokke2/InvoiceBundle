from __future__ import annotations

"""
FakturaRäknaren — Storage Engine
======================================
Fil    : FakturaRäknaren_/ui/core/storage.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Produktionskvalitets JSON-lagringslager utan UI-beroenden.

Hanterar all persistent data för fakturor, leverantörer, betalningar,
inställningar, ändringslogg och bilagor.

Funktioner
----------
• Atomisk skrivning   (tmp → rename — inga korrupta filer vid krasch)
• UUID-baserad identitet (aldrig index-baserat CRUD)
• Full CRUD + bulk-operationer
• Change-listener callbacks (DataStore.on_change / off_change)
• Automatisk tidsstämpling (created_at / updated_at)
• Query-hjälp (filter, search, sort, paginate)
• Backup / restore (zip, 'bak/'-mappen, Zip Slip-säker restore)
• Korrupta filer karantänas (.corrupt_<ts>.json) i stället för att gå förlorade
• Schema-migrationsramverk
• Trådsäker via threading.RLock (återinträdande — callbacks kan läsa lagret)
• Singleton StorageManager (en instans per datamapp)
• Multi-OS: Windows / Linux / macOS
• Senast ändrad/tillagd post sorteras ALLTID SIST i
  all() / sorted() / search() / filter() / find_*() — synkroniserat
  med calculator.py och search.py (MUST-023)

Datafält som stöds
------------------
• invoices    – id, invoice_type, supplier, invoice_number, ocr,
                date, due_date, payment_date, total_amount, vat_percent,
                vat_amount, amount_ex_vat, currency, status, category,
                reference, note, attachment, created_at, updated_at
• suppliers   – id, name, org_number, bg, pg, iban, bic,
                payment_terms, contact_person, email, phone,
                address, note, created_at, updated_at
• payments    – id, invoice_ids, payment_date, total_amount,
                currency, status, note, created_at, updated_at
• settings    – se DEFAULT_SETTINGS nedan
• changelog   – id, timestamp, action, entity, entity_id, details
• attachments – id, invoice_id, filename, path, mime_type,
                size_bytes, created_at

Copyright © dynamiskt år Rickard Längkvist
"""

import copy
import datetime
import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterator

log = logging.getLogger("FakturaStorage")

# ═════════════════════════════════════════════════════════════════════
#  KONSTANTER
# ═════════════════════════════════════════════════════════════════════

COPYRIGHT_YEAR: int = datetime.date.today().year

DATE_FMT: str = "%Y-%m-%d"

#: Mikrosekundprecision — garanterar stabil ordning vid snabbt
#: på varandra följande mutationer (senast ändrad SIST, MUST-023).
DATETIME_FMT: str = "%Y-%m-%dT%H:%M:%S.%f"

#: Standardsökvägar relativt projektets root (FakturaRäknaren_/)
DEFAULT_DATA_DIR: Path = Path("ui") / "data"
DEFAULT_BACKUP_DIR: Path = Path("bak")

# ═════════════════════════════════════════════════════════════════════
#  HJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def _now_iso() -> str:
    """Aktuell tid som ISO-sträng (sekundprecision)."""
    return datetime.datetime.now().strftime(DATETIME_FMT)


def _new_id() -> str:
    """Nytt UUID4 som sträng."""
    return str(uuid.uuid4())


def _ensure_dir(path: Path) -> None:
    """Skapar mapp (och föräldrar) om den saknas."""
    path.mkdir(parents=True, exist_ok=True)


def _checksum(data: Any) -> str:
    """MD5 över innehållet — för ändringsdetektering (ej säkerhet)."""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode()).hexdigest()


# ═════════════════════════════════════════════════════════════════════
#  SORTERING — SENAST ÄNDRAD SIST  (MUST-023)
#
#  Synkroniserat med calculator._timestamp_sort_key och
#  search._timestamp_sort_key / _sort_newest_last — samma beteende
#  i hela applikationen.
# ═════════════════════════════════════════════════════════════════════


def _timestamp_sort_key(record: dict) -> str:
    """
    Sorteringsnyckel: updated_at → created_at → "".

    • Primärt        : updated_at (senast ändrad)
    • Fallback       : created_at (skapad)
    • Sista fallback : "" (sorteras alltid FÖRE nyare poster)

    Används så att senast ändrad/tillagd post hamnar SIST (längst bak)
    i alla listresultat.
    """
    ts = str(record.get("updated_at", "")).strip()
    if not ts:
        ts = str(record.get("created_at", "")).strip()
    return ts


def _sort_newest_last(records: list[dict]) -> list[dict]:
    """
    Sorterar poster med senast ändrad SIST (längst bak).

    Äldst → nyast (stigande ordning på updated_at/created_at).
    """
    return sorted(records, key=_timestamp_sort_key)


# ═════════════════════════════════════════════════════════════════════
#  JSON-FIL-I/O  (atomisk)
# ═════════════════════════════════════════════════════════════════════


def _load_json(path: Path, default: Any = None) -> Any:
    """
    Läser JSON från *path*. Returnerar *default* vid fel — kastar aldrig.

    Vid JSONDecodeError karantänas den korrupta filen så att datan
    inte går förlorad men inte heller läses in igen.
    """
    if not path.exists():
        return copy.deepcopy(default) if default is not None else []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        log.error(
            "JSON decode error (%s): %s — returnerar default", path, exc
        )
        _rotate_corrupt(path)
        return copy.deepcopy(default) if default is not None else []
    except OSError as exc:
        log.error("File read error (%s): %s", path, exc)
        return copy.deepcopy(default) if default is not None else []


def _save_json(path: Path, data: Any) -> bool:
    """
    Skriver *data* atomiskt som JSON till *path*.

    Skriver till .tmp först, döper sedan om — förhindrar korruption
    vid krasch. En läsare ser aldrig en halvskriven fil.
    Returnerar True vid lyckad skrivning.
    """
    _ensure_dir(path.parent)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4, ensure_ascii=False, default=str)
        tmp.replace(path)
        return True
    except OSError as exc:
        log.error("File write error (%s): %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _rotate_corrupt(path: Path) -> None:
    """
    Döper om en korrupt JSON-fil till .corrupt_<ts>.json så att den
    varken går förlorad eller läses in igen (karantän).
    """
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    corrupt = path.with_suffix(f".corrupt_{ts}.json")
    try:
        path.rename(corrupt)
        log.warning("Korrupt fil karantänad: %s", corrupt)
    except OSError:
        pass


# ═════════════════════════════════════════════════════════════════════
#  SCHEMA-REGISTER
# ═════════════════════════════════════════════════════════════════════

_SCHEMAS: dict[str, dict] = {
    "invoices": {
        "id":             "",
        "invoice_type":   "Faktura",
        "supplier":       "",
        "invoice_number": "",
        "ocr":            "",
        "date":           "",
        "due_date":       "",
        "payment_date":   "",
        "total_amount":   0.0,
        "vat_percent":    0,
        "vat_amount":     0.0,
        "amount_ex_vat":  0.0,
        "currency":       "SEK",
        "status":         "Obetald",
        "category":       "",
        "reference":      "",
        "note":           "",
        "attachment":     "",
        "created_at":     "",
        "updated_at":     "",
    },
    "suppliers": {
        "id":             "",
        "name":           "",
        "org_number":     "",
        "bg":             "",
        "pg":             "",
        "iban":           "",
        "bic":            "",
        "payment_terms":  30,
        "contact_person": "",
        "email":          "",
        "phone":          "",
        "address":        "",
        "note":           "",
        "created_at":     "",
        "updated_at":     "",
    },
    "payments": {
        "id":           "",
        "invoice_ids":  [],
        "payment_date": "",
        "total_amount": 0.0,
        "currency":     "SEK",
        "status":       "Planerad",
        "note":         "",
        "created_at":   "",
        "updated_at":   "",
    },
    "settings": {
        "theme":            "dark",
        "startup":          False,
        "start_minimized":  True,
        "close_to_tray":    True,
        "hidden_tabs":      [],
        "window_width":     1280,
        "window_height":    820,
        "window_x":         -1,
        "window_y":         -1,
        "window_maximized": False,
        "font_size":        13,
        "company_name":     "",
        "org_number":       "",
        "currency":         "SEK",
        "backup_path":      str(DEFAULT_BACKUP_DIR),
        "db_path":          str(DEFAULT_DATA_DIR),
        "export_path":      "exports",
        "notify_due_days":  3,
        "auto_backup":      True,
        "backup_keep":      10,
    },
    "changelog": {
        "id":        "",
        "timestamp": "",
        "action":    "",
        "entity":    "",
        "entity_id": "",
        "details":   {},
    },
    "attachments": {
        "id":         "",
        "invoice_id": "",
        "filename":   "",
        "path":       "",
        "mime_type":  "",
        "size_bytes": 0,
        "created_at": "",
    },
}


def get_schema(name: str) -> dict:
    """Returnerar en deep copy av schemat för *name*, eller tom dict."""
    return copy.deepcopy(_SCHEMAS.get(name, {}))


# ═════════════════════════════════════════════════════════════════════
#  DATA STORE  (en samling)
# ═════════════════════════════════════════════════════════════════════


class DataStore:
    """
    Trådsäker JSON-baserad list-of-dicts-store för en entitetstyp.

    Sortering (MUST-023)
    ────────────────────
    all(), sorted(), search(), filter(), filter_by() och find_*()
    returnerar alla poster med senast ändrad SIST (längst bak).
    Synkroniserat med calculator.py och search.py.

    Varje post får:
    • ``id``         — UUID-sträng (genereras om den saknas)
    • ``created_at`` — ISO-timestamp vid första sparning
    • ``updated_at`` — ISO-timestamp vid varje sparning
    """

    def __init__(
        self,
        name: str,
        data_dir: Path,
        schema: dict | None = None,
    ) -> None:
        self._name = name
        self._path = data_dir / f"{name}.json"
        self._schema = schema or _SCHEMAS.get(name, {})
        self._lock = threading.RLock()
        self._callbacks: list[Callable] = []
        self._records: list[dict] = []
        self._load()

    # ── Egenskaper ─────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._name

    @property
    def path(self) -> Path:
        return self._path

    # ── Persistens ─────────────────────────────────────────────────────

    def _load(self) -> None:
        with self._lock:
            raw = _load_json(self._path, [])
            if isinstance(raw, list):
                self._records = raw
            elif isinstance(raw, dict):
                self._records = [raw]
            else:
                self._records = []
            count = len(self._records)
        log.debug(
            "DataStore[%s] laddade %d poster från %s",
            self._name, count, self._path,
        )

    def _persist(self) -> bool:
        """
        Sparar intern ordning till disk (sorterar INTE om på disk —
        sorteringen sker vid läsning via all()/filter() etc.).
        Notifierar callbacks vid lyckad skrivning.
        """
        with self._lock:
            ok = _save_json(self._path, self._records)
        if ok:
            self._notify()
        return ok

    def reload(self) -> None:
        """Läser om från disk (t.ex. efter backup-restore)."""
        self._load()
        self._notify()

    # ── Callbacks ──────────────────────────────────────────────────────

    def on_change(self, callback: Callable) -> None:
        """Registrerar en callback: callback(store_name, snapshot)."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def off_change(self, callback: Callable) -> None:
        """Avregistrerar en tidigare registrerad callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify(self) -> None:
        """Skickar sorterad snapshot (senast ändrad sist) till callbacks."""
        with self._lock:
            snapshot = _sort_newest_last(list(self._records))
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb(self._name, snapshot)
            except Exception as exc:
                log.warning(
                    "DataStore[%s] callback error: %s", self._name, exc
                )

    # ── CRUD ───────────────────────────────────────────────────────────

    def add(self, data: dict) -> dict:
        """
        Lägger till en ny post. Returnerar den sparade posten.

        Ny post får senaste updated_at → visas sist i all().
        """
        with self._lock:
            record = copy.deepcopy(self._schema) if self._schema else {}
            record.update(copy.deepcopy(data))
            if not record.get("id"):
                record["id"] = _new_id()
            now = _now_iso()
            record.setdefault("created_at", now)
            record["updated_at"] = now
            self._records.append(record)
            saved = copy.deepcopy(record)
        self._persist()
        log.debug(
            "DataStore[%s] ADD id=%s updated_at=%s",
            self._name, saved["id"], now,
        )
        return saved

    def update(self, record_id: str, data: dict) -> dict | None:
        """
        Uppdaterar en post via id. Returnerar uppdaterad post eller None.

        updated_at sätts till nu → posten sorteras sist nästa all().
        """
        with self._lock:
            updated: dict | None = None
            for i, rec in enumerate(self._records):
                if rec.get("id") == record_id:
                    updated = copy.deepcopy(rec)
                    updated.update(copy.deepcopy(data))
                    updated["id"] = record_id
                    updated["updated_at"] = _now_iso()
                    self._records[i] = updated
                    break
            saved = copy.deepcopy(updated) if updated else None
        if saved is None:
            log.warning(
                "DataStore[%s] UPDATE — id hittades inte: %s",
                self._name, record_id,
            )
            return None
        self._persist()
        log.debug(
            "DataStore[%s] UPDATE id=%s updated_at=%s",
            self._name, record_id, saved["updated_at"],
        )
        return saved

    def upsert(self, data: dict) -> dict:
        """Uppdaterar om id finns, annars lägger till."""
        rid = data.get("id", "")
        if rid and self.get(rid):
            return self.update(rid, data) or self.add(data)
        return self.add(data)

    def delete(self, record_id: str) -> bool:
        """Tar bort post via id. True om den fanns och togs bort."""
        with self._lock:
            before = len(self._records)
            self._records = [
                r for r in self._records if r.get("id") != record_id
            ]
            deleted = len(self._records) < before
        if deleted:
            self._persist()
            log.debug(
                "DataStore[%s] DELETE id=%s", self._name, record_id
            )
            return True
        log.warning(
            "DataStore[%s] DELETE — id hittades inte: %s",
            self._name, record_id,
        )
        return False

    def delete_many(self, record_ids: list[str]) -> int:
        """Tar bort flera poster. Returnerar antal borttagna."""
        with self._lock:
            id_set = set(record_ids)
            before = len(self._records)
            self._records = [
                r for r in self._records if r.get("id") not in id_set
            ]
            count = before - len(self._records)
        if count:
            self._persist()
        return count

    # ── Läsning (senast ändrad sist) ───────────────────────────────────

    def get(self, record_id: str) -> dict | None:
        """Returnerar en kopia av posten med *record_id*, eller None."""
        with self._lock:
            for rec in self._records:
                if rec.get("id") == record_id:
                    return copy.deepcopy(rec)
        return None

    def all(self) -> list[dict]:
        """
        Alla poster — senast ändrad/tillagd SIST.
        Synkroniserat med calculator._sort_newest_last.
        """
        with self._lock:
            records = [copy.deepcopy(r) for r in self._records]
        return _sort_newest_last(records)

    def all_raw(self) -> list[dict]:
        """
        Poster i intern (insättnings-)ordning — OSORTERAT.
        Används internt vid bulk-operationer.
        """
        with self._lock:
            return [copy.deepcopy(r) for r in self._records]

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def is_empty(self) -> bool:
        return self.count() == 0

    def newest(self) -> dict | None:
        """Senast ändrad/tillagd post (sista i all()). None om tomt."""
        records = self.all()
        return records[-1] if records else None

    def oldest(self) -> dict | None:
        """Äldst ändrad post (första i all()). None om tomt."""
        records = self.all()
        return records[0] if records else None

    # ── Filter / sök ───────────────────────────────────────────────────

    def filter(self, predicate: Callable[[dict], bool]) -> list[dict]:
        """Kopior av alla poster som matchar *predicate*. Senast ändrad sist."""
        with self._lock:
            result = [
                copy.deepcopy(r) for r in self._records if predicate(r)
            ]
        return _sort_newest_last(result)

    def filter_by(self, **kwargs: Any) -> list[dict]:
        """
        Exakt fältlikhetsfilter. Senast ändrad sist.

        Exempel: store.filter_by(status="Obetald", currency="SEK")
        """
        return self.filter(
            lambda r: all(r.get(k) == v for k, v in kwargs.items())
        )

    def search(
        self, query: str, fields: list[str] | None = None
    ) -> list[dict]:
        """
        Skiftlägesokänslig delsträngssökning över *fields*.

        Flerordsökning: ALLA termer måste förekomma någonstans i posten.
        Senast ändrad sist.
        """
        if not query.strip():
            return self.all()   # redan sorterad senast-ändrad-sist

        fields = fields or list(self._schema.keys())
        terms = [t.lower() for t in query.split() if t.strip()]

        def _matches(rec: dict) -> bool:
            haystack = " ".join(
                str(rec.get(f, "") or "").lower() for f in fields
            )
            return all(t in haystack for t in terms)

        with self._lock:
            result = [
                copy.deepcopy(r)
                for r in self._records
                if _matches(r)
            ]
        return _sort_newest_last(result)

    def find_one(
        self, predicate: Callable[[dict], bool]
    ) -> dict | None:
        """Returnerar SENAST ÄNDRAD matchande post, eller None."""
        with self._lock:
            matching = [r for r in self._records if predicate(r)]
        if not matching:
            return None
        return copy.deepcopy(max(matching, key=_timestamp_sort_key))

    def find_by_field(self, field: str, value: Any) -> list[dict]:
        """Alla poster där record[field] == value. Senast ändrad sist."""
        with self._lock:
            result = [
                copy.deepcopy(r)
                for r in self._records
                if r.get(field) == value
            ]
        return _sort_newest_last(result)

    def find_duplicates(
        self,
        match_fields: list[str],
        candidate: dict,
        exclude_id: str = "",
    ) -> list[dict]:
        """
        Poster som matchar *candidate* på ALLA *match_fields*
        (skiftlägesokänslig strängjämförelse). Senast ändrad sist.
        """

        def _eq(a: Any, b: Any) -> bool:
            return str(a).lower().strip() == str(b).lower().strip()

        with self._lock:
            result = [
                copy.deepcopy(r)
                for r in self._records
                if r.get("id") != exclude_id
                and all(
                    _eq(r.get(f, ""), candidate.get(f, ""))
                    for f in match_fields
                )
            ]
        return _sort_newest_last(result)

    # ── Sortering / paginering ─────────────────────────────────────────

    def sorted(self, key: str, reverse: bool = False) -> list[dict]:
        """
        Alla poster sorterade på *key*.

        Sekundär nyckel: updated_at (stigande) → senast ändrad SIST
        vid lika primärvärden. Blandade typer (tal/text) kraschar inte.
        """

        def _primary(r: dict) -> tuple[int, float, str]:
            val = r.get(key, "")
            try:
                return (0, float(val), "")
            except (TypeError, ValueError):
                return (1, 0.0, str(val).lower())

        def _sort_key(r: dict) -> tuple[tuple[int, float, str], str]:
            return (_primary(r), _timestamp_sort_key(r))

        with self._lock:
            records = [copy.deepcopy(r) for r in self._records]
        return sorted(records, key=_sort_key, reverse=reverse)

    def paginate(
        self,
        page: int,
        page_size: int,
        data: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        Paginerar *data* (standard: alla poster, senast ändrad sist).

        Returnerar dict med items/page/page_size/total/pages/
        has_next/has_prev.
        """
        records = data if data is not None else self.all()
        total = len(records)
        pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, pages))
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "items":     records[start:end],
            "page":      page,
            "page_size": page_size,
            "total":     total,
            "pages":     pages,
            "has_next":  page < pages,
            "has_prev":  page > 1,
        }

    # ── Bulk ───────────────────────────────────────────────────────────

    def bulk_add(self, items: list[dict]) -> list[dict]:
        """
        Lägger till flera poster i EN skrivning.

        Alla nya poster får samma now-timestamp → hamnar sist i all()
        i registreringsordning.
        """
        with self._lock:
            added = []
            now = _now_iso()
            for data in items:
                record = (
                    copy.deepcopy(self._schema) if self._schema else {}
                )
                record.update(copy.deepcopy(data))
                if not record.get("id"):
                    record["id"] = _new_id()
                record.setdefault("created_at", now)
                record["updated_at"] = now
                self._records.append(record)
                added.append(copy.deepcopy(record))
        self._persist()
        return added

    def bulk_update(self, updates: list[tuple[str, dict]]) -> int:
        """
        Uppdaterar flera poster: lista av (record_id, data_dict).
        Returnerar antal uppdaterade.
        """
        with self._lock:
            id_map = {
                r["id"]: i
                for i, r in enumerate(self._records)
                if "id" in r
            }
            now = _now_iso()
            count = 0
            for record_id, data in updates:
                if record_id in id_map:
                    idx = id_map[record_id]
                    self._records[idx].update(copy.deepcopy(data))
                    self._records[idx]["id"] = record_id
                    self._records[idx]["updated_at"] = now
                    count += 1
        if count:
            self._persist()
        return count

    # ── Utility ────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Tar bort ALLA poster (oåterkalleligt utan backup)."""
        with self._lock:
            self._records = []
        self._persist()
        log.warning("DataStore[%s] TÖMD", self._name)

    def checksum(self) -> str:
        """MD5-checksum av aktuellt innehåll — ändringsdetektering."""
        with self._lock:
            return _checksum(self._records)

    def export_json(self) -> str:
        """Aktuell data som formaterad JSON-sträng (senast ändrad sist)."""
        return json.dumps(
            self.all(), indent=4, ensure_ascii=False, default=str
        )

    def import_json(self, json_str: str, merge: bool = False) -> int:
        """
        Importerar poster från en JSON-sträng (lista av dicts).

        merge=True  → behåll befintliga, lägg till/uppdatera importerade
        merge=False → ersätt allt

        Returnerar antal importerade poster.
        """
        try:
            incoming = json.loads(json_str)
            if not isinstance(incoming, list):
                raise ValueError("Expected JSON array")
        except (json.JSONDecodeError, ValueError) as exc:
            log.error("import_json misslyckades: %s", exc)
            return 0

        with self._lock:
            if not merge:
                self._records = []
            now = _now_iso()
            for record in incoming:
                if not isinstance(record, dict):
                    continue
                if not record.get("id"):
                    record["id"] = _new_id()
                record.setdefault("created_at", now)
                record["updated_at"] = now
                existing_idx = next(
                    (
                        i
                        for i, r in enumerate(self._records)
                        if r.get("id") == record["id"]
                    ),
                    None,
                )
                if existing_idx is not None:
                    self._records[existing_idx] = record
                else:
                    self._records.append(record)
        self._persist()
        return len(incoming)

    # ── Iteration ──────────────────────────────────────────────────────

    def __iter__(self) -> Iterator[dict]:
        """Itererar i senast-ändrad-sist-ordning."""
        return iter(self.all())

    def __len__(self) -> int:
        return self.count()

    def __contains__(self, record_id: str) -> bool:
        return self.get(record_id) is not None

    def __repr__(self) -> str:
        return (
            f"DataStore(name={self._name!r}, "
            f"records={self.count()}, path={self._path})"
        )


# ═════════════════════════════════════════════════════════════════════
#  SETTINGS STORE  (ett JSON-objekt, inte lista)
# ═════════════════════════════════════════════════════════════════════


class SettingsStore:
    """
    Tunn wrapper kring ett enda JSON-objekt.

    Slår alltid ihop inläst data med DEFAULT_SETTINGS så att nya
    nycklar finns efter en app-uppgradering.

    Stöder bl.a.: theme, startup (autostart), start_minimized,
    close_to_tray, hidden_tabs, backup_path, db_path, export_path.
    """

    def __init__(self, path: Path, defaults: dict) -> None:
        self._path = path
        self._defaults = copy.deepcopy(defaults)
        self._data: dict = {}
        self._lock = threading.RLock()
        self._callbacks: list[Callable] = []
        self._load()

    def _load(self) -> None:
        with self._lock:
            stored = _load_json(self._path, {})
            self._data = copy.deepcopy(self._defaults)
            if isinstance(stored, dict):
                self._data.update(stored)

    def _persist(self) -> bool:
        with self._lock:
            ok = _save_json(self._path, self._data)
            snapshot = dict(self._data)
            callbacks = list(self._callbacks)
        if ok:
            for cb in callbacks:
                try:
                    cb(snapshot)
                except Exception as exc:
                    log.warning("SettingsStore callback error: %s", exc)
        return ok

    def on_change(self, callback: Callable) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
        self._persist()

    def update(self, mapping: dict) -> None:
        with self._lock:
            self._data.update(mapping)
        self._persist()

    def all(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def reset(self) -> None:
        with self._lock:
            self._data = copy.deepcopy(self._defaults)
        self._persist()

    def reload(self) -> None:
        self._load()

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def __repr__(self) -> str:
        return f"SettingsStore(path={self._path}, keys={len(self._data)})"


# ═════════════════════════════════════════════════════════════════════
#  CHANGELOG STORE  (append-only)
# ═════════════════════════════════════════════════════════════════════


class ChangelogStore:
    """
    Append-only logg över alla datamutationer.

    Ändrar eller tar aldrig bort befintliga poster.
    Returnerar poster i kronologisk ordning (äldst först).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        _ensure_dir(path.parent)

    def record(
        self,
        action: str,
        entity: str,
        entity_id: str,
        details: dict | None = None,
    ) -> dict:
        """Lägger till en ändringspost. Returnerar posten."""
        entry = {
            "id":        _new_id(),
            "timestamp": _now_iso(),
            "action":    action,
            "entity":    entity,
            "entity_id": entity_id,
            "details":   details or {},
        }
        with self._lock:
            existing = _load_json(self._path, [])
            if not isinstance(existing, list):
                existing = []
            existing.append(entry)
            _save_json(self._path, existing)
        return entry

    def all(self) -> list[dict]:
        """Alla poster i kronologisk ordning (äldst först)."""
        return _load_json(self._path, [])

    def for_entity(self, entity: str, entity_id: str) -> list[dict]:
        """Alla poster för en specifik entitet."""
        return [
            e
            for e in self.all()
            if e.get("entity") == entity
            and e.get("entity_id") == entity_id
        ]

    def recent(self, n: int = 50) -> list[dict]:
        """De N senaste posterna (sista = nyast)."""
        return self.all()[-n:]

    def clear(self) -> None:
        """Tömmer loggen (endast admin-användning)."""
        with self._lock:
            _save_json(self._path, [])

    def __repr__(self) -> str:
        return f"ChangelogStore(path={self._path})"


# ═════════════════════════════════════════════════════════════════════
#  BACKUP MANAGER
# ═════════════════════════════════════════════════════════════════════


class BackupManager:
    """
    Skapar/återställer tidsstämplade zip-arkiv av datamappen.

    • Backup-filer sparas i 'bak/'-mappen som standard.
    • Gamla backuper rensas automatiskt (keep).
    • Restore är Zip Slip-säker — sökvägar utanför målmappen blockeras.
    • Multi-OS: Windows / Linux / macOS.
    """

    def __init__(
        self,
        data_dir: Path,
        backup_dir: Path,
        keep: int = 10,
    ) -> None:
        self._data_dir = data_dir
        self._backup_dir = backup_dir
        self._keep = keep
        _ensure_dir(backup_dir)

    def create(self, label: str = "") -> Path | None:
        """Skapar zip-arkiv av datamappen. Path vid lyckat, None vid fel."""
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"backup_{ts}" + (f"_{label}" if label else "")
            arc = self._backup_dir / name
            result = shutil.make_archive(
                str(arc), "zip", str(self._data_dir)
            )
            log.info("Backup skapad: %s", result)
            self._prune()
            return Path(result)
        except Exception as exc:
            log.error("Backup create error: %s", exc)
            return None

    def restore(
        self, archive: Path, target_dir: Path | None = None
    ) -> bool:
        """
        Återställer ett backup-arkiv till *target_dir* (default: data_dir).

        Zip Slip-säker: varje arkivmedlems sökväg verifieras mot
        målmappen INNAN uppackning — poster som pekar utanför blockeras.
        """
        dst = (target_dir or self._data_dir).resolve()
        base = str(dst)
        try:
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
            log.info("Backup återställd: %s → %s", archive, dst)
            return True
        except Exception as exc:
            log.error("Backup restore error: %s", exc)
            return False

    def list_backups(self) -> list[Path]:
        """Alla backup-arkiv, nyast först."""
        return sorted(
            self._backup_dir.glob("backup_*.zip"), reverse=True
        )

    def _prune(self) -> None:
        """Behåller högst *keep* backuper (äldst tas bort)."""
        archives = sorted(self._backup_dir.glob("backup_*.zip"))
        while len(archives) > self._keep:
            archives.pop(0).unlink(missing_ok=True)

    def set_keep(self, n: int) -> None:
        self._keep = n

    def set_backup_dir(self, path: Path) -> None:
        self._backup_dir = path
        _ensure_dir(path)

    def __repr__(self) -> str:
        return (
            f"BackupManager(backup_dir={self._backup_dir}, "
            f"keep={self._keep})"
        )


# ═════════════════════════════════════════════════════════════════════
#  SCHEMA-MIGRATIONSRAMVERK
# ═════════════════════════════════════════════════════════════════════


class MigrationRunner:
    """
    Applicerar schemamigreringar på lagrade poster.

    En migrering är en funktion:
        def migrate_v2(records: list[dict]) -> list[dict]: ...

    Registreras med:
        runner.register("invoices", 2, migrate_v2)
    """

    def __init__(self) -> None:
        self._migrations: dict[str, dict[int, Callable]] = {}

    def register(
        self,
        store_name: str,
        version: int,
        fn: Callable[[list[dict]], list[dict]],
    ) -> None:
        self._migrations.setdefault(store_name, {})[version] = fn

    def run(
        self,
        store_name: str,
        records: list[dict],
        current_version: int = 0,
        target_version: int | None = None,
    ) -> tuple[list[dict], int]:
        """
        Applicerar migreringar i versionsordning från current_version+1.
        Returnerar (migrerade_poster, slutversion).
        """
        migrations = self._migrations.get(store_name, {})
        versions = sorted(v for v in migrations if v > current_version)
        if target_version is not None:
            versions = [v for v in versions if v <= target_version]

        version = current_version
        for v in versions:
            try:
                records = migrations[v](records)
                version = v
                log.info(
                    "Migration[%s] v%d applicerad (%d poster)",
                    store_name, v, len(records),
                )
            except Exception as exc:
                log.error(
                    "Migration[%s] v%d MISSLYCKADES: %s",
                    store_name, v, exc,
                )
                break
        return records, version


# ═════════════════════════════════════════════════════════════════════
#  DEFAULT SETTINGS  (synkade med _SCHEMAS["settings"])
# ═════════════════════════════════════════════════════════════════════

DEFAULT_SETTINGS: dict = copy.deepcopy(_SCHEMAS["settings"])


# ═════════════════════════════════════════════════════════════════════
#  STORAGE MANAGER  (top-level-fasad / singleton)
# ═════════════════════════════════════════════════════════════════════


class StorageManager:
    """
    Central lagringsfasad — singleton per datamapp.

    Äger
    ----
    • DataStore för invoices, suppliers, payments, attachments
    • SettingsStore (settings.json)
    • ChangelogStore (changelog.json)
    • BackupManager (bak/-mappen som standard)
    • MigrationRunner

    Sortering: alla DataStore-anrop returnerar senast ändrad SIST.

    Usage
    -----
        sm = StorageManager()                # ui/data/
        sm = StorageManager("min/datamapp")  # anpassad sökväg
        sm.invoices.add({...})
        sm.invoices.all()     # → senast ändrad sist
        sm.invoices.newest()  # → senast ändrad post
        sm.settings.get("theme")
        sm.changelog.record("ADD", "invoices", record_id)
        sm.backup.create()
    """

    _instances: dict[str, "StorageManager"] = {}

    def __new__(
        cls,
        data_dir: str | Path = DEFAULT_DATA_DIR,
        backup_dir: str | Path | None = None,
    ) -> "StorageManager":
        key = str(Path(data_dir).resolve())
        if key not in cls._instances:
            cls._instances[key] = super().__new__(cls)
        return cls._instances[key]

    def __init__(
        self,
        data_dir: str | Path = DEFAULT_DATA_DIR,
        backup_dir: str | Path | None = None,
    ) -> None:
        if getattr(self, "_ready", False):
            return
        self._ready = True

        self._data_dir = Path(data_dir).resolve()
        _ensure_dir(self._data_dir)

        # ── Data-stores ────────────────────────────────────────────────
        self.invoices = DataStore("invoices", self._data_dir)
        self.suppliers = DataStore("suppliers", self._data_dir)
        self.payments = DataStore("payments", self._data_dir)
        self.attachments = DataStore("attachments", self._data_dir)

        # ── Settings ──────────────────────────────────────────────────
        self.settings = SettingsStore(
            self._data_dir / "settings.json", DEFAULT_SETTINGS
        )

        # ── Changelog ──────────────────────────────────────────────────
        self.changelog = ChangelogStore(
            self._data_dir / "changelog.json"
        )

        # ── Backup ─────────────────────────────────────────────────────
        bkp_dir = (
            Path(backup_dir)
            if backup_dir
            else Path(
                self.settings.get(
                    "backup_path", str(DEFAULT_BACKUP_DIR)
                )
            )
        )
        self.backup = BackupManager(
            self._data_dir,
            bkp_dir,
            keep=int(self.settings.get("backup_keep", 10)),
        )

        # ── Migreringar ────────────────────────────────────────────────
        self.migrations = MigrationRunner()

        log.info(
            "StorageManager redo (data=%s, backup=%s)",
            self._data_dir, bkp_dir,
        )

    # ── CRUD (delegerar till stores + loggar ändringar) ────────────────

    def add(self, store_name: str, data: dict) -> dict:
        store = self._store(store_name)
        record = store.add(data)
        self.changelog.record("ADD", store_name, record["id"])
        return record

    def update(
        self, store_name: str, record_id: str, data: dict
    ) -> dict | None:
        store = self._store(store_name)
        result = store.update(record_id, data)
        if result:
            self.changelog.record(
                "UPDATE", store_name, record_id, data
            )
        return result

    def delete(self, store_name: str, record_id: str) -> bool:
        store = self._store(store_name)
        ok = store.delete(record_id)
        if ok:
            self.changelog.record("DELETE", store_name, record_id)
        return ok

    def get(self, store_name: str, record_id: str) -> dict | None:
        return self._store(store_name).get(record_id)

    def all(self, store_name: str) -> list[dict]:
        """Alla poster — senast ändrad SIST."""
        return self._store(store_name).all()

    def search(
        self,
        store_name: str,
        query: str,
        fields: list[str] | None = None,
    ) -> list[dict]:
        """Sökresultat — senast ändrad SIST."""
        return self._store(store_name).search(query, fields)

    def _store(self, name: str) -> DataStore:
        mapping: dict[str, DataStore] = {
            "invoices":    self.invoices,
            "suppliers":   self.suppliers,
            "payments":    self.payments,
            "attachments": self.attachments,
        }
        if name not in mapping:
            raise KeyError(f"Okänd store: '{name}'")
        return mapping[name]

    # ── Statistik ──────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        newest_inv = self.invoices.newest()
        newest_sup = self.suppliers.newest()
        return {
            "invoices":        self.invoices.count(),
            "suppliers":       self.suppliers.count(),
            "payments":        self.payments.count(),
            "attachments":     self.attachments.count(),
            "data_dir":        str(self._data_dir),
            "newest_invoice":  (
                newest_inv.get("invoice_number", "?")
                if newest_inv else None
            ),
            "newest_supplier": (
                newest_sup.get("name", "?") if newest_sup else None
            ),
            "checksums": {
                "invoices":  self.invoices.checksum(),
                "suppliers": self.suppliers.checksum(),
                "payments":  self.payments.checksum(),
            },
        }

    def reload_all(self) -> None:
        """Läser om alla stores från disk."""
        for store in (
            self.invoices,
            self.suppliers,
            self.payments,
            self.attachments,
        ):
            store.reload()
        self.settings.reload()

    # ── Bakåtkompatibla hjälpfunktioner ────────────────────────────────

    def load(self, name: str) -> list[dict]:
        """Legacy: alla poster från *name* (senast ändrad sist)."""
        return self._store(name).all()

    def save(self, name: str, data: list[dict]) -> None:
        """Legacy: skriv över hela store:n (använd med försiktighet)."""
        store = self._store(name)
        with store._lock:
            store._records = list(data)
        store._persist()

    def clear(self, name: str) -> None:
        """Legacy: töm alla poster i *name*."""
        self._store(name).clear()

    def count(self, name: str) -> int:
        """Legacy: antal poster i *name*."""
        return self._store(name).count()

    def __repr__(self) -> str:
        return (
            f"StorageManager(data_dir={self._data_dir}, "
            f"invoices={self.invoices.count()}, "
            f"suppliers={self.suppliers.count()})"
        )


# ═════════════════════════════════════════════════════════════════════
#  GLOBAL SINGLETON
# ═════════════════════════════════════════════════════════════════════

storage = StorageManager()


# ═════════════════════════════════════════════════════════════════════
#  SELF-TEST  (python ui/core/storage.py)
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import tempfile
    import time

    print("=" * 65)
    print("  FakturaRäknaren — Storage Engine självtest")
    print(f"  © {COPYRIGHT_YEAR} Rickard Längkvist")
    print("  Fil: FakturaRäknaren_/ui/core/storage.py")
    print("=" * 65)

    with tempfile.TemporaryDirectory() as tmp:
        sm = StorageManager(tmp)

        # ── add ───────────────────────────────────────────────────────
        inv1 = sm.add("invoices", {
            "supplier":       "Acme AB",
            "invoice_number": "INV-001",
            "invoice_type":   "Faktura",
            "total_amount":   1250.0,
            "vat_percent":    25,
            "vat_amount":     250.0,
            "amount_ex_vat":  1000.0,
            "payment_date":   "2025-02-15",
            "status":         "Obetald",
        })
        print(f"\n  Add invoice 1: id={inv1['id'][:8]}… "
              f"type={inv1.get('invoice_type')} updated={inv1['updated_at']}")
        time.sleep(0.01)

        inv2 = sm.add("invoices", {
            "supplier":       "Beta AB",
            "invoice_number": "INV-002",
            "invoice_type":   "Faktura",
            "total_amount":   3000.0,
            "status":         "Obetald",
        })
        print(f"  Add invoice 2: id={inv2['id'][:8]}… "
              f"updated={inv2['updated_at']}")

        # ── sortering: senast tillagd SIST ─────────────────────────────
        print("\n  ── Sortering: senast ändrad SIST ──")
        all_inv = sm.invoices.all()
        for r in all_inv:
            print(f"    {r['invoice_number']:<12} updated={r['updated_at']}")
        assert all_inv[-1]["id"] == inv2["id"], "SORTERINGSFEL: inv2 sist!"
        print("  ✅ inv2 (senast tillagd) är SIST")

        assert sm.invoices.newest()["id"] == inv2["id"], "newest() fel!"
        print(f"  newest() = {sm.invoices.newest()['invoice_number']}  ✅")
        assert sm.invoices.oldest()["id"] == inv1["id"], "oldest() fel!"
        print(f"  oldest() = {sm.invoices.oldest()['invoice_number']}  ✅")

        # ── update → sorteras om till sist ─────────────────────────────
        time.sleep(0.01)
        updated = sm.update("invoices", inv1["id"], {"status": "Betald"})
        print(f"\n  Update inv1 → status={updated['status']} "
              f"updated={updated['updated_at']}")
        all_after = sm.invoices.all()
        assert all_after[-1]["id"] == inv1["id"], \
            "SORTERINGSFEL: uppdaterad inv1 sist!"
        print(f"  all() efter update: senast = "
              f"{all_after[-1]['invoice_number']}  ✅")

        # ── kreditfaktura ──────────────────────────────────────────────
        time.sleep(0.01)
        crd = sm.add("invoices", {
            "supplier":       "Acme AB",
            "invoice_number": "KRE-001",
            "invoice_type":   "Kreditfaktura",
            "total_amount":   -500.0,
            "status":         "Obetald",
        })
        print(f"\n  Add kredit: {crd['invoice_number']} "
              f"amount={crd.get('total_amount')}")
        assert sm.invoices.newest()["id"] == crd["id"], "newest() fel!"
        print(f"  newest() = {sm.invoices.newest()['invoice_number']}  ✅")

        # ── search / filter_by sorterar senast sist ────────────────────
        results = sm.search("invoices", "acme")
        print(f"\n  Search 'acme' → {len(results)} resultat")
        if len(results) >= 2:
            assert (
                _timestamp_sort_key(results[-1])
                >= _timestamp_sort_key(results[0])
            ), "search sorteringsfel!"
            print("  ✅ sökresultat: senast ändrad sist")

        credits = sm.invoices.filter_by(invoice_type="Kreditfaktura")
        assert credits[-1]["invoice_number"] == "KRE-001", \
            "filter_by sorteringsfel!"
        print(f"  filter_by(Kreditfaktura) → {len(credits)}  ✅")

        # ── settings ───────────────────────────────────────────────────
        sm.settings.set("theme", "dark")
        sm.settings.set("start_minimized", True)
        sm.settings.set("close_to_tray", True)
        sm.settings.set("startup", False)
        print(f"\n  Settings: theme={sm.settings.get('theme')} "
              f"start_minimized={sm.settings.get('start_minimized')} "
              f"close_to_tray={sm.settings.get('close_to_tray')}")

        # ── backup + restore (Zip Slip-test) ───────────────────────────
        bak_dir = Path(tmp) / "bak"
        sm.backup.set_backup_dir(bak_dir)
        arc = sm.backup.create("selftest")
        print(f"\n  Backup → {arc.name if arc else 'FAILED'}")
        assert arc is not None and arc.exists(), "backup saknas!"
        assert sm.backup.restore(arc), "restore misslyckades!"
        print("  Restore ✔  (Zip Slip-säker)")

        # ── changelog ──────────────────────────────────────────────────
        print(f"  Changelog entries: {len(sm.changelog.all())}")
        print(f"  Recent (3): "
              f"{[e['action'] for e in sm.changelog.recent(3)]}")

        # ── stats / sorted / paginate ──────────────────────────────────
        s = sm.stats()
        print(f"\n  Stats: invoices={s['invoices']} "
              f"newest_invoice={s['newest_invoice']}")

        sorted_by_status = sm.invoices.sorted("status")
        print(f"  sorted('status') → {len(sorted_by_status)} poster")
        print("  ✅ sorted() med sekundärnyckel (senast ändrad sist)")

        for i in range(5):
            sm.add("suppliers", {"name": f"Supplier {i + 1}"})
        page = sm.suppliers.paginate(1, 3)
        print(f"  Paginate p1/3: items={len(page['items'])} "
              f"pages={page['pages']}")

        # ── find_duplicates ────────────────────────────────────────────
        dupes = sm.invoices.find_duplicates(
            ["invoice_number", "supplier"],
            {"invoice_number": "INV-001", "supplier": "Acme AB"},
        )
        print(f"  find_duplicates(INV-001, Acme AB) → {len(dupes)}")

        # ── delete ─────────────────────────────────────────────────────
        ok = sm.delete("invoices", inv1["id"])
        print(f"\n  Delete inv1: {ok}")
        print(f"  Invoices after delete: {sm.invoices.count()}")

        # ── singleton ──────────────────────────────────────────────────
        sm2 = StorageManager(tmp)
        print(f"  Singleton: same instance = {sm is sm2}")

        # ── schema-assertions ──────────────────────────────────────────
        schema = get_schema("invoices")
        for key_ in ("invoice_type", "payment_date", "amount_ex_vat"):
            assert key_ in schema, f"{key_} missing!"
        settings_schema = get_schema("settings")
        for key_ in ("start_minimized", "close_to_tray", "startup"):
            assert key_ in settings_schema, f"{key_} missing!"
        print("  Schema assertions: ✅")

        # ── export_json sorterad ───────────────────────────────────────
        exported_list = json.loads(sm.invoices.export_json())
        if len(exported_list) >= 2:
            assert (
                _timestamp_sort_key(exported_list[-1])
                >= _timestamp_sort_key(exported_list[0])
            ), "export_json sorteringsfel!"
            print("  export_json(): senast ändrad sist  ✅")

    print("\n✅  självtest klart.")
    print("    Fil: FakturaRäknaren_/ui/core/storage.py")
