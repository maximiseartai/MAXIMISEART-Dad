from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Final

from rozliczenia import intermax_ordering, preparation_messages, preparation_register, workbook_files
from rozliczenia.centrum import diagnosis_messages
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import diagnosis as diagnosis_contract
from rozliczenia.centrum.catalog import declaration_of
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import ConfigurationFiles, Template, workers_problem
from rozliczenia.centrum.keyed_box import KeyJudgement
from rozliczenia.centrum.log import UNEXPECTED_FAILURE_EVENT, CentrumLog, event_of
from rozliczenia.centrum.process_kind import CheckStep, NeededSetting, PeriodFolderCheck, ProcessKind
from rozliczenia.centrum.tool_freshness import RateLimited, ToolFreshness, offers_update
from rozliczenia.centrum.version import short_commit
from rozliczenia.dad_files import DadFiles
from rozliczenia.file_state import file_state
from rozliczenia.message import Message
from rozliczenia.period_folder import (
    PeriodFolder,
    PeriodFolderInaccessible,
    PeriodFolderLookupError,
    PeriodPlace,
    locate_period_folder,
    period_place_label,
)
from rozliczenia.centrum.settings.files import Unreadable
from rozliczenia.centrum.settings.folders import FolderSettings
from rozliczenia.centrum.settings.owner import WorkerListRead
from rozliczenia.run_context import TemplateCheck
from rozliczenia.settlement_period import SettlementPeriod, parse_period_token

LOG_ENTRIES: Final = 20


class _FoldersUnread(Exception):
    def __init__(self, file: str) -> None:
        super().__init__(file)
        self.file = file


@dataclass(frozen=True)
class CheckResult:
    label: str
    state: diagnosis_contract.CheckState
    detail: str
    message: Message | None = None
    fixed_by_update: bool = False

    @classmethod
    def passed(cls, label: str, detail: str) -> CheckResult:
        return cls(label, "passed", detail)

    @classmethod
    def failed(cls, label: str, message: Message) -> CheckResult:
        return cls(label, "failed", message.what, message)

    @classmethod
    def not_checked(cls, label: str, detail: str) -> CheckResult:
        return cls(label, "not_checked", detail)

    @classmethod
    def aside(cls, label: str, detail: str) -> CheckResult:
        return cls(label, "failed", detail)

    @classmethod
    def newer_tool_version(cls, label: str) -> CheckResult:
        message = diagnosis_messages.newer_tool_version()
        return cls(label, "failed", message.what, message, fixed_by_update=True)


@dataclass(frozen=True)
class Diagnosis:
    checks: tuple[CheckResult, ...]
    log_entries: tuple[str, ...]

    @property
    def _explaining(self) -> CheckResult | None:
        return next((check for check in self.checks if check.message is not None), None)

    @property
    def cause(self) -> Message | None:
        explaining = self._explaining
        return None if explaining is None else explaining.message

    @property
    def explanation(self) -> Message:
        return self.cause or diagnosis_messages.cause_not_found()

    @property
    def proposes_update(self) -> bool:
        explaining = self._explaining
        newer = any(check.fixed_by_update for check in self.checks)
        return newer and explaining is not None and not explaining.fixed_by_update

    @property
    def next_action(self) -> diagnosis_contract.DiagnosisNextAction:
        explaining = self._explaining
        if explaining is not None and explaining.fixed_by_update:
            return "update"
        cause = self.cause
        return "report" if cause is None or cause.reports_to_maintainer else "rerun"

    def view(self, stop: Message, report: diagnosis_contract.ReportDraft) -> diagnosis_contract.Diagnosis:
        explanation = self.explanation
        return diagnosis_contract.Diagnosis(
            explanation=common_contract.Message.of(explanation),
            confirms_stop=explanation == stop,
            next_action=self.next_action,
            update_proposal=self.proposes_update,
            checks=[diagnosis_contract.DiagnosisCheck(label=check.label, state=check.state, detail=check.detail) for check in self.checks],
            report=report,
        )


@dataclass(frozen=True)
class Surroundings:
    tool_freshness: ToolFreshness
    cloud_files: CloudFiles
    report_key: Callable[[], KeyJudgement]


