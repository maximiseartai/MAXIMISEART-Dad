from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, NamedTuple, assert_never

from rozliczenia import workbook_files
from rozliczenia.centrum.process_kind import ConfigurationNeed, TemplateRole
from rozliczenia.input_checks import ProcessTemplate
from rozliczenia.run_context import TemplateCheck
from rozliczenia.centrum import diagnosis_messages
from rozliczenia.centrum.settings.files import FieldProblem, Unreadable
from rozliczenia.message import Message
from rozliczenia.tool_files import CONFIG_DIR, COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, WORKER_TEMPLATE


@dataclass(frozen=True)
class ConfigurationFiles:
    internal_template: Path
    collective_template: Path
    worker_template: Path

    @classmethod
    def default(cls) -> ConfigurationFiles:
        return cls.in_folder(CONFIG_DIR)

    @classmethod
    def in_folder(cls, folder: Path) -> ConfigurationFiles:
        return cls(
            internal_template=folder / INTERNAL_TEMPLATE.name,
            collective_template=folder / COLLECTIVE_TEMPLATE.name,
            worker_template=folder / WORKER_TEMPLATE.name,
        )

    def path(self, need: ConfigurationNeed) -> Path:
        match need:
            case "internal_template":
                return self.internal_template
            case "collective_template":
                return self.collective_template
            case "worker_template":
                return self.worker_template
            case _:
                assert_never(need)

    def templates(self) -> tuple[Template, Template, Template]:
        return (
            Template("Wzorzec rozliczenia wewnętrznego", "internal", ProcessTemplate.internal(self.internal_template)),
            Template("Wzorzec pliku zbiorczego", "collective", ProcessTemplate.collective(self.collective_template)),
            Template("Wzorzec rozliczenia pracownika", "worker", ProcessTemplate.worker(self.worker_template)),
        )

    def template_inputs(self, roles: tuple[TemplateRole, ...]) -> list[InputWorkbook]:
        return [
            InputWorkbook(template.label, template.path, "template")
            for template in self.templates()
            if template.role in roles
        ]


InputKind = Literal["data_file", "template"]


class InputWorkbook(NamedTuple):
    label: str
    path: Path
    kind: InputKind


_CLOSING: Final[Mapping[InputKind, str]] = {
    "data_file": "Zapisz go i zamknij.",
    "template": "Zamknij go bez zapisywania zmian.",
}


def open_in_excel(workbooks: Iterable[InputWorkbook]) -> list[str]:
    return [
        f"{label} jest otwarty w Excelu. {_CLOSING[kind]} Jeśli Excel jest zamknięty, usuń z tego samego folderu "
        f"pozostawiony plik {workbook_files.excel_lock_file(path).name}."
        for label, path, kind in workbooks
        if workbook_files.is_open_in_excel(path)
    ]


@dataclass(frozen=True)
class Template:
    label: str
    role: TemplateRole
    template: ProcessTemplate

    @property
    def path(self) -> Path:
        return self.template.file.path

    def problem(self, check: TemplateCheck) -> Message | None:
        found = self.template.problem(check)
        return None if found is None else found.message


def workers_problem(problem: FieldProblem | Unreadable) -> Message:
    match problem:
        case FieldProblem(sentence=sentence):
            return diagnosis_messages.worker_list_bad(sentence)
        case Unreadable():
            return diagnosis_messages.worker_list_unreadable()
