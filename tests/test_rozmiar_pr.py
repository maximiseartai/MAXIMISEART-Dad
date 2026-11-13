"""Etykieta rozmiaru PR (``tools/ci/rozmiar_pr.py``, workflow ``rozmiar-pr.yml``): progi z t3code, efektywne linie od
bazy scalenia, pliki testów pominięte w PR mieszanym, a w PR z samymi testami liczone, i jedna etykieta ``size:*`` na PR.
Licznik szopy (ADR 0034): grupę pliku daje reguła katalogu, a lista dwóch szop tylko wyjątki od niej; licznik drukuje linie
maszynerii procesu i weryfikacji produktu osobno, a PR z nowymi liniami maszynerii bez większego usunięcia albo ze zmianą
strażnika dostaje etykietę zgody, którą zdejmuje komentarz ``ZGODA SZOPA`` konta z prawem ``admin``. Przeniesienia kodu
między grupami licznik nie rozpoznaje: jego postacie są próbkami ``ZNANE_LUKI``."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import re
from typing import Any, Final

import pytest

from tests.fixtures.git_repo import commit, git
from tests.fixtures.znane_luki import assert_znane_luki

import rozmiar_pr
from github import REPO


@pytest.mark.parametrize(
    ("linie", "nazwa"),
    [
        (0, "size:XS"),
        (9, "size:XS"),
        (10, "size:S"),
        (29, "size:S"),
        (30, "size:M"),
        (99, "size:M"),
        (100, "size:L"),
        (499, "size:L"),
        (500, "size:XL"),
        (999, "size:XL"),
        (1000, "size:XXL"),
    ],
)
def test_etykieta_rozmiaru_z_progow_xs_10_s_30_m_100_l_500_xl_1000_xxl(
    linie: int, nazwa: str
) -> None:
    assert rozmiar_pr.etykieta(linie).nazwa == nazwa


def _linie(liczba: int, prefiks: str = "x") -> str:
    return "".join(f"{prefiks} = {numer}\n" for numer in range(liczba))


def _zapisz(repo: Path, pliki: Mapping[str, str]) -> None:
    for nazwa, tresc in pliki.items():
        (repo / nazwa).parent.mkdir(parents=True, exist_ok=True)
        (repo / nazwa).write_text(tresc, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet", "--initial-branch", "main")
    _zapisz(tmp_path, {"src/stary.py": _linie(20), "tests/test_stary.py": _linie(5)})
    commit(tmp_path, "baza")
    git(tmp_path, "switch", "--quiet", "--create", "pr")
    return tmp_path


def test_pr_mieszany_liczy_linie_poza_testami_od_bazy_scalenia_bez_zmian_bialych_znakow(
    repo: Path,
) -> None:
    _zapisz(
        repo,
        {
            "src/nowy.py": _linie(12),
            # Same wcięcia i puste linie nie są efektywną zmianą.
            "src/stary.py": "".join(
                f"    {linia}\n\n" for linia in _linie(20).splitlines()
            ),
            "tests/test_nowy.py": _linie(200),
            "tests/expected/rozmiar.txt": _linie(10),
            "tools/lib/test_pomocnik.py": _linie(30),
            "frontend/src/karta.test.tsx": _linie(40),
        },
    )
    commit(repo, "pr")
    git(repo, "switch", "--quiet", "main")
    _zapisz(repo, {"src/main_po_rozwidleniu.py": _linie(700)})
    commit(repo, "main poszedł dalej")

    rozmiar = rozmiar_pr.zmierz(repo, "main", "pr")

    assert (rozmiar, rozmiar.etykieta.nazwa) == (
        rozmiar_pr.Rozmiar(bez_testow=12, testow=280),
        "size:S",
    )


def test_pr_z_samymi_testami_liczy_linie_testow(repo: Path) -> None:
    _zapisz(repo, {"tests/test_stary.py": _linie(5) + _linie(40, "y")})
    commit(repo, "same testy")

    rozmiar = rozmiar_pr.zmierz(repo, "main", "pr")

    assert (rozmiar, rozmiar.etykieta.nazwa) == (
        rozmiar_pr.Rozmiar(bez_testow=0, testow=40),
        "size:M",
    )


class _GitHub:
    def __init__(
        self,
        w_repo: list[dict[str, Any]],
        na_pr: list[str],
        komentarze: Sequence[dict[str, Any]] = (),
        prawa: Sequence[tuple[str, str]] = (),
    ) -> None:
        self.odpowiedzi: dict[str, Any] = {
            f"{REPO}/labels": w_repo,
            f"{REPO}/issues/7/labels": [{"name": nazwa} for nazwa in na_pr],
            f"{REPO}/issues/7/comments": list(komentarze),
            **{f"{REPO}/collaborators/{login}/permission": {"permission": prawo} for login, prawo in prawa},
        }
        self.wyslane: list[tuple[str, str, Mapping[str, object]]] = []

    def json(self, sciezka: str) -> Any:
        sciezka, _, zapytanie = sciezka.partition("?")
        return self.odpowiedzi[sciezka] if not zapytanie or zapytanie.endswith("page=1") else []

    def bajty(self, sciezka: str) -> bytes:
        raise AssertionError(sciezka)

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> Any:
        self.wyslane.append((metoda, sciezka, tresc))
        return {}


def test_nowa_etykieta_rozmiaru_zastepuje_stara_a_inne_etykiety_zostaja() -> None:
    m = rozmiar_pr.etykieta(50)
    github = _GitHub(
        w_repo=[
            {"name": "size:L", "color": "fe7d37", "description": "x"},
            {"name": "bug", "color": "000000"},
        ],
        na_pr=["size:L", "bug"],
    )

    linie = rozmiar_pr.nadaj(github, 7, m)

    assert github.wyslane == [
        (
            "POST",
            f"{REPO}/labels",
            {"name": "size:M", "color": m.kolor, "description": m.opis},
        ),
        ("DELETE", f"{REPO}/issues/7/labels/size%3AL", {}),
        ("POST", f"{REPO}/issues/7/labels", {"labels": ["size:M"]}),
    ]
    assert linie == [
        "założona etykieta size:M",
        "zdjęta size:L z #7",
        "nadana size:M #7",
    ]


def test_pr_z_wlasciwa_etykieta_nie_dostaje_zadnej_zmiany() -> None:
    s = rozmiar_pr.etykieta(10)
    github = _GitHub(
        w_repo=[{"name": s.nazwa, "color": s.kolor, "description": s.opis}],
        na_pr=[s.nazwa],
    )

    assert (rozmiar_pr.nadaj(github, 7, s), github.wyslane) == ([], [])


def test_etykieta_z_innym_opisem_albo_kolorem_dostaje_opis_i_kolor_progu() -> None:
    s = rozmiar_pr.etykieta(10)
    github = _GitHub(
        w_repo=[{"name": s.nazwa, "color": "ffffff", "description": None}],
        na_pr=[s.nazwa],
    )

    linie = rozmiar_pr.nadaj(github, 7, s)

    assert (linie, github.wyslane) == (
        ["poprawiona etykieta size:S"],
        [
            (
                "PATCH",
                f"{REPO}/labels/size%3AS",
                {"color": s.kolor, "description": s.opis},
            )
        ],
    )


_LISTA = """[weryfikacja]
"tools/lib/atrapa.py" = []
"tools/lib/atrapy/" = []

