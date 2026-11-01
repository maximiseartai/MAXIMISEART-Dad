"""Chromium Playwrighta dla testów, które prowadzą prawdziwą przeglądarkę (Wycena w efenix na Atrapie efenix).

Plan CI instaluje Chromium w zadaniu pytest, którego plik testów sięga Atrapy efenix (``PRZEGLADARKA`` w
``tools/lib/zakres_runu.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, Page, sync_playwright


@contextmanager
def chromium() -> Iterator[Browser]:
    """Chromium bez okna na czas bloku; zamyka się razem z Playwrightem."""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@contextmanager
def page_of(browser: Browser) -> Iterator[Page]:
    """Nowa karta w osobnym kontekście (bez ciasteczek i pamięci innych testów)."""

    context = browser.new_context()
    try:
        yield context.new_page()
    finally:
        context.close()
