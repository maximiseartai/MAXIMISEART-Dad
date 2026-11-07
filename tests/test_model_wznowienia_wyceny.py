"""Model TLA+ wznowienia Wyceny w efenix: kod opisany modelem i opowieść kontrprzykładu.

Model opisuje definicje z ``model/definicje.json`` skilla ``verify-wznowienie-wyceny-efenix`` w Sync commit z jego
``SKILL.md`` (rozjazd rozstrzyga ``tools/lib/rozjazd_modelu.py``). Zmiana innej części tych plików (``efenix_pricing.py``
zmienia się często) rozjazdem nie jest. Werdykt i znane znaleziska sprawdza ``tests/test_model_tlc.py`` na drodze
wspólnej dla modeli skilli.
"""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from tests.fixtures.git_repo import commit, git
from tests.fixtures.model_tlc import model_tlc, rozjazd_modelu, skrypt_modelu, wyjscie_tlc

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-wznowienie-wyceny-efenix" / "scripts" / "sprawdz_wznowienie_wyceny.py"
DEFINITIONS = ROOT / ".agents" / "skills" / "verify-wznowienie-wyceny-efenix" / "model" / "definicje.json"
PRICING = "src/rozliczenia/efenix_pricing.py"
COVERED = (
    "src/rozliczenia/efenix_pricing.py",
    "src/rozliczenia/efenix_positions.py",
    "src/rozliczenia/efenix_browser.py",
    "src/rozliczenia/efenix_checks.py",
    "src/rozliczenia/efenix_mark.py",
)


def _drift_after(root: Path, anchor: str, replacement: str) -> tuple[str, str | None]:
    """Commit synchronizacji z kodem opisanym modelem, potem zmiana ``anchor`` w ``efenix_pricing.py``; zwraca skrót
    commitu synchronizacji i rozjazd."""

    for path in (DEFINITIONS, *(ROOT / name for name in COVERED)):
        copy = root / path.relative_to(ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, copy)
    git(root, "init", "--quiet")
    sync = commit(root, "synchronizacja")[:9]
    pricing = root / PRICING
    text = pricing.read_text(encoding="utf-8")
    assert text.count(anchor) == 1, anchor
    pricing.write_text(text.replace(anchor, replacement), encoding="utf-8")
    commit(root, "zmiana")
    skill = root / DEFINITIONS.relative_to(ROOT).parents[1]
    (skill / "SKILL.md").write_text(f"Sync commit: `{sync}` (main).\n", encoding="utf-8")
    return sync, rozjazd_modelu.rozjazd(skill, root)


def test_zmieniona_definicja_opisana_modelem_jest_rozjazdem(tmp_path: Path) -> None:
    sync, found = _drift_after(tmp_path, "    if plan.excess:\n        return EmmettWarning(plan.excess)\n", "")

    assert found is not None and f"kod opisany modelem zmienił się od {sync}: {PRICING} _completed" in found, found


def test_zmiana_obok_definicji_opisanych_modelem_nie_jest_rozjazdem(tmp_path: Path) -> None:
    # Sprawdzania (``check`` w ``price_orders``) model nie opisuje.
    _, found = _drift_after(tmp_path, "    def check() -> None:\n", "    def check() -> None:\n        pass\n")

    assert found is None


def test_kontrprzyklad_daje_obietnice_i_przyczyny_jej_zdarzenia_z_wyjscia_tlc(capsys: pytest.CaptureFixture[str]) -> None:
    output = wyjscie_tlc(
        "ZmianaTatyZostajePozaZnanymi",
        ("Init", {"efenix": "<<[A |-> 0, B |-> 0]>>", "wynik": '<<"brak">>', "zlecenie": "1", "zlyWynikPoTacie": "{}"}),
        (
            "Wpisz",
            {
                "efenix": "<<[A |-> 1, B |-> 1]>>",
                "wynik": '<<"ostrzezenie">>',
                "zlecenie": "1",
                "zlyWynikPoTacie": '{{"przerwanie-po-ilosci",\n   "brak-pozycji-po-emmetcie"}}',
            },
        ),
    )

    found = model_tlc.werdykt(skrypt_modelu(SCRIPT).MODEL, output)

    assert found == model_tlc.Werdykt("ZmianaTatyZostaje", frozenset({"przerwanie-po-ilosci", "brak-pozycji-po-emmetcie"}))
    assert "1. okno wpisuje ilość z pliku w zleceniu 1" in capsys.readouterr().out
