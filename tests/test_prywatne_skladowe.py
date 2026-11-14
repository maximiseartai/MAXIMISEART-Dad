"""Kod w ``src/`` sięga do prywatnej składowej (``_nazwa``) innego obiektu albo modułu tylko w module, który ją
definiuje.

Pilnuje tego ruff ``SLF001`` z ``pyproject.toml``. Zapis Ustawień Centrum obok ich właściciela przez jego prywatne pola
(``settings._places[…].write``, ``settings._history.append``, ``settings._memory.write``) omija reguły właściciela, a
reguła ast-grep na nazwach pól musiałaby je wyliczać (#1727 r5, W1).

Prawo właściciela: plik, który konfiguracja ruff zwalnia z ``SLF001`` (``per-file-ignores`` w ``pyproject.toml``), sięga
tylko do nazw z ``OWNERS``. Ruff zwalnia plik z całego ``SLF001``, a nie z jednej nazwy, więc kod właściciela poza
zwolnieniem zgłasza dokładnie swoje nazwy. Postacie, których ``SLF001`` nie widzi, są próbkami ``ZNANE_LUKI``.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.fixtures.znane_luki import assert_znane_luki, ruff, wymaga_ruff, zapisz

ROOT = Path(__file__).resolve().parents[1]
# Pliki konfiguracji ruff, które obowiązują w src/, literałem, żeby tools/szybko.py wybierał ten test przy ich zmianie.
PYPROJECT = ROOT / "pyproject.toml"
SRC_CONFIG = ROOT / "src" / "ruff.toml"
# Sonda modułu Centrum bez prawa właściciela do żadnej prywatnej składowej.
CENTRUM_PROBE = ROOT / "src" / "rozliczenia" / "centrum" / "sonda_skladowej.py"

# Prawo właściciela: plik zwolniony z SLF001 → prywatne składowe klas z tego samego modułu, do których sięga. Wiersz to
# ścieżka i nazwy w jednym napisie z odstępami: ścieżka w osobnym napisie wiąże ten test w tools/lib/wplyw_zmiany.py
# z modułem właściciela i jego importami, a wtedy wybór dla wzorcowej zmiany Centrum przekracza limit
# tests/test_ksztalt_bramki.py (powód w BY_CHANGE_ONLY w tests/test_szybko.py).
OWNERS: dict[str, frozenset[str]] = {
    path: frozenset(names)
    for path, *names in (
        line.split()
        for line in """
            src/rozliczenia/centrum/logs_disk.py _path _run_started
            src/rozliczenia/centrum/reports.py _ask_box _delivered _pending _preview _queue _rejected _state_of
            src/rozliczenia/client_data.py _columns _lengths _lock
            src/rozliczenia/efenix_browser.py _part _sent
            src/rozliczenia/row_look.py _style
        """.strip().splitlines()
    )
}
# Prywatna składowa obiektu spoza klasy: każdy plik src/ bez zwolnienia ją zgłasza.
SHARED_PROBE = "def owner_field(owner: object) -> object:\n    return owner._field\n"

SETTINGS_WRITE = '''from rozliczenia.centrum.settings import CentrumSettings


def delete_worker(settings: CentrumSettings, data: str) -> None:
    settings._places["workers"].write(data)
'''

# Postać → moduł, w którym prywatne pole Ustawień przechodzi przez cały ruff na ścieżce modułu Centrum.
ZNANE_LUKI: dict[str, str] = {
    "nazwa pola w napisie getattr": '''from rozliczenia.centrum.settings import CentrumSettings


def places(settings: CentrumSettings) -> object:
    return getattr(settings, "_places")
''',
    "pole ze słownika vars": '''from rozliczenia.centrum.settings import CentrumSettings


def places(settings: CentrumSettings) -> object:
    return vars(settings)["_places"]
''',
    "obiekt pod nazwą self w funkcji modułu": '''from rozliczenia.centrum.settings import CentrumSettings


def places(self: CentrumSettings) -> object:
    return self._places
''',
}


def _private_members(*arguments: str, code: str | None = None, cwd: Path = ROOT) -> list[tuple[str, str]]:
    """``(plik, składowa)`` każdego ``SLF001``, które ``ruff check`` z ``--ignore-noqa`` zgłasza w ``cwd``. Reguły wybiera
    konfiguracja jak w CI: ``--select`` z wiersza poleceń zastąpiłby jej ``per-file-ignores``."""

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--ignore-noqa", "--output-format", "json", *arguments],
        input=code,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        check=False,
    )
    assert result.stderr == "", result.stderr
    return [
        (Path(finding["filename"]).resolve().relative_to(cwd.resolve()).as_posix(), finding["message"].split("`")[1])
        for finding in json.loads(result.stdout)
        if finding["code"] == "SLF001"
    ]


@wymaga_ruff
def test_zapis_ustawien_przez_prywatne_pole_wlasciciela_w_module_centrum_pada_w_ruff() -> None:
    """Moduł Centrum, który zapisuje plik Ustawień przez prywatne miejsce ``CentrumSettings``, pada w ruff."""

    found = _private_members("--stdin-filename", str(CENTRUM_PROBE), "-", code=SETTINGS_WRITE)

    assert found == [("src/rozliczenia/centrum/sonda_skladowej.py", "_places")]


@wymaga_ruff
def test_konfiguracja_ruff_zwalnia_z_slf001_tylko_wlascicieli(tmp_path: Path) -> None:
    """Kopia ``src/`` z próbką ``SHARED_PROBE`` w miejscu każdego pliku, który ruff tam sprawdza, i z konfiguracją ruff
    ``src/``: plik bez zgłoszenia jest zwolniony z ``SLF001``, a zwolniony może być tylko właściciel z ``OWNERS``."""

    for config in (PYPROJECT, SRC_CONFIG):
        copy = tmp_path / config.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    shown = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--show-files", "src"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    checked = {Path(line).resolve().relative_to(ROOT.resolve()).as_posix() for line in shown.splitlines() if line.strip()}
    for name in checked:
        probe = tmp_path / name
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text(SHARED_PROBE, encoding="utf-8")

    reported = {name for name, member in _private_members("src", cwd=tmp_path) if member == "_field"}

    assert sorted(checked - reported) == sorted(OWNERS), (
        "z SLF001 konfiguracja ruff zwalnia w src/ tylko pliki z OWNERS w tests/test_prywatne_skladowe.py: prawo "
        "właściciela to jego ścieżka w per-file-ignores pyproject.toml i wiersz OWNERS z nazwami składowych"
    )


@wymaga_ruff
@pytest.mark.parametrize("owner", list(OWNERS))
def test_wlasciciel_siega_tylko_do_swoich_prywatnych_skladowych(owner: str) -> None:
    """Kod właściciela biegnie przez ruff jako sonda obok niego, poza jego zwolnieniem i z ``--ignore-noqa``: zgłasza
    dokładnie składowe z ``OWNERS``. Inna składowa to droga obok jej właściciela, a składowa, do której plik już nie
    sięga, to prawo do usunięcia."""

    path = ROOT / owner
    probe = path.with_name("sonda_skladowej.py")

    found = {member for _, member in _private_members("--stdin-filename", str(probe), "-", code=path.read_text(encoding="utf-8"))}

    assert sorted(found) == sorted(OWNERS[owner]), (
        f"{owner} sięga do prywatnych składowych {sorted(found)}, a jego prawo w OWNERS to {sorted(OWNERS[owner])}: "
        "do składowej innego modułu sięgaj przez jego publiczną metodę, a nazwę, której plik już nie używa, usuń z OWNERS"
    )


@wymaga_ruff
def test_znane_luki_prywatnych_skladowych_przechodza_przez_ruff(tmp_path: Path) -> None:
    """Każda próbka ``ZNANE_LUKI`` przechodzi przez cały ruff z konfiguracją repozytorium na ścieżce modułu Centrum."""

    assert_znane_luki(ruff(zapisz(ZNANE_LUKI, tmp_path), CENTRUM_PROBE), "tests/test_prywatne_skladowe.py (ZNANE_LUKI)")
