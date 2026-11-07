"""Komentarz Logów Uruchomienia w Skrzynce Zgłoszeń (#320, #844): to, czego testy przez HTTP nie osiągną tanio.

Logi ponad limit komentarza GitHuba wymagałyby przez HTTP setek Komunikatów, więc to, że i tak idą jednym komentarzem
z pełnymi Logami w Archiwum Logów okresu, sprawdza wysyłka zbudowana wprost z rekordu (``post_of``): jej części to
dokładnie komentarze, które kolejka dopisuje do issue, a jej plik to plik w Archiwum.
Podsumowanie ma tu tylko przypadki bez taniej drogi przez HTTP z fikstur Przebiegu: nazwa Przygotowania,
powtórki kodów, powtórzone Zatrzymanie, Zatrzymanie po odmowie w Decyzji taty, czas w sekundach albo nieznany, brak commitu i sprawdzenia Diagnozy,
które nie przeszły albo których nie sprawdzono. Resztę sprawdza ``test_centrum_logi_w_skrzynce.py``. Strażnik reguły
danych (``guard_logs``, ADR 0025) ma tu klucz słownika Logów z zakazaną wartością: klucze pochodzą dziś z zamkniętych
list (operator z reguły taty, kod pozycji efenix, litera kolumny), więc przez HTTP żadna taka wartość do klucza nie
trafia, i liczbę policzoną przez narzędzie w kształcie telefonu, której syntetyczne pliki taty przez HTTP nie dają.
Pełne Logi z każdym polem schematu (``FULL_LOGS``) niesie tylko ten plik: przemiatanie kształtów pól (#936) daje
strażnikowi każdą ich wartość jako wartość z pliku taty, a przez HTTP jedno Uruchomienie nie wypełnia wszystkich pól.
Typy pól, które strażnik zostawia bez maski (``TOOL_FIELDS``), sprawdza tu test struktury na schemacie Logów.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping, Sequence
import copy
import dataclasses
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
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

from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.report_box import COMMENT_LIMIT, REPOSITORY
from rozliczenia.centrum.comment_versions import (
    LABEL,
    Closing,
    CommentVersion,
    Drop,
    LogsMissing,
    OwnLogs,
    ProgressVersion,
    ResultWithoutLogs,
    StandInLogs,
    WithoutLogsVersion,
    close,
    journal_after,
    post_of,
    progress_markdown,
    summary_markdown,
    without_logs_markdown,
)
from rozliczenia.centrum.contract import Progress, RunInfo, RunResult
from rozliczenia.centrum.dad_actions import DadActionJournal
from rozliczenia.centrum.diagnosis import Diagnosis
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.logs_disk import (
    EndEntry,
    Found,
    Journal,
    JournalKey,
    JournalRead,
    LeftJournal,
    LogsOnDisk,
    LogsRead,
    Missing,
    Refused,
    Unreadable,
)
from rozliczenia.centrum.outbox import PeriodThread, Post, Rank
from rozliczenia.centrum.run_comments import PROGRESS_S, RecordMaker, RunComments
from rozliczenia.centrum.run_logs import (
    READ_VALUES,
    TOOL_FIELDS,
    GuardedLogs,
    LoggedInterruption,
    OrderDone,
    PricingProgress,
    RunLog,
    StartFacts,
    guard_logs,
    guard_text,
)
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.client_data import MIN_VALUE, ForbiddenColumn, ForbiddenValues, shown
from tests.fixtures.clock import ManualClock
from tests.fixtures.dziennik_wyceny import begun_line, left_journal
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
    budują je ``RunComments._progress`` i ``close``."""

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


def _logs_on_disk(directory: Path) -> LogsOnDisk:
    """Logi na dysku w katalogu Logów ``directory`` (obok dziennika Centrum)."""

    return LogsOnDisk(CentrumLog(directory / "centrum-rozliczen.log"), journaled="efenix")


