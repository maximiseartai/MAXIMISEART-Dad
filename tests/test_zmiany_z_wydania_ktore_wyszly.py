from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
import sys
from typing import Final

import pytest

from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES
from rozliczenia.centrum.settings.reminders import REMINDERS_FILE
from rozliczenia.centrum.settings.workers import WORKERS_FILE

from tests.fixtures.znane_luki import modul
from zmiany_z_wydania import GRANICA_ODCISKU, NOWY_WPIS, Wpis, wpisy

PRZYPIETE: Final = {
    "2026-11-lista-wykonawcow": Wpis(WORKERS_FILE, "c469fcf617a2ba00"),
    "2026-11-folder-okresow-od-zalacznikow": Wpis(SETTINGS_FILE, "54784b00870283c2"),
    "2026-11-przypomnienia": Wpis(REMINDERS_FILE, "0a59d2c0f4842677"),
}

PRZYPNIJ: Final = (
    "każda Zmiana z Wydania ma w PRZYPIETE swój plik i odcisk od PR, który ją dodaje: nową przypnij, a zmienioną "
    "przepnij tylko wtedy, gdy jej id nie stoi w RELEASE_CHANGES żadnego tagu v*; gdy stoi, "
    f"{NOWY_WPIS}, bo tools/wydanie.py plan odmówi Wydania, w którym wpis z tagu zniknął albo ma inny plik lub odcisk"
)


def test_zmiana_z_wydania_ma_plik_i_odcisk_przypiete_od_pr_ktory_ja_dodaje_bo_tata_ma_jej_id_w_pamieci() -> None:
    teraz = wpisy(RELEASE_CHANGES)
    rozne = {
        id_zmiany: (PRZYPIETE.get(id_zmiany), teraz.get(id_zmiany))
        for id_zmiany in sorted(PRZYPIETE.keys() | teraz.keys())
        if PRZYPIETE.get(id_zmiany) != teraz.get(id_zmiany)
    }

    assert not rozne, f"{PRZYPNIJ}; (przypięte, teraz): {rozne}"


_NAGLOWEK: Final = "from rozliczenia.centrum.settings.folders import FOLDERS\nfrom rozliczenia.centrum.settings.proposal import ReleaseChange\n\n\n"
_WPIS: Final = '\n\nZMIANA = ReleaseChange("2026-12-proba", FOLDERS, {})\n'


def _zmiana(kod: str, propose: str = "propose") -> str:
    return kod + _WPIS.format(propose)


ODMOWY_ODCISKU: Final = {
    "lambda": {"zmiana": _WPIS.format("lambda inputs: inputs")},
    "metoda statyczna klasy obok funkcji modułu o tej samej nazwie": {
        "zmiana": _zmiana(
            "def propose(inputs):\n    return None\n\n\nclass K:\n    @staticmethod\n    def propose(inputs):\n        return inputs\n",
            "K.propose",
        )
    },
    "metoda obiektu": {"zmiana": _zmiana("class K:\n    def propose(self, inputs):\n        return inputs\n", "K().propose")},
    "funkcja z fabryki obok funkcji modułu o tej samej nazwie": {
        "zmiana": _zmiana(
            "def propose(inputs):\n    return None\n\n\ndef ustaw(*kody):\n    def propose(inputs):\n        return kody\n\n    return propose\n",
            "ustaw(1)",
        )
    },
    "functools.partial": {
        "zmiana": _zmiana("from functools import partial\n\n\ndef ustaw(kod, inputs):\n    return kod\n", "partial(ustaw, 1)")
    },
    "obiekt wywoływalny": {"zmiana": _zmiana("class Ustaw:\n    def __call__(self, inputs):\n        return inputs\n", "Ustaw()")},
    "funkcja spod dekoratora, który zwraca inną funkcję": {
        "zmiana": _zmiana(
            "import functools\n\n\ndef dek(f):\n    @functools.wraps(f)\n    def opakowana(inputs):\n        return f(inputs)\n\n"
            "    return opakowana\n\n\n@dek\ndef propose(inputs):\n    return inputs\n"
        )
    },
    "funkcja z bloku if modułu": {"zmiana": _zmiana("if True:\n\n    def propose(inputs):\n        return inputs\n")},
}

WIDZI_ODCISK: Final = {
    "funkcja importowana pod inną nazwą": (
        {"pomocnik": "def d(inputs):\n    return 1\n", "zmiana": _zmiana("from pomocnik import d as propose\n")},
        {"pomocnik": "def d(inputs):\n    return 2\n", "zmiana": _zmiana("from pomocnik import d as propose\n")},
    ),
    "funkcja przypisana do innej nazwy": (
        {"zmiana": _zmiana("def _ustaw(inputs):\n    return 1\n\n\npropose = _ustaw\n")},
        {"zmiana": _zmiana("def _ustaw(inputs):\n    return 2\n\n\npropose = _ustaw\n")},
    ),
    "dekorator modułu, który zwraca tę samą funkcję": (
        {"zmiana": _zmiana("def dek(f):\n    f.__defaults__ = (1,)\n    return f\n\n\n@dek\ndef propose(inputs, limit=0):\n    return limit\n")},
        {"zmiana": _zmiana("def dek(f):\n    f.__defaults__ = (2,)\n    return f\n\n\n@dek\ndef propose(inputs, limit=0):\n    return limit\n")},
    ),
    "nazwa związana z inną funkcją po utworzeniu wpisu": (
        {"zmiana": _zmiana("def propose(inputs):\n    return 1\n") + "\n\ndef propose(inputs):\n    return 3\n"},
        {"zmiana": _zmiana("def propose(inputs):\n    return 2\n") + "\n\ndef propose(inputs):\n    return 3\n"},
    ),
}

