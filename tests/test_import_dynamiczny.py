"""Import w trakcie działania poza ``tests/`` (``tools/lib/import_dynamiczny.py``) odmawia kodu testów, zanim go wykona,
pod każdą nazwą i ścieżką, a inny moduł daje jak ``importlib``."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

import import_dynamiczny
from import_dynamiczny import OdmowaImportuTestow

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def test_modul_testow_po_nazwie_pakietu_tests_jest_odmowiony() -> None:
    with pytest.raises(OdmowaImportuTestow, match="kod spoza tests/ nie importuje kodu testów"):
        import_dynamiczny.modul("tests.fixtures.znane_luki")


def test_modul_testow_pod_inna_nazwa_jest_odmowiony_zanim_wykona_kod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(FIXTURES))
    monkeypatch.delitem(sys.modules, "znane_luki", raising=False)

    with pytest.raises(OdmowaImportuTestow):
        import_dynamiczny.modul("znane_luki")
    assert "znane_luki" not in sys.modules


def test_podmodul_pakietu_z_testow_jest_odmowiony_zanim_wykona_pakiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "tests"))
    monkeypatch.delitem(sys.modules, "fixtures", raising=False)

    with pytest.raises(OdmowaImportuTestow):
        import_dynamiczny.modul("fixtures.znane_luki")
    assert "fixtures" not in sys.modules


def test_plik_z_testow_jest_odmowiony_takze_przez_dowiazanie(tmp_path: Path) -> None:
    link = tmp_path / "poza_testami"
    try:
        link.symlink_to(FIXTURES, target_is_directory=True)
    except OSError:
        pytest.skip("system nie pozwala tu na dowiązanie symboliczne (Windows bez uprawnień)")

    for plik in (FIXTURES / "znane_luki.py", FIXTURES / ".." / "fixtures" / "znane_luki.py", link / "znane_luki.py"):
        with pytest.raises(OdmowaImportuTestow):
            import_dynamiczny.modul_z_pliku("sonda", plik)


def test_plik_z_testow_w_innej_wielkosci_liter_jest_odmowiony_na_systemie_bez_wielkosci_liter() -> None:
    plik = ROOT / "TESTS" / "fixtures" / "znane_luki.py"
    if not plik.exists():
        pytest.skip("system plików rozróżnia wielkość liter, więc ta ścieżka nie prowadzi do tests/")

    with pytest.raises(OdmowaImportuTestow):
        import_dynamiczny.modul_z_pliku("sonda", plik)


def test_modul_spoza_testow_jest_importowany_jak_przez_importlib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pakiet_sondy").mkdir()
    (tmp_path / "pakiet_sondy" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pakiet_sondy" / "modul_sondy.py").write_text("WARTOSC = 7\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    try:
        assert import_dynamiczny.modul("json") is sys.modules["json"]
        assert import_dynamiczny.modul("pakiet_sondy.modul_sondy").WARTOSC == 7
        assert import_dynamiczny.modul_z_pliku("sonda_z_pliku", tmp_path / "pakiet_sondy" / "modul_sondy.py").WARTOSC == 7
        assert "sonda_z_pliku" not in sys.modules
    finally:
        sys.modules.pop("pakiet_sondy.modul_sondy", None)
        sys.modules.pop("pakiet_sondy", None)


def test_jest_modul_znajduje_modul_bez_wykonania_jego_kodu(tmp_path: Path) -> None:
    (tmp_path / "modul_z_bledem.py").write_text("raise SystemExit('wykonany')\n", encoding="utf-8")

    assert import_dynamiczny.jest_modul("modul_z_bledem", [str(tmp_path)])
    assert not import_dynamiczny.jest_modul("nie_ma_takiego_modulu_sondy", [str(tmp_path)])
    assert import_dynamiczny.jest_modul("pytest")
    assert "modul_z_bledem" not in sys.modules
