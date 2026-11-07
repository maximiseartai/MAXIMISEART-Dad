"""Katalog Komunikatów Diagnozy: przyczyny, których nie opisuje żaden katalog procesu.

Diagnoza wyjaśnia przyczynę Komunikatem z katalogu procesu, gdy proces ma
własny (np. Rejestr zleceń otwarty w Excelu). Ten katalog ma tylko resztę:
brak przyczyny, nowsza wersja narzędzia, plik okresu otwarty w Excelu i plik
tylko w chmurze OneDrive. Instrukcja taty cytuje „Co się stało” każdego Komunikatu
(``tests/test_instrukcja_taty.py``).
"""

from __future__ import annotations

from pathlib import Path

from rozliczenia.message import KEEP_ON_DEVICE, Message, file_label

_DIAGNOSIS = "Diagnoza w Centrum rozliczeń"


def cause_not_found() -> Message:
    """Każde sprawdzenie Diagnozy przeszło: przyczyna nie leży na komputerze taty."""

    return Message(
        code="NIE_ZNALEZIONO_PRZYCZYNY",
        what="Nie znalazłem przyczyny na tym komputerze.",
        where=_DIAGNOSIS,
        action="Wyślij do Maksa.",
    )


def newer_tool_version() -> Message:
    """Commit narzędzia u taty nie zawiera najnowszego Wydania na GitHubie: poprawka mogła już trafić do narzędzia."""

    return Message(
        code="NOWSZA_WERSJA_NARZEDZIA",
        what="Jest nowsza wersja narzędzia.",
        where="narzędzie na tym komputerze",
        action="Kliknij „Zaktualizuj narzędzie”. Gdy karta Centrum sama się odświeży, uruchom proces ponownie.",
    )


def period_file_open(path: Path) -> Message:
    """Plik okresu ma obok plik blokady Excela ``~$…``; narzędzie go nie usuwa."""

    return Message(
        code="PLIK_OKRESU_OTWARTY",
        what="Plik okresu jest otwarty w Excelu.",
        where=file_label(path),
        action=(
            "Zapisz i zamknij plik w Excelu, potem uruchom ponownie. Jeśli Excel jest zamknięty, "
            f"usuń z tego samego folderu pozostawiony plik ~${path.name} i uruchom ponownie."
        ),
    )


def file_only_in_cloud(path: Path) -> Message:
    """Plik, który czyta proces, OneDrive trzyma tylko w chmurze (atrybut „tylko online”), bez kopii lokalnej."""

    return Message(
        code="PLIK_TYLKO_W_CHMURZE",
        what="Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze.",
        where=file_label(path),
        action=f"{KEEP_ON_DEVICE} i uruchom ponownie.",
    )
