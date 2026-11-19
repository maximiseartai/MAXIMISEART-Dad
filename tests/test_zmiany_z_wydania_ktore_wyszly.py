from __future__ import annotations

import builtins
from collections.abc import Mapping
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
from typing import Final

import pytest

from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES
from rozliczenia.centrum.settings.reminders import REMINDERS_FILE
from rozliczenia.centrum.settings.workers import WORKERS_FILE

import repo
from zmiany_z_wydania import GRANICA_ODCISKU, INNY_KOD, Wpis, roznice, wpisy, wpisy_commitu

PRZYPIETE: Final = {
    "2026-11-lista-wykonawcow": Wpis(WORKERS_FILE, "a5b1a109c181edcf"),
    "2026-11-folder-okresow-od-zalacznikow": Wpis(SETTINGS_FILE, "308b4e7abd72e003"),
    "2026-11-przypomnienia": Wpis(REMINDERS_FILE, "def7aa3ade7b79c8"),
}

PRZYPNIJ: Final = (
    "każda Zmiana z Wydania ma w PRZYPIETE swój plik i odcisk od PR, który ją dodaje: nową przypnij, a zmienioną "
    "przepnij tylko wtedy, gdy jej id nie stoi w RELEASE_CHANGES żadnego tagu v*, bo tools/wydanie.py plan odmówi "
    "Wydania, w którym wpis z tagu zniknął albo ma inny plik lub odcisk; gdy stoi, zrób to, co mówi jej różnica wobec "
    "origin/main"
)


def _wobec_main(teraz: Mapping[str, Wpis]) -> str:
    try:
        main = wpisy_commitu(repo.ROOT, repo.merge_base(repo.ROOT, "HEAD", repo.BASE))
    except (subprocess.SubprocessError, ValueError) as blad:
        return f"tu nie da się jej policzyć ({blad}), więc {INNY_KOD}"
    return " | ".join(roznice(main, teraz, "origin/main").values()) or "wpisy z origin/main mają ten sam odcisk, więc zmienił się kod odcisku w tools/lib/zmiany_z_wydania.py: przepnij je"


def test_zmiana_z_wydania_ma_plik_i_odcisk_przypiete_od_pr_ktory_ja_dodaje_bo_tata_ma_jej_id_w_pamieci() -> None:
    teraz = wpisy(RELEASE_CHANGES)
    rozne = {
        id_zmiany: (PRZYPIETE.get(id_zmiany), teraz.get(id_zmiany))
        for id_zmiany in sorted(PRZYPIETE.keys() | teraz.keys())
        if PRZYPIETE.get(id_zmiany) != teraz.get(id_zmiany)
    }

    assert not rozne, f"{PRZYPNIJ}; (przypięte, teraz): {rozne}; różnica wobec origin/main: {_wobec_main(teraz)}"


_NAGLOWEK: Final = "from rozliczenia.centrum.settings.folders import FOLDERS\nfrom rozliczenia.centrum.settings.proposal import ReleaseChange\n\n\n"
_WPIS: Final = '\n\nZMIANA = ReleaseChange("2026-12-proba", FOLDERS, {})\n'
_FABRYKA: Final = "def ustaw(*kody):\n    def propose(inputs):\n        return kody\n\n    return propose\n"
_DEKORATOR_Z_WRAPS: Final = (
    "import functools\n\n\ndef dek(f):\n    @functools.wraps(f)\n    def opakowana(inputs):\n        return f(inputs)\n\n    return opakowana\n"
)
_KOD: Final = "import dataclasses\n\n\n@dataclasses.dataclass(frozen=True)\nclass Kod:\n    id: str\n\n\n"
_KOLOR: Final = "import enum\n\n\nclass Kolor(enum.Enum):\n    A = 1\n    B = 2\n\n\n"
_LOGIN: Final = "class Login(str):\n    pass\n"


def _zmiana(kod: str, propose: str = "propose") -> str:
    return kod + _WPIS.format(propose)


