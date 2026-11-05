"""Komentarz Logów Uruchomienia w Skrzynce Zgłoszeń (#320, #844): to, czego testy przez HTTP nie osiągną tanio.

Logi ponad limit komentarza GitHuba wymagałyby przez HTTP setek Komunikatów, więc to, że i tak idą jednym komentarzem
z pełnymi Logami w Archiwum Logów okresu, sprawdza wysyłka zbudowana wprost z rekordu (``logi_post``): jej części to
dokładnie komentarze, które kolejka dopisuje do issue, a jej plik to plik w Archiwum.
Podsumowanie ma tu tylko przypadki bez taniej drogi przez HTTP z fikstur Przebiegu: nazwa Przygotowania,
powtórki kodów, powtórzone Zatrzymanie, Zatrzymanie po odmowie w Decyzji taty, czas w sekundach albo nieznany, brak commitu i sprawdzenia Diagnozy,
które nie przeszły albo których nie sprawdzono. Resztę sprawdza ``test_centrum_logi_w_skrzynce.py``. Strażnik reguły
danych (``guarded``, ADR 0025) ma tu klucz słownika Logów z zakazaną wartością: klucze pochodzą dziś z zamkniętych
list (operator z reguły taty, kod pozycji efenix, litera kolumny), więc przez HTTP żadna taka wartość do klucza nie
trafia, i liczbę policzoną przez narzędzie w kształcie telefonu, której syntetyczne pliki taty przez HTTP nie dają.
"""

from __future__ import annotations

from decimal import Decimal
import gzip
from typing import Any

from pydantic import ValidationError
import pytest

from rozliczenia.centrum.report_box import COMMENT_LIMIT, REPOSITORY
from rozliczenia.centrum.run_logs import RunLog, guarded, logi_post, summary_markdown
from rozliczenia.client_data import ForbiddenColumn, ForbiddenValues
from tests.fixtures.formy_telefonu import COMPUTED, PHONE

RUN_ID = "627b45fe219e4274b722953c34d4af54"
STOP = {"kind": "stop", "code": "ZLA_KONFIGURACJA_WYKONAWCOW", "what": "Co.", "where": "Gdzie.", "action": "Zrób."}


def warning(code: str, what: str = "Co.") -> dict[str, str]:
    return {"kind": "warning", "code": code, "what": what, "where": "Gdzie.", "action": "Zrób."}


def record(**changes: Any) -> RunLog:
    fields: dict[str, Any] = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "process": "settlement",
        "mode": "zapis",
        "period": "08_14_09_2026",
        "started_at": "2026-10-23T20:47:20.846240Z",
        "ended_at": "2026-10-23T20:47:20.857060Z",
        "duration_ms": 10,
        "tool": {"wydanie": None, "commit": "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"},
        "result": "OK",
        "ending": "finished",
        "stop_kind": None,
        "issue_count": 0,
        "messages": [],
        "technical_notes": [],
        "summary": None,
        "phases": [],
        "templates": [],
        "environment": {"system": "Windows-11", "python": "3.12.10", "files": None},
        "trace": None,
        "diagnosis": None,
    }
    return RunLog.model_validate({**fields, **changes})


