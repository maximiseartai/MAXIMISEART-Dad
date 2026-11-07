"""Komentarz Logów Uruchomienia w Skrzynce Zgłoszeń (#320, #844): to, czego testy przez HTTP nie osiągną tanio.

Logi ponad limit komentarza GitHuba wymagałyby przez HTTP setek Komunikatów, więc to, że i tak idą jednym komentarzem
z pełnymi Logami w Archiwum Logów okresu, sprawdza wysyłka zbudowana wprost z rekordu (``post_of``): jej części to
dokładnie komentarze, które kolejka dopisuje do issue, a jej plik to plik w Archiwum.
Podsumowanie ma tu tylko przypadki bez taniej drogi przez HTTP z fikstur Przebiegu: nazwa Przygotowania,
powtórki kodów, powtórzone Zatrzymanie, Zatrzymanie po odmowie w Decyzji taty, czas w sekundach albo nieznany, brak commitu i sprawdzenia Diagnozy,
które nie przeszły albo których nie sprawdzono. Resztę sprawdza ``test_centrum_logi_w_skrzynce.py``. Strażnik reguły
danych (``guarded``, ADR 0025) ma tu klucz słownika Logów z zakazaną wartością: klucze pochodzą dziś z zamkniętych
list (operator z reguły taty, kod pozycji efenix, litera kolumny), więc przez HTTP żadna taka wartość do klucza nie
trafia, i liczbę policzoną przez narzędzie w kształcie telefonu, której syntetyczne pliki taty przez HTTP nie dają.
Pełne Logi z każdym polem schematu (``FULL_LOGS``) niesie tylko ten plik: przemiatanie kształtów pól (#936) daje
strażnikowi każdą ich wartość jako wartość z pliku taty, a przez HTTP jedno Uruchomienie nie wypełnia wszystkich pól.
Typy pól, które strażnik zostawia bez maski (``TOOL_FIELDS``), sprawdza tu test struktury na schemacie Logów.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
import copy
import dataclasses
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import gzip
import json
from pathlib import Path
import pickle
from types import SimpleNamespace, UnionType
from typing import Annotated, Any, Final, Literal, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel
import pytest

from rozliczenia.centrum.report_box import COMMENT_LIMIT, REPOSITORY
from rozliczenia.centrum.comment_versions import (
    LABEL,
    CommentVersion,
    OwnLogs,
    ProgressVersion,
    ResultWithoutLogs,
    StandInLogs,
    WithoutLogsVersion,
    journal_after,
    post_of,
    progress_markdown,
    summary_markdown,
    without_logs_markdown,
)
from rozliczenia.centrum.outbox import PeriodThread, Rank
from rozliczenia.centrum.run_logs import (
    READ_VALUES,
    TOOL_FIELDS,
    OrderDone,
    PricingProgress,
    RunLog,
    RunLogs,
    StartFacts,
    guard_logs,
    guard_text,
    guarded,
)
from rozliczenia.client_data import MIN_VALUE, ForbiddenColumn, ForbiddenValues, shown
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

    post = post_of(OwnLogs(guard_logs(logs, ForbiddenValues())))

    name = f"20261023T204720Z-settlement-{RUN_ID}.json.gz"
    link = f"https://github.com/{REPOSITORY}/releases/download/logi-08_14_09_2026/{name}"
    [comment] = post.parts
    assert comment == f"{summary_markdown(logs)}\n"
    assert comment.splitlines()[-1] == f"- Pełne Logi: [{name}]({link})"
    assert post.archive is not None
    assert (post.archive.tag, post.archive.packed_name, post.archive.link) == ("logi-08_14_09_2026", name, link)
    assert gzip.decompress(post.archive.packed()).decode("utf-8") == logs.text


def _versions() -> dict[str, CommentVersion]:
    """Każda wersja komentarza jednego Uruchomienia Wyceny w efenix, z tekstem po strażniku."""

    logs = guard_logs(record(process="efenix", run_id=RUN_ID), ForbiddenValues())
    started = StartFacts(
        run_id=RUN_ID, process="efenix", mode="zapis", period="08_14_09_2026", started_at=logs.record.started_at
    )
    progress = PricingProgress(started, (OrderDone(18, "gotowe", None),), 2, 19)
    text = guard_text("Postęp albo wynik bez Logów.", "komentarz", ForbiddenValues())
    return {
        "postep": ProgressVersion(progress, text),
        "logi-z-pliku-albo-urwane": StandInLogs(logs),
        "wynik-bez-logow": WithoutLogsVersion(ResultWithoutLogs(progress, "OK", "niezapisane"), text),
        "logi-z-wynikiem-albo-diagnoza": OwnLogs(logs),
    }


# Stopień wersji (GLOSSARY „Logi Uruchomienia”, #910): postęp najniższy, wersja zastępcza ze startu Centrum niższa niż
# Logi z wynikiem, a Logi z pracy Centrum Uruchomienia najwyższe.
RANKS: Final = {
    "postep": Rank.DRAFT,
    "logi-z-pliku-albo-urwane": Rank.STAND_IN,
    "wynik-bez-logow": Rank.STAND_IN,
    "logi-z-wynikiem-albo-diagnoza": Rank.OWN,
}


@pytest.mark.parametrize(("kind", "rank"), RANKS.items(), ids=RANKS.keys())
def test_kazda_wersja_komentarza_uruchomienia_to_ta_sama_wysylka_w_swoim_stopniu_a_plik_w_archiwum_maja_tylko_logi(
    kind: str, rank: Rank
) -> None:
    """Każda wersja komentarza Uruchomienia idzie do issue Logów okresu jako ta sama wysyłka (Uruchomienie i etykieta),
    więc kolejka zmienia jeden komentarz, w stopniu, który wybiera nadawca (#910). Pełny plik w Archiwum Logów okresu
    mają tylko Logi: postęp i wynik bez Logów go nie mają."""

    version = _versions()[kind]

    post = post_of(version)

    assert isinstance(post.target, PeriodThread)
    assert (post.target.label, post.period, post.run_id, post.rank) == (LABEL, "08_14_09_2026", RUN_ID, rank)
    assert (post.archive is not None) == isinstance(version, OwnLogs | StandInLogs)


JOURNAL_AFTER: Final = {
    "postep": ("zostaw", "zostaw"),
    "logi-z-pliku-albo-urwane": ("usuń", "zostaw"),
    "wynik-bez-logow": ("usuń", "zostaw"),
    "logi-z-wynikiem-albo-diagnoza": ("usuń", "zostaw"),
}


@pytest.mark.parametrize(("kind", "after"), JOURNAL_AFTER.items(), ids=JOURNAL_AFTER.keys())
def test_dziennik_wyceny_znika_tylko_po_wersji_koncowej_komentarza_ktora_kolejka_przyjela(
    kind: str, after: tuple[str, str]
) -> None:
    """Dziennik Wyceny w efenix jest śladem komentarza, który może mówić, że Uruchomienie trwa, więc znika tylko wtedy,
    gdy Kolejka wysyłki przyjęła wersję końcową tego komentarza: Logi albo wynik bez Logów (#910). Postęp, także przyjęty,
    dziennika nie usuwa."""

    version = _versions()[kind]

    assert (journal_after(version, accepted=True), journal_after(version, accepted=False)) == after


def _progress() -> PricingProgress:
    """Postęp Wyceny w efenix Uruchomienia ``RUN_ID``: jedno zlecenie skończone z dwóch."""

    started = StartFacts(
        run_id=RUN_ID, process="efenix", mode="zapis", period="08_14_09_2026", started_at=datetime(2026, 9, 10, 8, 0)
    )
    return PricingProgress(started, (OrderDone(18, "gotowe", None),), 2, 19)


def _text_version(kind: str, forbidden: ForbiddenValues) -> ProgressVersion | WithoutLogsVersion:
    """Postęp albo wynik bez Logów Uruchomienia ``RUN_ID`` z tekstem komentarza po strażniku ``forbidden``, tak jak
    buduje je ``RunLogs``."""

    progress = _progress()
    if kind == "postep":
        return ProgressVersion(progress, guard_text(progress_markdown(progress, elapsed_s=90), "postęp", forbidden))
    final = ResultWithoutLogs(progress, "OK", "niezapisane")
    return WithoutLogsVersion(final, guard_text(without_logs_markdown(final), "wynik bez Logów", forbidden))


@pytest.mark.parametrize("kind", ["postep", "wynik-bez-logow"])
def test_postep_i_wynik_bez_logow_ida_do_skrzynki_z_tekstem_po_strazniku(kind: str) -> None:
    """Komentarz postępu i wyniku bez Logów idzie do Skrzynki taki, jaki dał strażnik reguły danych pracy Centrum (ADR
    0025): wartość z kolumny ``ADRES``, która trafiła do jego tekstu (tu w miejscu identyfikatora Uruchomienia), jest
    maską z uwagą techniczną, a nie wartością sprzed strażnika."""

    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, RUN_ID)

    [comment] = post_of(_text_version(kind, forbidden)).parts

    assert RUN_ID not in comment
    assert "- Uwaga techniczna: Reguła danych: zamaskowano wartość kolumny ADRES" in comment


# Drogi do Logów albo tekstu po strażniku bez guard_logs i guard_text, które zamyka sam typ (docstring run_logs._MINTED).
NOT_FROM_GUARD: Final[dict[str, Callable[[Any], object]]] = {
    "replace": lambda value: dataclasses.replace(value, **_field_change(value)),
    "kopia": copy.copy,
    "gleboka-kopia": copy.deepcopy,
    "pickle": lambda value: pickle.loads(pickle.dumps(value)),
    "zmiana-pola": lambda value: setattr(value, "text", "ul. Syntetyczna 1"),
    "zmiana-slotu": lambda value: setattr(value, _slot(value), "ul. Syntetyczna 1"),
    "usuniecie-slotu": lambda value: delattr(value, _slot(value)),
}


def _field_change(value: object) -> dict[str, object]:
    """Zmiana pola, które wartość po strażniku miała, gdy była dataclassą (przed rundą 2 przeglądu #1038): ``record``
    Logów (Logi sprzed strażnika) i ``text`` tekstu."""

    return {"record": record()} if hasattr(value, "record") else {"text": "ul. Syntetyczna 1"}


def _guarded(kind: str) -> Any:
    """Logi (``logi``) albo tekst (``tekst``) po strażniku z ``guard_logs`` i ``guard_text``."""

    return guard_logs(record(), ForbiddenValues()) if kind == "logi" else guard_text("Postęp.", "postęp", ForbiddenValues())


def _slot(value: object) -> str:
    """Nazwa pierwszego slotu wartości po strażniku po name manglingu (``_Klasa__pole``)."""

    kind = type(value)
    slots: tuple[str, ...] = getattr(kind, "__slots__")
    return f"_{kind.__name__}{slots[0]}"


@pytest.mark.parametrize("make", NOT_FROM_GUARD.values(), ids=NOT_FROM_GUARD.keys())
@pytest.mark.parametrize("kind", ["logi", "tekst"])
def test_logi_i_tekst_po_strazniku_nie_powstaja_z_kopii_ani_zmiany_istniejacych(
    kind: str, make: Callable[[Any], object]
) -> None:
    """Logi i tekst po strażniku reguły danych daje tylko ``guard_logs`` i ``guard_text``: kopia, ``replace`` i zmiana
    pola odmawiają, bo wartość, która ich nie przeszła, przeszłaby jako po strażniku (przegląd #1038, runda 1)."""

    value = _guarded(kind)
    text = value.text

    with pytest.raises((TypeError, AttributeError)):
        make(value)

    assert value.text == text


def test_logi_i_tekst_po_strazniku_nie_powstaja_z_konstruktora_bez_dowodu_straznika() -> None:
    logs = guard_logs(record(), ForbiddenValues())
    text = guard_text("Postęp.", "postęp", ForbiddenValues())

    with pytest.raises(TypeError, match="guard_logs"):
        type(logs)(logs.record, logs.record, object())
    with pytest.raises(TypeError, match="guard_text"):
        type(text)("ul. Syntetyczna 1", object())


@pytest.mark.parametrize("kind", ["logi", "tekst"])
def test_logi_i_tekst_po_strazniku_nie_maja_podklas_takze_zrobionych_w_trakcie_dzialania(kind: str) -> None:
    """Podklasa Logów albo tekstu po strażniku mogłaby podać tekst sprzed strażnika jako po strażniku, więc jej
    utworzenie odmawia, także przez ``type()`` w trakcie działania (przegląd #1038, runda 2)."""

    value = _guarded(kind)

    with pytest.raises(TypeError, match="podklas"):
        type("Inne", (type(value),), {"text": property(lambda self: "ul. Syntetyczna 1")})


def _file_of_logs(directory: Path) -> RunLogs:
    """Logi Uruchomienia w katalogu ``directory``, z których test woła tylko plik Logów (``close``)."""

    unused: Any = None
    return RunLogs(
        directory,
        unused,
        commit=unused,
        wydanie=unused,
        files=unused,
        cloud_files=unused,
        dad_actions=unused,
        forbidden=ForbiddenValues(),
    )


# Wszystko, co bierze Logi albo tekst po strażniku: cztery wersje komentarza Uruchomienia i plik Logów.
TAKES_GUARDED: Final[dict[str, Callable[[Any, Path], object]]] = {
    "postep": lambda value, _: ProgressVersion(_progress(), value),
    "wynik-bez-logow": lambda value, _: WithoutLogsVersion(ResultWithoutLogs(_progress(), "OK", "niezapisane"), value),
    "logi-z-pliku-albo-urwane": lambda value, _: StandInLogs(value),
    "logi-z-wynikiem-albo-diagnoza": lambda value, _: OwnLogs(value),
    "plik-logow": lambda value, directory: _file_of_logs(directory).close(value),
}


@pytest.mark.parametrize("take", TAKES_GUARDED.values(), ids=TAKES_GUARDED.keys())
def test_wersje_komentarza_i_plik_logow_odmawiaja_logow_sprzed_straznika_ktorych_typ_nie_widzi(
    take: Callable[[Any, Path], object], tmp_path: Path
) -> None:
    """Logi sprzed strażnika podane przez ``Any`` (np. ``cast(Any, …)`` albo ``# type: ignore``) typ przepuszcza, więc
    wersja komentarza Uruchomienia i plik Logów sprawdzają je przy uruchomieniu i odmawiają, zanim cokolwiek pójdzie do
    Skrzynki albo na dysk (przegląd #1038, runda 2)."""

    raw = record()
    unguarded: Any = SimpleNamespace(record=raw, text=raw.text)

    with pytest.raises(TypeError, match="po strażniku"):
        take(unguarded, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_zakazana_wartosc_w_kluczu_slownika_logow_jest_zamaskowana_z_uwaga_o_polu_bez_wartosci() -> None:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, "Syntetyczna Kwarcowa 9")
    logs = record(process="intermax", intermax_entries={"rows": {"SYNTETYCZNA KWARCOWA 9": [12]}, "without_entry": []})

    guarded_logs = guard_logs(logs, forbidden)
    kept = guarded_logs.record

    assert kept.intermax_entries is not None
    assert kept.intermax_entries.rows == {"[adres]": [12]}
    assert kept.technical_notes == ["Reguła danych: zamaskowano wartość kolumny ADRES w: intermax_entries.rows."]
    post = post_of(OwnLogs(guarded_logs))
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
                            "cells": {
                                "C": "Komórka syntetyczna",
                                "D": {"type": "datetime", "text": "2026-10-21 00:00:00"},
                                "E": 12.5,
                                "F": True,
                                "G": 4801234567,
                                "H": 98765.5,
                            },
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
TOOL_FIELD_VALUES: Final = {
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


@pytest.mark.parametrize(("place", "value"), TOOL_FIELD_VALUES.items(), ids=TOOL_FIELD_VALUES.keys())
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

    guarded_logs = guard_logs(logs, forbidden)
    kept = guarded_logs.record

    assert _json_at(kept, place) == _json_at(logs, place)
    assert kept.messages[0].where == "Komórka „[adres]”."
    post = post_of(OwnLogs(guarded_logs))
    assert (post.run_id, post.period) == (RUN_ID, "08_14_09_2026")


def _scalars(value: object) -> Iterator[tuple[str | int | float, bool]]:
    """Każda wartość skalarna JSON-a Logów (tekst, także chwila i kwota, i liczba; bez ``bool`` i ``None``) i każdy
    klucz: (wartość, czy to klucz)."""

    if isinstance(value, dict):
        for key, entry in value.items():
            yield key, True
            yield from _scalars(entry)
    elif isinstance(value, list):
        for entry in value:
            yield from _scalars(entry)
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        yield value, False


def _numbers(value: object, read: bool = False) -> Iterator[tuple[int | float, bool]]:
    """Każda liczba Logów ``value`` i czy stoi w polu ``READ_VALUES`` (komórki pliku taty, ilości przy zleceniu Wyceny w
    efenix): tylko takie liczby strażnik sprawdza (ADR 0025), a każdą inną policzyło narzędzie."""

    if isinstance(value, BaseModel):
        for name, field in type(value).model_fields.items():
            yield from _numbers(getattr(value, name), read or READ_VALUES in field.metadata)
    elif is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            yield from _numbers(getattr(value, item.name), read)
    elif isinstance(value, Mapping):
        for entry in value.values():
            yield from _numbers(entry, read)
    elif isinstance(value, (list, tuple)):
        for entry in value:
            yield from _numbers(entry, read)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield value, read


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


def test_kazda_wartosc_pelnych_logow_jako_adres_z_pliku_taty_daje_logi_bez_niej_poza_slowami_narzedzia() -> None:
    """Przemiatanie kształtów pól (#936): każda wartość skalarna pełnych Logów (tekst, chwila, kwota, liczba, także
    liczba z komórki pliku taty) i każdy klucz po kolei jako wartość kolumny ``ADRES`` z pliku taty. Pełne Logi mają
    wartość w każdym polu ``RunLog``, a Logi powstają za każdym razem, także gdy to nazwa pola schematu, słowo zamkniętej
    listy, wartość pola narzędzia albo liczba, którą policzyło narzędzie, a pola narzędzia mają wartość z rekordu.
    Wartość spoza słów narzędzia nie zostaje nigdzie w tekście Logów, a nazwa pola, której nie ma w żadnym tekście, nie
    zmienia Logów wcale."""

    assert set(RunLog.model_fields) <= set(FULL_LOGS), "pełne Logi mają wartość w każdym polu Logów"
    logs = full_logs()
    scalars = list(_scalars(logs.model_dump(mode="json")))
    names, closed = _schema_words()
    assert names <= {value for value, key in scalars if key}, "pełne Logi mają każde pole schematu"
    numbers = list(_numbers(logs))
    assert [number for number, read in numbers if read and len(shown(number)) >= MIN_VALUE], "liczba z komórki w Logach"
    texts = "\n".join(value for value, key in scalars if isinstance(value, str) and not key)
    tool_numbers = (shown(number) for number, read in numbers if not read)
    tool_words = "\n".join([*names, *closed, *tool_numbers, *(_json_at(logs, place) for place in TOOL_FIELD_VALUES)])

    swept = 0
    for value in sorted({value for value, _ in scalars}, key=shown):
        forbidden = ForbiddenValues()
        forbidden.remember_value(ForbiddenColumn.ADDRESS, value)
        if not forbidden.guard(shown(value), "").notes:
            continue  # krótsza niż ``MIN_VALUE``: strażnik jej nie szuka
        swept += 1

        guarded_logs = guard_logs(logs, forbidden)
        kept = guarded_logs.record

        assert post_of(OwnLogs(guarded_logs)).run_id == RUN_ID, value
        assert [place for place in TOOL_FIELD_VALUES if _json_at(kept, place) != _json_at(logs, place)] == [], value
        if not forbidden.guard(tool_words, "").notes:
            assert not forbidden.guard(kept.text, "").notes, f"{value!r} zostało w Logach"
        if value in names and not forbidden.guard(texts, "").notes:
            assert kept == logs, value
    assert swept > len(names)


# Pola w poddrzewach ``TOOL_FIELDS``, których typ przyjmuje dowolny tekst, z tym, skąd jest ich wartość (#936). Strażnik
# zostawia je bez maski, więc każde nowe takie pole trafia tu tylko z powodem, a pole bez powodu czerwieni test niżej.
TOOL_TEXT: Final = {
    "RunLog.run_id": "uuid4().hex przy starcie Uruchomienia (runs.py), w Logach Urwanego Uruchomienia z dziennika Centrum",
    "RunLog.period": "token okresu z parse_period_token żądania przeglądarki albo period_of zegara (INTERMAX)",
    "Tool.wydanie": "numer Wydania z tagu Gita narzędzia",
    "Tool.commit": "commit Gita narzędzia",
    "CallTrace.exception_type": "typ wyjątku z modułem, bez treści wyjątku (call_trace.exception_type)",
    "CallCause.exception_type": "typ wyjątku z modułem, bez treści wyjątku (call_trace.exception_type)",
    "CallFrame.file": "plik kodu narzędzia względem katalogu narzędzia, bez bibliotek (call_trace._tool_file)",
    "CallFrame.function": "nazwa funkcji kodu narzędzia z traceback",
    "ButtonPressed.operation": "operation_id trasy API z kontraktu, bez treści zapytania (dad_actions._pressed)",
    "Environment.system": "platform.platform(), bez nazwy komputera",
    "Environment.python": "platform.python_version()",
}

_CLOSED: Final = (type(None), bool, int, float, Decimal, date, datetime)
"""Typy bez dowolnego tekstu; liczbę ``READ_VALUES`` ``_free`` sprawdza osobno."""


def _free(annotation: object, owner: str, metadata: Sequence[object] = ()) -> Iterator[str]:
    """Pola typu ``annotation`` (pole ``owner``, ``Model.pole``), które mogą nieść treść pliku taty: dowolny tekst,
    słownik, liczbę ``READ_VALUES`` albo typ, którego ta funkcja nie zna."""

    origin, args = get_origin(annotation), get_args(annotation)
    if READ_VALUES in metadata:
        yield f"{owner} (READ_VALUES)"
    elif origin is Annotated:
        yield from _free(args[0], owner, args[1:])
    elif origin in (Union, UnionType, list, tuple):
        for arg in args:
            if arg is not Ellipsis:
                yield from _free(arg, owner)
    elif origin is Literal or annotation in _CLOSED or (isinstance(annotation, type) and issubclass(annotation, Enum)):
        return
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
        for name, field in annotation.model_fields.items():
            yield from _free(field.annotation, f"{annotation.__name__}.{name}", field.metadata)
    elif isinstance(annotation, type) and is_dataclass(annotation):
        hints = get_type_hints(annotation, include_extras=True)
        for item in fields(annotation):
            yield from _free(hints[item.name], f"{annotation.__name__}.{item.name}")
    else:
        yield owner if annotation is str else f"{owner} ({annotation!r})"


def test_pole_z_listy_pol_narzedzia_ma_w_typie_tylko_zamkniete_listy_chwile_liczby_narzedzia_i_tekst_z_powodem() -> None:
    """Strażnik zostawia każde pole z ``TOOL_FIELDS`` bez maski z całym poddrzewem (#936), więc typ każdego z nich,
    przez modele, dataclassy, listy i unie, ma tylko zamknięte listy, chwile, liczby spoza ``READ_VALUES`` i tekst z
    ``TOOL_TEXT`` z powodem. Nowe pole z dowolnym tekstem, słownikiem albo liczbą z komórek w takim poddrzewie czerwieni
    ten test, zanim wyjdzie bez maski."""

    assert set(TOOL_FIELD_VALUES) == TOOL_FIELDS, "test pola z listy ma każde pole z listy"
    found: set[str] = set()
    for place in TOOL_FIELDS:
        *path, name = place.split(".")
        model: type[BaseModel] = RunLog
        for step in path:
            nested = model.model_fields[step].annotation
            assert isinstance(nested, type) and issubclass(nested, BaseModel), place
            model = nested
        field = model.model_fields[name]
        found.update(_free(field.annotation, f"{model.__name__}.{name}", field.metadata))

    assert sorted(found - set(TOOL_TEXT)) == []
    assert sorted(set(TOOL_TEXT) - found) == [], "wyjątek bez pola w poddrzewie listy"
