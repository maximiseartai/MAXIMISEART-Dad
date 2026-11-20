from __future__ import annotations

from pathlib import Path

from rozliczenia.message import IF_ERROR_RETURNS, KEEP_ON_DEVICE, Message, file_label
from rozliczenia.workbook_messages import lock_hint

_DIAGNOSIS = "Diagnoza w Centrum rozliczeń"


def cause_not_found() -> Message:
    return Message(
        code="NIE_ZNALEZIONO_PRZYCZYNY",
        what="Nie znalazłem przyczyny na tym komputerze.",
        where=_DIAGNOSIS,
        action="Wyślij do Maksa.",
    )


def newer_tool_version() -> Message:
    return Message(
        code="NOWSZA_WERSJA_NARZEDZIA",
        what="Jest nowsza wersja narzędzia.",
        where="narzędzie na tym komputerze",
        action="Kliknij „Zaktualizuj narzędzie”. Gdy karta Centrum sama się odświeży, uruchom proces ponownie.",
    )


def period_file_open(path: Path) -> Message:
    return Message(
        code="PLIK_OKRESU_OTWARTY",
        what="Plik okresu jest otwarty w Excelu.",
        where=file_label(path),
        action=f"Zapisz i zamknij plik w Excelu, potem uruchom ponownie. {lock_hint(path, 'uruchom ponownie')}",
    )


def file_only_in_cloud(path: Path) -> Message:
    return Message(
        code="PLIK_TYLKO_W_CHMURZE",
        what="Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze.",
        where=file_label(path),
        action=f"{KEEP_ON_DEVICE} i uruchom ponownie.",
    )


_WORKER_LIST = "Lista Wykonawców w Ustawieniach Centrum"


def worker_list_bad(sentence: str) -> Message:
    return Message(
        code="ZLA_LISTA_WYKONAWCOW",
        what=f"Lista Wykonawców ma złe ustawienie. {sentence}",
        where=_WORKER_LIST,
        action="Otwórz Ustawienia, sekcję Wykonawcy, sprawdź tam, co jest nie tak z listą, i po poprawce uruchom ponownie.",
        setting="wykonawcy",
    )


def worker_list_last_good(sentence: str) -> Message:
    return Message(
        code="LISTA_WYKONAWCOW_OSTATNIA_DOBRA",
        what=f"Uruchomienie użyło ostatniej dobrej Listy Wykonawców, bo bieżąca ma złe ustawienie. {sentence}",
        where=_WORKER_LIST,
        action="Otwórz Ustawienia, sekcję Wykonawcy, i sprawdź tam, co jest nie tak z listą, zanim uruchomisz następny proces.",
        setting="wykonawcy",
    )


def worker_list_unreadable() -> Message:
    return Message(
        code="NIEDOSTEPNA_LISTA_WYKONAWCOW",
        what="Nie można teraz odczytać Listy Wykonawców. Plik może być zajęty przez inny program.",
        where=_WORKER_LIST,
        action=f"Zamknij program, który może trzymać plik, i uruchom ponownie. {IF_ERROR_RETURNS}",
        setting="wykonawcy",
    )