# Wszystko, co bierze Logi albo tekst po strażniku: cztery wersje komentarza Uruchomienia i plik Logów.
TAKES_GUARDED: Final[dict[str, Callable[[Any, Path], object]]] = {
    "postep": lambda value, _: ProgressVersion(_progress(), value),
    "wynik-bez-logow": lambda value, _: WithoutLogsVersion(ResultWithoutLogs(_progress(), "OK", "niezapisane"), value),
    "logi-z-pliku-albo-urwane": lambda value, _: StandInLogs(value),
    "logi-z-wynikiem-albo-diagnoza": lambda value, _: OwnLogs(value),
    "plik-logow": lambda value, directory: _logs_on_disk(directory).write(value),
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


# Wartość po strażniku drugiego typu: tekst komentarza zamiast Logów i Logi zamiast tekstu (przegląd #1038, runda 3).
OTHER_GUARDED: Final = {
    "postep": "logi",
    "wynik-bez-logow": "logi",
    "logi-z-pliku-albo-urwane": "tekst",
    "logi-z-wynikiem-albo-diagnoza": "tekst",
    "plik-logow": "tekst",
}


@pytest.mark.parametrize(("name", "other"), OTHER_GUARDED.items(), ids=OTHER_GUARDED.keys())
def test_wersje_komentarza_i_plik_logow_odmawiaja_wartosci_po_strazniku_drugiego_typu(
    name: str, other: str, tmp_path: Path
) -> None:
    """Tekst komentarza po strażniku nie jest Logami, a Logi nie są tekstem komentarza: wersja z Logami i plik Logów
    biorą tylko Logi po strażniku, a postęp i wynik bez Logów tylko tekst, także gdy typ wartości nie widzi (``Any``)."""

    with pytest.raises(TypeError, match="po strażniku"):
        TAKES_GUARDED[name](_guarded(other), tmp_path)

    assert list(tmp_path.iterdir()) == []


# Wartość z kolumny ADRES pliku taty, którą ta praca Centrum przeczytała (ADR 0025): w Logach z dziennika i w tekście
# wyniku bez Logów (tu w miejscu identyfikatora Uruchomienia, jak w teście postępu wyżej).
ADDRESS: Final = "Syntetyczna Kwarcowa 9"


def _forbidden() -> ForbiddenValues:
    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, ADDRESS)
    forbidden.remember_value(ForbiddenColumn.ADDRESS, RUN_ID)
    return forbidden


def _journal(end: EndEntry | None) -> JournalRead:
    """Dziennik Wyceny Uruchomienia ``RUN_ID`` z zaczętym zleceniem z wiersza 19 i wpisem końca ``end``."""

    started = StartFacts(
        run_id=RUN_ID, process="efenix", mode="zapis", period="08_14_09_2026", started_at=datetime(2026, 9, 10, 8, 0)
    )
    interruption = LoggedInterruption(row=19, place=1, total=2, omitted=0)
    return JournalRead(started, [], interruption, datetime(2026, 9, 10, 8, 5), 2, end)


FROM_FILE: Final = record(process="efenix", technical_notes=[f"Notatka: {ADDRESS}"])
"""Logi z pliku, które zapisała praca Centrum sprzed strażnika (wartość z kolumny ADRES bez maski)."""
INTERRUPTED: Final = record(
    process="efenix", result=None, ending="interrupted", duration_ms=None, technical_notes=[f"Notatka: {ADDRESS}"]
)
"""Logi Urwanego Uruchomienia, które składa start Centrum (``RecordMaker.interrupted``)."""


def _without_logs(
    read: JournalRead, result: RunResult | None, logs: LogsMissing, forbidden: ForbiddenValues
) -> WithoutLogsVersion:
    final = ResultWithoutLogs(read.progress, result, logs)
    return WithoutLogsVersion(final, guard_text(without_logs_markdown(final), "wynik Wyceny w efenix bez Logów", forbidden))


# Macierz startu Centrum (GLOSSARY „Dziennik Wyceny w efenix”, #910): co zastał na dysku → wersja zastępcza po strażniku
# reguły danych tej pracy Centrum i czy start złożył Logi Urwanego Uruchomienia (zabiera działania taty).
CLOSE_MATRIX: Final[
    dict[str, tuple[EndEntry | None, bool, LogsRead, Callable[[JournalRead, ForbiddenValues], Closing], bool]]
] = {
    "dziennik-bez-pierwszej-linii": (None, False, Missing(), lambda read, forbidden: Drop(), False),
    "logi-z-pliku": (
        EndEntry("OK"),
        True,
        Found(FROM_FILE),
        lambda read, forbidden: StandInLogs(guard_logs(FROM_FILE, forbidden)),
        False,
    ),
    "logi-nieczytelne": (
        EndEntry("OK"),
        True,
        Unreadable(),
        lambda read, forbidden: _without_logs(read, "OK", "nieczytelne", forbidden),
        False,
    ),
    # Plik Logów jest, więc Uruchomienie miało wynik, ale ani plik, ani dziennik go nie mówią (przegląd #1043, Drobne 3).
    "logi-nieczytelne-bez-wpisu-konca": (
        None,
        True,
        Unreadable(),
        lambda read, forbidden: _without_logs(read, None, "nieczytelne", forbidden),
        False,
    ),
    "bez-logow-z-wpisem-konca": (
        EndEntry("WYMAGA_SPRAWDZENIA"),
        True,
        Missing(),
        lambda read, forbidden: _without_logs(read, "WYMAGA_SPRAWDZENIA", "niezapisane", forbidden),
        False,
    ),
    "urwane-uruchomienie": (
        None,
        True,
        Missing(),
        lambda read, forbidden: StandInLogs(guard_logs(INTERRUPTED, forbidden)),
        True,
    ),
}


