"""Skoroszyt, którego nie da się użyć: tłumaczenie powodu (``Problem``) na Komunikat na każdym wejściu.

Komunikat każdej roli pliku przy każdym powodzie pilnują próbki katalogów (``tests/fixtures/message_samples.py``)
i testy procesów. Tu jest jeden test tłumaczenia na wejście, na drodze, której nie sprawdza nic innego.
"""

from __future__ import annotations

from collections.abc import Callable
import errno
from pathlib import Path

from openpyxl import load_workbook
import pytest

from rozliczenia.domain import PhaseStarted, ProgressEvent, ProgressPhase, WorkerStarted
from rozliczenia.engine import SettlementInputs, run_settlements
from rozliczenia.message import StopError
from rozliczenia.run_context import RunContext

from tests.fixtures.centrum import CentrumClient, ToolDirectory, centrum_app
from tests.fixtures.centrum_processes import write_configuration
from atrapy.preparation import make_preparation_fixture
from tests.fixtures.operacje import run_preparation
from atrapy.settlement import make_fixture
from atrapy.workbooks import active_worksheet


def test_przygotowanie_tlumaczy_wzorzec_otwarty_w_excelu_dopiero_w_zapisywaniu(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    lock_file = fixture.collective_template_path.with_name(f"~${fixture.collective_template_path.name}")

    def open_before_saving(event: ProgressEvent) -> None:
        if isinstance(event, PhaseStarted) and event.phase is ProgressPhase.SAVING:
            lock_file.write_bytes(b"")

    with pytest.raises(StopError) as raised:
        run_preparation(fixture, observer=open_before_saving)

    assert raised.value.message.code == "WZORZEC_OTWARTY"
    assert list(fixture.periods_directory.iterdir()) == []


def test_przebieg_bez_pliku_zbiorczego_zatrzymuje_sprawdzanie_brakiem_pliku_zbiorczego(tmp_path: Path) -> None:
    source_path, _, config_path = make_fixture(tmp_path)
    source_path.unlink()

    with pytest.raises(StopError) as raised:
        run_settlements(
            SettlementInputs(source_path, config_path, tmp_path / "Wzorzec rozliczenia pracownika.xlsx"),
            RunContext(),
        )

    assert raised.value.message.code == "BRAK_PLIKU_ZBIORCZEGO"


def test_przebieg_bez_wzorca_rozliczenia_pracownika_w_zapisywaniu_nie_tworzy_skoroszytow_z_wzorca(
    tmp_path: Path,
) -> None:
    source_path, target_directory, config_path = make_fixture(tmp_path)
    worker_template_path = tmp_path / "Wzorzec rozliczenia pracownika.xlsx"

    def remove_before_first_file(event: ProgressEvent) -> None:
        if isinstance(event, WorkerStarted) and event.template_index == 1:
            worker_template_path.unlink()

    with pytest.raises(StopError) as raised:
        run_settlements(
            SettlementInputs(source_path, config_path, worker_template_path),
            RunContext(observer=remove_before_first_file),
        )

    assert (raised.value.message.code, raised.value.message.where) == (
        "BLAD_KOPII_WZORCA",
        f"plik Wzorzec rozliczenia pracownika.xlsx, folder {tmp_path.name}",
    )
    assert not target_directory.exists()


INTERNAL = "Wzorzec rozliczenia wewnętrznego.xlsx"
COLLECTIVE = "Wzorzec pliku zbiorczego.xlsx"
WORKER = "Wzorzec rozliczenia pracownika.xlsx"


def inaccessible(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    read_bytes = Path.read_bytes

    def blocked(read: Path) -> bytes:
        if read == path:
            raise PermissionError(errno.EACCES, "Plik jest używany przez inny proces")
        return read_bytes(read)

    monkeypatch.setattr(Path, "read_bytes", blocked)


def with_data(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workbook = load_workbook(path)
    try:
        active_worksheet(workbook)["A18"] = "dane"
        workbook.save(path)
    finally:
        workbook.close()


@pytest.mark.parametrize(
    ("file_name", "damage", "what"),
    [
        pytest.param(INTERNAL, inaccessible, "Nie można teraz odczytać wzorca.", id="niedostepny-wzorzec-wewnetrzny"),
        pytest.param(
            WORKER,
            with_data,
            "Nie można użyć Wzorca rozliczenia pracownika. Wzorzec rozliczenia pracownika zawiera dane",
            id="wzorzec-pracownika-z-danymi",
        ),
    ],
)
def test_konfiguracja_pokazuje_niedostepny_wzorzec_i_wzorzec_z_danymi_jako_nieczytelne(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_name: str,
    damage: Callable[[Path, pytest.MonkeyPatch], None],
    what: str,
) -> None:
    tool = ToolDirectory(tmp_path)
    write_configuration(tool)
    damage(tool.config / file_name, monkeypatch)

    response = CentrumClient(centrum_app(tool)).get("/api/configuration")

    template = {template["file_name"]: template for template in response.json()["templates"]}[file_name]
    assert (template["state"], template["problem"]) == ("problem", "unreadable")
    assert template["message"]["what"].startswith(what)