@dataclass(frozen=True)
class _ProcessFiles:
    declaration: ProcessKind[Any, Any]
    period: SettlementPeriod
    settings: FolderSettings | Unreadable
    configuration: ConfigurationFiles

    @property
    def folders(self) -> FolderSettings:
        if isinstance(self.settings, Unreadable):
            raise _FoldersUnread(self.settings.name)
        return self.settings

    @cached_property
    def period_folder(self) -> PeriodFolder | PeriodFolderLookupError | None:
        periods_directory = self.folders.periods_directory_to_read
        if periods_directory is None:
            return None
        try:
            return locate_period_folder(periods_directory, self.period)
        except PeriodFolderLookupError as error:
            return error

    @cached_property
    def period_files(self) -> tuple[Path, ...]:
        folder = self.period_folder
        if not isinstance(folder, PeriodFolder):
            return ()
        return (folder.internal_settlement, folder.collective_file, *folder.worker_settlement_files())

    @cached_property
    def templates(self) -> tuple[Template, ...]:
        return tuple(template for template in self.configuration.templates() if template.role in self.declaration.templates)

    @property
    def files(self) -> list[Path]:
        register = self.folders.register_to_read
        files = [register] if self.declaration.reads_register and register is not None else []
        files += [template.path for template in self.templates]
        return files + list(self.period_files) if self.declaration.reads_period_folder else files


def files_of_process(
    process: common_contract.ProcessKey,
    period: str,
    *,
    settings: FolderSettings | Unreadable,
    configuration: ConfigurationFiles,
) -> list[Path] | Unreadable:
    if isinstance(settings, Unreadable):
        return settings
    return _ProcessFiles(declaration_of(process), parse_period_token(period), settings, configuration).files


@dataclass(frozen=True)
class _Computer(_ProcessFiles):
    log: CentrumLog
    surroundings: Surroundings
    template_check: TemplateCheck
    dad_files: DadFiles
    workers: WorkerListRead

    @cached_property
    def log_entries(self) -> tuple[str, ...]:
        return tuple(self.log.recent(LOG_ENTRIES))


_CheckRun = Callable[[_Computer, str], list[CheckResult]]
_NOT_CHECKED_UNEXPECTED: Final = "Nie udało się sprawdzić: nieoczekiwany błąd."


@dataclass(frozen=True)
class _Check:
    label: str
    run: _CheckRun

    def results(self, computer: _Computer) -> list[CheckResult]:
        try:
            return self.run(computer, self.label)
        except PeriodFolderInaccessible as inaccessible:
            return [CheckResult.failed(self.label, preparation_messages.folder_inaccessible(inaccessible.folder))]
        except _FoldersUnread as unread:
            return [CheckResult.not_checked(self.label, f"Nie sprawdzono: pliku {unread.file} w folderze config nie dało się przeczytać.")]
        except Exception as failure:
            computer.log.unexpected_failure(failure, where=f"Diagnoza: {self.label}")
            return [CheckResult.not_checked(self.label, _NOT_CHECKED_UNEXPECTED)]


def _check(label: str) -> Callable[[_CheckRun], _Check]:
    def named(run: _CheckRun) -> _Check:
        return _Check(label, run)

    return named


@_check("Aktualność narzędzia")
def _tool_freshness(computer: _Computer, label: str) -> list[CheckResult]:
    freshness = computer.surroundings.tool_freshness
    judgement, answer = freshness.assess()
    if offers_update(judgement):
        return [CheckResult.newer_tool_version(label)]
    if judgement == "current":
        return [CheckResult.passed(label, f"Najnowsza wersja z GitHuba, commit {short_commit(freshness.local() or '')}.")]
    if isinstance(answer, RateLimited):
        return [
            CheckResult.not_checked(
                label,
                "Nie sprawdzono: GitHub chwilowo nie odpowiada na pytania o nową wersję. "
                f"Centrum sprawdzi ponownie po {answer.reset.astimezone():%H:%M}.",
            )
        ]
    return [CheckResult.not_checked(label, _NOT_CHECKED_FRESHNESS[judgement])]


