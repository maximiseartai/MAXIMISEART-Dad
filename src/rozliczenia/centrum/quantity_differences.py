from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Final

from fastapi import APIRouter

from rozliczenia.centrum import refusal
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import quantity_differences as contract
from rozliczenia.centrum.contract.quantity_rules import (
    ComponentCondition,
    DevicesCondition,
    FillAction,
    RuleCondition,
    RuleForm,
    RuleWrite,
    SentenceColumn,
    SentencePart,
    SentenceText,
)
from rozliczenia.centrum.contract.settings_workers import SettingProblem
from rozliczenia.centrum.quantity_rules_preview import Recent, RecentCollectiveFiles
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.quantity_rules_router import PriceList, RuleSentences
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.quantity_exceptions import (
    SECTION,
    QuantityException,
    entry_of,
    exception_of,
)
from rozliczenia.collective_layout import QUANTITY_LETTERS
from rozliczenia.order_facts import TataValue
from rozliczenia.quantity_check import row_check, week_hour
from rozliczenia.quantity_engine import BUILT_IN_COLUMNS, DeviceList, OrderContent, QuantityRules, RuleResult, devices_read
from rozliczenia.text import normalize_text

SHOWN: Final = 50
_UNREADABLE: Final[dict[int | str, dict[str, object]]] = {409: {"model": common_contract.Problem}}

@dataclass(frozen=True)
class Difference:
    period: str
    row: int
    content: OrderContent
    column: str
    result: RuleResult
    tata: TataValue

    @property
    def rule(self) -> int:
        return self.result.quantities.get(self.column, 0)

    @property
    def exception(self) -> QuantityException:
        return exception_of(self.period, self.row, self.column, self.tata, self.content)


def differences(recent: Recent, rules: QuantityRules) -> list[Difference]:
    found: list[Difference] = []
    for file in recent.files:
        for numbered in file.orders.rows:
            checked = row_check(numbered.order, rules)
            content = numbered.order.content
            if checked.result is None or content is None:
                continue
            found.extend(
                Difference(file.period, numbered.number, content, column, checked.result, numbered.order.quantity(column))
                for column in sorted(checked.differences, key=QUANTITY_LETTERS.index)
            )
    return found


def quantity_differences_router(settings: CentrumSettings, price_list: PriceList, recent: RecentCollectiveFiles) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    def listed() -> tuple[contract.QuantityDifferences, list[Difference]]:
        view = settings.quantity_rules()
        rules = view.rules
        bad = view.exceptions_problem
        problem = None if bad is None else SettingProblem(field=bad.place, message=bad.sentence)
        directory = settings.folders().periods_directory_to_read
        if directory is None:
            return contract.DifferencesWithoutFiles(state="no_periods_directory", exceptions_problem=problem), []
        found = recent.read(directory)
        if not found.files and not found.unread:
            return contract.DifferencesWithoutFiles(state="no_settled_periods", exceptions_problem=problem), []
        every = differences(found, rules)
        excepted = {exception.id for exception in view.exceptions}
        shown = [difference for difference in every if difference.exception.id not in excepted]
        names = price_list.names()
        return (
            contract.DifferencesReady(
                state="ready",
                unread=list(found.unread),
                differences=[_difference(difference, names, rules.devices) for difference in shown[:SHOWN]],
                more=max(0, len(shown) - SHOWN),
                exceptions=len(every) - len(shown),
                exceptions_problem=problem,
            ),
            every,
        )

    @router.get("/quantity-rules/differences", operation_id="getQuantityDifferences", responses=_UNREADABLE)
    def read() -> contract.QuantityDifferences:
        return listed()[0]

    @router.post("/quantity-rules/differences/{difference_id}/exception", operation_id="markQuantityException", responses=NOT_FOUND_OR_CONFLICT)
    def mark(difference_id: str) -> contract.ExceptionSaved:
        """„To był wyjątek”: wyjątek różnicy o tym id z różnic policzonych teraz, zapisem właściciela Ustawień."""

        exception = next(
            (difference.exception for difference in listed()[1] if difference.exception.id == difference_id), None
        )
        if exception is None:
            raise refusal.quantity_difference_unknown()
        match settings.change_exceptions(exception):
            case Saved(change=change):
                return contract.ExceptionSaved(differences=listed()[0], change=change)
            case Refused(problem=problem):
                raise refusal.setting_refused(problem)
            case NotSaved():
                raise refusal.settings_not_saved()
            case KeptInPeriods(presence=presence, what=what):
                raise refusal.worker_kept(presence, what)

    return router


def _difference(difference: Difference, names: Mapping[str, str], devices: DeviceList) -> contract.QuantityDifference:
    content = difference.content
    assert content.started is not None, "wiersz bez daty i godziny w DATA nie ma różnic"
    return contract.QuantityDifference(
        id=difference.exception.id,
        period=difference.period,
        row=difference.row,
        devices=content.devices,
        activities=content.activities,
        when=week_hour(content.started.weekday, content.started.at.hour),
        column=difference.column,
        name=names.get(difference.column) or None,
        rule=difference.rule,
        tata=difference.tata,
        draft=_draft(difference, devices),
    )


def _draft(difference: Difference, devices: DeviceList) -> RuleForm:
    read = devices_read(devices, difference.content)
    conditions: list[RuleCondition]
    if read.all_known:
        conditions = [
            ComponentCondition(kind="component", component=component, negated=False) for component in read.components
        ] or [DevicesCondition(kind="devices", mode="empty", text="", negated=False)]
    else:
        text = normalize_text(difference.content.devices)
        conditions = [DevicesCondition(kind="devices", mode="contains", text=text, negated=False)]
    missing = difference.tata - difference.rule if isinstance(difference.tata, int) else 0
    action = (
        FillAction(kind="fill", writes=[RuleWrite(column=difference.column, value=missing, multiplier="once", component=None)])
        if missing > 0 and difference.column not in BUILT_IN_COLUMNS
        else None
    )
    return RuleForm(scope="known" if read.all_known else "unknown", conditions=conditions, action=action)


def exception_sentence(exception: QuantityException, names: Mapping[str, str]) -> list[SentencePart]:
    tata = exception.tata if isinstance(exception.tata, int) else "wartość nieliczbową"
    return [
        SentenceText(kind="text", text=f"To był wyjątek: okres {exception.period}, wiersz {exception.row}, "),
        SentenceColumn(kind="column", letter=exception.column, name=names.get(exception.column) or None),
        SentenceText(kind="text", text=f": wpisałeś {tata}."),
    ]


def with_exception_sentences(rules: Callable[[], RuleSentences], price_list: PriceList) -> Callable[[], RuleSentences]:
    def reader() -> RuleSentences:
        rule_sentence = rules()
        names = price_list.names()

        def sentence(key: str, value: str | None) -> list[SentencePart] | None:
            if key.partition(".")[0] != SECTION:
                return rule_sentence(key, value)
            if value is None:
                return None
            try:
                exception = entry_of(json.loads(value))
            except ValueError:
                return None
            return None if exception is None else exception_sentence(exception, names)

        return sentence

    return reader
