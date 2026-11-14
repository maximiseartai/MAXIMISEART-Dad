"""Jedno Uruchomienie procesu (settlement, preparation, intermax, efenix, report_entering) z wynikiem JSON; użyj w E2E, benchmarku i skillach.

Skrypt dla maszyn: jedno Uruchomienie procesu, wynik jako JSON.

Użycie (z katalogu repozytorium):

    python tools/uruchom_proces.py settlement --source PLIK_ZBIORCZY [--dry-run]
        [--wykonawcy PLIK] [--worker-template PLIK] [--metrics PLIK]
    python tools/uruchom_proces.py preparation --register REJESTR --periods-directory FOLDER --period TOKEN
        [--dry-run] [--wykonawcy PLIK] [--internal-template PLIK] [--collective-template PLIK] [--metrics PLIK]
    python tools/uruchom_proces.py intermax --register REJESTR [--copies FOLDER] [--metrics PLIK]
    python tools/uruchom_proces.py efenix --source PLIK_ZBIORCZY --efenix-url ADRES [--z-przekazaniem] [--metrics PLIK]
    python tools/uruchom_proces.py report_entering --register REJESTR --periods-directory FOLDER --maile FOLDER
        [--wykonawcy PLIK] [--metrics PLIK]

``settlement`` to Przebieg rozliczeń, ``preparation`` Przygotowanie pliku
zbiorczego, ``intermax`` Uporządkowanie INTERMAX (klucze procesu z kontraktu
Centrum rozliczeń), a ``efenix`` Wycena w efenix. Wycena w efenix otwiera
listę zleceń pod ``--efenix-url`` w nowym Chromium Playwrighta bez okna i
uzupełnia w nim wyceny zleceń (data wykonania, Wycena Emmetta, pola „Ilość”)
bez tempa ludzkiego, bo to zawsze adres Atrapy efenix, nigdy efenix.pl (ADR 0024). Bez ``--z-przekazaniem`` biegnie w
trybie bez Przekazania (gotowe zlecenia dostają Znacznik efenix), a z nim gotowe zlecenia przekazuje do akceptacji
(ADR 0027). ``report_entering`` to Wpisanie raportów (ADR 0028): maile czyta z plików ``.eml`` folderu ``--maile``,
nigdy z Gmaila, a pamięć własnych wpisów ma tylko na czas Uruchomienia, więc okno dni zaczyna się dziś, o ile okres
dzisiejszego dnia nie ma Pliku zbiorczego w folderze ``--periods-directory``.
Uporządkowanie nie ma okresu ani
podglądu bez zapisu: zawsze
zapisuje, a Kopia INTERMAX trafia do ``--copies`` (bez parametru folder Kopii
narzędzia), z nazwą z zegara komputera. Proces prowadzi ten
sam rdzeń Uruchomienia procesu co w Centrum, więc wynik ma te same liczby,
etykiety i Komunikaty co karta Uruchomienia. Bez parametru Lista Wykonawców
i Wzorce są te z Centrum (``config/wykonawcy.yaml``, ``ConfigurationFiles.default()``), a plik
metryk to plik metryk procesu. Listę Wykonawców ``--wykonawcy`` czyta reguła właściciela Ustawień Centrum
(``WORKERS.parse``) bez zapisu Historii i pamięci: brak pliku to pusta lista, a zła treść kończy Skrypt kodem 1 ze
zdaniem na stderr, bez JSON. Skrypt nie czyta Ustawień taty (Reguły ilości są te z Wydania), nie otwiera okien
wyboru i nie pyta o nic: każdą Decyzję taty odrzuca, więc nigdy nie czeka.

Na stdout trafia jeden obiekt JSON (UTF-8, ``ProcessResult``):

- ``result``: ``OK``, ``WYMAGA_SPRAWDZENIA`` albo ``BLAD_KRYTYCZNY``;
- ``summary``: podsumowanie albo plan (DRY-RUN) z widoku Uruchomienia
  (``runs_contract.RunSummary``), ``null`` przy Zatrzymaniu;
- ``warnings``: ostrzeżenia procesu w zakończonym procesie, każde z kodem i
  trzema częściami Komunikatu;
- ``stop``: przy Zatrzymaniu sposób zakończenia (``process_run.StopEnding``: ``stop``,
  ``declined``, ``unexpected``, ``after_engine``) i Komunikat z kodem i trzema częściami,
  inaczej ``null``;
- ``progress``: ostatni stan postępu w kształcie kontraktu (``runs_contract.Progress``);
  po awarii widoku ostatni zbudowany przed nią, a gdy żaden nie powstał, pusty (bez etapów);
- ``total_duration_ms``: ``Czas uruchomienia``;
- ``technical_notes``: uwagi techniczne rdzenia (niezapisane metryki, odłączony podgląd);
- ``metrics_saved``: rekord metryk trafił do pliku metryk.

JSON nie zawiera tekstu wyjątku ani śladu wywołań.

Kod wyjścia to 0 OK, 2 Wymaga sprawdzenia, 1 Zatrzymanie.
Błędne argumenty też kończą się kodem 1, bez JSON, z opisem użycia na stderr,
żeby literówka nigdy nie wyglądała jak wynik Wymaga sprawdzenia.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Final, NoReturn, assert_never

from pydantic import BaseModel, ConfigDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from rozliczenia import intermax_copies
from rozliczenia.centrum import run_view
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.catalog import CATALOG
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.process_kind import HostParts, Need, ProcessKind, Start, startable
from rozliczenia.centrum.settings.files import FieldProblem
from rozliczenia.centrum.settings.memory import settings_bytes
from rozliczenia.centrum.settings.workers import WORKERS, WORKERS_FILE
from rozliczenia.decision import Decision
from rozliczenia.message import Message
from rozliczenia.process_run import Finished, Outcome, RunResult, StopEnding
from rozliczenia.run_context import RunContext
from rozliczenia.tool_files import CONFIG_DIR
from rozliczenia.worker_list import WorkerList
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.quantity_rules_file import DEFAULT_QUANTITY_RULES
from rozliczenia.report_entering import ReportEnteringParts, ReportStateInMemory

from atrapy.skrzynka_raportow import FolderInbox

_EXIT_CODES = {"OK": 0, "WYMAGA_SPRAWDZENIA": 2, "BLAD_KRYTYCZNY": 1}

class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CodedMessage(_Model):
    code: str
    what: str
    where: str
    action: str

    @classmethod
    def of(cls, message: Message) -> CodedMessage:
        return cls(code=message.code, what=message.what, where=message.where, action=message.action)


class StopResult(_Model):
    kind: StopEnding
    message: CodedMessage


class ProcessResult(_Model):
    result: RunResult
    summary: runs_contract.RunSummary | None
    warnings: list[CodedMessage]
    stop: StopResult | None
    progress: runs_contract.Progress
    total_duration_ms: int
    technical_notes: list[str]
    metrics_saved: bool

    @classmethod
    def of(cls, outcome: Outcome[run_view.Shown[Any]], progress: runs_contract.Progress) -> ProcessResult:
        shown = outcome.view
        ending = outcome.ending
        return cls(
            result=outcome.result,
            summary=None if shown is None else shown.summary,
            warnings=[] if shown is None else [CodedMessage.of(warning) for warning in shown.warnings],
            stop=None if isinstance(ending, Finished) else StopResult(kind=ending.kind, message=CodedMessage.of(ending.message)),
            progress=progress,
            total_duration_ms=outcome.total_duration_ms,
            technical_notes=list(outcome.technical_notes),
            metrics_saved=outcome.metrics_saved,
        )


class _Unattended:
    continue_hint = f"uruchom proces w Centrum rozliczeń i {runs_contract.CONTINUE_HINT}"

    def __init__(self, progress_view: Callable[[ProgressSnapshot], runs_contract.Progress]) -> None:
        self._progress_view = progress_view
        self.progress = runs_contract.Progress(
            phases=[], template_total=0, templates_completed=0, current_worker=None, figures=[]
        )

    def confirm(self, decision: Decision) -> bool:
        return False

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        self.progress = self._progress_view(snapshot)


_REGISTER: Final = "Rejestr zleceń"
_CONFIGURATION: Final = ConfigurationFiles.default()
_PRICING_FLAG: Final = "--z-przekazaniem"
"""Przełącznik trybu Wyceny w efenix procesu z trybami: z nim „z Przekazaniem”, bez niego tryb domyślny wpisu."""


@dataclass(frozen=True)
class _Flag:
    """Flaga potrzeby wejścia procesu; ``default`` ``None``: flaga wymagana, ``path``: wartość to ścieżka."""

    option: str
    help: str
    default: Path | None = None
    path: bool = True


def _flag(need: Need, kind: ProcessKind[Any, Any]) -> _Flag:
    match need:
        case "collective_file":
            return _Flag("--source", "Plik zbiorczy.")
        case "register":
            name = kind.view.register_name
            return _Flag("--register", f"{name}." if name == _REGISTER else f"{_REGISTER} ({name}).")
        case "periods_directory":
            return _Flag("--periods-directory", "Folder okresów.")
        case "period":
            return _Flag("--period", "Token okresu, np. 08_14_09_2026.", path=False)
        case "workers":
            return _Flag("--wykonawcy", "Lista Wykonawców (plik wykonawcy.yaml).", CONFIG_DIR / WORKERS_FILE)
        case "internal_template":
            return _Flag("--internal-template", "Wzorzec rozliczenia wewnętrznego.", _CONFIGURATION.path(need))
        case "collective_template":
            return _Flag("--collective-template", "Wzorzec pliku zbiorczego.", _CONFIGURATION.path(need))
        case "worker_template":
            return _Flag("--worker-template", "Wzorzec rozliczenia pracownika.", _CONFIGURATION.path(need))
        case "copies_directory":
            return _Flag("--copies", "Folder Kopii INTERMAX.", intermax_copies.default_directory())
        case "efenix_window":
            return _Flag("--efenix-url", "Adres listy zleceń efenix (w testach Atrapy efenix).", path=False)
        case "worker_report_inbox":
            return _Flag("--maile", "Folder maili .eml w miejscu Skrzynki raportów.")
        case _:
            assert_never(need)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    processes = parser.add_subparsers(required=True, metavar="PROCES", dest="process")
    for kind in CATALOG.kinds:
        process = processes.add_parser(kind.key, help=kind.title)
        for need in kind.needs:
            flag = _flag(need, kind)
            process.add_argument(
                flag.option,
                dest=need,
                metavar=flag.option.removeprefix("--").replace("-", "_").upper(),
                type=Path if flag.path else str,
                required=flag.default is None,
                default=flag.default,
                help=flag.help,
            )
        if kind.view.pricing_modes:
            process.add_argument(
                _PRICING_FLAG,
                dest="handover",
                action="store_true",
                help="Gotowe zlecenia przekaż do akceptacji (tryb z Przekazaniem).",
            )
        process.add_argument("--metrics", type=Path, default=CATALOG.metrics_paths[kind.key], help="Plik metryk JSONL.")
        if kind.core.preview is not None:
            process.add_argument("--dry-run", action="store_true", help="Podgląd bez zapisu.")
    return parser


def _start(kind: ProcessKind[Any, Any], args: argparse.Namespace, parser: argparse.ArgumentParser) -> Start:
    values = vars(args)
    return Start(
        {need: values[need] for need in kind.path_needs},
        period=values.get("period"),
        dry_run=values.get("dry_run", False),
        pricing="z Przekazaniem" if values.get("handover") else None,
        workers=_workers(args.workers, parser) if "workers" in kind.needs else None,
        quantity_rules=DEFAULT_QUANTITY_RULES,
        warnings=(),
    )


def _workers(path: Path, parser: argparse.ArgumentParser) -> WorkerList:
    """Lista Wykonawców z pliku ``path`` regułą właściciela Ustawień Centrum; zły plik kończy Skrypt kodem 1."""

    data = settings_bytes(path)
    if isinstance(data, OSError):
        parser.error(f"--wykonawcy: nie można teraz odczytać pliku {path.name}")
    parsed = WORKERS.parse(data)
    if isinstance(parsed, FieldProblem):
        parser.error(f"--wykonawcy: {parsed.sentence}")
    return parsed


def _parts(kind: ProcessKind[Any, Any], args: argparse.Namespace) -> HostParts:
    efenix = None
    if "efenix_window" in kind.needs:
        # Playwright tylko dla Wyceny w efenix: inne procesy nie płacą przy każdym starcie za jego import.
        from rozliczenia.centrum.efenix_chrome import atrapa_opening

        # Bez tempa ludzkiego: Skrypt dla maszyn biegnie tylko na Atrapie efenix (ADR 0024), w nowym Chromium bez
        # sesji taty.
        efenix = atrapa_opening(args.efenix_window)
    # Maile z folderu .eml, nigdy z Gmaila, i pamięć własnych wpisów tylko na czas tego Uruchomienia.
    inbox = "worker_report_inbox" in kind.needs
    reports = ReportEnteringParts(FolderInbox(args.worker_report_inbox), ReportStateInMemory()) if inbox else None
    return HostParts(efenix=efenix, reports=reports)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    kind = CATALOG.kind(args.process)
    # Bez Kopii wejścia, z plikiem metryk ``--metrics`` w miejscu pliku metryk procesu.
    prepared = CATALOG.with_metrics({kind.key: args.metrics}).prepared(
        kind.key, _start(kind, args, parser), _parts(kind, args), RunContext()
    )
    unattended = _Unattended(prepared.progress_view)
    outcome = startable(prepared).conduct(unattended)
    result = ProcessResult.of(outcome, unattended.progress)
    sys.stdout.buffer.write(result.model_dump_json(indent=2).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
    return _EXIT_CODES[outcome.result]


if __name__ == "__main__":
    raise SystemExit(main())
