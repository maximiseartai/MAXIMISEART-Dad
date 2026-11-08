"""Okno efenix, które gospodarz daje Wycenie w efenix: Chrome taty w Centrum albo Chromium na Atrapie efenix.

W Centrum taty to widoczne okno zainstalowanego Google Chrome w trwałym profilu narzędzia
(``efenix_browser.default_profile``), w którym proces czeka, aż tata się zaloguje, i pracuje w tempie ludzkim. Testy i
weryfikacja podają Centrum Chromium Playwrighta, adres Atrapy efenix i okno bez tempa, a Skrypt dla maszyn i odtworzenie
otwierają nowe Chromium bez sesji taty i bez tempa (``atrapa_opening``), bo biegną tylko na Atrapie efenix (ADR 0024).

To jedyny moduł Centrum, który wczytuje przeglądarkę (``efenix_browser``): katalog procesów dostaje gotowe
``process_kind.EfenixOpening``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from rozliczenia import efenix_browser
from rozliczenia.centrum.process_kind import EfenixOpening
from rozliczenia.efenix_pace import Pace

EFENIX_URL: Final = "https://efenix.pl/index.php"
"""Lista zleceń prawdziwego efenix, którą otwiera tylko Centrum taty; testy i weryfikacja podają adres Atrapy efenix."""


@dataclass(frozen=True)
class EfenixWindow:
    """Okno efenix, które Centrum otwiera dla Wyceny w efenix: adres listy zleceń, profil, przeglądarka i tempo ludzkie
    (``efenix_pace``).

    ``channel`` ``"chrome"`` to zainstalowany Google Chrome, ``None`` Chromium Playwrighta; ``headless`` i ``arguments``
    są tylko dla testów i weryfikacji, które nie mają ekranu, a ``pace`` ``None`` (bez przerw) tylko dla Atrapy efenix.
    """

    url: str
    profile: Path
    channel: str | None = "chrome"
    headless: bool = False
    arguments: tuple[str, ...] = ()
    pace: Pace | None = Pace()

    @classmethod
    def of_tata(cls) -> EfenixWindow:
        """Widoczne okno Google Chrome taty w profilu narzędzia z prawdziwym efenix, w tempie ludzkim."""

        return cls(EFENIX_URL, efenix_browser.default_profile())

    def opening(self) -> EfenixOpening:
        return EfenixOpening(
            lambda login: efenix_browser.chrome(
                self.url, self.profile, login, channel=self.channel, headless=self.headless, arguments=self.arguments
            ),
            self.pace,
        )


def atrapa_opening(url: str) -> EfenixOpening:
    """Nowe Chromium Playwrighta bez okna i bez sesji taty na liście zleceń ``url`` Atrapy efenix, bez tempa ludzkiego."""

    return EfenixOpening(lambda _login: efenix_browser.chromium(url), pace=None)
