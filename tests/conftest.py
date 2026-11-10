"""Shared test helpers for behavior that is unrelated to filesystem timing."""
from __future__ import annotations

import pytest


_WATCH_TEST_MODULES = {
    "test_watch_folders",
    "test_invoice_payment_details",
    "test_match_ask_wheel",
    "test_multipage_confirm_learn",
}


@pytest.fixture(autouse=True)
def _skip_watch_quiet_wait_in_unrelated_tests(monkeypatch, request):
    """Keep existing invoice-parsing tests deterministic and fast.

    The dedicated stability test opts back into a nonzero quiet interval.
    """
    module_name = request.module.__name__.rsplit(".", 1)[-1]
    if module_name not in _WATCH_TEST_MODULES:
        return
    try:
        import ui.watch_folders as watch_folders
    except (ImportError, OSError):
        return
    monkeypatch.setattr(watch_folders, "FILE_STABILITY_SECONDS", 0.0)
