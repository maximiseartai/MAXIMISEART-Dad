"""Model TLA+ Aktualizacji narzędzia: opowieść kontrprzykładu krokami kodu.

Werdykt, znane znaleziska, rozjazd z kodem w CI i narzędzia TLC sprawdza ``tests/test_model_tlc.py`` na drodze wspólnej
dla modeli skilli.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.model_tlc import model_tlc, skrypt_modelu, wyjscie_tlc

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"


def test_dziennik_ktory_zostaje_na_zawsze_to_naruszony_postep_z_nowa_wersja_krokami_i_stanem_na_koncu(
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = {"nowaUsuwaPlikTaty": "FALSE", "nowaZmieniaWymagania": "TRUE", "nowaStartuje": "FALSE", "krok": '"spoczynek"'}
    last = {"head": '"nowa"', "plikTaty": '"taty"', "biblioteki": '"czesciowe"', "centrum": '"brak"', "dziennik": '"w_toku"'}
    output = wyjscie_tlc(None, ("Init", first), ("Instaluj", {**first, **last, "krok": '"pip_install zwraca False"'}), ("Stuttering", {}))

    found = model_tlc.werdykt(skrypt_modelu(SCRIPT).MODEL, output)

    assert found == model_tlc.Werdykt("Postep")
    assert capsys.readouterr().out.splitlines() == [
        "   naruszone Postep: dziennik „Aktualizacja w toku” zostaje na zawsze.",
        "   nowa wersja: usuwa plik taty z config/: nie, zmienia requirements.txt: tak, startuje: nie",
        "   1. pip_install zwraca False",
        "   2. (dalej nic się nie dzieje)",
        "   na koniec: klon na wersji nowa, plik taty: taty, biblioteki: czesciowe, Centrum: brak, dziennik: w_toku",
    ]
