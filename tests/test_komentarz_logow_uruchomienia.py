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
Pełne Logi z każdym polem schematu (``FULL_LOGS``) niesie tylko ten plik: przemiatanie kształtów pól (#936) daje
strażnikowi każdy ich tekst jako wartość z pliku taty, a przez HTTP jedno Uruchomienie nie wypełnia wszystkich pól.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
import gzip
import json
from typing import Any, Final

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


_FULL_STEP: Final[dict[str, Any]] = {
    "action": "Wycena Emmetta",
    "started_at": "2026-10-23T20:48:01.300000Z",
    "duration_ms": 250,
    "found": 1,
    "execution_date": "2026-10-20",
    "amount": "67.89",
    "quantities": {"014": 3},
    "position": "Pozycja testowa",
    "quantity": 4,
    "accepted": True,
    "results": [{"same_number": True, "status": "Status syntetyczny", "realizator": "realizator.testowy", "address": ["lokal"]}],
    "status": "Status otwarty",
    "realizator": "otwierajacy.testowy",
}
# Pełne Logi: każde pole schematu ma wartość, a każda wartość jest jedna w Logach. Tekst spoza zamkniętych list i pól
# narzędzia to syntetyczna treść plików taty i strony efenix.
FULL_LOGS: Final[dict[str, Any]] = {
    "schema_version": 2,
    "run_id": RUN_ID,
    "process": "efenix",
    "mode": "zapis",
    "period": "08_14_09_2026",
    "started_at": "2026-10-23T20:47:20.846240Z",
    "ended_at": "2026-10-23T20:49:31.857060Z",
    "duration_ms": 131_011,
    "tool": {"wydanie": "0.10.0", "commit": "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"},
    "result": "WYMAGA_SPRAWDZENIA",
    "ending": "after_engine",
    "stop_kind": "for_maks",
    "issue_count": 3,
    "messages": [
        {"kind": "warning", "code": "EFENIX_SPRZECZNOSC", "what": "Syntetyczny opis różnicy", "where": "Wiersz osiemnasty", "action": "Popraw ilość ręcznie"}
    ],
    "technical_notes": ["Syntetyczna uwaga techniczna"],
    "summary": {
        "figures": [{"label": "Zlecenia wycenione", "value": 4, "unit": "count"}],
        "counts": {"title": "Pozycje syntetyczne", "counts": [{"label": "Montaż gniazda", "count": 2}], "zero_warns": False},
        "files": [{"name": "Plik zbiorczy syntetyczny.xlsx", "kind": "collective_file"}],
        "worker_settlements": [{"worker": "Wykonawca Testowy", "file": "Rozliczenie Testowe.xlsx", "orders": 3, "empty": False}],
        "intermax_copy": "Kopia INTERMAX syntetyczna.xlsx",
    },
    "phases": [
        {
            "phase": "Planowanie",
            "state": "completed",
            "duration_ms": 5,
            "started_at": "2026-10-23T20:47:21.100000Z",
            "ended_at": "2026-10-23T20:47:21.105000Z",
        }
    ],
    "templates": [
        {
            "wykonawca": "Wykonawca Szablonowy",
            "outcome": "ZAPISANO",
            "rows": 7,
            "duration_ms": 40,
            "started_at": "2026-10-23T20:47:22.200000Z",
            "ended_at": "2026-10-23T20:47:22.240000Z",
        }
    ],
    "inea_only_cleared": {"AK": 2},
    "intermax_entries": {"rows": {"Operator Syntetyczny": [12, 13]}, "without_entry": [{"row": 14, "operator": "Operator Hurtowy"}]},
    "efenix_orders": [
        {
            "row": 18,
            "outcome": "ostrzeżenie Emmetta",
            "code": "EFENIX_KOD_ZLECENIA",
            "file": {"012": 1, "013": "Ilość tekstem"},
            "file_amount": "123.45",
            "steps": [_FULL_STEP],
        }
    ],
    "efenix_stop": {
        "cause": {
            "part": "Strona syntetyczna",
            "what": "Przyczyna syntetyczna",
            "positions": ["015"],
            "element": "selektor-syntetyczny",
            "count": 2,
            "status": 503,
            "error_type": "PlaywrightTimeout",
            "operation": "kliknięcie",
        },
        "row": 19,
        "order": 2,
        "orders": 4,
        "steps": [{**_FULL_STEP, "action": "szukanie", "started_at": "2026-10-23T20:48:30.100000Z"}],
        "failed": {**_FULL_STEP, "action": "ilość", "started_at": "2026-10-23T20:48:40.200000Z"},
    },
    "environment": {
        "system": "Windows-11-10.0.26100-SP0",
        "python": "3.12.10",
        "files": [{"name": "Rejestr syntetyczny.xlsx", "size": 2048, "online_only": False}],
    },
    "trace": {
        "exception_type": "rozliczenia.efenix_pricing.PricingStopped",
        "frames": [{"file": "src/rozliczenia/efenix_pricing.py", "line": 120, "function": "price_orders"}],
        "causes": [
            {"exception_type": "TimeoutError", "frames": [{"file": "src/rozliczenia/efenix_window.py", "line": 45, "function": "wait_for_page"}]}
        ],
    },
    "diagnosis": {
        "diagnosed_at": "2026-10-23T20:52:00.400000Z",
        "explanation": {"code": "BRAK_WZORCA", "what": "Opis diagnozy", "where": "Miejsce diagnozy", "action": "Działanie diagnozy"},
        "next_action": "report",
        "checks": [{"label": "Wzorzec syntetyczny", "state": "failed", "detail": "Szczegół sprawdzenia", "code": "BRAK_WZORCA_KOD"}],
    },
    "dad_actions": {
        "entries": [
            {"at": "2026-10-23T20:40:00.500000Z", "action": "start Centrum"},
            {"at": "2026-10-23T20:41:00.600000Z", "action": "widok", "page": "okresy", "kind": "cold_start"},
            {"at": "2026-10-23T20:47:20.700000Z", "action": "przycisk", "operation": "startRun", "process": "efenix", "mode": "zapis"},
        ],
        "omitted": 0,
    },
    "interruption": {"row": 20, "place": 3, "total": 4, "omitted": 1},
    "input_copy": [
        {
            "name": "Plik zbiorczy taty.xlsx",
            "fingerprint": {"size": 4096, "modified_at": "2026-10-22T08:00:00.900000Z", "sha256": "ab" * 32},
            "sheets": [
                {
                    "sheet": "Arkusz syntetyczny",
                    "header_row": 17,
                    "columns": {"C": "WYKONAWCA"},
                    "rows": [
                        {
                            "row": 18,
                            "cells": {"C": "Komórka syntetyczna", "D": {"type": "datetime", "text": "2026-10-21 00:00:00"}, "E": 12.5, "F": True},
                        }
                    ],
                    "empty_rows": [21],
                    "shifted_row": 22,
                    "uncertain_rows": [23],
                    "last_ordered_row": 16,
                    "yellow_row": 15,
                }
            ],
            "folders": ["Folder nadrzędny", "Folder okresu"],
        }
    ],
    "input_copy_notes": ["Syntetyczna uwaga kopii"],
}


def full_logs(**changes: Any) -> RunLog:
    return RunLog.model_validate({**FULL_LOGS, **changes})


def _json_at(logs: RunLog, place: str) -> str:
    """Pole ``place`` (nazwy pól po kropce) w JSON-ie Logów ``logs``."""

    value: Any = logs.model_dump(mode="json")
    for key in place.split("."):
        value = value[key]
    return json.dumps(value, ensure_ascii=False)


# Pola Logów, które niosą tylko słowa i chwile narzędzia (ADR 0025, #936), i wartość z każdego z nich w pełnych Logach.
TOOL_FIELDS: Final = {
    "run_id": RUN_ID,
    "process": "efenix",
    "mode": "zapis",
    "period": "08_14_09_2026",
    "started_at": "2026-10-23T20:47:20.846240Z",
    "ended_at": "2026-10-23T20:49:31.857060Z",
    "tool": "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e",
    "result": "WYMAGA_SPRAWDZENIA",
    "ending": "after_engine",
    "stop_kind": "for_maks",
    "phases": "Planowanie",
    "trace": "price_orders",
    "dad_actions": "startRun",
    "environment.system": "Windows-11-10.0.26100-SP0",
    "environment.python": "3.12.10",
}


@pytest.mark.parametrize(("place", "value"), TOOL_FIELDS.items(), ids=TOOL_FIELDS.keys())
def test_pole_ze_slowami_i_chwilami_narzedzia_zostaje_w_logach_choc_plik_taty_ma_te_wartosc_w_kolumnie_adres(
    place: str, value: str
) -> None:
    """Strażnik porównuje słowa, a nie pochodzenie wartości (#936): wartość z kolumny ``ADRES`` pliku taty równa słowu
    albo chwili narzędzia zostaje w polu, które niesie tylko to, co dało narzędzie. Logi powstają i idą do issue swojego
    okresu jako swoje Uruchomienie, a w Komunikacie, który cytuje komórkę, ta wartość jest maską."""

    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, value)
    logs = full_logs(messages=[{**FULL_LOGS["messages"][0], "where": f"Komórka „{value}”."}])
    assert forbidden.guard(_json_at(logs, place), place).notes, "pole ma wartość z kolumny ADRES"

    kept = guarded(logs, forbidden)

    assert _json_at(kept, place) == _json_at(logs, place)
    assert kept.messages[0].where == "Komórka „[adres]”."
    post = logi_post(kept)
    assert (post.run_id, post.period) == (RUN_ID, "08_14_09_2026")