@pytest.mark.parametrize(
    ("end", "first_line", "logs", "expected", "built"), CLOSE_MATRIX.values(), ids=CLOSE_MATRIX.keys()
)
def test_start_centrum_zamyka_dziennik_wyceny_wersja_zastepcza_po_strazniku_z_tego_co_zastal_na_dysku(
    end: EndEntry | None,
    first_line: bool,
    logs: LogsRead,
    expected: Callable[[JournalRead, ForbiddenValues], Closing],
    built: bool,
) -> None:
    """Model ``Czytaj`` skilla ``verify-urwane-uruchomienie``: dziennik bez pierwszej linii start usuwa, a z każdego
    innego robi wersję zastępczą komentarza Uruchomienia z tego, co zastał: Logi z pliku, wynik bez Logów, gdy pliku nie
    da się odczytać albo go nie ma, a jest wpis końca, i Logi Urwanego Uruchomienia, gdy nie ma ani pliku, ani wpisu
    końca. Każda wersja przeszła strażnika reguły danych tej pracy Centrum (ADR 0025), także Logi z pliku sprzed niego,
    a Logi Urwanego Uruchomienia składa tylko ostatnia gałąź, bo zabierają działania taty, które czekają na Logi."""

    read = _journal(end)
    asked: list[JournalRead] = []

    def interrupted(journal: JournalRead) -> RunLog:
        asked.append(journal)
        return INTERRUPTED

    forbidden = _forbidden()
    left = LeftJournal(JournalKey(Path("dziennik.jsonl")), read if first_line else None, logs)

    closing = close(left, forbidden, interrupted)

    wanted = expected(read, forbidden)
    if isinstance(wanted, Drop):
        assert closing == wanted
    else:
        assert not isinstance(closing, Drop)
        assert post_of(closing) == post_of(wanted)
        assert all(ADDRESS not in text for text in post_of(closing).parts)
    assert asked == ([read] if built else [])


def test_plik_logow_ktorego_system_nie_daje_odczytac_zostawia_dziennik_z_bledem_systemu() -> None:
    """Nie wiadomo, czy Logi są i jakie, więc start nie zgaduje wersji: błąd systemu wychodzi do startu, który zostawia
    dziennik następnemu startowi, i niczego nie składa."""

    failure = PermissionError("plik trzyma antywirus")
    left = LeftJournal(JournalKey(Path("dziennik.jsonl")), _journal(None), Refused(failure))
    asked: list[JournalRead] = []

    def interrupted(journal: JournalRead) -> RunLog:
        asked.append(journal)
        return INTERRUPTED

    with pytest.raises(OSError, match="antywirus"):
        close(left, _forbidden(), interrupted)

    assert asked == []


class SwitchedOff(BaseException):
    """Centrum zgasło (brak prądu, zamknięta konsola, zabity proces): ``BaseException``, więc żadne ``except`` kodu go
    nie zatrzyma, jak wątku, który ginie razem z komputerem."""


@dataclass
class RecordingQueue:
    """Kolejka wysyłki, która przyjmuje każdą wysyłkę (``accepts``) albo każdej odmawia i pamięta przyjęte."""

    posts: list[Post] = dataclasses.field(default_factory=list)
    accepts: bool = True

    def post(self, post: Post) -> bool:
        if self.accepts:
            self.posts.append(post)
        return self.accepts

    def delivered(self, run_id: str, label: str) -> str | None:
        return None


