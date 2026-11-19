"""Rozstrzygnięcie D1 (``tools/cien_podstaw.py``): kandydaci na defekty złapane przez kroki skilli NF na PR, przyczyny
z ich audytu, oszczędność N0 z cienia ``plan.json`` i ucieczki z NF w wyroczni ``main`` dają wynik według reguły z ADR
0020, D1."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
import io
import json
from pathlib import Path
import subprocess
from typing import Any, NoReturn
import zipfile

import pytest

from tests.fixtures.git_repo import commit, git, repository
from tests.fixtures.znane_luki import assert_znane_luki

import api_actions
import cien_podstaw
from cien_podstaw import OSZCZEDNOSC_MIN, X, BladAudytu, Glowa, Naprawa, PlikNaprawy, Porazka, Pytest, Rekordy, RunMain, RunPr, Wariant, Wynik, rozstrzygnij
from github import REPO
import plan_runu
import repo as repo_gita
from zakres_runu import Podstawy, Zdarzenie

CIEN = {"V0": Wariant(("verify-a/ci", "verify-b/ci"), 300.0), "NF": Wariant(("verify-a/ci",), 200.0), "N0": Wariant((), 100.0)}


def _pr(galaz: str = "g", *, run: int = 1, padle: tuple[str, ...] = ("verify-a/ci",), naprawa: tuple[str, ...] | None = ("src/a.py",),
        pytest: Pytest = Pytest.PRZESZEDL, cien: Mapping[str, Wariant] | None = CIEN, probka: bool = False, main_zmienil: tuple[str, ...] = (),
        przepisana: bool = False) -> RunPr:  # fmt: skip
    """Czerwony run PR ``run``, którego naprawa ma pliki ``naprawa``, z nich ``main_zmienil`` zmienione przez ``main``
    między bazami głów; ``naprawa=None``: bez następnego runu gałęzi z wynikiem."""

    glowa = Glowa(run, f"https://github.com/o/r/actions/runs/{run}", "c" * 40, "b" * 40)
    pliki = tuple(PlikNaprawy(sciezka, sciezka, "", "", sciezka in main_zmienil) for sciezka in naprawa or ())
    return RunPr(run, galaz, pytest, padle, None if naprawa is None else Naprawa(glowa, glowa, pliki, przepisana), cien, probka)


def _sciezki(run: RunPr) -> tuple[str, ...] | None:
    return None if run.naprawa is None else run.naprawa.sciezki


def _klucze(porazki: tuple[Porazka, ...]) -> tuple[str, ...]:
    return tuple(porazka.klucz for porazka in porazki)


def _rekordy(*pr: RunPr, main: tuple[RunMain, ...] = (), pr_runow: int = 60, od: str = "2026-11-20") -> Rekordy:
    return Rekordy(od, "2026-12-03", pr_runow, pr, main)


@pytest.mark.parametrize(
    ("run", "kandydat"),
    [
        (_pr(naprawa=("src/rozliczenia/a.py",)), True),
        (_pr(naprawa=(".agents/skills/verify-a/scripts/drive.py",)), True),
        # Naprawa w folderze innego skilla, w testach albo jej brak (flaky, infrastruktura, ostatni run gałęzi): to nie kandydat.
        (_pr(naprawa=(".agents/skills/verify-b/SKILL.md",)), False),
        (_pr(naprawa=("tests/test_a.py",)), False),
        (_pr(naprawa=None), False),
        # Defekt, który złapał też pytest, NF nie złapał sam.
        (_pr(pytest=Pytest.PADL), False),
        # Krok spoza NF albo w N0 nie różni wariantów.
        (_pr(padle=("verify-b/ci",), naprawa=("src/b.py",)), False),
        (_pr(cien={**CIEN, "N0": Wariant(("verify-a/ci",), 200.0)}), False),
    ],
    ids=["naprawa w src", "naprawa w folderze skilla", "naprawa w innym skillu", "naprawa w testach", "bez następnego runu",
         "padł też pytest", "krok tylko w V0", "krok też w N0"],  # fmt: skip
)
def test_kandydat_nf_to_padly_krok_nf_spoza_n0_przy_zielonym_pytest_z_naprawa_w_folderze_skilla_albo_src(run: RunPr, kandydat: bool) -> None:
    assert _klucze(rozstrzygnij(_rekordy(run)).kandydaci) == (("1 verify-a/ci",) if kandydat else ())


def _linie_porazek(rekordy: Rekordy) -> dict[str, list[str]]:
    """Klucz każdej porażki kroku skilla czerwonych runów rekordów → pierwsze pole linii wyniku, której drugie pole to
    ten klucz (przy ``NIE LICZY SIĘ`` z powodem)."""

    porazki: dict[str, list[str]] = {f"{run.run} {krok}": [] for run in rekordy.pr for krok in run.padle}
    for pola in (linia.split(" | ") for linia in cien_podstaw.wypisz(rekordy, rozstrzygnij(rekordy))):
        if len(pola) > 1 and pola[1] in porazki:
            porazki[pola[1]].append(f"{pola[0]} | {pola[-1]}" if pola[0] == "NIE LICZY SIĘ" else pola[0])
    return porazki


@pytest.mark.parametrize(
    ("run", "linie"),
    [
        (_pr(), {"1 verify-a/ci": ["KANDYDAT NF 1/1"]}),
        (_pr(naprawa=None), {"1 verify-a/ci": ["NIEPOLICZONY, wymaga audytu"]}),
        (_pr(naprawa=(), przepisana=True), {"1 verify-a/ci": ["NIEPOLICZONY, wymaga audytu"]}),
        (_pr(cien=None), {"1 verify-a/ci": ["BEZ CIENIA"]}),
        (_pr(cien=None, naprawa=("tests/test_a.py",)), {"1 verify-a/ci": ["NIE LICZY SIĘ | run bez artefaktu planu, bez naprawy w folderze skilla ani src/"]}),
        (_pr(pytest=Pytest.PADL), {"1 verify-a/ci": ["NIE LICZY SIĘ | padł też pytest: pytest złapał"]}),
        (_pr(cien={**CIEN, "N0": Wariant(("verify-a/ci",), 200.0)}), {"1 verify-a/ci": ["NIE LICZY SIĘ | krok spoza NF albo w N0: warianty się nie różnią"]}),
        (_pr(naprawa=("tests/test_a.py",)), {"1 verify-a/ci": ["NIE LICZY SIĘ | naprawa tylko poza folderem skilla i src/: tests/test_a.py"]}),
        (_pr(naprawa=()), {"1 verify-a/ci": ["NIE LICZY SIĘ | własna zmiana PR przy następnej głowie ta sama co przy czerwonej (np. tylko scalenie main)"]}),
        (_pr(padle=("verify-a/ci", "verify-b/ci")),
         {"1 verify-a/ci": ["KANDYDAT NF 1/1"], "1 verify-b/ci": ["NIE LICZY SIĘ | krok spoza NF albo w N0: warianty się nie różnią"]}),
    ],
    ids=["kandydat", "bez następnego runu", "przepisana historia", "bez cienia z naprawą", "bez cienia bez naprawy", "padł też pytest", "krok też w N0",
         "naprawa poza folderem skilla i src", "bez zmiany własnej zmiany PR", "dwa kroki jednego runu"],  # fmt: skip
)
def test_kazda_porazka_kroku_skilla_czerwonego_runu_stoi_w_wyniku_dokladnie_raz_z_postacia_z_tabeli_docstringu(
    run: RunPr, linie: dict[str, list[str]]
) -> None:
    """Reguła, która się pomyli, przesuwa porażkę do innej linii na oczach audytora, a nie gubi jej po cichu."""

    assert _linie_porazek(_rekordy(run)) == linie


def test_dowod_porazki_wymienia_inne_czerwone_runy_galezi_tylko_z_tym_samym_krokiem() -> None:
    cien = {**CIEN, "NF": Wariant(("verify-a/ci", "verify-b/ci"), 200.0)}
    rekordy = _rekordy(_pr(run=1, cien=cien), _pr(run=2, padle=("verify-b/ci",), naprawa=("src/b.py",), cien=cien), _pr(run=3, cien=cien))

    linie = cien_podstaw.wypisz(rekordy, rozstrzygnij(rekordy))

    assert [linia for linia in linie if linia.startswith(("KANDYDAT", "  ten krok"))] == [
        "KANDYDAT NF 1/3 | 1 verify-a/ci | g, PR bez merge'a w oknie | do audytu",
        "  ten krok padł też w runach tej gałęzi: 3 (kandydat 2)",
        "KANDYDAT NF 2/3 | 3 verify-a/ci | g, PR bez merge'a w oknie | do audytu",
        "  ten krok padł też w runach tej gałęzi: 1 (kandydat 1)",
        "KANDYDAT NF 3/3 | 2 verify-b/ci | g, PR bez merge'a w oknie | do audytu",
    ]


def test_kazdy_czerwony_run_galezi_z_tym_samym_krokiem_jest_osobna_porazka_w_wyniku_bo_moze_miec_inna_przyczyne() -> None:
    """Jedna gałąź z jednym krokiem miała dwie przyczyny (#2178 r3, D1): run 1 naprawiony commitem w ``src/``, run 2
    usunięciem commitu, więc obie porażki stoją w wyniku, każda z innymi runami gałęzi przy dowodzie."""

    runy = (_pr(run=1), _pr(run=2, naprawa=(), przepisana=True), _pr(run=3, naprawa=(".agents/skills/verify-a/drive.py",)), _pr("h", run=4, cien=None))
    rekordy = _rekordy(*runy)
    wynik = rozstrzygnij(rekordy)

    linie = cien_podstaw.wypisz(rekordy, wynik)

    assert (_klucze(wynik.kandydaci), _klucze(wynik.niepoliczone), _klucze(wynik.bez_cienia)) == (("1 verify-a/ci", "3 verify-a/ci"), ("2 verify-a/ci",), ("4 verify-a/ci",))
    assert [linia for linia in linie if linia.startswith(("KANDYDAT", "NIEPOLICZONY", "  ten krok"))] == [
        "KANDYDAT NF 1/2 | 1 verify-a/ci | g, PR bez merge'a w oknie | do audytu",
        "  ten krok padł też w runach tej gałęzi: 3 (kandydat 2), 2 (niepoliczony)",
        "KANDYDAT NF 2/2 | 3 verify-a/ci | g, PR bez merge'a w oknie | do audytu",
        "  ten krok padł też w runach tej gałęzi: 1 (kandydat 1), 2 (niepoliczony)",
        "NIEPOLICZONY, wymaga audytu | 2 verify-a/ci | g, PR bez merge'a w oknie | czerwona głowa nie jest przodkiem następnej"
        " (rebase, usunięty commit, reset): naprawa usunięciem commitu nie ma pliku",
        "  ten krok padł też w runach tej gałęzi: 1 (kandydat 1), 3 (kandydat 2)",
    ]


@pytest.mark.parametrize(
    ("runy", "wymaga"),
    [
        ((_pr(main_zmienil=("src/a.py",)),), ("1 verify-a/ci",)),
        ((_pr(naprawa=("src/a.py", "src/b.py"), main_zmienil=("src/a.py",)),), ()),
        # Plik spoza naprawy kroku (test) nie czyni kandydata pewnym.
        ((_pr(naprawa=("src/a.py", "tests/test_a.py"), main_zmienil=("src/a.py",)),), ("1 verify-a/ci",)),
        # Każdy czerwony run gałęzi ma własnego kandydata, więc naprawa innego runu nie zdejmuje znacznika.
        ((_pr(main_zmienil=("src/a.py",)), _pr(run=2)), ("1 verify-a/ci",)),
        ((_pr(pytest=Pytest.NIE_SKONCZYL),), ("1 verify-a/ci",)),
    ],
    ids=["jedyny plik naprawy zmienił też main", "drugi plik naprawy bez zmiany main", "drugi plik spoza naprawy kroku",
         "drugi czerwony run gałęzi z naprawą bez zmiany main", "run anulowany, zanim pytest skończył"],  # fmt: skip
)
def test_kandydat_wymaga_audytu_gdy_kazdy_plik_naprawy_kroku_zmienil_main_albo_run_anulowano_przed_koncem_pytest(
    runy: tuple[RunPr, ...], wymaga: tuple[str, ...]
) -> None:
    wynik = rozstrzygnij(_rekordy(*runy))

    assert (_klucze(wynik.kandydaci)[:1], _klucze(wynik.wymaga_audytu)) == (("1 verify-a/ci",), wymaga)


@pytest.mark.parametrize(
    ("runy", "niepoliczony"),
    [
        ((_pr(naprawa=(), przepisana=True),), True),
        ((_pr(naprawa=("tests/test_a.py",), przepisana=True),), True),
        ((_pr(naprawa=None),), True),
        ((_pr(naprawa=(), przepisana=False),), False),
        # Ten sam krok gałęzi z naprawą w innym runie nie ukrywa tej porażki; z pytest albo spoza NF to nie krok NF.
        ((_pr(naprawa=(), przepisana=True), _pr(run=2)), True),
        ((_pr(naprawa=(), przepisana=True, pytest=Pytest.PADL),), False),
        ((_pr(naprawa=(), przepisana=True, cien={**CIEN, "N0": Wariant(("verify-a/ci",), 200.0)}),), False),
    ],
    ids=["bez plików naprawy", "naprawa spoza folderu skilla i src", "bez następnego runu z wynikiem", "głowa czerwona przodkiem następnej",
         "krok gałęzi kandydatem w innym runie", "padł też pytest", "krok też w N0"],  # fmt: skip
)
def test_porazka_kroku_nf_bez_naprawy_z_przepisana_historia_albo_bez_nastepnego_runu_jest_niepoliczona_do_audytu(
    runy: tuple[RunPr, ...], niepoliczony: bool
) -> None:
    wynik = rozstrzygnij(_rekordy(*runy))

    assert _klucze(wynik.niepoliczone) == (("1 verify-a/ci",) if niepoliczony else ())


def test_prawdziwe_defekty_to_rozne_przyczyny_potwierdzone_audytem_kandydatow_i_niepoliczonych() -> None:
    """Jednostka z #2169: dwie gałęzie z jedną poprawką to jedna przyczyna (jedno czerwone ``main`` i jeden PR naprawy),
    potwierdzony niepoliczony liczy się, a porażka z pustą listą (nie prawdziwy defekt albo niepewny) nie."""

    runy = (_pr("g", run=1), _pr("h", run=2), _pr("h", run=3, naprawa=None), _pr("k", run=4))
    audyt = {"1 verify-a/ci": ["dziennik przed wpisem start"], "2 verify-a/ci": ["dziennik przed wpisem start"], "3 verify-a/ci": ["napęd"], "4 verify-a/ci": []}

    rekordy = _rekordy(*runy)
    wynik = rozstrzygnij(rekordy, audyt)

    assert {nazwa: _klucze(porazki) for nazwa, porazki in (wynik.przyczyny or {}).items()} == {
        "dziennik przed wpisem start": ("1 verify-a/ci", "2 verify-a/ci"),
        "napęd": ("3 verify-a/ci",),
    }
    assert [linia for linia in cien_podstaw.wypisz(rekordy, wynik) if linia.startswith("BEZ PRZYCZYNY")] == [
        "BEZ PRZYCZYNY | 4 verify-a/ci (audyt: nie prawdziwy defekt albo niepewny)"
    ]


@pytest.mark.parametrize(
    "audyt",
    [{"1 verify-a/ci": []}, {"1 verify-a/ci": [], "2 verify-a/ci": [], "3 verify-a/ci": ["p"]}],
    ids=["bez porażki z wyniku", "z porażką spoza wyniku"],
)
def test_audyt_ktory_nie_wymienia_dokladnie_porazek_z_wyniku_to_odmowa(audyt: dict[str, list[str]]) -> None:
    with pytest.raises(BladAudytu, match="audyt nie pasuje do wyniku"):
        rozstrzygnij(_rekordy(_pr(run=1), _pr(run=2, naprawa=None)), audyt)


@pytest.mark.parametrize("tekst", ['{"1 verify-a/ci": null}', '{"1 verify-a/ci": [""]}', '{"1 verify-a/ci": "p"}', '[["1 verify-a/ci", ["p"]]]'],
                         ids=["bez listy", "pusta nazwa przyczyny", "napis zamiast listy", "lista zamiast obiektu"])  # fmt: skip
def test_audyt_w_innej_postaci_niz_obiekt_list_nazw_przyczyn_to_odmowa_przed_zbieraniem(tmp_path: Path, tekst: str) -> None:
    (tmp_path / "audyt.json").write_text(tekst, encoding="utf-8")

    # Bez GitHuba i gita: zbieranie dla okna nie zaczyna się przed odmową.
    with pytest.raises(SystemExit) as wyjscie:
        cien_podstaw.main(["--katalog", str(tmp_path / "bieg"), "--od", "2026-11-12", "--do", "2026-11-12", "--audyt", str(tmp_path / "audyt.json")], root=tmp_path, github=_GitHub({}, {}))

    assert wyjscie.value.code == 2


def test_oszczednosc_n0_to_srednia_roznica_scian_nf_i_n0_z_probki_razy_runy_pr_okna_w_minutach() -> None:
    szybki_nf = {**CIEN, "NF": Wariant(("verify-a/ci",), 100.0)}
    probka = (_pr(padle=(), probka=True), _pr(padle=(), cien=szybki_nf, probka=True), _pr(padle=(), cien=None, probka=True))

    # Czerwony run spoza próbki ma cień do przypisania defektu, ale średniej nie przesuwa.
    wynik = rozstrzygnij(_rekordy(*probka, _pr(cien={**CIEN, "N0": Wariant((), 0.0)}), pr_runow=60))

    # Różnice 100 i 0 s, średnio 50 s na run, razy 60 runów okna: 50 min.
    assert (wynik.probka, wynik.oszczednosc_min) == (2, 50.0)


def test_ucieczka_z_nf_to_padla_na_main_podstawa_ktora_nf_pominal_na_scalonym_pr_a_czerwien_to_mediana_jej_runow() -> None:
    main = (
        RunMain(7, ("verify-b/ci",), ("verify-b/ci",), 30.0),
        RunMain(8, ("verify-b/ci",), (), 90.0),
        RunMain(9, ("verify-b/ci", "verify-c/ci"), ("verify-c/ci",), 50.0),
    )

    wynik = rozstrzygnij(_rekordy(main=main))

    assert (wynik.ucieczki, wynik.czerwien_min) == (((7, "verify-b/ci"), (9, "verify-c/ci")), 40.0)


@pytest.mark.parametrize(
    ("przyczyny", "oszczednosc_min", "od", "wynik"),
    [
        (X - 1, OSZCZEDNOSC_MIN, "2026-11-20", Wynik.N0_WYGRYWA),
        (X, OSZCZEDNOSC_MIN, "2026-11-20", Wynik.NF_ZOSTAJE),
        (X - 1, OSZCZEDNOSC_MIN - 1, "2026-11-20", Wynik.NF_ZOSTAJE),
        (None, OSZCZEDNOSC_MIN, "2026-11-20", Wynik.CZEKA_NA_AUDYT),
        (None, OSZCZEDNOSC_MIN - 1, "2026-11-20", Wynik.NF_ZOSTAJE),
        (X - 1, OSZCZEDNOSC_MIN, "2026-11-27", Wynik.OKNO),
    ],
    ids=["mniej niż X przyczyn, oszczędność na progu", "X przyczyn", "oszczędność pod progiem", "bez audytu", "bez audytu, oszczędność pod progiem",
         "okno 7 dni"],  # fmt: skip
)
def test_n0_wygrywa_tylko_gdy_audyt_potwierdzil_mniej_niz_x_przyczyn_w_14_dniach_a_oszczednosc_siega_progu(
    przyczyny: int | None, oszczednosc_min: float, od: str, wynik: Wynik
) -> None:
    # Każdy run ma cień, w którym NF jest o ``oszczednosc_min`` minut na 600 runów okna dłuższy od N0, a każdy z 2X
    # kandydatów dzieli przyczynę z drugim, więc par gałąź + krok jest dwa razy więcej niż przyczyn; drogie ucieczki
    # z NF na main przechodzą też przy N0, więc wyniku nie zmieniają.
    cien = {**CIEN, "N0": Wariant((), CIEN["NF"].sciana_s - oszczednosc_min * 60 / 600)}
    runy = [_pr(f"g{n}", run=n, cien=cien) for n in range(2 * X)]
    audyt = None if przyczyny is None else {f"{n} verify-a/ci": [f"przyczyna {n // 2}"] if n // 2 < przyczyny else [] for n in range(2 * X)}
    main = (RunMain(1, ("verify-b/ci",), ("verify-b/ci",), 600.0),)

    rekordy = _rekordy(*runy, _pr("probka", run=99, padle=(), cien=cien, probka=True), main=main, pr_runow=600, od=od)

    assert rozstrzygnij(rekordy, audyt).wynik is wynik


# --- zbieranie z GitHuba i gita ---


class _GitHub:
    """Odpowiedzi API po ścieżce; zapytanie spoza nich to ``KeyError``, a każde trafia do ``pytania``."""

    def __init__(self, odpowiedzi: dict[str, Any], bajty: dict[str, bytes]) -> None:
        self.odpowiedzi, self.pliki = odpowiedzi, bajty
        self.pytania: list[str] = []

    def json(self, sciezka: str) -> Any:
        self.pytania.append(sciezka)
        return self.odpowiedzi[sciezka]

    def bajty(self, sciezka: str) -> bytes:
        self.pytania.append(sciezka)
        return self.pliki[sciezka]

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> NoReturn:
        raise AssertionError(f"pomiar tylko czyta: {metoda} {sciezka}")


def _zip_planu(cien: dict[Podstawy, tuple[tuple[str, ...], float]]) -> bytes:
    plan = plan_runu.Plan(Zdarzenie.PULL_REQUEST, 90.0, (), (), cien=tuple(plan_runu.Cien(w, kroki, s, 3) for w, (kroki, s) in cien.items()))
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w") as archiwum:
        archiwum.writestr(plan_runu.PLIK, plan.do_json())
    return bufor.getvalue()


def _run(numer: int, event: str, galaz: str, sha: str, wynik: str, godzina: int, koniec: str = "10") -> dict[str, Any]:
    """Run utworzony o ``godzina``:00, zakończony o ``godzina``:``koniec`` albo o godzinie ``koniec`` z dwukropkiem."""

    skonczony = koniec if ":" in koniec else f"{godzina:02}:{koniec}"
    return {"id": numer, "event": event, "head_branch": galaz, "head_sha": sha, "status": "completed", "conclusion": wynik,
            "created_at": f"2026-11-12T{godzina:02}:00:00Z", "updated_at": f"2026-11-12T{skonczony}:00Z",
            "html_url": f"https://github.com/o/r/actions/runs/{numer}"}  # fmt: skip


@pytest.fixture
def swiat(tmp_path: Path) -> tuple[Path, _GitHub]:
    """PR ``g``: czerwony run 2 (padła podstawa verify-a w Mutation checks), naprawa w folderze skilla, zielony run 3 i
    merge do ``main``, którego run 4 jest czerwony przez podstawę verify-b, pominiętą przez NF na runie 3. Ponowiona próba
    runu 4 kończy się o 6:00, po zielonym runie 5, więc czerwień kończy dopiero zielony run 6 o 6:40. ``main`` idzie po
    merge'u dalej o dwa commity, na których biegnie run 6, więc baza głów PR to ``main`` sprzed merge'a, a nie sprzed
    ostatniego commitu okna."""

    repo = repository(tmp_path / "repo", {"src/a.py": "A = 1\n", ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\n---\n"}, tools=())
    baza = commit(repo, "baza")
    git(repo, "checkout", "--quiet", "-b", "g")
    (repo / "src/a.py").write_text("A = 2\n", encoding="utf-8")
    czerwona = commit(repo, "zmiana")
    (repo / ".agents/skills/verify-a/drive.py").write_text("X = 1\n", encoding="utf-8")
    naprawiona = commit(repo, "naprawa")
    git(repo, "checkout", "--quiet", baza)
    git(repo, "merge", "--quiet", "--no-ff", "--message", "Merge pull request #1 from o/g", "g")
    scalona = git(repo, "rev-parse", "HEAD")
    for numer in (1, 2):
        (repo / f"src/z{numer}.py").write_text("Z = 1\n", encoding="utf-8")
        dalej = commit(repo, f"main po merge'u {numer}")
    runy = [
        _run(1, "push", "main", baza, "success", 1),
        _run(2, "pull_request", "g", czerwona, "failure", 2),
        _run(3, "pull_request", "g", naprawiona, "success", 3),
        _run(4, "push", "main", scalona, "failure", 4, koniec="06:00"),
        _run(5, "push", "main", scalona, "success", 5),
        _run(6, "push", "main", dalej, "success", 6, koniec="40"),
    ]
    odpowiedzi, pliki = _czerwony_run_2(runy)
    odpowiedzi |= {
        f"{REPO}/actions/runs/4/jobs?filter=latest&per_page=100": {"jobs": [{"id": 41, "name": "Mutation checks (2/3)", "conclusion": "failure"}]},
        f"{REPO}/actions/runs/3/artifacts?name=plan": {"artifacts": [{"id": 300, "expired": False}]},
    }
    pliki |= {
        f"{REPO}/actions/jobs/41/logs": b"WYKONANIE FAIL | skill:verify-b/ci\n",
        f"{REPO}/actions/artifacts/300/zip": _zip_planu({Podstawy.V0: (("verify-b/ci",), 250.0), Podstawy.NF: ((), 120.0), Podstawy.N0: ((), 120.0)}),
    }
    return repo, _GitHub(odpowiedzi, pliki)


def _czerwony_run_2(runy: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Odpowiedzi API okna 12.11 z ``runy``, w którym run PR 2 jest czerwony przez podstawę verify-a z kroków NF przy
    zielonym pytest."""

    odpowiedzi = {
        f"{REPO}/actions/workflows/ci.yml/runs?created=2026-11-12&per_page={api_actions.STRONA}&page=1": {"workflow_runs": runy},
        f"{REPO}/actions/runs/2/jobs?filter=latest&per_page=100": {
            "jobs": [{"id": 21, "name": "pytest (Python 3.13, 1/1)", "conclusion": "success"}, {"id": 22, "name": "Mutation checks (1/2)", "conclusion": "failure"}]
        },
        f"{REPO}/actions/runs/2/artifacts?name=plan": {"artifacts": [{"id": 200, "expired": False}]},
    }
    pliki = {
        f"{REPO}/actions/jobs/22/logs": "2026 WYKONANIE FAIL | pytest:tests/test_a.py, skill:verify-a/ci#1/2\n".encode(),
        f"{REPO}/actions/artifacts/200/zip": _zip_planu({Podstawy.V0: (("verify-a/ci",), 300.0), Podstawy.NF: (("verify-a/ci",), 200.0), Podstawy.N0: ((), 100.0)}),
    }
    return odpowiedzi, pliki


def test_zbieranie_laczy_runy_logi_cien_planow_i_commity_gita_a_ponowny_bieg_nie_pyta_githuba(tmp_path: Path, swiat: tuple[Path, _GitHub]) -> None:
    repo, github = swiat
    dzien = date(2026, 11, 12)

    rekordy = cien_podstaw.zbierz(api_actions.Api(tmp_path / "bieg", github), repo, dzien, dzien, date(2026, 12, 1), cien_podstaw.PROBKA)
    pytania = len(github.pytania)
    cien_podstaw.zbierz(api_actions.Api(tmp_path / "bieg", github), repo, dzien, dzien, date(2026, 12, 1), cien_podstaw.PROBKA)
    wynik = rozstrzygnij(rekordy)

    assert (_klucze(wynik.kandydaci), wynik.ucieczki, wynik.oszczednosc_min) == (("2 verify-a/ci",), ((4, "verify-b/ci"),), 100.0 / 2 * 2 / 60)
    assert (wynik.czerwien_min, _sciezki(rekordy.pr[0])) == (40.0, (".agents/skills/verify-a/drive.py",))
    assert len(github.pytania) == pytania


def test_wynik_z_zapisanych_rekordow_jest_tym_samym_co_z_githuba_a_audyt_liczy_przyczyny(
    tmp_path: Path, swiat: tuple[Path, _GitHub], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, github = swiat
    argumenty = ["--katalog", str(tmp_path / "bieg"), "--od", "2026-11-12", "--do", "2026-11-12"]
    (tmp_path / "audyt.json").write_text(json.dumps({"2 verify-a/ci": ["napęd verify-a"]}), encoding="utf-8")

    kod = cien_podstaw.main(argumenty, root=repo, github=github)
    z_githuba = capsys.readouterr().out.splitlines()
    cien_podstaw.main(["--rekordy", str(tmp_path / "bieg" / "rekordy.json")])
    z_rekordow = capsys.readouterr().out.splitlines()
    cien_podstaw.main(["--rekordy", str(tmp_path / "bieg" / "rekordy.json"), "--audyt", str(tmp_path / "audyt.json")])
    z_audytem = capsys.readouterr().out.splitlines()

    assert (kod, z_rekordow[-1], json.loads((tmp_path / "bieg" / "rekordy.json").read_text(encoding="utf-8"))["pr_runow"]) == (0, z_githuba[-1], 2)
    # Okno jednego dnia nie ma wyniku, bo progi liczą 14 dni.
    assert z_rekordow[-1] == (
        f"D1 | złapane przez NF: kandydaci 1 (wymaga audytu 0), niepoliczone 0, przyczyny po audycie brak audytu (--audyt); N0 wygrywa poniżej {X}"
        f" przyczyn | oszczędność N0 2 agent-min (próg {OSZCZEDNOSC_MIN:.0f}) | wynik: {Wynik.OKNO}"
    )
    assert "PRZYCZYNA 1/1 | napęd verify-a | 2 verify-a/ci" in z_audytem and "przyczyny po audycie 1;" in z_audytem[-1]


def test_kandydat_nf_ma_w_wyniku_dowod_do_audytu_pr_runy_z_adresami_i_zmiane_wlasnego_diffu_pr_pliku_naprawy_miedzy_glowami(
    tmp_path: Path, swiat: tuple[Path, _GitHub], capsys: pytest.CaptureFixture[str]
) -> None:
    """Naprawa w ``swiat`` dodaje plik w folderze verify-a, którego ``main`` nie zmienił, więc kandydat jest tylko do audytu:
    własny diff PR tego pliku jest przy czerwonej głowie pusty, a przy następnej dodaje jedną linię, a rekordy trzymają
    oba diffy w całości, z końcami linii, jakie drukuje git (na Windows plik z ``write_text`` ma w commicie ``\\r\\n``)."""

    repo, github = swiat
    baza, czerwona, naprawiona = (git(repo, "rev-parse", rewizja) for rewizja in ("g~2", "g~1", "g"))
    plik = ".agents/skills/verify-a/drive.py"

    cien_podstaw.main(["--katalog", str(tmp_path / "bieg"), "--od", "2026-11-12", "--do", "2026-11-12"], root=repo, github=github)
    linie = capsys.readouterr().out.splitlines()
    poczatek = linie.index("KANDYDAT NF 1/1 | 2 verify-a/ci | g, PR #1 | do audytu")
    zapisany = json.loads((tmp_path / "bieg" / "rekordy.json").read_text(encoding="utf-8"))["pr"][0]["naprawa"]["pliki"][0]

    # Blok kandydata kończy się na pierwszej linii bez wcięcia.
    assert linie[poczatek + 1 : poczatek + 8] == [
        f"  czerwony run 2 https://github.com/o/r/actions/runs/2 | padł krok verify-a/ci | głowa {czerwona[:12]}, baza {baza[:12]}",
        f"  następny run 3 https://github.com/o/r/actions/runs/3 | głowa {naprawiona[:12]}, baza {baza[:12]}",
        f"  plik {plik}",
        f"    git diff {baza[:12]}...{czerwona[:12]} -- {plik} | linii +/-: 0",
        f"    git diff {baza[:12]}...{naprawiona[:12]} -- {plik} | linii +/-: 1",
        "    linie +/- tylko przy czerwonej (-) albo tylko przy następnej (+): 1",
        "      + +X = 1",
    ] and not linie[poczatek + 8].startswith(" ")
    assert (zapisany["diff_czerwonej"], zapisany["diff_nastepnej"]) == (
        "",
        repo_gita.git(repo, "diff", "--no-ext-diff", "--no-color", f"{baza}...{naprawiona}", "--", plik),
    )


def _zadania(pytest_wynik: str, mutacje_wynik: str = "failure") -> dict[str, Any]:
    return {"jobs": [{"id": 21, "name": "pytest (Python 3.13, 1/1)", "conclusion": pytest_wynik}, {"id": 22, "name": "Mutation checks (1/2)", "conclusion": mutacje_wynik}]}


@pytest.mark.parametrize(
    ("wyniki", "zadania_2", "naglowek", "nastepny"),
    [
        (("failure", "cancelled", "success"), "success", "KANDYDAT NF 1/1 | 2 verify-a/ci | g, PR bez merge'a w oknie | do audytu", 4),
        (("cancelled", None, "success"), "cancelled",
         "KANDYDAT NF 1/1 | 2 verify-a/ci | g, PR bez merge'a w oknie | wymaga audytu: run anulowany, zanim pytest skończył: nie wiadomo, czy pytest by ją złapał", 4),
        (("cancelled", None, "success"), "success", "KANDYDAT NF 1/1 | 2 verify-a/ci | g, PR bez merge'a w oknie | do audytu", 4),
        (("failure", "cancelled", "cancelled"), "success",
         "NIEPOLICZONY, wymaga audytu | 2 verify-a/ci | g, PR bez merge'a w oknie | brak następnego runu gałęzi z wynikiem w oknie albo git nie zna"
         " jego głowy: naprawa mogła pójść inną gałęzią albo po oknie", None),
        (("failure", None, None), "success",
         "NIEPOLICZONY, wymaga audytu | 2 verify-a/ci | g, PR bez merge'a w oknie | brak następnego runu gałęzi z wynikiem w oknie albo git nie zna"
         " jego głowy: naprawa mogła pójść inną gałęzią albo po oknie", None),
        (("timed_out", None, "success"), "success", "KANDYDAT NF 1/1 | 2 verify-a/ci | g, PR bez merge'a w oknie | do audytu", 4),
    ],
    ids=["następny run anulowany przez push z naprawą", "czerwony run anulowany, zanim pytest skończył", "czerwony run anulowany po końcu pytest",
         "następne runy gałęzi tylko anulowane", "bez następnego runu w oknie", "czerwony run z przekroczonym czasem"],  # fmt: skip
)
def test_czerwony_run_anulowany_albo_z_przekroczonym_czasem_nie_ukrywa_porazki_kroku_nf(
    tmp_path: Path, wyniki: tuple[str | None, ...], zadania_2: str, naglowek: str, nastepny: int | None
) -> None:
    """Gałąź ``g``: czerwona głowa zmienia ``src/a.py``, druga dodaje plik w ``docs/``, trzecia naprawia folder verify-a;
    run ``n + 2`` biegnie na ``n``-tej z nich z wynikiem ``wyniki[n]`` (``None``: bez runu). Anulowany run nie ma
    naprawy z pushu, który go anulował, więc naprawa sięga następnego runu z wynikiem; czerwony run anulowany z padłym
    zadaniem Mutation checks, jak każdy run z wynikiem innym niż success (np. timed_out), jest porażką jak run z wynikiem
    failure, a bez następnego runu z wynikiem porażka stoi jako
    niepoliczona."""

    repo = repository(tmp_path / "repo", {"src/a.py": "A = 1\n", ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\n---\n"}, tools=())
    baza = commit(repo, "baza")
    git(repo, "checkout", "--quiet", "-b", "g")
    glowy = []
    for plik in ("src/a.py", "docs/d.md", ".agents/skills/verify-a/drive.py"):
        (repo / plik).parent.mkdir(parents=True, exist_ok=True)
        (repo / plik).write_text("ZMIANA = 1\n", encoding="utf-8")
        glowy.append(commit(repo, plik))
    runy = [_run(1, "push", "main", baza, "success", 1)]
    runy += [_run(n + 2, "pull_request", "g", glowa, wynik, n + 2) for n, (glowa, wynik) in enumerate(zip(glowy, wyniki, strict=True)) if wynik]
    odpowiedzi, pliki = _czerwony_run_2(runy)
    odpowiedzi |= {f"{REPO}/actions/runs/2/jobs?filter=latest&per_page=100": _zadania(zadania_2)}
    # Runy anulowane bez padłego zadania: zadania pytest i Mutation checks anulowane.
    odpowiedzi |= {f"{REPO}/actions/runs/{n}/jobs?filter=latest&per_page=100": _zadania("cancelled", "cancelled") for n in (3, 4)}
    dzien = date(2026, 11, 12)

    rekordy = cien_podstaw.zbierz(api_actions.Api(tmp_path / "bieg", _GitHub(odpowiedzi, pliki)), repo, dzien, dzien, date(2026, 12, 1), 0)
    linie = cien_podstaw.wypisz(rekordy, rozstrzygnij(rekordy))

    assert [linia for linia in linie if linia.startswith(("KANDYDAT", "NIEPOLICZONY"))] == [naglowek]
    assert (None if rekordy.pr[0].naprawa is None else rekordy.pr[0].naprawa.nastepna.run) == nastepny


def _przemianowanie_przez_main(droga: str) -> Callable[[Path], tuple[str, str, str]]:
    """``main`` przemianowuje ``src/a.py`` na ``src/b.py`` bez zmiany treści, a gałąź zmienia w nim funkcję ``b`` (albo
    tylko usuwa z niej linię) i folder verify-a, potem aktualizuje się ``droga`` (klucz ``PROBY_PRZEMIANOWANIA``):
    ``(main, czerwona, następna)``."""

    def stan(repo: Path) -> tuple[str, str, str]:
        a, b = "def a():\n    x = 1\n    return x", "def b():\n    y = 2\n    return y"
        (repo / "src/a.py").write_text(f"{a}\n\n{b}\n", encoding="utf-8")
        baza = commit(repo, "baza")
        git(repo, "mv", "src/a.py", "src/b.py")
        main = commit(repo, "main przemianowuje src/a.py na src/b.py")
        git(repo, "checkout", "--quiet", "-B", "g", baza)
        usuwa = droga.startswith("PR tylko usuwa linię")
        zmiana = b.replace("    y = 2\n", "") if usuwa else b.replace("2", "3")
        (repo / "src/a.py").write_text(f"{a}\n\n{zmiana}\n", encoding="utf-8")
        (repo / ".agents/skills/verify-a/drive.py").write_text("X = 1\n", encoding="utf-8")
        czerwona = commit(repo, "zmiana")
        if droga.endswith("poprawka, potem scalenie main"):
            poprawka = f"{a.replace('    x = 1\n', '')}\n\n{zmiana}\n" if usuwa else f"{a}\n\n{b.replace('2', '4')}\n"
            (repo / "src/a.py").write_text(poprawka, encoding="utf-8")
            commit(repo, "poprawka pod ścieżką sprzed przemianowania")
        if droga.endswith("scalenie main"):
            git(repo, "merge", "--quiet", "--no-edit", main)
        else:
            git(repo, "rebase", "--quiet", main)
        if droga == "rebase i poprawka":
            (repo / "src/b.py").write_text(f"{a}\n\n{b.replace('2', '4')}\n", encoding="utf-8")
            commit(repo, "poprawka")
        return main, czerwona, git(repo, "rev-parse", "HEAD")

    return stan


# Droga aktualizacji gałęzi po przemianowaniu jej pliku przez ``main`` → (naprawa, linie +/- własnego diffu PR przy
# czerwonej i następnej głowie, linie różnicy tych diffów w dowodzie); bez naprawy porażka nie liczy się.
PROBY_PRZEMIANOWANIA: dict[str, tuple[tuple[str, ...], tuple[int, int], list[str]]] = {
    "rebase": ((), (0, 0), []),
    "scalenie main": ((), (0, 0), []),
    "rebase i poprawka": (("src/b.py",), (2, 2), ["- +    y = 3", "+ +    y = 4"]),
    "poprawka, potem scalenie main": (("src/b.py",), (2, 2), ["- +    y = 3", "+ +    y = 4"]),
    "PR tylko usuwa linię, poprawka, potem scalenie main": (("src/b.py",), (1, 2), ["+ -    x = 1"]),
}


@pytest.mark.parametrize("droga", list(PROBY_PRZEMIANOWANIA))
def test_plik_przemianowany_przez_main_to_dla_naprawy_i_dowodu_ten_sam_plik_pod_sciezka_sprzed_przemianowania(tmp_path: Path, droga: str) -> None:
    """Rebase i scalenie ``main``, który przemianował plik gałęzi, zostawiają własną zmianę PR (#2178 r3, D2), a poprawka
    po rebase'ie albo pod starą ścieżką przed scaleniem ``main`` (#2195 r1, także gdy PR w tym pliku tylko usuwa linie)
    jest naprawą: porażka jest kandydatem, a dowód czyta własny diff czerwonej głowy pod ścieżką sprzed przemianowania
    i następnej pod nową."""

    naprawa, (linii_czerwonej, linii_nastepnej), roznica = PROBY_PRZEMIANOWANIA[droga]
    rekordy = _rekordy_luki(tmp_path, _przemianowanie_przez_main(droga))
    wynik = rozstrzygnij(rekordy)
    linie = cien_podstaw.wypisz(rekordy, wynik)

    assert _sciezki(rekordy.pr[0]) == naprawa
    if not naprawa:
        return
    assert len(wynik.kandydaci) + len(wynik.niepoliczone) == sum(len(run.padle) for run in rekordy.pr)
    assert rekordy.pr[0].naprawa is not None
    czerwona, nastepna = rekordy.pr[0].naprawa.czerwona, rekordy.pr[0].naprawa.nastepna
    poczatek = linie.index("  plik src/b.py | przy czerwonej głowie src/a.py: main przemianował go między bazami głów")
    assert linie[poczatek + 1 : poczatek + 4 + len(roznica)] == [
        f"    git diff {czerwona.baza[:12]}...{czerwona.sha[:12]} -- src/a.py | linii +/-: {linii_czerwonej}",
        f"    git diff {nastepna.baza[:12]}...{nastepna.sha[:12]} -- src/b.py | linii +/-: {linii_nastepnej}",
        f"    linie +/- tylko przy czerwonej (-) albo tylko przy następnej (+): {len(roznica)}",
        *(f"      {linia}" for linia in roznica),
    ]


def _konflikt(repo: Path, *argumenty: str) -> None:
    """``git <argumenty>`` (rebase albo scalenie ``main``) staje na konflikcie w ``src/a.py``, więc próbka rozstrzyga
    prawdziwy konflikt."""

    with pytest.raises(subprocess.CalledProcessError):
        git(repo, *argumenty)
    assert git(repo, "diff", "--name-only", "--diff-filter=U") == "src/a.py"


@pytest.mark.parametrize(
    ("glowy", "naprawa"),
    [
        (("na bazie", "rebase"), ()),
        (("rebase", "na bazie"), ()),
        (("na bazie", "main scalony"), ()),
        (("na bazie", "main scalony z nową linią"), ()),
        (("na bazie", "main scalony ze zmianą pliku z main"), ()),
        (("na bazie", "rebase z poprawką"), ("src/a.py",)),
        (("na bazie", "main scalony i poprawka"), ("src/a.py",)),
        (("na bazie", "rebase i przestawiona linia"), (".agents/skills/verify-a/notatki.md",)),
    ],
    ids=["rebase z konfliktem", "rebase na starszą bazę", "main scalony z konfliktem", "rozstrzygnięcie łączące linie w commicie scalenia",
         "plik z main zmieniony w commicie scalenia", "rebase z poprawką w rozstrzygnięciu konfliktu", "main scalony, potem commit poprawki",
         "rebase, potem przestawiona linia gałęzi"],  # fmt: skip
)
def test_naprawa_to_zmiana_wlasnej_zmiany_pr_commitem_galezi_a_nie_rebase_scalenie_main_ani_rozstrzygniecie_konfliktu(
    tmp_path: Path, glowy: tuple[str, str], naprawa: tuple[str, ...]
) -> None:
    """Gałąź zmienia folder skilla verify-a i linię 6 ``src/a.py``, a ``main`` po jej bazie zmienia ``src/``, folder
    verify-a (także wstawia linię do pliku, który zmienia gałąź) i linie 5 i 6 ``src/a.py``, więc rebase i scalenie
    ``main`` stają na prawdziwym konflikcie. Rozstrzygnięcie, które zostawia linię gałęzi, rebase'em, scaleniem ``main``
    albo cofnięciem na starszą bazę, naprawą nie jest, choć diff między głowami zmienia oba foldery, a commit rebase'u
    zmienia ``src/a.py``; zmiana tylko w commicie scalenia (nowa linia z linii ``main`` i gałęzi, plik z ``main``
    wygenerowany na nowo) też nie. Poprawka linii gałęzi jest naprawą w rozstrzygnięciu rebase'u i w commicie po
    scaleniu ``main``, a przestawienie linii gałęzi w pliku, który zmienił ``main``, w commicie po rebase'ie."""

    linie = [f"{n}\n" for n in range(1, 11)]
    notatki = ".agents/skills/verify-a/notatki.md"

    def a_py(piata: str, szosta: str) -> str:
        return "".join([*linie[:4], piata, szosta, *linie[6:]])

    repo = repository(tmp_path / "repo", {"src/a.py": "".join(linie), ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\n---\n", notatki: "".join(linie)}, tools=())
    baza = commit(repo, "baza")
    (repo / "src/b.py").write_text("B = 1\n", encoding="utf-8")
    (repo / ".agents/skills/verify-a/SKILL.md").write_text("---\nname: verify-a\ndescription: d\n---\n", encoding="utf-8")
    (repo / notatki).write_text("".join(["1 z main\n", *linie[1:3], "3a z main\n", *linie[3:]]), encoding="utf-8")
    (repo / "src/a.py").write_text(a_py("5 z main\n", "6 z main\n"), encoding="utf-8")
    main = commit(repo, "main dalej")
    git(repo, "checkout", "--quiet", baza)
    (repo / ".agents/skills/verify-a/drive.py").write_text("X = 1\n", encoding="utf-8")
    (repo / notatki).write_text("".join([*linie[:-1], "10 z gałęzi\n"]), encoding="utf-8")
    (repo / "src/a.py").write_text(a_py("5\n", "6 z gałęzi\n"), encoding="utf-8")
    na_bazie = commit(repo, "zmiana")
    sha = {"na bazie": na_bazie}
    for nazwa, szosta in (("rebase", "6 z gałęzi\n"), ("rebase z poprawką", "6 poprawione\n")):
        git(repo, "checkout", "--quiet", "-B", "g", na_bazie)
        _konflikt(repo, "rebase", main)
        (repo / "src/a.py").write_text(a_py("5 z main\n", szosta), encoding="utf-8")
        git(repo, "add", "--all")
        git(repo, "commit", "--quiet", "--no-edit")
        git(repo, "rebase", "--continue")
        sha[nazwa] = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "--quiet", "--detach", sha["rebase"])
    (repo / notatki).write_text("".join(["1 z main\n", *linie[1:3], "3a z main\n", *linie[3:8], "10 z gałęzi\n", linie[8]]), encoding="utf-8")
    sha["rebase i przestawiona linia"] = commit(repo, "przestawienie")
    for nazwa, szosta, b in (("main scalony", "6 z gałęzi\n", "B = 1\n"), ("main scalony z nową linią", "6 z main i gałęzi\n", "B = 1\n"),
                             ("main scalony ze zmianą pliku z main", "6 z gałęzi\n", "B = 2\n")):  # fmt: skip
        git(repo, "checkout", "--quiet", "--detach", na_bazie)
        _konflikt(repo, "merge", "--no-ff", "--no-commit", main)
        (repo / "src/a.py").write_text(a_py("5 z main\n", szosta), encoding="utf-8")
        (repo / "src/b.py").write_text(b, encoding="utf-8")
        sha[nazwa] = commit(repo, "Merge branch main")
    git(repo, "checkout", "--quiet", sha["main scalony"])
    (repo / "src/a.py").write_text(a_py("5 z main\n", "6 poprawione\n"), encoding="utf-8")
    sha["main scalony i poprawka"] = commit(repo, "poprawka")
    runy = [_run(1, "push", "main", baza, "success", 1), _run(2, "pull_request", "g", sha[glowy[0]], "failure", 2),
            _run(3, "push", "main", main, "success", 3), _run(4, "pull_request", "g", sha[glowy[1]], "success", 4)]  # fmt: skip
    dzien = date(2026, 11, 12)

    rekordy = cien_podstaw.zbierz(api_actions.Api(tmp_path / "bieg", _GitHub(*_czerwony_run_2(runy))), repo, dzien, dzien, date(2026, 12, 1), 0)

    assert (_sciezki(rekordy.pr[0]), _klucze(rozstrzygnij(rekordy).kandydaci)) == (naprawa, ("2 verify-a/ci",) if naprawa else ())


def _zamiana_funkcji_przez_main(repo: Path, rozstrzygnij_konflikt: bool) -> tuple[str, str, str]:
    """``main`` przestawia funkcje ``src/a.py`` (zamienia dwie, a z konfliktem przenosi zmienioną pod trzecią), gałąź
    zmienia linię w funkcji i folder verify-a, a rebase zostawia jej zmianę w funkcji na nowym miejscu: ``(main, czerwona,
    następna)``."""

    def funkcje(*ciala: str) -> str:
        return "\n\n".join(ciala) + "\n"

    a, b, b_pr = "def a():\n    x = 1\n    return x", "def b():\n    y = 2\n    return y", "def b():\n    y = 3\n    return y"
    c = "def c():\n    z = 4\n    w = 5\n    v = 6\n    return z + w + v"
    przed, po = ((a, b), (b, a)) if not rozstrzygnij_konflikt else ((a, b, c), (a, c, b))
    (repo / "src/a.py").write_text(funkcje(*przed), encoding="utf-8")
    baza = commit(repo, "baza")
    (repo / "src/a.py").write_text(funkcje(*po), encoding="utf-8")
    main = commit(repo, "main przestawia funkcje")
    git(repo, "checkout", "--quiet", "-B", "g", baza)
    (repo / "src/a.py").write_text(funkcje(*(b_pr if f == b else f for f in przed)), encoding="utf-8")
    (repo / ".agents/skills/verify-a/drive.py").write_text("X = 1\n", encoding="utf-8")
    czerwona = commit(repo, "zmiana")
    if rozstrzygnij_konflikt:
        _konflikt(repo, "rebase", main)
        (repo / "src/a.py").write_text(funkcje(*(b_pr if f == b else f for f in po)), encoding="utf-8")
        git(repo, "add", "--all")
        git(repo, "-c", "core.editor=true", "rebase", "--continue")
    else:
        git(repo, "rebase", "--quiet", main)
    return main, czerwona, git(repo, "rev-parse", "HEAD")


def _usuniety_zly_commit(repo: Path) -> tuple[str, str, str]:
    """Gałąź ma trzy commity, z których środkowy psuje folder verify-a, a naprawa usuwa go rebase'em (drop), bez nowej
    bazy: ``(main, czerwona, następna)``."""

    baza = commit(repo, "baza")
    git(repo, "checkout", "--quiet", "-B", "g", baza)
    for plik in ("src/a.py", ".agents/skills/verify-a/drive.py", "src/c.py"):
        (repo / plik).write_text("ZMIANA = 1\n", encoding="utf-8")
        commit(repo, plik)
    czerwona = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "--quiet", "--detach", "g~2")
    git(repo, "cherry-pick", czerwona)
    return baza, czerwona, git(repo, "rev-parse", "HEAD")


# Znane luki reguły naprawy (ADR 0034): klasa mechanizmu, który się myli, i postać → (stan gita, poprawna naprawa).
ZNANE_LUKI: dict[str, tuple[Callable[[Path], tuple[str, str, str]], tuple[str, ...]]] = {
    "reguła treści bierze linie przestawione przez main za zmianę własnej zmiany PR: main zamienia dwie funkcje, rebase bez konfliktu": (
        lambda repo: _zamiana_funkcji_przez_main(repo, rozstrzygnij_konflikt=False),
        (),
    ),
    "reguła treści bierze linie przestawione przez main za zmianę własnej zmiany PR: main przenosi zmienioną funkcję, rebase z konfliktem": (
        lambda repo: _zamiana_funkcji_przez_main(repo, rozstrzygnij_konflikt=True),
        (),
    ),
    "kandydaci to pliki commitów nowych od czerwonej głowy: naprawa usuwa zły commit rebase'em (drop)": (
        _usuniety_zly_commit,
        (".agents/skills/verify-a/drive.py",),
    ),
}


def _rekordy_luki(katalog: Path, stan: Callable[[Path], tuple[str, str, str]]) -> Rekordy:
    """Rekordy okna z czerwonym runem PR (padła podstawa verify-a z NF) na czerwonej głowie stanu i następnym runem."""

    repo = repository(katalog / "repo", {"src/a.py": "A = 1\n", ".agents/skills/verify-a/SKILL.md": "---\nname: verify-a\n---\n"}, tools=())
    main, czerwona, nastepna = stan(repo)
    baza = git(repo, "merge-base", main, czerwona)
    runy = [_run(1, "push", "main", baza, "success", 1), _run(2, "pull_request", "g", czerwona, "failure", 2),
            _run(3, "push", "main", main, "success", 3), _run(4, "pull_request", "g", nastepna, "success", 4)]  # fmt: skip
    dzien = date(2026, 11, 12)
    return cien_podstaw.zbierz(api_actions.Api(katalog / "bieg", _GitHub(*_czerwony_run_2(runy))), repo, dzien, dzien, date(2026, 12, 1), 0)


def test_znane_luki_reguly_naprawy_przechodza_przez_jej_wybor_kandydatow(tmp_path: Path) -> None:
    zgloszenia: dict[str, list[str]] = {}
    for numer, (opis, (stan, poprawna)) in enumerate(ZNANE_LUKI.items()):
        naprawa = _sciezki(_rekordy_luki(tmp_path / str(numer), stan).pr[0])
        zgloszenia[opis] = [f"naprawa {naprawa} jest poprawna"] if naprawa == poprawna else []

    assert_znane_luki(zgloszenia, "tests/test_cien_podstaw.py (ZNANE_LUKI)")


def test_porazka_kroku_nf_z_glowa_nastepnego_runu_nieznana_gitowi_jest_niepoliczona_do_audytu(tmp_path: Path) -> None:
    """Głowy następnego runu nie ma w checkoucie ani na ``origin`` (np. gałąź usunięta po force-pushu), więc naprawy nie
    da się policzyć, a porażka stoi w wyniku zamiast zniknąć."""

    def stan(repo: Path) -> tuple[str, str, str]:
        main, czerwona, _ = _usuniety_zly_commit(repo)
        return main, czerwona, "f" * 40

    rekordy = _rekordy_luki(tmp_path, stan)

    assert (rekordy.pr[0].naprawa, _klucze(rozstrzygnij(rekordy).niepoliczone)) == (None, ("2 verify-a/ci",))


@pytest.mark.parametrize("opis", list(ZNANE_LUKI))
def test_znana_luka_reguly_naprawy_wymaga_audytu_w_wyniku(tmp_path: Path, opis: str) -> None:
    """Postać, w której reguła naprawy się myli, stoi w wyniku jako kandydat albo niepoliczony z „wymaga audytu”, więc
    audyt rozstrzyga ją zamiast reguły."""

    rekordy = _rekordy_luki(tmp_path, ZNANE_LUKI[opis][0])

    linie = [linia for linia in cien_podstaw.wypisz(rekordy, rozstrzygnij(rekordy)) if linia.startswith(("KANDYDAT NF", "NIEPOLICZONY"))]

    assert len(linie) == 1 and "| 2 verify-a/ci | g, " in linie[0] and "wymaga audytu" in linie[0], linie