def _po(przed: Mapping[str, str], **zmiany: tuple[str, str]) -> dict[str, str]:
    return {nazwa: kod.replace(*zmiany[nazwa]) if nazwa in zmiany else kod for nazwa, kod in przed.items()}


def _przypadek(przed: Mapping[str, str], ten_sam: bool, opis: str, **zmiany: tuple[str, str]) -> object:
    return pytest.param(dict(przed), _po(przed, **zmiany), ten_sam, id=opis)


PRZYPADKI_ODCISKU: Final = [
    _przypadek({"zmiana": _zmiana("def propose(inputs):\n    return 1\n")}, False, "ciało funkcji propose", zmiana=("return 1", "return 2")),
    _przypadek({"zmiana": _zmiana("", "lambda inputs: 1")}, False, "lambda", zmiana=(": 1", ": 2")),
    _przypadek(
        {"zmiana": _zmiana("def propose(inputs):\n    return None\n\n\nclass K:\n    @staticmethod\n    def propose(inputs):\n        return 1\n", "K.propose")},
        False,
        "metoda statyczna klasy obok funkcji modułu o tej samej nazwie",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek({"zmiana": _zmiana(_FABRYKA, "ustaw(1)")}, False, "funkcja z fabryki: argument fabryki", zmiana=("ustaw(1)", "ustaw(2)")),
    _przypadek({"zmiana": _zmiana(_FABRYKA, "ustaw(1)")}, False, "funkcja z fabryki: ciało funkcji zagnieżdżonej", zmiana=("return kody\n", "return kody[1:]\n")),
    _przypadek(
        {"zmiana": _zmiana("from functools import partial\n\n\ndef ustaw(kod, inputs):\n    return kod\n", "partial(ustaw, 1)")},
        False,
        "functools.partial",
        zmiana=("partial(ustaw, 1)", "partial(ustaw, 2)"),
    ),
    _przypadek(
        {"zmiana": _zmiana(_DEKORATOR_Z_WRAPS + "\n\n@dek\ndef propose(inputs):\n    return 1\n")},
        False,
        "funkcja spod dekoratora modułu, który zwraca inną funkcję",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek(
        {"pomocnik": _DEKORATOR_Z_WRAPS, "zmiana": _zmiana("from pomocnik import dek\n\n\n@dek\ndef propose(inputs):\n    return 1\n")},
        False,
        "funkcja spod dekoratora innego modułu z functools.wraps",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek(
        {
            "pomocnik": "def dek(f):\n    f.__defaults__ = (1,)\n    return f\n",
            "zmiana": _zmiana("from pomocnik import dek\n\n\n@dek\ndef propose(inputs, limit=0):\n    return limit\n"),
        },
        False,
        "dekorator innego modułu, który zmienia funkcję w miejscu",
        pomocnik=("(1,)", "(2,)"),
    ),
    _przypadek({"zmiana": _zmiana("if True:\n\n    def propose(inputs):\n        return 1\n")}, False, "propose z bloku if modułu", zmiana=("return 1", "return 2")),
    _przypadek(
        {"zmiana": _zmiana('_POWOD, _INNY = "a", 0\n\n\ndef propose(inputs):\n    return _POWOD\n')},
        False,
        "stała z rozpakowania krotki",
        zmiana=('"a"', '"b"'),
    ),
    _przypadek(
        {"zmiana": _zmiana("if True:\n\n    def _d():\n        return 1\n\n\ndef propose(inputs):\n    return _d()\n")},
        False,
        "funkcja pomocnicza z bloku if modułu",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("try:\n\n    def _d():\n        return 1\n\nexcept ImportError:\n    pass\n\n\ndef propose(inputs):\n    return _d()\n")},
        False,
        "funkcja pomocnicza z bloku try modułu",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("for _LIMIT in (1,):\n    pass\n\n\ndef propose(inputs):\n    return _LIMIT\n")},
        False,
        "stała z pętli for modułu",
        zmiana=("(1,)", "(2,)"),
    ),
    _przypadek(
        {"zmiana": _zmiana("import contextlib\n\nwith contextlib.nullcontext(1) as _LIMIT:\n    pass\n\n\ndef propose(inputs):\n    return _LIMIT\n")},
        False,
        "stała z bloku with modułu",
        zmiana=("nullcontext(1)", "nullcontext(2)"),
    ),
    _przypadek(
        {"zmiana": _zmiana("def propose(inputs):\n    return 1\n") + "\n\ndef propose(inputs):\n    return 3\n"},
        False,
        "propose związane z inną funkcją po utworzeniu wpisu",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("def _d():\n    return 1\n\n\ndef _d():\n    return 3\n\n\ndef propose(inputs):\n    return _d()\n")},
        False,
        "funkcja pomocnicza związana drugi raz: ta, która biegnie",
        zmiana=("return 3", "return 4"),
    ),
    _przypadek(
        {"pomocnik": "def d(inputs):\n    return 1\n", "zmiana": _zmiana("from pomocnik import d as propose\n")},
        False,
        "funkcja innego modułu importowana jako propose",
        pomocnik=("1", "2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("def _ustaw(inputs):\n    return 1\n\n\npropose = _ustaw\n")},
        False,
        "funkcja przypisana do innej nazwy",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("LIMIT = 1\n\n\ndef _dzien(text):\n    return text[:LIMIT]\n\n\ndef propose(inputs):\n    return _dzien(inputs)\n")},
        False,
        "stała modułu, po którą sięga funkcja pomocnicza",
        zmiana=("LIMIT = 1", "LIMIT = 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("def _d():\n    return 1\n\n\ndef propose(inputs):\n    return (lambda: _d())()\n")},
        False,
        "funkcja pomocnicza, po którą sięga lambda w ciele propose",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("LIMIT = 1\n\n\ndef propose(inputs, limit=LIMIT):\n    return limit\n")},
        False,
        "domyślna wartość parametru z nazwy modułu",
        zmiana=("LIMIT = 1", "LIMIT = 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("class _Blad(Exception):\n    pass\n\n\ndef propose(inputs):\n    try:\n        return 1\n    except _Blad:\n        return 0\n")},
        False,
        "klasa modułu, po którą sięga nazwą",
        zmiana=("(Exception)", "(ValueError)"),
    ),
    _przypadek(
        {"zmiana": _zmiana("LIMIT = 1\n\n\nclass _K:\n    @staticmethod\n    def f():\n        return LIMIT\n\n\ndef propose(inputs):\n    return _K.f()\n")},
        False,
        "stała, po którą sięga metoda klasy modułu",
        zmiana=("LIMIT = 1", "LIMIT = 2"),
    ),
    _przypadek(
        {"pomocnik": "LIMIT = 1\n", "zmiana": _zmiana("from pomocnik import LIMIT\n\n\ndef propose(inputs):\n    return LIMIT\n")},
        False,
        "stała innego modułu",
        pomocnik=("1", "2"),
    ),
    _przypadek(
        {"zmiana": _zmiana(_KOD + '_KOD = Kod("a")\n\n\ndef propose(inputs):\n    return _KOD\n')},
        False,
        "obiekt dataclass modułu",
        zmiana=('Kod("a")', 'Kod("b")'),
    ),
    _przypadek(
        {"zmiana": _zmiana(_KOLOR + "_KOLOR = Kolor.A\n\n\ndef propose(inputs):\n    return _KOLOR\n")},
        False,
        "członek Enum modułu",
        zmiana=("_KOLOR = Kolor.A", "_KOLOR = Kolor.B"),
    ),
    _przypadek(
        {"zmiana": _zmiana("def dek(f):\n    f.limit = 1\n    return f\n\n\n@dek\ndef propose(inputs):\n    return propose.limit\n")},
        False,
        "atrybut funkcji ustawiony przez dekorator modułu",
        zmiana=("f.limit = 1", "f.limit = 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("class _Baza:\n    LIMIT = 1\n\n\nclass _K(_Baza):\n    pass\n\n\ndef propose(inputs):\n    return _K.LIMIT\n")},
        False,
        "klasa bazowa z modułu klasy, po którą sięga wpis",
        zmiana=("LIMIT = 1", "LIMIT = 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("class _K:\n    pass\n\n\n_K.LIMIT = 1\n\n\ndef propose(inputs):\n    return _K.LIMIT\n")},
        False,
        "atrybut klasy modułu ustawiony po klasie",
        zmiana=("_K.LIMIT = 1", "_K.LIMIT = 2"),
    ),
    _przypadek(
        {"pomocnik": "Typy = int | str\n", "zmiana": _zmiana("from pomocnik import Typy\n\n\ndef propose(inputs):\n    return isinstance(inputs, Typy)\n")},
        False,
        "unia typów innego modułu",
        pomocnik=("int | str", "int | bytes"),
    ),
    _przypadek(
        {"zmiana": _zmiana("import dataclasses\n\nLIMIT = 1\n\n\n@dataclasses.dataclass\nclass _K:\n    limit: int = 0\n\n    def __post_init__(self):\n        self.limit = LIMIT\n\n\ndef propose(inputs):\n    return _K().limit\n")},
        False,
        "stała, po którą sięga __post_init__ klasy modułu",
        zmiana=("LIMIT = 1", "LIMIT = 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("LIMIT = 1\n\n\nclass _K:\n    @property\n    def limit(self):\n        return LIMIT\n\n\ndef propose(inputs):\n    return _K().limit\n")},
        False,
        "stała, po którą sięga property klasy modułu",
        zmiana=("LIMIT = 1", "LIMIT = 2"),
    ),
    _przypadek(
        {"pomocnik": _KOLOR + "class Inny(enum.Enum):\n    A = 1\n", "zmiana": _zmiana("import pomocnik\n\n_KOLOR = pomocnik.Kolor.A\n\n\ndef propose(inputs):\n    return _KOLOR\n")},
        False,
        "członek Enum innego modułu, którego klasy moduł propose nie wiąże nazwą",
        zmiana=("pomocnik.Kolor.A", "pomocnik.Inny.A"),
    ),
    _przypadek(
        {"pomocnik": "def d(x):\n    return 1\n\n\ndef e(x):\n    return 1\n", "zmiana": _zmiana("from pomocnik import d\n\n_KODY = (d,)\n\n\ndef propose(inputs):\n    return _KODY\n")},
        False,
        "definicja innego modułu w krotce modułu propose zamieniona na inną",
        zmiana=("from pomocnik import d\n\n_KODY = (d,)", "from pomocnik import d, e\n\n_KODY = (e,)"),
    ),
    _przypadek(
        {"zmiana": _zmiana("def propose(inputs):\n    return (1)\n")},
        True,
        "docstring, komentarz i formatowanie",
        zmiana=("    return (1)\n", '    """Zwraca jeden."""\n    # jeden\n    return 1\n'),
    ),
    _przypadek(
        {"zmiana": _zmiana("def _inna():\n    return 1\n\n\ndef propose(inputs):\n    return 0\n")},
        True,
        "funkcja modułu, po którą wpis nie sięga",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("def _d():\n    return 1\n\n\ndef propose(inputs):\n    return _d()\n")},
        True,
        "definicje przesunięte w module",
        zmiana=("def _d():\n    return 1\n\n\ndef propose(inputs):\n    return _d()\n", "\n\n\ndef propose(inputs):\n    return _d()\n\n\ndef _d():\n    return 1\n"),
    ),
    _przypadek(
        {"zmiana": _zmiana("def _d():\n    return 1\n\n\ndef _d():\n    return 3\n\n\ndef propose(inputs):\n    return _d()\n")},
        True,
        "pierwsza definicja nazwy, którą zastępuje druga",
        zmiana=("return 1", "return 2"),
    ),
    _przypadek(
        {"zmiana": _zmiana("_KODY = frozenset((1, 9))\n\n\ndef propose(inputs):\n    return _KODY\n")},
        True,
        "zbiór z tymi samymi elementami w innej kolejności",
        zmiana=("(1, 9)", "(9, 1)"),
    ),
    _przypadek(
        {"pomocnik": "def d(x):\n    return 1\n", "zmiana": _zmiana("from pomocnik import d\n\n\ndef propose(inputs):\n    return d(inputs)\n")},
        True,
        "definicja innego modułu przemianowana z aliasem pod starą nazwą",
        pomocnik=("def d(x):\n    return 1\n", "def nowa(x):\n    return 1\n\n\nd = nowa\n"),
    ),
    _przypadek(
        {"typy": "", "pomocnik": _LOGIN, "zmiana": _zmiana("from pomocnik import Login\n\n\ndef propose(inputs):\n    return Login(inputs)\n")},
        True,
        "definicja innego modułu przeniesiona do trzeciego modułu z tym samym importem",
        typy=("", _LOGIN),
        pomocnik=(_LOGIN, "from typy import Login\n"),
    ),
]

ROZNICE_ODCISKU: Final = [
    pytest.param(
        {"zmiana": _zmiana("def propose(inputs):\n    return 1\n")},
        {"zmiana": _zmiana("def propose(inputs):\n    return 2\n")},
        "propose › funkcja („return 2” zamiast „return 1”)",
        id="poprawka w miejscu: linia źródła",
    ),
    pytest.param(
        {"pomocnik": "def d(x):\n    return 1\n\n\ndef e(x):\n    return 1\n", "zmiana": _zmiana("from pomocnik import d\n\n_KODY = (d,)\n\n\ndef propose(inputs):\n    return _KODY\n")},
        {"pomocnik": "def d(x):\n    return 1\n\n\ndef e(x):\n    return 1\n", "zmiana": _zmiana("from pomocnik import e\n\n_KODY = (e,)\n\n\ndef propose(inputs):\n    return _KODY\n")},
        "propose › nazwy › _KODY › tuple › 0 › nazwa w module propose („e” zamiast „d”)",
        id="nazwa, pod którą moduł propose wiąże definicję innego modułu",
    ),
    pytest.param(
        {"pomocnik": _KOLOR, "zmiana": _zmiana("import pomocnik\n\n_KOLOR = pomocnik.Kolor.A\n\n\ndef propose(inputs):\n    return _KOLOR\n")},
        {"pomocnik": _KOLOR.replace("class Kolor", "class Barwa") + "Kolor = Barwa\n", "zmiana": _zmiana("import pomocnik\n\n_KOLOR = pomocnik.Kolor.A\n\n\ndef propose(inputs):\n    return _KOLOR\n")},
        "propose › nazwy › _KOLOR › enum › definicja innego modułu („pomocnik.Barwa” zamiast „pomocnik.Kolor”)",
        id="moduł i nazwa definicji innego modułu, której moduł propose nie wiąże nazwą",
    ),
]

ODMOWY_ODCISKU: Final = [
    pytest.param({"zmiana": _zmiana("class K:\n    def propose(self, inputs):\n        return inputs\n", "K().propose")}, id="metoda obiektu"),
    pytest.param({"zmiana": _zmiana("class K:\n    @classmethod\n    def propose(cls, inputs):\n        return inputs\n", "K.propose")}, id="metoda klasy"),
    pytest.param({"zmiana": _zmiana("class Ustaw:\n    def __call__(self, inputs):\n        return inputs\n", "Ustaw()")}, id="obiekt wywoływalny"),
    pytest.param({"zmiana": _zmiana("", "(lambda inputs: 1) if True else (lambda inputs: 2)")}, id="dwie lambdy w jednej linii"),
    pytest.param({"zmiana": _zmiana("", "lambda inputs: (lambda current: current)")}, id="lambda z lambdą w ciele w jednej linii"),
    pytest.param(
        {"zmiana": _zmiana("class Rejestr:\n    pass\n\n\n_REJESTR = Rejestr()\n\n\ndef propose(inputs):\n    return _REJESTR\n")},
        id="obiekt modułu, który nie jest dataclass",
    ),
    pytest.param(
        {"zmiana": _zmiana("import functools\n\n\n@functools.lru_cache\ndef _d():\n    return 1\n\n\ndef propose(inputs):\n    return _d()\n")},
        id="funkcja pod functools.lru_cache",
    ),
    pytest.param(
        {"zmiana": _zmiana('exec("def _d():\\n    return 1")\n\n\ndef propose(inputs):\n    return _d()\n')}, id="funkcja modułu bez źródła w pliku"
    ),
    pytest.param({"zmiana": _zmiana('_K = type("_K", (), {})\n\n\ndef propose(inputs):\n    return _K\n')}, id="klasa modułu utworzona w biegu"),
]

ZNANE_LUKI_ODCISKU: Final = {
    "zna tylko nazwę definicji innego modułu: funkcja, którą wpis importuje": (
        {"pomocnik": "def d(x):\n    return 1\n", "zmiana": _zmiana("from pomocnik import d\n\n\ndef propose(inputs):\n    return d(inputs)\n")},
        {"pomocnik": "def d(x):\n    return 2\n", "zmiana": _zmiana("from pomocnik import d\n\n\ndef propose(inputs):\n    return d(inputs)\n")},
    ),
    "zna tylko nazwę modułu: funkcja innego modułu przez atrybut modułu": (
        {"pomocnik": "def d(x):\n    return 1\n", "zmiana": _zmiana("import pomocnik\n\n\ndef propose(inputs):\n    return pomocnik.d(inputs)\n")},
        {"pomocnik": "def d(x):\n    return 2\n", "zmiana": _zmiana("import pomocnik\n\n\ndef propose(inputs):\n    return pomocnik.d(inputs)\n")},
    ),
    "zna tylko moduł funkcji propose: funkcja spod dekoratora innego modułu bez functools.wraps": (
        {
            "pomocnik": "def dek(f):\n    def opakowana(inputs):\n        return f(inputs)\n\n    return opakowana\n",
            "zmiana": _zmiana("from pomocnik import dek\n\n\n@dek\ndef propose(inputs):\n    return 1\n"),
        },
        {
            "pomocnik": "def dek(f):\n    def opakowana(inputs):\n        return f(inputs)\n\n    return opakowana\n",
            "zmiana": _zmiana("from pomocnik import dek\n\n\n@dek\ndef propose(inputs):\n    return 2\n"),
        },
    ),
    "nie czyta nazwy zbudowanej w biegu: funkcja modułu po napisie z nazwą": (
        {"zmiana": _zmiana("import sys\n\n\ndef _d(x):\n    return 1\n\n\ndef propose(inputs):\n    return getattr(sys.modules[__name__], '_d')(inputs)\n")},
        {"zmiana": _zmiana("import sys\n\n\ndef _d(x):\n    return 2\n\n\ndef propose(inputs):\n    return getattr(sys.modules[__name__], '_d')(inputs)\n")},
    ),
    "zna definicję innego modułu tylko po nazwie, pod którą wiąże ją moduł propose: inna definicja pod tą samą nazwą": (
        {"pomocnik": "def d(x):\n    return 1\n\n\ndef e(x):\n    return 2\n", "zmiana": _zmiana("from pomocnik import d\n\n\ndef propose(inputs):\n    return d(inputs)\n")},
        {"pomocnik": "def d(x):\n    return 1\n\n\ndef e(x):\n    return 2\n", "zmiana": _zmiana("from pomocnik import e as d\n\n\ndef propose(inputs):\n    return d(inputs)\n")},
    ),
    "czyta nazwy tylko z __globals__ modułu: nazwa, którą moduł wstawia do builtins": (
        {"zmiana": _zmiana("import builtins\n\nbuiltins._LIMIT_ODCISKU = 1\n\n\ndef propose(inputs):\n    return _LIMIT_ODCISKU\n")},
        {"zmiana": _zmiana("import builtins\n\nbuiltins._LIMIT_ODCISKU = 2\n\n\ndef propose(inputs):\n    return _LIMIT_ODCISKU\n")},
    ),
    "czyta nazwy tylko z __globals__ modułu: nazwa, którą moduł wstawia do słownika __builtins__": (
        {"zmiana": _zmiana("__builtins__['_LIMIT_ODCISKU'] = 1\n\n\ndef propose(inputs):\n    return _LIMIT_ODCISKU\n")},
        {"zmiana": _zmiana("__builtins__['_LIMIT_ODCISKU'] = 2\n\n\ndef propose(inputs):\n    return _LIMIT_ODCISKU\n")},
    ),
    "nie wie, jakiej klasy obiekt dostaje: metoda po atrybucie obiektu": (
        {"zmiana": _zmiana("class K:\n    def f(self):\n        return 1\n\n\ndef propose(inputs):\n    return inputs.f()\n")},
        {"zmiana": _zmiana("class K:\n    def f(self):\n        return 2\n\n\ndef propose(inputs):\n    return inputs.f()\n")},
    ),
}


def _wpis_zmiany(katalog: Path, moduly: Mapping[str, str]) -> Wpis:
    katalog.mkdir()
    wbudowane = set(vars(builtins))
    try:
        for nazwa, kod in moduly.items():
            plik = katalog / f"{nazwa}.py"
            plik.write_text(_NAGLOWEK + kod if nazwa == "zmiana" else kod, encoding="utf-8")
            spec = importlib.util.spec_from_file_location(nazwa, plik)
            assert spec is not None and spec.loader is not None, plik
            sys.modules[nazwa] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sys.modules[nazwa])
        return wpisy([sys.modules["zmiana"].ZMIANA])["2026-12-proba"]
    finally:
        for nazwa in moduly:
            sys.modules.pop(nazwa, None)
        for nazwa in set(vars(builtins)) - wbudowane:
            delattr(builtins, nazwa)


@pytest.mark.parametrize("przed, po, ten_sam", PRZYPADKI_ODCISKU)
def test_odcisk_zmiany_z_wydania_rozwiazuje_nazwy_wartosciami_w_biegu(tmp_path: Path, przed: dict[str, str], po: dict[str, str], ten_sam: bool) -> None:
    assert (_wpis_zmiany(tmp_path / "przed", przed) == _wpis_zmiany(tmp_path / "po", po)) is ten_sam


@pytest.mark.parametrize("przed, po, element", ROZNICE_ODCISKU)
def test_roznica_zmiany_z_wydania_podaje_pierwszy_inny_element_i_co_zrobic_w_kazdym_przypadku(
    tmp_path: Path, przed: dict[str, str], po: dict[str, str], element: str
) -> None:
    roznica = roznice({"2026-12-proba": _wpis_zmiany(tmp_path / "przed", przed)}, {"2026-12-proba": _wpis_zmiany(tmp_path / "po", po)}, "v0.1.0")

    assert roznica == {"2026-12-proba": f"2026-12-proba z v0.1.0 ma inny kod w {element}; {INNY_KOD}"}


@pytest.mark.parametrize("moduly", ODMOWY_ODCISKU)
def test_odcisk_odmawia_zmiany_z_wydania_z_wartoscia_ktorej_nie_umie_odcisnac(tmp_path: Path, moduly: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=re.escape(GRANICA_ODCISKU)):
        _wpis_zmiany(tmp_path / "zmiana", moduly)


@pytest.mark.parametrize("przed, po", list(ZNANE_LUKI_ODCISKU.values()), ids=list(ZNANE_LUKI_ODCISKU))
def test_znane_luki_odcisku_zmiany_z_wydania_daja_ten_sam_odcisk(tmp_path: Path, przed: dict[str, str], po: dict[str, str]) -> None:
    rowne = _wpis_zmiany(tmp_path / "przed", przed) == _wpis_zmiany(tmp_path / "po", po)

    assert rowne, "odcisk łapie już tę lukę: usuń próbkę z ZNANE_LUKI_ODCISKU"