_NOT_CHECKED_FRESHNESS: Final = {
    "no_commit": "Nie sprawdzono: narzędzie na tym komputerze nie ma commitu Gita.",
    "no_answer": "Nie sprawdzono: brak połączenia z GitHubem.",
    "no_release": "Nie sprawdzono: na GitHubie nie ma jeszcze żadnego Wydania.",
}


@_check("Ustawienia Centrum")
def _tata_settings(computer: _Computer, label: str) -> list[CheckResult]:
    settings = computer.folders
    needed: Sequence[NeededSetting] = computer.declaration.settings
    for setting in needed:
        chosen = setting.chosen(settings)
        if chosen is None:
            return [CheckResult.not_checked(label, f"Nie wskazano: {setting.name}.")]
        state = setting.state(settings)
        if state == "missing":
            return [CheckResult.failed(label, setting.missing(chosen))]
        if state == "inaccessible":
            return [CheckResult.not_checked(label, f"Nie da się teraz odczytać: {setting.name}.")]
    names = " i ".join(setting.name for setting in needed)
    return [CheckResult.passed(label, f"{names[:1].upper()}{names[1:]} {'są' if len(needed) > 1 else 'jest'} na miejscu.")]


@_check("Rejestr zleceń")
def _register(computer: _Computer, label: str) -> list[CheckResult]:
    register = computer.folders.register_to_read
    if register is None:
        return [CheckResult.not_checked(label, "Rejestru zleceń nie ma na miejscu.")]
    problem = preparation_register.register_problem(register, computer.dad_files)
    if problem is not None:
        return [CheckResult.failed(label, problem)]
    return [CheckResult.passed(label, "Nie jest otwarty w Excelu, otwiera się i ma wymagane nagłówki.")]


@_check("INTERMAX")
def _intermax(computer: _Computer, label: str) -> list[CheckResult]:
    register = computer.folders.register_to_read
    if register is None:
        return [CheckResult.not_checked(label, "INTERMAX nie ma na miejscu.")]
    problem = intermax_ordering.register_problem(register, computer.dad_files)
    if problem is not None:
        return [CheckResult.failed(label, problem)]
    return [CheckResult.passed(label, "Obok nie leży kopia konfliktu OneDrive, nie jest otwarty w Excelu, otwiera się i ma arkusz zleceń.")]


@_check("Wzorce")
def _templates(computer: _Computer, label: str) -> list[CheckResult]:
    return [
        result
        for template in computer.templates
        for result in _Check(template.label, _template_check(template)).results(computer)
    ]


def _template_check(template: Template) -> _CheckRun:
    def check(computer: _Computer, label: str) -> list[CheckResult]:
        problem = template.problem(computer.template_check)
        if problem is None:
            return [CheckResult.passed(label, f"{template.path.name} przechodzi Sprawdzanie.")]
        return [CheckResult.failed(label, problem)]

    return check


@_check("Lista Wykonawców")
def _worker_list(computer: _Computer, label: str) -> list[CheckResult]:
    workers = computer.workers
    problem = workers.problem()
    if problem is None:
        return [CheckResult.passed(label, f"Wykonawców na liście: {len(workers.counted().workers)}.")]
    return [CheckResult.failed(label, workers_problem(problem))]


def _period_folder(
    computer: _Computer, label: str, collective_file_missing: Callable[[Path], Message] | None
) -> list[CheckResult]:
    folder = computer.period_folder
    if folder is None:
        return [CheckResult.not_checked(label, "Folderu okresów nie ma na miejscu.")]
    if isinstance(folder, PeriodFolderLookupError):
        return [CheckResult.failed(label, preparation_messages.period_folder_lookup_problem(folder))]
    observed = folder.observe()
    if collective_file_missing is not None and not observed.collective_file_exists:
        return [CheckResult.failed(label, collective_file_missing(folder.collective_file))]
    places: tuple[PeriodPlace, ...] = ("internal_settlement", "collective_file", "worker_settlements_folder")
    present = [period_place_label(place) for place in places if observed.exists(place)]
    if not observed.period_folder_exists:
        return [CheckResult.passed(label, f"Folderu {computer.period.token} jeszcze nie ma.")]
    return [CheckResult.passed(label, f"Pliki okresu: {', '.join(present) if present else 'brak'}.")]


