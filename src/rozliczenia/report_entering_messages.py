"""Katalog Komunikatów Wpisania raportów dla taty (zasady treści: zob. ``message``, ADR 0028).

Komunikaty o samym INTERMAX (brak, Excel, OneDrive, nieudany zapis) daje ``intermax_messages`` z ``ENTERING``, tak jak
w Uporządkowaniu INTERMAX. Tu są Komunikaty o Skrzynce raportów, pamięci własnych wpisów, decyzjach
„Zostaw moją” i zapisie komórek. Żaden nie zawiera hasła aplikacji, adresu skrzynki ani nadawcy, tematu ani treści maila, numeru zlecenia ani
loginu Wykonawcy: pliki w ``config`` prowadzi Maks, więc każda ich usterka idzie do niego.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from .message import IF_ERROR_RETURNS, Message, explorer_check, file_label, folder_label
from .tool_files import REPORT_ENTERING_DECISIONS, REPORT_ENTERING_STATE
from .worker_report_inbox import INBOX_ACCESS_FILE

_PROCESS: Final = "Wpisanie raportów"
_UNCHANGED: Final = "INTERMAX nie został zmieniony."
_INBOX: Final = "skrzynka raportów w Gmailu"
_ACCESS: Final = file_label(Path("config") / INBOX_ACCESS_FILE)
_STATE: Final = file_label(Path("config") / REPORT_ENTERING_STATE)
_DECISIONS: Final = file_label(Path("config") / REPORT_ENTERING_DECISIONS)


def inbox_access_missing() -> Message:
    """Pliku dostępu do Skrzynki raportów nie ma albo nie ma w nim adresu i hasła aplikacji."""

    return Message.to_maintainer(
        code="RAPORTY_BRAK_DOSTEPU_DO_SKRZYNKI",
        what=f"Skrzynka raportów nie jest jeszcze ustawiona, więc maili nie przeczytano. {_UNCHANGED}",
        where=_ACCESS,
    )


def inbox_access_unreadable() -> Message:
    """Plik dostępu do Skrzynki raportów ma treść, której narzędzie nie umie przeczytać."""

    return Message.to_maintainer(
        code="RAPORTY_NIECZYTELNY_DOSTEP_DO_SKRZYNKI",
        what=f"Nie można odczytać ustawień skrzynki raportów, więc maili nie przeczytano. {_UNCHANGED}",
        where=_ACCESS,
    )


def password_rejected() -> Message:
    """Gmail odrzucił hasło aplikacji: nowe hasło może dać tylko Maks (spec #1224, US 47)."""

    return Message.to_maintainer(
        code="RAPORTY_HASLO_ODRZUCONE",
        what=f"Skrzynka raportów odrzuciła hasło, Maks musi je odnowić. Maili nie przeczytano. {_UNCHANGED}",
        where=_INBOX,
    )


def inbox_unreachable() -> Message:
    """Skrzynki raportów nie dało się teraz przeczytać (sieć, Gmail): tata ponawia sam, bez Zgłoszenia (US 49)."""

    return Message(
        code="RAPORTY_SKRZYNKA_NIEDOSTEPNA",
        what=f"Nie udało się połączyć ze skrzynką raportów. {_UNCHANGED}",
        where=_INBOX,
        action=f"Spróbuj za chwilę: sprawdź połączenie z internetem i kliknij jeszcze raz. {IF_ERROR_RETURNS}",
    )


CONFLICT_ACTION: Final = (
    "Otwórz w Excelu INTERMAX i tę kopię, przepisz do INTERMAX zmiany, których w nim brakuje, zapisz go i usuń kopię."
)
"""Co tata robi z kopią konfliktu OneDrive obok INTERMAX: w Komunikacie i na ekranie Raporty."""


def conflict_copy(copy: Path) -> Message:
    """Obok INTERMAX leży kopia konfliktu OneDrive ``copy``: dwie wersje INTERMAX, więc kliknięcie niczego nie czyta."""

    return Message(
        code="RAPORTY_KOPIA_KONFLIKTU",
        dad_file="order_register",
        what=f"Obok INTERMAX leży kopia konfliktu OneDrive, więc maili nie przeczytano. {_UNCHANGED}",
        where=file_label(copy),
        action=f"{CONFLICT_ACTION} Potem kliknij jeszcze raz.",
    )


def conflict_after_save(copy: Path) -> Message:
    """Po zapisie obok INTERMAX pojawiła się kopia konfliktu OneDrive ``copy``: ktoś zmieniał INTERMAX w tym samym
    czasie, a raporty są już wpisane."""

    return Message(
        code="RAPORTY_KOPIA_KONFLIKTU_PO_ZAPISIE",
        dad_file="order_register",
        what="Raporty zostały wpisane, ale obok INTERMAX pojawiła się kopia konfliktu OneDrive: ktoś zmieniał INTERMAX "
        "w tym samym czasie.",
        where=file_label(copy),
        action=f"{CONFLICT_ACTION} Dopiero wtedy kliknij jeszcze raz.",
    )


def periods_directory_missing(periods_directory: Path) -> Message:
    """Folderu okresów z Ustawień Centrum nie ma: bez niego narzędzie nie wie, które okresy mają już Plik zbiorczy."""

    return Message(
        code="RAPORTY_BRAK_FOLDERU_OKRESOW",
        what=f"Nie znaleziono folderu okresów, więc maili nie przeczytano. {_UNCHANGED}",
        where=folder_label(periods_directory),
        action="Wskaż w Ustawieniach folder okresów, w którym są foldery tygodni, i kliknij jeszcze raz.",
    )


def periods_folder_inaccessible(folder: Path) -> Message:
    """Folderu okresów albo Folderu okresu nie da się odczytać (brak dostępu, OneDrive nie działa), więc narzędzie nie
    wie, czy okres ma już Plik zbiorczy."""

    return Message(
        code="RAPORTY_NIEDOSTEPNY_FOLDER_OKRESOW",
        what=f"Nie można teraz odczytać folderu okresów, więc maili nie przeczytano. {_UNCHANGED}",
        where=folder_label(folder),
        action=explorer_check("folder", "kliknij jeszcze raz"),
    )


def state_unreadable() -> Message:
    """Pamięci własnych wpisów nie da się odczytać: bez niej narzędzie nie odróżni własnego wpisu od ręcznego."""

    return Message.to_maintainer(
        code="RAPORTY_NIECZYTELNA_PAMIEC",
        what=f"Nie można odczytać pamięci wpisanych raportów. {_UNCHANGED}",
        where=_STATE,
    )


def decisions_unreadable() -> Message:
    """Decyzji „Zostaw moją” nie da się odczytać: bez nich wróciłyby różnice, które tata zostawił. Pamięć własnych wpisów
    jest poprawna, więc Komunikat jej nie wskazuje, a usunięcie pliku decyzji przywróciłoby różnice."""

    return Message.to_maintainer(
        code="RAPORTY_NIECZYTELNE_DECYZJE",
        what=f"Nie można odczytać decyzji „Zostaw moją”, więc maili nie przeczytano. {_UNCHANGED}",
        where=_DECISIONS,
        before="Nie usuwaj tego pliku: bez niego wrócą różnice, przy których kliknięto „Zostaw moją”.",
    )


def cells_rejected() -> Message:
    """Zapis komórek odrzucił zmiany rdzenia raportów: rdzeń i zapis się nie zgadzają, czyli błąd narzędzia."""

    return Message.to_maintainer(
        code="RAPORTY_ZMIANY_ODRZUCONE",
        what=f"Zapis odrzucił komórki, które narzędzie chciało wpisać. {_UNCHANGED}",
        where=_PROCESS,
    )


def unsupported_shape(register: Path, sheet: str) -> Message:
    """Komórka raportu ma formułę, leży w scaleniu albo wierszy arkusza nie da się rozdzielić."""

    return Message.to_maintainer(
        code="RAPORTY_NIEOBSLUGIWANY_UKLAD_INTERMAX",
        what=f"Zlecenia mają układ, do którego narzędzie nie wpisuje raportów. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}",
    )


def memory_not_saved() -> Message:
    """Ostrzeżenie: raporty są wpisane, ale pamięci wpisanych raportów nie udało się zapisać."""

    return Message(
        code="RAPORTY_PAMIEC_NIEZAPISANA",
        what="Raporty zostały wpisane, ale nie udało się zapisać pamięci wpisanych raportów.",
        where=_STATE,
        action=f"Nie musisz nic robić teraz: narzędzie zapisze ją przy następnym kliknięciu. {IF_ERROR_RETURNS}",
    )


def unexpected_failure() -> Message:
    """Nieprzewidziany błąd; treść wyjątku nie trafia do taty."""

    return Message(
        code="BLAD_NIEOCZEKIWANY",
        what=f"Wystąpił nieoczekiwany błąd. {_UNCHANGED}",
        where=_PROCESS,
        action=f"Kliknij jeszcze raz. {IF_ERROR_RETURNS}",
    )


def summary_not_shown() -> Message:
    """Raporty są wpisane, ale podsumowania nie dało się pokazać."""

    return Message.to_maintainer(
        code="BLAD_PODSUMOWANIA",
        what="Raporty zostały wpisane, ale nie udało się pokazać podsumowania.",
        where=_PROCESS,
        check="INTERMAX",
    )
