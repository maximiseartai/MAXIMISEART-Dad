"""Ostrzeżenia o Ilościach usług „do uzupełnienia” po Przygotowaniu pliku zbiorczego (#271).

Numery wierszy w ostrzeżeniach to numery wierszy Pliku zbiorczego, bo tata poprawia Plik zbiorczy: Zlecenia
skuteczne leżą w nim od wiersza 18, bez pustych wierszy i zleceń nieskutecznych z Rejestru zleceń.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from rozliczenia.message import Message

from tests.fixtures.centrum import finished_view
from tests.fixtures.centrum_processes import preparing_centrum
from tests.fixtures.preparation import (
    COLLECTIVE_FILE_NAME,
    PERIOD,
    RegisterRow,
    make_preparation_fixture,
    register_order,
    run_preparation,
)

TUESDAY = datetime(2026, 9, 8, 8, 0)
MONDAY = datetime(2026, 9, 14, 9, 0)
REMINDER = ("KOLUMNY_Z_OPISU", f"plik {COLLECTIVE_FILE_NAME}, kolumny Y, AB, AD, AJ, AK, AL i AM")


def _order(number: int, devices: str | None, *, started: datetime | None = None, successful: str = "tak") -> RegisterRow:
    started = started or TUESDAY + timedelta(hours=number)
    return register_order(number, started, successful=successful) | {"URZĄDZENIA": devices}


def _mixed_period() -> list[RegisterRow]:
    """Rejestr, w którym wiersze Pliku zbiorczego (18–23) mają inne numery niż wiersze Rejestru zleceń (2–9)."""

    return [
        _order(1, "nokia zte"),  # Plik zbiorczy 18
        None,
        _order(2, "nokia zte SYN-URZ-2"),  # 19: składnik nieznany Regułom ilości
        _order(3, "SYN-URZ-3", successful="nie"),  # nieskuteczne: nie trafia do Pliku zbiorczego
        _order(4, "prewencja"),  # 20
        _order(5, None),  # 21: puste URZĄDZENIA
        _order(6, "SYN-URZ-6"),  # 22
        _order(7, "Niedostępność usług", started=MONDAY),  # 23
    ]


def _known_devices_period() -> list[RegisterRow]:
    return [_order(1, "nokia zte"), _order(2, "SYN-URZ-2", successful="nie"), _order(3, "fut", started=MONDAY)]


def _coded(warnings: list[Message]) -> list[tuple[str, str]]:
    return [(warning.code, warning.where) for warning in warnings]


def test_ostrzezenia_wskazuja_wiersze_pliku_zbiorczego_bez_regul_i_z_opisu_oraz_przypominaja_kolumny_z_opisu(
    tmp_path: Path,
) -> None:
    fixture = make_preparation_fixture(tmp_path, _mixed_period())

    summary = run_preparation(fixture)

    assert _coded(summary.warnings) == [
        ("NIEZNANE_URZADZENIA", f"plik {COLLECTIVE_FILE_NAME}, wiersze 19, 22"),
        ("WIERSZE_Z_OPISU", f"plik {COLLECTIVE_FILE_NAME}, wiersze 20, 21, 23"),
        REMINDER,
    ]
    assert "SYN-" not in repr(summary.warnings)


def test_okres_tylko_ze_znanymi_urzadzeniami_ma_tylko_ostrzezenie_o_kolumnach_z_opisu(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path, _known_devices_period())

    summary = run_preparation(fixture)

    assert _coded(summary.warnings) == [REMINDER]


def test_podglad_bez_zapisu_ma_te_same_ostrzezenia_co_zapis(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path, _mixed_period())

    preview = run_preparation(fixture, dry_run=True)
    summary = run_preparation(fixture)

    assert len(preview.warnings) == 3
    assert preview.warnings == summary.warnings


def test_w_centrum_podglad_z_ostrzezeniami_ilosci_prowadzi_do_uruchom_a_zapis_wymaga_sprawdzenia(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path, _mixed_period())

    def previewed() -> bool:
        setup, _settlement, _efenix = centrum.client.get("/api/runs/setup").json()["processes"]
        [choice] = [choice for choice in setup["periods"] if choice["token"] == PERIOD]
        return bool(choice["previewed"])

    centrum.start(dry_run=True)
    preview = finished_view(centrum.client)["result"]
    preview_previewed = previewed()
    centrum.start(dry_run=False)
    written = finished_view(centrum.client)["result"]

    assert (preview["result"], preview["next_action"], preview["headline"]) == (
        "OK",
        "run",
        "Podgląd gotowy · nic nie zapisano",
    )
    assert preview_previewed is True
    assert (written["result"], written["next_action"], written["headline"]) == (
        "WYMAGA_SPRAWDZENIA",
        "open_collective_file",
        "Plik zbiorczy przygotowany · wymaga sprawdzenia",
    )
    shown = [(warning["what"], warning["where"]) for warning in written["warnings"]]
    assert [where for _what, where in shown] == [
        f"plik {COLLECTIVE_FILE_NAME}, wiersze 19, 22",
        f"plik {COLLECTIVE_FILE_NAME}, wiersze 20, 21, 23",
        REMINDER[1],
    ]
    assert [(warning["what"], warning["where"]) for warning in preview["warnings"]] == shown
    assert [(record["mode"], record["result"]) for record in centrum.metric_records()] == [
        ("DRY-RUN", "OK"),
        ("RUN", "WYMAGA_SPRAWDZENIA"),
    ]


def test_w_centrum_zapis_okresu_tylko_ze_znanymi_urzadzeniami_wymaga_sprawdzenia_a_podglad_nie(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path, _known_devices_period())

    centrum.start(dry_run=True)
    preview = finished_view(centrum.client)["result"]
    centrum.start(dry_run=False)
    written = finished_view(centrum.client)["result"]

    assert (preview["result"], written["result"]) == ("OK", "WYMAGA_SPRAWDZENIA")
    assert [warning["where"] for warning in written["warnings"]] == [REMINDER[1]]