@_check("Pliki okresu w Excelu")
def _period_files_in_excel(computer: _Computer, label: str) -> list[CheckResult]:
    folder = computer.period_folder
    if not isinstance(folder, PeriodFolder):
        return [CheckResult.not_checked(label, "Nie odszukano Folderu okresu.")]
    for path in computer.period_files:
        if workbook_files.is_open_in_excel(path):
            return [CheckResult.failed(label, diagnosis_messages.period_file_open(path))]
    return [CheckResult.passed(label, "Żaden plik okresu nie jest otwarty w Excelu.")]


@_check("Pliki w OneDrive")
def _files_in_onedrive(computer: _Computer, label: str) -> list[CheckResult]:
    cloud = computer.surroundings.cloud_files
    if not cloud.checked:
        return [CheckResult.not_checked(label, "Nie sprawdzono: tylko w Windows.")]
    states = [(path, file_state(path)) for path in computer.files]
    files = [path for path, state in states if state == "file"]
    for path in files:
        if cloud.online_only(path):
            return [CheckResult.failed(label, diagnosis_messages.file_only_in_cloud(path))]
    unreadable = sum(state == "inaccessible" for _, state in states)
    if unreadable:
        detail = f"Nie da się teraz odczytać plików: {unreadable}. Pozostałe są na tym komputerze: {len(files)}."
        return [CheckResult.not_checked(label, detail)]
    return [CheckResult.passed(label, f"Sprawdzone pliki są na tym komputerze: {len(files)}.")]


@_check("Token do Zgłoszeń")
def _report_key(computer: _Computer, label: str) -> list[CheckResult]:
    match computer.surroundings.report_key():
        case "accepted":
            return [CheckResult.passed(label, "Skrzynka Zgłoszeń przyjmuje Token do Zgłoszeń.")]
        case "refused":
            return [CheckResult.aside(label, "Skrzynka Zgłoszeń odrzuca Token do Zgłoszeń. Zgłoszenie poczeka, aż Maks go wymieni.")]
        case "missing":
            return [CheckResult.aside(label, "Na tym komputerze nie ma Tokenu do Zgłoszeń. Zgłoszenie poczeka, aż Maks go wpisze.")]
        case "unchecked":
            return [CheckResult.not_checked(label, "Nie sprawdzono: brak połączenia ze Skrzynką Zgłoszeń.")]


@_check("Dziennik Centrum rozliczeń")
def _centrum_log(computer: _Computer, label: str) -> list[CheckResult]:
    entries = computer.log_entries
    unexpected = ", w tym nieoczekiwany wyjątek" if any(event_of(entry) == UNEXPECTED_FAILURE_EVENT for entry in entries) else ""
    return [CheckResult.passed(label, f"Ostatnie wpisy od startu Centrum: {len(entries)}{unexpected}.")]


def _check_of(step: CheckStep) -> _Check:
    match step:
        case "tata_settings":
            return _tata_settings
        case "files_in_onedrive":
            return _files_in_onedrive
        case "register":
            return _register
        case "intermax":
            return _intermax
        case "templates":
            return _templates
        case "period_files_in_excel":
            return _period_files_in_excel
        case "tool_freshness":
            return _tool_freshness
        case "report_key":
            return _report_key
        case "centrum_log":
            return _centrum_log
        case "worker_list":
            return _worker_list
        case PeriodFolderCheck(collective_file_missing=missing):
            return _Check("Folder okresu", lambda computer, label: _period_folder(computer, label, missing))


def diagnose(
    process: common_contract.ProcessKey,
    period: str,
    *,
    settings: FolderSettings | Unreadable,
    configuration: ConfigurationFiles,
    log: CentrumLog,
    surroundings: Surroundings,
    template_check: TemplateCheck,
    files: DadFiles,
    workers: WorkerListRead,
) -> Diagnosis:
    declaration = declaration_of(process)
    computer = _Computer(
        declaration, parse_period_token(period), settings, configuration, log, surroundings, template_check, files, workers
    )
    checks: list[CheckResult] = []
    for step in declaration.checks:
        checks.extend(_check_of(step).results(computer))
    return Diagnosis(tuple(checks), computer.log_entries)
