"""Katalog procesów Centrum rozliczeń (#717): każdy wpis katalogu działa w każdym miejscu Centrum tak samo.

Test zgodności przechodzi po wszystkich wpisach katalogu i patrzy przez interfejs HTTP Centrum: karta przed startem
i odmowa startu bez Ustawień taty, karta Uruchomienia na żywo i z Logów, Logi Uruchomienia, Historia i statystyki
Metryk oraz kolejność sprawdzeń Diagnozy. Dokładne teksty i listy sprawdzeń każdego procesu przypinają jego testy HTTP.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, get_args

from fastapi.testclient import TestClient
import pytest

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.catalog import CATALOG
from rozliczenia.centrum.efenix_chrome import atrapa_opening
from rozliczenia.centrum.process_kind import HostParts, PathNeed, PeriodProcessKind, ProcessKind, Start
from rozliczenia.centrum.comment_versions import summary_markdown
from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.efenix_pricing import PricingMode
from rozliczenia.run_context import RunContext
from rozliczenia.tool_files import TOOL_ROOT
from tests.fixtures.centrum import centrum, finished_view
from tests.fixtures.centrum_intermax import ordering_centrum
from tests.fixtures.centrum_processes import preparing_centrum, run_to_end, settling_centrum
from atrapy.preparation import PERIOD


def test_katalog_ma_jeden_wpis_kazdego_procesu_centrum() -> None:
    keys = [kind.key for kind in CATALOG.kinds]
    period_keys = [kind.key for kind in CATALOG.kinds if isinstance(kind, PeriodProcessKind)]

    assert sorted(keys) == sorted(get_args(common_contract.ProcessKey))
    assert sorted(period_keys) == sorted(get_args(common_contract.PeriodProcessKey))


def test_tryb_z_karty_to_tryb_silnika_wyceny_w_efenix_pod_ta_sama_nazwa() -> None:
    """Tryb Wyceny, który tata wybiera przyciskiem (``runs_contract.Pricing``), silnik zna pod tą samą nazwą (ADR 0027): inny
    tryb na karcie wywróciłby start Wyceny w trakcie budowy wejścia."""

    assert {mode.value for mode in PricingMode} == set(get_args(runs_contract.Pricing))


_SETTLEMENT_FILES: Final[dict[PathNeed, Path]] = {
    "collective_file": Path("plik-zbiorczy.xlsx"),
    "worker_config": Path("konfiguracja.xlsx"),
}
_ATRAPA: Final = HostParts(efenix=atrapa_opening("http://127.0.0.1:9/index.php"))


@pytest.mark.parametrize(
    ("key", "start", "parts", "error"),
    [
        ("settlement", Start(_SETTLEMENT_FILES, period=None, dry_run=False), HostParts(), "potrzebuje plików"),
        (
            "preparation",
            Start(
                {
                    "register": Path("rejestr.xlsx"),
                    "periods_directory": Path("okresy"),
                    "worker_config": Path("konfiguracja.xlsx"),
                    "internal_template": Path("wewnetrzny.xlsx"),
                    "collective_template": Path("zbiorczy.xlsx"),
                },
                period=None,
                dry_run=True,
            ),
            HostParts(),
            "potrzebuje okresu",
        ),
        ("efenix", Start({"collective_file": Path("plik-zbiorczy.xlsx")}, None, False), HostParts(), "potrzebuje okna efenix"),
        ("efenix", Start({"collective_file": Path("plik-zbiorczy.xlsx")}, None, True), _ATRAPA, "nie ma Podglądu bez zapisu"),
        (
            "settlement",
            Start({**_SETTLEMENT_FILES, "worker_template": Path("wzorzec.xlsx")}, None, False, pricing="z Przekazaniem"),
            HostParts(),
            "nie ma trybu z Przekazaniem",
        ),
    ],
    ids=["bez-pliku", "bez-okresu", "bez-okna-efenix", "podglad-bez-podgladu", "tryb-spoza-procesu"],
)
def test_start_bez_potrzeby_procesu_to_blad_gospodarza_a_nie_uruchomienie(
    key: common_contract.ProcessKey, start: Start, parts: HostParts, error: str
) -> None:
    """Odmowy dla taty daje karta startu; start, któremu brakuje potrzeby wpisu procesu, to błąd gospodarza (Centrum,
    Skryptu dla maszyn albo odtworzenia), który katalog zgłasza, zanim zbuduje wejście procesu."""

    with pytest.raises(ValueError, match=error):
        CATALOG.prepared(key, start, parts, RunContext())


@pytest.mark.parametrize(("chosen", "expected"), [(None, "bez Przekazania"), ("z Przekazaniem", "z Przekazaniem")])
def test_wycena_bez_wybranego_trybu_biegnie_bez_przekazania_jak_przed_trybami(
    chosen: runs_contract.Pricing | None, expected: runs_contract.Pricing
) -> None:
    """Skrypt dla maszyn bez ``--z-przekazaniem`` i Logi sprzed trybów nie wybierają trybu, a Wycena biegnie wtedy bez
    Przekazania (ADR 0027): ten sam tryb w wejściu silnika i w Uruchomieniu na karcie."""

    start = Start({"collective_file": Path("plik-zbiorczy.xlsx")}, period=None, dry_run=False, pricing=chosen)

    prepared = CATALOG.prepared("efenix", start, _ATRAPA, RunContext())

    assert (prepared.inputs.mode.value, prepared.info("u").pricing) == (expected, expected)


def test_kazdy_proces_ma_wlasna_historie_metryk_w_katalogu_narzedzia() -> None:
    """Nazwy plików metryk są te same na dysku taty od pierwszego Wydania: Historia i Metryki czytają je po zmianie."""

    assert CATALOG.metrics_paths == {
        "preparation": TOOL_ROOT / ".przygotowanie-pliku-zbiorczego-metrics.jsonl",
        "settlement": TOOL_ROOT / ".rozliczenia-metrics.jsonl",
        "efenix": TOOL_ROOT / ".wycena-efenix-metrics.jsonl",
        "intermax": TOOL_ROOT / ".uporzadkowanie-intermax-metrics.jsonl",
    }


def _period_setup(key: str) -> Callable[[TestClient], tuple[str | None, Any]]:
    def setup_and_start(client: TestClient) -> tuple[str | None, Any]:
        setup = next(process for process in client.get("/api/runs/setup").json()["processes"] if process["process"] == key)
        return setup["blocker"], client.post("/api/runs", json={"process": key, "period": PERIOD, "mode": "DRY-RUN"})

    return setup_and_start


def _intermax_setup(client: TestClient) -> tuple[str | None, Any]:
    return client.get("/api/intermax").json()["blocker"], client.post("/api/intermax/run")


# Karta przed startem i start każdego procesu tak, jak je woła przeglądarka; nowy wpis katalogu potrzebuje tu swojej.
_SETUP_AND_START: dict[common_contract.ProcessKey, Callable[[TestClient], tuple[str | None, Any]]] = {
    "preparation": _period_setup("preparation"),
    "settlement": _period_setup("settlement"),
    "efenix": _period_setup("efenix"),
    "intermax": _intermax_setup,
}


@pytest.mark.parametrize("declaration", CATALOG.kinds, ids=lambda declaration: declaration.key)
def test_bez_ustawien_taty_karta_i_odmowa_startu_mowia_to_samo_co_brakuje(
    tmp_path: Path, declaration: ProcessKind[Any, Any]
) -> None:
    client = centrum(tmp_path).client

    blocker, refused = _SETUP_AND_START[declaration.key](client)

    assert refused.status_code == 409
    assert blocker is not None and blocker.startswith("Najpierw wskaż ")
    assert refused.json()["message"] == blocker


def _stopped_preparation(tmp_path: Path) -> tuple[TestClient, dict[str, Any]]:
    preparing = preparing_centrum(tmp_path)
    preparing.engines.fail_summary = True
    return preparing.client, run_to_end(preparing, dry_run=True)


def _stopped_settlement(tmp_path: Path) -> tuple[TestClient, dict[str, Any]]:
    settling = settling_centrum(tmp_path)
    settling.engines.fail_summary = True
    return settling.client, run_to_end(settling, dry_run=True)


def _stopped_efenix(tmp_path: Path) -> tuple[TestClient, dict[str, Any]]:
    settling = settling_centrum(tmp_path)
    settling.engines.fail_engine = True
    assert settling.client.post("/api/runs", json={"process": "efenix", "period": PERIOD, "mode": "RUN"}).status_code == 200
    return settling.client, finished_view(settling.client)


def _stopped_intermax(tmp_path: Path) -> tuple[TestClient, dict[str, Any]]:
    ordering = ordering_centrum(tmp_path)
    ordering.engines.fail_summary = True
    return ordering.client, ordering.run_to_end()


# Zatrzymanie „do Maksa” bez zmiany plików taty: silnik kończy pracę, a jego podsumowania nie da się pokazać.
_STOPPED: dict[common_contract.ProcessKey, Callable[[Path], tuple[TestClient, dict[str, Any]]]] = {
    "preparation": _stopped_preparation,
    "settlement": _stopped_settlement,
    "efenix": _stopped_efenix,
    "intermax": _stopped_intermax,
}


@pytest.mark.parametrize("declaration", CATALOG.kinds, ids=lambda declaration: declaration.key)
def test_uruchomienie_procesu_ma_te_same_fakty_wpisu_na_karcie_w_logach_historii_i_metrykach(
    tmp_path: Path, declaration: ProcessKind[Any, Any]
) -> None:
    client, view = _STOPPED[declaration.key](tmp_path)
    run = view["run"]

    card = client.get(f"/api/runs/{run['id']}/card").json()
    (log_file,) = (tmp_path / "logs" / "uruchomienia").glob(f"*-{run['id']}.json")
    metrics = client.get("/api/metrics").json()

    assert (run["process"], run["title"]) == (declaration.key, declaration.title)
    assert (run["confirms_readiness"], run["register_name"]) == (
        declaration.view.confirms_readiness,
        declaration.view.register_name,
    )
    assert card["run"] == run
    assert summary_markdown(RunLog.model_validate_json(log_file.read_text(encoding="utf-8"))).startswith(
        f"**Logi Uruchomienia**: {declaration.title}, "
    )
    assert [row["process_label"] for row in metrics["runs"] if row["run_id"] == run["id"]] == [declaration.title]
    assert [row["mode"] for row in metrics["statistics"] if row["process"] == declaration.key] == list(
        declaration.view.modes
    )


@pytest.mark.parametrize("declaration", CATALOG.kinds, ids=lambda declaration: declaration.key)
def test_diagnoza_kazdego_procesu_idzie_w_kolejnosci_wyjasniania(
    tmp_path: Path, declaration: ProcessKind[Any, Any]
) -> None:
    """Ustawienia taty pierwsze, OneDrive przed każdym sprawdzeniem, które otwiera pliki, a na końcu Aktualność
    narzędzia, Token do Zgłoszeń i dziennik; Folder okresu tylko w procesie z okresem."""

    client, view = _STOPPED[declaration.key](tmp_path)

    diagnosis = client.post(f"/api/runs/{view['run']['id']}/diagnosis").json()
    labels = [check["label"] for check in diagnosis["checks"]]

    assert labels[:2] == ["Ustawienia taty", "Pliki w OneDrive"]
    assert labels[-3:] == ["Aktualność narzędzia", "Token do Zgłoszeń", "Dziennik Centrum rozliczeń"]
    assert ("Folder okresu" in labels) is declaration.reads_period_folder
    assert ("Pliki okresu w Excelu" in labels) is declaration.reads_period_folder
    assert any(label.startswith("Wzorzec ") for label in labels) is bool(declaration.templates)
