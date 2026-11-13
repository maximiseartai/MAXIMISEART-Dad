"""Pomiar u taty przez HTTP API Centrum: czas serwera w ``Server-Timing`` i pomiary widoków w dzienniku Centrum."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from rozliczenia.centrum.log import CentrumLog
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.period_folder import PeriodFolder
from tests.fixtures.centrum import Centrum, centrum, view_timing

SERVER_TIMING = re.compile(r"centrum;dur=\d+(\.\d+)?")


def test_kazda_odpowiedz_api_podaje_sam_czas_obslugi_w_server_timing(tmp_path: Path) -> None:
    client = centrum(tmp_path).client

    responses = [
        client.get("/api/health"),
        client.get("/api/settings"),
        client.get("/api/periods"),
        client.put("/api/settings/theme", json={"theme": "light"}),
        client.put("/api/settings/theme", json={"theme": "light"}, headers={"Origin": "http://zly.example"}),
        client.get("/api/health", headers={"Host": "zly.example:47811"}),
        client.post("/api/periods/22_28_09_2026/open", json={"target": "period_folder"}),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 403, 403, 409]
    timings = [response.headers.get("server-timing", "") for response in responses]
    assert [timing for timing in timings if not SERVER_TIMING.fullmatch(timing)] == []


def log_entries(app: Centrum) -> list[str]:
    """Wpisy dziennika Centrum bez znacznika czasu."""

    if not app.log_path.exists():
        return []
    return [line.split(" ", 1)[1] for line in app.log_path.read_text(encoding="utf-8").splitlines()]


def test_pomiary_widokow_z_przegladarki_trafiaja_do_dziennika_centrum(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    navigation = view_timing(
        kind="navigation",
        page="okresy",
        ready_ms=95,
        fcp_ms=None,
        skeleton_ms=0,
        requests=[{"operation": "getPeriodBoard", "browser_ms": 1840, "server_ms": 1795}],
    )

    responses = [app.client.post("/api/view-timings", json=timing) for timing in (view_timing(), navigation)]

    assert [response.status_code for response in responses] == [204, 204]
    assert log_entries(app) == [
        "pomiar widok=zimny-start strona=metryki gotowe_ms=415 fcp_ms=210 szkielet_ms=120"
        " zapytania=getSettings:12/3,getMetrics:48/-",
        "pomiar widok=przejscie-w-menu strona=okresy gotowe_ms=95 szkielet_ms=0 zapytania=getPeriodBoard:1840/1795",
    ]


def test_okno_ustawien_mierzy_sie_jak_widok_a_widoku_konfiguracja_juz_nie_ma(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    settings = view_timing(
        kind="navigation",
        page="ustawienia",
        ready_ms=310,
        fcp_ms=None,
        skeleton_ms=150,
        requests=[{"operation": "getConfiguration", "browser_ms": 290, "server_ms": 270}],
    )

    responses = [app.client.post("/api/view-timings", json=timing) for timing in (settings, view_timing(page="konfiguracja"))]

    assert [response.status_code for response in responses] == [204, 422]
    assert log_entries(app) == [
        "pomiar widok=przejscie-w-menu strona=ustawienia gotowe_ms=310 szkielet_ms=150 zapytania=getConfiguration:290/270",
    ]


def test_dziennik_przyjmuje_ograniczona_liczbe_pomiarow_na_jedno_uruchomienie_centrum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit = 3
    monkeypatch.setattr("rozliczenia.centrum.log.MAX_VIEW_TIMINGS", limit)
    app = centrum(tmp_path)

    responses = [app.client.post("/api/view-timings", json=view_timing()) for _ in range(limit + 1)]
    after_restart = centrum(tmp_path).client.post("/api/view-timings", json=view_timing(page="okresy"))

    assert {response.status_code for response in responses} == {204}
    assert after_restart.status_code == 204
    entries = [entry for entry in log_entries(app) if entry.startswith("pomiar ")]
    assert len(entries) == limit + 1
    assert entries[-1].startswith("pomiar widok=zimny-start strona=okresy ")


def test_dziennik_przyjmuje_najwyzej_200_pomiarow_na_jedno_uruchomienie_centrum() -> None:
    lines: list[str] = []

    def measure(log: CentrumLog, page: str) -> None:
        log.view_timed(view="zimny-start", page=page, ready_ms=415, fcp_ms=210, skeleton_ms=120, requests=())

    first_run = CentrumLog(Path("nieuzywany.log"), append=lines.append)
    for _ in range(201):
        measure(first_run, "metryki")
    measure(CentrumLog(Path("nieuzywany.log"), append=lines.append), "okresy")

    entries = [line.split(" ", 1)[1] for line in lines]
    assert len(entries) == 201
    assert entries[-1].startswith("pomiar widok=zimny-start strona=okresy ")


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"page": "historia"}, id="nieznana strona"),
        pytest.param({"kind": "reload"}, id="nieznany rodzaj widoku"),
        pytest.param(
            {"requests": [{"operation": "getSecrets", "browser_ms": 5, "server_ms": 1}]}, id="nieznana operacja"
        ),
        pytest.param(
            {"requests": [{"operation": "getSettings", "browser_ms": 5, "server_ms": 1}] * 21},
            id="za duzo zapytan",
        ),
        pytest.param({"ready_ms": -1}, id="ujemny czas"),
        pytest.param({"ready_ms": 600_001}, id="czas ponad 10 minut"),
        pytest.param({"skeleton_ms": 12.5}, id="ulamek milisekundy"),
        pytest.param(
            {"requests": [{"operation": "getSettings", "browser_ms": 5, "server_ms": 10**9}]},
            id="czas serwera poza zakresem",
        ),
    ],
)
def test_pomiar_z_nieznana_nazwa_albo_wartoscia_poza_zakresem_jest_odrzucony(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    app = centrum(tmp_path)

    response = app.client.post("/api/view-timings", json=view_timing(**changes))

    assert response.status_code == 422
    assert log_entries(app) == []


def test_token_okresu_ani_sciezka_przyslane_przez_przegladarke_nie_trafiaja_do_dziennika(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    token = "22_28_09_2026"
    path = str(PeriodFolder(tmp_path / "INEA", parse_period_token(token)).collective_file)
    request = {"operation": "getPeriodBoard", "browser_ms": 5, "server_ms": 1}

    responses = [
        app.client.post("/api/view-timings", json=timing)
        for timing in (
            view_timing(page=token),
            view_timing(requests=[request | {"operation": f"/api/periods/{token}/open"}]),
            view_timing(requests=[request | {"url": f"/api/periods/{token}/open"}]),
            view_timing(path=path),
        )
    ]

    assert [response.status_code for response in responses] == [422] * 4
    assert log_entries(app) == []


def test_nieudany_zapis_dziennika_nie_zmienia_odpowiedzi_innych_zapytan(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.log_path.parent.write_text("dziennik nie da się założyć: w miejscu folderu jest plik", encoding="utf-8")

    timing = app.client.post("/api/view-timings", json=view_timing())
    settings = app.client.get("/api/settings")
    theme = app.client.put("/api/settings/theme", json={"theme": "light"})

    assert timing.status_code == 204
    assert (settings.status_code, settings.json()["theme"]) == (200, "dark")
    assert (theme.status_code, theme.json()["theme"]) == (200, "light")