SUMMARY_LINES: dict[str, tuple[dict[str, Any], list[str]]] = {
    "przygotowanie-podglad": (
        {"process": "preparation", "mode": "podgląd"},
        ["**Logi Uruchomienia**: Przygotowanie pliku zbiorczego, podgląd, okres 08_14_09_2026"],
    ),
    "uporzadkowanie-intermax": (
        {"process": "intermax"},
        ["**Logi Uruchomienia**: Uporządkowanie INTERMAX, zapis, okres 08_14_09_2026"],
    ),
    "ostrzezenia-z-powtorzeniami": (
        {"result": "WYMAGA_SPRAWDZENIA", "messages": [warning("BRAK_MAPOWANIA"), warning("NIEZNANE_URZADZENIA"), warning("BRAK_MAPOWANIA")]},
        [
            "- Wynik: WYMAGA_SPRAWDZENIA",
            "- Komunikaty: `BRAK_MAPOWANIA` ×2 (ostrzeżenie), `NIEZNANE_URZADZENIA` (ostrzeżenie)",
        ],
    ),
    "powtorka": (
        {"result": "BLAD_KRYTYCZNY", "ending": "stop", "stop_kind": "repeated", "messages": [STOP]},
        ["- Wynik: BLAD_KRYTYCZNY, powtórzone Zatrzymanie dla taty"],
    ),
    "odmowa-w-decyzji-taty": (
        {"result": "BLAD_KRYTYCZNY", "ending": "declined", "stop_kind": "declined", "messages": [STOP]},
        ["- Wynik: BLAD_KRYTYCZNY, Zatrzymanie po odmowie w Decyzji taty"],
    ),
    "czas-nieznany": (
        {"result": "BLAD_KRYTYCZNY", "ending": "unexpected", "stop_kind": "for_maks", "duration_ms": None},
        ["- Czas: nieznany"],
    ),
    "czas-w-sekundach": (
        {"result": "BLAD_KRYTYCZNY", "ending": "after_engine", "stop_kind": "for_maks", "duration_ms": 12_345},
        ["- Czas: 12,3 s"],
    ),
    "diagnoza": (
        {
            "diagnosis": {
                "diagnosed_at": "2026-10-23T20:48:02.120000Z",
                "explanation": {"code": "BRAK_WZORCA", "what": "Co.", "where": "Gdzie.", "action": "Zrób."},
                "next_action": "report",
                "checks": [
                    {"label": "Ustawienia taty", "state": "passed", "detail": "Są.", "code": None},
                    {"label": "Wzorzec pliku zbiorczego", "state": "failed", "detail": "Co.", "code": "BRAK_WZORCA"},
                    {"label": "Folder okresu", "state": "failed", "detail": "Co.", "code": "BRAK_FOLDERU"},
                    {"label": "Aktualność narzędzia", "state": "not_checked", "detail": "Bez sieci.", "code": None},
                ],
            }
        },
        [
            "- Diagnoza: `BRAK_WZORCA`; nie przeszło: Wzorzec pliku zbiorczego, Folder okresu; "
            "nie sprawdzono: Aktualność narzędzia"
        ],
    ),
    "diagnoza-bez-przyczyny": (
        {
            "diagnosis": {
                "diagnosed_at": "2026-10-23T20:48:02.120000Z",
                "explanation": {"code": "NIE_ZNALEZIONO_PRZYCZYNY", "what": "Co.", "where": "Gdzie.", "action": "Zrób."},
                "next_action": "report",
                "checks": [{"label": "Ustawienia taty", "state": "passed", "detail": "Są.", "code": None}],
            }
        },
        ["- Diagnoza: `NIE_ZNALEZIONO_PRZYCZYNY`"],
    ),
    "z-wydaniem": (
        {"tool": {"wydanie": "0.10.0", "commit": "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"}},
        ["- Wydanie: 0.10.0, commit 3c1d0a9"],
    ),
    "bez-commitu": (
        {"tool": {"wydanie": None, "commit": None}},
        ["- Wydanie: brak, commit nieznany"],
    ),
}


@pytest.mark.parametrize(("changes", "lines"), SUMMARY_LINES.values(), ids=SUMMARY_LINES.keys())
def test_podsumowanie_nazywa_wynik_sposob_zakonczenia_i_kody_komunikatow(
    changes: dict[str, Any], lines: list[str]
) -> None:
    summary = summary_markdown(record(**changes)).splitlines()

    assert [line for line in lines if line not in summary] == []


def test_logi_ponad_limit_komentarza_ida_jednym_komentarzem_a_cale_w_pliku_archiwum_logow_okresu() -> None:
    logs = record(
        result="WYMAGA_SPRAWDZENIA",
        messages=[warning("BRAK_MAPOWANIA", f"Wiersz {row}: {'ż' * 300}") for row in range(600)],
    )
    assert len(logs.text) > 3 * COMMENT_LIMIT

    post = logi_post(logs)

    name = f"20261023T204720Z-settlement-{RUN_ID}.json.gz"
    link = f"https://github.com/{REPOSITORY}/releases/download/logi-08_14_09_2026/{name}"
    [comment] = post.parts
    assert comment == f"{summary_markdown(logs)}\n"
    assert comment.splitlines()[-1] == f"- Pełne Logi: [{name}]({link})"
    assert post.archive is not None
    assert (post.archive.tag, post.archive.packed_name, post.archive.link) == ("logi-08_14_09_2026", name, link)
    assert gzip.decompress(post.archive.packed()).decode("utf-8") == logs.text


def test_zakazana_wartosc_w_kluczu_slownika_logow_jest_zamaskowana_z_uwaga_o_polu_bez_wartosci() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Kwarcowa 9")
    logs = record(process="intermax", intermax_entries={"rows": {"SYNTETYCZNA KWARCOWA 9": [12]}, "without_entry": []})

    kept = guarded(logs, forbidden)

    assert kept.intermax_entries is not None
    assert kept.intermax_entries.rows == {"[adres]": [12]}
    assert kept.technical_notes == ["Reguła danych: zamaskowano wartość kolumny ADRES w: intermax_entries.rows."]
    post = logi_post(kept)
    assert post.archive is not None
    assert gzip.decompress(post.archive.packed()).decode("utf-8") == kept.text
    assert all("Kwarcowa" not in text for text in (*post.parts, kept.text))


