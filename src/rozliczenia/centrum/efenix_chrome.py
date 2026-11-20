from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from rozliczenia import efenix_browser
from rozliczenia.centrum.process_kind import EfenixOpening
from rozliczenia.efenix_pace import Pace

EFENIX_URL: Final = "https://efenix.pl/index.php"


@dataclass(frozen=True)
class EfenixWindow:
    url: str
    profile: Path
    channel: str | None = "chrome"
    headless: bool = False
    arguments: tuple[str, ...] = ()
    pace: Pace | None = Pace()

    @classmethod
    def of_tata(cls) -> EfenixWindow:
        return cls(EFENIX_URL, efenix_browser.default_profile())

    def opening(self) -> EfenixOpening:
        return EfenixOpening(
            lambda login: efenix_browser.chrome(
                self.url, self.profile, login, channel=self.channel, headless=self.headless, arguments=self.arguments
            ),
            self.pace,
        )


def atrapa_opening(url: str) -> EfenixOpening:
    return EfenixOpening(lambda _login: efenix_browser.chromium(url), pace=None)
