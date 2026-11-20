"""Model TLA+ wznowienia Wyceny w efenix: opowieść kontrprzykładu.

Rozjazd modelu z kodem opisanym modelem sprawdza ``tests/test_rozjazd_modelu.py``, a werdykt i znane znaleziska
``tests/test_model_tlc.py``, na drodze wspólnej dla modeli skilli.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.model_tlc import skrypt_modelu, wyjscie_tlc
import model_tlc

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-wznowienie-wyceny-efenix" / "scripts" / "sprawdz_wznowienie_wyceny.py"


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