StartStep = Literal["ZapiszLogi", "Wyslij"]
"""Kroki modelu ``verify-urwane-uruchomienie`` przy starcie Centrum, które coś zapisują."""
EndStep = Literal["WpisKonca", "LogiWyniku", "WyslijWynik", "UsunPoLogach"]
"""Kroki modelu na końcu Wyceny (``RunComments.run_ended``), które coś zapisują, w kolejności modelu."""


class PowerCut:
    """Zgaśnięcie Centrum tuż przed krokiem modelu ``verify-urwane-uruchomienie``, który coś zapisuje. Daje Logi na dysku
    i kolejkę, które gasną przed nim: start Centrum przed zapisem pliku Logów (``ZapiszLogi``) albo wysyłką wersji
    zastępczej (``Wyslij``), koniec Wyceny przed wpisem końca (``WpisKonca``), plikiem Logów z wynikiem (``LogiWyniku``),
    ich wysyłką (``WyslijWynik``) albo usunięciem dziennika za nimi (``UsunPoLogach``); ``None``: Centrum nie gaśnie. Po
    zgaśnięciu nic już nie pisze, także ``finally`` kodu, który biegł w tej chwili."""

    def __init__(self, before: StartStep | EndStep | None) -> None:
        self.before = before
        self.off = False

    def reached(self, step: StartStep | EndStep) -> None:
        """Krok ``step`` zaczyna pisać: Centrum gaśnie, gdy to krok zgaśnięcia albo już zgasło."""

        if self.off or step == self.before:
            self.off = True
            raise SwitchedOff

    def disk(self, directory: Path) -> LogsOnDisk:
        cut = self
        log = CentrumLog(directory / "centrum-rozliczen.log")

        class SwitchedOffJournal(Journal):
            def end(self, run_id: str, result: RunResult) -> None:
                cut.reached("WpisKonca")
                super().end(run_id, result)

            def remove(self, run_id: str) -> None:
                cut.reached("UsunPoLogach")
                super().remove(run_id)

        journal = SwitchedOffJournal(directory / "dzienniki-wyceny", log, process="efenix")

        class SwitchedOffDisk(LogsOnDisk):
            @property
            def journal(self) -> Journal:
                return journal

            def write(self, logs: GuardedLogs) -> None:
                # Ten sam zapis pliku Logów to ZapiszLogi przy starcie Centrum i LogiWyniku na końcu Wyceny.
                cut.reached("ZapiszLogi" if cut.before == "ZapiszLogi" else "LogiWyniku")
                super().write(logs)

        return SwitchedOffDisk(log, journaled="efenix")

    def queue(self, queue: RecordingQueue) -> RecordingQueue:
        cut = self

        class SwitchedOffQueue(RecordingQueue):
            def post(self, post: Post) -> bool:
                if post.rank != Rank.DRAFT or cut.off:
                    cut.reached("Wyslij" if post.rank == Rank.STAND_IN else "WyslijWynik")
                return super().post(post)

        return SwitchedOffQueue(queue.posts)


def _started(comments: RunComments) -> None:
    """Start Centrum od budowy aplikacji do pierwszego zapytania API: zamknięcie dzienników, potem ich wysyłka."""

    comments.close_left_behind()
    asyncio.run(comments.send_left_behind())


def _comments(
    directory: Path, queue: RecordingQueue, disk: LogsOnDisk | None = None, clock: ManualClock | None = None
) -> RunComments:
    """Start Centrum (model ``Start``) na katalogu Logów ``directory``: dziś narzędzie bez commitu i bez plików procesu."""

    log = CentrumLog(directory / "centrum-rozliczen.log")
    records = RecordMaker(
        commit=lambda: None,
        wydanie=lambda commit: None,
        files=lambda process, period: [],
        cloud_files=CloudFiles(None),
        dad_actions=DadActionJournal(directory / "dzialania-taty.jsonl", log),
    )
    return RunComments(
        disk or _logs_on_disk(directory),
        queue,
        forbidden=ForbiddenValues(),
        clock=clock or ManualClock(),
        log=log,
        records=records,
    )


def _urwane(directory: Path) -> Path:
    """Dziennik Urwanego Uruchomienia ``RUN_ID``, które zgasło przy zleceniu z wiersza 19."""

    started = StartFacts(
        run_id=RUN_ID, process="efenix", mode="zapis", period="08_14_09_2026", started_at=datetime(2026, 9, 10, 8, 0)
    )
    return left_journal(directory, started, begun_line(datetime(2026, 9, 10, 8, 1), row=19, place=1, total=2))


