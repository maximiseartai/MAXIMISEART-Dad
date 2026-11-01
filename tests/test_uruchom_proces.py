"""Skrypt dla maszyn ``tools/uruchom_proces.py`` jako osobny proces Pythona: kod wyjścia, wynik JSON i pliki."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType
from typing import Any, get_args, get_type_hints

import pytest

from rozliczenia import TOOL_ROOT, settlement_messages
from rozliczenia.centrum import contract, run_view
from rozliczenia.preparation_process import PROCESS as PREPARATION
from rozliczenia.process_run import Stop
from rozliczenia.telemetry import COUNTER_NAMES, MetricsStore

from tests.fixtures.centrum_processes import run_to_end, settling_centrum
from tests.fixtures.preparation import (
    COLLECTIVE_FILE_NAME,
    INTERNAL_SETTLEMENT_NAME,
    PreparationFixture,
    incomplete_period_fixture,
    link_register_order_numbers,
    make_preparation_fixture,
)
from rozliczenia.preparation_register import read_register
from rozliczenia.workbook_files import read_data_rows
from tests.fixtures.settlement import (
    PERIOD,
    SOURCE_NAME,
    link_order_numbers,
    make_fixture,
    make_preview_fixture,
    write_quantity_source,
    write_template,
)
from tests.fixtures.atrapa_efenix import amount_of, atrapa_efenix
from tests.fixtures.efenix import Order as EfenixOrder
from tests.fixtures.efenix import write_collective_file
from tests.fixtures.intermax import Intermax
from tests.fixtures.workbooks import hyperlinks

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "uruchom_proces.py"
WORKER_SETTLEMENTS = f"Rozliczenie pracowników {PERIOD}"
DETACHED_VIEW_NOTICE = "Podgląd postępu przestał się aktualizować; wynik nie zależy od tego."


def _completed(*arguments: str | Path, script: Path = SCRIPT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *map(str, arguments)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=100,
        check=False,
    )


def _run(*arguments: str | Path, script: Path = SCRIPT) -> tuple[int, dict[str, Any]]:
    completed = _completed(*arguments, script=script)
    assert completed.stderr == ""
    assert "Traceback" not in completed.stdout
    return completed.returncode, json.loads(completed.stdout)


def _script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("uruchom_proces", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_skrypt_dla_maszyn_i_karta_centrum_znaja_kazde_zatrzymanie_rdzenia(monkeypatch: pytest.MonkeyPatch) -> None:
    core = set(get_args(get_type_hints(Stop)["kind"]))
    script = set(get_args(_script(monkeypatch).StopResult.model_fields["kind"].annotation))
    card = set(get_args(contract.RunOutcome.model_fields["ending"].annotation)) - {"finished"}

    assert core == script == card == {"stop", "declined", "unexpected", "after_engine"}


def _settlement_arguments(tmp_path: Path, source: Path, config: Path, *extra: str) -> list[str]:
    return [
        "settlement",
        "--source",
        str(source),
        "--config",
        str(config),
        "--worker-template",
        str(tmp_path / "Wzorzec rozliczenia pracownika.xlsx"),
        "--metrics",
        str(tmp_path / "metrics.jsonl"),
        *extra,
    ]


def _settlement(tmp_path: Path, source: Path, config: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    return _run(*_settlement_arguments(tmp_path, source, config, *extra))


def _preparation(fixture: PreparationFixture, *extra: str) -> tuple[int, dict[str, Any]]:
    return _run(*_preparation_arguments(fixture, *extra))


def _preparation_arguments(fixture: PreparationFixture, *extra: str) -> list[str | Path]:
    return [
        "preparation",
        "--register",
        fixture.register_path,
        "--periods-directory",
        fixture.periods_directory,
        "--period",
        PERIOD,
        "--config",
        fixture.config_path,
        "--internal-template",
        fixture.internal_template_path,
        "--collective-template",
        fixture.collective_template_path,
        "--metrics",
        fixture.register_path.parent / "metrics.jsonl",
        *extra,
    ]


def _run_logs() -> set[str]:
    """Logi Uruchomienia w katalogu Logów narzędzia, gdzie leżą u taty."""

    directory = TOOL_ROOT / "logs" / "uruchomienia"
    return {path.name for path in directory.iterdir()} if directory.is_dir() else set()


def test_przebieg_ze_skryptu_dla_maszyn_nie_tworzy_kontroli_ilosci_ani_logow_uruchomienia(tmp_path: Path) -> None:
    logs_before = _run_logs()
    source, _target, config = make_fixture(tmp_path)
    started = datetime(2026, 9, 9, 13, 45)
    write_quantity_source(
        source,
        [{"C": "u ZNACZNIK-UMOWA", "D": "nokia ZNACZNIK-URZADZENIA", "E": "ZNACZNIK-CZYNNOSCI", "G": started, "V": 2}],
    )

    completed = _completed(*_settlement_arguments(tmp_path, source, config))

    assert completed.returncode == 0, completed.stderr
    assert [path for path in tmp_path.rglob("*") if path.name in ("zgloszenia", "kolejka", "uruchomienia")] == []
    assert _run_logs() == logs_before
    printed = completed.stdout + completed.stderr + (tmp_path / "metrics.jsonl").read_text(encoding="utf-8")
    assert [marker for marker in ("ZNACZNIK-UMOWA", "ZNACZNIK-URZADZENIA", "ZNACZNIK-CZYNNOSCI") if marker in printed] == []


def test_przebieg_rozliczen_ok_konczy_kodem_0_z_podsumowaniem_karty_uruchomienia(tmp_path: Path) -> None:
    source, target, config = make_fixture(tmp_path)

    exit_code, result = _settlement(tmp_path, source, config)

    assert (exit_code, result["result"], result["stop"]) == (0, "OK", None)
    assert [(figure["label"], figure["value"]) for figure in result["summary"]["figures"]] == [
        ("Zapisane szablony", 2),
        ("Puste szablony", 1),
    ]
    assert result["summary"]["worker_settlements"] == [
        {"worker": "Adrian Testowy", "file": f"Rozliczenie {PERIOD} - Adrian Testowy.xlsx", "orders": 2, "empty": False},
        {"worker": "Darek Fikcyjny", "file": f"Rozliczenie {PERIOD} - Darek Fikcyjny.xlsx", "orders": 1, "empty": False},
        {"worker": "Kamil Syntetyczny", "file": f"Rozliczenie {PERIOD} - Kamil Syntetyczny.xlsx", "orders": 0, "empty": True},
    ]
    assert sorted(path.name for path in target.iterdir()) == [file["file"] for file in result["summary"]["worker_settlements"]]
    assert sorted(path.name for path in source.parent.iterdir()) == [SOURCE_NAME, WORKER_SETTLEMENTS]
    assert result["warnings"] == []
    progress = result["progress"]
    assert [(phase["phase"], phase["state"]) for phase in progress["phases"]] == [
        ("Sprawdzanie", "completed"),
        ("Odczyt danych", "completed"),
        ("Planowanie", "completed"),
        ("Zapisywanie", "completed"),
    ]
    assert (progress["template_total"], progress["templates_completed"]) == (3, 3)
    [record] = MetricsStore(tmp_path / "metrics.jsonl", COUNTER_NAMES).read()
    assert (record["mode"], record["result"], record["total_duration_ms"]) == ("RUN", "OK", result["total_duration_ms"])
    assert (result["metrics_saved"], result["technical_notes"]) == (True, [])
    assert str(tmp_path) not in json.dumps(result)


def test_adres_hiperlacza_nie_trafia_do_wyniku_komunikatow_ani_metryk(tmp_path: Path) -> None:
    source, target, config = make_fixture(tmp_path)
    sentinel = "SENTINEL-SPRAWA-7"
    links = link_order_numbers(source, f"https://przyklad.invalid/zlecenie?caseId={sentinel}&wiersz=")

    outputs = [_completed(*_settlement_arguments(tmp_path, source, config, *mode)) for mode in (("--dry-run",), ())]

    assert [completed.returncode for completed in outputs] == [0, 0]
    assert hyperlinks(target / f"Rozliczenie {PERIOD} - Darek Fikcyjny.xlsx") == {"F18": links[19]}
    for completed in outputs:
        assert sentinel not in completed.stdout + completed.stderr
    assert sentinel not in (tmp_path / "metrics.jsonl").read_text(encoding="utf-8")
    assert sentinel not in repr(read_data_rows(source))


def test_adres_hiperlacza_z_rejestru_nie_trafia_do_wyniku_przygotowania_ani_metryk(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)
    sentinel = "SENTINEL-SPRAWA-8"
    links = link_register_order_numbers(fixture.register_path, f"https://przyklad.invalid/zlecenie?caseId={sentinel}&wiersz=")

    outputs = [_completed(*_preparation_arguments(fixture, *mode)) for mode in (("--dry-run",), ())]

    # Zapis z ostrzeżeniami ilości wymaga sprawdzenia (kod 2), podgląd z tymi samymi ostrzeżeniami jest OK.
    assert [completed.returncode for completed in outputs] == [0, 2]
    assert hyperlinks(fixture.collective_file_path) == {"F18": links[4], "F19": links[9], "F20": links[13]}
    for completed in outputs:
        assert sentinel not in completed.stdout + completed.stderr
    assert sentinel not in (fixture.register_path.parent / "metrics.jsonl").read_text(encoding="utf-8")
    assert sentinel not in repr(read_register(fixture.register_path))


@pytest.mark.parametrize(("good_views", "phase_states"), [(0, set()), (1, {"pending"})])
def test_awaria_podgladu_postepu_odlacza_go_bez_tekstu_wyjatku_i_bez_zmiany_wyniku(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    good_views: int,
    phase_states: set[str],
) -> None:
    source, target, config = make_fixture(tmp_path)
    secret = "Jan Kowalski /Users/klient/Rejestr.xlsx"
    shown = run_view.ProcessView.progress
    calls = itertools.count()

    def broken_after_good_views(view: Any, *args: Any, **kwargs: Any) -> Any:
        if next(calls) < good_views:
            return shown(view, *args, **kwargs)
        raise RuntimeError(secret)

    monkeypatch.setattr(run_view.ProcessView, "progress", broken_after_good_views)

    exit_code = _script(monkeypatch).main(_settlement_arguments(tmp_path, source, config))
    stdout, stderr = capsys.readouterr()
    result = json.loads(stdout)

    assert secret not in stdout + stderr
    assert stderr == ""
    assert (exit_code, result["result"], result["stop"]) == (0, "OK", None)
    assert result["technical_notes"] == [DETACHED_VIEW_NOTICE]
    assert {phase["state"] for phase in result["progress"]["phases"]} == phase_states
    assert [(figure["label"], figure["value"]) for figure in result["summary"]["figures"]] == [
        ("Zapisane szablony", 2),
        ("Puste szablony", 1),
    ]
    assert len(list(target.iterdir())) == 3
    [record] = MetricsStore(tmp_path / "metrics.jsonl", COUNTER_NAMES).read()
    assert (record["result"], result["metrics_saved"]) == ("OK", True)


def test_plan_ktorego_nie_da_sie_pokazac_to_zatrzymanie_po_silniku_z_tym_samym_wynikiem_co_w_metrykach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source, _target, config = make_preview_fixture(tmp_path)
    secret = "Jan Kowalski /Users/klient/Rejestr.xlsx"

    def broken_view(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(secret)

    monkeypatch.setattr(run_view.ProcessView, "shown", broken_view)

    exit_code = _script(monkeypatch).main(_settlement_arguments(tmp_path, source, config, "--dry-run"))
    stdout, stderr = capsys.readouterr()
    result = json.loads(stdout)

    assert secret not in stdout + stderr
    assert stderr == ""
    assert (exit_code, result["result"], result["summary"], result["warnings"]) == (1, "BLAD_KRYTYCZNY", None, [])
    assert (result["stop"]["kind"], result["stop"]["message"]["code"]) == ("after_engine", "BLAD_PLANU")
    [record] = MetricsStore(tmp_path / "metrics.jsonl", COUNTER_NAMES).read()
    assert (record["mode"], record["result"]) == ("DRY-RUN", "BLAD_KRYTYCZNY")


def test_nieudany_zapis_metryk_jest_ostrzezeniem_bez_zmiany_wyniku(tmp_path: Path) -> None:
    source, target, config = make_fixture(tmp_path)
    not_a_folder = tmp_path / "plik zamiast folderu"
    not_a_folder.write_text("", encoding="utf-8")

    exit_code, result = _settlement(tmp_path, source, config, "--metrics", str(not_a_folder / "metrics.jsonl"))

    assert (exit_code, result["result"], result["stop"]) == (0, "OK", None)
    assert result["metrics_saved"] is False
    assert result["technical_notes"] == ["Ostrzeżenie: Nie zapisano metryk; proces rozliczeń zakończył się niezależnie."]
    assert [(figure["label"], figure["value"]) for figure in result["summary"]["figures"]] == [
        ("Zapisane szablony", 2),
        ("Puste szablony", 1),
    ]
    assert len(list(target.iterdir())) == 3


def test_podglad_z_nieznanym_wykonawca_wymaga_sprawdzenia_kodem_2_z_kodem_ostrzezenia(tmp_path: Path) -> None:
    source, _target, config = make_preview_fixture(tmp_path)

    exit_code, result = _settlement(tmp_path, source, config, "--dry-run")

    assert (exit_code, result["result"], result["stop"]) == (2, "WYMAGA_SPRAWDZENIA", None)
    assert [warning["code"] for warning in result["warnings"]] == ["BRAK_MAPOWANIA"]
    assert set(result["warnings"][0]) == {"code", "what", "where", "action"}
    assert [(figure["label"], figure["value"]) for figure in result["summary"]["figures"]] == [
        ("Wiersze danych", 3),
        ("Planowane szablony", 2),
        ("Puste szablony", 1),
    ]
    assert sorted(path.name for path in source.parent.iterdir()) == [SOURCE_NAME]
    [record] = MetricsStore(tmp_path / "metrics.jsonl", COUNTER_NAMES).read()
    assert (record["mode"], record["result"]) == ("DRY-RUN", "WYMAGA_SPRAWDZENIA")


def test_podsumowanie_i_ostrzezenia_w_kolejnosci_etapow_sa_te_same_w_skrypcie_na_karcie_i_w_metrykach(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    write_quantity_source(
        centrum.collective_file,
        [{"H": "andrzej.nieznany2"}, {}, {"H": None}, {"H": "andrzej.nieznany3"}, {"H": None}],
    )
    view = run_to_end(centrum, dry_run=True)
    card = view["result"]

    exit_code, result = _run(
        "settlement",
        "--source",
        centrum.collective_file,
        "--config",
        centrum.configuration.worker_config,
        "--worker-template",
        centrum.configuration.worker_template,
        "--metrics",
        tmp_path / "metrics-skryptu.jsonl",
        "--dry-run",
    )

    where = f"plik {SOURCE_NAME}, folder {PERIOD}"
    assert [(warning["code"], warning["where"]) for warning in result["warnings"]] == [
        ("BRAK_WYKONAWCY", where),
        ("BRAK_WYKONAWCY", where),
        ("BRAK_MAPOWANIA", where),
        ("BRAK_MAPOWANIA", where),
    ]
    expected = [
        settlement_messages.row_without_worker_warning(centrum.collective_file, 20),
        settlement_messages.row_without_worker_warning(centrum.collective_file, 22),
        settlement_messages.unmapped_worker_warning(centrum.collective_file, "andrzej.nieznany2"),
        settlement_messages.unmapped_worker_warning(centrum.collective_file, "andrzej.nieznany3"),
    ]
    assert result["warnings"] == [
        {"code": message.code, "what": message.what, "where": message.where, "action": message.action} for message in expected
    ]
    assert (exit_code, result["result"]) == (2, card["result"])
    assert result["summary"] == card["summary"]
    assert [{key: value for key, value in warning.items() if key != "code"} for warning in result["warnings"]] == card[
        "warnings"
    ]
    assert ("Problemy", 4) in [(figure["label"], figure["value"]) for figure in view["progress"]["figures"]]
    [script_record] = MetricsStore(tmp_path / "metrics-skryptu.jsonl", COUNTER_NAMES).read()
    [card_record] = centrum.metric_records()
    assert script_record["counters"]["issues"] == card_record["counters"]["issues"] == 4


def test_zatrzymanie_w_sprawdzaniu_konczy_kodem_1_z_kodem_komunikatu_i_bez_plikow(tmp_path: Path) -> None:
    source, _target, config = make_fixture(tmp_path)
    source.unlink()

    exit_code, result = _settlement(tmp_path, source, config)

    assert (exit_code, result["result"], result["summary"], result["warnings"]) == (1, "BLAD_KRYTYCZNY", None, [])
    assert result["stop"]["kind"] == "stop"
    assert result["stop"]["message"]["code"] == "BRAK_PLIKU_ZBIORCZEGO"
    assert set(result["stop"]["message"]) == {"code", "what", "where", "action"}
    first, *rest = result["progress"]["phases"]
    assert (first["phase"], first["state"]) == ("Sprawdzanie", "failed")
    assert {phase["state"] for phase in rest} == {"pending"}
    assert list(source.parent.iterdir()) == []
    [record] = MetricsStore(tmp_path / "metrics.jsonl", COUNTER_NAMES).read()
    assert (record["result"], set(record["counters"].values())) == ("BLAD_KRYTYCZNY", {0})
    assert str(tmp_path) not in json.dumps(result)


def test_decyzja_o_niepelnym_okresie_jest_odrzucana_bez_czekania_i_bez_plikow_okresu(tmp_path: Path) -> None:
    fixture = incomplete_period_fixture(tmp_path)

    exit_code, result = _preparation(fixture)

    assert (exit_code, result["result"], result["summary"]) == (1, "BLAD_KRYTYCZNY", None)
    assert (result["stop"]["kind"], result["stop"]["message"]["code"]) == ("declined", "PRZERWANO_NIEPELNY_OKRES")
    assert not fixture.period_directory.exists()
    [record] = MetricsStore(fixture.register_path.parent / "metrics.jsonl", PREPARATION.counter_names).read()
    assert (record["mode"], record["period"], record["result"]) == ("RUN", PERIOD, "BLAD_KRYTYCZNY")
    assert str(tmp_path) not in json.dumps(result)


def test_podglad_przygotowania_pliku_zbiorczego_pokazuje_plan_bez_plikow_okresu(tmp_path: Path) -> None:
    fixture = make_preparation_fixture(tmp_path)

    exit_code, result = _preparation(fixture, "--dry-run")

    assert (exit_code, result["result"], result["stop"]) == (0, "OK", None)
    assert [warning["code"] for warning in result["warnings"]] == ["NIEZNANE_URZADZENIA", "KOLUMNY_Z_OPISU"]
    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    assert (figures["Zlecenia okresu"], figures["Zlecenia skuteczne"]) == (4, 3)
    assert result["summary"]["files"] == [
        {"name": INTERNAL_SETTLEMENT_NAME, "kind": "internal_settlement"},
        {"name": COLLECTIVE_FILE_NAME, "kind": "collective_file"},
    ]
    assert list(fixture.periods_directory.iterdir()) == []
    assert result["metrics_saved"] is True


def test_uporzadkowanie_intermax_ze_skryptu_dla_maszyn_oddaje_karte_uruchomienia_i_kopie(tmp_path: Path) -> None:
    register = tmp_path / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    Intermax().write(register)
    copies, metrics = tmp_path / "Kopie INTERMAX", tmp_path / "metrics.jsonl"

    exit_code, result = _run("intermax", "--register", register, "--copies", copies, "--metrics", metrics)

    assert (exit_code, result["result"], result["stop"]) == (0, "OK", None)
    assert result["summary"]["figures"] == [
        {"label": "Zlecenia", "value": 6, "unit": "count"},
        {"label": "Wykonawcy", "value": 3, "unit": "count"},
    ]
    assert result["summary"]["counts"] == {
        "title": "Uporządkowany dzień",
        "counts": [{"label": "pon 26.10.2026", "count": 6}],
    }
    assert [phase["state"] for phase in result["progress"]["phases"]] == ["completed"] * 4
    assert len(list(copies.iterdir())) == 1
    assert "intermax" in get_args(contract.ProcessKey)
    assert "jan.nowak" not in json.dumps(result) and "jan.nowak" not in metrics.read_text(encoding="utf-8")


def test_uporzadkowanie_intermax_z_nieusunieta_stara_kopia_konczy_sie_ok_z_ostrzezeniem(tmp_path: Path) -> None:
    register = tmp_path / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    Intermax().write(register)
    copies = tmp_path / "Kopie INTERMAX"
    copies.mkdir()
    for day in range(10, 20):
        (copies / f"INTERMAX przed uporządkowaniem 2026-10-{day:02d} 07-00-00.xlsx").write_bytes(b"kopia")
    (copies / "INTERMAX przed uporządkowaniem 2026-10-09 07-00-00.xlsx").mkdir()

    exit_code, result = _run("intermax", "--register", register, "--copies", copies, "--metrics", tmp_path / "m.jsonl")

    assert (exit_code, result["result"], result["stop"]) == (0, "OK", None)
    assert [warning["code"] for warning in result["warnings"]] == ["STARE_KOPIE_INTERMAX"]


def test_uporzadkowanie_intermax_bez_surowych_zlecen_konczy_kodem_1_z_kodem_komunikatu(tmp_path: Path) -> None:
    register = tmp_path / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    Intermax(raw=()).write(register)

    exit_code, result = _run("intermax", "--register", register, "--copies", tmp_path / "Kopie", "--metrics", tmp_path / "m.jsonl")

    assert (exit_code, result["result"], result["summary"]) == (1, "BLAD_KRYTYCZNY", None)
    assert (result["stop"]["kind"], result["stop"]["message"]["code"]) == ("stop", "BRAK_SUROWYCH_ZLECEN")


def test_wycena_w_efenix_ze_skryptu_dla_maszyn_na_atrapie_oddaje_gotowe_bledy_z_kwotami_i_ostrzezenia_emmetta(
    tmp_path: Path,
) -> None:
    au = float(amount_of({"012": 2}))
    orders = [
        EfenixOrder("#9401", cells={"O": 2}, amount=au),  # wiersz 18: gotowe po dopisaniu
        EfenixOrder("#9402"),  # 19: inny status
        EfenixOrder("#9403", cells={"O": 2}, amount=au + 10),  # 20: kwota inna niż AU
        EfenixOrder("#9404", cells={"O": 2}, amount=au, emmett={"012": 1}),  # 21: sprzeczność z Emmettem
    ]
    source = write_collective_file(tmp_path, orders)
    metrics = tmp_path / "metrics.jsonl"
    efenix = [order.in_efenix(f"90{index}") for index, order in enumerate(orders)]
    with atrapa_efenix([efenix[0], replace(efenix[1], status="Rozliczone"), *efenix[2:]]) as atrapa:
        exit_code, result = _run("efenix", "--source", source, "--efenix-url", atrapa.url, "--metrics", metrics)
        changes = atrapa.status_changes()

    assert (exit_code, result["result"], result["stop"], changes) == (2, "WYMAGA_SPRAWDZENIA", None, 0)
    assert result["summary"]["figures"] == [
        {"label": "Zlecenia w zakresie", "value": 4, "unit": "count"},
        {"label": "Gotowe do przekazania", "value": 1, "unit": "count"},
        {"label": "Błędy zleceń", "value": 2, "unit": "count"},
        {"label": "Ostrzeżenia Emmetta", "value": 1, "unit": "count"},
        {"label": "Pominięte ze zdjęciami", "value": 0, "unit": "count"},
        {"label": "Pominięte usterki", "value": 0, "unit": "count"},
    ]
    assert [(warning["code"], warning["where"].rpartition(", ")[2]) for warning in result["warnings"]] == [
        ("EFENIX_INNY_STATUS", "wiersz 19"),
        ("EFENIX_INNA_KWOTA", "wiersz 20"),
        ("EFENIX_SPRZECZNOSC_Z_EMMETTEM", "wiersz 21"),
    ]
    amounts = f"kwota w efenix to {au:.2f} zł, a Kwota (AU) {au + 10:.2f} zł".replace(".", ",")
    assert amounts in result["warnings"][1]["what"]
    assert "pozycja INDEKS_012 (kolumna O): Emmett 1, plik 2" in result["warnings"][2]["what"]
    assert [phase["state"] for phase in result["progress"]["phases"]] == ["completed"] * 4
    assert "9401" not in json.dumps(result) and "9401" not in metrics.read_text(encoding="utf-8")


def test_bledne_argumenty_koncza_sie_kodem_1_bez_wyniku_json(tmp_path: Path) -> None:
    completed = _completed("settlement", "--metrics", tmp_path / "metrics.jsonl")

    assert (completed.returncode, completed.stdout) == (1, "")
    assert "--source" in completed.stderr
    assert not (tmp_path / "metrics.jsonl").exists()


def test_bez_podanych_plikow_oba_procesy_czytaja_konfiguracje_wykonawcow_i_wzorce_z_folderu_config_narzedzia(
    tmp_path: Path,
) -> None:
    tool = tmp_path / "narzedzie"
    shutil.copytree(SCRIPT.parents[1] / "src", tool / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (tool / "tools").mkdir()
    script = Path(shutil.copy(SCRIPT, tool / "tools"))
    preparation = make_preparation_fixture(tool)  # w config/ Konfiguracja wykonawców i oba Wzorce Przygotowania
    write_template(tool / "config" / "Wzorzec rozliczenia pracownika.xlsx")
    source, _target, _config = make_fixture(tmp_path / "okresy")

    settled = _run("settlement", "--source", source, "--dry-run", script=script)
    prepared = _run(
        "preparation",
        "--register",
        preparation.register_path,
        "--periods-directory",
        preparation.periods_directory,
        "--period",
        PERIOD,
        "--dry-run",
        script=script,
    )

    assert (settled[0], settled[1]["stop"]) == (0, None)
    assert settled[1]["summary"]["worker_settlements"] == [
        {"worker": "Adrian Testowy", "file": f"Rozliczenie {PERIOD} - Adrian Testowy.xlsx", "orders": 2, "empty": False},
        {"worker": "Darek Fikcyjny", "file": f"Rozliczenie {PERIOD} - Darek Fikcyjny.xlsx", "orders": 1, "empty": False},
        {"worker": "Kamil Syntetyczny", "file": f"Rozliczenie {PERIOD} - Kamil Syntetyczny.xlsx", "orders": 0, "empty": True},
    ]
    assert (prepared[0], prepared[1]["stop"]) == (0, None)
