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
from rozliczenia.quantity_check import RowCheck, row_check, week_hour
from rozliczenia.quantity_engine import QuantityRule, QuantityRules, RuleResult
from rozliczenia.workbook_files import WorkbookError

RECENT: Final = 4
SHOWN_ROWS: Final = 50
_BUILT_IN: Final = frozenset({"P/Q", "S"})


@dataclass(frozen=True)
class RecentFile:
    period: str
    orders: NumberedOrders


@dataclass(frozen=True)
class Recent:
    files: tuple[RecentFile, ...]
    unread: tuple[str, ...]


class RecentCollectiveFiles:
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
        if folder.observe().settled:
            settled.append(folder)
            if len(settled) == RECENT:
                break
    return settled


Sentence = Callable[[QuantityRule], list[SentencePart]]

def preview(
    before: QuantityRules,
    after: QuantityRules,
    recent: Recent,
    names: Mapping[str, str],
    sentence: Sentence,
    edited: list[SentencePart] | None,
) -> contract.PreviewReady:
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
    if result is None:
        return None
    return (type(result), dict(result.quantities), result.leave_empty)


def _differences(files: Sequence[RecentFile], rules: QuantityRules) -> int:
    return sum(len(row_check(numbered.order, rules).differences) for file in files for numbered in file.orders.rows)


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
        when=week_hour(content.started.weekday, content.started.at.hour),
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
