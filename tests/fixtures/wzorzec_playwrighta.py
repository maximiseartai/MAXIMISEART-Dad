"""Chromium Playwrighta bez ``launch_options``: wzorzec, z którym test porównuje przeglądarkę okna efenix.

Jedyny goły start przeglądarki w testach, z prawem właściciela w ``ignores:`` reguły ``przegladarka-bez-launch-options``:
ta przeglądarka nie otwiera żadnej strony, więc losowanie portu lokalnego na Windows jej nie dotyczy.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, sync_playwright


@contextmanager
def plain_chromium() -> Iterator[Browser]:
    """Chromium z samymi argumentami Playwrighta i ``--enable-automation``, które odblokowuje
    ``Browser.getBrowserCommandLine``; zamyka się razem z Playwrightem."""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--enable-automation"])
        try:
            yield browser
        finally:
            browser.close()
