"""Etykieta rozmiaru PR (``tools/ci/rozmiar_pr.py``, workflow ``rozmiar-pr.yml``): progi z t3code, efektywne linie od
bazy scalenia, pliki testów pominięte w PR mieszanym, a w PR z samymi testami liczone, i jedna etykieta ``size:*`` na PR.
Licznik szopy (ADR 0034): grupę pliku daje reguła katalogu, a lista dwóch szop tylko wyjątki od niej; PR z nowymi liniami
maszynerii procesu bez większego usunięcia dostaje etykietę zgody, którą zdejmuje komentarz ``ZGODA SZOPA`` konta
z prawem ``admin``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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


@pytest.fixture
def szopa(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet", "--initial-branch", "main")
    _zapisz(
        tmp_path,
        {
            "src/stary.py": _linie(20),
            "tests/test_stary.py": _linie(5),
            "tools/bramka.py": _linie(30),
            "tests/test_bramka.py": _linie(10),
            "tools/lib/atrapa.py": _linie(10),
            "tools/inna.py": _linie(10),
            "tools/lib/szopa.toml": _LISTA,
        },
    )
    commit(tmp_path, "baza")
    git(tmp_path, "switch", "--quiet", "--create", "pr")
    return tmp_path


def _licz(repo: Path, github: _GitHub) -> tuple[list[str], list[tuple[str, str, Mapping[str, object]]]]:
    """Linie licznika szopy i wywołania GitHuba dla etykiety zgody, bez etykiety rozmiaru."""

    linie = rozmiar_pr.licz(repo, "main", "pr", 7, github, _HTML.__getitem__)
    zgody = [wywolanie for wywolanie in github.wyslane if "ZGODA" in wywolanie[1] or "ZGODA" in str(wywolanie[2])]
    return [linia for linia in linie if linia.startswith("SZOPA")], zgody


def test_pr_bez_linii_maszynerii_procesu_nie_wymaga_zgody_choc_zmienia_produkt_weryfikacje_proze_i_liste(szopa: Path) -> None:
    _zapisz(
        szopa,
        {
            "src/stary.py": _linie(35),
            "tests/test_nowy.py": _linie(40),
            "tools/lib/atrapa.py": _linie(16),
            "tools/OPIS.md": _linie(50),
            "tools/lib/szopa.toml": _LISTA.replace('"tools/lib/atrapa.py" = []', '"tools/lib/atrapa.py" = ["tests/test_nowy.py"]'),
        },
    )
    commit(szopa, "produkt")

    assert _licz(szopa, _GitHub(w_repo=[], na_pr=[])) == (
        [
            "SZOPA | #7 | maszyneria procesu z testami +0 -0, testy zachowania src / src 5/35 = 0,14, testy szopy / src 50/35 = 1,43"
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
            "SZOPA | #7 | maszyneria procesu z testami +5 -12, testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50"
            " | usuwa więcej linii maszynerii procesu, niż dodaje",
            "SZOPA | zdjęta wymaga ZGODA SZOPA z #7",
        ],
        [("DELETE", f"{REPO}/issues/7/labels/wymaga%20ZGODA%20SZOPA", {})],
    )


def test_pr_ktory_dodaje_tyle_linii_maszynerii_z_testami_ile_usuwa_wymaga_zgody(szopa: Path) -> None:
    _zapisz(szopa, {"tools/bramka.py": _linie(22), "tests/test_bramka.py": _linie(10) + _linie(8, "y")})
    commit(szopa, "tyle samo maszynerii")
    zgoda = rozmiar_pr.ZGODA

    assert _licz(szopa, _GitHub(w_repo=[], na_pr=[])) == (
        [
            "SZOPA | #7 | maszyneria procesu z testami +8 -8, testy zachowania src / src 5/20 = 0,25, testy szopy / src 18/20 = 0,90"
            " | wymaga ZGODA SZOPA",
            "SZOPA | założona etykieta wymaga ZGODA SZOPA",
            "SZOPA | nadana wymaga ZGODA SZOPA #7",
        ],
        [
            ("POST", f"{REPO}/labels", {"name": zgoda.nazwa, "color": zgoda.kolor, "description": zgoda.opis}),
            ("POST", f"{REPO}/issues/7/labels", {"labels": [zgoda.nazwa]}),
        ],
    )


def test_pr_liczy_linie_maszynerii_plikow_z_bazy_wedlug_listy_bazy_choc_jego_lista_przenosi_je_do_weryfikacji(szopa: Path) -> None:
    # tools/bramka.py ma wpis na liście bazy, tools/inna.py grupę z reguły katalogu, a nowy tools/lib/atrapa_nowa.py
    # bierze grupę z listy głowy.
    _zapisz(
        szopa,
        {
            "tools/bramka.py": _linie(30) + _linie(4, "y"),
            "tools/inna.py": _linie(10) + _linie(2, "y"),
            "tools/lib/atrapa_nowa.py": _linie(9),
            "tools/lib/szopa.toml": _LISTA.replace(
                '"tools/lib/atrapa.py" = []',
                '"tools/lib/atrapa.py" = []\n"tools/bramka.py" = []\n"tools/inna.py" = []\n"tools/lib/atrapa_nowa.py" = []',
            ).replace('"tools/bramka.py" = ["tests/test_bramka.py"]', '"tools/lib/bramka_testy.py" = ["tests/test_bramka.py"]'),
        },
    )
    commit(szopa, "maszyneria jako weryfikacja")

    linie, _ = _licz(szopa, _GitHub(w_repo=[], na_pr=[]))

    assert linie[0] == (
        "SZOPA | #7 | maszyneria procesu z testami +6 -0, testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50"
        " | wymaga ZGODA SZOPA"
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
        "SZOPA | #7 | maszyneria procesu z testami +6 -0, testy zachowania src / src 12/20 = 0,60, testy szopy / src 10/20 = 0,50"
        " | wymaga ZGODA SZOPA"
    )


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
            "SZOPA | #7 | maszyneria procesu z testami +3 -0, testy zachowania src / src 5/20 = 0,25, testy szopy / src 10/20 = 0,50"
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
