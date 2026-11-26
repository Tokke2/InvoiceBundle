"""Arkivering av dubblettkopior — Qt-fri hjälpmodul.

Användarkrav (besked 20): när en dubblett känns av vid import ska
den ALDRIG importeras — den arkiveras i en egen undermapp
``dubbletter/`` bredvid filen. Modulen har inga Qt-beroenden så
beteendet kan testas funktionellt i sandlådan.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("watch_folders")

#: Namnet på den egna undermappen för arkiverade dubbletter.
#: Motsvarar Arkiv/-konventionen: mappen hoppas över av alla skanningar.
DUPLICATE_FOLDER_NAME = "dubbletter"


def archive_duplicate_copy(path: Path | str) -> str:
    """Flyttar en dubblettkopia till undermappen ``dubbletter/``.

    Filen flyttas till en undermapp bredvid sig själv (skapas vid
    behov). Namnkrockar löses med `` (2)``, `` (3)`` … så ingen fil
    någonsin skrivs över. Vid fel stannar filen kvar och returneras
    "" (uppringaren behåller då tidigare beteende: hoppa över, logga).
    """
    src = Path(path)
    try:
        dest_dir = src.parent / DUPLICATE_FOLDER_NAME
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
