"""Chromium Playwrighta dla testów, które prowadzą prawdziwą przeglądarkę (Wycena w efenix na Atrapie efenix).

Plan CI instaluje Chromium w zadaniu pytest, którego plik testów sięga Atrapy efenix (``PRZEGLADARKA`` w
``tools/lib/zakres_runu.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, Page, sync_playwright

from rozliczenia.efenix_browser import launch_options


@contextmanager
def chromium() -> Iterator[Browser]:
    """Chromium bez okna na czas bloku, z argumentami okna efenix; zamyka się razem z Playwrightem."""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options(playwright))
        try:
            yield browser
        finally:
            browser.close()


@contextmanager
def page_of(browser: Browser, *, java_script: bool = True) -> Iterator[Page]:
    """Nowa karta w osobnym kontekście (bez ciasteczek i pamięci innych testów), bez JavaScriptu przy ``java_script``
    ``False``."""

    context = browser.new_context(java_script_enabled=java_script)
    try:
        yield context.new_page()
    finally:
        context.close()