ZNANE_LUKI_ODCISKU: Final = {
    "funkcja modułu, po którą wpis sięga napisem z nazwą": (
        {"zmiana": _zmiana("import sys\n\n\ndef _d(x):\n    return 1\n\n\ndef propose(inputs):\n    return getattr(sys.modules[__name__], '_d')(inputs)\n")},
        {"zmiana": _zmiana("import sys\n\n\ndef _d(x):\n    return 2\n\n\ndef propose(inputs):\n    return getattr(sys.modules[__name__], '_d')(inputs)\n")},
    ),
    "metoda, po którą wpis sięga atrybutem obiektu": (
        {"zmiana": _zmiana("class K:\n    def f(self):\n        return 1\n\n\ndef propose(inputs):\n    return inputs.f()\n")},
        {"zmiana": _zmiana("class K:\n    def f(self):\n        return 2\n\n\ndef propose(inputs):\n    return inputs.f()\n")},
    ),
    "funkcja z innego modułu, którą wpis importuje": (
        {"pomocnik": "def d(x):\n    return 1\n", "zmiana": _zmiana("from pomocnik import d\n\n\ndef propose(inputs):\n    return d(inputs)\n")},
        {"pomocnik": "def d(x):\n    return 2\n", "zmiana": _zmiana("from pomocnik import d\n\n\ndef propose(inputs):\n    return d(inputs)\n")},
    ),
    "dekorator z innego modułu, który zmienia funkcję w miejscu": (
        {
            "pomocnik": "def dek(f):\n    f.__defaults__ = (1,)\n    return f\n",
            "zmiana": _zmiana("from pomocnik import dek\n\n\n@dek\ndef propose(inputs, limit=0):\n    return limit\n"),
        },
        {
            "pomocnik": "def dek(f):\n    f.__defaults__ = (2,)\n    return f\n",
            "zmiana": _zmiana("from pomocnik import dek\n\n\n@dek\ndef propose(inputs, limit=0):\n    return limit\n"),
        },
    ),
}


def _odcisk_zmiany(katalog: Path, moduly: Mapping[str, str]) -> str:
    katalog.mkdir()
    try:
        for nazwa, kod in moduly.items():
            plik = katalog / f"{nazwa}.py"
            plik.write_text(_NAGLOWEK + kod if nazwa == "zmiana" else kod, encoding="utf-8")
            sys.modules[nazwa] = modul(plik)
        return wpisy([sys.modules["zmiana"].ZMIANA])["2026-12-proba"].odcisk
    finally:
        for nazwa in moduly:
            sys.modules.pop(nazwa, None)


@pytest.mark.parametrize("moduly", list(ODMOWY_ODCISKU.values()), ids=list(ODMOWY_ODCISKU))
def test_odcisk_odmawia_zmiany_z_wydania_ktorej_propose_nie_jest_def_najwyzszego_poziomu_modulu(tmp_path: Path, moduly: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=re.escape(GRANICA_ODCISKU)):
        _odcisk_zmiany(tmp_path / "zmiana", moduly)


@pytest.mark.parametrize("przed, po", list(WIDZI_ODCISK.values()), ids=list(WIDZI_ODCISK))
def test_odcisk_zmiany_z_wydania_bierze_definicje_z_kodu_propose_a_nie_z_nazwy_w_module(
    tmp_path: Path, przed: dict[str, str], po: dict[str, str]
) -> None:
    assert _odcisk_zmiany(tmp_path / "przed", przed) != _odcisk_zmiany(tmp_path / "po", po)


@pytest.mark.parametrize("przed, po", list(ZNANE_LUKI_ODCISKU.values()), ids=list(ZNANE_LUKI_ODCISKU))
def test_znane_luki_odcisku_zmiany_z_wydania_daja_ten_sam_odcisk(tmp_path: Path, przed: dict[str, str], po: dict[str, str]) -> None:
    rowne = _odcisk_zmiany(tmp_path / "przed", przed) == _odcisk_zmiany(tmp_path / "po", po)

    assert rowne, "odcisk łapie już tę lukę: usuń próbkę z ZNANE_LUKI_ODCISKU"


def test_odcisk_zmiany_z_wydania_widzi_funkcje_i_stale_modulu_po_ktore_wpis_siega_nazwa_a_nie_docstring(tmp_path: Path) -> None:
    przed = _zmiana('LIMIT = 1\n\n\ndef _dzien(text):\n    """Dzień."""\n    return text[:LIMIT]\n\n\ndef propose(inputs):\n    return _dzien(inputs)\n')
    bazowy = _odcisk_zmiany(tmp_path / "baza", {"zmiana": przed})

    assert _odcisk_zmiany(tmp_path / "bez_docstringu", {"zmiana": przed.replace('"""Dzień."""\n    ', "")}) == bazowy
    assert _odcisk_zmiany(tmp_path / "inna_funkcja", {"zmiana": przed.replace("text[:LIMIT]", "text[1:]")}) != bazowy
    assert _odcisk_zmiany(tmp_path / "inna_stala", {"zmiana": przed.replace("LIMIT = 1", "LIMIT = 2")}) != bazowy
