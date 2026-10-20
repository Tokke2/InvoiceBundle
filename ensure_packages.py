"""
Fakturabunten — saknade Python-tillbehör
==========================================
Körs vid start, före PySide6. Installerar eller uppdaterar bara det
som saknas eller är för gammalt mot requirements.txt. Visar en
förloppsindikator. Skriver inget utanför appmappens logg.

Copyright © dynamiskt år Rickard Längkvist
"""

from __future__ import annotations

import datetime
import importlib.metadata as metadata
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("FakturaMain")

BASE_DIR = Path(__file__).resolve().parent
REQUIREMENTS = BASE_DIR / "requirements.txt"

#: (distributionsnamn, importnamn) när de skiljer sig.
_IMPORT_NAME = {
    "PySide6": "PySide6",
    "reportlab": "reportlab",
    "pypdf": "pypdf",
    "PyMuPDF": "pymupdf",
    "Pillow": "PIL",
}


def _parse_requirement(line: str) -> tuple[str, tuple[int, ...]] | None:
    """'PySide6>=6.6' → ('PySide6', (6, 6))."""
    text = line.split("#", 1)[0].strip()
    if not text or text.startswith("-"):
        return None
    match = re.match(r"^([A-Za-z0-9_.-]+)\s*>=\s*([0-9][0-9.]*)$", text)
    if not match:
        name = re.split(r"[<>=!\s]", text, maxsplit=1)[0].strip()
        return (name, ()) if name else None
    parts = tuple(int(p) for p in match.group(2).split(".") if p.isdigit())
    return match.group(1), parts


def _installed_version(dist_name: str) -> tuple[int, ...] | None:
    try:
        raw = metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return None
    except Exception:
        return None
    nums = tuple(int(p) for p in raw.split(".") if p.isdigit())
    return nums or (0,)


def _importable(dist_name: str) -> bool:
    name = _IMPORT_NAME.get(dist_name, dist_name)
    try:
        __import__(name)
        return True
    except Exception:
        return False


def packages_needed() -> list[tuple[str, str]]:
    """
    Paket som måste installeras eller uppdateras.

    Returnerar (namn, orsak) där orsak är 'saknas' eller 'för gammal'.
    """
    if not REQUIREMENTS.is_file():
        return []
    needed: list[tuple[str, str]] = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        parsed = _parse_requirement(line)
        if not parsed:
            continue
        name, minimum = parsed
        current = _installed_version(name)
        can_import = _importable(name)
        if not can_import:
            needed.append((name, "saknas"))
            continue
        # Import fungerar men versionsdata saknas → inte saknad.
        if current is None:
            continue
        if minimum and current < minimum:
            needed.append((name, "för gammal"))
    return needed


def _site_writable() -> bool:
    try:
        import site
        paths = site.getsitepackages()
    except Exception:
        return False
    for path in paths:
        probe = Path(path)
        if probe.exists() and os.access(probe, os.W_OK):
            return True
    return False


def _pip_base() -> list[str]:
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check", "--upgrade",
    ]
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if not in_venv and not _site_writable():
        cmd.append("--user")
    return cmd


def _refresh_import_path() -> None:
    try:
        import site
        site.main()
        user = site.getusersitepackages()
        if user and user not in sys.path:
            sys.path.append(user)
    except Exception:
        pass
    importlib_invalidate()


def importlib_invalidate() -> None:
    import importlib
    importlib.invalidate_caches()


