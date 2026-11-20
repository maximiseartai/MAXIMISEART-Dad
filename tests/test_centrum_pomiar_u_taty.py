from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re

import pytest

from rozliczenia.centrum.dad_action_journal import DAD_ACTIONS_FILE
from rozliczenia.centrum.log import FOR_LOGS_FILE, MAX_VIEW_TIMINGS, CentrumLog
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.period_folder import PeriodFolder
from tests.fixtures.centrum import Centrum, centrum, view_timing

SERVER_TIMING = re.compile(r"centrum;dur=\d+(\.\d+)?")


def test_kazda_odpowiedz_api_takze_odmowa_i_nieoczekiwany_wyjatek_podaje_sam_czas_obslugi_w_server_timing(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    client = app.client
    register = tmp_path / "ZLECENIA INTERMAX.xlsx"
    register.touch()
    app.platform.chosen_files.append(register)
    assert client.post("/api/settings/register/choose").status_code == 200
    app.platform.failure = RuntimeError("system nie otworzył pliku")

    responses = [
        client.get("/api/health"),
        client.get("/api/settings"),
        client.get("/api/periods"),
        client.put("/api/settings/theme", json={"theme": "light"}),
        client.put("/api/settings/theme", json={"theme": "light"}, headers={"Origin": "http://zly.example"}),
        client.get("/api/health", headers={"Host": "zly.example:47811"}),
        client.post("/api/periods/22_28_09_2026/open", json={"target": "period_folder"}),
        client.post("/api/settings/register/open"),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 403, 403, 409, 500]
    timings = [response.headers.get("server-timing", "") for response in responses]
    assert [timing for timing in timings if not SERVER_TIMING.fullmatch(timing)] == []


def log_entries(app: Centrum) -> list[str]:
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


def test_okno_ustawien_mierzy_sie_jak_widok(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    settings = view_timing(
        kind="navigation",
        page="ustawienia",
        ready_ms=310,
        fcp_ms=None,
        skeleton_ms=150,
        requests=[{"operation": "getConfiguration", "browser_ms": 290, "server_ms": 270}],
    )

    response = app.client.post("/api/view-timings", json=settings)

    assert response.status_code == 204
    assert log_entries(app) == [
        "pomiar widok=przejscie-w-menu strona=ustawienia gotowe_ms=310 szkielet_ms=150 zapytania=getConfiguration:290/270",
    ]


def test_dziennik_przyjmuje_najwyzej_200_pomiarow_na_jedno_uruchomienie_centrum(tmp_path: Path) -> None:
    app = centrum(tmp_path)

    responses = [app.client.post("/api/view-timings", json=view_timing()) for _ in range(201)]
    after_restart = centrum(tmp_path).client.post("/api/view-timings", json=view_timing(page="okresy"))

    assert {response.status_code for response in responses} == {204}
    assert after_restart.status_code == 204
    entries = [entry for entry in log_entries(app) if entry.startswith("pomiar ")]
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
def test_pomiar_z_nieznana_nazwa_albo_wartoscia_poza_zakresem_jest_odrzucony_bez_wpisu_w_dzienniku_dzialan_taty(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    app = centrum(tmp_path)

    response = app.client.post("/api/view-timings", json=view_timing(**changes))

    assert response.status_code == 422
    assert log_entries(app) == []
    assert not (app.log_path.parent / DAD_ACTIONS_FILE).exists()


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
    assert (theme.status_code, theme.json()["settings"]["theme"]) == (200, "light")


_FOLDER_TEXT = r"C:\Users\Tata\OneDrive\INEA\22_28_09_2026 Kowalski\ZBIORCZY.xlsx"
_KEY_TEXT = "github_pat_11AAAAAAA0wymyslony"
_FAILURE_ENTRIES: dict[str, Callable[[CentrumLog, OSError], None]] = {
    "nieoczekiwany-wyjatek": lambda log, failure: log.unexpected_failure(failure, where="/api/periods"),
    "aktualizacja-wynik-zostaje": CentrumLog.update_result_kept,
    "dzialania-taty-niedostepne": CentrumLog.dad_actions_unavailable,
    "dziennik-wyceny-niedostepny": lambda log, failure: log.pricing_journal_unavailable(failure, where="wpis"),
    "skrzynka-zapisy-niedostepne": CentrumLog.box_notes_unavailable,
}


@pytest.mark.parametrize("event", _FAILURE_ENTRIES)
def test_z_wyjatku_do_dziennika_trafia_tylko_nazwa_typu_bez_sciezki_folderu_okresow_i_klucza(
    tmp_path: Path, event: str
) -> None:
    lines: list[str] = []

    _FAILURE_ENTRIES[event](
        CentrumLog(tmp_path / "centrum.log", append=lines.append),
        PermissionError(13, f"Odmowa dostępu z kluczem {_KEY_TEXT}", _FOLDER_TEXT),
    )

    [line] = lines
    assert line.split(" ")[1:3] == [event, "typ=PermissionError"]
    assert [secret for secret in ("Odmowa", "Tata", "Kowalski", _KEY_TEXT) if secret in line] == []


def test_po_limicie_pomiarow_widokow_dziennik_dalej_zapisuje_prace_serwera(tmp_path: Path) -> None:
    lines: list[str] = []
    log = CentrumLog(tmp_path / "centrum.log", append=lines.append)

    for _ in range(MAX_VIEW_TIMINGS + 1):
        log.view_timed(view="przejscie-w-menu", page="okresy", ready_ms=1, fcp_ms=None, skeleton_ms=0, requests=[])
    log.stopped(port=47811)

    assert [line.split(" ")[1] for line in lines] == ["pomiar"] * MAX_VIEW_TIMINGS + ["stop"]


def test_wynik_aktualizacji_zapisany_przed_restartem_centrum_nie_trafia_do_dziennika_drugi_raz(tmp_path: Path) -> None:
    log = CentrumLog(tmp_path / "centrum.log")
    log.started(port=47811, version="v1", console=False)
    log.update_started(before="a1")
    log.update_finished(result="AKTUALIZACJA_NIEUDANA", before="a1", after=None, installed=False)
    log.started(port=47811, version="v1", console=False)

    assert log.update_awaits(result="AKTUALIZACJA_NIEUDANA", before="a1", after=None) is False


def test_wpisy_dla_logow_ktorych_nie_da_sie_oproznic_dostaja_tez_nastepne_logi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = CentrumLog(tmp_path / "centrum.log")
    log.stopped(port=47811)
    write_text = Path.write_text

    def for_logs_locked(self: Path, data: str, encoding: str | None = None) -> int:
        if self.name == FOR_LOGS_FILE:
            raise PermissionError(13, "Odmowa dostępu", str(self))
        return write_text(self, data, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", for_logs_locked)

    takes = [log.take_for_logs() for _ in range(2)]

    assert [([entry.split(" ")[1] for entry in entries], omitted) for entries, omitted in takes] == [(["stop"], 0)] * 2