@pytest.mark.parametrize("before", get_args(StartStep))
def test_centrum_zgaszone_przy_zamykaniu_dziennika_wyceny_wysyla_logi_urwanego_uruchomienia_przy_nastepnym_starcie(
    before: StartStep, tmp_path: Path
) -> None:
    """Start Centrum, który zgasł przed zapisem pliku Logów Urwanego Uruchomienia albo przed ich wysyłką, zostawia
    dziennik i niczego nie wysyła; następny start wysyła je raz, w stopniu wersji zastępczej, z plikiem w Archiwum o
    bajtach pliku Logów, dopiero przy pierwszym zapytaniu (po ``Outbox.resume``), i dopiero wtedy usuwa dziennik
    (obietnice DziennikPoKolejce, TeSameZnaki, NicPrzedWznowieniem i Zbieganie)."""

    journal = _urwane(tmp_path)
    queue, cut = RecordingQueue(), PowerCut(before)

    with pytest.raises(SwitchedOff):
        _started(_comments(tmp_path, cut.queue(queue), cut.disk(tmp_path)))
    after_cut = (journal.exists(), list(queue.posts))
    restarted = _comments(tmp_path, queue)
    restarted.close_left_behind()
    before_request = list(queue.posts)
    asyncio.run(restarted.send_left_behind())

    [post] = queue.posts
    [logs_file] = (tmp_path / "uruchomienia").glob(f"*-{RUN_ID}.json")
    sent = RunLog.model_validate_json(logs_file.read_text(encoding="utf-8"))
    assert (after_cut, before_request) == ((True, []), [])
    assert (post.rank, sent.ending, sent.interruption) == (
        Rank.STAND_IN,
        "interrupted",
        LoggedInterruption(row=19, place=1, total=2, omitted=0),
    )
    assert post.archive is not None and gzip.decompress(post.archive.packed()) == logs_file.read_bytes()
    assert not journal.exists()


def test_katalog_logow_ktory_nie_przyjal_pliku_przy_starcie_nie_zatrzymuje_logow_urwanego_uruchomienia(
    tmp_path: Path,
) -> None:
    """Na miejscu katalogu Logów stoi plik, więc start Centrum nie zapisze pliku Logów Urwanego Uruchomienia: jedna linia
    dziennika Centrum, a te Logi i tak idą do Skrzynki przy pierwszym zapytaniu i dziennik znika (przegląd #1043,
    Drobne 1)."""

    journal = _urwane(tmp_path)
    (tmp_path / "uruchomienia").write_text("", encoding="utf-8")
    queue = RecordingQueue()
    comments = _comments(tmp_path, queue)

    comments.close_left_behind()
    asyncio.run(comments.send_left_behind())

    [post] = queue.posts
    lines = (tmp_path / "centrum-rozliczen.log").read_text(encoding="utf-8").splitlines()
    assert (post.rank, journal.exists()) == (Rank.STAND_IN, False)
    assert [line.split(" ", 1)[1].split(" typ=")[0] for line in lines] == ["dziennik-wyceny-niedostepny"]
    assert lines[0].endswith("miejsce=start")


def test_wersja_zastepcza_idzie_do_kolejki_raz_choc_kazde_zapytanie_api_pyta_o_wysylke(tmp_path: Path) -> None:
    """Wysyłka wersji zastępczej jest zależnością każdej trasy API, a idzie tylko przy pierwszym zapytaniu: następne nie
    wysyłają jej znowu ani nie usuwają dziennika drugi raz (przegląd #1043, Drobne 2)."""

    _urwane(tmp_path)
    queue = RecordingQueue()
    comments = _comments(tmp_path, queue)
    comments.close_left_behind()

    for _ in range(3):
        asyncio.run(comments.send_left_behind())

    assert [post.rank for post in queue.posts] == [Rank.STAND_IN]
    assert not (tmp_path / "centrum-rozliczen.log").exists()


PRICING = RunInfo(
    id=RUN_ID,
    process="efenix",
    title="Wycena w efenix",
    period="08_14_09_2026",
    dry_run=False,
    confirms_readiness=False,
    register_name="Rejestr zleceń",
)
STARTED_AT: Final = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
OTHER_RUN_ID: Final = "b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6"
ENTRIES: Final = ["start Uruchomienia", "zaczynam zlecenie"]
"""Wpisy dziennika Wyceny ``PRICING`` przed jej wynikiem (``_priced``)."""


