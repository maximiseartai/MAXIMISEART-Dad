from __future__ import annotations

import pytest

from rozliczenia.message import DadFile

from tests.fixtures.message_samples import PREPARATION_SAMPLES, SETTLEMENT_SAMPLES, Samples

DAD_FILES: dict[str, dict[str, DadFile]] = {
    "przygotowanie-pliku-zbiorczego": {
        "REJESTR_OTWARTY": "order_register",
        "NIEDOSTEPNY_REJESTR": "order_register",
        "USZKODZONY_REJESTR": "order_register",
        "BRAK_NAGLOWKA_REJESTRU": "order_register",
        "POWTORZONY_NAGLOWEK_REJESTRU": "order_register",
        "BRAK_ARKUSZA_ZLECEN": "order_register",
        "ZLECENIA_W_WIELU_ARKUSZACH": "order_register",
        "WIERSZ_BEZ_DATY": "order_register",
        "ZLE_SKUTECZNE": "order_register",
        "NIEZNANY_WYKONAWCA": "order_register",
        "BRAK_ZLECEN_OKRESU": "order_register",
        "PRZERWANO_NIEPELNY_OKRES": "order_register",
    },
    "przebieg-rozliczen": {
        "PLIK_ZBIORCZY_OTWARTY": "collective_file",
        "NIEDOSTEPNY_PLIK_ZBIORCZY": "collective_file",
        "ZLY_PLIK_ZBIORCZY": "collective_file",
        "NIEZNANY_WYKONAWCA": "collective_file",
        "WIERSZE_BEZ_WYKONAWCY": "collective_file",
    },
}
SAMPLES: dict[str, Samples] = {
    "przygotowanie-pliku-zbiorczego": PREPARATION_SAMPLES,
    "przebieg-rozliczen": SETTLEMENT_SAMPLES,
}


@pytest.mark.parametrize("catalog", SAMPLES)
def test_komunikat_wskazuje_plik_taty_tylko_gdy_poprawka_jest_w_tym_pliku(catalog: str) -> None:
    messages = [sample() for samples in SAMPLES[catalog].values() for sample in samples]

    assert {message.code: message.dad_file for message in messages if message.dad_file} == DAD_FILES[catalog]
