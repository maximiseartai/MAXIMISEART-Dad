"""Pliki Konfiguracji tylko do odczytu: trzy Wzorce, konfiguracja wykonawców i plik adresów Wykonawców.

Reguły należą do procesów: Wzorce i Konfigurację wykonawców sprawdza
Sprawdzanie obu procesów (``input_checks``) tymi samymi czytnikami co proces,
z tym samym komunikatem w trzech częściach, którym zatrzymałby się proces
używający tego pliku. Niczego w katalogu konfiguracji nie zapisuje. Stan dla
przeglądarki składa ``configuration_router``, a te same Sprawdzania
(``ConfigurationFiles.templates``, ``workers_problem``) wykonuje Diagnoza.
Karta startu Uruchomienia pyta tu, które skoroszyty wejściowe procesu są otwarte w Excelu (``open_in_excel``).
Moduł nie wczytuje FastAPI: ``ConfigurationFiles`` biorą też Skrypt dla maszyn i odtworzenie bez serwera.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, NamedTuple, assert_never

from rozliczenia import input_checks, workbook_files
from rozliczenia.centrum.process_kind import ConfigurationNeed, TemplateRole
from rozliczenia.input_checks import ProcessTemplate
from rozliczenia.message import Message
from rozliczenia.run_context import TemplateCheck
from rozliczenia.tool_files import CONFIG_DIR, COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, WORKER_CONFIG, WORKER_TEMPLATE
from rozliczenia.worker_addresses import WORKER_ADDRESSES_FILE


@dataclass(frozen=True)
class ConfigurationFiles:
    """Konfiguracja wykonawców, plik adresów Wykonawców i trzy Wzorce, z których korzystają procesy."""

    worker_config: Path
    worker_addresses: Path
    internal_template: Path
    collective_template: Path
    worker_template: Path

    @classmethod
    def default(cls) -> ConfigurationFiles:
        return cls.in_folder(CONFIG_DIR)

    @classmethod
    def in_folder(cls, folder: Path) -> ConfigurationFiles:
        return cls(
            worker_config=folder / WORKER_CONFIG.name,
            worker_addresses=folder / WORKER_ADDRESSES_FILE,
            internal_template=folder / INTERNAL_TEMPLATE.name,
            collective_template=folder / COLLECTIVE_TEMPLATE.name,
            worker_template=folder / WORKER_TEMPLATE.name,
        )

    def path(self, need: ConfigurationNeed) -> Path:
        match need:
            case "worker_config":
                return self.worker_config
            case "worker_addresses":
                return self.worker_addresses
            case "internal_template":
                return self.internal_template
            case "collective_template":
                return self.collective_template
            case "worker_template":
                return self.worker_template
            case _:
                assert_never(need)

    def templates(self) -> tuple[Template, Template, Template]:
        """Trzy Wzorce w kolejności Konfiguracji, każdy pod swoją rolą i ze Sprawdzaniem procesu, który go używa."""

        return (
            Template("Wzorzec rozliczenia wewnętrznego", "internal", ProcessTemplate.internal(self.internal_template)),
            Template("Wzorzec pliku zbiorczego", "collective", ProcessTemplate.collective(self.collective_template)),
            Template("Wzorzec rozliczenia pracownika", "worker", ProcessTemplate.worker(self.worker_template)),
        )

    def template_inputs(self, roles: tuple[TemplateRole, ...]) -> list[InputWorkbook]:
        """Wzorce o rolach ``roles`` (Wzorce procesu z jego wpisu w katalogu) jako skoroszyty wejściowe, w kolejności
        Konfiguracji."""

        return [
            InputWorkbook(template.label, template.path, "template")
            for template in self.templates()
            if template.role in roles
        ]


InputKind = Literal["data_file", "template"]


class InputWorkbook(NamedTuple):
    """Skoroszyt, który proces czyta: etykieta dla taty, ścieżka i rodzaj, od którego zależy rada."""

    label: str
    path: Path
    kind: InputKind


# Plik danych tata uzupełnia, więc go zapisuje; zmiana zapisana we Wzorcu trafiłaby do każdego pliku z niego.
_CLOSING: Final[Mapping[InputKind, str]] = {
    "data_file": "Zapisz go i zamknij.",
    "template": "Zamknij go bez zapisywania zmian.",
}


def open_in_excel(workbooks: Iterable[InputWorkbook]) -> list[str]:
    """Zdania karty startu o skoroszytach wejściowych otwartych w Excelu, w kolejności ``workbooks``.

    Plik blokady zostaje też po awarii Excela, więc zdanie mówi, jak go usunąć, tak jak Zatrzymanie procesu.
    """

    return [
        f"{label} jest otwarty w Excelu. {_CLOSING[kind]} Jeśli Excel jest zamknięty, usuń z tego samego folderu "
        f"pozostawiony plik {workbook_files.excel_lock_file(path).name}."
        for label, path, kind in workbooks
        if workbook_files.is_open_in_excel(path)
    ]


@dataclass(frozen=True)
class Template:
    """Wzorzec: etykieta, rola, pod którą czyta go wpis procesu w katalogu, i Wzorzec procesu ze Sprawdzaniem."""

    label: str
    role: TemplateRole
    template: ProcessTemplate

    @property
    def path(self) -> Path:
        return self.template.file.path

    def problem(self, check: TemplateCheck) -> Message | None:
        """Komunikat, którym zatrzymałby się proces używający Wzorca; ``None``, gdy przechodzi Sprawdzanie ``check``."""

        found = self.template.problem(check)
        return None if found is None else found.message


def workers_problem(config_path: Path) -> Message | None:
    """Komunikat, którym zatrzymałby się proces przy tej konfiguracji wykonawców; ``None``, gdy się wczytuje."""

    workers = input_checks.workers(config_path)
    return workers if isinstance(workers, Message) else None
