"""Kolejność Sprawdzania: przy usterkach w kilku plikach naraz tata widzi Komunikat tej, którą proces sprawdza pierwszą.

Tabele usterek każdego procesu stoją w kolejności, w jakiej proces je sprawdza, aż do Odczytu danych.
Para usterek w dwóch różnych wejściach zatrzymuje proces tym samym Komunikatem, co wcześniejsza z nich sama.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Generic, TypeVar

import pytest

from rozliczenia.period_folder import worker_settlements_name_with
from rozliczenia import tool_files
from rozliczenia.engine import SettlementInputs, run_settlements
from rozliczenia.message import Message, StopError
from rozliczenia.run_context import RunContext

from atrapy.preparation import (
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    PreparationFixture,
    make_preparation_fixture,
    month_periods_folder,
)
from tests.fixtures.operacje import run_preparation
from atrapy.settlement import NOT_A_PERIOD, make_fixture

NOT_A_WORKBOOK = b"to nie jest skoroszyt"
INVALID_YAML = "workers: ["


@dataclass
class Preparation:
    fixture: PreparationFixture
    period: str = PERIOD

    @classmethod
    def create(cls, root: Path) -> Preparation:
        root.mkdir(parents=True)
        return cls(make_preparation_fixture(root))

    def stop(self) -> Message:
        with pytest.raises(StopError) as raised:
            run_preparation(self.fixture, self.period)
        return raised.value.message


@dataclass
class Settlement:
    source: Path
    config: Path
    worker_template: Path

    @classmethod
    def create(cls, root: Path) -> Settlement:
        source, _target, config = make_fixture(root)
        return cls(source, config, root / tool_files.WORKER_TEMPLATE.name)

    def stop(self) -> Message:
        with pytest.raises(StopError) as raised:
            run_settlements(SettlementInputs(self.source, self.config, self.worker_template), RunContext())
        return raised.value.message


World = TypeVar("World", Preparation, Settlement)


@dataclass(frozen=True)
class Fault(Generic[World]):
    name: str
    damaged_input: str
    apply: Callable[[World], object]
    code: str


def _lock(path: Path) -> None:
    path.with_name(f"~${path.name}").write_bytes(b"")


def _invalid_period(world: Preparation) -> None:
    world.period = NOT_A_PERIOD


def _periods_directory_missing(world: Preparation) -> None:
    """Folder okresów z Ustawień zniknął z folderu ``Rozliczenia 2026``, który ma foldery ``INEA`` miesięcy.

    Odszukanie Folderu okresu policzyłoby układ od folderu roku, więc tylko Sprawdzanie folderu okresów
    przed odszukaniem daje tu Komunikat o folderze okresów.
    """

    periods_directory = world.fixture.periods_directory
    month_periods_folder(periods_directory, "09_Wrzesień_2026")
    missing = periods_directory / "Rozliczenia 2026" / "08_Sierpień_2026" / "INEA"
    world.fixture = replace(world.fixture, periods_directory=missing)


def _period_folder_only_in_other_layout(world: Preparation) -> None:
    month_periods_folder(world.fixture.periods_directory, "09_Wrzesień_2026")


def _period_file_exists(world: Preparation) -> None:
    period_directory = world.fixture.period_directory
    period_directory.mkdir()
    (period_directory / INTERNAL_SETTLEMENT_NAME).write_bytes(b"")


def _period_folder_misnamed(world: Settlement) -> None:
    folder = world.source.parent.rename(world.source.parent.with_name(f"{PERIOD} kopia"))
    world.source = folder / world.source.name


def _worker_settlements_exist(world: Settlement) -> None:
    (world.source.parent / worker_settlements_name_with(PERIOD)).mkdir()


PREPARATION: Sequence[Fault[Preparation]] = (
    Fault("token-okresu", "token okresu", _invalid_period, "ZLY_TOKEN_OKRESU"),
    Fault("brak-rejestru", "rejestr", lambda world: world.fixture.register_path.unlink(), "BRAK_REJESTRU"),
    Fault(
        "brak-wzorca-wewnetrznego",
        "wzorzec wewnętrzny",
        lambda world: world.fixture.internal_template_path.unlink(),
        "BRAK_WZORCA",
    ),
    Fault(
        "wzorzec-zbiorczy-otwarty",
        "wzorzec zbiorczy",
        lambda world: _lock(world.fixture.collective_template_path),
        "WZORZEC_OTWARTY",
    ),
    Fault("brak-folderu-okresow", "folder okresów", _periods_directory_missing, "BRAK_FOLDERU_OKRESOW"),
    Fault("brak-folderu-okresu", "folder okresów", _period_folder_only_in_other_layout, "BRAK_FOLDERU_OKRESU"),
    Fault("plik-okresu-istnieje", "folder okresów", _period_file_exists, "PLIK_OKRESU_ISTNIEJE"),
    Fault(
        "zla-konfiguracja-wykonawcow",
        "konfiguracja wykonawców",
        lambda world: world.fixture.config_path.write_text(INVALID_YAML, encoding="utf-8"),
        "ZLA_KONFIGURACJA_WYKONAWCOW",
    ),
    Fault(
        "uszkodzony-rejestr",
        "rejestr",
        lambda world: world.fixture.register_path.write_bytes(NOT_A_WORKBOOK),
        "USZKODZONY_REJESTR",
    ),
)

SETTLEMENT: Sequence[Fault[Settlement]] = (
    Fault("brak-pliku-zbiorczego", "plik zbiorczy", lambda world: world.source.unlink(), "BRAK_PLIKU_ZBIORCZEGO"),
    Fault("zly-folder-okresu", "folder okresu", _period_folder_misnamed, "ZLY_PLIK_ZBIORCZY"),
    Fault(
        "folder-rozliczen-istnieje",
        "folder rozliczeń pracowników",
        _worker_settlements_exist,
        "FOLDER_ROZLICZEN_ISTNIEJE",
    ),
    Fault(
        "zla-konfiguracja-wykonawcow",
        "konfiguracja wykonawców",
        lambda world: world.config.write_text(INVALID_YAML, encoding="utf-8"),
        "ZLA_KONFIGURACJA_WYKONAWCOW",
    ),
    Fault(
        "brak-wzorca-pracownika",
        "wzorzec pracownika",
        lambda world: world.worker_template.unlink(),
        "ZLY_WZORZEC_PRACOWNIKA",
    ),
    Fault(
        "uszkodzony-plik-zbiorczy",
        "plik zbiorczy",
        lambda world: world.source.write_bytes(NOT_A_WORKBOOK),
        "ZLY_PLIK_ZBIORCZY",
    ),
)


def _first_stop(create: Callable[[Path], World], root: Path, faults: Sequence[Fault[World]]) -> Message:
    """Komunikat Zatrzymania świata taty w ``root / "tata"``, w którym ``faults`` uszkodzono w kolejności tabeli.

    Ten sam folder ``tata`` w każdym świecie daje Komunikaty, które nazywają te same pliki i foldery.
    """

    world = create(root / "tata")
    for fault in faults:
        fault.apply(world)
    return world.stop()


def _code_and_what(message: Message) -> tuple[str, str]:
    """Bez „Gdzie”, które nazywa folder pliku, a ten może przenieść późniejsza usterka (``zly-folder-okresu``)."""

    return message.code, message.what


def _singles(faults: Sequence[Fault[World]]) -> list[object]:
    return [pytest.param(fault, id=fault.name) for fault in faults]


def _pairs(faults: Sequence[Fault[World]]) -> list[object]:
    return [
        pytest.param(earlier, later, id=f"{earlier.name}+{later.name}")
        for earlier, later in combinations(faults, 2)
        if earlier.damaged_input != later.damaged_input
    ]


@pytest.mark.parametrize("fault", _singles(PREPARATION))
def test_przygotowanie_zatrzymuje_sie_na_kazdej_usterce_jej_komunikatem(
    tmp_path: Path, fault: Fault[Preparation]
) -> None:
    assert _first_stop(Preparation.create, tmp_path, [fault]).code == fault.code


@pytest.mark.parametrize(("earlier", "later"), _pairs(PREPARATION))
def test_przygotowanie_przy_dwoch_usterkach_zatrzymuje_sie_na_wczesniej_sprawdzanej(
    tmp_path: Path, earlier: Fault[Preparation], later: Fault[Preparation]
) -> None:
    both = _first_stop(Preparation.create, tmp_path / "obie", [earlier, later])

    assert _code_and_what(both) == _code_and_what(_first_stop(Preparation.create, tmp_path / "wczesniejsza", [earlier]))


@pytest.mark.parametrize("fault", _singles(SETTLEMENT))
def test_przebieg_zatrzymuje_sie_na_kazdej_usterce_jej_komunikatem(tmp_path: Path, fault: Fault[Settlement]) -> None:
    assert _first_stop(Settlement.create, tmp_path, [fault]).code == fault.code


@pytest.mark.parametrize(("earlier", "later"), _pairs(SETTLEMENT))
def test_przebieg_przy_dwoch_usterkach_zatrzymuje_sie_na_wczesniej_sprawdzanej(
    tmp_path: Path, earlier: Fault[Settlement], later: Fault[Settlement]
) -> None:
    both = _first_stop(Settlement.create, tmp_path / "obie", [earlier, later])

    assert _code_and_what(both) == _code_and_what(_first_stop(Settlement.create, tmp_path / "wczesniejsza", [earlier]))
