from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import pytest

import api_actions
import budzet_ci
import cien_podstaw
import czasy_ci
from github import GitHub
from api_actions import REZERWA_POMIARU, REZERWA_SCALANIA, Api, Zapas, ZRezerwa
import pomiar_ci
import ponow_ci
from repo import ROOT
import scal_pr

REPO = "repos/{owner}/{repo}"
ZADANIA_RUNU = f"{REPO}/actions/runs/7/jobs?filter=all&per_page=100&page=1"
LISTA_RUNOW = f"{REPO}/actions/workflows/ci.yml/runs?created=2026-11-03&"
RESET = datetime(2026, 11, 19, 13, 5, tzinfo=timezone.utc).timestamp()
GODZINA_RESETU = f"{datetime.fromtimestamp(RESET, timezone.utc).astimezone():%H:%M}"
PODPROCES = """
import sys
import api_actions

class GitHub:
    def json(self, sciezka):
        return {"z": "github"}

print(api_actions.odmowa(int(sys.argv[2])))
print(api_actions.Api(GitHub()).json(sys.argv[1], lambda dane: False))
"""


class _GitHub:
    def __init__(self) -> None:
        self.pytania: list[str] = []

    def json(self, sciezka: str) -> Any:
        self.pytania.append(sciezka)
        if sciezka.startswith(LISTA_RUNOW):
            return {"workflow_runs": [{"id": 7, "status": "completed", "event": "push", "head_sha": "0" * 40, "run_attempt": 1}]}
        return {"total_count": 1, "jobs": [{"id": 70, "status": "completed"}]}

    def bajty(self, sciezka: str) -> bytes:
        self.pytania.append(sciezka)
        return b"log"

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        self.pytania.append(sciezka)
        return None


@pytest.fixture
def kopia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(api_actions.ZMIENNA_KOPII, str(tmp_path / "kopia"))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return tmp_path / "kopia"


@pytest.fixture
def dom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for nazwa in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(nazwa, str(tmp_path / "dom"))
    monkeypatch.delenv(api_actions.ZMIENNA_KOPII)
    return tmp_path / "dom"


def test_zapas_i_odpowiedzi_api_w_domu_komputera_nie_zmieniaja_wyniku_testu_ani_jego_podprocesu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dom = tmp_path / "dom"
    for nazwa in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(nazwa, str(dom))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    stan_komputera = dom / ".cache" / "maximiseart"
    _zapisz_zapas(stan_komputera, 0, time.time())
    Api(_GitHub(), stan_komputera / "api").json(ZADANIA_RUNU, lambda dane: True)
    github = _GitHub()

    w_tescie = (api_actions.odmowa(REZERWA_SCALANIA), Api(github).json(ZADANIA_RUNU, lambda dane: False) is not None)
    w_podprocesie = subprocess.run(
        [sys.executable, "-c", PODPROCES, ZADANIA_RUNU, str(REZERWA_SCALANIA)],
        cwd=ROOT / "tools" / "lib",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    assert (w_tescie, github.pytania) == ((None, True), [ZADANIA_RUNU])
    assert w_podprocesie == ["None", "{'z': 'github'}"]


def test_druga_prosba_o_zakonczony_run_z_innego_biegu_bierze_kopie_na_komputerze_bez_zapytania(dom: Path) -> None:
    pierwszy, drugi = _GitHub(), _GitHub()

    odpowiedz = Api(pierwszy).json(ZADANIA_RUNU, lambda dane: True)
    z_kopii = Api(drugi).json(ZADANIA_RUNU, lambda dane: True)
    Api(drugi).bajty(f"{REPO}/actions/jobs/70/logs")
    log_z_kopii = Api(pierwszy).bajty(f"{REPO}/actions/jobs/70/logs")

    assert (z_kopii, log_z_kopii) == (odpowiedz, b"log")
    assert (pierwszy.pytania, drugi.pytania) == ([ZADANIA_RUNU], [f"{REPO}/actions/jobs/70/logs"])
    assert (dom / ".cache" / "maximiseart" / "api").is_dir()


def test_odpowiedz_ktora_jeszcze_sie_zmieni_nie_trafia_do_kopii(kopia: Path) -> None:
    github = _GitHub()

    Api(github).json(ZADANIA_RUNU, lambda dane: False)
    Api(github).json(ZADANIA_RUNU, lambda dane: False)

    assert github.pytania == [ZADANIA_RUNU, ZADANIA_RUNU]


@pytest.mark.parametrize("pytan_przed_odmowa", [0, 1], ids=["przed listą runów", "przed zadaniami runu z listy"])
def test_narzedzie_pomiarowe_ponizej_rezerwy_konczy_sie_linia_z_godzina_resetu_bez_dalszych_zapytan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], pytan_przed_odmowa: int
) -> None:
    github = _GitHub()
    zapasy = iter([*[Zapas(5000, RESET)] * pytan_przed_odmowa, Zapas(REZERWA_POMIARU - 1, RESET)])

    kod = pomiar_ci.main(
        ["--katalog", str(tmp_path / "bieg"), "--od", "2026-11-03", "--do", "2026-11-03"],
        root=tmp_path,
        github=ZRezerwa(github, REZERWA_POMIARU, lambda: next(zapasy)),
        kopia=tmp_path / "api",
    )

    assert (kod, capsys.readouterr()) == (
        1,
        (f"POMIAR CI ODMOWA | zapas GitHub API {REZERWA_POMIARU - 1} zapytań poniżej rezerwy {REZERWA_POMIARU}: ponów po resecie limitu o {GODZINA_RESETU}\n", ""),
    )
    assert len(github.pytania) == pytan_przed_odmowa


