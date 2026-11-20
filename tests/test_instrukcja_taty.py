from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import inspect
from pathlib import Path
import re
import sys
from types import FrameType, ModuleType

import pytest

from rozliczenia import efenix_messages, intermax_messages
from rozliczenia import preparation_messages as messages
from rozliczenia import settlement_messages
from rozliczenia.centrum import (
    diagnosis_messages,
    fill_messages,
    notification_messages,
    report_messages,
    start_problems,
    update_messages,
)
from rozliczenia.message import Message

from tests.fixtures.message_samples import (
    ABOVE_CONFIG,
    DIAGNOSIS_SAMPLES,
    EFENIX_SAMPLES,
    FILL_SAMPLES,
    NOTIFICATION_SAMPLES,
    INTERMAX_ORDERING_ONLY,
    PREPARATION_SAMPLES,
    REPORT_SAMPLES,
    SETTLEMENT_SAMPLES,
    START_SAMPLES,
    UPDATE_SAMPLES,
    Samples,
)


INSTRUCTION = Path(__file__).resolve().parents[1] / "docs" / "tata-instrukcja.md"
QUOTED = re.compile(r"„([^”]+)”")
FULL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|(?<![:\\/])(?:\\\\|//)[^\\/\s]")
ABOVE_PERIOD_FOLDER = ABOVE_CONFIG | {"Dane", "INEA"}
ABOVE_REPORT_QUEUE = ABOVE_CONFIG | {"config", "zgloszenia"}
ABOVE_TOOL_FOLDER = ABOVE_CONFIG - {"Narzedzie"}
RESTORING_INTERMAX_COPY = frozenset({"copies_unreadable", "copy_missing", "copy_unusable", "copy_damaged"})

@dataclass(frozen=True)
class Catalog:
    module: ModuleType
    section: str
    samples: Samples
    outside_centrum: frozenset[str] = frozenset()
    hidden_folders: frozenset[str] = ABOVE_CONFIG

    def factories(self) -> set[str]:
        return {
            name
            for name, function in inspect.getmembers(self.module, inspect.isfunction)
            if function.__module__ == self.module.__name__ and not name.startswith("_")
        }

    def case_factories(self) -> dict[str, Callable[..., Message]]:
        return {
            name: function
            for name, function in inspect.getmembers(self.module, inspect.isfunction)
            if function.__module__ == self.module.__name__
            and name.startswith("_")
            and inspect.signature(function).return_annotation == "Message"
        }

    def messages(self) -> list[Message]:
        return [sample() for samples in self.samples.values() for sample in samples]

    def shown_messages(self) -> list[Message]:
        own = [samples for name, samples in self.samples.items() if name not in self.outside_centrum]
        return [sample() for samples in own for sample in samples]


CATALOGS = {
    "przygotowanie-pliku-zbiorczego": Catalog(
        messages,
        "### Komunikat → co zrobić",
        PREPARATION_SAMPLES,
        outside_centrum=frozenset({"invalid_period_token"}),
    ),
    "przebieg-rozliczen": Catalog(
        settlement_messages,
        "### Komunikat w Centrum rozliczeń → co zrobić",
        SETTLEMENT_SAMPLES,
        hidden_folders=ABOVE_PERIOD_FOLDER,
    ),
    "start-centrum-rozliczen": Catalog(start_problems, "### Komunikaty startu Centrum rozliczeń", START_SAMPLES),
    "diagnoza": Catalog(
        diagnosis_messages,
        "### Wyjaśnienie Diagnozy → co zrobić",
        DIAGNOSIS_SAMPLES,
        hidden_folders=ABOVE_PERIOD_FOLDER,
    ),
    "zgloszenie": Catalog(
        report_messages,
        "### Zgłoszenie → co zrobić",
        REPORT_SAMPLES,
        hidden_folders=ABOVE_REPORT_QUEUE,
    ),
    "powiadomienia": Catalog(notification_messages, "### Powiadomienia", NOTIFICATION_SAMPLES),
    "aktualizacja-narzedzia": Catalog(
        update_messages, "### Aktualizacja narzędzia → co zrobić", UPDATE_SAMPLES
    ),
    "uzupelnienie-pliku-zbiorczego": Catalog(
        fill_messages,
        "### Uzupełnienie → co zrobić",
        FILL_SAMPLES,
        hidden_folders=ABOVE_PERIOD_FOLDER,
    ),
    "uporzadkowanie-intermax": Catalog(
        intermax_messages,
        "### Uporządkowanie INTERMAX → co zrobić",
        INTERMAX_ORDERING_ONLY,
        outside_centrum=RESTORING_INTERMAX_COPY,
        hidden_folders=ABOVE_TOOL_FOLDER,
    ),
    "wycena-w-efenix": Catalog(
        efenix_messages,
        "### Wycena w efenix → co zrobić",
        EFENIX_SAMPLES,
        hidden_folders=ABOVE_PERIOD_FOLDER - {"Dane"},
    ),
}

each_catalog = pytest.mark.parametrize("catalog", CATALOGS.values(), ids=CATALOGS.keys())


def _settlement_problem_quotes() -> list[str]:
    lines = INSTRUCTION.read_text(encoding="utf-8").splitlines()
    start = lines.index("### Gdy pojawi się problem", lines.index("## Przebieg rozliczeń"))
    quotes: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        if line.startswith("- "):
            quotes.extend(QUOTED.findall(line))
    return quotes


def _instruction_fragments(section: str) -> list[str]:
    lines = INSTRUCTION.read_text(encoding="utf-8").splitlines()
    start = lines.index(section)
    level = section.split(" ", 1)[0]
    fragments: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#") and len(line.split(" ", 1)[0]) <= len(level):
            break
        if not line.startswith("|") or set(line) <= {"|", "-", " ", ":"}:
            continue
        first_cell = line.strip("|").split("|", 1)[0]
        fragments.extend(QUOTED.findall(first_cell))
    return fragments


@each_catalog
def test_probki_pokrywaja_kazda_fabryke_katalogu(catalog: Catalog) -> None:
    assert set(catalog.samples) == catalog.factories()


@each_catalog
def test_probki_docieraja_do_kazdej_fabryki_przypadku_katalogu(catalog: Catalog) -> None:
    names = {factory.__code__: name for name, factory in catalog.case_factories().items()}
    reached: set[str] = set()

    def record(frame: FrameType, event: str, _arg: object) -> None:
        if event == "call" and frame.f_code in names:
            reached.add(names[frame.f_code])

    sys.setprofile(record)
    try:
        catalog.messages()
    finally:
        sys.setprofile(None)

    assert reached == set(names.values())


@each_catalog
def test_instrukcja_taty_objasnia_kazdy_komunikat_katalogu(catalog: Catalog) -> None:
    fragments = _instruction_fragments(catalog.section)
    unexplained = sorted(
        {message.code for message in catalog.shown_messages() if not any(f in message.what for f in fragments)}
    )

    assert unexplained == []


@each_catalog
def test_kazdy_cytat_instrukcji_wskazuje_dokladnie_jeden_kod(catalog: Catalog) -> None:
    codes_per_fragment = {
        fragment: {message.code for message in catalog.shown_messages() if fragment in message.what}
        for fragment in _instruction_fragments(catalog.section)
    }

    assert {fragment: codes for fragment, codes in codes_per_fragment.items() if len(codes) != 1} == {}


@each_catalog
def test_kazdy_kod_katalogu_ma_dokladnie_jeden_cytat_instrukcji(catalog: Catalog) -> None:
    fragments = _instruction_fragments(catalog.section)
    fragments_per_code: dict[str, set[str]] = {}
    for message in catalog.shown_messages():
        fragments_per_code.setdefault(message.code, set()).update(f for f in fragments if f in message.what)

    assert {code: found for code, found in fragments_per_code.items() if len(found) != 1} == {}


def test_cytaty_sekcji_gdy_pojawi_sie_problem_odpowiadaja_komunikatom_przebiegu_rozliczen() -> None:
    texts = [message.what for message in CATALOGS["przebieg-rozliczen"].messages()]
    quotes = _settlement_problem_quotes()

    assert quotes
    assert [quote for quote in quotes if not any(quote in text for text in texts)] == []


@each_catalog
def test_komunikaty_katalogu_nie_maja_pelnych_sciezek(catalog: Catalog) -> None:
    shown = {
        message.code: part
        for message in catalog.messages()
        for part in (message.what, message.where, message.action)
        if FULL_PATH.search(part) or any(folder in part for folder in catalog.hidden_folders)
    }

    assert shown == {}


@pytest.mark.parametrize(
    ("text", "full_path"),
    [
        pytest.param("plik C:\\Dane\\Rejestr.xlsx", True, id="litera-dysku-z-ukosnikiem-wstecznym"),
        pytest.param("plik C:/Dane/Rejestr.xlsx", True, id="litera-dysku-z-ukosnikiem"),
        pytest.param("folder \\\\nas\\Wspolne", True, id="sciezka-sieciowa-z-ukosnikami-wstecznymi"),
        pytest.param("folder //nas/Wspolne", True, id="sciezka-sieciowa-z-ukosnikami"),
        pytest.param("adres http://127.0.0.1:8765/ na tym komputerze", False, id="adres-po-dwukropku"),
        pytest.param("folder Dane, arkusz ZLECENIA", False, id="nazwa-folderu-bez-sciezki"),
    ],
)
def test_pelna_sciezka_to_litera_dysku_albo_sciezka_sieciowa_a_nie_adres(text: str, full_path: bool) -> None:
    assert bool(FULL_PATH.search(text)) is full_path