def _ended(info: RunInfo = PRICING) -> EndedRun:
    """Koniec Uruchomienia ``info`` bez wyniku rdzenia (``BLAD_KRYTYCZNY``), po pół godzinie."""

    progress = Progress(phases=[], template_total=0, templates_completed=0, current_worker=None, figures=[])
    return EndedRun(info, None, None, progress, STARTED_AT, STARTED_AT + timedelta(minutes=30))


def _priced(comments: RunComments, disk: LogsOnDisk) -> None:
    """Start Wyceny ``PRICING`` z Centrum i zlecenie z wiersza 19 zaczęte w jej dzienniku, przed wynikiem."""

    comments.run_started(PRICING, STARTED_AT)
    disk.journal.begun(19, 1, 1)


# Zgaśnięcie Centrum przed krokiem końca Wyceny (model ``verify-urwane-uruchomienie``; ``None``: bez zgaśnięcia) i czy na
# miejscu katalogu Logów stoi plik → co zostaje: wpis końca w dzienniku, plik Logów z wynikiem i stopnie wysyłek tej pracy
# Centrum (postęp przy starcie Wyceny, Logi z wynikiem), a potem wersja zastępcza następnego startu: Logi z pliku, wynik bez
# Logów albo Logi Urwanego Uruchomienia (przy ``WpisKonca`` to przyjęte znalezisko ``przed-wpisem-konca``). Bez zgaśnięcia
# dziennik znika za Logami z wynikiem, a start nie ma czego wysłać.
AFTER_CUT: Final[dict[str, tuple[EndStep | None, bool, tuple[bool, bool, list[Rank], str | None]]]] = {
    "WpisKonca": ("WpisKonca", False, (False, False, [Rank.DRAFT], "interrupted")),
    "LogiWyniku": ("LogiWyniku", False, (True, False, [Rank.DRAFT], "bez-logow")),
    "WyslijWynik": ("WyslijWynik", False, (True, True, [Rank.DRAFT], "finished")),
    "UsunPoLogach": ("UsunPoLogach", False, (True, True, [Rank.DRAFT, Rank.OWN], "finished")),
    # Logi z wynikiem przyjęte bez swojego pliku: start wysyła wynik bez Logów, niższego stopnia (#871, #910).
    "UsunPoLogach-bez-pliku-logow": ("UsunPoLogach", True, (True, False, [Rank.DRAFT, Rank.OWN], "bez-logow")),
    "bez-zgasniecia": (None, False, (True, True, [Rank.DRAFT, Rank.OWN], None)),
}


@pytest.mark.parametrize(("before", "blocked", "expected"), AFTER_CUT.values(), ids=AFTER_CUT.keys())
def test_centrum_zgaszone_przed_kazdym_krokiem_konca_wyceny_daje_nastepnemu_startowi_wersje_zastepcza_z_tego_co_zapisalo(
    before: EndStep | None, blocked: bool, expected: tuple[bool, bool, list[Rank], str | None], tmp_path: Path
) -> None:
    """Koniec Wyceny w efenix to po kolei wpis końca, plik Logów z wynikiem, ich wysyłka i usunięcie dziennika, gdy
    kolejka je przyjęła (``RunComments.run_ended``, #871, #910). Centrum zgaszone przed każdym z tych kroków zostawia
    dziennik, a następny start wysyła z niego wersję zastępczą tego, co zdążyło się zapisać, w stopniu niższym od Logów
    z wynikiem, i usuwa dziennik. Zgaśnięcie przed wpisem końca daje Logi Urwanego Uruchomienia (przyjęte znalezisko)."""

    queue, cut = RecordingQueue(), PowerCut(before)
    disk = cut.disk(tmp_path)
    comments = _comments(tmp_path, cut.queue(queue), disk)
    if blocked:
        (tmp_path / "uruchomienia").write_text("", encoding="utf-8")
    _priced(comments, disk)

    if before is None:
        comments.run_ended(_ended())
    else:
        with pytest.raises(SwitchedOff):
            comments.run_ended(_ended())
    ended = [
        [json.loads(line)["entry"] for line in path.read_text(encoding="utf-8").splitlines()]
        for path in (tmp_path / "dzienniki-wyceny").glob("*.jsonl")
    ]
    logs_files = list((tmp_path / "uruchomienia").glob(f"*-{RUN_ID}.json"))
    ranks = [post.rank for post in queue.posts]
    restarted = _comments(tmp_path, queue)
    _started(restarted)

    end_entry, logs_file, sent, stand_in = expected
    assert (ranks, bool(logs_files)) == (sent, logs_file)
    assert ended == ([] if stand_in is None else [ENTRIES + (["koniec Uruchomienia"] if end_entry else [])])
    assert list((tmp_path / "dzienniki-wyceny").glob("*.jsonl")) == []
    if stand_in is None:
        assert [post.rank for post in queue.posts] == sent
        return
    *_, last = queue.posts
    assert last.rank == Rank.STAND_IN
    if stand_in == "bez-logow":
        assert last.archive is None and "- Wynik: BLAD_KRYTYCZNY" in last.parts[0]
    else:
        assert last.archive is not None
        assert json.loads(gzip.decompress(last.archive.packed()))["ending"] == stand_in


