"""Komunikat: bezpieczny tekst dla taty w trzech częściach i jedyny błąd zatrzymania, który go niesie.

Katalogi procesów (``preparation_messages``, ``settlement_messages``) i
katalog startu Centrum rozliczeń (``centrum.start_problems``) są tylko treścią:
każda ich fabryka zwraca ``Message``. Zatrzymanie Uruchomienia procesu to
``raise StopError(katalog.fabryka(...))``.

Trzy części nie zawierają pełnych ścieżek, treści wyjątków, adresów ani treści
wierszy; wskazują tylko nazwę pliku, folder, arkusz, kolumnę, wiersz albo
Wykonawcę. Wyjątkiem jest Zatrzymanie o brakach w ``SKUTECZNE``
(``preparation_messages.invalid_successful_values``): pokazuje dokładną
zawartość komórki innej niż ``tak`` i ``nie``, żeby tata od razu widział, co
poprawić. Kod jest unikalny w obrębie katalogu procesu: w
``tests/test_instrukcja_taty.py`` każdy kod katalogu ma dokładnie jeden cytat
instrukcji taty, a każdy cytat wskazuje dokładnie jeden kod. Typ zwracany przez
każdą fabrykę pilnuje mypy (tryb strict obejmuje testy).

Moduł używa tylko biblioteki standardowej, bo Komunikat startu Centrum o
brakującej bibliotece musi działać bez zależności.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Final, Literal

DadFile = Literal["order_register", "collective_file"]
"""Plik taty, który Komunikat każe poprawić: Rejestr zleceń albo Plik zbiorczy."""

REPORT_TO_MAINTAINER: Final = "Przekaż ten komunikat osobie utrzymującej narzędzie."
KEEP_ON_DEVICE: Final = (
    "W Eksploratorze plików kliknij ten plik prawym przyciskiem myszy, wybierz „Zawsze zachowuj na tym urządzeniu”, "
    "poczekaj, aż się pobierze,"
)
"""Jak tata pobiera plik, który OneDrive trzyma tylko w chmurze; Komunikat kończy to zdanie swoim „i …”."""
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")
_CONDITIONS: Final = ("jeśli", "w innym wypadku")


@dataclass(frozen=True)
class Message:
    """Komunikat: co się stało, gdzie, co zrobić, z kodem unikalnym w katalogu procesu.

    ``dad_file``: plik taty, w którym jest poprawka z „Co zrobić”, gdy otwarcie go pomaga; odcisk problemu
    go nie zawiera.
    """

    code: str
    what: str
    where: str
    action: str
    dad_file: DadFile | None = None

    @property
    def text(self) -> str:
        return f"Co się stało: {self.what}\nGdzie: {self.where}\nCo zrobić: {self.action}"

    @property
    def reports_to_maintainer(self) -> bool:
        """„Co zrobić” bezwarunkowo każe przekazać Komunikat osobie utrzymującej narzędzie.

        Zdanie warunkowe („Jeśli błąd wraca, przekaż…”, „W innym wypadku przekaż…”)
        nie liczy się: najpierw tata ponawia albo poprawia sam.
        """

        return any(_unconditional_referral(sentence) for sentence in _SENTENCE_END.split(self.action))


class StopError(Exception):
    """Zatrzymanie Uruchomienia procesu z Komunikatem z katalogu procesu.

    Treść dla taty jest w ``message``, nigdy w ``str(error)`` (ADR 0004):
    ``str(error)`` to sam kod Komunikatu, więc zapis wyjątku do logu nie
    przenosi treści Komunikatu. ``facts``: fakty Zatrzymania dla Logów
    Uruchomienia, które zna tylko proces (np. ``efenix_pricing.PricingStopped``),
    bez danych klientów; ``None``, gdy proces ich nie daje.
    """

    def __init__(self, message: Message, *, facts: object = None) -> None:
        super().__init__(message.code)
        self.message = message
        self.facts = facts


def _unconditional_referral(sentence: str) -> bool:
    lowered = sentence.lower()
    refers = "przekaż" in lowered and "osobie utrzymującej narzędzie" in lowered
    return refers and not any(condition in lowered for condition in _CONDITIONS)


def file_label(path: Path) -> str:
    """Plik z folderem, w którym leży, bez pełnej ścieżki, np. ``plik a.xlsx, folder config``."""

    return f"plik {path.name}, folder {path.parent.name}" if path.parent.name else f"plik {path.name}"


def folder_label(directory: Path) -> str:
    """Folder z folderem nadrzędnym, bez pełnej ścieżki, np. ``folder INEA\\08_14_09_2026``."""

    return f"folder {directory.parent.name}\\{directory.name}" if directory.parent.name else f"folder {directory.name}"
