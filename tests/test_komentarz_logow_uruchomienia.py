"""Komentarz Logów Uruchomienia w Skrzynce Zgłoszeń (#320, #844): to, czego testy przez HTTP nie osiągną tanio.

Logi ponad limit komentarza GitHuba wymagałyby przez HTTP setek Komunikatów, więc to, że i tak idą jednym komentarzem
z pełnymi Logami w Archiwum Logów okresu, sprawdza wysyłka zbudowana wprost z rekordu (``logi_post``): jej części to
dokładnie komentarze, które kolejka dopisuje do issue, a jej plik to plik w Archiwum.
Podsumowanie ma tu tylko przypadki bez taniej drogi przez HTTP z fikstur Przebiegu: nazwa Przygotowania,
powtórki kodów, powtórzone Zatrzymanie, Zatrzymanie po odmowie w Decyzji taty, czas w sekundach albo nieznany, brak commitu i sprawdzenia Diagnozy,
które nie przeszły albo których nie sprawdzono. Resztę sprawdza ``test_centrum_logi_w_skrzynce.py``.
"""

from __future__ import annotations

import gzip
from typing import Any

import pytest

from rozliczenia.centrum.report_box import COMMENT_LIMIT, REPOSITORY
from rozliczenia.centrum.run_logs import RunLog, logi_post, summary_markdown

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
