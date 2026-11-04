"""Reguła danych (ADR 0025) na interfejsie ``client_data``: które wartości strażnik zna i jak je maskuje.

Strażnika wołają cztery wysyłki Centrum (Logi, Zgłoszenie, Kontrola ilości, Uwaga taty), więc macierz reguły jest tu raz,
a każda wysyłka ma swój test przez HTTP API. Położenie wartości w tekście, wielkość liter i znaki między jej słowami
sprawdzają własności w ``test_wlasnosci_dopasowania_tekstu.py``. Wartości są syntetyczne.
"""

from __future__ import annotations

from rozliczenia.client_data import MIN_VALUE, ForbiddenColumn, ForbiddenValues, Guarded, free_text

ADDRESS_NOTE = "Reguła danych: zamaskowano wartość kolumny ADRES w: tekst."
ORANGE_NOTE = "Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: tekst."


def test_wartosc_krotsza_niz_piec_znakow_nie_jest_zakazana_a_piec_znakow_juz_jest() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Lipa")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, " „Lipno")

    guarded = forbidden.guard("Lipa kwitnie przy drodze na Lipno", "tekst")

    assert MIN_VALUE == 5
    assert guarded == Guarded("Lipa kwitnie przy drodze na [adres]", (ADDRESS_NOTE,))


def test_z_dwoch_wartosci_od_tego_samego_slowa_maskowana_jest_cala_dluzsza() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5 m 7")

    longer = forbidden.guard("klient Syntetyczna Lipowa 5 m 7 dzwonić", "tekst")
    shorter = forbidden.guard("klient Syntetyczna Lipowa 5, dzwonić", "tekst")

    assert (longer.text, shorter.text) == ("klient [adres] dzwonić", "klient [adres], dzwonić")


def test_numer_orange_ktory_excel_czyta_jako_liczbe_ulamkowa_jest_zamaskowany_w_zapisie_cyfr() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 4801234567.0)

    guarded = forbidden.guard("umowa 4801234567 aktywna", "tekst")

    assert guarded == Guarded("umowa [numer Orange] aktywna", (ORANGE_NOTE,))


def test_wartosc_zapamietana_pod_dwiema_kolumnami_jest_maskowana_jak_pierwsza() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, "SYN-48012")
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "syn 48012")

    assert forbidden.guard("umowa SYN 48012", "tekst") == Guarded("umowa [numer Orange]", (ORANGE_NOTE,))


def test_kazda_praca_centrum_ma_wlasna_pamiec_zakazanych_wartosci() -> None:
    first, second = ForbiddenValues(), ForbiddenValues()
    first.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Lipowa 5")

    assert second.guard("Syntetyczna Lipowa 5", "tekst") == Guarded("Syntetyczna Lipowa 5", ())


def test_numer_zlecenia_po_krzyzyku_nie_jest_telefonem_a_te_same_cyfry_bez_krzyzyka_sa() -> None:
    # NUMER ZL. to „#” i numer, który może wyjść (ADR 0025); dziś ma 8 cyfr, a 9 cyfr to kształt telefonu.
    assert free_text("zlecenie #123456789 zrobione") == "zlecenie #123456789 zrobione"
    assert free_text("zlecenie 123456789 zrobione, oddzwonić +48123456789") == "zlecenie [telefon] zrobione, oddzwonić [telefon]"
