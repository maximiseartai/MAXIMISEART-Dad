"""Interleave Dad's clicks in the tool's efenix tab with every write of a real Wycena w efenix and check where each write lands.

The checker runs the real process (``run_process`` with ``efenix_process.PROCESS`` and the window
``efenix_browser.window`` in Playwright's Chromium) on the Atrapa efenix (``tools/lib/atrapy/atrapa_efenix.py``) with
one order of a synthetic Plik zbiorczy, order A: an empty pricing and an empty execution date, so the process sets the
date, loads Wycena Emmetta and enters two quantities over Emmett's, and in the mode with Przekazanie forwards it. The
Atrapa also holds order B, someone else's order with Dad's own pricing and date, which the process never reads.

Dad acts in the tool's tab at the points where he has time to: in each pause before a write (``efenix_pace.Pace``,
``ACTION_PAUSE_S`` at Dad's; ``Pace.sleep`` is the checker's hook, the constructor seam of the pace) and during the
reload the efenix script makes after „Załaduj do zlecenia” (``EFENIX_EMMETT_RELOAD_MS``, about 1 s at efenix). There
he does one of three things a person does in a browser tab: opens another order (B), goes back to the list of orders,
or reloads the page. The points come from a run without Dad (the reference) of each mode: one point before each write
the reference makes, so a new write of the process gets its point without a change here, and a write with no pause
before it is ``LUKA MODELU``.

The rules, each with the sentence it comes from:

- ZAPIS_W_PRZECZYTANYM: every write of the process in efenix (the execution date, „Załaduj do zlecenia”, a quantity,
  Przekazanie do akceptacji) reaches efenix with the identifier of the order the process read (``open_order`` sets
  ``_order_id``), and order B is unchanged after the run, whatever Dad did in the tab (``efenix_browser``: Przekazanie
  of another order „też jest nieodwracalne”; ADR 0024: „Załaduj do zlecenia” „czyści wycenę zlecenia”).
- PRZEBIEG_WZORCOWY: a run without Dad ends order A gotowe (mode without Przekazanie) or przekazane (mode with it) with
  the file's quantities and date in efenix, so the scenario reaches every write the rule talks about.
- BEZ_WYJATKU: a run ends with a result or a Zatrzymanie, never with an unexpected error.

The verdict is the last line (``tools/lib/eksplorator.py``). ``--lista`` prints the cases, ``--przypadek`` runs one.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import date
import enum
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import traceback
from typing import Final
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from playwright.sync_api import Browser, Page, Request, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from eksplorator import Excuse, excuse_line, excused, gone_lines, verdict
import rozjazd_modelu
from rozliczenia import efenix_browser, efenix_process
from rozliczenia.dad_files import DadFiles
from rozliczenia.efenix_pace import Pace
from rozliczenia.efenix_pricing import EfenixInputs, OrderKind, PricingMode, PricingStopped, PricingSummary
from rozliczenia.efenix_window import Efenix, Login
from rozliczenia.process_run import Outcome, Stop, run_process
from rozliczenia.run_context import RunContext
from skrypt_skilla import Parser
# Adresy działań efenix z Atrapy, celowej kopii efenix (docs/agents/skille.md, „Co wyrocznia bierze z src”): adres to
# fakt świata efenix, więc jego zmiana w efenix_page ma wywrócić sprawdzenie, a nie przejść razem z nim.
from atrapy.atrapa_efenix import (
    CHANGE_STATUS,
    EFENIX_EMMETT_RELOAD_MS,
    LOAD_EMMETT,
    ORDER_PAGE,
    SAVE_QUANTITY,
    SET_DATE,
    AtrapaOrder,
    amount_of,
    atrapa_efenix,
)
from atrapy.efenix import Order, write_collective_file
from atrapy.interlocutor import Tata

VERDICT: Final = "KARTA EFENIX"
LIMIT_MS: Final = 3_000 + EFENIX_EMMETT_RELOAD_MS
"""The window's time limit in the checker, as in ``verify-wycena-efenix``: 3 s and the reload after „Załaduj do
zlecenia”, which the window waits for in the same limit."""

# --- The scenario -----------------------------------------------------------------------------------------------------

READ: Final = "a5kx1"
"""Identifier of order A, the one the process searches, opens (``_order_id``) and prices."""
OTHER: Final = "b7qz9"
"""Identifier of order B, someone else's order with Dad's pricing, which the process never reads."""
FILE: Final[Mapping[str, int]] = {"012": 1, "019": 2, "015": 1}
"""Quantities of the Plik zbiorczy by position: O→012, T→019, AG→015 (spec #741)."""
DAY: Final = date(2026, 9, 1)
ORDER_A: Final = Order(
    "#5287401", day=DAY, cells={"O": 1, "T": 2, "AG": 1}, amount=float(amount_of(FILE)), emmett={"012": 1, "019": 1}
)
"""Emmett gives 1 in T, the file 2: the process enters T over Emmett's and adds AG, two quantity writes (ADR 0026)."""
ORDER_B: Final = AtrapaOrder(
    order_id=OTHER,
    number="5287499",
    realizator="adrian.testowy",
    address="Sopot-Centrum ul.Inna 1 Lokal 2",
    execution_date=date(2026, 9, 3),
    quantities={"012": 3, "016": 2},
    emmett={"012": 1},
)


class Write(enum.Enum):
    """A write of the process in efenix, by the request the page script sends for it."""

    DATE = "data wykonania"
    EMMETT = "„Załaduj do zlecenia”"
    QUANTITY = "ilość"
    STATUS = "Przekazanie do akceptacji"


# The page scripts of efenix send the order in these fields (reconnaissance of 1.11.2026, copied into the Atrapa): a fact
# of the efenix world, copied on purpose (docs/agents/skille.md, „Co wyrocznia bierze z src”).
WRITES: Final[Mapping[str, tuple[Write, str]]] = {
    SET_DATE: (Write.DATE, "id"),
    LOAD_EMMETT: (Write.EMMETT, "order_id"),
    SAVE_QUANTITY: (Write.QUANTITY, "order_id"),
    CHANGE_STATUS: (Write.STATUS, "order_id"),
}
SLUGS: Final[Mapping[Write, str]] = {Write.DATE: "data", Write.EMMETT: "emmett", Write.QUANTITY: "ilosc", Write.STATUS: "przekazanie"}


class Target(enum.Enum):
    """Where a write that missed order A landed."""

    SHOWN = "zlecenie B, które tata otworzył w karcie"
    ELSEWHERE = "zlecenie, którego proces nie przeczytał, a tata nie otworzył"


class DadAction(enum.Enum):
    """What Dad does in the tool's tab; the value is the case name's prefix."""

    OTHER_ORDER = "inne-zlecenie"
    LIST = "lista"
    RELOAD = "przeladowanie"


TOLD: Final[Mapping[DadAction, str]] = {
    DadAction.OTHER_ORDER: "tata otwiera w karcie narzędzia zlecenie B",
    DadAction.LIST: "tata wraca w karcie narzędzia na listę zleceń",
    DadAction.RELOAD: "tata przeładowuje kartę narzędzia",
}
RELOAD_POINT: Final = "w-przeladowaniu-po-zaladuj"


@dataclass(frozen=True)
class Point:
    """Where Dad acts: in the pause number ``pause`` of the run (``None``: during the reload after „Załaduj do
    zlecenia”), in the mode ``mode``."""

    name: str
    mode: PricingMode
    pause: int | None


@dataclass(frozen=True)
class Case:
    point: Point
    action: DadAction

    @property
    def name(self) -> str:
        return f"{self.action.value}@{self.point.name}"


# --- One run ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Seen:
    """A request the Atrapa received: method, path and parameters."""

    method: str
    path: str
    params: Mapping[str, str]


@dataclass
class Run:
    requests: list[Seen]
    pauses: list[int]
    """For each pause before a write, how many requests the Atrapa had received when it began."""
    acted_at: int | None
    """How many requests the Atrapa had received when Dad acted; ``None``: he never got to act."""
    orders: dict[str, AtrapaOrder]
    kind: OrderKind | None
    stop: str | None
    error: str | None = None


def run_once(browser: Browser, mode: PricingMode, case: Case | None) -> Run:
    """One Uruchomienie in a new tab on a new Atrapa with orders A and B; Dad does ``case`` (``None``: nothing)."""

    with tempfile.TemporaryDirectory(prefix="karta-efenix-") as folder, atrapa_efenix(
        [ORDER_A.in_efenix(READ), ORDER_B], emmett_reload_ms=EFENIX_EMMETT_RELOAD_MS
    ) as atrapa:
        source = write_collective_file(Path(folder), [ORDER_A])
        context = browser.new_context()
        page = context.new_page()
        pauses: list[int] = []
        acted: list[int] = []

        def act(action: DadAction) -> None:
            at = len(atrapa.requests)
            with suppress(PlaywrightError):
                _do(page, action, urljoin(atrapa.url, f"{ORDER_PAGE}?id={OTHER}"), atrapa.url)
                acted.append(at)

        def sleep(_seconds: float) -> None:
            pauses.append(len(atrapa.requests))
            if case is not None and not acted and case.point.pause == len(pauses) - 1:
                act(case.action)

        def finished(request: Request) -> None:
            if case is not None and not acted and case.point.pause is None and request.url.endswith("/" + LOAD_EMMETT):
                act(case.action)

        page.on("requestfinished", finished)

        @contextmanager
        def open_efenix(login: Login) -> Iterator[Efenix]:
            with efenix_browser.window(page, atrapa.url, timeout_ms=LIMIT_MS, login=login, login_timeout_ms=LIMIT_MS) as efenix:
                yield efenix

        outcome: Outcome[PricingSummary] | None = None
        error = None
        try:
            outcome = run_process(
                efenix_process.PROCESS,
                EfenixInputs(source, open_efenix, pace=Pace(sleep=sleep, clock=time.monotonic), mode=mode),
                Tata(),
                view=lambda _inputs, summary: summary,
                metrics_path=Path(folder) / "metryki.jsonl",
                context=RunContext(files=DadFiles()),
            )
        except Exception as failure:  # noqa: BLE001 - BEZ_WYJATKU names any error that escapes run_process
            error = "".join(traceback.format_exception_only(failure)).strip()
        finally:
            with suppress(PlaywrightError):
                context.close()
        requests = [Seen(request.method, request.path, dict(request.params)) for request in atrapa.requests]
        orders = {order.order_id: order for order in atrapa.state()[0]}
    kind, stop = _result(outcome)
    return Run(requests, pauses, acted[0] if acted else None, orders, kind, stop, error)


def _do(page: Page, action: DadAction, other_order: str, list_url: str) -> None:
    match action:
        case DadAction.OTHER_ORDER:
            page.goto(other_order, wait_until="load")
        case DadAction.LIST:
            page.goto(list_url, wait_until="load")
        case DadAction.RELOAD:
            page.reload(wait_until="load")


def _result(outcome: Outcome[PricingSummary] | None) -> tuple[OrderKind | None, str | None]:
    if outcome is None:
        return None, None
    summary: PricingSummary | None = outcome.view
    stop = None
    if isinstance(outcome.ending, Stop):
        stop = outcome.ending.message.code
        if isinstance(outcome.ending.facts, PricingStopped):
            summary = outcome.ending.facts.summary
    kind = summary.results[0].kind if summary is not None and summary.results else None
    return kind, stop


# --- The checks ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stray:
    """A write that reached efenix with another order than A."""

    write: Write
    target: Target


@dataclass(frozen=True)
class StrayShape:
    """The known finding's shape: which writes land elsewhere (``writes``) and where (``targets``)."""

    writes: frozenset[Write]
    targets: frozenset[Target]

    def holds(self, observed: Stray) -> bool:
        return observed.write in self.writes and observed.target in self.targets


KNOWN_FINDINGS: Final[tuple[Excuse[StrayShape], ...]] = (
    Excuse(
        "zapis-w-zleceniu-z-karty",
        "ZAPIS_W_PRZECZYTANYM",
        "set_execution_date, load_emmett i enter_quantity nie sprawdzają, które zlecenie pokazuje karta: klikają przycisk"
        " albo pole strony, która w niej jest, a skrypt strony bierze identyfikator zlecenia z tej strony, więc gdy tata"
        " otworzy w karcie narzędzia inne zlecenie, data wykonania, „Załaduj do zlecenia” i ilości trafiają w nie;"
        " strażnik okna chroni tylko Przekazanie do akceptacji (_blocked_cause porównuje order_id z _order_id)",
        StrayShape(frozenset({Write.DATE, Write.EMMETT, Write.QUANTITY}), frozenset({Target.SHOWN})),
        after=(
            "inne-zlecenie@przed-data",
            "inne-zlecenie@przed-emmett",
            "inne-zlecenie@przed-ilosc-1",
            "inne-zlecenie@przed-ilosc-2",
            f"inne-zlecenie@{RELOAD_POINT}",
        ),
    ),
)
ACCEPTED_RISKS: Final[tuple[Excuse[StrayShape], ...]] = ()


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str
    observed: Stray | None = None


def strays(run: Run) -> list[tuple[Stray, str]]:
    """Each write that reached efenix with an order other than A, with that order."""

    found = []
    for seen in run.requests:
        if seen.method == "POST" and seen.path in WRITES:
            write, key = WRITES[seen.path]
            order = seen.params.get(key, "")
            if order != READ:
                found.append((Stray(write, Target.SHOWN if order == OTHER else Target.ELSEWHERE), order))
    return found


def _state(order: AtrapaOrder | None) -> tuple[object, ...] | None:
    return None if order is None else (order.execution_date, dict(order.quantities), order.status, order.emmett_loads)


def _told(order: AtrapaOrder | None) -> str:
    if order is None:
        return "nie ma"
    quantities = ", ".join(f"{code}: {quantity}" for code, quantity in sorted(order.quantities.items()) if quantity) or "bez ilości"
    day = "bez daty" if order.execution_date is None else f"data {order.execution_date.isoformat()}"
    return f"[{day}; {quantities}; {order.status}; załadowań Emmetta {order.emmett_loads}]"


def check(run: Run, *, reference: bool, mode: PricingMode) -> list[Violation]:
    violations: list[Violation] = []
    if run.error is not None:
        violations.append(Violation("BEZ_WYJATKU", run.error))
    stray = strays(run)
    violations += [
        Violation("ZAPIS_W_PRZECZYTANYM", f"{found.write.value} z identyfikatorem {order!r}: {found.target.value}", found)
        for found, order in stray
    ]
    if _state(run.orders.get(OTHER)) != _state(ORDER_B) and not any(found.target is Target.SHOWN for found, _order in stray):
        violations.append(Violation("ZAPIS_W_PRZECZYTANYM", "zlecenie B zmienione bez zapisu z jego identyfikatorem"))
    if reference:
        a = run.orders.get(READ)
        expected = OrderKind.FORWARDED if mode is PricingMode.FORWARD else OrderKind.READY
        if run.kind is not expected or a is None or dict(a.quantities) != dict(FILE) or a.execution_date != DAY:
            ended = run.kind.value if run.kind is not None else f"Zatrzymaniem {run.stop}"
            violations.append(
                Violation(
                    "PRZEBIEG_WZORCOWY",
                    f"bez taty zlecenie A kończy się: {ended}, w efenix {_told(a)}; ma być {expected.value} z ilościami i datą z pliku",
                )
            )
    return violations


def points(reference: Run, mode: PricingMode) -> tuple[list[tuple[str, int]], list[str]]:
    """The pauses of a reference run as (case point name, pause number), the pause right before each write, and the
    gaps: a write with no pause between it and the write before it, at which Dad has no point."""

    writes = [
        (number, WRITES[seen.path][0]) for number, seen in enumerate(reference.requests) if seen.method == "POST" and seen.path in WRITES
    ]
    named: list[tuple[str, int]] = []
    gaps: list[str] = []
    counts: dict[Write, int] = {}
    for index, (number, write) in enumerate(writes):
        previous = writes[index - 1][0] if index else -1
        pause = next((p for p, at in enumerate(reference.pauses) if previous < at <= number), None)
        if pause is None:
            gaps.append(f"{mode.value}: zapis „{write.value}” bez przerwy przed nim, więc tata nie ma przed nim punktu")
            continue
        counts[write] = counts.get(write, 0) + 1
        repeated = sum(other is write for _number, other in writes) > 1
        named.append((f"przed-{SLUGS[write]}" + (f"-{counts[write]}" if repeated else ""), pause))
    return named, gaps


def cases(fill: Run, forward: Run) -> tuple[list[Case], list[str]]:
    """The cases: each of Dad's actions at each point of the run without Przekazanie, at the points the run with it adds
    (the pause before Przekazanie), and during the reload after „Załaduj do zlecenia”."""

    fill_points, gaps = points(fill, PricingMode.FILL)
    forward_points, forward_gaps = points(forward, PricingMode.FORWARD)
    found = [Point(name, PricingMode.FILL, pause) for name, pause in fill_points]
    found += [Point(name, PricingMode.FORWARD, pause) for name, pause in forward_points if name not in dict(fill_points)]
    if any(seen.path == LOAD_EMMETT for seen in fill.requests):
        found.append(Point(RELOAD_POINT, PricingMode.FILL, None))
    return [Case(point, action) for point in found for action in DadAction], gaps + forward_gaps


# --- The report ---------------------------------------------------------------------------------------------------


@dataclass
class Report:
    new: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    shown: set[tuple[str, str]] = field(default_factory=set)
    ran: set[str] = field(default_factory=set)
    lines: list[str] = field(default_factory=list)


def story(case: Case, run: Run) -> str:
    """The run as numbered steps in the code's words, from Dad's action on."""

    steps = [f"proces czyta zlecenie A (open_order: _order_id = {READ!r})"]
    if run.acted_at is not None:
        where = "w przerwie przed zapisem (Pacing.before_write)" if case.point.pause is not None else "w przeładowaniu po „Załaduj do zlecenia”"
        steps.append(f"{where}: {TOLD[case.action]}")
    labels = {READ: "A", OTHER: "B"}
    for seen in run.requests[run.acted_at or 0 :] if run.acted_at is not None else ():
        if seen.method == "POST" and seen.path in WRITES:
            write, key = WRITES[seen.path]
            order = seen.params.get(key, "")
            steps.append(f"{seen.path} z {key}={order!r}: {write.value} w zleceniu {labels.get(order, order)}")
    ended = run.kind.value if run.kind is not None else "-"
    steps.append(
        f"koniec: wynik zlecenia A {ended}{' (Zatrzymanie ' + run.stop + ')' if run.stop else ''}; w efenix zlecenie A"
        f" {_told(run.orders.get(READ))}, zlecenie B {_told(run.orders.get(OTHER))} (przed przebiegiem {_told(ORDER_B)})"
    )
    return "\n    ".join(f"{number}. {step}" for number, step in enumerate(steps, start=1))


def judge(report: Report, case: Case, run: Run) -> None:
    if run.acted_at is None:
        report.gaps.append(f"{case.name}: tata nie doszedł do swojego punktu, bo przebieg skończył się przed nim")
        return
    report.ran.add(case.name)
    excuses: set[str] = set()
    for violation in check(run, reference=False, mode=case.point.mode):
        found = excused(violation.rule, violation.observed, known=KNOWN_FINDINGS, accepted=ACCEPTED_RISKS)
        if found is None:
            report.new.append(f"NOWE NARUSZENIE {violation.rule} w {case.name}: {violation.detail}\n    {story(case, run)}")
        else:
            report.shown.add((found[1].name, case.name))
            excuses.add(found[1].name)
    if excuses:
        report.known.append(f"{case.name}: {', '.join(sorted(excuses))}\n    {story(case, run)}")
    outcome = run.kind.value if run.kind is not None else "-"
    report.lines.append(f"{case.name}: zlecenie A {outcome}{', Zatrzymanie ' + run.stop if run.stop else ''}; zapisy poza A: {len(strays(run))}")


def in_pool(chosen: Sequence[Case], workers: int) -> list[tuple[Case, Run]]:
    """Each case in its own run, ``workers`` browsers at once, in the order of ``chosen``."""

    tasks: queue.Queue[int] = queue.Queue()
    for number in range(len(chosen)):
        tasks.put(number)
    results: dict[int, Run] = {}

    def worker() -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                while True:
                    try:
                        number = tasks.get_nowait()
                    except queue.Empty:
                        return
                    results[number] = run_once(browser, chosen[number].point.mode, chosen[number])
            finally:
                browser.close()

    threads = [threading.Thread(target=worker, name=f"karta-efenix-{n}") for n in range(max(1, min(workers, len(chosen))))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return [(chosen[number], results[number]) for number in range(len(chosen)) if number in results]


def references() -> dict[PricingMode, Run]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            return {mode: run_once(browser, mode, None) for mode in PricingMode}
        finally:
            browser.close()


def explore(selected: str | None, workers: int) -> Report:
    report = Report()
    reference = references()
    for mode, run in reference.items():
        for violation in check(run, reference=True, mode=mode):
            report.new.append(f"NOWE NARUSZENIE {violation.rule} w przebiegu bez taty ({mode.value}): {violation.detail}")
    found, gaps = cases(reference[PricingMode.FILL], reference[PricingMode.FORWARD])
    report.gaps += gaps
    chosen = [case for case in found if selected in (None, case.name)]
    if selected is not None and not chosen:
        report.gaps.append(f"nie ma przypadku {selected}: --lista podaje przypadki")
    ran = in_pool(chosen, workers)
    report.gaps += [f"{case.name}: przebieg bez wyniku" for case in chosen if case not in {done for done, _run in ran}]
    for case, run in ran:
        judge(report, case, run)
    return report


def summarize(report: Report, *, strict: bool) -> tuple[list[str], int]:
    lines = [*sorted(report.lines), *report.gaps, *report.new]
    lines += [excuse_line("known", entry) for entry in KNOWN_FINDINGS if any(name == entry.name for name, _unit in report.shown)]
    lines += report.known
    gone = gone_lines(report.ran, report.shown, known=KNOWN_FINDINGS, accepted=ACCEPTED_RISKS)
    lines += gone
    known = len({name for name, _unit in report.shown})
    last, code = verdict(
        VERDICT, new=len(report.new) + (known if strict else 0), gone=len(gone), known=0 if strict else known, gaps=len(report.gaps)
    )
    return [*lines, last], code


def main(argv: Sequence[str] | None = None) -> int:
    parser = Parser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--lista", action="store_true", help="drukuje przypadki (z przebiegów bez taty) i kończy")
    parser.add_argument("--przypadek", help="uruchamia tylko ten przypadek (nazwa z --lista)")
    parser.add_argument("--strict", action="store_true", help="znane ustalenia też są naruszeniem")
    parser.add_argument("--przegladarki", type=int, default=min(4, os.cpu_count() or 1), help="ile przeglądarek naraz (domyślnie do 4)")
    args = parser.parse_args(argv)
    if args.lista:
        reference = references()
        found, gaps = cases(reference[PricingMode.FILL], reference[PricingMode.FORWARD])
        print("\n".join([*(f"{case.name} ({case.point.mode.value})" for case in found), *gaps]))
        return 2 if gaps else 0
    started = time.monotonic()
    drift = rozjazd_modelu.rozjazd(Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[4])
    report = explore(args.przypadek, args.przegladarki)
    lines, code = summarize(report, strict=args.strict)
    if drift is not None:
        print(f"UWAGA: {drift}\n")
    print("\n".join(lines[:-1]))
    print(f"czas: {time.monotonic() - started:.1f} s, przypadków: {len(report.ran)}")
    print(lines[-1])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
