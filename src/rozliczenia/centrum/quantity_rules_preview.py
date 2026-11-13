"""Podgląd zmiany Reguł ilości przed zapisem (ADR 0033): skutek na Wierszach danych ostatnich Plików zbiorczych po
Przebiegu rozliczeń, tym samym rachunkiem co Kontrola ilości.

Pliki to Pliki zbiorcze ostatnich ``RECENT`` Folderów okresu ze Statusem okresu „Rozliczenia pracowników gotowe”, od
najnowszego okresu: te tata wypełnił i rozliczył, więc ich ilości to ilości taty. Czyta je ten sam odczyt co Uzupełnienie
(``collective_file.read_numbered_orders`` uchwytem plików taty pracy Centrum), także gdy trzyma je Excel, a odczyt pliku
zostaje w pamięci do zmiany jego znacznika zapisu, więc kolejne podglądy tej samej zmiany nie czytają skoroszytów od nowa.
Plik, którego nie da się przeczytać, podgląd pomija i nazywa jego okres.

Rachunek wiersza to ``quantity_check.row_check`` (ten sam liczy Kontrola ilości) dla reguł teraz i po zmianie, a liczby
różnic to ``quantity_check.check`` każdego pliku, więc ``differences_after`` to liczba różnic Kontroli ilości, którą
dałyby te pliki po zmianie. Wiersz zmienia się, gdy reguły dają w nim inny rodzaj wyniku, inne ilości albo inne kolumny
zostawione puste w Rozliczeniu pracownika. Odpowiedź ma tylko treść dozwoloną filtrem prywatności (``OrderFacts``) bez
``UMOWA``: ``URZĄDZENIA``, ``CZYNNOŚCI``, dzień tygodnia z pełną godziną (jak grupy różnic Kontroli ilości) i ilości,
nigdy adresu, numeru zlecenia ani daty dziennej.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Final

from rozliczenia import collective_file
from rozliczenia.centrum.contract import quantity_rules as contract
from rozliczenia.centrum.contract.quantity_rules import SentencePart
from rozliczenia.centrum.live_file import saved_version
from rozliczenia.collective_file import NumberedOrders
from rozliczenia.collective_layout import QUANTITY_LETTERS
from rozliczenia.dad_files import DadFiles
from rozliczenia.order_facts import MissingHeaders
from rozliczenia.period_folder import PeriodFolder, scan_period_folders
from rozliczenia.quantities_to_fill import NumberedOrder
from rozliczenia.quantity_check import QuantityCheck, RowCheck, check, row_check
from rozliczenia.quantity_engine import QuantityRule, QuantityRules, RuleResult
from rozliczenia.text import WEEKDAY_LABELS
from rozliczenia.workbook_files import WorkbookError

RECENT: Final = 4
"""Tyle ostatnich Plików zbiorczych po Przebiegu rozliczeń bierze podgląd."""
SHOWN_ROWS: Final = 50
"""Najwyżej tyle wierszy z różnicą pokazuje podgląd; resztę tylko liczy."""
_BUILT_IN: Final = frozenset({"P/Q", "S"})


@dataclass(frozen=True)
class RecentFile:
    period: str
    orders: NumberedOrders


@dataclass(frozen=True)
class Recent:
    """Przeczytane Pliki zbiorcze od najnowszego okresu i okresy, których Pliku zbiorczego nie dało się przeczytać."""

    files: tuple[RecentFile, ...]
    unread: tuple[str, ...]


class RecentCollectiveFiles:
    """Ostatnie Pliki zbiorcze po Przebiegu rozliczeń; jeden na pracę Centrum, żądania z kilku wątków czytają po kolei."""

    def __init__(self, files: DadFiles) -> None:
        self._files = files
        self._lock = threading.Lock()
        self._reads: dict[Path, tuple[str, NumberedOrders]] = {}

    def read(self, periods_directory: Path) -> Recent:
        with self._lock:
            settled = _settled(periods_directory)
            files: list[RecentFile] = []
            unread: list[str] = []
            for folder in settled:
                found = self._read(folder.collective_file)
                if found is None:
                    unread.append(folder.period.token)
                else:
                    files.append(RecentFile(folder.period.token, found))
            kept = {folder.collective_file for folder in settled}
            self._reads = {path: read for path, read in self._reads.items() if path in kept}
            return Recent(tuple(files), tuple(unread))

    def _read(self, path: Path) -> NumberedOrders | None:
        version = saved_version(path)
        remembered = self._reads.get(path)
        if version is not None and remembered is not None and remembered[0] == version:
            return remembered[1]
        try:
            found = collective_file.read_numbered_orders(path, self._files)
        except WorkbookError:
            return None
        if isinstance(found, MissingHeaders):
            return None
        if version is not None:
            self._reads[path] = (version, found)
        return found


def _settled(periods_directory: Path) -> list[PeriodFolder]:
    scanned = scan_period_folders(periods_directory)
    settled: list[PeriodFolder] = []
    for folder in sorted(scanned.found(), key=lambda found: found.period.tuesday, reverse=True):
        if folder.observe().status == "worker_settlements_ready":
            settled.append(folder)
            if len(settled) == RECENT:
                break
    return settled


Sentence = Callable[[QuantityRule], list[SentencePart]]
"""Zdanie reguły dla taty, jak w sekcji Reguły ilości."""


def preview(
    before: QuantityRules,
    after: QuantityRules,
    recent: Recent,
    names: Mapping[str, str],
    sentence: Sentence,
    edited: list[SentencePart] | None,
) -> contract.PreviewReady:
    """Skutek zmiany reguł ``before`` → ``after`` na plikach ``recent``; ``names``: litera kolumny → nazwa pozycji
    cennika, ``edited``: zdanie reguły po zmianie (``None`` przy usunięciu)."""

    changed = changed_as_tata = 0
    rows: list[contract.PreviewRow] = []
    shown_more = 0
    rules = {rule.id: rule for rule in after.rules}
    for file in recent.files:
        for numbered in file.orders.rows:
            old, new = row_check(numbered.order, before), row_check(numbered.order, after)
            if _outcome(old.result) == _outcome(new.result):
                continue
            changed += 1
            if not new.differences:
                changed_as_tata += 1
            elif len(rows) < SHOWN_ROWS:
                rows.append(_row(file.period, numbered, old, new, names, rules, sentence))
            else:
                shown_more += 1
    return contract.PreviewReady(
        state="ready",
        sentence=edited,
        files=[contract.PreviewFile(period=file.period, rows=len(file.orders.rows)) for file in recent.files],
        unread=list(recent.unread),
        changed=changed,
        changed_as_tata=changed_as_tata,
        differences_before=_differences(recent.files, before),
        differences_after=_differences(recent.files, after),
        rows=rows,
        more=shown_more,
    )


def _outcome(result: RuleResult | None) -> object:
    """Wynik reguł w wierszu tak, jak go widzi tata: rodzaj, ilości i kolumny zostawione puste."""

    if result is None:
        return None
    return (type(result), dict(result.quantities), result.leave_empty)


def _differences(files: Sequence[RecentFile], rules: QuantityRules) -> int:
    total = 0
    for file in files:
        result = check(tuple(numbered.order for numbered in file.orders.rows), rules)
        assert isinstance(result, QuantityCheck), "plik bez nagłówków wejścia nie trafia do podglądu"
        total += result.difference_count
    return total


def _row(
    period: str,
    numbered: NumberedOrder,
    old: RowCheck,
    new: RowCheck,
    names: Mapping[str, str],
    rules: Mapping[str, QuantityRule],
    sentence: Sentence,
) -> contract.PreviewRow:
    content = numbered.order.content
    assert content is not None and content.started is not None and new.result is not None, "wiersz bez daty się nie zmienia"
    before = {} if old.result is None else old.result.quantities
    after = new.result.quantities
    shown = {*new.differences, *(column for column in QUANTITY_LETTERS if before.get(column, 0) != after.get(column, 0))}
    return contract.PreviewRow(
        period=period,
        row=numbered.number,
        devices=content.devices,
        activities=content.activities,
        when=f"{WEEKDAY_LABELS[content.started.weekday]} {content.started.at.hour}",
        cells=[
            contract.PreviewCell(
                column=column,
                name=names.get(column) or None,
                before=before.get(column, 0),
                after=after.get(column, 0),
                tata=numbered.order.quantity(column),
            )
            for column in QUANTITY_LETTERS
            if column in shown
        ],
        sums=_sums(new.result, names, rules, sentence),
    )


def _sums(
    result: RuleResult, names: Mapping[str, str], rules: Mapping[str, QuantityRule], sentence: Sentence
) -> list[contract.PreviewSum]:
    """Kolumny, w które wpisało kilka reguł, z sumą i tymi regułami (US 61)."""

    by_column: dict[str, list[str]] = {}
    for contribution in result.contributions:
        if contribution.source not in _BUILT_IN:
            by_column.setdefault(contribution.column, [])
            if contribution.source not in by_column[contribution.column]:
                by_column[contribution.column].append(contribution.source)
    return [
        contract.PreviewSum(
            column=column,
            name=names.get(column) or None,
            total=result.quantities.get(column, 0),
            rules=[contract.SummedRule(id=rule, sentence=sentence(rules[rule])) for rule in by_column[column]],
        )
        for column in QUANTITY_LETTERS
        if len(by_column.get(column, ())) > 1
    ]