def test_wynik_wyceny_bez_przyjecia_logow_przez_kolejke_zostawia_dziennik_do_nastepnego_startu(tmp_path: Path) -> None:
    """Kolejka odmawia Logów z wynikiem (``post`` daje ``False``), więc komentarz postępu nie ma jeszcze wersji
    końcowej: dziennik zostaje z wpisem końca, a następny start wysyła z niego Logi z pliku (#910)."""

    queue = RecordingQueue(accepts=False)
    disk = _logs_on_disk(tmp_path)
    comments = _comments(tmp_path, queue, disk)
    _priced(comments, disk)

    comments.run_ended(_ended())
    left = list((tmp_path / "dzienniki-wyceny").glob("*.jsonl"))
    queue.accepts = True
    _started(_comments(tmp_path, queue))

    [post] = queue.posts
    assert (len(left), post.rank) == (1, Rank.STAND_IN)
    assert list((tmp_path / "dzienniki-wyceny").glob("*.jsonl")) == []


def test_blad_wpisu_konca_nie_zatrzymuje_logow_z_wynikiem_a_blad_pliku_logow_ich_wysylki(tmp_path: Path) -> None:
    """Każdy krok końca Wyceny ma własną osłonę (#871): wpis końca, który rzucił, nie zatrzymuje Logów z wynikiem, a plik
    Logów, który się nie zapisał (na miejscu katalogu Logów stoi plik), nie zatrzymuje ich wysyłki; kolejka je przyjęła,
    więc dziennik znika, a dziennik Centrum ma typ każdego błędu w miejscu działań po wyniku."""

    queue = RecordingQueue()
    log = CentrumLog(tmp_path / "centrum-rozliczen.log")

    class BrokenJournal(Journal):
        def end(self, run_id: str, result: RunResult) -> None:
            raise PermissionError("dziennik trzyma antywirus")

    journal = BrokenJournal(tmp_path / "dzienniki-wyceny", log, process="efenix")

    class BrokenEndDisk(LogsOnDisk):
        @property
        def journal(self) -> Journal:
            return journal

    disk = BrokenEndDisk(log, journaled="efenix")
    comments = _comments(tmp_path, queue, disk)
    _priced(comments, disk)
    (tmp_path / "uruchomienia").write_text("", encoding="utf-8")

    comments.run_ended(_ended())

    failures = [
        line.split(" ", 1)[1]
        for line in (tmp_path / "centrum-rozliczen.log").read_text(encoding="utf-8").splitlines()
        if "nieoczekiwany-wyjatek" in line
    ]
    assert [post.rank for post in queue.posts] == [Rank.DRAFT, Rank.OWN]
    assert failures == [
        'nieoczekiwany-wyjatek typ=PermissionError miejsce="po wyniku Uruchomienia procesu"',
        'nieoczekiwany-wyjatek typ=FileExistsError miejsce="po wyniku Uruchomienia procesu"',
    ]
    assert list((tmp_path / "dzienniki-wyceny").glob("*.jsonl")) == []