def test_liczba_policzona_przez_narzedzie_w_ksztalcie_telefonu_zostaje_a_ta_sama_liczba_z_komorki_jest_telefonem() -> None:
    """Strażnik liczby sprawdza tylko wartości z komórek pliku taty (ADR 0025): numer wiersza i rozmiar pliku w Kopii
    wejścia policzyło narzędzie, więc zostają, choć mają kształt telefonu, a te same liczby w komórkach są ``[telefon]``."""

    row, size = (form.value for form in COMPUTED)
    sheet = {"sheet": "Sheet1", "header_row": 17, "columns": {}, "rows": [{"row": row, "cells": {"AS": row, "AT": size}}], "empty_rows": []}
    copied = {"name": "plik.xlsx", "fingerprint": {"size": size, "modified_at": None, "sha256": "0" * 64}, "sheets": [sheet]}

    kept = guarded(record(input_copy=[copied]), ForbiddenValues())

    assert kept.input_copy is not None
    [file] = kept.input_copy
    [logged] = file.sheets[0].rows
    assert (file.fingerprint.size, logged.row, logged.cells) == (size, row, {"AS": PHONE, "AT": PHONE})
    assert (kept.technical_notes, kept.input_copy_notes) == ([], [])


def _step(amount: str | None) -> dict[str, Any]:
    return {
        "action": "otwarcie zlecenia",
        "started_at": "2026-10-23T20:47:20.846240Z",
        "duration_ms": 20,
        "found": None,
        "execution_date": None,
        "amount": amount,
        "quantities": None,
        "position": None,
        "quantity": None,
        "accepted": None,
    }


def test_maska_w_kwocie_logow_nie_gubi_logow_tylko_kwote_albo_zlecenie_z_uwaga_o_polu() -> None:
    """Kwota w Logach jest liczbą ``Decimal``, więc maska strażnika (numer Orange ``12345`` w ``12345.67``) w niej nie
    stoi: kwota strony, która może być pusta, jest pusta, a zlecenie z kwotą z pliku, która pusta być nie może, odpada,
    każde z uwagą techniczną o polu bez wartości; reszta Logów wychodzi, a numer z nich znika."""

    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, 12345)
    orders = [
        {"row": 18, "outcome": "gotowe", "code": None, "file": {}, "file_amount": "12345.67", "steps": [_step(None)]},
        {"row": 19, "outcome": "gotowe", "code": None, "file": {}, "file_amount": "10.00", "steps": [_step("12345.67")]},
    ]
    logs = record(process="efenix", efenix_orders=orders)

    kept = guarded(logs, forbidden)

    assert kept.efenix_orders is not None
    assert [(order.row, order.file_amount, order.steps[0].amount) for order in kept.efenix_orders] == [(19, Decimal("10.00"), None)]
    assert kept.technical_notes[-2:] == [
        "Reguła danych: pominięto efenix_orders[0]: strażnik zamaskował w nim wartość, której pole nie przyjmuje.",
        "Reguła danych: pole efenix_orders[1].steps[0].amount jest puste: strażnik zamaskował w nim wartość, której pole "
        "nie przyjmuje.",
    ]
    assert "12345" not in kept.text


def test_maska_w_chwili_zmiany_pliku_kopii_wejscia_daje_puste_pole_z_uwaga_kopii_a_nie_karty() -> None:
    """Chwila zmiany pliku w Kopii wejścia jest datą, więc numer Orange ``123456Z`` w niej (część ułamkowa sekundy z
    oznaczeniem UTC) zostawia pole puste, a uwaga idzie do uwag Kopii, których karta nie pokazuje."""

    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, "123456Z")
    fingerprint = {"size": 10, "modified_at": "2026-10-23T20:47:20.123456Z", "sha256": "0" * 64}
    logs = record(input_copy=[{"name": "plik.xlsx", "fingerprint": fingerprint, "sheets": []}])

    kept = guarded(logs, forbidden)

    assert kept.input_copy is not None
    assert kept.input_copy[0].fingerprint.modified_at is None
    assert kept.input_copy_notes[-1] == (
        "Reguła danych: pole input_copy[0].fingerprint.modified_at jest puste: strażnik zamaskował w nim wartość, "
        "której pole nie przyjmuje."
    )
    assert kept.technical_notes == []


def test_maska_w_chwili_startu_uruchomienia_zostaje_bledem_walidacji_logow() -> None:
    """Granica: pole Logów najwyższego poziomu bez ``None`` (chwila startu) nie ma czego pominąć, więc Logi z maską w
    nim nie powstają; tę chwilę daje zegar Centrum, nie plik taty."""

    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ORANGE, "846240Z")

    with pytest.raises(ValidationError, match="started_at"):
        guarded(record(), forbidden)