def _texts(value: object) -> Iterator[tuple[str, bool]]:
    """Każdy tekst JSON-a Logów: klucz (``True``) albo wartość tekstowa (``False``)."""

    if isinstance(value, dict):
        for key, entry in value.items():
            yield key, True
            yield from _texts(entry)
    elif isinstance(value, list):
        for entry in value:
            yield from _texts(entry)
    elif isinstance(value, str):
        yield value, False


def _schema_words() -> tuple[set[str], set[str]]:
    """Nazwy pól i wartości zamkniętych list schematu Logów (``RunLog.model_json_schema``)."""

    names: set[str] = set()
    closed: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            closed.update(str(value) for value in node.get("enum", ()))
            if "const" in node:
                closed.add(str(node["const"]))
            for entry in node.values():
                walk(entry)
        elif isinstance(node, list):
            for entry in node:
                walk(entry)

    walk(RunLog.model_json_schema())
    return names, closed


def test_kazdy_tekst_pelnych_logow_jako_adres_z_pliku_taty_daje_logi_bez_niego_poza_slowami_narzedzia() -> None:
    """Przemiatanie kształtów pól (#936): każdy tekst pełnych Logów, wartość i klucz, po kolei jako wartość kolumny
    ``ADRES`` z pliku taty. Logi powstają za każdym razem, także gdy to nazwa pola schematu, słowo zamkniętej listy albo
    wartość pola narzędzia, a pola narzędzia mają wartość z rekordu. Wartość spoza słów narzędzia nie zostaje nigdzie w
    tekście Logów, a nazwa pola, której nie ma w żadnej wartości, nie zmienia Logów wcale."""

    logs = full_logs()
    texts = list(_texts(logs.model_dump(mode="json")))
    names, closed = _schema_words()
    assert names <= {text for text, key in texts if key}, "pełne Logi mają każde pole schematu"
    values = "\n".join(text for text, key in texts if not key)
    tool_words = "\n".join([*names, *closed, *(_json_at(logs, place) for place in TOOL_FIELDS)])

    swept = 0
    for word in sorted({text for text, _ in texts}):
        forbidden = ForbiddenValues()
        forbidden.remember_value(ForbiddenColumn.ADDRESS, word)
        if not forbidden.guard(word, "").notes:
            continue  # krótsza niż ``MIN_VALUE``: strażnik jej nie szuka
        swept += 1

        kept = guarded(logs, forbidden)

        assert logi_post(kept).run_id == RUN_ID, word
        assert [place for place in TOOL_FIELDS if _json_at(kept, place) != _json_at(logs, place)] == [], word
        if not forbidden.guard(tool_words, "").notes:
            assert not forbidden.guard(kept.text, "").notes, f"{word!r} zostało w Logach"
        if word in names and not forbidden.guard(values, "").notes:
            assert kept == logs, word
    assert swept > len(names)