class _Progress:
    """Mörk förloppsruta. Tkinter följer med Python, så den syns före PySide6."""

    def __init__(self, total: int) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self.root = tk.Tk()
        self.root.title("Fakturabunten — tillbehör")
        self.root.configure(bg="#0c1218")
        self.root.resizable(False, False)
        self.root.geometry("520x168")
        self._center()
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        tk.Label(
            self.root,
            text="Installerar saknade tillbehör",
            bg="#0c1218",
            fg="#f4f7fb",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=18, pady=(16, 4))

        self.status = tk.StringVar(value="Förbereder…")
        tk.Label(
            self.root,
            textvariable=self.status,
            bg="#0c1218",
            fg="#f4f7fb",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(fill="x", padx=18)

        self.detail = tk.StringVar(value="")
        tk.Label(
            self.root,
            textvariable=self.detail,
            bg="#0c1218",
            fg="#d5deea",
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(2, 8))

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Gold.Horizontal.TProgressbar",
            troughcolor="#1c2836",
            background="#e8b030",
            bordercolor="#1c2836",
            lightcolor="#e8b030",
            darkcolor="#e8b030",
        )
        self.bar = ttk.Progressbar(
            self.root,
            style="Gold.Horizontal.TProgressbar",
            mode="determinate",
            maximum=max(total, 1),
            length=480,
        )
        self.bar.pack(padx=18, pady=(0, 16))
        self.root.update_idletasks()
        self.root.update()

    def _center(self) -> None:
        self.root.update_idletasks()
        w, h = 520, 168
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def set(self, value: float, status: str, detail: str = "") -> None:
        self.bar.stop()
        self.bar.configure(mode="determinate")
        self.bar["value"] = value
        self.status.set(status)
        self.detail.set(detail[:90])
        self.root.update_idletasks()
        self.root.update()

    def pulse(self, status: str, detail: str = "") -> None:
        if str(self.bar["mode"]) != "indeterminate":
            self.bar.configure(mode="indeterminate")
            self.bar.start(12)
        self.status.set(status)
        self.detail.set(detail[:90])
        self.root.update_idletasks()
        self.root.update()

    def close(self) -> None:
        try:
            self.bar.stop()
            self.root.destroy()
        except Exception:
            pass


def _run_pip(cmd: list[str], progress: _Progress | None, status: str) -> int:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        if progress is not None:
            progress.pulse(status, line)
        else:
            print(line, flush=True)
    return proc.wait()


def _append_log(message: str) -> None:
    try:
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (log_dir / "app.log").open("a", encoding="utf-8") as fh:
            fh.write(
                '{"ts": "%s", "level": "INFO", "logger": "FakturaMain", '
                '"action": "TILLBEHOR", "msg": "%s"}\n'
                % (stamp, message.replace('"', "'"))
            )
    except Exception:
        pass


def ensure_packages(*, force_console: bool = False) -> bool:
    """
    Installerar saknade tillbehör. True om appen kan fortsätta.

    Visar förloppsindikator bara när något faktiskt ska hämtas.
    """
    needed = packages_needed()
    if not needed:
        log.info("TILLBEHOR: alla krav uppfyllda")
        return True

    names = ", ".join(f"{n} ({why})" for n, why in needed)
    log.info("TILLBEHOR_SAKNAS: %s", names)
    _append_log(f"TILLBEHOR_SAKNAS: {names}")

    progress: _Progress | None = None
    if not force_console:
        try:
            progress = _Progress(len(needed))
        except Exception as exc:
            log.warning("TILLBEHOR: ingen ruta (%s) — textläge", exc)
            progress = None

    ok = True
    try:
        for index, (name, why) in enumerate(needed, start=1):
            status = f"{index}/{len(needed)}  {name}  ({why})"
            if progress is not None:
                progress.set(index - 1, status, "Hämtar…")
            cmd = _pip_base() + [name]
            log.info("TILLBEHOR_PIP: %s", " ".join(cmd))
            code = _run_pip(cmd, progress, status)
            if code != 0:
                ok = False
                log.error("TILLBEHOR_FEL: %s exit %s", name, code)
                if progress is not None:
                    progress.set(index, f"Misslyckades: {name}", f"pip avslutade med kod {code}")
            else:
                if progress is not None:
                    progress.set(index, status, "Klart")
        _refresh_import_path()
    finally:
        if progress is not None:
            if ok:
                progress.set(len(needed), "Klart", "Startar programmet…")
            progress.close()

    still = packages_needed()
    if still:
        missing = ", ".join(n for n, _ in still)
        _append_log(f"TILLBEHOR_KVAR: {missing}")
        log.error("TILLBEHOR_KVAR: %s", missing)
        _tell_user(
            "Tillbehör saknas",
            "De här kunde inte installeras:\n\n"
            f"{missing}\n\n"
            "Kontrollera internet och försök starta igen.\n"
            f"Logg: {BASE_DIR / 'logs' / 'app.log'}",
        )
        return False

    _append_log("TILLBEHOR_OK: " + ", ".join(n for n, _ in needed))
    log.info("TILLBEHOR_OK")
    return True


def _tell_user(title: str, text: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, text)
        root.destroy()
        return
    except Exception:
        pass
    print(f"{title}\n{text}", file=sys.stderr)


