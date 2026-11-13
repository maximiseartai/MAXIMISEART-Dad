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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

DadFile = Literal["order_register", "collective_file"]
"""Plik taty, który Komunikat każe poprawić: Rejestr zleceń albo Plik zbiorczy."""

SettingsSection = Literal["wykonawcy"]
"""Sekcja okna Ustawień Centrum, w której jest poprawka z „Co zrobić”: Wykonawcy (Lista Wykonawców)."""

_MAINTAINER: Final = "osobie utrzymującej narzędzie"
KEEP_ON_DEVICE: Final = (
    "W Eksploratorze plików kliknij ten plik prawym przyciskiem myszy, wybierz „Zawsze zachowuj na tym urządzeniu”, "
    "poczekaj, aż się pobierze,"
)
"""Jak tata pobiera plik, który OneDrive trzyma tylko w chmurze; Komunikat kończy to zdanie swoim „i …”."""


def explorer_check(folder: str, then: str, *, read_only: bool = False) -> str:
    """Zdanie o folderze, którego nie da się odczytać albo zapisać: Eksplorator plików i OneDrive, potem ``then``.

    ``folder``: jak zdanie nazywa folder („folder”, „jego folder”); ``read_only``: też „nie jest tylko do odczytu”,
    gdy w folderze trzeba zapisać.
    """

    writable = ", nie jest tylko do odczytu" if read_only else ""
    return f"Sprawdź, czy {folder} otwiera się w Eksploratorze plików{writable} i czy OneDrive działa, potem {then}."


@dataclass(frozen=True)
class Message:
    """Komunikat: co się stało, gdzie, co zrobić, z kodem unikalnym w katalogu procesu.

    ``dad_file``: plik taty, w którym jest poprawka z „Co zrobić”, gdy otwarcie go pomaga; odcisk problemu
    go nie zawiera.

    ``setting``: sekcja okna Ustawień Centrum, w której jest poprawka z „Co zrobić”; Centrum pokazuje przy Komunikacie
    link do niej, a odcisk problemu jej nie zawiera.

    ``reports_to_maintainer``: Rodzaj Zatrzymania „do Maksa”, bo „Co zrobić” bezwarunkowo każe przekazać Komunikat
    osobie utrzymującej narzędzie. Ustawia go tylko ``Message.to_maintainer``, który pisze też to zdanie; zdanie
    warunkowe (``refer_if``) rodzaju nie zmienia, bo najpierw tata ponawia albo poprawia sam.
    """

    code: str
    what: str
    where: str
    action: str
    dad_file: DadFile | None = None
    setting: SettingsSection | None = None
    reports_to_maintainer: bool = field(default=False, kw_only=True)

    @classmethod
    def to_maintainer(cls, code: str, what: str, where: str, *, before: str = "", check: str = "") -> Message:
        refer = f"Sprawdź {check} i przekaż" if check else "Przekaż"
        action = f"{refer} ten komunikat {_MAINTAINER}."
        return cls(code, what, where, f"{before} {action}" if before else action, reports_to_maintainer=True)

    @property
    def text(self) -> str:
        return f"Co się stało: {self.what}\nGdzie: {self.where}\nCo zrobić: {self.action}"


def refer_if(condition: str, *, request: str = "przekaż ten komunikat", then: str = "") -> str:
    """Zdanie „Co zrobić”, które kieruje do osoby utrzymującej narzędzie dopiero pod warunkiem, np. gdy błąd wraca.

    Np. ``refer_if("Jeśli komunikat wraca", request="przekaż go")``. Rodzaju Zatrzymania nie zmienia.
    """

    return f"{condition}, {request} {_MAINTAINER}{then}."


IF_ERROR_RETURNS: Final = refer_if("Jeśli błąd wraca")
OTHERWISE_REFER: Final = f"W innym wypadku przekaż ten komunikat {_MAINTAINER}."
"""Skierowanie, gdy tata nie usunie przyczyny sam krokami z poprzedniego zdania; rodzaju nie zmienia jak ``refer_if``."""


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


def file_label(path: Path) -> str:
    """Plik z folderem, w którym leży, bez pełnej ścieżki, np. ``plik a.xlsx, folder config``."""

    return f"plik {path.name}, folder {path.parent.name}" if path.parent.name else f"plik {path.name}"


def folder_label(directory: Path) -> str:
    """Folder z folderem nadrzędnym, bez pełnej ścieżki, np. ``folder INEA\\08_14_09_2026``."""

    return f"folder {directory.parent.name}\\{directory.name}" if directory.parent.name else f"folder {directory.name}"
