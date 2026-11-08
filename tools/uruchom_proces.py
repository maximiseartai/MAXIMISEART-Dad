"""Jedno Uruchomienie procesu (settlement, preparation, intermax, efenix) z wynikiem JSON; użyj w E2E, benchmarku i skillach zamiast Centrum rozliczeń.

Skrypt dla maszyn: jedno Uruchomienie procesu, wynik jako JSON.

Użycie (z katalogu repozytorium):

    python tools/uruchom_proces.py settlement --source PLIK_ZBIORCZY [--dry-run]
        [--config PLIK] [--worker-template PLIK] [--metrics PLIK]
    python tools/uruchom_proces.py preparation --register REJESTR --periods-directory FOLDER --period TOKEN
        [--dry-run] [--config PLIK] [--internal-template PLIK] [--collective-template PLIK] [--metrics PLIK]
    python tools/uruchom_proces.py intermax --register REJESTR [--copies FOLDER] [--metrics PLIK]
    python tools/uruchom_proces.py efenix --source PLIK_ZBIORCZY --efenix-url ADRES [--z-przekazaniem] [--metrics PLIK]

``settlement`` to Przebieg rozliczeń, ``preparation`` Przygotowanie pliku
zbiorczego, ``intermax`` Uporządkowanie INTERMAX (klucze procesu z kontraktu
Centrum rozliczeń), a ``efenix`` Wycena w efenix. Wycena w efenix otwiera
listę zleceń pod ``--efenix-url`` w nowym Chromium Playwrighta bez okna i
uzupełnia w nim wyceny zleceń (data wykonania, Wycena Emmetta, pola „Ilość”)
bez tempa ludzkiego, bo to zawsze adres Atrapy efenix, nigdy efenix.pl (ADR 0024). Bez ``--z-przekazaniem`` biegnie w
trybie bez Przekazania (gotowe zlecenia dostają Znacznik efenix), a z nim gotowe zlecenia przekazuje do akceptacji
(ADR 0027). Uporządkowanie nie ma okresu ani
podglądu bez zapisu: zawsze
zapisuje, a Kopia INTERMAX trafia do ``--copies`` (bez parametru folder Kopii
narzędzia), z nazwą z zegara komputera. Proces prowadzi ten
sam rdzeń Uruchomienia procesu co w Centrum, więc wynik ma te same liczby,
etykiety i Komunikaty co karta Uruchomienia. Bez parametru Konfiguracja
wykonawców i Wzorce są te z Centrum (``ConfigurationFiles.default()``), a plik
metryk to plik metryk procesu. Skrypt nie czyta Ustawień taty, nie otwiera okien
wyboru i nie pyta o nic: każdą Decyzję taty odrzuca, więc nigdy nie czeka.

Na stdout trafia jeden obiekt JSON (UTF-8, ``ProcessResult``):

- ``result``: ``OK``, ``WYMAGA_SPRAWDZENIA`` albo ``BLAD_KRYTYCZNY``;
- ``summary``: podsumowanie albo plan (DRY-RUN) z widoku Uruchomienia
  (``contract.RunSummary``), ``null`` przy Zatrzymaniu;
- ``warnings``: ostrzeżenia procesu w zakończonym procesie, każde z kodem i
  trzema częściami Komunikatu;
- ``stop``: przy Zatrzymaniu sposób zakończenia (``process_run.StopEnding``: ``stop``,
  ``declined``, ``unexpected``, ``after_engine``) i Komunikat z kodem i trzema częściami,
  inaczej ``null``;
- ``progress``: ostatni stan postępu w kształcie kontraktu (``contract.Progress``);
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
from pathlib import Path
import sys
from typing import Any, NoReturn

from pydantic import BaseModel, ConfigDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rozliczenia import efenix_browser, intermax_copies
from rozliczenia.centrum import contract, run_view
from rozliczenia.centrum.catalog import CATALOG
from rozliczenia.centrum.configuration import ConfigurationFiles
from rozliczenia.centrum.process_kind import PreparedRun
from rozliczenia.centrum.runs import CONTINUE_HINT
from rozliczenia.decision import Decision
from rozliczenia.efenix_pricing import PricingMode
from rozliczenia.efenix_pricing import EfenixInputs
from rozliczenia.intermax_ordering import OrderingInputs
from rozliczenia.message import Message
from rozliczenia.collective_preparation import PreparationInputs
from rozliczenia.process_run import Finished, Outcome, ProcessInputs, StopEnding
from rozliczenia.run_context import RunContext
from rozliczenia.progress import ProgressSnapshot
from rozliczenia.engine import SettlementInputs

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
        return cls(code=message.code, **contract.Message.of(message).model_dump())


class StopResult(_Model):
    kind: StopEnding
    message: CodedMessage


class ProcessResult(_Model):
    result: contract.RunResult
    summary: contract.RunSummary | None
    warnings: list[CodedMessage]
    stop: StopResult | None
    progress: contract.Progress
    total_duration_ms: int
    technical_notes: list[str]
    metrics_saved: bool

    @classmethod
    def of(cls, outcome: Outcome[run_view.Shown[Any]], progress: contract.Progress) -> ProcessResult:
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
    continue_hint = f"uruchom proces w Centrum rozliczeń i {CONTINUE_HINT}"

    def __init__(self, progress_view: Callable[[ProgressSnapshot], contract.Progress]) -> None:
        self._progress_view = progress_view
        self.progress = contract.Progress(
            phases=[], template_total=0, templates_completed=0, current_worker=None, figures=[]
        )

    def confirm(self, decision: Decision) -> bool:
        return False

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        self.progress = self._progress_view(snapshot)


def _prepared(
    key: contract.ProcessKey,
    inputs: ProcessInputs,
    metrics: Path,
    pricing: contract.Pricing | None = None,
) -> PreparedRun[Any, Any]:
    """Uruchomienie bez Kopii wejścia, z plikiem metryk ``metrics`` (``--metrics``) w miejscu pliku metryk procesu."""

    return CATALOG.with_metrics({key: metrics}).prepared(
        key, period=inputs.period, inputs=inputs, context=RunContext(), pricing=pricing
    )


def _settle(args: argparse.Namespace) -> PreparedRun[Any, Any]:
    inputs = SettlementInputs(
        args.source, dry_run=args.dry_run, config_path=args.config, worker_template_path=args.worker_template
    )
    return _prepared("settlement", inputs, args.metrics)


def _prepare(args: argparse.Namespace) -> PreparedRun[Any, Any]:
    inputs = PreparationInputs(
        args.register,
        args.periods_directory,
        args.period,
        dry_run=args.dry_run,
        config_path=args.config,
        internal_template_path=args.internal_template,
        collective_template_path=args.collective_template,
    )
    return _prepared("preparation", inputs, args.metrics)


def _order(args: argparse.Namespace) -> PreparedRun[Any, Any]:
    inputs = OrderingInputs(args.register, args.copies)
    return _prepared("intermax", inputs, args.metrics)


def _price(args: argparse.Namespace) -> PreparedRun[Any, Any]:
    url: str = args.efenix_url
    # Bez tempa ludzkiego: Skrypt dla maszyn biegnie tylko na Atrapie efenix (ADR 0024), w nowym Chromium bez sesji taty.
    pricing: contract.Pricing = "z Przekazaniem" if args.z_przekazaniem else contract.DEFAULT_PRICING
    inputs = EfenixInputs(args.source, lambda _login: efenix_browser.chromium(url), pace=None, mode=PricingMode(pricing))
    return _prepared("efenix", inputs, args.metrics, pricing=pricing)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    files = ConfigurationFiles.default()
    parser = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    processes = parser.add_subparsers(required=True, metavar="PROCES")

    settlement = processes.add_parser("settlement", help=CATALOG.kind("settlement").title)
    settlement.add_argument("--source", type=Path, required=True, help="Plik zbiorczy.")
    settlement.add_argument("--config", type=Path, default=files.worker_config, help="Konfiguracja wykonawców.")
    settlement.add_argument(
        "--worker-template", type=Path, default=files.worker_template, help="Wzorzec rozliczenia pracownika."
    )
    settlement.add_argument(
        "--metrics", type=Path, default=CATALOG.metrics_paths["settlement"], help="Plik metryk JSONL."
    )
    settlement.add_argument("--dry-run", action="store_true", help="Podgląd bez zapisu.")
    settlement.set_defaults(prepare=_settle)

    preparation = processes.add_parser("preparation", help=CATALOG.kind("preparation").title)
    preparation.add_argument("--register", type=Path, required=True, help="Rejestr zleceń.")
    preparation.add_argument("--periods-directory", type=Path, required=True, help="Folder okresów.")
    preparation.add_argument("--period", required=True, help="Token okresu, np. 08_14_09_2026.")
    preparation.add_argument("--config", type=Path, default=files.worker_config, help="Konfiguracja wykonawców.")
    preparation.add_argument(
        "--internal-template", type=Path, default=files.internal_template, help="Wzorzec rozliczenia wewnętrznego."
    )
    preparation.add_argument(
        "--collective-template", type=Path, default=files.collective_template, help="Wzorzec pliku zbiorczego."
    )
    preparation.add_argument(
        "--metrics", type=Path, default=CATALOG.metrics_paths["preparation"], help="Plik metryk JSONL."
    )
    preparation.add_argument("--dry-run", action="store_true", help="Podgląd bez zapisu.")
    preparation.set_defaults(prepare=_prepare)

    ordering = processes.add_parser("intermax", help=CATALOG.kind("intermax").title)
    ordering.add_argument("--register", type=Path, required=True, help="Rejestr zleceń (INTERMAX).")
    ordering.add_argument(
        "--copies", type=Path, default=intermax_copies.default_directory(), help="Folder Kopii INTERMAX."
    )
    ordering.add_argument(
        "--metrics", type=Path, default=CATALOG.metrics_paths["intermax"], help="Plik metryk JSONL."
    )
    ordering.set_defaults(prepare=_order)

    pricing = processes.add_parser("efenix", help=CATALOG.kind("efenix").title)
    pricing.add_argument("--source", type=Path, required=True, help="Plik zbiorczy.")
    pricing.add_argument("--efenix-url", required=True, help="Adres listy zleceń efenix (w testach Atrapy efenix).")
    pricing.add_argument(
        "--z-przekazaniem", action="store_true", help="Gotowe zlecenia przekaż do akceptacji (tryb z Przekazaniem)."
    )
    pricing.add_argument("--metrics", type=Path, default=CATALOG.metrics_paths["efenix"], help="Plik metryk JSONL.")
    pricing.set_defaults(prepare=_price)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    prepare: Callable[[argparse.Namespace], PreparedRun[Any, Any]] = args.prepare
    prepared = prepare(args)
    unattended = _Unattended(prepared.progress_view)
    outcome = prepared.conduct(unattended)
    result = ProcessResult.of(outcome, unattended.progress)
    sys.stdout.buffer.write(result.model_dump_json(indent=2).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
    return _EXIT_CODES[outcome.result]


if __name__ == "__main__":
    raise SystemExit(main())
