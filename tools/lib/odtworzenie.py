"""Odtworzenie Uruchomienia procesu z jego Logów na kodzie tego drzewa (#847): wejście z Kopii wejścia, ten sam proces
i tryb, a w miejscu efenix Atrapa efenix z odczytów stron; wynik to raport z pierwszą różnicą i granicami Logów.

Jedyną operacją jest ``replay()``. Kształt danych:

- Logi Uruchomienia (``run_logs.RunLog`` tego drzewa) dają proces, tryb, okres, wynik i ślad do porównania, a Kopia
  wejścia wiersze plików taty. Wpisanie raportów ma maile ze Skrzynki raportów tylko jako Wpisy raportu w Logach
  (``report_entering``, wejście kliknięcia z nich daje ``LoggedReports.replay``), więc odtworzenie podaje je procesowi
  jako maile w postaci kanonicznej (``worker_reports.as_mail``) od adresów ``@odtworzenie.invalid``, z Listą
  Wykonawców z loginów Wpisów oraz z pamięcią wpisów i decyzjami „Zostaw moją” sprzed kliknięcia z Logów.
- Granice (``Limit``) to to, czego Logi nie niosą. Granica blokująca (Logi bez Kopii wejścia, Urwane Uruchomienie,
  pusta Kopia, komórka typu, którego Kopia nie zapisała, Logi Wyceny bez odczytu wyników szukania, wiersz Kopii albo
  zlecenie śladu efenix, które strażnik reguły danych pominął) kończy odtworzenie bez uruchomienia procesu: wynik
  takiego odtworzenia nic by nie znaczył; to samo numer Wpisu raportu z maską strażnika i numer pamięci wpisów, którego
  nie ma w jednym Wpisie. Zastrzeżenie (maski strażnika w Kopii i w czynnościach Wpisów, wiersz Rejestru zleceń albo
  INTERMAX w obu położeniach bez komórek dozwolonych tylko w jednym, pole albo element, które strażnik pominął poza
  wejściem, Wzorce spoza Logów, Surowe zlecenia, dni nad wklejeniem, Atrapa w miejscu efenix, maile w postaci
  kanonicznej zamiast maili taty) raport podaje przy każdym wyniku, bo może tłumaczyć różnicę.
- Pliki wejścia powstają w katalogu roboczym z Kopii wejścia, pod tą samą nazwą w folderach o tych samych nazwach co
  u taty (``CopiedFile.folders``), więc Komunikaty nazywają te same plik i folder: każdy arkusz z nagłówkami i
  wierszami pod tymi samymi numerami, przesunięty pierwszy wiersz wklejenia INTERMAX znowu przesunięty, a nad
  wklejeniem ostatni uporządkowany i żółty wiersz w tych samych wierszach co u taty. Wiersze Rejestru zleceń
  Przygotowania mają krój uporządkowanych wierszy taty (Calibri 8), bo pierwszy wiersz bloku bez niego pamięć reguły
  danych zna dwie kolumny na lewo od nagłówka (#918), wiersze wklejenia INTERMAX krój wiersza z aplikacji, a wiersze
  INTERMAX Wpisania raportów krój uporządkowanych wierszy, bo Kopia ma tylko uporządkowane wiersze. W miejscu kolumn
  ``ADRES`` i numeru Orange stoją wartości syntetyczne z numerem wiersza (``SYNTHETIC_ADDRESS``, ``SYNTHETIC_ORANGE``),
  których żaden plik taty nie ma. Wzorce i Listę Wykonawców (``wykonawcy.yaml``) daje folder ``configuration``, bo Logi
  mają z nich tylko nazwę i rozmiar. Reguły ilości ze startu Uruchomienia są w Logach (``RunLog.quantity_rules``), a
  Przygotowanie i Przebieg z Logów sprzed ich zapisu liczą Regułami ilości z Wydania tego drzewa (zastrzeżenie).
- Proces biegnie przez to samo Uruchomienie co w Centrum (``process_kind.PreparedRun.conduct``: ten sam rdzeń i wpis
  katalogu procesów), z Kopią wejścia i pamięcią reguły danych, a Logi odtworzenia składają ``EndedRun.of``,
  ``logs_of`` i strażnik (``guard_logs``), jak w Centrum. Decyzję taty odtworzenie rozstrzyga tak jak tata: odmowa
  tylko wtedy, gdy Logi kończą się odmową.
- Porównanie (``first_difference``) idzie po polach Logów w kolejności przyczyn: Kopia wejścia (czy pliki z Kopii
  czytają się tak samo), wynik, zakończenie i Rodzaj Zatrzymania, Komunikaty, uwagi techniczne, podsumowanie, liczba
  problemów, etapy, Szablony pracownika, Ilości tylko dla INEA, Wpisy INTERMAX, Wpisanie raportów, ślad zleceń i
  Zatrzymanie okna efenix oraz ślad wywołań. Raport podaje przyczynę Zatrzymania z Logów (``stop_cause``): przyczynę techniczną Zatrzymania
  okna efenix i łańcuch wyjątków śladu wywołań z drogą startu okna, która zawiodła (#976). Czasy i chwile kroków, odciski plików, środowisko, dziennik działań taty i uwagi strażnika o Kopii
  wejścia są poza porównaniem: zależą od komputera i chwili, a nie od kodu i wejścia.

Odtworzenie pisze tylko w katalogu roboczym (``work``): pliki wejścia, Rozliczenia i Kopie INTERMAX, które proces
zapisuje, i metryki. Nic nie idzie do Skrzynki Zgłoszeń, bo odtworzenie nie ma Kolejki wysyłki.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import enum
import json
from pathlib import Path
import platform
from typing import Any, Final, assert_never

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia import collective_layout, intermax_copies
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.catalog import CATALOG, declaration_of
from rozliczenia.centrum.dad_actions import DadActions
from rozliczenia.centrum.logs_disk import name_of
from rozliczenia.centrum import stops
from rozliczenia.centrum.logs_of_run import logs_of
from rozliczenia.centrum.efenix_chrome import atrapa_opening
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.settings.files import FieldProblem
from rozliczenia.centrum.settings.memory import settings_bytes
from rozliczenia.centrum.settings.workers import WORKERS, WORKERS_FILE
from rozliczenia.centrum.process_kind import (
    ConfigurationNeed,
    HostParts,
    PathNeed,
    PeriodProcessKind,
    PreparedRun,
    ProcessKind,
    Start,
    startable,
)
from rozliczenia.centrum.report_entering_logs import EnteringReplay, ReplayedOrderless, Unreplayable
from rozliczenia.centrum.run_logs import Environment, LoggedCell, LoggedInputFile, LoggedSheet, LoggedTyped, RunLog, StartFacts
from rozliczenia.centrum.run_logs_guard import GuardCut, guard_cuts, guard_logs
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.client_data import MASKS, ForbiddenColumn, ForbiddenValues, empty_memory, forbidden_columns
from rozliczenia.collective_layout import ADDRESS_COLUMN, HEADER_ROW
from rozliczenia.dad_files import DadFiles
from rozliczenia.decision import Decision
from rozliczenia.efenix_orders import PricingScope, read_scope
from rozliczenia.period_folder import PeriodFolder
from rozliczenia.raw_orders import SHIFT
from rozliczenia.register_columns import (
    COLUMNS,
    DATE,
    DAY_FILL,
    ORDER_NUMBER,
    ORDERED_FONT,
    ORDERED_SIZE,
    WORKER,
    Column,
)
from rozliczenia.intermax_cells import CellsWritten
from rozliczenia.process_run import Finished
from rozliczenia.progress import ProgressProjection, ProgressSnapshot
from rozliczenia.quantity_engine import QuantityRules, RulesProblem
from rozliczenia.quantity_rules_file import DEFAULT_QUANTITY_RULES
from rozliczenia.report_entering import ClickResult, ReportEnteringParts, SavedState
from rozliczenia import report_entering_messages
from rozliczenia.run_context import RunContexts
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.text import normalize_text
from rozliczenia.workbook_files import FORBIDDEN_POSITIONS
from rozliczenia.worker_list import WorkerEntry, WorkerList
from rozliczenia.worker_reports import Login, OwnEntries, ReadStranger, SenderAddress, as_mail

from atrapy.skrzynka_raportow import FakeInbox
import atrapa_z_logow

SYNTHETIC_ADDRESS: Final = atrapa_z_logow.SYNTHETIC_ADDRESS
SYNTHETIC_ORANGE: Final = "ORANGE-ODTWORZENIE-{row}"

_SYNTHETIC: Final = {ForbiddenColumn.ADDRESS: SYNTHETIC_ADDRESS, ForbiddenColumn.ORANGE: SYNTHETIC_ORANGE}
_COLLECTIVE_FORBIDDEN: Final = {collective_layout.letter(column): forbidden for forbidden, column in FORBIDDEN_POSITIONS}
"""Zakazane kolumny Pliku zbiorczego z układu Wzorca; nagłówek to nazwa kolumny w regule danych, jak we Wzorcu."""
_ADDRESS: Final = collective_layout.letter(ADDRESS_COLUMN)
_REGISTER_FORBIDDEN: Final = {
    column.register_header: forbidden
    for column in COLUMNS
    for forbidden, _ in forbidden_columns({normalize_text(column.target_header): column})
}
"""Nagłówek Rejestru zleceń i INTERMAX (``ADRES``, ``NUMER UMOWY``) każdej kolumny, której Kopia wejścia nie ma."""
_ORDERED_FONT: Final = Font(name=ORDERED_FONT, sz=ORDERED_SIZE)
"""Krój uporządkowanego wiersza Rejestru zleceń i INTERMAX (``raw_orders.ordered_look``)."""
_PASTED_FONT: Final = Font(name="Roboto", sz=4)
"""Krój wiersza wklejonego z aplikacji firmowej, bez wyglądu uporządkowanego (``raw_orders.ordered_look``)."""
_YELLOW: Final = PatternFill("solid", fgColor=f"FF{DAY_FILL}")
"""Żółty wiersz, którym tata oddziela dni w INTERMAX."""
_ORDERED_TEXT: Final = "uporządkowany wiersz odtworzenia"
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

        title = declaration_of(record.process).title
        blocking = [limit.text for limit in self.limits if limit.blocking]
        first = f"{self.verdict.headline}: {blocking[0]}" if blocking else self.verdict.headline
        lines = [
            first,
            f"Uruchomienie: {title}, {record.mode.word}, okres {record.period}, {name_of(record.start)}",
            f"Kod: {code}",
        ]
        if (cause := stop_cause(record)) is not None:
            lines.append(f"Przyczyna w Logach: {cause}")
        if self.difference is not None:
            lines += [
                f"Pierwsza różnica: {self.difference.field}",
                f"  Logi:        {_shown(self.difference.logged)}",
                f"  Odtworzenie: {_shown(self.difference.replayed)}",
            ]
        if self.verdict is not Verdict.IMPOSSIBLE:
            lines.append(f"Porównano: {', '.join(part.name for part in COMPARED)}.")
            lines.append(
                "Poza porównaniem: czasy i chwile kroków, odciski plików, środowisko, dziennik działań taty, wygląd "
                "komórek (Kopia wejścia go nie ma) i zapisane pliki."
            )
        rest = [limit.text for limit in self.limits if not limit.blocking] + blocking[1:]
        if rest:
            lines.append("Granice:")
            lines += [f"- {text}" for text in rest]
        return lines


def stop_cause(record: RunLog) -> str | None:
    """Przyczyna Zatrzymania z Logów dla Maksa (#976); ``None``: Logi bez Zatrzymania okna efenix i bez śladu wywołań.

    Z Zatrzymania okna efenix: miejsce (przy starcie okna albo wiersz zlecenia z miejscem w przebiegu) i przyczyna
    techniczna ze szczegółami (działanie przeglądarki, typ błędu, status HTTP, element). Ze śladu wywołań: łańcuch
    wyjątków od Zatrzymania do źródła, w którym zaraz po Zatrzymaniu stoi wyjątek okna, czyli droga startu, która
    zawiodła (``EfenixUnreachable``, ``BrowserNotStarted``), i ostatnia ramka kodu narzędzia bezpośredniej przyczyny
    (bez przyczyny: samego wyjątku), czyli miejsce, w którym ta droga powstała.
    """

    parts: list[str] = []
    stop = record.efenix_stop
    if stop is not None:
        cause = stop.cause
        where = "przy starcie okna" if stop.row is None else f"przy wierszu {stop.row} ({stop.order} z {stop.orders})"
        status = None if cause.status is None else f"HTTP {cause.status}"
        details = [detail for detail in (cause.operation, cause.error_type, status, cause.element) if detail is not None]
        parts.append(f"okno efenix {where}: {cause.what}" + (f" ({', '.join(details)})" if details else ""))
    trace = record.trace
    if trace is not None:
        chain = [trace.exception_type, *(cause.exception_type for cause in trace.causes)]
        frames = trace.causes[0].frames if trace.causes else trace.frames
        raised = "" if not frames else f", powstał w {frames[-1].file}:{frames[-1].line} w {frames[-1].function}"
        parts.append(f"wyjątki {' ← '.join(chain)}{raised}")
    return "; ".join(parts) or None


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

    kind = CATALOG.kind(record.process)
    rebuild = _rebuild(record.process)
    limits = _limits(record, kind, rebuild, configuration)
    if any(limit.blocking for limit in limits):
        return Report(Verdict.IMPOSSIBLE, None, tuple(limits))
    with ExitStack() as stack:
        here = _Work(work, configuration, efenix_today, stack)
        rebuilt = rebuild.files(record, here)
        limits += rebuilt.limits
        if any(limit.blocking for limit in rebuilt.limits):
            return Report(Verdict.IMPOSSIBLE, None, tuple(limits))
        memory = empty_memory()
        replayed = _run(record, _prepared(record, kind, rebuilt, here, memory), memory)
    difference = first_difference(record, replayed)
    return Report(
        Verdict.AGREES if difference is None else Verdict.DIFFERS,
        difference,
        tuple(limits),
        replayed,
    )


# --- granice --------------------------------------------------------------------------------------------------------


def _limits(record: RunLog, kind: ProcessKind[Any, Any], rebuild: _Rebuild, configuration: Path | None) -> list[Limit]:
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
    limits = [
        *_guard_limits(record),
        *_typed_limits(copied),
        *_masked_limits(record),
        *_rules_limits(record, kind),
        *rebuild.limits(record),
    ]
    names = _from_configuration(kind, rebuild)
    if names:
        limits.append(_configuration_limit(record, configuration, names))
    if record.stop_kind == "repeated":
        limits.append(
            Limit(
                "Powtórka zależy od poprzedniego Zatrzymania w tej samej pracy Centrum: odtworzenie porównuje ją jak "
                "Zatrzymanie dla taty"
            )
        )
    return limits


def _guard_limits(record: RunLog) -> list[Limit]:
    """Miejsca Logów, które strażnik reguły danych pominął albo zostawił puste (``guard_cuts``), bo maska trafiła
    w pole, które jej nie przyjmuje. W wejściu odtworzenia (Kopia wejścia bez odcisku pliku, ślad zleceń efenix, z którego
    powstaje Atrapa, każde pole Logów Wpisania raportów, bo wejście buduje się z wielu z nich) to granica blokująca:
    odtworzone wejście nie jest wejściem taty, a różnica wskazałaby fałszywą przyczynę. Poza wejściem to zastrzeżenie:
    różnica w tym miejscu jest skutkiem maski."""

    limits: list[Limit] = []
    for cut in guard_cuts(record):
        lost = "pominął" if cut.removed else "zostawił puste"
        place = f"{lost} w Logach {cut.place} (maska w polu, które jej nie przyjmuje)"
        if _replay_input(cut):
            limits.append(Limit(f"strażnik reguły danych {place}, a odtworzenie buduje z niego wejście", blocking=True))
        else:
            limits.append(Limit(f"Strażnik reguły danych {place}: różnica w tym miejscu jest skutkiem maski"))
    return limits


def _replay_input(cut: GuardCut) -> bool:
    return cut.field in ("efenix_orders", "report_entering") or (
        cut.field == "input_copy" and ".fingerprint" not in cut.place
    )


def _rules_limits(record: RunLog, kind: ProcessKind[Any, Any]) -> list[Limit]:
    """Reguły ilości ze startu z Logów: bez nich (Logi sprzed ich zapisu) proces, który nimi liczy, odtworzenie liczy
    Regułami ilości z Wydania tego drzewa, a reguły, których nie da się odczytać albo które mają maskę strażnika reguły
    danych, kończą odtworzenie: wynik z innymi regułami nic by nie znaczył."""

    logged = record.quantity_rules
    if not kind.quantity_rules:
        return []
    if logged is None:
        return [
            Limit(
                "Logi nie mają Reguł ilości Uruchomienia (Logi sprzed ich zapisu), więc odtworzenie liczy Regułami ilości "
                "z Wydania tego drzewa: reguły taty z Ustawień mogły dać inne ilości"
            )
        ]
    masked = sorted({mask for mask in MASKS if mask in json.dumps(logged.model_dump(), ensure_ascii=False)})
    if masked:
        return [
            Limit(
                f"Reguły ilości w Logach mają maski strażnika reguły danych ({', '.join(masked)}), więc odtworzenie nie zna "
                "reguł Uruchomienia",
                blocking=True,
            )
        ]
    value = logged.value()
    if isinstance(value, RulesProblem):
        return [Limit(f"Reguł ilości z Logów nie da się odczytać ({value.field}: {value.message})", blocking=True)]
    return []


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


def _configuration_limit(record: RunLog, configuration: Path | None, names: Sequence[str]) -> Limit:
    """Lista Wykonawców i Wzorce (pliki ``names``) z folderu ``configuration``: bez folderu odtworzenie nie biegnie, a
    plik, którego w nim nie ma, i rozmiar inny niż plik taty w Logach (``environment.files``) raport nazywa."""

    if configuration is None or not configuration.is_dir():
        return Limit(
            f"nie ma folderu z Listą Wykonawców i Wzorcami ({configuration or 'brak'}, --konfiguracja): Logi ich "
            "nie niosą, a proces bez nich nie biegnie",
            blocking=True,
        )
    logged = {file.name: file.size for file in (record.environment.files or ())}
    paths = [configuration / name for name in names]
    missing = [path.name for path in paths if not path.is_file()]
    sizes = [
        f"{path.name}: u taty {logged[path.name]} B, tu {path.stat().st_size} B"
        for path in paths
        if path.is_file() and logged.get(path.name) not in (None, path.stat().st_size)
    ]
    text = (
        f"Lista Wykonawców i Wzorce nie są w Logach: odtworzenie czyta je z {configuration}, a Logi mają tylko "
        "nazwę i rozmiar plików taty"
    )
    if missing:
        text += f"; w folderze nie ma: {', '.join(missing)}"
    if sizes:
        text += f"; inny rozmiar niż u taty: {'; '.join(sizes)}"
    return Limit(text)


# --- pliki wejścia --------------------------------------------------------------------------------------------------


@dataclass
class _Work:
    """Katalog roboczy odtworzenia, folder Konfiguracji, dzień Atrapy i stos zasobów (Atrapa) na czas przebiegu."""

    directory: Path
    configuration: Path | None
    efenix_today: date | None
    stack: ExitStack

    def path(self, *parts: str) -> Path:
        path = self.directory.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def folder(self, *parts: str) -> Path:
        folder = self.directory.joinpath(*parts)
        folder.mkdir(parents=True, exist_ok=True)
        return folder


@dataclass(frozen=True)
class _Rebuilt:
    """Pliki wejścia odbudowane z Logów pod potrzebami procesu (bez Konfiguracji, którą daje folder Konfiguracji),
    zależności gospodarza i granice, które odbudowa znalazła po drodze."""

    paths: Mapping[PathNeed, Path]
    parts: HostParts = field(default_factory=HostParts)
    limits: list[Limit] = field(default_factory=list)
    workers: WorkerList | None = None


@dataclass(frozen=True)
class _Rebuild:
    """Odtworzenie jednego procesu w tym, czego katalog procesów nie wie: granice Logów i odbudowa plików z Logów.
    ``workers``: odbudowa daje Listę Wykonawców z Logów, więc nie bierze się ona z folderu Konfiguracji."""

    limits: Callable[[RunLog], list[Limit]]
    files: Callable[[RunLog, _Work], _Rebuilt]
    workers: bool = False


def _cell(value: LoggedCell) -> _Written:
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
            created[f"{_ADDRESS}{row.row}"] = addresses[row.row]
    path = work.path("okresy", *(copied.folders or [record.period]), copied.name)
    workbook.save(path)
    return path


def _collective_limits(record: RunLog) -> list[Limit]:
    limits = _one_file_limits(record, "proces")
    if limits:
        return limits
    sheets = _the_file(record).sheets
    if len(sheets) != 1 or sheets[0].header_row != HEADER_ROW:
        return [
            Limit(
                f"Kopia Pliku zbiorczego nie ma jednego arkusza z nagłówkami w wierszu {HEADER_ROW}",
                blocking=True,
            )
        ]
    return []


def _settlement(record: RunLog, work: _Work) -> _Rebuilt:
    return _Rebuilt({"collective_file": _collective_file(record, work, {})})


def _register_file(
    record: RunLog, work: _Work, folder: str, font: Callable[[LoggedSheet, int], Font]
) -> tuple[Path, list[Limit]]:
    """Rejestr zleceń albo INTERMAX z Kopii wejścia: arkusze z nagłówkami w wierszu 1 i wierszami pod ich numerami.

    Kolumn ``ADRES`` i ``NUMER UMOWY`` Kopia nie ma, więc ich nagłówki stoją w pierwszych kolumnach bez nagłówka między
    kolumnami Kopii (u taty tam stoją), a gdy takich nie ma, za ostatnią; ich komórki mają wartości syntetyczne.
    Przesunięty pierwszy wiersz wklejenia INTERMAX stoi znowu dwie kolumny w lewo, a nad wklejeniem ostatni
    uporządkowany wiersz (Calibri 8, bez daty) i żółty wiersz stoją tam, gdzie u taty. ``font``: krój komórek wiersza
    (numer) arkusza z Kopii.
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
            shift = SHIFT if row.row == sheet.shifted_row else 0
            for letter, value in row.cells.items():
                created.cell(row.row, column_index_from_string(letter) - shift, _cell(value)).font = font(sheet, row.row)
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
    columns = sorted(column_index_from_string(letter) for letter in sheet.columns)
    if not columns:
        return
    if sheet.last_ordered_row is not None:
        cell = created.cell(sheet.last_ordered_row, columns[0], _ORDERED_TEXT)
        cell.font = _ORDERED_FONT
    if sheet.yellow_row is not None:
        for column in range(columns[0], columns[-1] + 1):
            created.cell(sheet.yellow_row, column).fill = _YELLOW


def _preparation(record: RunLog, work: _Work) -> _Rebuilt:
    # Kopia nie ma wyglądu komórek, a z wyglądu uporządkowanego wiersza Rejestru pamięć reguły danych wie, że jego
    # komórki stoją pod nagłówkiem (#918): wiersze mają krój uporządkowanych wierszy taty (``_register_font``). Pierwszy
    # wiersz bloku wklejenia u taty (bez tego wyglądu) nie ma w Kopii komórek, które w jego położeniu stoją pod
    # ``ADRES`` i ``NUMER UMOWY`` (u taty ``DATA`` i ``NUMER ZL.``), a różnicę z wiersza z siatki tłumaczy zastrzeżenie
    # o nim (``_preparation_limits``).
    register, limits = _register_file(record, work, "rejestr", _register_font)
    return _Rebuilt({"register": register, "periods_directory": work.folder("okresy")}, limits=limits)


def _register_font(sheet: LoggedSheet, row: int) -> Font:
    """Krój wiersza Rejestru zleceń Przygotowania: wiersz z siatki ma krój wiersza z aplikacji, więc pod
    uporządkowanymi znowu zaczyna blok, a każdy inny krój uporządkowanych wierszy taty. Wiersz z siatki ze śladem
    przesunięcia (data z godziną dwie kolumny przed ``DATA GODZ. POCZ.``) się nie powtarza, bo tej kolumny Kopia
    Przygotowania nie ma; różnicę z niego tłumaczy zastrzeżenie o wierszach w obu położeniach."""

    return _PASTED_FONT if row in sheet.uncertain_rows else _ORDERED_FONT


def _preparation_limits(record: RunLog) -> list[Limit]:
    limits = _one_file_limits(record, "Przygotowanie pliku zbiorczego")
    if limits:
        return limits
    uncertain = _uncertain_rows(record)
    if uncertain:
        limits.append(
            Limit(
                f"Kopia wejścia ma wiersze Rejestru zleceń w obu położeniach ({uncertain}): to wiersze z siatki reguły "
                "położenia (ślad przesunięcia albo pierwszy wiersz bloku, którego przesunięcia nie widać), a nie ma w nich "
                "komórek, które w którymś położeniu stałyby pod ADRES, NUMER UMOWY albo poza kolumnami Rejestru, które "
                "czyta Przygotowanie (u taty NUMER ZL. i DATA GODZ. POCZ., gdy nie jest datą z godziną), więc odtworzony "
                "wiersz ich nie ma, a Planowanie może zdecydować inaczej (ADR 0025)"
            )
        )
    return [
        *limits,
        Limit(
            "Surowe zlecenia na dole arkuszy Rejestru zleceń nie są w Kopii wejścia: odtworzony Rejestr ich nie ma, więc "
            "Zatrzymanie o nich się nie powtórzy"
        ),
        Limit(
            "folderu okresów taty Logi nie mają: odtworzenie zakłada Folder okresu w folderze „okresy”, więc Komunikat, "
            "który nazywa folder nad Folderem okresu, ma tę nazwę"
        ),
    ]


def _intermax(record: RunLog, work: _Work) -> _Rebuilt:
    register, limits = _register_file(record, work, "intermax", lambda sheet, row: _PASTED_FONT)
    moment = _intermax_moment(record, work)
    return _Rebuilt(
        {"register": register, "copies_directory": work.folder("Kopie INTERMAX")}, HostParts(now=lambda: moment), limits
    )


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
    where = _uncertain_rows(record)
    if where:
        limits.append(
            Limit(
                f"Kopia wejścia ma wiersze INTERMAX w obu położeniach ({where}): to wiersze z siatki reguły położenia "
                "(ślad przesunięcia albo pierwszy wiersz bloku, którego przesunięcia nie widać), a nie ma "
                "w nich komórek, które w którymś położeniu stałyby pod "
                "ADRES, NUMER UMOWY albo za UWAGI (NUMER ZL., ZWROT, UWAGI i DATA GODZ. POCZ., gdy nie jest datą z "
                "godziną), więc odtworzony wiersz ich nie ma, a reguła, która je czyta, może zdecydować inaczej (ADR 0025)"
            )
        )
    return [
        *limits,
        Limit(
            "dni uporządkowane nad wklejeniem nie są w Kopii wejścia: odtworzony INTERMAX ma nad wklejeniem tylko ostatni "
            "uporządkowany i żółty wiersz, więc odmowa dnia już uporządkowanego i wiersz z wyglądem z aplikacji nad "
            "uporządkowanymi się nie powtórzą"
        ),
        Limit("kolumn z aplikacji za UWAGI nie ma w Kopii wejścia: odtworzony INTERMAX ich nie ma"),
    ]


def _uncertain_rows(record: RunLog) -> str:
    """Wiersze w obu położeniach (``uncertain_rows``) każdego arkusza Kopii wejścia jedynego pliku, po arkuszach; pusty
    napis, gdy ich nie ma."""

    uncertain = [(sheet.sheet, sheet.uncertain_rows) for sheet in _the_file(record).sheets if sheet.uncertain_rows]
    return "; ".join(f"arkusz {name}, wiersze {', '.join(map(str, rows))}" for name, rows in uncertain)


def _efenix(record: RunLog, work: _Work) -> _Rebuilt:
    orders = record.efenix_orders or []
    source = _collective_file(record, work, atrapa_z_logow.file_addresses(orders))
    # Zakres tylko do budowy Atrapy efenix: ten odczyt nie należy do Uruchomienia, więc nie trafia do jego Kopii.
    scope = read_scope(source, DadFiles())
    if not isinstance(scope, PricingScope):
        scoped: Sequence[atrapa_z_logow.ScopedOrder] = ()
    else:
        scoped = [atrapa_z_logow.ScopedOrder(order.row, order.number, order.address) for order in scope.orders]
    fed = atrapa_z_logow.fed(orders, scoped)
    today = work.efenix_today or record.started_at.astimezone().date()
    atrapa = work.stack.enter_context(atrapa_z_logow.started(fed, today))
    limits = [Limit(text, blocking=blocking) for text, blocking in fed.limits]
    return _Rebuilt({"collective_file": source}, HostParts(efenix=atrapa_opening(atrapa.url)), limits)


def _efenix_limits(record: RunLog) -> list[Limit]:
    limits = _collective_limits(record)
    if limits:
        return limits
    limits = [Limit(text, blocking=True) for text in atrapa_z_logow.unread(record.efenix_orders or [])]
    limits.append(
        Limit(
            "efenix to Atrapa efenix z odczytów stron w Logach, a nie efenix taty: budowa stron, odpowiedzi na zapis i "
            "ceny pozycji, których Logi nie wyznaczają, są Atrapy"
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


# Wpisanie raportów: INTERMAX z Kopii wejścia, a maile ze Skrzynki raportów z Wpisów w Logach w postaci kanonicznej.

_REPLAY_DOMAIN: Final = "odtworzenie.invalid"
"""Domena adresów nadawców w odtworzeniu: adresów taty Logi nie mają, a ``.invalid`` nie jest adresem nikogo."""
_NO_WORKER: Final = Login("odtworzenie")
"""Login pliku adresów odtworzenia bez Wpisów od Wykonawców: plik adresów bez Wykonawcy nie przechodzi walidacji."""
_MEMORY_NOT_SAVED: Final = report_entering_messages.memory_not_saved().code


def _entering_limits(record: RunLog) -> list[Limit]:
    limits = _one_file_limits(record, "Wpisanie raportów")
    if limits:
        return limits
    entering = record.report_entering
    if entering is None:
        return [
            Limit(
                "Logi nie mają Wpisów raportu, bo Uruchomienie skończyło się przed rdzeniem raportów: odtworzenie czyta "
                "Skrzynkę raportów bez maili, z gotowym plikiem dostępu i własnym plikiem adresów, a pamięć wpisów bez "
                "dnia wdrożenia, więc biegnie do końca, a Zatrzymanie taty z hasła, skrzynki, pliku adresów albo "
                "pamięci wpisów się nie powtarza i różnica wychodzi w wyniku"
            )
        ]
    replay = entering.replay()
    if isinstance(replay, Unreplayable):
        return [Limit(replay.reason, blocking=True)]
    limits = [
        Limit(
            "maili taty Logi nie mają: odtworzenie czyta Wpisy raportu z Logów z maili w postaci kanonicznej (temat "
            "„Raport dd.mm.rrrr”, linia „numer tak|nie czynności” na Wpis) od adresów @odtworzenie.invalid, z "
            "Konfiguracją wykonawców i plikiem adresów z loginów Wpisów, więc powtarza dopasowanie do zleceń, pamięć "
            "wpisów, decyzje „Zostaw moją” i Nienadpisywanie, ale nie rozpoznanie tekstu maila taty"
        ),
        *(Limit(text) for text in replay.reservations),
    ]
    if record.ending != "finished" and entering.written is None and entering.changes:
        limits.append(
            Limit(
                "zapis INTERMAX u taty skończył się Zatrzymaniem, które zależy od jego dysku (INTERMAX otwarty w Excelu "
                "albo zmieniony w trakcie): w katalogu roboczym odtworzenia zapis może się udać, więc to Zatrzymanie "
                "może się nie powtórzyć"
            )
        )
    return limits


def _entering(record: RunLog, work: _Work) -> _Rebuilt:
    """INTERMAX z uporządkowanych wierszy Kopii wejścia, Lista Wykonawców z loginów Wpisów,
    Skrzynka raportów z maili w postaci kanonicznej (``worker_reports.as_mail``), pamięć wpisów z ``rollout_before`` i
    ``memory_before`` z decyzjami „Zostaw moją” z ``kept``, folder okresów z pustym Plikiem zbiorczym każdego okresu zamkniętego u taty (``closed``) oraz
    zegar z dniem kliknięcia u taty. Numery z Wpisu, które INTERMAX taty miał w przeczytanym wierszu bez zlecenia
    (``orderless``), stają na dole swojego arkusza jako Surowe zlecenia z krojem z aplikacji, bo Kopia wejścia Wpisania
    raportów ma tylko uporządkowane wiersze zleceń z dni od ``Window.start``."""

    register, limits = _register_file(record, work, "intermax", lambda sheet, row: _ORDERED_FONT)
    started = record.started_at.astimezone()
    entering = record.report_entering
    replay = EnteringReplay.without_logs(started.date()) if entering is None else entering.replay()
    assert isinstance(replay, EnteringReplay), "Logi bez wejścia kliknięcia to granica blokująca (_entering_limits)"
    if replay.orderless:
        _add_orderless(register, replay)
    reads = replay.mails
    logins = sorted({read.worker for read in reads if not isinstance(read, ReadStranger)}) or [_NO_WORKER]
    senders = {login: _sender(f"wykonawca-{index}") for index, login in enumerate(logins)}
    workers = WorkerList.of([WorkerEntry([login], login, [sender.shown()]) for login, sender in senders.items()])
    assert isinstance(workers, WorkerList), "login Wpisu jest nazwą pliku, bo Logi niosą go po Liście Wykonawców taty"
    strangers = iter(replay.strangers)
    mails = [
        as_mail(read, _sender(f"obcy-{read.mail.digest}-{next(strangers)}") if isinstance(read, ReadStranger) else senders[read.worker])
        for read in reads
    ]
    moment = datetime.combine(replay.today, started.timetz())
    warned = any(message.code == _MEMORY_NOT_SAVED for message in record.messages)
    inbox = FakeInbox(mails, skipped=replay.skipped)
    parts = HostParts(now=lambda: moment, reports=ReportEnteringParts(inbox, _LoggedState(replay.saved, saves=not warned)))
    periods = work.folder("okresy")
    for token in replay.closed:
        collective = PeriodFolder(periods, parse_period_token(token)).collective_file
        collective.parent.mkdir(parents=True, exist_ok=True)
        collective.touch()
    paths: dict[PathNeed, Path] = {"register": register, "periods_directory": periods}
    return _Rebuilt(paths, parts, limits, workers)


def _add_orderless(register: Path, replay: EnteringReplay) -> None:
    """Numery z wierszy bez zlecenia z Logów jako Surowe zlecenia pod ostatnim wierszem swojego arkusza (z pustym
    wierszem nad nimi), jak wklejenie z aplikacji: pierwsze przesunięte o ``SHIFT`` kolumn w lewo, reszta pod
    nagłówkami, każde z ``NUMER ZL.`` w postaci z Wpisu (z zerem na początku, gdy Wpis go ma, inaczej liczbą) i dniem
    kliknięcia w ``DATA GODZ. POCZ.``, krojem z aplikacji. Proces czyta wtedy ich numery jak u taty, choć wiersz taty
    mógł być wierszem bez ``WYKONAWCA`` albo z datą tekstem, a reguła danych zna pierwsze tylko w przesuniętym
    położeniu, jak u taty. Numer, którego każdy wiersz był u taty zleceniem sprzed ``Window.start`` (``day``), dostaje
    ten dzień i ``WYKONAWCA``, więc rdzeń daje ten sam powód (``AddBar.BEFORE_WINDOW``)."""

    workbook = load_workbook(register)
    by_sheet: dict[str, list[ReplayedOrderless]] = {}
    for logged in replay.orderless:
        by_sheet.setdefault(logged.sheet, []).append(logged)
    for name, orderless in by_sheet.items():
        sheet = workbook[name]
        header = {normalize_text(cell.value): cell.column for cell in sheet[1] if cell.value is not None}
        first = sheet.max_row + 2
        for index, logged in enumerate(orderless):
            day = replay.today if logged.day is None else logged.day
            cells: dict[Column, datetime | int | str] = {
                DATE: datetime.combine(day, time()),
                ORDER_NUMBER: logged.number,
            }
            if logged.day is not None:
                cells[WORKER] = _NO_WORKER
            shift = SHIFT if index == 0 else 0
            for column, value in cells.items():
                [place] = [header[found] for found in map(normalize_text, column.register_headers) if found in header]
                sheet.cell(first + index, place - shift, value).font = _PASTED_FONT
    workbook.save(register)


@dataclass
class _LoggedState:
    """Pamięć wpisów taty przed kliknięciem z Logów; zapis po kliknięciu nie udaje się, gdy u taty się nie udał."""

    saved: SavedState
    saves: bool

    def load(self) -> SavedState:
        return self.saved

    def save_memory(self, written: CellsWritten, rollout: date, memory: OwnEntries) -> bool:
        return self.saves

    def save_result(self, written: CellsWritten, result: ClickResult) -> None:
        """Widoku Raporty odtworzenie nie ma, a wynik kliknięcia porównuje z Logów."""


def _sender(local: str) -> SenderAddress:
    sender = SenderAddress.of(f"{local}@{_REPLAY_DOMAIN}")
    assert sender is not None, local
    return sender


def _rebuild(key: common_contract.ProcessKey) -> _Rebuild:
    """Odtworzenie procesu ``key``; nowy proces bez swojej gałęzi pada w mypy."""

    match key:
        case "settlement":
            return _Rebuild(_collective_limits, _settlement)
        case "preparation":
            return _Rebuild(_preparation_limits, _preparation)
        case "intermax":
            return _Rebuild(_intermax_limits, _intermax)
        case "efenix":
            return _Rebuild(_efenix_limits, _efenix)
        case "report_entering":
            return _Rebuild(_entering_limits, _entering, workers=True)
        case _:
            assert_never(key)


def _from_configuration(kind: ProcessKind[Any, Any], rebuild: _Rebuild) -> list[str]:
    """Pliki procesu ``kind``, które odtworzenie bierze z folderu Konfiguracji, a nie z odbudowy: Wzorce i Lista
    Wykonawców."""

    templates = [ConfigurationFiles.in_folder(Path()).path(need).name for need in kind.configuration_needs]
    return [*templates, WORKERS_FILE] if "workers" in kind.needs and not rebuild.workers else templates


def _prepared(
    record: RunLog, kind: ProcessKind[Any, Any], rebuilt: _Rebuilt, work: _Work, memory: ForbiddenValues
) -> PreparedRun[Any, Any]:
    """Uruchomienie z Logów ``record`` z plikami odbudowanymi i z folderu Konfiguracji, z Kopią wejścia i plikiem
    metryk w katalogu roboczym w miejscu pliku metryk procesu. Okres Uporządkowania INTERMAX to okres dnia z zegara
    procesu u taty (ADR 0019), więc start podaje okres tylko procesowi z okresem."""

    paths = {**rebuilt.paths, **_configured(work, kind.configuration_needs)}
    period = record.period if isinstance(kind, PeriodProcessKind) else None
    workers = rebuilt.workers if rebuilt.workers is not None else _configured_workers(work) if "workers" in kind.needs else None
    start = Start(
        paths,
        period=period,
        dry_run=record.mode.dry_run,
        pricing=record.pricing,
        workers=workers,
        quantity_rules=_quantity_rules(record),
        warnings=record.start_warnings(),
    )
    metrics = work.path("metryki.jsonl")
    return CATALOG.with_metrics({kind.key: metrics}).prepared(kind.key, start, rebuilt.parts, RunContexts(files=DadFiles(forbidden=memory)).new())


def _quantity_rules(record: RunLog) -> QuantityRules:
    """Reguły ilości ze startu Uruchomienia z Logów, a z Logów sprzed ich zapisu Reguły ilości z Wydania tego drzewa;
    reguły, których nie da się odczytać, zatrzymują odtworzenie wcześniej (``_rules_limits``)."""

    if record.quantity_rules is None:
        return DEFAULT_QUANTITY_RULES
    value = record.quantity_rules.value()
    assert isinstance(value, QuantityRules), "reguły, których nie da się odczytać, to granica blokująca"
    return value


def _configured(work: _Work, needs: Sequence[ConfigurationNeed]) -> dict[PathNeed, Path]:
    if not needs:
        return {}
    assert work.configuration is not None, "bez folderu Konfiguracji _configuration_limit blokuje odtworzenie"
    files = ConfigurationFiles.in_folder(work.configuration)
    return {need: files.path(need) for need in needs}


def _configured_workers(work: _Work) -> WorkerList:
    """Lista Wykonawców z ``wykonawcy.yaml`` folderu Konfiguracji regułą właściciela Ustawień Centrum; brak pliku to
    pusta lista, jak w Centrum, a zła treść to błąd odtworzenia (``ValueError`` ze zdaniem)."""

    assert work.configuration is not None, "bez folderu Konfiguracji _configuration_limit blokuje odtworzenie"
    data = settings_bytes(work.configuration / WORKERS_FILE)
    if isinstance(data, OSError):
        raise data
    parsed = WORKERS.parse(data)
    if isinstance(parsed, FieldProblem):
        raise ValueError(f"{WORKERS_FILE}: {parsed.sentence}")
    return parsed


# --- przebieg -------------------------------------------------------------------------------------------------------


class _Tata:
    """Rozmówca odtworzenia jak tata w Logach: zgoda w Decyzji taty, chyba że Logi kończą się odmową, i ostatni widok
    postępu, jak karta Centrum (``runs.Run``)."""

    continue_hint = runs_contract.CONTINUE_HINT

    def __init__(self, prepared: PreparedRun[Any, Any], consent: bool) -> None:
        self._prepared = prepared
        self._consent = consent
        self.progress = prepared.progress_view(ProgressProjection().snapshot)

    def confirm(self, decision: Decision) -> bool:
        return self._consent

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        self.progress = self._prepared.progress_view(snapshot)


def _run(record: RunLog, prepared: PreparedRun[Any, Any], memory: ForbiddenValues) -> RunLog:
    """Uruchomienie odtworzenia przez rdzeń procesu i jego Logi po strażniku, jak w Centrum (``RunComments.run_ended``)."""

    tata = _Tata(prepared, consent=record.ending != "declined")
    info = prepared.info(record.run_id)
    started_at = datetime.now(timezone.utc)
    core = startable(prepared).conduct(tata)
    stop = None if isinstance(core.ending, Finished) else core.ending
    ended = EndedRun.of(
        prepared,
        core,
        info=info,
        stopped=None if stop is None else stops.plain(info, stop),
        progress=tata.progress,
        started_at=started_at,
    )
    environment = Environment(system=platform.platform(), python=platform.python_version(), files=None)
    replayed = logs_of(
        ended,
        tool=record.tool,
        environment=environment,
        dad_actions=DadActions(entries=[], omitted=0),
    )
    return guard_logs(replayed, memory).record


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


def _same_value(value: Any) -> object:
    return value


@dataclass(frozen=True)
class _Part:
    """Porównana część Logów: nazwa w raporcie, pole ``RunLog`` i jego postać bez czasów, chwil i odcisków."""

    name: str
    key: str
    view: Callable[[Any], object] = _same_value


COMPARED: Final = (
    _Part("Kopia wejścia", "input_copy", _copied),
    _Part("wynik", "result"),
    _Part("zakończenie", "ending"),
    _Part("Rodzaj Zatrzymania", "stop_kind", lambda kind: "for_tata" if kind == "repeated" else kind),
    _Part("Komunikaty", "messages"),
    _Part("uwagi techniczne", "technical_notes"),
    _Part("podsumowanie", "summary"),
    _Part("liczba problemów", "issue_count"),
    _Part("etapy", "phases", lambda phases: [{"phase": phase["phase"], "state": phase["state"]} for phase in phases]),
    _Part(
        "Szablony pracownika",
        "templates",
        lambda templates: [{key: template[key] for key in ("wykonawca", "outcome", "rows")} for template in templates],
    ),
    _Part("Ilości tylko dla INEA", "inea_only_cleared"),
    _Part("Wpisy INTERMAX", "intermax_entries"),
    _Part("Wpisanie raportów", "report_entering"),
    _Part("ślad zleceń efenix", "efenix_orders", _orders),
    _Part("Zatrzymanie okna efenix", "efenix_stop", _window_stop),
    _Part("ślad wywołań", "trace"),
)
"""Porównane części Logów w kolejności przyczyn."""
NOT_COMPARED: Final = frozenset(
    {
        *StartFacts.model_fields,
        "schema_version",
        "ended_at",
        "duration_ms",
        "tool",
        "environment",
        "diagnosis",
        "dad_actions",
        "interruption",
        "input_copy_notes",
        "quantity_rules",
    }
)
"""Pola Logów, które odtworzenie bierze z Logów albo które zależą od chwili, komputera albo taty, a nie od wejścia i
kodu: fakty startu, czasy, narzędzie, środowisko, Diagnoza, działania taty, Urwanie, uwagi o Kopii wejścia i Reguły
ilości ze startu. Każde inne
pole ``RunLog`` jest w ``COMPARED`` (``tests/test_centrum_logi_w_skrzynce.py``)."""


def first_difference(logged: RunLog, replayed: RunLog) -> Difference | None:
    left, right = logged.model_dump(), replayed.model_dump()
    for part in COMPARED:
        found = _walk(part.view(left[part.key]), part.view(right[part.key]), f"{part.name} ({part.key})")
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
