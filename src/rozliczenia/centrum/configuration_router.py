from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, assert_never

from fastapi import APIRouter

from rozliczenia import workbook_files
from rozliczenia.centrum.configuration import Template
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import configuration as configuration_contract
from rozliczenia.centrum.keyed_box import KeyJudgement
from rozliczenia.centrum.tool_freshness import Judgement, ReleaseSource, ToolFreshness, offers_update
from rozliczenia.centrum.version import short_commit
from rozliczenia.message import Message
from rozliczenia.run_context import TemplateCheck
from rozliczenia.workbook_files import Problem


_Problem = tuple[configuration_contract.TemplateProblemKind, Message]


def _kind(problem: Problem) -> configuration_contract.TemplateProblemKind:
    match problem:
        case Problem.MISSING:
            return "missing"
        case Problem.OPEN_IN_EXCEL:
            return "open_in_excel"
        case Problem.INACCESSIBLE | Problem.UNREADABLE | Problem.LAYOUT | Problem.HAS_DATA:
            return "unreadable"
        case _:
            assert_never(problem)


def configuration_router(
    templates: Callable[[], Sequence[Template]],
    freshness: ToolFreshness,
    release: ReleaseSource,
    key_judgement: Callable[[], KeyJudgement],
    template_check: TemplateCheck,
) -> APIRouter:
    router = APIRouter(prefix="/api/configuration", tags=["konfiguracja"])
    checked = _CheckedTemplates(template_check)

    @router.get("", operation_id="getConfiguration")
    def configuration() -> configuration_contract.Configuration:
        commit = freshness.local()
        judgement = freshness.judge(release)
        return configuration_contract.Configuration(
            version=None if commit is None else configuration_contract.ToolVersion(commit=short_commit(commit), since=freshness.since()),
            freshness=_STATE[judgement],
            update_offered=offers_update(judgement),
            templates=[checked.status(template) for template in templates()],
            reports=_KEY_STATE[key_judgement()],
        )

    return router


_STATE: Final[Mapping[Judgement, configuration_contract.ToolFreshnessState]] = {
    "current": "current",
    "newer": "newer",
    "no_release": "not_checked",
    "no_answer": "not_checked",
    "no_commit": "not_checked",
}


_KEY_STATE: Final[Mapping[KeyJudgement, configuration_contract.ReportKeyState]] = {
    "accepted": "ready",
    "unchecked": "ready",
    "refused": "refused_key",
    "missing": "missing_key",
}
CONFIGURATION_WAIT_S: Final = 1.0


_CONTENT_PROBLEMS: Final = frozenset({Problem.UNREADABLE, Problem.LAYOUT, Problem.HAS_DATA})


class _CheckedTemplates:
    def __init__(self, check: TemplateCheck) -> None:
        self._check = check
        self._results: dict[Path, tuple[tuple[int, int, bool], _Problem | None]] = {}

    def status(self, template: Template) -> configuration_contract.TemplateStatus:
        label, path = template.label, template.path
        found = self._problem(template)
        if found is None:
            return configuration_contract.TemplateReady(state="ready", label=label, file_name=path.name)
        problem, message = found
        return configuration_contract.TemplateProblem(
            state="problem", label=label, file_name=path.name, problem=problem, message=common_contract.Message.of(message)
        )

    def _problem(self, template: Template) -> _Problem | None:
        path = template.path
        try:
            stat = path.stat()
        except OSError:
            signature = None
        else:
            signature = (stat.st_mtime_ns, stat.st_size, workbook_files.is_open_in_excel(path))
            cached = self._results.get(path)
            if cached is not None and cached[0] == signature:
                return cached[1]
        found = template.template.problem(self._check)
        result = None if found is None else (_kind(found.problem), found.message)
        if signature is not None:
            if found is None or found.problem in _CONTENT_PROBLEMS:
                self._results[path] = (signature, result)
        return result

