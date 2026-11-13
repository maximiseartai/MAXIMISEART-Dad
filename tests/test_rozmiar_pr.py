"""Etykieta rozmiaru PR (``tools/ci/rozmiar_pr.py``, workflow ``rozmiar-pr.yml``): progi z t3code, efektywne linie od
bazy scalenia, pliki testów pominięte w PR mieszanym, a w PR z samymi testami liczone, i jedna etykieta ``size:*`` na PR.
Licznik szopy (ADR 0034): grupę pliku daje reguła katalogu, a lista dwóch szop bazy tylko wyjątki od niej; licznik podaje
linie maszynerii procesu i weryfikacji produktu osobno oraz dwa stosunki testów do ``src``, a atrybuty ``.gitattributes``
nie zmieniają jego liczb."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

import pytest

from tests.fixtures.git_repo import commit, git

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
    def __init__(self, w_repo: list[dict[str, Any]], na_pr: list[str]) -> None:
        self.odpowiedzi = {
            f"{REPO}/labels": w_repo,
            f"{REPO}/issues/7/labels": [{"name": nazwa} for nazwa in na_pr],
        }
        self.wyslane: list[tuple[str, str, Mapping[str, object]]] = []

    def json(self, sciezka: str) -> Any:
        return (
            self.odpowiedzi[sciezka.partition("?")[0]]
            if sciezka.endswith("page=1")
            else []
        )

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


@pytest.fixture
def szopa(tmp_path: Path) -> Path:
    """Repozytorium z listą ``_LISTA`` na gałęzi ``main`` i gałęzią ``pr`` z niej."""

    git(tmp_path, "init", "--quiet", "--initial-branch", "main")
    _zapisz(
        tmp_path,
        {
            "src/stary.py": _linie(20),
            "tests/test_stary.py": _linie(5),
            "tools/bramka.py": _linie(30),
            "tests/test_bramka.py": _linie(10),
            "tools/lib/atrapa.py": _linie(10),
            "tools/lib/atrapy/stara.py": _linie(10),
            "tools/inna.py": _linie(60),
            rozmiar_pr.LISTA: _LISTA,
        },
    )
    commit(tmp_path, "baza")
    git(tmp_path, "switch", "--quiet", "--create", "pr")
    return tmp_path


def _szopa(repo: Path) -> str:
    return rozmiar_pr.zmierz_szope(repo, "main", "pr").opis()


def test_licznik_szopy_liczy_weryfikacje_z_listy_i_reguly_a_produkt_tylko_w_stosunkach_bez_prozy(szopa: Path) -> None:
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

    assert _szopa(szopa) == (
        "maszyneria procesu z testami +0 -0, weryfikacja produktu z testami +13 -0"
        ", testy zachowania src / src 45/35 = 1,29, testy szopy / src 10/35 = 0,29"
    )


def test_licznik_szopy_liczy_maszynerie_z_jej_testami_z_listy_i_nowy_plik_narzedzi_z_reguly_katalogu(szopa: Path) -> None:
    _zapisz(
        szopa,
        {"tools/bramka.py": _linie(18), "tests/test_bramka.py": _linie(10) + _linie(8, "y"), "tools/nowa.py": _linie(5)},
    )
    commit(szopa, "maszyneria")

    assert _szopa(szopa) == (
        "maszyneria procesu z testami +13 -12, weryfikacja produktu z testami +0 -0"
        ", testy zachowania src / src 5/20 = 0,25, testy szopy / src 18/20 = 0,90"
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

    assert _szopa(szopa) == (
        "maszyneria procesu z testami +6 -0, weryfikacja produktu z testami +9 -0"
        ", testy zachowania src / src 12/20 = 0,60, testy szopy / src 10/20 = 0,50"
    )


def test_przeniesienie_pliku_maszynerii_do_weryfikacji_widac_w_liczbach_obu_grup(szopa: Path) -> None:
    git(szopa, "mv", "tools/inna.py", "tools/lib/atrapy/inna.py")
    commit(szopa, "maszyneria do weryfikacji")

    assert _szopa(szopa) == (
        "maszyneria procesu z testami +0 -60, weryfikacja produktu z testami +60 -0"
        ", testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50"
    )


def test_pr_liczy_grupy_wedlug_listy_bazy_a_nastepny_pr_wedlug_listy_po_scaleniu(szopa: Path) -> None:
    _zapisz(
        szopa,
        {
            rozmiar_pr.LISTA: '[weryfikacja]\n"tools/lib/atrapa.py" = []\n"tools/lib/atrapy/" = []\n"tools/bramka.py" = ["tests/test_bramka.py"]\n',
            "tools/bramka.py": _linie(30) + _linie(40, "y"),
        },
    )
    commit(szopa, "bramka w weryfikacji")
    zmiana_listy = _szopa(szopa)
    git(szopa, "branch", "--force", "main", "pr")
    _zapisz(szopa, {"tools/bramka.py": _linie(30) + _linie(45, "y")})
    commit(szopa, "więcej bramki")

    assert (zmiana_listy, _szopa(szopa)) == (
        "maszyneria procesu z testami +40 -0, weryfikacja produktu z testami +0 -0"
        ", testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50",
        "maszyneria procesu z testami +0 -0, weryfikacja produktu z testami +5 -0"
        ", testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50",
    )


@pytest.mark.parametrize(
    ("plik", "atrybuty"),
    [
        (".gitattributes", "tools/bramka.py -diff\n"),
        (".gitattributes", "tools/** binary\nsrc/** binary\ntests/** binary\n"),
        ("tools/.gitattributes", "bramka.py -diff\n"),
        ("atrybuty-z-konfiguracji", "* binary\n"),
    ],
    ids=["diff-na-pliku-maszynerii", "binary-na-katalogach-szopy-i-src", "diff-w-podkatalogu", "plik-z-core-attributesfile"],
)
def test_atrybut_diff_albo_binary_spoza_bajtow_pliku_nie_zeruje_linii_licznika_szopy(szopa: Path, plik: str, atrybuty: str) -> None:
    # Przegląd #1646 r3, W1: jedna linia .gitattributes na main zerowała numstat każdego kolejnego PR.
    _zapisz(szopa, {plik: atrybuty})
    if plik == "atrybuty-z-konfiguracji":
        git(szopa, "config", "core.attributesFile", str(szopa / plik))
    commit(szopa, "atrybuty")
    git(szopa, "branch", "--force", "main", "pr")
    _zapisz(szopa, {"tools/bramka.py": _linie(30) + _linie(40, "y"), "tools/zrzut.bin": "a\0b\n" * 3})
    commit(szopa, "więcej bramki i plik binarny")

    assert _szopa(szopa) == (
        "maszyneria procesu z testami +40 -0, weryfikacja produktu z testami +0 -0"
        ", testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50"
    )


@pytest.mark.parametrize(
    ("tekst", "blad"),
    [
        ('[inna]\n"tools/a.py" = []\n', "tabela [inna] nie jest grupą listy"),
        ('[maszyneria]\n"tools/a.py" = "tests/test_a.py"\n', "jednostka tools/a.py ma mieć listę plików testów"),
        ('[produkt]\n"src/" = ["tests/test_a.py"]\n[maszyneria]\n"tools/a.py" = ["tests/test_a.py"]\n', "tests/test_a.py stoi na liście dwa razy"),
    ],
    ids=["obca-tabela", "testy-nie-lista", "powtorzony-wpis"],
)
def test_lista_dwoch_szop_innego_ksztaltu_albo_z_powtorzonym_wpisem_to_blad(tekst: str, blad: str) -> None:
    with pytest.raises(ValueError, match=re.escape(blad)):
        rozmiar_pr.wpisy(tekst)