[maszyneria]
"tools/bramka.py" = ["tests/test_bramka.py"]
"""
# HTML renderera GitHuba (``gh api markdown``, gfm) dla treści komentarzy testu.
_HTML = {
    "ZGODA SZOPA": '<p dir="auto">ZGODA SZOPA</p>\n',
    "Ok.\n\n- ZGODA SZOPA": '<p dir="auto">Ok.</p>\n<ul dir="auto">\n<li>ZGODA SZOPA</li>\n</ul>\n',
    "Zgoda w kodzie:\n\n```\nZGODA SZOPA\n```": (
        '<p dir="auto">Zgoda w kodzie:</p>\n<pre class="notranslate"><code class="notranslate">ZGODA SZOPA\n</code></pre>\n'
    ),
}


def _repo_szopy(katalog: Path) -> Path:
    """Repozytorium z listą ``_LISTA`` na gałęzi ``main`` i gałęzią ``pr`` z niej."""

    katalog.mkdir(exist_ok=True)
    git(katalog, "init", "--quiet", "--initial-branch", "main")
    _zapisz(
        katalog,
        {
            "src/stary.py": _linie(20),
            "tests/test_stary.py": _linie(5),
            "tools/bramka.py": _linie(30),
            "tests/test_bramka.py": _linie(10),
            "tools/lib/atrapa.py": _linie(10),
            "tools/lib/atrapy/stara.py": _linie(10),
            "tools/inna.py": _linie(60),
            rozmiar_pr.LISTA: _LISTA,
            "tools/ci/rozmiar_pr.py": _linie(10),
            ".github/workflows/rozmiar-pr.yml": _linie(10),
        },
    )
    commit(katalog, "baza")
    git(katalog, "switch", "--quiet", "--create", "pr")
    return katalog


@pytest.fixture
def szopa(tmp_path: Path) -> Path:
    return _repo_szopy(tmp_path)


def _przenies(repo: Path, stara: str, nowa: str, tresc: str | None = None) -> None:
    """Plik ``stara`` znika, a pod ``nowa`` stoi jego treść albo ``tresc``."""

    _zapisz(repo, {nowa: (repo / stara).read_text(encoding="utf-8") if tresc is None else tresc})
    (repo / stara).unlink()


def _licz(repo: Path, github: _GitHub) -> tuple[list[str], list[tuple[str, str, Mapping[str, object]]]]:
    """Linie licznika szopy i wywołania GitHuba dla etykiety zgody, bez etykiety rozmiaru."""

    linie = rozmiar_pr.licz(repo, "main", "pr", 7, github, _HTML.__getitem__)
    zgody = [wywolanie for wywolanie in github.wyslane if "ZGODA" in wywolanie[1] or "ZGODA" in str(wywolanie[2])]
    return [linia for linia in linie if linia.startswith("SZOPA")], zgody


def _nadana(linia: str) -> tuple[list[str], list[tuple[str, str, Mapping[str, object]]]]:
    """Wynik ``_licz`` PR bez etykiety zgody, któremu licznik drukuje ``linia`` i nadaje etykietę zgody."""

    zgoda = rozmiar_pr.ZGODA
    return (
        [linia, f"SZOPA | założona etykieta {zgoda.nazwa}", f"SZOPA | nadana {zgoda.nazwa} #7"],
        [
            ("POST", f"{REPO}/labels", {"name": zgoda.nazwa, "color": zgoda.kolor, "description": zgoda.opis}),
            ("POST", f"{REPO}/issues/7/labels", {"labels": [zgoda.nazwa]}),
        ],
    )


def test_pr_bez_linii_maszynerii_procesu_nie_wymaga_zgody_choc_zmienia_produkt_weryfikacje_i_proze(szopa: Path) -> None:
    _zapisz(
        szopa,
        {
            "src/stary.py": _linie(35),
            "tests/test_nowy.py": _linie(40),
            "tools/lib/atrapa.py": _linie(16),
            "tools/lib/atrapy/nowa.py": _linie(7),
            "tools/OPIS.md": _linie(50),
        },
    )
    commit(szopa, "produkt")

    assert _licz(szopa, _GitHub(w_repo=[], na_pr=[])) == (
        [
            "SZOPA | #7 | maszyneria procesu z testami +0 -0, weryfikacja produktu z testami +13 -0, testy zachowania src / src 45/35 = 1,29, testy szopy / src 10/35 = 0,29"
            " | bez nowych linii maszynerii procesu"
        ],
        [],
    )


def test_pr_ktory_usuwa_wiecej_linii_maszynerii_niz_dodaje_traci_etykiete_zgody(szopa: Path) -> None:
    # Nowy plik spod tools/ bez wpisu na liście ma grupę maszyneria z reguły katalogu.
    _zapisz(szopa, {"tools/bramka.py": _linie(18), "tools/nowa.py": _linie(5)})
    commit(szopa, "mniej maszynerii")

    assert _licz(szopa, _GitHub(w_repo=[], na_pr=[rozmiar_pr.ZGODA.nazwa])) == (
        [
            "SZOPA | #7 | maszyneria procesu z testami +5 -12, weryfikacja produktu z testami +0 -0, testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50"
            " | usuwa więcej linii maszynerii procesu, niż dodaje",
            "SZOPA | zdjęta wymaga ZGODA SZOPA z #7",
        ],
        [("DELETE", f"{REPO}/issues/7/labels/wymaga%20ZGODA%20SZOPA", {})],
    )


def test_pr_ktory_dodaje_tyle_linii_maszynerii_z_testami_ile_usuwa_wymaga_zgody(szopa: Path) -> None:
    _zapisz(szopa, {"tools/bramka.py": _linie(22), "tests/test_bramka.py": _linie(10) + _linie(8, "y")})
    commit(szopa, "tyle samo maszynerii")

    assert _licz(szopa, _GitHub(w_repo=[], na_pr=[])) == _nadana(
        "SZOPA | #7 | maszyneria procesu z testami +8 -8, weryfikacja produktu z testami +0 -0, testy zachowania src / src 5/20 = 0,25, testy szopy / src 18/20 = 0,90"
        " | wymaga ZGODA SZOPA"
    )


def test_przeniesienie_pliku_maszynerii_do_weryfikacji_widac_w_liczbach_obu_grup(szopa: Path) -> None:
    # Licznik nie rozpoznaje przeniesienia (granica w docstringu licznika), więc recenzent widzi je w liczbach grup.
    _przenies(szopa, "tools/inna.py", "tools/lib/atrapy/inna.py")
    commit(szopa, "maszyneria do weryfikacji")

    assert _licz(szopa, _GitHub(w_repo=[], na_pr=[])) == (
        [
            "SZOPA | #7 | maszyneria procesu z testami +0 -60, weryfikacja produktu z testami +60 -0"
            ", testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50 | bez nowych linii maszynerii procesu"
        ],
        [],
    )


def test_pr_z_nowymi_liniami_maszynerii_i_przeniesieniem_jej_pliku_pod_nowy_wpis_listy_wymaga_zgody(szopa: Path) -> None:
    # Przegląd #1646 r1, W1: wpis listy przenosi plik do weryfikacji, a zmiana listy to zmiana strażnika.
    _zapisz(szopa, {"tools/bramka.py": _linie(30) + _linie(40, "y")})
    _przenies(szopa, "tools/inna.py", "tools/inna_w.py")
    _zapisz(szopa, {rozmiar_pr.LISTA: _LISTA.replace('"tools/lib/atrapy/" = []', '"tools/lib/atrapy/" = []\n"tools/inna_w.py" = []')})
    commit(szopa, "nowa maszyneria i przeniesienie pod nowy wpis")

    assert _licz(szopa, _GitHub(w_repo=[], na_pr=[])) == _nadana(
        "SZOPA | #7 | maszyneria procesu z testami +100 -60, weryfikacja produktu z testami +0 -0"
        ", testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50, zmienia strażnika tools/lib/szopa.toml"
        " | wymaga ZGODA SZOPA"
    )


def test_pr_ktory_zmienia_tylko_liste_wymaga_zgody_a_nastepny_pr_liczy_pliki_wedlug_przyjetej_listy(szopa: Path) -> None:
    # Lista głowy nie zmienia grup PR, który ją zmienia, więc zgoda przypada na zmianę listy (przegląd #1646 r1, W2).
    _zapisz(
        szopa,
        {rozmiar_pr.LISTA: '[weryfikacja]\n"tools/lib/atrapa.py" = []\n"tools/lib/atrapy/" = []\n"tools/bramka.py" = ["tests/test_bramka.py"]\n'},
    )
    commit(szopa, "bramka w weryfikacji")

    zmiana_listy = _licz(szopa, _GitHub(w_repo=[], na_pr=[]))
    git(szopa, "branch", "--force", "main", "pr")
    _zapisz(szopa, {"tools/bramka.py": _linie(30) + _linie(40, "y")})
    commit(szopa, "więcej bramki")

    assert (zmiana_listy, _licz(szopa, _GitHub(w_repo=[], na_pr=[]))) == (
        _nadana(
            "SZOPA | #7 | maszyneria procesu z testami +0 -0, weryfikacja produktu z testami +0 -0, testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50"
            ", zmienia strażnika tools/lib/szopa.toml | wymaga ZGODA SZOPA"
        ),
        (
            [
                "SZOPA | #7 | maszyneria procesu z testami +0 -0, weryfikacja produktu z testami +40 -0, testy zachowania src / src 5/20 = 0,25"
                ", testy szopy / src 10/20 = 0,50 | bez nowych linii maszynerii procesu"
            ],
            [],
        ),
    )


@pytest.mark.parametrize(
    ("sciezka", "tresc", "liczby"),
    [
        (rozmiar_pr.LISTA, _LISTA.replace('"tools/lib/atrapa.py" = []\n', ""), "+0 -0"),
        ("tools/ci/rozmiar_pr.py", _linie(9), "+0 -1"),
        (".github/workflows/rozmiar-pr.yml", _linie(9), "+0 -0"),
    ],
    ids=["lista", "licznik", "workflow"],
)
def test_pr_ktory_zmienia_straznika_bez_nowych_linii_maszynerii_wymaga_zgody(szopa: Path, sciezka: str, tresc: str, liczby: str) -> None:
    _zapisz(szopa, {sciezka: tresc})
    commit(szopa, "strażnik bez jednej linii")

    assert _licz(szopa, _GitHub(w_repo=[], na_pr=[])) == _nadana(
        f"SZOPA | #7 | maszyneria procesu z testami {liczby}, weryfikacja produktu z testami +0 -0, testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50"
        f", zmienia strażnika {sciezka} | wymaga ZGODA SZOPA"
    )


def test_nowe_pliki_testow_narzedzi_i_skilli_bez_wpisu_na_liscie_biora_grupe_z_reguly_katalogu(szopa: Path) -> None:
    # Testy: produkt; tools/: maszyneria; skill verify-*: weryfikacja; inny skill: maszyneria; docs/: poza szopą.
    _zapisz(
        szopa,
        {
            "tests/test_cos.py": _linie(7),
            "tools/lib/cos.py": _linie(4),
            ".agents/skills/verify-cos/scripts/cos.py": _linie(9),
            ".agents/skills/pr/scripts/cos.py": _linie(2),
            "docs/cos.py": _linie(6),
        },
    )
    commit(szopa, "nowe pliki bez wpisu")

    linie, _ = _licz(szopa, _GitHub(w_repo=[], na_pr=[]))

    assert linie[0] == (
        "SZOPA | #7 | maszyneria procesu z testami +6 -0, weryfikacja produktu z testami +9 -0, testy zachowania src / src 12/20 = 0,60, testy szopy / src 10/20 = 0,50"
        " | wymaga ZGODA SZOPA"
    )


def _nowe_linie_maszynerii(repo: Path) -> None:
    _zapisz(repo, {"tools/bramka.py": _linie(30) + _linie(40, "y")})


def _git_mv_do_katalogu_weryfikacji(repo: Path) -> None:
    _nowe_linie_maszynerii(repo)
    git(repo, "mv", "tools/inna.py", "tools/lib/atrapy/inna.py")


def _git_mv_do_skilla_verify(repo: Path) -> None:
    _nowe_linie_maszynerii(repo)
    (repo / ".agents/skills/verify-cos").mkdir(parents=True)
    git(repo, "mv", "tools/inna.py", ".agents/skills/verify-cos/inna.py")


def _git_mv_poza_szope(repo: Path) -> None:
    _nowe_linie_maszynerii(repo)
    (repo / ".github/scripts").mkdir(parents=True)
    git(repo, "mv", "tools/inna.py", ".github/scripts/inna.py")


def _kopia_do_katalogu_weryfikacji_z_importem_w_starym_pliku(repo: Path) -> None:
    _nowe_linie_maszynerii(repo)
    _zapisz(repo, {"tools/lib/atrapy/inna.py": (repo / "tools/inna.py").read_text(encoding="utf-8")})
    _zapisz(repo, {"tools/inna.py": "from atrapy.inna import *\n"})


def _plik_maszynerii_napisany_od_nowa_pod_sciezka_weryfikacji(repo: Path) -> None:
    _nowe_linie_maszynerii(repo)
    _przenies(repo, "tools/inna.py", "tools/lib/atrapy/inna.py", _linie(60, "z"))


def _nowy_test_maszynerii_bez_wpisu(repo: Path) -> None:
    _zapisz(repo, {"tests/test_inna.py": _linie(20)})


# Znane luki licznika szopy (tests/fixtures/znane_luki.py): opis postaci → zmiana PR, która powiększa maszynerię procesu,
# a mimo to przechodzi przez licznik bez etykiety zgody. Licznik liczy linie według ścieżek i nie rozpoznaje pochodzenia
# kodu, więc każda postać przeniesienia między grupami jest tu, a recenzent ocenia ją z liczb obu grup.
ZNANE_LUKI: Final[dict[str, Callable[[Path], None]]] = {
    "nowe linie maszynerii i git mv jej pliku do katalogu weryfikacji z listy bazy (przegląd #1646 r1, W1)": (
        _git_mv_do_katalogu_weryfikacji
    ),
    "nowe linie maszynerii i git mv jej pliku do skilla verify-* (przegląd #1646 r2, sonda S3)": _git_mv_do_skilla_verify,
    "nowe linie maszynerii i git mv jej pliku poza szopę (przegląd #1646 r2, sonda S2)": _git_mv_poza_szope,
    "nowe linie maszynerii i kopia jej pliku do katalogu weryfikacji, a w starym pliku jedna linia importu (przegląd #1646 r2, W1)": (
        _kopia_do_katalogu_weryfikacji_z_importem_w_starym_pliku
    ),
    "nowe linie maszynerii i jej plik usunięty i napisany od nowa pod ścieżką weryfikacji": (
        _plik_maszynerii_napisany_od_nowa_pod_sciezka_weryfikacji
    ),
    "nowy test maszynerii bez wpisu na liście liczy się jako test produktu": _nowy_test_maszynerii_bez_wpisu,
}


def test_znane_luki_licznika_szopy_przechodza_bez_etykiety_zgody(tmp_path: Path) -> None:
    zgloszenia: dict[str, list[str]] = {}
    for numer, (opis, zmiana) in enumerate(ZNANE_LUKI.items()):
        repo = _repo_szopy(tmp_path / str(numer))
        zmiana(repo)
        commit(repo, opis)
        szopa = rozmiar_pr.zmierz_szope(repo, "main", "pr")
        zgloszenia[opis] = [f"licznik: {szopa.opis()} | {szopa.stan(None)}"] if szopa.wymaga_zgody else []

    assert_znane_luki(zgloszenia, "tests/test_rozmiar_pr.py")


@pytest.mark.parametrize(
    ("komentarz", "prawo", "stan", "zgody"),
    [
        (
            "Ok.\n\n- ZGODA SZOPA",
            "admin",
            "ZGODA SZOPA od maks",
            (["SZOPA | zdjęta wymaga ZGODA SZOPA z #7"], [("DELETE", f"{REPO}/issues/7/labels/wymaga%20ZGODA%20SZOPA", {})]),
        ),
        ("ZGODA SZOPA", "write", "wymaga ZGODA SZOPA", ([], [])),
        ("Zgoda w kodzie:\n\n```\nZGODA SZOPA\n```", "admin", "wymaga ZGODA SZOPA", ([], [])),
    ],
    ids=["punkt-listy-od-admina", "akapit-od-konta-bez-admina", "blok-kodu-od-admina"],
)
def test_komentarz_zgoda_szopa_od_konta_admin_poza_kodem_zdejmuje_etykiete_zgody(
    szopa: Path, komentarz: str, prawo: str, stan: str, zgody: tuple[list[str], list[tuple[str, str, Mapping[str, object]]]]
) -> None:
    _zapisz(szopa, {"tools/bramka.py": _linie(30) + _linie(3, "y")})
    commit(szopa, "więcej maszynerii")
    github = _GitHub(
        w_repo=[], na_pr=[rozmiar_pr.ZGODA.nazwa], komentarze=[{"user": {"login": "maks"}, "body": komentarz}], prawa=[("maks", prawo)]
    )

    linie, wywolania = _licz(szopa, github)

    assert (linie, wywolania) == (
        [
            "SZOPA | #7 | maszyneria procesu z testami +3 -0, weryfikacja produktu z testami +0 -0, testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50"
            f" | {stan}",
            *zgody[0],
        ],
        zgody[1],
    )


@pytest.mark.parametrize(
    ("tekst", "blad"),
    [
        ('[inna]\n"tools/a.py" = []\n', "tabela [inna] nie jest grupą listy"),
        ('[maszyneria]\n"tools/a.py" = "tests/test_a.py"\n', "jednostka tools/a.py ma mieć listę plików testów"),
        ('[produkt]\n"src/" = ["tests/test_a.py"]\n[maszyneria]\n"tools/a.py" = ["tests/test_a.py"]\n', "tests/test_a.py stoi na liście dwa razy"),
    ],
)
def test_lista_dwoch_szop_innego_ksztaltu_albo_z_powtorzonym_wpisem_to_blad(tekst: str, blad: str) -> None:
    with pytest.raises(ValueError, match=re.escape(blad)):
        rozmiar_pr.wpisy(tekst)
