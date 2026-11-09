"""Skill ``verify-github-skrzynki``: granice przebiegu na żywo i nagrania prawdziwego GitHuba.

Przebieg na żywo pisze tylko do repozytoriów próbnych (pustego i Archiwum z commitem), więc transport klienta Skrzynki
odmawia każdego innego adresu, także prawdziwej Skrzynki, zanim cokolwiek wyśle. Nagrania leżą w repozytorium publicznym, więc nie mają klucza ani
nagłówków żądań. Odtwarzanie nagrań (podstawa ``ci:``) biegnie w Mutation checks; tu sprawdza się, że odtwarzanie
odmawia żądania spoza nagrania, a sprzątanie zostawia Release razem z jego tagiem.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import pytest

from rozliczenia.centrum.github import HttpRequest
from rozliczenia.centrum.keyed_box import LIST_LAG_S
from rozliczenia.centrum.report_box import REPOSITORY, GitHubReportBox, Unreachable

SKILL = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "verify-github-skrzynki"
sys.path.insert(0, str(SKILL / "scripts"))

import github_skrzynki  # noqa: E402
import github_sprzatanie  # noqa: E402
import github_wymiana  # noqa: E402

TRIAL = "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba"
TRIAL_ARCHIVE = "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia-proba-archiwum"


@pytest.mark.parametrize("trial", [TRIAL, TRIAL_ARCHIVE], ids=["puste", "archiwum"])
@pytest.mark.parametrize(
    "url",
    [
        f"https://api.github.com/repos/{REPOSITORY}/issues",
        f"https://uploads.github.com/repos/{REPOSITORY}/releases/1/assets?name=a",
    ],
    ids=["api", "wysylka-plikow"],
)
def test_zadanie_skrzynki_idzie_do_repozytorium_probnego(url: str, trial: str) -> None:
    moved = github_wymiana.to_trial(url, trial)

    assert f"/repos/{trial}/" in moved
    assert f"/repos/{REPOSITORY}/" not in moved


@pytest.mark.parametrize("trial", [REPOSITORY, "maximiseartai/MAXIMISEART-Dad"], ids=["skrzynka", "repo-narzedzia"])
def test_transport_przebiegu_odmawia_repozytorium_docelowego_spoza_prob_przed_wysylka(trial: str) -> None:
    sent: list[str] = []
    transport = github_wymiana.LiveTransport(github_wymiana.Recorder(), github_wymiana.Pace(), sent, trial=trial)

    with pytest.raises(github_wymiana.OutsideTrial):
        transport(HttpRequest("POST", f"https://api.github.com/repos/{REPOSITORY}/releases", {}, b"{}"))

    assert sent == []


def test_adres_pobrania_pliku_z_archiwum_proby_to_ten_sam_adres_w_skrzynce() -> None:
    page = f"https://github.com/{TRIAL_ARCHIVE}/releases/download/logi-08_14_09_2026/logi.json.gz"

    assert github_wymiana.from_trial_web(page) == (
        f"https://github.com/{REPOSITORY}/releases/download/logi-08_14_09_2026/logi.json.gz"
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://github.com/{REPOSITORY}/releases/download/t/a.gz",
        f"https://github.com/{TRIAL}/releases/download/t/a.gz",
        "https://github.com/maximiseartai/MAXIMISEART-Dad/releases/download/v0.1.0/a.gz",
        f"https://example.com/{TRIAL_ARCHIVE}/releases/download/t/a.gz",
    ],
    ids=["skrzynka", "puste-probne", "repo-narzedzia", "inny-host"],
)
def test_strona_poza_archiwum_proby_jest_poza_przebiegiem(url: str) -> None:
    admin = github_wymiana.Admin("klucz-nieuzywany", github_wymiana.Pace())

    with pytest.raises(github_wymiana.OutsideTrial):
        github_wymiana.from_trial_web(url)
    with pytest.raises(github_wymiana.OutsideTrial):
        admin.web_status(url)

    assert admin.log == []


@pytest.mark.parametrize(
    "url",
    [
        f"https://api.github.com/repos/{TRIAL}/issues",
        "https://api.github.com/repos/maximiseartai/MAXIMISEART-Dad/issues",
        f"https://example.com/repos/{REPOSITORY}/issues",
        f"https://api.github.com/repos/{REPOSITORY}-inne/issues",
    ],
    ids=["juz-probne", "repo-narzedzia", "inny-host", "repo-o-tym-samym-poczatku"],
)
def test_transport_przebiegu_odmawia_adresu_spoza_skrzynki_przed_wysylka(
    url: str,
) -> None:
    sent: list[str] = []
    transport = github_wymiana.LiveTransport(github_wymiana.Recorder(), github_wymiana.Pace(), sent)

    with pytest.raises(github_wymiana.OutsideTrial):
        transport(HttpRequest("POST", url, {}, b"{}"))

    assert sent == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"/repos/{REPOSITORY}/issues"),
        ("DELETE", "/repos/maximiseartai/MAXIMISEART-Dad/git/refs/tags/v0.1.0"),
        ("GET", "/user/repos"),
        ("DELETE", f"/repos/{TRIAL_ARCHIVE}-inne/releases/1"),
    ],
    ids=["skrzynka", "repo-narzedzia", "odczyt-poza-proba", "repo-o-tym-samym-poczatku"],
)
def test_harness_odmawia_poza_repozytorium_probnym(method: str, path: str) -> None:
    admin = github_wymiana.Admin("klucz-nieuzywany", github_wymiana.Pace())

    with pytest.raises(github_wymiana.OutsideTrial):
        admin.request(method, path)

    assert admin.log == []


_TOKEN = re.compile(r"\b(gh[opsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")


def test_nagrania_sa_i_nie_maja_klucza_ani_naglowkow_zadan() -> None:
    recordings = sorted((SKILL / "nagrania").glob("*.json"))
    texts = {path.name: path.read_text(encoding="utf-8") for path in recordings}

    assert {"aktualnosc.json"} <= set(texts), sorted(texts)
    assert all(any(name.startswith(f"{feature}-") for name in texts) for feature in ("skrzynka", "archiwum")), sorted(texts)
    assert [name for name, text in texts.items() if _TOKEN.search(text) or "Authorization" in text] == []
    for name, text in texts.items():
        for case in json.loads(text)["przypadki"].values():
            assert all(
                set(exchange) == set(github_wymiana.Exchange("", "", None, None, None, None, None).to_json())
                for exchange in case["wymiany"]
            ), name


@pytest.mark.parametrize("case", ["etykieta-z-githuba", "lista-strony", "lista-zamkniete"])
def test_przypadek_pada_gdy_lista_githuba_nadazyla_pozniej_niz_zaklada_centrum(case: str) -> None:
    """Centrum zakłada, że lista GitHuba pokazuje każdy zapis po ``keyed_box.LIST_LAG_S`` (#879), więc przypadek, w
    którym lista nadążyła później, to rozjazd, choć klient odpowiada dobrze; nagrane opóźnienie przypadek przepuszcza."""

    recording = json.loads((SKILL / "nagrania" / "skrzynka-fine-grained.json").read_text(encoding="utf-8"))
    facts = recording["przypadki"][case]["fakty"]
    recorded = {result.case: result.problems for result in github_skrzynki.replay("skrzynka-fine-grained", recording)}
    facts["nadazylo_po_s"] = LIST_LAG_S + 0.1

    late = {result.case: result.problems for result in github_skrzynki.replay("skrzynka-fine-grained", recording)}

    assert recorded[case] == []
    assert [problem for problem in late[case] if "LIST_LAG_S" in problem] != [], late[case]
    assert {name: problems for name, problems in late.items() if name != case} == {
        name: problems for name, problems in recorded.items() if name != case
    }


def test_odtwarzanie_odmawia_zadania_spoza_nagrania() -> None:
    recorded = github_wymiana.Exchange(
        "GET",
        f"/repos/{REPOSITORY}/issues/1/comments?per_page=100&page=1",
        None,
        None,
        200,
        None,
        [],
    )
    transport = github_wymiana.ReplayTransport([recorded])

    outcome = GitHubReportBox(transport=transport).comments(2, key="github_pat_ODTWORZENIE")

    assert outcome == Unreachable()
    [problem] = transport.finish()
    assert "issues/2/comments" in problem and "issues/1/comments" in problem


class _ArchiveHarness:
    """Harness repozytorium próbnego Archiwum z jednym Release'em runu (ze znacznikiem) i jego tagiem."""

    def __init__(self, run: str, assets: list[str]) -> None:
        self.release = {"id": 7, "tag_name": f"logi-verify-{run}", "body": f"{github_wymiana.RUN_MARKER}{run}"}
        self.assets = [{"name": name} for name in assets]
        self.deleted: list[str] = []

    def pages(self, path: str) -> list[object]:
        if path.endswith("/releases?"):
            return [self.release]
        if path.endswith("/releases/7/assets?"):
            return list(self.assets)
        if path.endswith("/tags?"):
            return [{"name": self.release["tag_name"]}]
        raise AssertionError(path)

    def request(self, method: str, path: str, payload: object = None) -> tuple[int, object]:
        self.deleted.append(f"{method} {path}")
        return 204, None


@pytest.mark.parametrize(
    ("assets", "deleted"),
    [
        (["obcy-plik.json.gz"], []),
        (
            ["20261105T000000-abcdef-settlement-1.json.gz"],
            ["releases/7", "git/refs/tags/logi-verify-20261105T000000-abcdef"],
        ),
    ],
    ids=["z-cudzym-plikiem-zostaje-z-tagiem", "z-plikami-runu-znika-z-tagiem"],
)
def test_sprzatanie_usuwa_tag_archiwum_runu_tylko_razem_z_jego_release(assets: list[str], deleted: list[str]) -> None:
    run = "20261105T000000-abcdef"
    harness = _ArchiveHarness(run, assets)

    github_sprzatanie._clean_releases(harness, TRIAL_ARCHIVE, run, set())  # type: ignore[arg-type]

    assert harness.deleted == [f"DELETE /repos/{TRIAL_ARCHIVE}/{path}" for path in deleted]
