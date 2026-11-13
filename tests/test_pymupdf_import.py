# -*- coding: utf-8 -*-
"""PyMuPDF uses its current name, with a fallback for older installations."""
from __future__ import annotations

import builtins
import runpy
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for directory in (ROOT, ROOT / "plugins"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


@pytest.mark.parametrize("available", ["modern", "legacy", "neither"])
def test_scan_import_selects_the_available_pymupdf_api(monkeypatch, available):
    """Test actual imports rather than merely looking for text in the source."""
    original_import = builtins.__import__
    modern = types.ModuleType("pymupdf")
    legacy = types.ModuleType("fitz")
    calls = []

    def import_selected(name, *args, **kwargs):
        if name in ("pymupdf", "fitz"):
            calls.append(name)
            if name == "pymupdf" and available == "modern":
                return modern
            if name == "fitz" and available == "legacy":
                return legacy
            raise ImportError(f"Simulated missing {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_selected)
    module = runpy.run_path(str(ROOT / "plugins" / "scan_import.py"))
    if available == "modern":
        assert module["HAS_FITZ"] is True
        assert module["fitz"] is modern
        assert calls == ["pymupdf"]
    elif available == "legacy":
        assert module["HAS_FITZ"] is True
        assert module["fitz"] is legacy
        assert calls == ["pymupdf", "fitz"]
    else:
        assert module["HAS_FITZ"] is False
        assert calls == ["pymupdf", "fitz"]


@pytest.mark.parametrize("available", ["modern", "legacy"])
def test_invoice_page_count_uses_modern_api_or_legacy_fallback(
    monkeypatch, tmp_path, available
):
    from ui.invoices_helpers import attachment_page_count

    class Document:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def __len__(self):
            return 3

    modern = types.ModuleType("pymupdf")
    legacy = types.ModuleType("fitz")
    modern.open = legacy.open = lambda _path: Document()
    original_import = builtins.__import__
    calls = []

    def import_selected(name, *args, **kwargs):
        if name in ("pymupdf", "fitz"):
            calls.append(name)
            if name == "pymupdf" and available == "modern":
                return modern
            if name == "fitz" and available == "legacy":
                return legacy
            raise ImportError(f"Simulated missing {name}")
        return original_import(name, *args, **kwargs)

    pdf = tmp_path / "faktura.pdf"
    pdf.write_bytes(b"%PDF-placeholder")
    monkeypatch.setattr(builtins, "__import__", import_selected)
    assert attachment_page_count(pdf) == 3
    expected = ["pymupdf"] if available == "modern" else ["pymupdf", "fitz"]
    assert calls == expected


def test_real_pymupdf_pdf_can_still_be_counted_and_rendered(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    import scan_import
    from ui.invoices_helpers import attachment_page_count

    pdf = tmp_path / "faktura.pdf"
    document = pymupdf.open()
    for title in ("Faktura sida ett", "Faktura sida tva"):
        document.new_page().insert_text((40, 60), title)
    document.save(pdf)
    document.close()

    assert scan_import.HAS_FITZ is True
    assert scan_import.fitz is pymupdf
    assert scan_import.page_image_count(pdf) == 2
    assert attachment_page_count(pdf) == 2
    image = scan_import.render_page_image(pdf, page_index=1, dpi=72)
    assert image is not None and image.startswith(b"\x89PNG\r\n\x1a\n")


def test_new_process_does_not_emit_deprecated_fitz_warning():
    """The startup warning must not reappear just because a module was cached."""
    pytest.importorskip("pymupdf")
    code = """
import sys, warnings
sys.path.insert(0, sys.argv[1])
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always')
    import scan_import
assert scan_import.HAS_FITZ and scan_import.fitz.__name__ == 'pymupdf'
assert not any('fitz' in str(w.message).lower() and
               'deprecated' in str(w.message).lower() for w in caught), caught
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "plugins")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
