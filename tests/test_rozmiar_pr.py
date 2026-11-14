"""Etykieta rozmiaru PR (``tools/ci/rozmiar_pr.py``, workflow ``rozmiar-pr.yml``): progi z t3code, efektywne linie od
bazy scalenia, pliki testów pominięte w PR mieszanym, a w PR z samymi testami liczone, i jedna etykieta ``size:*`` na PR.
Licznik szopy (ADR 0034): grupę pliku daje reguła katalogu, a lista dwóch szop bazy tylko wyjątki od niej; licznik podaje
linie maszynerii procesu i weryfikacji produktu osobno oraz dwa stosunki testów do ``src``, a atrybuty ``.gitattributes``
nie zmieniają jego liczb. PR, który dodaje więcej linii maszynerii procesu, niż usuwa, dostaje etykietę informacyjną;
przeniesienia między grupami licznik nie rozpoznaje, więc ich postacie są próbkami ``ZNANE_LUKI``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
        },
    )
    commit(katalog, "baza")
    git(katalog, "switch", "--quiet", "--create", "pr")
    return katalog


@pytest.fixture
def szopa(tmp_path: Path) -> Path:
    return _repo_szopy(tmp_path)


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


_POWIEKSZA = rozmiar_pr.POWIEKSZA
# Linie licznika i wywołania GitHuba dla etykiety ``POWIEKSZA``.
_Akcje = tuple[list[str], list[tuple[str, str, Mapping[str, object]]]]
_ZALOZONA_I_NADANA: _Akcje = (
    [f"SZOPA | założona etykieta {_POWIEKSZA.nazwa}", f"SZOPA | nadana {_POWIEKSZA.nazwa} #7"],
    [
        ("POST", f"{REPO}/labels", {"name": _POWIEKSZA.nazwa, "color": _POWIEKSZA.kolor, "description": _POWIEKSZA.opis}),
        ("POST", f"{REPO}/issues/7/labels", {"labels": [_POWIEKSZA.nazwa]}),
    ],
)
_ZDJETA: _Akcje = (
    [f"SZOPA | zdjęta {_POWIEKSZA.nazwa} z #7"],
    [("DELETE", f"{REPO}/issues/7/labels/powi%C4%99ksza%20maszyneri%C4%99%20procesu", {})],
)


@pytest.mark.parametrize(
    ("pliki", "na_pr", "maszyneria", "etykieta"),
    [
        ({"tools/bramka.py": _linie(30) + _linie(40, "y")}, [], "+40 -0", _ZALOZONA_I_NADANA),
        ({"tools/bramka.py": _linie(30) + _linie(40, "y")}, [_POWIEKSZA.nazwa], "+40 -0", ([], [])),
        ({"tools/bramka.py": _linie(22), "tests/test_bramka.py": _linie(10) + _linie(8, "y")}, [_POWIEKSZA.nazwa], "+8 -8", _ZDJETA),
        ({"tools/bramka.py": _linie(18), "tools/nowa.py": _linie(5)}, [_POWIEKSZA.nazwa], "+5 -12", _ZDJETA),
        ({"tools/bramka.py": _linie(18), "tools/nowa.py": _linie(5)}, [], "+5 -12", ([], [])),
    ],
    ids=["wiecej-dodanych-dostaje", "wiecej-dodanych-z-etykieta-bez-zmian", "remis-traci", "ubytek-traci", "ubytek-bez-etykiety-bez-zmian"],
)
def test_pr_z_wiecej_dodanymi_niz_usunietymi_liniami_maszynerii_ma_etykiete_a_remis_i_ubytek_ja_traca(
    szopa: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pliki: Mapping[str, str],
    na_pr: list[str],
    maszyneria: str,
    etykieta: _Akcje,
) -> None:
    _zapisz(szopa, pliki)
    commit(szopa, "maszyneria")
    github = _GitHub(w_repo=[], na_pr=na_pr)
    monkeypatch.setattr("repo.ROOT", szopa)
    monkeypatch.setattr(rozmiar_pr, "GhApi", lambda: github)

    assert rozmiar_pr.main(["--baza", "main", "--glowa", "pr", "--pr", "7"]) == 0

    szopa_linie = [linia for linia in capsys.readouterr().out.splitlines() if linia.startswith("SZOPA")]
    assert (szopa_linie[0].split(", ")[0], szopa_linie[1:]) == (f"SZOPA | #7 | maszyneria procesu z testami {maszyneria}", etykieta[0])
    assert [wywolanie for wywolanie in github.wyslane if "size" not in wywolanie[1] + str(wywolanie[2])] == etykieta[1]


def test_bez_numeru_pr_licznik_tylko_drukuje_i_nie_pyta_githuba(
    szopa: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def bez_githuba() -> None:
        raise AssertionError("bez --pr narzędzie nie pyta GitHuba")

    _zapisz(szopa, {"tools/bramka.py": _linie(30) + _linie(40, "y")})
    commit(szopa, "więcej maszynerii")
    monkeypatch.setattr("repo.ROOT", szopa)
    monkeypatch.setattr(rozmiar_pr, "GhApi", bez_githuba)

    assert rozmiar_pr.main(["--baza", "main", "--glowa", "pr"]) == 0

    assert [linia.split(" | ")[:2] for linia in capsys.readouterr().out.splitlines()] == [["ROZMIAR PR", "pr"], ["SZOPA", "pr"]]


def _nowe_linie_maszynerii(repo: Path) -> None:
    _zapisz(repo, {"tools/bramka.py": _linie(30) + _linie(40, "y")})


def _git_mv_do_katalogu_weryfikacji(repo: Path) -> None:
    _nowe_linie_maszynerii(repo)
    git(repo, "mv", "tools/inna.py", "tools/lib/atrapy/inna.py")


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
    (repo / "tools/inna.py").unlink()
    _zapisz(repo, {"tools/lib/atrapy/inna.py": _linie(60, "z")})


def _lista_przenosi_plik_do_weryfikacji_a_nastepny_pr_dodaje_jego_linie(repo: Path) -> None:
    _zapisz(repo, {rozmiar_pr.LISTA: _LISTA.replace("[maszyneria]", '"tools/inna.py" = []\n\n[maszyneria]')})
    commit(repo, "lista przenosi tools/inna.py do weryfikacji")
    git(repo, "branch", "--force", "main", "pr")
    _zapisz(repo, {"tools/inna.py": _linie(60) + _linie(40, "y")})


def _nowy_test_maszynerii_bez_wpisu(repo: Path) -> None:
    _zapisz(repo, {"tests/test_inna.py": _linie(20)})


# Znane luki etykiety (tests/fixtures/znane_luki.py): opis postaci → zmiana PR, która powiększa maszynerię procesu, a mimo
# to przechodzi przez licznik bez etykiety. Licznik liczy linie według ścieżek i listy bazy, więc kod przeniesiony między
# grupami odejmuje linie maszynerii, a recenzent widzi go w liczbach obu grup.
ZNANE_LUKI: Final[dict[str, Callable[[Path], None]]] = {
    "nowe linie maszynerii i git mv jej pliku do katalogu weryfikacji z listy bazy (przegląd #1646 r1, W1)": (
        _git_mv_do_katalogu_weryfikacji
    ),
    "nowe linie maszynerii i git mv jej pliku poza szopę": _git_mv_poza_szope,
    "nowe linie maszynerii i kopia jej pliku do katalogu weryfikacji, a w starym pliku jedna linia importu (przegląd #1646 r2, W1)": (
        _kopia_do_katalogu_weryfikacji_z_importem_w_starym_pliku
    ),
    "nowe linie maszynerii i jej plik usunięty i napisany od nowa pod ścieżką weryfikacji": (
        _plik_maszynerii_napisany_od_nowa_pod_sciezka_weryfikacji
    ),
    "PR zmienia tylko listę i przenosi plik maszynerii do weryfikacji, a następny PR dodaje jego linie (przegląd #1646 r1, W2)": (
        _lista_przenosi_plik_do_weryfikacji_a_nastepny_pr_dodaje_jego_linie
    ),
    "nowy test maszynerii bez wpisu na liście liczy się jako test produktu": _nowy_test_maszynerii_bez_wpisu,
}


def test_znane_luki_etykiety_maszynerii_przechodza_przez_licznik_bez_etykiety(tmp_path: Path) -> None:
    zgloszenia: dict[str, list[str]] = {}
    for numer, (opis, zmiana) in enumerate(ZNANE_LUKI.items()):
        repo = _repo_szopy(tmp_path / str(numer))
        zmiana(repo)
        commit(repo, opis)
        szopa = rozmiar_pr.zmierz_szope(repo, "main", "pr")
        zgloszenia[opis] = [f"licznik: {szopa.opis()} | {_POWIEKSZA.nazwa}"] if szopa.powieksza else []

    assert_znane_luki(zgloszenia, "tests/test_rozmiar_pr.py")


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
