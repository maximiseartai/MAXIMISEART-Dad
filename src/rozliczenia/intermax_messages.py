"""Katalog Komunikatów o INTERMAX dla procesów, które go podmieniają: Uporządkowania INTERMAX, przywrócenia Kopii INTERMAX
i Wpisania raportów (zasady treści: zob. ``message``).

Komunikaty nie zawierają adresów, numerów zleceń, numerów umów ani loginów Wykonawców.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from functools import partial
from pathlib import Path
from typing import Final

from .intermax_replace import Refusal
from .message import IF_ERROR_RETURNS, Message, file_label, folder_label, refer_if
from .order_base import ORDER_BASE_NAME
from .register_columns import ORDERED_FONT, ORDERED_SIZE
from .text import row_range
from . import workbook_messages
from .workbook_files import WorkbookError
from .workbook_messages import DadWorkbook, WorkbookMessages

_PROCESS = "Uporządkowanie INTERMAX"
_UNCHANGED = "INTERMAX nie został zmieniony."
_INTERMAX = DadWorkbook("INTERMAX", "INTERMAX", "order_register", _UNCHANGED, "uruchom ponownie")
_AGAIN = "przywróć kopię jeszcze raz"
_COPIES_PLACE = "w Ustawieniach, w sekcji Kopie INTERMAX"
"""Miejsce w Centrum, w którym tata widzi i przywraca Kopie INTERMAX; Komunikaty o Kopiach nazywają je tylko stąd."""


@dataclass(frozen=True)
class Replacement:
    """Proces, który podmienia INTERMAX: Uporządkowanie (``ORDERING``), przywrócenie Kopii (``RESTORE``) albo Wpisanie
    raportów (``ENTERING``, bez Kopii INTERMAX, ADR 0028).

    Komunikaty o INTERMAX, którego proces nie może podmienić, mówią to samo w obu procesach, a różnią się kodem,
    zwrotem ponowienia (``workbook.again``) i zdaniem „Co się stało” o tym, czego proces nie zrobił. Kod zdania o samym
    INTERMAX (brak, Excel, OneDrive) to ``prefix`` i kod Uporządkowania.
    """

    workbook: DadWorkbook
    prefix: str
    not_written_code: str
    not_written: str
    no_copy_code: str
    no_copy: str
    old_copies_code: str
    done: str


ORDERING: Final = Replacement(
    workbook=_INTERMAX,
    prefix="",
    not_written_code="ZAPIS_INTERMAX_NIEUDANY",
    not_written="Nie udało się zapisać INTERMAX.",
    no_copy_code="KOPIA_INTERMAX_NIEUDANA",
    no_copy="Nie udało się zrobić Kopii INTERMAX.",
    old_copies_code="STARE_KOPIE_INTERMAX",
    done="INTERMAX został uporządkowany",
)
RESTORE: Final = Replacement(
    workbook=replace(_INTERMAX, again=_AGAIN),
    prefix="PRZYWRACANIE_",
    not_written_code="PRZYWRACANIE_NIEUDANE",
    not_written="Nie udało się przywrócić kopii.",
    no_copy_code="PRZYWRACANIE_KOPIA_NIEUDANA",
    no_copy="Nie udało się zrobić Kopii obecnego INTERMAX, więc kopia nie została przywrócona.",
    old_copies_code="PRZYWRACANIE_STARE_KOPIE",
    done="Kopia została przywrócona",
)
ENTERING: Final = Replacement(
    workbook=replace(_INTERMAX, again="kliknij jeszcze raz", closing="Zamknij INTERMAX i kliknij jeszcze raz."),
    prefix="RAPORTY_",
    not_written_code="RAPORTY_ZAPIS_INTERMAX_NIEUDANY",
    not_written="Nie udało się zapisać INTERMAX.",
    no_copy_code="RAPORTY_KOPIA_INTERMAX_NIEUDANA",
    no_copy="Nie udało się zrobić Kopii INTERMAX.",
    old_copies_code="RAPORTY_STARE_KOPIE_INTERMAX",
    done="Raporty zostały wpisane",
)
"""Wpisanie raportów podmienia INTERMAX bez Kopii (``intermax_replace.replace_without_copy``), więc Komunikatów o Kopii
nie daje; pola o Kopii są tu tylko dlatego, że ``Replacement`` je ma. Tata klika „Wpisz raporty z maili” na ekranie
Raporty, więc zwrot ponowienia to „kliknij jeszcze raz”, a przy INTERMAX otwartym w Excelu „Zamknij INTERMAX i kliknij
jeszcze raz”."""


def register_unusable(error: WorkbookError, replacement: Replacement) -> Message:
    """INTERMAX, którego proces ``replacement`` nie może użyć; ``error`` mówi dlaczego.

    Przywrócenie czyta tylko bajty INTERMAX, więc INTERMAX, którego nie da się odczytać, nazywa jak niedostępny.
    """

    def not_synced(register: Path) -> Message:
        return workbook_messages.not_synced(f"{replacement.prefix}NIEDOSTEPNY_INTERMAX", register, replacement.workbook)

    return workbook_messages.unusable(
        error,
        WorkbookMessages(
            missing=partial(register_missing, replacement=replacement),
            open_in_excel=partial(_register_open, replacement=replacement),
            inaccessible=not_synced,
            unreadable=not_synced if replacement is RESTORE else partial(_register_unreadable, replacement=replacement),
        ),
    )


def register_missing(register: Path, replacement: Replacement) -> Message:
    return Message(
        code=f"{replacement.prefix}BRAK_INTERMAX",
        what=f"Nie znaleziono INTERMAX. {_UNCHANGED}",
        where=file_label(register),
        action=f"Wybierz w Ustawieniach właściwy plik INTERMAX, potem {replacement.workbook.again}.",
    )


def _register_open(register: Path, replacement: Replacement) -> Message:
    """INTERMAX jest otwarty w Excelu: plik blokady obok przed Kopią INTERMAX albo przy odmowie podmiany pliku."""

    return workbook_messages.open_in_excel(f"{replacement.prefix}INTERMAX_OTWARTY", register, replacement.workbook)


def _register_unreadable(register: Path, replacement: Replacement) -> Message:
    return Message(
        code=f"{replacement.prefix}NIECZYTELNY_INTERMAX",
        dad_file="order_register",
        what=f"Nie można odczytać INTERMAX jako skoroszytu Excela. {_UNCHANGED}",
        where=file_label(register),
        action=(
            "Otwórz INTERMAX w Excelu i sprawdź, czy się otwiera. Jeśli tak, zapisz go, zamknij i uruchom ponownie. "
            f"{IF_ERROR_RETURNS}"
        ),
    )


def no_order_sheet(register: Path) -> Message:
    return Message(
        code="BRAK_ARKUSZA_ZLECEN",
        dad_file="order_register",
        what=f"W INTERMAX nie ma arkusza zleceń z nagłówkami od AKCJE do UWAGI w wierszu 1. {_UNCHANGED}",
        where=file_label(register),
        action="Sprawdź nagłówki arkusza zleceń w wierszu 1 i uruchom ponownie.",
    )


def register_with_duplicated_headers(register: Path, sheet: str, headers: Sequence[str]) -> Message:
    """Wymagany nagłówek występuje w wierszu 1 arkusza zleceń więcej niż raz, więc nie wiadomo, z której kolumny brać
    dane; ten sam fakt zatrzymuje Przygotowanie pliku zbiorczego."""

    single = len(headers) == 1
    listed = ", ".join(headers)
    return Message(
        code="POWTORZONY_NAGLOWEK_INTERMAX",
        dad_file="order_register",
        what=(
            f"W INTERMAX {'nagłówek' if single else 'nagłówki'} {listed} {'występuje' if single else 'występują'} "
            f"więcej niż raz, więc nie wiadomo, z której kolumny brać dane. {_UNCHANGED}"
        ),
        where=f"{file_label(register)}, arkusz {sheet}, wiersz 1",
        action=(
            f"Zostaw {'nagłówek' if single else 'każdy z nagłówków'} {listed} tylko w jednej kolumnie, zapisz i zamknij "
            "INTERMAX i uruchom ponownie."
        ),
    )


def no_raw_orders(register: Path, sheet: str) -> Message:
    return Message(
        code="BRAK_SUROWYCH_ZLECEN",
        dad_file="order_register",
        what=f"Na dole arkusza zleceń nie ma wklejonych zleceń do uporządkowania. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}",
        action="Wklej zlecenia dnia z aplikacji na dół arkusza zleceń, zapisz i zamknij INTERMAX i uruchom ponownie.",
    )


def raw_orders_in_several_sheets(register: Path, sheets: Sequence[str]) -> Message:
    return Message(
        code="SUROWE_ZLECENIA_W_KILKU_ARKUSZACH",
        dad_file="order_register",
        what=f"Wklejone zlecenia są w więcej niż jednym arkuszu zleceń. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusze {', '.join(sheets)}",
        action=(
            "Zostaw wklejone zlecenia tylko na dole jednego arkusza zleceń, a z pozostałych je usuń. Zapisz i zamknij "
            "INTERMAX i uruchom ponownie."
        ),
    )


def raw_order_above_ordered(register: Path, sheet: str, row: int, ordered_row: int) -> Message:
    return Message(
        code="SUROWE_ZLECENIA_NAD_UPORZADKOWANYMI",
        dad_file="order_register",
        what=(
            f"Wiersz {row} wygląda jak wklejone zlecenie, ale stoi nad uporządkowanym wierszem {ordered_row}. "
            f"{_UNCHANGED}"
        ),
        where=f"{file_label(register)}, arkusz {sheet}, wiersz {row}",
        action=(
            "Przenieś wklejone zlecenia na dół arkusza zleceń, pod ostatni uporządkowany wiersz. Jeśli wiersz "
            f"{row} jest już uporządkowany, nadaj mu czcionkę {ORDERED_FONT} {ORDERED_SIZE}. Zapisz i zamknij INTERMAX i uruchom ponownie."
        ),
    )


def raw_order_without_value(register: Path, sheet: str, row: int, column: str, *, worker: bool) -> Message:
    missing = "Wykonawcy" if worker else "daty z godziną"
    entered = "Wykonawcę" if worker else "datę z godziną"
    return Message(
        code="SUROWE_ZLECENIE_BEZ_WYKONAWCY" if worker else "SUROWE_ZLECENIE_BEZ_DATY",
        dad_file="order_register",
        what=f"Wklejone zlecenie w wierszu {row} nie ma {missing} w kolumnie {column}. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}, komórka {column}{row}",
        action=f"Wpisz {entered} w komórce {column}{row}, zapisz i zamknij INTERMAX i uruchom ponownie.",
    )


def several_days(register: Path, sheet: str, days: Sequence[date], first_row: int, last_row: int) -> Message:
    return Message(
        code="WKLEJENIE_Z_KILKU_DNI",
        dad_file="order_register",
        what=f"Wklejone zlecenia są z więcej niż jednego dnia: {', '.join(map(_day, days))}. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}, {row_range(first_row, last_row)}",
        action=(
            "Zostaw na dole arkusza zleceń zlecenia jednego dnia, a pozostałe usuń. Zapisz i zamknij INTERMAX i "
            "uruchom ponownie, a następny dzień wklej i uporządkuj osobno."
        ),
    )


def day_already_ordered(register: Path, sheet: str, day: date, first_row: int, last_row: int) -> Message:
    return Message(
        code="DZIEN_JUZ_UPORZADKOWANY",
        dad_file="order_register",
        what=f"Dzień {_day(day)} jest już uporządkowany. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}, {_pasted(first_row, last_row)}",
        action="Nowe zlecenia na ten dzień dopisz ręcznie, a wklejone usuń.",
    )


def _pasted(first_row: int, last_row: int) -> str:
    return f"{'wklejony' if first_row == last_row else 'wklejone'} {row_range(first_row, last_row)}"


def _day(day: date) -> str:
    return day.strftime("%d.%m.%Y")


CONFLICT_ACTION: Final = (
    "Otwórz w Excelu INTERMAX i tę kopię, przepisz do INTERMAX zmiany, których w nim brakuje, zapisz go i usuń kopię."
)


def conflict_copy(copy: Path) -> Message:
    return Message(
        code="KOPIA_KONFLIKTU_INTERMAX",
        dad_file="order_register",
        what=f"Obok INTERMAX leży kopia konfliktu OneDrive: OneDrive ma dwie wersje INTERMAX. {_UNCHANGED}",
        where=file_label(copy),
        action=f"{CONFLICT_ACTION} Potem uruchom ponownie.",
    )


def unsupported_shape(register: Path, sheet: str) -> Message:
    return Message.to_maintainer(
        code="NIEOBSLUGIWANY_UKLAD_INTERMAX",
        what=f"Wklejone zlecenia mają układ, którego narzędzie nie porządkuje. {_UNCHANGED}",
        where=f"{file_label(register)}, arkusz {sheet}",
    )


def refused(refusal: Refusal, register: Path, copies: Path, replacement: Replacement) -> Message:
    """Podmiana INTERMAX procesu ``replacement`` odmówiła z powodu ``refusal``; INTERMAX i Kopie są takie, jak były.

    Uporządkowanie sprawdza zapis planem dnia, a Wpisanie raportów zmianami komórek, więc różnica to błąd narzędzia;
    przywrócenie porównuje same bajty Kopii, więc różnica to nieudany zapis. Kopia o tej samej nazwie przy przywróceniu to przywrócenie z tej samej sekundy.
    """

    match refusal:
        case Refusal.EXCEL_HOLDS:
            return _register_open(register, replacement)
        case Refusal.ONEDRIVE_HOLDS:
            return Message(
                code=f"{replacement.prefix}INTERMAX_SYNCHRONIZOWANY",
                what=f"OneDrive jeszcze synchronizuje INTERMAX. {_UNCHANGED}",
                where=file_label(register),
                action=f"Poczekaj, aż OneDrive skończy synchronizację, potem {replacement.workbook.again}.",
            )
        case Refusal.WRITE_MISMATCH if replacement is not RESTORE:
            return Message.to_maintainer(
                code=f"{replacement.prefix}ZAPIS_INTERMAX_NIEZGODNY",
                what=f"Sprawdzenie zapisu wykazało różnicę, więc zapis został odrzucony. {_UNCHANGED}",
                where=file_label(register),
            )
        case Refusal.WRITE_FAILED | Refusal.WRITE_MISMATCH:
            return _disk_failed(replacement.not_written_code, replacement.not_written, file_label(register), replacement)
        case Refusal.COPY_EXISTS if replacement is RESTORE:
            return Message(
                code="PRZYWRACANIE_PRZED_CHWILA",
                what="Przed chwilą przywrócono już kopię INTERMAX, więc ta kopia nie została przywrócona.",
                where=folder_label(copies),
                action=f"Sprawdź listę kopii {_COPIES_PLACE}. Jeśli nadal trzeba, {_AGAIN}.",
            )
        case Refusal.COPY_FAILED | Refusal.COPY_EXISTS:
            return _disk_failed(replacement.no_copy_code, replacement.no_copy, folder_label(copies), replacement)


def _disk_failed(code: str, what: str, where: str, replacement: Replacement) -> Message:
    return Message(
        code=code,
        what=f"{what} {_UNCHANGED}",
        where=where,
        action=f"Sprawdź, czy na dysku jest wolne miejsce, potem {replacement.workbook.again}. {IF_ERROR_RETURNS}",
    )


def old_copies_kept(directory: Path, replacement: Replacement) -> Message:
    return Message(
        code=replacement.old_copies_code,
        what=f"{replacement.done}, ale nie udało się usunąć starszych Kopii INTERMAX.",
        where=folder_label(directory),
        action=(
            "Nie musisz nic robić teraz. Jeśli któraś Kopia INTERMAX jest otwarta w Excelu, zamknij ją. "
            f"{refer_if('Jeśli komunikat wraca', request='przekaż go')}"
        ),
    )


ORDER_BASE_SKIPPED: Final = "BAZA_ZLECEN_POMINIETA"
"""Kod ostrzeżenia, że dzień jest bez Historii adresu, bo Bazy zleceń nie dało się przeczytać; odtworzenie, które
Bazy nie ma, pomija je w porównaniu Komunikatów."""
HISTORY_FIGURE: Final = "Historia adresu"
"""Etykieta liczby zleceń z Historią adresu na karcie Uporządkowania; odtworzenie, które Bazy nie ma, pomija ją w
porównaniu podsumowania, jak ostrzeżenie ``ORDER_BASE_SKIPPED`` w Komunikatach."""
_WITHOUT_HISTORY: Final = "INTERMAX został uporządkowany bez Historii adresu"
_HISTORY_LATER: Final = (
    "Dzień jest już uporządkowany. Jeśli chcesz przy nim Historii adresu, przywróć Kopię INTERMAX sprzed uporządkowania "
    f"{_COPIES_PLACE} i uruchom ponownie."
)


def order_base_unusable(error: WorkbookError) -> Message:
    """Ostrzeżenie: Bazy zleceń z folderu INTERMAX nie dało się przeczytać, więc dzień jest bez Historii adresu;
    ``error`` mówi dlaczego. Bazę otwartą w Excelu proces czyta w jej ostatniej zapisanej wersji."""

    return workbook_messages.unusable(
        error,
        WorkbookMessages(
            missing=_order_base_missing,
            open_in_excel=_order_base_inaccessible,
            inaccessible=_order_base_inaccessible,
            unreadable=_order_base_unreadable,
        ),
    )


def _order_base_missing(base: Path) -> Message:
    return Message(
        code=ORDER_BASE_SKIPPED,
        what=f"{_WITHOUT_HISTORY}, bo w folderze INTERMAX nie ma Bazy zleceń.",
        where=file_label(base),
        action=f"Połóż Bazę zleceń w folderze INTERMAX pod nazwą {ORDER_BASE_NAME}. {_HISTORY_LATER}",
    )


def _order_base_inaccessible(base: Path) -> Message:
    return Message(
        code=ORDER_BASE_SKIPPED,
        what=f"{_WITHOUT_HISTORY}, bo nie można teraz odczytać Bazy zleceń.",
        where=file_label(base),
        action=f"Poczekaj, aż OneDrive skończy synchronizację Bazy zleceń. {_HISTORY_LATER} {IF_ERROR_RETURNS}",
    )


def _order_base_unreadable(base: Path) -> Message:
    return Message(
        code=ORDER_BASE_SKIPPED,
        what=f"{_WITHOUT_HISTORY}, bo Bazy zleceń nie można odczytać jako skoroszytu Excela.",
        where=file_label(base),
        action=f"Otwórz Bazę zleceń w Excelu i sprawdź, czy się otwiera; jeśli tak, zapisz ją. {_HISTORY_LATER} {IF_ERROR_RETURNS}",
    )


def order_base_unsupported(base: Path, sheet: str) -> Message:
    return Message(
        code=ORDER_BASE_SKIPPED,
        what=f"{_WITHOUT_HISTORY}, bo arkusz Bazy zleceń ma układ, którego narzędzie nie czyta.",
        where=f"{file_label(base)}, arkusz {sheet}",
        action=(
            "Sprawdź, czy w wierszu 1 tego arkusza kolumna A ma nagłówek nad adresami. "
            f"{refer_if('Jeśli ma, a komunikat wraca', request='przekaż go')} {_HISTORY_LATER}"
        ),
    )


def copies_unreadable(directory: Path) -> Message:
    return Message(
        code="KOPIE_INTERMAX_NIEDOSTEPNE",
        what=f"Nie można teraz odczytać folderu Kopii INTERMAX. {_UNCHANGED}",
        where=folder_label(directory),
        action=f"Poczekaj chwilę i odśwież stronę. {IF_ERROR_RETURNS}",
    )


def copy_missing(directory: Path, name: str) -> Message:
    return Message(
        code="BRAK_KOPII_INTERMAX",
        what=f"Tej Kopii INTERMAX już nie ma. {_UNCHANGED}",
        where=f"{folder_label(directory)}, {name}",
        action=f"Wybierz kopię z listy {_COPIES_PLACE}.",
    )


def copy_unusable(error: WorkbookError) -> Message:
    return workbook_messages.unusable(
        error,
        WorkbookMessages(
            missing=lambda copy: copy_missing(copy.parent, copy.name),
            open_in_excel=_copy_open,
            inaccessible=_copy_unreadable,
            unreadable=_copy_unreadable,
        ),
    )


def _copy_open(copy: Path) -> Message:
    return Message(
        code="KOPIA_INTERMAX_OTWARTA",
        what=f"Ta Kopia INTERMAX jest otwarta w Excelu. {_UNCHANGED}",
        where=file_label(copy),
        action=f"Zamknij ją w Excelu bez zapisywania zmian, potem {_AGAIN}. {workbook_messages.lock_hint(copy, _AGAIN)}",
    )


def _copy_unreadable(copy: Path) -> Message:
    return Message(
        code="KOPIA_INTERMAX_NIEDOSTEPNA",
        what=f"Nie można teraz odczytać tej Kopii INTERMAX. {_UNCHANGED}",
        where=file_label(copy),
        action=f"Spróbuj za chwilę: {_AGAIN}. {IF_ERROR_RETURNS}",
    )


def copy_damaged(copy: Path) -> Message:
    return Message(
        code="KOPIA_INTERMAX_USZKODZONA",
        what=f"Ta Kopia INTERMAX jest uszkodzona, więc nie została przywrócona. {_UNCHANGED}",
        where=file_label(copy),
        action="Wybierz inną kopię z listy.",
    )


def unexpected_failure() -> Message:
    return Message(
        code="BLAD_NIEOCZEKIWANY",
        what=f"Wystąpił nieoczekiwany błąd. {_UNCHANGED}",
        where=_PROCESS,
        action=f"Uruchom ponownie. {IF_ERROR_RETURNS}",
    )


def summary_not_shown() -> Message:
    return Message.to_maintainer(
        code="BLAD_PODSUMOWANIA",
        what="INTERMAX został uporządkowany, ale nie udało się pokazać podsumowania.",
        where=_PROCESS,
        before="Nie uruchamiaj ponownie.",
        check="INTERMAX",
    )