def test_zapas_ktorego_pomiar_juz_nie_bierze_zostaje_dla_scalania_i_ponowienia(capsys: pytest.CaptureFixture[str]) -> None:
    pomiar, scalanie = _GitHub(), _GitHub()
    zapas = Zapas(REZERWA_POMIARU - 1, RESET)

    klient_pomiaru = ZRezerwa(pomiar, REZERWA_POMIARU, lambda: zapas)
    for zapytanie in (
        lambda: klient_pomiaru.json(ZADANIA_RUNU),
        lambda: klient_pomiaru.bajty(f"{REPO}/actions/jobs/70/logs"),
        lambda: klient_pomiaru.wyslij("POST", f"{REPO}/issues", {}),
    ):
        with pytest.raises(api_actions.PonizejRezerwy):
            zapytanie()
    ZRezerwa(scalanie, REZERWA_SCALANIA, lambda: zapas).json(ZADANIA_RUNU)
    ZRezerwa(pomiar, REZERWA_POMIARU, lambda: Zapas(REZERWA_POMIARU, RESET)).json(ZADANIA_RUNU)
    kod = ponow_ci.main(["--run", "7"], api=ZRezerwa(scalanie, REZERWA_SCALANIA, lambda: Zapas(REZERWA_SCALANIA - 1, RESET)))

    assert (pomiar.pytania, scalanie.pytania) == ([ZADANIA_RUNU], [ZADANIA_RUNU])
    assert (kod, capsys.readouterr().out.splitlines()) == (
        1,
        [f"PONÓW ODMOWA | zapas GitHub API {REZERWA_SCALANIA - 1} zapytań poniżej rezerwy {REZERWA_SCALANIA}: ponów po resecie limitu o {GODZINA_RESETU}"],
    )


def _zapisz_zapas(kopia: Path, pozostalo: int, odczyt: float) -> None:
    plik = kopia / "zapas-api.json"
    plik.parent.mkdir(parents=True, exist_ok=True)
    plik.write_text(json.dumps({"odczyt": odczyt, "pozostalo": pozostalo, "reset": RESET}), encoding="utf-8")


def test_scalanie_ponizej_swojej_rezerwy_odmawia_z_zapasu_zapisanego_przez_inny_watek_bez_pytania_githuba(kopia: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _zapisz_zapas(kopia, REZERWA_SCALANIA - 1, time.time())

    kod = scal_pr.main(["1", "--bez-merge"])

    assert (kod, capsys.readouterr().out.splitlines()) == (
        1,
        [f"SCAL ODMOWA | zapas GitHub API {REZERWA_SCALANIA - 1} zapytań poniżej rezerwy {REZERWA_SCALANIA}: ponów po resecie limitu o {GODZINA_RESETU}"],
    )


@pytest.mark.parametrize(
    ("klient", "rezerwa"),
    [
        pytest.param(pomiar_ci.GITHUB, REZERWA_POMIARU, id="pomiar_ci"),
        pytest.param(budzet_ci.GITHUB, REZERWA_POMIARU, id="budzet_ci"),
        pytest.param(cien_podstaw.GITHUB, REZERWA_POMIARU, id="cien_podstaw"),
        pytest.param(czasy_ci.GITHUB, REZERWA_POMIARU, id="plan_ci przez czasy_ci"),
        pytest.param(ponow_ci.GITHUB, REZERWA_SCALANIA, id="ponow_ci"),
    ],
)
def test_klient_github_narzedzia_odmawia_ponizej_jego_rezerwy_bez_uruchomienia_gh(kopia: Path, klient: GitHub, rezerwa: int) -> None:
    _zapisz_zapas(kopia, rezerwa - 1, time.time())

    with pytest.raises(api_actions.PonizejRezerwy, match=f"poniżej rezerwy {rezerwa}:"):
        klient.json(ZADANIA_RUNU)


def _rate_limit(pozostalo: int) -> str:
    return json.dumps({"resources": {"core": {"limit": 5000, "remaining": pozostalo, "reset": RESET}}})


def test_zapas_odczytany_przed_chwila_przez_inny_proces_nie_pyta_githuba_a_starszy_pyta_i_zapisuje_nowy(kopia: Path) -> None:
    odczyty: list[int] = []

    def odczyt() -> str:
        odczyty.append(1)
        return _rate_limit(4000)

    _zapisz_zapas(kopia, 2000, 1000.0)
    swiezy = api_actions.zapas_maca(odczyt=odczyt, teraz=lambda: 1000.0 + api_actions.ODSWIEZ_ZAPAS_S - 1)
    stary = api_actions.zapas_maca(odczyt=odczyt, teraz=lambda: 1000.0 + api_actions.ODSWIEZ_ZAPAS_S)
    po_odczycie = api_actions.zapas_maca(odczyt=odczyt, teraz=lambda: 1000.0 + api_actions.ODSWIEZ_ZAPAS_S + 1)

    assert (swiezy, stary, po_odczycie, len(odczyty)) == (Zapas(2000, RESET), Zapas(4000, RESET), Zapas(4000, RESET), 1)


def test_bez_odczytu_zapasu_narzedzie_pyta_jak_dotad(kopia: Path) -> None:
    def odczyt() -> str:
        raise subprocess.CalledProcessError(4, ["gh", "api", "rate_limit"])

    assert api_actions.zapas_maca(odczyt=odczyt) is None
    assert api_actions.odmowa(REZERWA_POMIARU, lambda: api_actions.zapas_maca(odczyt=odczyt)) is None


def test_w_github_actions_run_ma_wlasny_token_wiec_rezerwy_nie_ma(kopia: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _zapisz_zapas(kopia, 0, time.time())

    assert api_actions.zapas_maca(odczyt=lambda: _rate_limit(0)) is None