def test_postep_wyceny_idzie_tylko_z_pierwsza_linia_dziennika_na_dysku_i_konczy_sie_z_wynikiem(tmp_path: Path) -> None:
    """Postęp Wyceny w efenix idzie przy jej starcie i co ``PROGRESS_S``, tylko gdy dziennik ma na dysku pierwszą linię
    (#846): bez niej (na miejscu katalogu dzienników stoi plik) budzik dzwoni, a nic nie idzie. Od końca Wyceny postęp
    nie idzie, a pierwszy budzik po końcu nie ustawia następnego."""

    (tmp_path / "dzienniki-wyceny").write_text("", encoding="utf-8")
    queue, clock = RecordingQueue(), ManualClock()
    comments = _comments(tmp_path, queue, clock=clock)

    comments.run_started(PRICING, STARTED_AT)
    clock.advance(PROGRESS_S)
    without_first_line = (list(queue.posts), clock.wakes)
    (tmp_path / "dzienniki-wyceny").unlink()
    comments.run_started(PRICING.model_copy(update={"id": OTHER_RUN_ID}), STARTED_AT)
    clock.advance(PROGRESS_S)
    during = [post.rank for post in queue.posts]
    comments.run_ended(_ended(PRICING.model_copy(update={"id": OTHER_RUN_ID})))
    clock.advance(PROGRESS_S)

    assert without_first_line == ([], 1)
    assert during == [Rank.DRAFT, Rank.DRAFT]
    assert ([post.rank for post in queue.posts], clock.wakes) == ([Rank.DRAFT, Rank.DRAFT, Rank.OWN], 0)


def test_postep_wyceny_przeczytany_przed_jej_koncem_nie_idzie_po_jej_logach_gdy_trwa_juz_nastepna_wycena(
    tmp_path: Path,
) -> None:
    """Budzik postępu czyta dziennik Wyceny, zanim weźmie blokadę komentarza Uruchomienia (#846). Gdy w tej chwili Wycena
    się kończy, a Centrum startuje następną, postęp pierwszej nie idzie: poszedłby po jej Logach z wynikiem jako
    nowsza wersja komentarza, która mówi, że Uruchomienie trwa. Postęp następnej Wyceny idzie (przegląd #1047)."""

    queue, clock = RecordingQueue(), ManualClock()
    log = CentrumLog(tmp_path / "centrum-rozliczen.log")
    box: list[RunComments] = []
    next_pricing = PRICING.model_copy(update={"id": OTHER_RUN_ID})

    class EndingWhileRead(Journal):
        armed = False

        def progress(self, run_id: str) -> PricingProgress | None:
            read = super().progress(run_id)
            if self.armed and run_id == RUN_ID:
                self.armed = False
                box[0].run_ended(_ended())
                box[0].run_started(next_pricing, STARTED_AT)
            return read

    journal = EndingWhileRead(tmp_path / "dzienniki-wyceny", log, process="efenix")

    class RacingDisk(LogsOnDisk):
        @property
        def journal(self) -> Journal:
            return journal

    disk = RacingDisk(log, journaled="efenix")
    box.append(_comments(tmp_path, queue, disk, clock))
    _priced(box[0], disk)
    journal.armed = True

    clock.advance(PROGRESS_S)

    assert [(post.rank, post.run_id) for post in queue.posts] == [
        (Rank.DRAFT, RUN_ID),
        (Rank.OWN, RUN_ID),
        (Rank.DRAFT, OTHER_RUN_ID),
    ]


def test_diagnoza_dopisuje_sie_do_logow_ostatniego_uruchomienia_raz_na_wynik(tmp_path: Path) -> None:
    """Diagnoza dopisuje się do Logów ostatniego Uruchomienia tej pracy Centrum nowszą wersją tej samej wysyłki, a druga
    z tym samym wynikiem i Diagnoza innego Uruchomienia nie zmieniają niczego (#840)."""

    queue = RecordingQueue()
    comments = _comments(tmp_path, queue)
    comments.run_ended(_ended(PRICING.model_copy(update={"process": "preparation"})))
    diagnosis = Diagnosis((), ("wpis dziennika Centrum",))

    comments.diagnosed(OTHER_RUN_ID, diagnosis)
    other = len(queue.posts)
    for _ in range(2):
        comments.diagnosed(RUN_ID, diagnosis)

    [file] = (tmp_path / "uruchomienia").glob(f"*-{RUN_ID}.json")
    first, diagnosed = queue.posts
    assert other == 1
    assert (first.run_id, diagnosed.run_id, diagnosed.rank) == (RUN_ID, RUN_ID, Rank.OWN)
    assert diagnosed.archive is not None and gzip.decompress(diagnosed.archive.packed()) == file.read_bytes()
    assert RunLog.model_validate_json(file.read_text(encoding="utf-8")).diagnosis is not None


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

    kept = guard_logs(record(input_copy=[copied]), ForbiddenValues()).record

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

    kept = guard_logs(logs, forbidden).record

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

    kept = guard_logs(logs, forbidden).record

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
