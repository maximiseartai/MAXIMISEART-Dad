"""Kod w ``src/`` sięga do prywatnej składowej (``_nazwa``) innego obiektu albo modułu tylko w klasie, która ją
definiuje.

Pilnuje tego ruff ``SLF001`` z ``pyproject.toml`` w każdym runie. Zapis Ustawień Centrum obok ich właściciela przez jego
prywatne pola (``settings._places[…].write``, ``settings._history.append``, ``settings._memory.write``) omija reguły
właściciela, a reguła ast-grep na nazwach pól musiałaby je wyliczać (#1727 r5, W1). Drogi ``DROGI`` ruff odrzuca
w module Centrum, a postacie, których ``SLF001`` nie widzi, są próbkami ``ZNANE_LUKI``: ruff i mypy przepuszczają je na
tej samej ścieżce.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from tests.fixtures.znane_luki import assert_znane_luki, ruff, ruff_i_mypy, wymaga_ruff, wymaga_ruff_i_mypy, zapisz

ROOT = Path(__file__).resolve().parents[1]
# Sonda modułu Centrum: ścieżka w src/ bez prawa właściciela do SLF001.
CENTRUM_PROBE = ROOT / "src" / "rozliczenia" / "centrum" / "sonda_skladowej.py"

_USTAWIENIA: Final = "from rozliczenia.centrum.settings.owner import CentrumSettings\n\n\n"

# Postać → moduł, którego prywatne pole Ustawień ruff odrzuca w module Centrum (SLF001).
DROGI: Final = {
    "zapis pliku Ustawień przez prywatne miejsce właściciela": _USTAWIENIA
    + 'def usun_pracownika(settings: CentrumSettings, data: str) -> None:\n    settings._places["workers"].write(data)\n',
    "wpis historii zmian Ustawień obok właściciela": _USTAWIENIA
    + "def historia(settings: CentrumSettings) -> object:\n    return settings._history\n",
    "zapis pamięci Ustawień obok właściciela": _USTAWIENIA
    + "def pamiec(settings: CentrumSettings) -> object:\n    return settings._memory\n",
}

# Postać → moduł, w którym prywatna składowa innego obiektu albo modułu przechodzi przez ruff i mypy na ścieżce modułu
# Centrum. SLF001 nie zgłasza odbiorcy pod nazwą self, cls ani mcs (także modułu zaimportowanego pod nią) ani importu
# prywatnej nazwy.
ZNANE_LUKI: Final = {
    "nazwa pola w napisie getattr": _USTAWIENIA
    + 'def places(settings: CentrumSettings) -> object:\n    return getattr(settings, "_places")\n',
    "pole ze słownika vars": _USTAWIENIA + 'def places(settings: CentrumSettings) -> object:\n    return vars(settings)["_places"]\n',
    "obiekt pod nazwą self w funkcji modułu": _USTAWIENIA + "def places(self: CentrumSettings) -> object:\n    return self._places\n",
    "obiekt pod nazwą cls w funkcji modułu": _USTAWIENIA + "def places(cls: CentrumSettings) -> object:\n    return cls._places\n",
    "obiekt pod nazwą mcs w funkcji modułu": _USTAWIENIA + "def places(mcs: CentrumSettings) -> object:\n    return mcs._places\n",
    "moduł zaimportowany pod nazwą cls": """from rozliczenia.centrum.settings import owner as cls


def miejsce() -> object:
    return cls._Place
""",
    "import prywatnej nazwy innego modułu": """from rozliczenia.centrum.settings.owner import _Place


def miejsce() -> object:
    return _Place
""",
}


@wymaga_ruff
def test_prywatna_skladowa_ustawien_w_module_centrum_pada_w_ruff(tmp_path: Path) -> None:
    """Moduł Centrum, który sięga do prywatnego pola ``CentrumSettings``, pada w ruff (``SLF001``)."""

    zgloszenia = ruff(zapisz(DROGI, tmp_path), CENTRUM_PROBE)

    assert {opis: lista for opis, lista in zgloszenia.items() if not any("SLF001" in z for z in lista)} == {}


@wymaga_ruff_i_mypy
def test_znane_luki_prywatnych_skladowych_przechodza_przez_ruff_i_mypy(tmp_path: Path) -> None:
    """Każda próbka ``ZNANE_LUKI`` przechodzi przez cały ruff i mypy z konfiguracją repozytorium na ścieżce modułu
    Centrum."""

    assert_znane_luki(ruff_i_mypy(zapisz(ZNANE_LUKI, tmp_path), CENTRUM_PROBE), "tests/test_prywatne_skladowe.py (ZNANE_LUKI)")
