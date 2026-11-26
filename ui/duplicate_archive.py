"""Arkiv-flyttningshjälp — Qt-fri modul.

Användarkrav som här kodas:

* Besked 20: en dubblett vid import ALDRIG importeras — den
  arkiveras i egen undermapp ``dubbletter/`` bredvid filen.
* Besked 24: fakturor som markerats BETALDA får sina original
  årssorterade — ``Arkiv/<fakturadatumets år>/``.

Modulen har inga Qt-beroenden så beteendet kan testas funktionellt.
"""

from __future__ import annotations

import datetime
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("watch_folders")

#: Namnet på den egna undermappen för arkiverade dubbletter.
#: Motsvarar Arkiv/-konventionen: mappen hoppas över av alla skanningar.
DUPLICATE_FOLDER_NAME = "dubbletter"


#: Namnet på arkivmappen för betalda original (användarkrav 24).
PAID_ARCHIVE_FOLDER_NAME = "Arkiv"


def paid_archive_year(invoice_date: str, path: Path) -> str:
    """Fakturadatumets år (YYYY) — fallback: filens ändringstid."""
    raw = str(invoice_date or "").strip()
    if raw:
        try:
            return f"{datetime.datetime.fromisoformat(raw[:10]).year:04d}"
        except (TypeError, ValueError):
            pass
    try:
        return str(datetime.datetime.fromtimestamp(
            path.stat().st_mtime
        ).year)
    except (OSError, OverflowError, ValueError):
        return ""


def sort_paid_original_into_year_folder(
    path: Path | str, invoice_date: str = "",
) -> str:
    """Flyttar en betald fakturas original till ``Arkiv/<år>/``.

    Året = fakturadatumets år (fallback: filens ändringstid).
    Namnkrockar löses med `` (2)``, `` (3)`` … Returnerar den nya
    vägen, eller "" om flytten misslyckades (filen stannar kvar).
    """
    src = Path(path)
    if not src.is_file():
        return ""
    year = paid_archive_year(invoice_date, src)
    if not year.isdigit() or not 1900 <= int(year) <= 9999:
        return ""
    try:
        dest_dir = src.parent / PAID_ARCHIVE_FOLDER_NAME / year
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{src.stem} ({counter}){src.suffix}"
            counter += 1
        shutil.move(str(src), str(dest))
        logger.info(
            "Betalda fakturans original årssorterat: %s -> %s",
            src.name, dest,
        )
        return str(dest)
    except Exception as exc:
        logger.warning("Kunde inte årssortera %s: %s", src, exc)
        return ""


def _inside_duplicate_folder(src: Path) -> bool:
    """Sant när filen redan ligger under en dubbletter/-mapp."""
    return any(
        part.lower() == DUPLICATE_FOLDER_NAME for part in src.parts[:-1]
    )


def archive_duplicate_copy(
    path: Path | str, invoice_date: str = "",
) -> str:
    """Flyttar en dubblettkopia till ``dubbletter/<årsarkiv>/``.

    Användarkrav (besked 25): EN dubbletter/-mapp per nivå, med
    årsundermappar (``dubbletter/<fakturadatumets år>/``) — aldrig
    kapslade ``dubbletter/dubbletter/…``. Ligger filen redan under
    en dubbletter/-mapp görs INGEN ny flytt (den är redan arkiverad;
    vägen returneras oförändrad) — därmed kan upprepade skannings-
    rundor aldrig flytta den djupare. Året = fakturadatumets år
    (fallback: filens ändringstid). Namnkrockar löses med
    `` (2)``, `` (3)`` … så ingen fil någonsin skrivs över. Vid fel
    stannar filen kvar och returneras "".
    """
    src = Path(path)
    if _inside_duplicate_folder(src):
        # Redan arkiverad — flytta ALDRIG djupare (besked 25).
        logger.debug(
            "Dubbletten %s är redan arkiverad — lämnas oförändrad",
            src,
        )
        return str(src)
    try:
        year = paid_archive_year(invoice_date, src)
        if not year.isdigit() or not 1900 <= int(year) <= 9999:
            year = "okänt-år"
        dest_dir = src.parent / DUPLICATE_FOLDER_NAME / year
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{src.stem} ({counter}){src.suffix}"
            counter += 1
        shutil.move(str(src), str(dest))
        logger.info(
            "Dubblett arkiverad: %s -> %s", src.name, dest,
        )
        return str(dest)
    except Exception as exc:
        logger.warning(
            "Kunde inte arkivera dubbletten %s: %s", src, exc,
        )
        return ""
