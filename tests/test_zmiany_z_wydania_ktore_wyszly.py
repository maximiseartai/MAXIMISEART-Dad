from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES
from rozliczenia.centrum.settings.reminders import REMINDERS_FILE
from rozliczenia.centrum.settings.workers import WORKERS_FILE

from zmiany_z_wydania import NOWY_WPIS, Wpis, odcisk, wpisy

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


ZNANE_LUKI_ODCISKU: Final = {
    "funkcja modułu, po którą wpis sięga napisem z nazwą": (
        {"zmiana.py": "import sys\n\ndef _d(x):\n    return 1\n\ndef propose(inputs):\n    return getattr(sys.modules[__name__], '_d')(inputs)\n"},
        {"zmiana.py": "import sys\n\ndef _d(x):\n    return 2\n\ndef propose(inputs):\n    return getattr(sys.modules[__name__], '_d')(inputs)\n"},
    ),
    "metoda, po którą wpis sięga atrybutem obiektu": (
        {"zmiana.py": "class K:\n    def f(self):\n        return 1\n\ndef propose(inputs):\n    return inputs.f()\n"},
        {"zmiana.py": "class K:\n    def f(self):\n        return 2\n\ndef propose(inputs):\n    return inputs.f()\n"},
    ),
    "funkcja z innego modułu, którą wpis importuje": (
        {"zmiana.py": "from pomocnik import d\n\ndef propose(inputs):\n    return d(inputs)\n", "pomocnik.py": "def d(x):\n    return 1\n"},
        {"zmiana.py": "from pomocnik import d\n\ndef propose(inputs):\n    return d(inputs)\n", "pomocnik.py": "def d(x):\n    return 2\n"},
    ),
}


def _odcisk_plikow(katalog: Path, pliki: dict[str, str]) -> str:
    katalog.mkdir()
    for nazwa, tekst in pliki.items():
        (katalog / nazwa).write_text(tekst, encoding="utf-8")
    return odcisk(katalog / "zmiana.py", "propose")


@pytest.mark.parametrize("przed, po", list(ZNANE_LUKI_ODCISKU.values()), ids=list(ZNANE_LUKI_ODCISKU))
def test_znane_luki_odcisku_zmiany_z_wydania_daja_ten_sam_odcisk(tmp_path: Path, przed: dict[str, str], po: dict[str, str]) -> None:
    rowne = _odcisk_plikow(tmp_path / "przed", przed) == _odcisk_plikow(tmp_path / "po", po)

    assert rowne, "odcisk łapie już tę lukę: usuń próbkę z ZNANE_LUKI_ODCISKU"


def test_odcisk_zmiany_z_wydania_widzi_funkcje_i_stale_modulu_po_ktore_wpis_siega_nazwa_a_nie_docstring(tmp_path: Path) -> None:
    przed = 'LIMIT = 1\n\ndef _dzien(text):\n    """Dzień."""\n    return text[:LIMIT]\n\ndef propose(inputs):\n    return _dzien(inputs)\n'
    bazowy = _odcisk_plikow(tmp_path / "baza", {"zmiana.py": przed})

    assert _odcisk_plikow(tmp_path / "bez_docstringu", {"zmiana.py": przed.replace('"""Dzień."""\n    ', "")}) == bazowy
    assert _odcisk_plikow(tmp_path / "inna_funkcja", {"zmiana.py": przed.replace("text[:LIMIT]", "text[1:]")}) != bazowy
    assert _odcisk_plikow(tmp_path / "inna_stala", {"zmiana.py": przed.replace("LIMIT = 1", "LIMIT = 2")}) != bazowy
