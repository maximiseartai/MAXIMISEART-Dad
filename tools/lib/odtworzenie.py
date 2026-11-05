"""Odtworzenie Uruchomienia procesu z jego Logów na kodzie tego drzewa (#847): wejście z Kopii wejścia, ten sam proces
i tryb, a w miejscu efenix Atrapa efenix z odczytów stron; wynik to raport z pierwszą różnicą i granicami Logów.

Jedyną operacją jest ``replay()``. Kształt danych:

- Logi Uruchomienia (``run_logs.RunLog`` tego drzewa) dają proces, tryb, okres, wynik i ślad do porównania, a Kopia
  wejścia wiersze plików taty.
- Granice (``Limit``) to to, czego Logi nie niosą. Granica blokująca (Logi bez Kopii wejścia, Urwane Uruchomienie,
  pusta Kopia, wiersz INTERMAX bez pewnego położenia, komórka typu, którego Kopia nie zapisała, Logi Wyceny bez odczytu
  wyników szukania, wiersz Kopii albo zlecenie śladu efenix, które strażnik reguły danych pominął) kończy odtworzenie
  bez uruchomienia procesu: wynik takiego odtworzenia nic by nie znaczył. Zastrzeżenie (maski strażnika w Kopii, pole
  albo element, które strażnik pominął poza wejściem, Wzorce spoza Logów, Surowe zlecenia, dni nad wklejeniem, Atrapa w
  miejscu efenix) raport podaje przy każdym wyniku, bo może tłumaczyć różnicę.
- Pliki wejścia powstają w katalogu roboczym z Kopii wejścia, pod tą samą nazwą w folderach o tych samych nazwach co
  u taty (``CopiedFile.folders``), więc Komunikaty nazywają te same plik i folder: każdy arkusz z nagłówkami i
  wierszami pod tymi samymi numerami, przesunięty pierwszy wiersz wklejenia INTERMAX znowu przesunięty, a nad
  wklejeniem ostatni uporządkowany i żółty wiersz w tych samych wierszach co u taty. Wiersze Rejestru zleceń
  Przygotowania mają krój uporządkowanych wierszy taty (Calibri 8), bo wiersz bez niego pamięć reguły danych zna też
  dwie kolumny na lewo od nagłówka (#918), a wiersze wklejenia INTERMAX krój wiersza z aplikacji. W miejscu kolumn
  ``ADRES`` i numeru Orange stoją wartości syntetyczne z numerem wiersza (``SYNTHETIC_ADDRESS``, ``SYNTHETIC_ORANGE``),
  których żaden plik taty nie ma. Wzorce i Konfigurację wykonawców daje folder ``configuration``, bo Logi mają z nich
  tylko nazwę i rozmiar.
- Proces biegnie przez ten sam rdzeń (``process_run.run_process``) i ten sam wpis katalogu procesów co w Centrum, z
  Kopią wejścia i pamięcią reguły danych, a Logi odtworzenia składają ``RunLog.of`` i strażnik (``guarded``), jak w
  Centrum. Decyzję taty odtworzenie rozstrzyga tak jak tata: odmowa tylko wtedy, gdy Logi kończą się odmową.
- Porównanie (``first_difference``) idzie po polach Logów w kolejności przyczyn: Kopia wejścia (czy pliki z Kopii
  czytają się tak samo), wynik, zakończenie i Rodzaj Zatrzymania, Komunikaty, uwagi techniczne, podsumowanie, liczba
  problemów, etapy, Szablony pracownika, Ilości tylko dla INEA, Wpisy INTERMAX, ślad zleceń i Zatrzymanie okna efenix
  oraz ślad wywołań. Czasy i chwile kroków, odciski plików, środowisko, dziennik działań taty i uwagi strażnika o Kopii
  wejścia są poza porównaniem: zależą od komputera i chwili, a nie od kodu i wejścia.

Odtworzenie pisze tylko w katalogu roboczym (``work``): pliki wejścia, Rozliczenia i Kopie INTERMAX, które proces
zapisuje, metryki i Ślad Wyceny Emmetta. Nic nie idzie do Skrzynki Zgłoszeń, bo odtworzenie nie ma Kolejki wysyłki.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import enum
import json
from pathlib import Path
import platform
import re
from typing import Any, Final

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia import efenix_browser, intermax_copies
from rozliczenia.centrum import contract
from rozliczenia.centrum.catalog import (
    EFENIX,
    INTERMAX,
    PREPARATION,
    SETTLEMENT,
    ProcessDeclaration,
)
from rozliczenia.centrum.dad_actions import DadActions
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.reports import ProblemFingerprint
from rozliczenia.centrum.run_logs import (
    Environment,
    LoggedCell,
    LoggedInputFile,
    LoggedSheet,
    LoggedTyped,
    RunLog,
    guard_cuts,
    guarded,
)
from rozliczenia.centrum.runs import CONTINUE_HINT, EndedRun, PreparedRun
from rozliczenia.centrum.stops import StoppedRun
from rozliczenia.client_data import ForbiddenColumn, ForbiddenValues, forbidden_columns
from rozliczenia.collective_preparation import (
    default_collective_template_path,
    default_internal_template_path,
)
from rozliczenia.decision import Decision
from rozliczenia.efenix_orders import PricingScope, read_scope
from rozliczenia.efenix_process import EfenixInputs
from rozliczenia.engine import default_worker_template_path
from rozliczenia.input_checks import FILE_READERS
from rozliczenia.input_copy import InputCopy
from rozliczenia.intermax_process import OrderingInputs
from rozliczenia.preparation_process import PreparationInputs
from rozliczenia.preparation_register import COLUMNS
from rozliczenia.process_run import Finished, Stop, run_process
from rozliczenia.progress import ProgressProjection, ProgressSnapshot
from rozliczenia.settlement_process import SettlementInputs
from rozliczenia.worker_config import default_config_path, normalize_text

import atrapa_z_logow

SYNTHETIC_ADDRESS: Final = atrapa_z_logow.SYNTHETIC_ADDRESS
"""``ADRES`` wiersza w odtworzonym pliku: ulica z numerem wiersza, którą reguła adresu efenix rozbiera."""
SYNTHETIC_ORANGE: Final = "ORANGE-ODTWORZENIE-{row}"
"""Numer Orange wiersza w odtworzonym pliku."""
MASKS: Final = ("[adres]", "[numer Orange]", "[telefon]", "[ulica]")
"""Maski strażnika reguły danych (``client_data``), które Kopia wejścia może nieść w miejscu wartości taty."""

_SYNTHETIC: Final = {ForbiddenColumn.ADDRESS: SYNTHETIC_ADDRESS, ForbiddenColumn.ORANGE: SYNTHETIC_ORANGE}
_COLLECTIVE_HEADER_ROW: Final = 17
_COLLECTIVE_FORBIDDEN: Final = {"B": ForbiddenColumn.ADDRESS, "I": ForbiddenColumn.ORANGE}
"""Zakazane kolumny Pliku zbiorczego z układu Wzorca (``workbook_files._FORBIDDEN_POSITIONS``); nagłówek to nazwa
kolumny w regule danych, jak we Wzorcu."""
_REGISTER_FORBIDDEN: Final = {
    column.register_header: forbidden
    for column in COLUMNS
    for forbidden, _ in forbidden_columns({normalize_text(column.target_header): column})
}
"""Nagłówek Rejestru zleceń i INTERMAX (``ADRES``, ``NUMER UMOWY``) każdej kolumny, której Kopia wejścia nie ma."""
_ORDERED_FONT: Final = Font(name="Calibri", sz=8)
"""Krój uporządkowanego wiersza Rejestru zleceń i INTERMAX (``raw_orders.ordered_look``)."""
_PASTED_FONT: Final = Font(name="Roboto", sz=4)
"""Krój wiersza wklejonego z aplikacji firmowej, bez wyglądu uporządkowanego (``raw_orders.ordered_look``)."""
_YELLOW: Final = PatternFill("solid", fgColor="FFFFFF00")
"""Żółty wiersz, którym tata oddziela dni w INTERMAX."""
_ORDERED_TEXT: Final = "uporządkowany wiersz odtworzenia"
_SHIFT: Final = 2
"""O tyle kolumn w lewo stoi przesunięty pierwszy wiersz wklejenia INTERMAX (``raw_orders.SHIFT``)."""
_MISSING: Final = "(brak)"
_Written = bool | int | float | str | datetime | time | timedelta
"""Wartość komórki odtworzonego pliku."""


class Verdict(enum.Enum):
    """Wynik odtworzenia z kodem wyjścia narzędzia."""

    AGREES = ("ODTWORZENIE ZGODNE", 0)
    DIFFERS = ("ODTWORZENIE RÓŻNE", 1)
    IMPOSSIBLE = ("NIE DA SIĘ ODTWORZYĆ", 3)

    @property
    def headline(self) -> str:
        return self.value[0]

    @property
    def exit_code(self) -> int:
        return self.value[1]


@dataclass(frozen=True)
class Limit:
    """Granica Logów: czego odtworzenie nie ma; ``blocking``: bez tego wynik odtworzenia nic nie znaczy."""

    text: str
    blocking: bool = False


@dataclass(frozen=True)
class Difference:
    """Pierwsza różnica: pole Logów (ścieżka JSON) i wartość w Logach i w odtworzeniu (``_MISSING``: pola nie ma)."""

    field: str
    logged: object
    replayed: object


@dataclass(frozen=True)
class Report:
    """Wynik odtworzenia, pierwsza różnica, granice i Logi odtworzenia (``None``: proces nie biegł)."""

    verdict: Verdict
    difference: Difference | None
    limits: tuple[Limit, ...]
    replayed: RunLog | None = None

    def lines(self, record: RunLog, code: str) -> list[str]:
        """Raport dla Maksa: wynik w pierwszej linii, potem Uruchomienie, kod, różnica i granice."""

        title = _KINDS[record.process].declaration.title
        blocking = [limit.text for limit in self.limits if limit.blocking]
        first = f"{self.verdict.headline}: {blocking[0]}" if blocking else self.verdict.headline
        lines = [
            first,
            f"Uruchomienie: {title}, {record.mode}, okres {record.period}, {record.file_name}",
            f"Kod: {code}",
        ]
        if self.difference is not None:
            lines += [
                f"Pierwsza różnica: {self.difference.field}",
                f"  Logi:        {_shown(self.difference.logged)}",
                f"  Odtworzenie: {_shown(self.difference.replayed)}",
            ]
        if self.verdict is not Verdict.IMPOSSIBLE:
            lines.append(f"Porównano: {', '.join(name for name, _ in _COMPARED)}.")
            lines.append(
                "Poza porównaniem: czasy i chwile kroków, odciski plików, środowisko, dziennik działań taty, wygląd "
                "komórek (Kopia wejścia go nie ma) i zapisane pliki."
            )
        rest = [limit.text for limit in self.limits if not limit.blocking] + blocking[1:]
        if rest:
            lines.append("Granice:")
            lines += [f"- {text}" for text in rest]
        return lines


def replay(
    record: RunLog,
    *,
    work: Path,
    configuration: Path | None,
    efenix_today: date | None = None,
) -> Report:
    """Odtwarza Uruchomienie ``record`` w katalogu roboczym ``work`` i porównuje je z Logami.

    ``configuration``: folder z Konfiguracją wykonawców i Wzorcami pod nazwami z ``config/`` narzędzia (``None``: bez
    niego, wtedy Przygotowanie i Przebieg mają granicę blokującą). ``efenix_today``: dzisiejszy dzień kalendarza Atrapy
    efenix (``None``: dzień startu Uruchomienia w czasie tego komputera).
    """

    kind = _KINDS[record.process]
    limits = _limits(record, kind, configuration)
    if any(limit.blocking for limit in limits):
        return Report(Verdict.IMPOSSIBLE, None, tuple(limits))
    with ExitStack() as stack:
        setup = kind.setup(record, _Work(work, configuration, efenix_today, stack))
        limits += setup.limits
        if any(limit.blocking for limit in setup.limits):
            return Report(Verdict.IMPOSSIBLE, None, tuple(limits))
        replayed = _run(record, setup, work)
    difference = first_difference(record, replayed)
    return Report(
        Verdict.AGREES if difference is None else Verdict.DIFFERS,
        difference,
        tuple(limits),
        replayed,
    )


# --- granice --------------------------------------------------------------------------------------------------------


def _limits(record: RunLog, kind: _Kind, configuration: Path | None) -> list[Limit]:
    if record.ending == "interrupted":
        return [
            Limit(
                "to Logi Urwanego Uruchomienia: Centrum zgasło w trakcie, a Logi z dziennika Wyceny nie mają Kopii "
                "wejścia ani wyniku do porównania",
                blocking=True,
            )
        ]
    copied = record.input_copy
    if copied is None:
        return [
            Limit(
                "Logi nie mają Kopii wejścia (Logi sprzed #841 albo Uporządkowanie sprzed #842)",
                blocking=True,
            )
        ]
    if not copied:
        return [
            Limit(
                "Kopia wejścia jest pusta: Uruchomienie skończyło się przed odczytem plików taty, więc nie wiadomo, "
                "jakie pliki zastało",
                blocking=True,
            )
        ]
    limits = [*_guard_limits(record), *_typed_limits(copied), *_masked_limits(record), *kind.limits(record)]
    if kind.configuration:
        limits.append(_configuration_limit(record, configuration, kind.configuration))
    if record.stop_kind == "repeated":
        limits.append(
            Limit(
                "Powtórka zależy od poprzedniego Zatrzymania w tej samej pracy Centrum: odtworzenie porównuje ją jak "
                "Zatrzymanie dla taty"
            )
        )
    return limits


def _guard_limits(record: RunLog) -> list[Limit]:
    """Miejsca Logów, które strażnik reguły danych pominął albo zostawił puste (``run_logs.guard_cuts``), bo maska trafiła
    w pole, które jej nie przyjmuje. W wejściu odtworzenia (Kopia wejścia bez odcisku pliku, ślad zleceń efenix, z którego
    powstaje Atrapa) to granica blokująca: odtworzone wejście nie jest wejściem taty, a różnica wskazałaby fałszywą
    przyczynę. Poza wejściem to zastrzeżenie: różnica w tym miejscu jest skutkiem maski."""

    limits: list[Limit] = []
    for cut in guard_cuts(record):
        lost = "pominął" if cut.removed else "zostawił puste"
        place = f"{lost} w Logach {cut.place} (maska w polu, które jej nie przyjmuje)"
        if _replay_input(cut.place):
            limits.append(Limit(f"strażnik reguły danych {place}, a odtworzenie buduje z niego wejście", blocking=True))
        else:
            limits.append(Limit(f"Strażnik reguły danych {place}: różnica w tym miejscu jest skutkiem maski"))
    return limits


def _replay_input(place: str) -> bool:
    """Czy miejsce Logów ``place`` (ścieżka JSON) to wejście odtworzenia: Kopia wejścia poza odciskiem pliku albo ślad
    zleceń efenix."""

    top = re.split(r"[.\[]", place)[0]
    return top == "efenix_orders" or (top == "input_copy" and ".fingerprint" not in place)


def _typed_limits(copied: Sequence[LoggedInputFile]) -> list[Limit]:
    other = [
        f"{sheet.sheet} {letter}{row.row}"
        for file in copied
        for sheet in file.sheets
        for row in sheet.rows
        for letter, value in row.cells.items()
        if isinstance(value, LoggedTyped) and value.type == "other"
    ]
    if not other:
        return []
    return [
        Limit(
            f"Kopia wejścia nie zapisała wartości {len(other)} komórek (typ spoza Kopii, np. {other[0]}), więc "
            "odtworzone pliki ich nie mają",
            blocking=True,
        )
    ]


def _masked_limits(record: RunLog) -> list[Limit]:
    counted: Counter[str] = Counter()
    for file in record.input_copy or ():
        for sheet in file.sheets:
            for row in sheet.rows:
                for value in row.cells.values():
                    if isinstance(value, str):
                        counted.update({mask: value.count(mask) for mask in MASKS if mask in value})
    if not counted:
        return []
    masks = ", ".join(f"{mask} ×{count}" for mask, count in counted.most_common())
    return [
        Limit(
            f"Kopia wejścia ma maski strażnika reguły danych ({masks}): odtworzenie czyta maskę w miejscu wartości taty, "
            "więc reguła, która czyta tę komórkę, może zdecydować inaczej"
        )
    ]


def _configuration_limit(record: RunLog, configuration: Path | None, roles: Sequence[str]) -> Limit:
    """Konfiguracja wykonawców i Wzorce (``roles``) z folderu ``configuration``: bez folderu odtworzenie nie biegnie, a
    plik, którego w nim nie ma, i rozmiar inny niż plik taty w Logach (``environment.files``) raport nazywa."""

    if configuration is None or not configuration.is_dir():
        return Limit(
            f"nie ma folderu z Konfiguracją wykonawców i Wzorcami ({configuration or 'brak'}, --konfiguracja): Logi ich "
            "nie niosą, a proces bez nich nie biegnie",
            blocking=True,
        )
    logged = {file.name: file.size for file in (record.environment.files or ())}
    files = _configuration_files(configuration)
    missing = [files[role].name for role in roles if not files[role].is_file()]
    sizes = [
        f"{path.name}: u taty {logged[path.name]} B, tu {path.stat().st_size} B"
        for path in (files[role] for role in roles)
        if path.is_file() and logged.get(path.name) not in (None, path.stat().st_size)
    ]
    text = (
        f"Konfiguracja wykonawców i Wzorce nie są w Logach: odtworzenie czyta je z {configuration}, a Logi mają tylko "
        "nazwę i rozmiar plików taty"
    )
    if missing:
        text += f"; w folderze nie ma: {', '.join(missing)}"
    if sizes:
        text += f"; inny rozmiar niż u taty: {'; '.join(sizes)}"
    return Limit(text)


def _configuration_files(folder: Path) -> dict[str, Path]:
    return {
        "worker_config": folder / default_config_path().name,
        "internal_template": folder / default_internal_template_path().name,
        "collective_template": folder / default_collective_template_path().name,
        "worker_template": folder / default_worker_template_path().name,
    }


# --- pliki wejścia --------------------------------------------------------------------------------------------------


@dataclass
class _Work:
    """Katalog roboczy odtworzenia, folder Konfiguracji, dzień Atrapy i stos zasobów (Atrapa) na czas przebiegu."""

    directory: Path
    configuration: Path | None
    efenix_today: date | None
    stack: ExitStack

    def path(self, *parts: str) -> Path:
        """Plik ``parts`` w katalogu roboczym; jego folder już jest."""

        path = self.directory.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def folder(self, *parts: str) -> Path:
        """Folder ``parts`` w katalogu roboczym, już założony."""

        folder = self.directory.joinpath(*parts)
        folder.mkdir(parents=True, exist_ok=True)
        return folder


@dataclass
class _Setup:
    """Uruchomienie gotowe do startu w katalogu roboczym i granice, które odbudowa wejścia znalazła po drodze."""

    prepared: PreparedRun[Any, Any]
    forbidden: ForbiddenValues
    limits: list[Limit] = field(default_factory=list)


@dataclass(frozen=True)
class _Kind:
    """Odtworzenie jednego procesu: jego wpis w katalogu procesów, granice, odbudowa wejścia i czy czyta Konfigurację i
    Wzorce."""

    declaration: ProcessDeclaration[Any, Any]
    limits: Callable[[RunLog], list[Limit]]
    setup: Callable[[RunLog, _Work], _Setup]
    configuration: tuple[str, ...] = ()
    """Pliki z folderu Konfiguracji (klucze ``_configuration_files``), które proces czyta."""


def _cell(value: LoggedCell) -> _Written:
    """Wartość komórki do zapisu w pliku: tekst, liczba i prawda/fałsz jak w Kopii, a data, godzina i czas trwania z
    zapisu w Kopii (``input_copy.Typed``)."""

    if not isinstance(value, LoggedTyped):
        return value
    match value.type:
        case "datetime":
            return datetime.fromisoformat(value.text)
        case "time":
            return time.fromisoformat(value.text)
        case "timedelta":
            return timedelta(seconds=float(value.text))
        case "other":
            raise ValueError(f"komórka typu spoza Kopii wejścia: {value.text}")


def _sheet(workbook: Workbook, sheet: LoggedSheet) -> Worksheet:
    created: Worksheet = workbook.create_sheet(sheet.sheet)
    for letter, header in sheet.columns.items():
        created.cell(sheet.header_row, column_index_from_string(letter), header)
    return created


def _new_workbook() -> Workbook:
    workbook = Workbook()
    default = workbook.active
    if default is not None:
        workbook.remove(default)
    return workbook


def _the_file(record: RunLog) -> LoggedInputFile:
    """Jedyny plik Kopii wejścia; ``_one_file_limits`` blokuje odtworzenie Logów z inną liczbą plików."""

    [copied] = record.input_copy or []
    return copied


def _one_file_limits(record: RunLog, what: str) -> list[Limit]:
    copied = record.input_copy or ()
    if len(copied) != 1:
        return [
            Limit(
                f"Kopia wejścia ma {len(copied)} pliki, a {what} czyta jeden",
                blocking=True,
            )
        ]
    return []


def _collective_file(record: RunLog, work: _Work, addresses: Mapping[int, str]) -> Path:
    """Plik zbiorczy z Kopii wejścia: arkusz z nagłówkami w wierszu 17 i Wierszami danych pod ich numerami, a w B i I
    (``ADRES``, numer Orange) wartości ``addresses`` albo syntetyczne."""

    copied = _the_file(record)
    [sheet] = copied.sheets
    workbook = _new_workbook()
    created = _sheet(workbook, sheet)
    for letter, forbidden in _COLLECTIVE_FORBIDDEN.items():
        created[f"{letter}{sheet.header_row}"] = forbidden.value
    for row in sheet.rows:
        for letter, value in row.cells.items():
            created[f"{letter}{row.row}"] = _cell(value)
        for letter, forbidden in _COLLECTIVE_FORBIDDEN.items():
            created[f"{letter}{row.row}"] = _SYNTHETIC[forbidden].format(row=row.row)
        if row.row in addresses:
            created[f"B{row.row}"] = addresses[row.row]
    path = work.path("okresy", *(copied.folders or [record.period]), copied.name)
    workbook.save(path)
    return path


def _collective_limits(record: RunLog) -> list[Limit]:
    limits = _one_file_limits(record, "proces")
    if limits:
        return limits
    sheets = _the_file(record).sheets
    if len(sheets) != 1 or sheets[0].header_row != _COLLECTIVE_HEADER_ROW:
        return [
            Limit(
                "Kopia Pliku zbiorczego nie ma jednego arkusza z nagłówkami w wierszu 17",
                blocking=True,
            )
        ]
    return []


def _settlement(record: RunLog, work: _Work) -> _Setup:
    source = _collective_file(record, work, {})
    configuration = _configured(work)
    forbidden, copy = ForbiddenValues(), InputCopy()
    inputs = SettlementInputs(
        source,
        dry_run=record.mode == "podgląd",
        config_path=configuration["worker_config"],
        worker_template_path=configuration["worker_template"],
        readers=FILE_READERS,
        forbidden=forbidden,
        copy=copy,
    )
    return _Setup(
        PreparedRun(SETTLEMENT, record.period, SETTLEMENT.core(_PROCESSES), inputs, copy),
        forbidden,
    )


def _configured(work: _Work) -> dict[str, Path]:
    assert work.configuration is not None, "bez folderu Konfiguracji _configuration_limit blokuje odtworzenie"
    return _configuration_files(work.configuration)


def _register_file(record: RunLog, work: _Work, folder: str, font: Font) -> tuple[Path, list[Limit]]:
    """Rejestr zleceń albo INTERMAX z Kopii wejścia: arkusze z nagłówkami w wierszu 1 i wierszami pod ich numerami.

    Kolumn ``ADRES`` i ``NUMER UMOWY`` Kopia nie ma, więc ich nagłówki stoją w pierwszych kolumnach bez nagłówka między
    kolumnami Kopii (u taty tam stoją), a gdy takich nie ma, za ostatnią; ich komórki mają wartości syntetyczne.
    Przesunięty pierwszy wiersz wklejenia INTERMAX stoi znowu dwie kolumny w lewo, a nad wklejeniem ostatni
    uporządkowany wiersz (Calibri 8, bez daty) i żółty wiersz stoją tam, gdzie u taty. ``font``: krój komórek z Kopii.
    """

    copied = _the_file(record)
    workbook = _new_workbook()
    limits: list[Limit] = []
    for sheet in copied.sheets:
        created = _sheet(workbook, sheet)
        forbidden = _forbidden_places(sheet)
        if len(forbidden) < len(_REGISTER_FORBIDDEN):
            limits.append(Limit(f"arkusz {sheet.sheet}: nie wiem, gdzie stały kolumny ADRES i NUMER UMOWY"))
        for column, header in forbidden.items():
            created.cell(sheet.header_row, column, header)
        for row in sheet.rows:
            shift = _SHIFT if row.row == sheet.shifted_row else 0
            for letter, value in row.cells.items():
                created.cell(row.row, column_index_from_string(letter) - shift, _cell(value)).font = font
            for column, header in forbidden.items():
                synthetic = _SYNTHETIC[_REGISTER_FORBIDDEN[header]].format(row=row.row)
                created.cell(row.row, column - shift, synthetic)
        _above_paste(created, sheet)
    path = work.path(folder, *copied.folders, copied.name)
    workbook.save(path)
    return path, limits


def _forbidden_places(sheet: LoggedSheet) -> dict[int, str]:
    """Kolumna (od 1) każdego nagłówka ``_REGISTER_FORBIDDEN``: kolumny bez nagłówka w Kopii między pierwszą a ostatnią
    kolumną z nagłówkiem, po kolei, a gdy ich brakuje, kolumny za ostatnią."""

    used = sorted(column_index_from_string(letter) for letter in sheet.columns)
    if not used:
        return {}
    gaps = [column for column in range(used[0], used[-1] + 1) if column not in used]
    places = [*gaps, *range(used[-1] + 1, used[-1] + 1 + len(_REGISTER_FORBIDDEN))]
    # zip kończy się na krótszej liście: miejsc jest zawsze co najmniej tyle co nagłówków
    return dict(zip(places, _REGISTER_FORBIDDEN, strict=False))


def _above_paste(created: Worksheet, sheet: LoggedSheet) -> None:
    """Ostatni uporządkowany i żółty wiersz nad wklejeniem INTERMAX w kolumnach zlecenia arkusza ``sheet``."""

    columns = sorted(column_index_from_string(letter) for letter in sheet.columns)
    if not columns:
        return
    if sheet.last_ordered_row is not None:
        cell = created.cell(sheet.last_ordered_row, columns[0], _ORDERED_TEXT)
        cell.font = _ORDERED_FONT
    if sheet.yellow_row is not None:
        for column in range(columns[0], columns[-1] + 1):
            created.cell(sheet.yellow_row, column).fill = _YELLOW


def _preparation(record: RunLog, work: _Work) -> _Setup:
    # Kopia nie ma wyglądu komórek, a z wyglądu uporządkowanego wiersza Rejestru pamięć reguły danych wie, że jego
    # komórki stoją pod nagłówkiem (#918): wiersze mają krój uporządkowanych wierszy taty. Wiersz, który u taty go nie
    # miał, ma w Kopii maski w miejscu tekstu dwie kolumny na lewo od ``ADRES`` i ``NUMER UMOWY`` (u taty ``DATA`` i
    # ``NUMER ZL.``), więc różnicę z niego tłumaczy zastrzeżenie o maskach (``_masked_limits``).
    register, limits = _register_file(record, work, "rejestr", _ORDERED_FONT)
    periods = work.folder("okresy")
    configuration = _configured(work)
    forbidden, copy = ForbiddenValues(), InputCopy()
    inputs = PreparationInputs(
        register,
        periods,
        record.period,
        dry_run=record.mode == "podgląd",
        config_path=configuration["worker_config"],
        internal_template_path=configuration["internal_template"],
        collective_template_path=configuration["collective_template"],
        readers=FILE_READERS,
        forbidden=forbidden,
        copy=copy,
    )
    prepared = PreparedRun(PREPARATION, record.period, PREPARATION.core(_PROCESSES), inputs, copy)
    return _Setup(prepared, forbidden, limits)


def _preparation_limits(record: RunLog) -> list[Limit]:
    return _one_file_limits(record, "Przygotowanie pliku zbiorczego") or [
        Limit(
            "Surowe zlecenia na dole arkuszy Rejestru zleceń nie są w Kopii wejścia: odtworzony Rejestr ich nie ma, więc "
            "Zatrzymanie o nich się nie powtórzy"
        ),
        Limit(
            "folderu okresów taty Logi nie mają: odtworzenie zakłada Folder okresu w folderze „okresy”, więc Komunikat, "
            "który nazywa folder nad Folderem okresu, ma tę nazwę"
        ),
    ]


def _intermax(record: RunLog, work: _Work) -> _Setup:
    register, limits = _register_file(record, work, "intermax", _PASTED_FONT)
    moment = _intermax_moment(record, work)
    forbidden, copy = ForbiddenValues(), InputCopy()
    inputs = OrderingInputs(
        register,
        work.folder("Kopie INTERMAX"),
        now=lambda: moment,
        forbidden=forbidden,
        copy=copy,
    )
    prepared = PreparedRun(INTERMAX, inputs.period, INTERMAX.core(_PROCESSES), inputs, copy)
    return _Setup(prepared, forbidden, limits)


def _intermax_moment(record: RunLog, work: _Work) -> datetime:
    """Zegar procesu Uporządkowania u taty: chwila z nazwy Kopii INTERMAX w podsumowaniu, a bez niej start Uruchomienia
    w czasie tego komputera."""

    name = None if record.summary is None else record.summary.intermax_copy
    if name is not None:
        folder = work.folder("nazwa Kopii INTERMAX")
        (folder / name).touch()
        listed = intermax_copies.listed(folder)
        if listed:
            return listed[0].moment
    return record.started_at.astimezone()


def _intermax_limits(record: RunLog) -> list[Limit]:
    limits = _one_file_limits(record, "Uporządkowanie INTERMAX")
    if limits:
        return limits
    uncertain = [(sheet.sheet, sheet.uncertain_rows) for sheet in _the_file(record).sheets if sheet.uncertain_rows]
    if uncertain:
        where = "; ".join(f"arkusz {name}, wiersze {', '.join(map(str, rows))}" for name, rows in uncertain)
        return [
            Limit(
                f"Kopia wejścia ma wiersze INTERMAX bez pewnego położenia ({where}): brak w nich komórek DATA GODZ. "
                "POCZ., NUMER ZL., ZWROT i UWAGI, a strażnik mógł zamaskować w Kopii wartości z drugiego położenia "
                "(#913), więc odtworzenie nie zbuduje tych wierszy",
                blocking=True,
            )
        ]
    return [
        Limit(
            "dni uporządkowane nad wklejeniem nie są w Kopii wejścia: odtworzony INTERMAX ma nad wklejeniem tylko ostatni "
            "uporządkowany i żółty wiersz, więc odmowa dnia już uporządkowanego i wiersz z wyglądem z aplikacji nad "
            "uporządkowanymi się nie powtórzą"
        ),
        Limit("kolumn z aplikacji za UWAGI nie ma w Kopii wejścia: odtworzony INTERMAX ich nie ma"),
    ]


def _efenix(record: RunLog, work: _Work) -> _Setup:
    orders = record.efenix_orders or []
    source = _collective_file(record, work, atrapa_z_logow.file_addresses(orders))
    scope = read_scope(source)
    if not isinstance(scope, PricingScope):
        scoped: Sequence[atrapa_z_logow.ScopedOrder] = ()
    else:
        scoped = [atrapa_z_logow.ScopedOrder(order.row, order.number, order.address) for order in scope.orders]
    fed = atrapa_z_logow.fed(orders, scoped)
    today = work.efenix_today or record.started_at.astimezone().date()
    atrapa = work.stack.enter_context(atrapa_z_logow.started(fed, today))
    url = atrapa.url
    forbidden, copy = ForbiddenValues(), InputCopy()
    inputs = EfenixInputs(
        source,
        lambda _login: efenix_browser.chromium(url),
        pace=None,
        trace_directory=work.folder("Ślad Wyceny Emmetta"),
        forbidden=forbidden,
        copy=copy,
    )
    prepared = PreparedRun(EFENIX, record.period, EFENIX.core(_PROCESSES), inputs, copy)
    limits = [Limit(text, blocking=blocking) for text, blocking in fed.limits]
    return _Setup(prepared, forbidden, limits)


def _efenix_limits(record: RunLog) -> list[Limit]:
    limits = _collective_limits(record)
    if limits:
        return limits
    limits = [Limit(text, blocking=True) for text in atrapa_z_logow.unread(record.efenix_orders or [])]
    limits.append(
        Limit(
            "efenix to Atrapa efenix z odczytów stron w Logach, a nie efenix taty: budowa stron, odpowiedzi na zapis i "
            "ceny pozycji, których Logi nie wyznaczają, są Atrapy; Śladu Wyceny Emmetta z wcześniejszych Wycen Logi "
            "nie mają"
        )
    )
    if record.efenix_stop is not None:
        limits.append(
            Limit(
                f"Zatrzymanie okna efenix ({record.efenix_stop.cause.what}) zależy od strony efenix taty: na Atrapie "
                "się nie powtórzy"
            )
        )
    return limits


_PROCESSES: Final = Processes.default()
_KINDS: Final[Mapping[contract.ProcessKey, _Kind]] = {
    "settlement": _Kind(SETTLEMENT, _collective_limits, _settlement, ("worker_config", "worker_template")),
    "preparation": _Kind(
        PREPARATION, _preparation_limits, _preparation, ("worker_config", "internal_template", "collective_template")
    ),
    "intermax": _Kind(INTERMAX, _intermax_limits, _intermax),
    "efenix": _Kind(EFENIX, _efenix_limits, _efenix),
}
"""Odtworzenie każdego procesu z katalogu procesów (``contract.ProcessKey``)."""


# --- przebieg -------------------------------------------------------------------------------------------------------


class _Tata:
    """Rozmówca odtworzenia jak tata w Logach: zgoda w Decyzji taty, chyba że Logi kończą się odmową, i ostatni widok
    postępu, jak karta Centrum (``runs._Run``)."""

    continue_hint = CONTINUE_HINT

    def __init__(self, prepared: PreparedRun[Any, Any], consent: bool) -> None:
        self._prepared = prepared
        self._consent = consent
        self.progress = prepared.progress_view(ProgressProjection().snapshot)

    def confirm(self, decision: Decision) -> bool:
        return self._consent

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        self.progress = self._prepared.progress_view(snapshot)

    @contextmanager
    def waiting(self) -> Iterator[None]:
        yield


def _run(record: RunLog, setup: _Setup, work: Path) -> RunLog:
    """Uruchomienie odtworzenia przez rdzeń procesu i jego Logi po strażniku, jak w Centrum (``RunLogs.run_ended``)."""

    prepared = setup.prepared
    tata = _Tata(prepared, consent=record.ending != "declined")
    info = prepared.declaration.run_info(run_id=record.run_id, period=record.period, dry_run=prepared.dry_run)
    started_at = datetime.now(timezone.utc)
    core = run_process(
        prepared.process,
        prepared.inputs,
        tata,
        view=prepared.declaration.view.shown,
        metrics_path=work / "metryki.jsonl",
    )
    stop = None if isinstance(core.ending, Finished) else core.ending
    ended = EndedRun(
        info=info,
        core=core,
        stopped=None if stop is None else _stopped(info, stop),
        progress=tata.progress,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        input_copy=prepared.input_copy,
    )
    environment = Environment(system=platform.platform(), python=platform.python_version(), files=None)
    replayed = RunLog.of(
        ended,
        tool=record.tool,
        environment=environment,
        dad_actions=DadActions(entries=[], omitted=0),
    )
    return guarded(replayed, setup.forbidden)


def _stopped(info: contract.RunInfo, stop: Stop) -> StoppedRun:
    """Zatrzymanie odtworzenia tak, jak je nazywa Centrum (``Stops.ended``) bez Powtórki, Diagnozy i Zgłoszenia."""

    kind = "declined" if stop.kind == "declined" else stop.stop_kind
    return StoppedRun(info, stop, ProblemFingerprint.of(info.process, stop.message), kind, None, None)


# --- porównanie -----------------------------------------------------------------------------------------------------


def _copied(files: list[dict[str, Any]] | None) -> object:
    return (
        None
        if files is None
        else [{key: value for key, value in file.items() if key != "fingerprint"} for file in files]
    )


def _steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in step.items() if key not in ("started_at", "duration_ms")} for step in steps]


def _orders(orders: list[dict[str, Any]] | None) -> object:
    return None if orders is None else [{**order, "steps": _steps(order["steps"])} for order in orders]


def _window_stop(stop: dict[str, Any] | None) -> object:
    if stop is None:
        return None
    failed = stop["failed"]
    return {
        **stop,
        "steps": _steps(stop["steps"]),
        "failed": None if failed is None else _steps([failed])[0],
    }


_COMPARED: Final[tuple[tuple[str, Callable[[dict[str, Any]], object]], ...]] = (
    ("Kopia wejścia", lambda logs: _copied(logs["input_copy"])),
    ("wynik", lambda logs: logs["result"]),
    ("zakończenie", lambda logs: logs["ending"]),
    (
        "Rodzaj Zatrzymania",
        lambda logs: "for_tata" if logs["stop_kind"] == "repeated" else logs["stop_kind"],
    ),
    ("Komunikaty", lambda logs: logs["messages"]),
    ("uwagi techniczne", lambda logs: logs["technical_notes"]),
    ("podsumowanie", lambda logs: logs["summary"]),
    ("liczba problemów", lambda logs: logs["issue_count"]),
    (
        "etapy",
        lambda logs: [{"phase": phase["phase"], "state": phase["state"]} for phase in logs["phases"]],
    ),
    (
        "Szablony pracownika",
        lambda logs: [
            {key: template[key] for key in ("wykonawca", "outcome", "rows")} for template in logs["templates"]
        ],
    ),
    ("Ilości tylko dla INEA", lambda logs: logs["inea_only_cleared"]),
    ("Wpisy INTERMAX", lambda logs: logs["intermax_entries"]),
    ("ślad zleceń efenix", lambda logs: _orders(logs["efenix_orders"])),
    ("Zatrzymanie okna efenix", lambda logs: _window_stop(logs["efenix_stop"])),
    ("ślad wywołań", lambda logs: logs["trace"]),
)
"""Porównane części Logów w kolejności przyczyn i ich postać bez czasów, chwil i odcisków."""
_FIELDS: Final = {
    "Kopia wejścia": "input_copy",
    "wynik": "result",
    "zakończenie": "ending",
    "Rodzaj Zatrzymania": "stop_kind",
    "Komunikaty": "messages",
    "uwagi techniczne": "technical_notes",
    "podsumowanie": "summary",
    "liczba problemów": "issue_count",
    "etapy": "phases",
    "Szablony pracownika": "templates",
    "Ilości tylko dla INEA": "inea_only_cleared",
    "Wpisy INTERMAX": "intermax_entries",
    "ślad zleceń efenix": "efenix_orders",
    "Zatrzymanie okna efenix": "efenix_stop",
    "ślad wywołań": "trace",
}


def first_difference(logged: RunLog, replayed: RunLog) -> Difference | None:
    """Pierwsza różnica Logów odtworzenia ``replayed`` od Logów ``logged`` w porównanych częściach (``_COMPARED``)."""

    left, right = logged.model_dump(), replayed.model_dump()
    for name, view in _COMPARED:
        found = _walk(view(left), view(right), f"{name} ({_FIELDS[name]})")
        if found is not None:
            return found
    return None


def _walk(logged: object, replayed: object, place: str) -> Difference | None:
    if isinstance(logged, dict) and isinstance(replayed, dict):
        for key in [*logged, *(key for key in replayed if key not in logged)]:
            inner = f"{place}.{key}"
            if key not in replayed or key not in logged:
                return Difference(inner, logged.get(key, _MISSING), replayed.get(key, _MISSING))
            found = _walk(logged[key], replayed[key], inner)
            if found is not None:
                return found
        return None
    if isinstance(logged, list) and isinstance(replayed, list):
        # zip kończy się na krótszej liście: inną długość zgłasza warunek za pętlą
        for index, (left, right) in enumerate(zip(logged, replayed, strict=False)):
            found = _walk(left, right, f"{place}[{_label(index, left)}]")
            if found is not None:
                return found
        if len(logged) != len(replayed):
            index = min(len(logged), len(replayed))
            longer = logged if len(logged) > len(replayed) else replayed
            left = logged[index] if index < len(logged) else _MISSING
            right = replayed[index] if index < len(replayed) else _MISSING
            return Difference(f"{place}[{_label(index, longer[index])}]", left, right)
        return None
    return None if _same(logged, replayed) else Difference(place, logged, replayed)


def _same(logged: object, replayed: object) -> bool:
    """Ta sama wartość: liczba całkowita i ułamek o tej samej wartości tak (zapis pliku zmienia 5.0 w 5), ``Decimal`` po
    wartości (``21.0`` to ``21``), a prawda/fałsz i liczba nie."""

    if isinstance(logged, bool) or isinstance(replayed, bool):
        return type(logged) is type(replayed) and logged == replayed
    if isinstance(logged, (int, float)) and isinstance(replayed, (int, float)):
        return logged == replayed
    return type(logged) is type(replayed) and logged == replayed


def _label(index: int, element: object) -> str:
    """Miejsce w liście: numer od 0 i, gdy element go ma, arkusz, wiersz albo nazwa pliku."""

    if isinstance(element, dict):
        for key, name in (
            ("sheet", "arkusz"),
            ("row", "wiersz"),
            ("worker", "Wykonawca"),
            ("wykonawca", "Wykonawca"),
            ("name", "plik"),
            ("phase", "etap"),
            ("code", "kod"),
        ):
            if isinstance(element.get(key), (str, int)) and not isinstance(element.get(key), bool):
                return f"{index}: {name} {element[key]}"
    return str(index)


def _shown(value: object) -> str:
    if value is _MISSING:
        return _MISSING
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 300 else f"{text[:297]}..."
