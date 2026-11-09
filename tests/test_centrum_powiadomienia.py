"""Powiadomienia (ADR 0015, #323) przez HTTP API Centrum z fałszywą Skrzynką Zgłoszeń i podstawionym zegarem."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
from typing import Any

import pytest

from rozliczenia.centrum.notifications import CHECK_WAIT_S, NOTIFICATIONS_FILE
from rozliczenia.centrum.outbox import RETRY_S
from rozliczenia.centrum.release_notes import DadCase, ReleaseNotes, render
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE, NOTE, OLD_REPORTS_FILE, REPORT
from rozliczenia.centrum.report_box import CloseReason, Refused, Unreachable
from rozliczenia.centrum.tool_freshness import PublishedRelease
from rozliczenia.centrum.tool_update import Release

from tests.fixtures.centrum import (
    QUEUED_FOR_KEY,
    READ_BY_MAKS,
    RESOLVED,
    SENT,
    TOOL_COMMIT,
    ToolDirectory,
    case_states,
    centrum as plain_centrum,
    finished_view,
    join_threads_since,
    write_report_key,
)
from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, settling_centrum, stopped_for_maks
from tests.fixtures.linie_watkow import new_line
from tests.fixtures.locked_file import lock_file
from tests.fixtures.potomne import wait_for

NOTE_TITLE = "Plik zbiorczy otwiera się długo"
CLOSED_AT = datetime(2026, 10, 20, 9, 15, tzinfo=timezone.utc)


def sent_report(centrum: PreparingCentrum) -> str:
    """Zgłoszenie „do Maksa” wysłane z tego komputera; zwraca jego „Co się stało”.

    Czeka też na pytania skrzynki, które wysyłka zostawia w tle (Diagnoza szuka otwartego Zgłoszenia i nikt na to nie
    czeka): spóźniona odmowa po zmianie skrzynki w teście byłaby werdyktem „klucz odrzucony” sprzed jego pytania.
    """

    since = new_line()
    run_id = stopped_for_maks(centrum)
    assert centrum.client.post(f"/api/runs/{run_id}/diagnosis").status_code == 200
    assert centrum.client.post(f"/api/runs/{run_id}/report").json() == {"state": "sent"}
    join_threads_since(since)
    return centrum.surroundings.report_box.sent[-1].title.split(": ", 1)[1]


def sent_note(centrum: PreparingCentrum, title: str = NOTE_TITLE) -> dict[str, Any]:
    response = centrum.client.post("/api/dad-notes", json={"title": title, "body": "Excel myśli minutę."})
    assert response.status_code == 200, response.json()
    answer: dict[str, Any] = response.json()
    return answer


def number_of(centrum: PreparingCentrum, title: str) -> int:
    return next(issue.number for issue in centrum.surroundings.report_box.issues if issue.title == title)


def notifications(centrum: PreparingCentrum) -> dict[str, Any]:
    response = centrum.client.get("/api/notifications")
    assert response.status_code == 200, response.json()
    answer: dict[str, Any] = response.json()
    return answer


def rows(centrum: PreparingCentrum) -> list[tuple[str, str, dict[str, str], bool]]:
    """Powiadomienia jak w widoku: rodzaj, nazwa, stan i czy nowe."""

    return [
        (item["kind"], item["title"] if item["kind"] == "uwaga" else item["what"], item["state"], item["unread"])
        for item in notifications(centrum)["items"]
    ]


def polls(centrum: PreparingCentrum) -> int:
    """Ile razy Centrum pytało skrzynkę o stan spraw taty (issue z etykietą, także zamknięte)."""

    return sum(include_closed for _, include_closed in centrum.surroundings.report_box.listed)


def read(centrum: PreparingCentrum, ids: list[str]) -> dict[str, Any]:
    response = centrum.client.post("/api/notifications/read", json={"ids": ids})
    assert response.status_code == 200, response.json()
    answer: dict[str, Any] = response.json()
    return answer


def test_wyslana_uwaga_i_zgloszenie_daja_powiadomienia_a_zamkniecie_mowi_co_zrobil_maks(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    what = sent_report(centrum)
    assert sent_note(centrum) == {"state": "sent"}
    box, clock = centrum.surroundings.report_box, centrum.surroundings.clock

    assert rows(centrum) == [("uwaga", NOTE_TITLE, SENT, False), ("zgloszenie", what, SENT, False)]
    assert notifications(centrum)["unread"] == 0

    box.close(number_of(centrum, NOTE_TITLE), "completed", CLOSED_AT)
    box.close(box.sent[-1].number, "not_planned", CLOSED_AT + timedelta(hours=1))
    clock.advance(minutes=10)

    assert rows(centrum) == [("zgloszenie", what, READ_BY_MAKS, True), ("uwaga", NOTE_TITLE, RESOLVED, True)]
    answer = notifications(centrum)
    assert answer["unread"] == 2
    assert [item["at"] for item in answer["items"]] == ["2026-10-20T10:15:00Z", "2026-10-20T09:15:00Z"]
    assert "Excel myśli minutę." not in str(answer)


@pytest.mark.parametrize(
    ("reason", "state"),
    [("completed", RESOLVED), ("not_planned", READ_BY_MAKS), ("duplicate", READ_BY_MAKS), (None, RESOLVED)],
    ids=["completed", "not_planned", "duplicate", "bez-powodu"],
)
def test_powod_zamkniecia_issue_rozstrzyga_stan_sprawy(
    tmp_path: Path, reason: CloseReason | None, state: dict[str, str]
) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    sent_note(centrum)
    centrum.surroundings.report_box.close(number_of(centrum, NOTE_TITLE), reason)

    assert rows(centrum) == [("uwaga", NOTE_TITLE, state, True)]


def test_uwaga_bez_tokenu_czeka_na_token_bez_kropki_a_skrzynka_nie_jest_pytana(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    assert sent_note(centrum) == QUEUED_FOR_KEY

    assert rows(centrum) == [("uwaga", NOTE_TITLE, QUEUED_FOR_KEY, False)]
    assert notifications(centrum)["unread"] == 0
    assert centrum.surroundings.report_box.listed == []


def test_oznacz_przeczytane_gasi_kropke_takze_po_restarcie_a_nowy_stan_znow_jest_nowy(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    sent_note(centrum)
    sent_note(centrum, "Suma godzin na dole tabeli")
    box, clock = centrum.surroundings.report_box, centrum.surroundings.clock
    box.close(number_of(centrum, NOTE_TITLE))
    before = notifications(centrum)
    assert before["unread"] == 1

    after = read(centrum, [item["id"] for item in before["items"]])

    assert after["unread"] == 0
    assert [item["unread"] for item in after["items"]] == [False, False]
    centrum.restart()
    assert notifications(centrum)["unread"] == 0
    box.close(number_of(centrum, "Suma godzin na dole tabeli"), "not_planned")
    clock.advance(minutes=10)
    assert rows(centrum) == [
        ("uwaga", "Suma godzin na dole tabeli", READ_BY_MAKS, True),
        ("uwaga", NOTE_TITLE, RESOLVED, False),
    ]


def test_powiadomienie_o_wycenie_w_efenix_przeczytane_przez_tate_zostaje_na_liscie_bez_kropki(tmp_path: Path) -> None:
    """Zakończona Wycena w efenix (tu Zatrzymaniem) to nowe Powiadomienie; po oznaczeniu przeczytanych zostaje na liście
    przy każdym następnym odczycie, już bez kropki."""

    centrum = settling_centrum(tmp_path)
    centrum.engines.fail_engine = True
    period = centrum.period_directory.name
    assert centrum.client.post("/api/runs", json={"process": "efenix", "period": period, "mode": "RUN"}).status_code == 200
    finished_view(centrum.client)

    def pricings(answer: dict[str, Any]) -> list[tuple[str, bool]]:
        return [(item["period"], item["unread"]) for item in answer["items"] if item["kind"] == "wycena_w_efenix"]

    before = centrum.client.get("/api/notifications").json()
    after = centrum.client.post("/api/notifications/read", json={"ids": [item["id"] for item in before["items"]]}).json()
    later = centrum.client.get("/api/notifications").json()

    assert [pricings(before), pricings(after), pricings(later)] == [[(period, True)], [(period, False)], [(period, False)]]
    assert [before["unread"], after["unread"], later["unread"]] == [1, 0, 0]


def test_przeczytane_sa_tylko_powiadomienia_ktore_tata_zobaczyl(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    sent_note(centrum)
    box, clock = centrum.surroundings.report_box, centrum.surroundings.clock
    seen = notifications(centrum)
    box.close(number_of(centrum, NOTE_TITLE))
    clock.advance(minutes=10)
    assert notifications(centrum)["unread"] == 1

    assert read(centrum, [item["id"] for item in seen["items"]])["unread"] == 1


def unavailable(where: str) -> dict[str, str]:
    """Komunikat Powiadomień o pliku stanu, którego Centrum nie może zapisać."""

    return {
        "what": "Centrum nie może teraz zapisać Powiadomień na tym komputerze, bo plik jest niedostępny.",
        "where": f"plik {where} w folderze config",
        "action": "Nie zamykaj Centrum: pamięta zmiany i zapisze je samo. Zamknij program, który może trzymać ten "
        "plik, i otwórz Powiadomienia ponownie. Jeśli Komunikat zostaje, wyślij Uwagę do Maksa.",
    }


def test_niedostepny_plik_spraw_taty_daje_komunikat_a_po_zwolnieniu_odczyt_zapisuje_numer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    locked = lock_file(monkeypatch, DAD_CASES_FILE)
    assert sent_note(centrum) == {"state": "sent"}

    blocked = notifications(centrum)
    locked.release()
    released = notifications(centrum)
    centrum.restart()

    assert blocked["message"] == unavailable(DAD_CASES_FILE)
    assert released["message"] is None
    assert rows(centrum) == [("uwaga", NOTE_TITLE, SENT, False)]


@pytest.mark.parametrize("again", ["odczyt", "oznaczenie"])
def test_niedostepny_plik_przeczytanych_daje_komunikat_a_po_zwolnieniu_zapisuje_je_odczyt_albo_oznaczenie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, again: str
) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    sent_note(centrum)
    centrum.surroundings.report_box.close(number_of(centrum, NOTE_TITLE))
    ids = [item["id"] for item in notifications(centrum)["items"]]
    locked = lock_file(monkeypatch, NOTIFICATIONS_FILE)

    blocked = read(centrum, ids)
    locked.release()
    released = notifications(centrum) if again == "odczyt" else read(centrum, ids)
    centrum.restart()

    assert (blocked["unread"], blocked["message"]) == (0, unavailable(NOTIFICATIONS_FILE))
    assert released["message"] is None
    assert notifications(centrum)["unread"] == 0


def test_oba_niedostepne_pliki_stanu_sa_w_jednym_komunikacie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    sent_note(centrum)
    centrum.surroundings.report_box.close(number_of(centrum, NOTE_TITLE))
    lock_file(monkeypatch, DAD_CASES_FILE)
    lock_file(monkeypatch, NOTIFICATIONS_FILE)

    answer = read(centrum, [item["id"] for item in notifications(centrum)["items"]])

    assert answer["message"] == {
        "what": "Centrum nie może teraz zapisać Powiadomień na tym komputerze, bo pliki są niedostępne.",
        "where": f"pliki {DAD_CASES_FILE} i {NOTIFICATIONS_FILE} w folderze config",
        "action": "Nie zamykaj Centrum: pamięta zmiany i zapisze je samo. Zamknij program, który może trzymać te "
        "pliki, i otwórz Powiadomienia ponownie. Jeśli Komunikat zostaje, wyślij Uwagę do Maksa.",
    }


def test_skrzynka_jest_pytana_przy_starcie_i_najwyzej_raz_na_10_minut(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    sent_report(centrum)
    clock = centrum.surroundings.clock
    asked = polls(centrum)

    notifications(centrum)
    notifications(centrum)
    clock.advance(minutes=9.9)
    notifications(centrum)

    assert polls(centrum) == asked + 1

    clock.advance(minutes=0.1)
    notifications(centrum)
    notifications(centrum)

    assert polls(centrum) == asked + 2

    centrum.restart()
    notifications(centrum)

    assert polls(centrum) == asked + 3


def test_zamknieta_sprawa_nie_jest_pytana_ponownie_a_jej_stan_zostaje_po_restarcie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    what = sent_report(centrum)
    box = centrum.surroundings.report_box
    box.close(box.sent[-1].number, "not_planned")
    assert rows(centrum) == [("zgloszenie", what, READ_BY_MAKS, True)]
    asked = polls(centrum)

    centrum.restart()
    box.search_failure = Unreachable()

    assert rows(centrum) == [("zgloszenie", what, READ_BY_MAKS, True)]
    assert polls(centrum) == asked


@pytest.mark.parametrize("failure", [Unreachable(), Refused()], ids=["brak-sieci", "odmowa"])
def test_porazka_skrzynki_przechodzi_po_cichu_z_ostatnim_znanym_stanem(
    tmp_path: Path, failure: Refused | Unreachable
) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    what = sent_report(centrum)
    box = centrum.surroundings.report_box
    box.close(box.sent[-1].number)
    box.search_failure = failure
    log_before = centrum.log_path.read_text(encoding="utf-8")
    asked = polls(centrum)

    assert rows(centrum) == [("zgloszenie", what, SENT, False)]
    assert polls(centrum) == asked + 1
    assert centrum.log_path.read_text(encoding="utf-8") == log_before


def test_bez_wyslanych_spraw_albo_klucza_skrzynka_nie_jest_pytana(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box

    assert notifications(centrum) == {"unread": 0, "items": [], "message": None}
    assert box.listed == []

    sent_report(centrum)
    asked = polls(centrum)
    ToolDirectory(tmp_path).report_key.unlink()

    notifications(centrum)
    assert polls(centrum) == asked


def test_przy_starcie_centrum_skrzynka_jest_pytana_w_tle_przed_odczytem_powiadomien(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    what = sent_report(centrum)
    box = centrum.surroundings.report_box
    box.close(box.sent[-1].number)
    centrum.restart()
    asked = polls(centrum)

    with centrum.client:  # start Centrum, jak po kliknięciu skrótu
        wait_for(lambda: polls(centrum) != asked, 5, every=0.01)
        asked_at_start = polls(centrum)

        assert rows(centrum) == [("zgloszenie", what, RESOLVED, True)]

    assert asked_at_start == polls(centrum) == asked + 1


def test_spozniona_odpowiedz_skrzynki_nie_wstrzymuje_powiadomien_a_jej_stan_i_tak_zostaje(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    what = sent_report(centrum)
    box = centrum.surroundings.report_box
    box.close(box.sent[-1].number)
    box.search_hold = threading.Event()
    started = time.monotonic()

    try:
        assert rows(centrum) == [("zgloszenie", what, SENT, False)]
        took = time.monotonic() - started
    finally:
        box.search_hold.set()

    assert took < CHECK_WAIT_S + 2
    wait_for(lambda: rows(centrum)[0][2] != SENT, 5, every=0.01)
    assert rows(centrum) == [("zgloszenie", what, RESOLVED, True)]


SUMMARY = "Plik zbiorczy ma kolumnę z kilometrami."
POINTS = ["Rozliczenia pracowników są dwa razy szybsze.", "Plik zbiorczy sam wpisuje ilości usług."]
NEW_COMMIT = "b7e4c1a2d3f5e6a7b8c9d0e1f2a3b4c5d6e7f8a9"
PUBLISHED_AT = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
# Sprawa z notki, której ten komputer nie wysłał: Uwaga taty z innego komputera.
FOREIGN = DadCase(999, "Uwaga z innego komputera", NOTE.label)


def published(tag: str, notes: str = SUMMARY, at: datetime = PUBLISHED_AT) -> PublishedRelease:
    release = Release.of_tag(tag)
    assert release is not None
    return PublishedRelease(release, notes, at)


def release_on_main(centrum: PreparingCentrum, tag: str, commit: str, *listed: PublishedRelease) -> None:
    """GitHub: najnowsze Wydanie na `main` to ``tag`` na ``commit``, a lista GitHub Releases to ``listed``."""

    github = centrum.surroundings.github
    github.release, github.tag, github.published = commit, tag, list(listed)


def new_versions(centrum: PreparingCentrum) -> list[dict[str, Any]]:
    return [item for item in notifications(centrum)["items"] if item["kind"] == "nowa_wersja"]


def test_nowsze_wydanie_daje_powiadomienie_z_notka_sprawami_taty_i_przyciskiem(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    what = sent_report(centrum)
    sent_note(centrum)
    cases = (
        DadCase(number_of(centrum, NOTE_TITLE), "Tytuł z Release", NOTE.label),
        DadCase(centrum.surroundings.report_box.sent[0].number, "Tytuł z Release", REPORT.label),
        FOREIGN,
    )
    notes = render(ReleaseNotes("\n".join([SUMMARY, "", *(f"- {point}" for point in POINTS)]), cases))
    release_on_main(centrum, "v0.2.0", NEW_COMMIT, published("v0.2.0", notes))
    # Odpowiedź GitHuba z Diagnozy przed Zgłoszeniem Centrum pamięta przez 10 minut.
    centrum.surroundings.clock.advance(minutes=10)

    answer = notifications(centrum)

    assert [item for item in answer["items"] if item["kind"] == "nowa_wersja"] == [
        {
            "kind": "nowa_wersja",
            "id": "wydanie-v0.2.0",
            "at": "2026-10-22T08:00:00Z",
            "unread": True,
            "version": "0.2.0",
            "intro": SUMMARY,
            "points": POINTS,
            "solved": [{"kind": "uwaga", "title": NOTE_TITLE}, {"kind": "zgloszenie", "title": what}],
            "update_offered": True,
        }
    ]
    assert answer["unread"] == 1
    assert centrum.client.get("/api/configuration").json()["update_offered"] is True


def test_notka_poprawiona_recznie_na_githubie_daje_co_nowego_bez_listy_i_sprawy_taty(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    sent_note(centrum)
    notes = f"{SUMMARY}\r\n### Rozwiązane sprawy taty \r\n- Uwaga taty #{number_of(centrum, NOTE_TITLE)}: {NOTE_TITLE}\r\n"
    release_on_main(centrum, "v0.2.0", NEW_COMMIT, published("v0.2.0", notes))

    assert [(item["intro"], item["points"], item["solved"]) for item in new_versions(centrum)] == [
        (SUMMARY, [], [{"kind": "uwaga", "title": NOTE_TITLE}])
    ]


def test_wydanie_nie_nowsze_od_wersji_taty_nie_ma_przycisku_ani_kropki_a_wyzsze_spoza_main_nie_jest_powiadomieniem(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path)
    tool = centrum.surroundings.github.tool_commit
    assert tool is not None
    release_on_main(
        centrum,
        "v0.2.0",
        tool,
        published("v0.3.0", "Wydanie z gałęzi spoza main.", PUBLISHED_AT + timedelta(days=1)),
        published("v0.2.0"),
        published("v0.1.0", "Pierwsza wersja z Powiadomieniami.", PUBLISHED_AT - timedelta(days=14)),
    )

    assert [(item["version"], item["update_offered"], item["unread"]) for item in new_versions(centrum)] == [
        ("0.2.0", False, False),
        ("0.1.0", False, False),
    ]
    assert notifications(centrum)["unread"] == 0
    assert centrum.client.get("/api/configuration").json()["update_offered"] is False


def test_po_przejsciu_na_wydanie_przycisk_znika_a_karta_zostaje_przeczytana(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    release_on_main(centrum, "v0.2.0", NEW_COMMIT, published("v0.2.0"))
    read(centrum, [item["id"] for item in new_versions(centrum)])

    centrum.surroundings.github.tool_commit = NEW_COMMIT  # Aktualizacja narzędzia i ponowny start Centrum
    centrum.restart()

    assert [(item["id"], item["unread"], item["update_offered"]) for item in new_versions(centrum)] == [
        ("wydanie-v0.2.0", False, False)
    ]
    assert notifications(centrum)["unread"] == 0


def test_nowe_wydanie_zapala_kropke_a_przycisk_przechodzi_na_nie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    release_on_main(centrum, "v0.2.0", NEW_COMMIT, published("v0.2.0"))
    read(centrum, [item["id"] for item in new_versions(centrum)])
    assert notifications(centrum)["unread"] == 0

    newer = published("v0.3.0", "Rozliczenia pracowników są szybsze.", PUBLISHED_AT + timedelta(days=7))
    release_on_main(centrum, "v0.3.0", "c" * 40, newer, published("v0.2.0"))
    centrum.surroundings.clock.advance(minutes=10)

    assert [(item["version"], item["unread"], item["update_offered"]) for item in new_versions(centrum)] == [
        ("0.3.0", True, True),
        ("0.2.0", False, False),
    ]
    assert notifications(centrum)["unread"] == 1


def test_bez_sieci_powiadomienia_o_wydaniach_zostaja_bez_zmian_i_bez_komunikatu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    github, clock = centrum.surroundings.github, centrum.surroundings.clock
    github.release, github.published = None, None
    assert new_versions(centrum) == []
    release_on_main(centrum, "v0.2.0", NEW_COMMIT, published("v0.2.0"))
    clock.advance(minutes=10)
    known = notifications(centrum)
    asked = (github.asked, github.asked_published)

    github.release, github.published = None, None
    clock.advance(minutes=10)
    response = centrum.client.get("/api/notifications")

    assert (response.status_code, response.json()) == (200, known)
    assert (github.asked, github.asked_published) == (asked[0] + 1, asked[1] + 1)
    assert not centrum.log_path.exists() or "nieoczekiwany-wyjatek" not in centrum.log_path.read_text(encoding="utf-8")


def test_github_jest_pytany_o_wydania_przy_starcie_i_najwyzej_raz_na_10_minut_wspolnie_z_konfiguracja(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path)
    release_on_main(centrum, "v0.2.0", NEW_COMMIT, published("v0.2.0"))
    github, clock = centrum.surroundings.github, centrum.surroundings.clock

    with centrum.client:  # start Centrum, jak po kliknięciu skrótu
        wait_for(lambda: github.asked_published != 0, 5, every=0.01)
        assert (github.asked, github.asked_published) == (1, 1)

        for _ in range(3):
            notifications(centrum)
            centrum.client.get("/api/configuration")
            clock.advance(minutes=3)
        assert (github.asked, github.asked_published) == (1, 1)

        clock.advance(minutes=1)
        assert [item["version"] for item in new_versions(centrum)] == ["0.2.0"]
        centrum.client.get("/api/configuration")
        assert (github.asked, github.asked_published) == (2, 2)


def queued_report(centrum: PreparingCentrum) -> str:
    """Zgłoszenie „do Maksa”, które czeka w kolejce Skrzynki (bez Tokenu do Zgłoszeń); zwraca jego „Co się stało”."""

    run_id = stopped_for_maks(centrum)
    diagnosis = centrum.client.post(f"/api/runs/{run_id}/diagnosis").json()
    assert centrum.client.post(f"/api/runs/{run_id}/report").json() == {"state": "queued", "waits_for": "key"}
    what: str = diagnosis["report"]["title"].split(": ", 1)[1]
    return what


def delivered_from_queue(centrum: PreparingCentrum) -> int:
    """Maks wpisuje klucz, kolejka budzi się po minucie i dostarcza Zgłoszenie; zwraca numer jego issue."""

    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box
    centrum.surroundings.clock.advance(RETRY_S)
    assert box.wait_until(lambda box: len(box.sent) == 1)
    number = box.sent[0].number
    assert wait_for(lambda: case_states(centrum.client, "zgloszenie") == [SENT])
    return number


def test_zgloszenie_w_kolejce_bez_tokenu_czeka_na_token_a_po_dostarczeniu_jest_wyslane_bez_kropki(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    what = queued_report(centrum)
    waiting = notifications(centrum)

    number = delivered_from_queue(centrum)

    assert [(item["what"], item["state"], item["unread"]) for item in waiting["items"]] == [
        (what, QUEUED_FOR_KEY, False)
    ]
    [item] = notifications(centrum)["items"]
    assert (item["id"], item["state"], item["unread"]) == (f"zgloszenie-{number}-wyslana", SENT, False)


def test_wydanie_rozwiazuje_zgloszenie_wyslane_z_kolejki(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    what = queued_report(centrum)
    number = delivered_from_queue(centrum)
    cases = (DadCase(number, "Tytuł z Release", REPORT.label),)
    release_on_main(centrum, "v0.2.0", NEW_COMMIT, published("v0.2.0", render(ReleaseNotes(SUMMARY, cases))))
    centrum.surroundings.clock.advance(minutes=10)

    [version] = new_versions(centrum)

    assert version["solved"] == [{"kind": "zgloszenie", "title": what}]


def test_zgloszenie_wyslane_przed_kolejka_zostaje_przeczytane(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    config = ToolDirectory(tmp_path).config
    (config / OLD_REPORTS_FILE).write_text(
        json.dumps(
            [
                {
                    "fingerprint": "0123456789abcdef",
                    "number": 12,
                    "commit": TOOL_COMMIT,
                    "what": "Nie znaleziono wzorca.",
                    "sent_at": "2026-10-19T08:00:00+00:00",
                    "closure": {"reason": "completed", "at": CLOSED_AT.isoformat()},
                }
            ]
        ),
        encoding="utf-8",
    )
    (config / NOTIFICATIONS_FILE).write_text(
        json.dumps({"schema_version": 1, "przeczytane": ["zgloszenie-12-rozwiazana"]}), encoding="utf-8"
    )
    centrum.restart()

    answer = notifications(centrum)

    assert [(item["id"], item["unread"]) for item in answer["items"]] == [("zgloszenie-12-rozwiazana", False)]
    assert answer["unread"] == 0


def queued_case(fingerprint: str, what: str) -> dict[str, object]:
    """Zgłoszenie w pliku Spraw taty, które czeka w kolejce Skrzynki: bez numeru issue."""

    return {
        "kind": "zgloszenie",
        "id": fingerprint,
        "title": what,
        "commit": TOOL_COMMIT,
        "sent_at": "2026-10-19T08:00:00+00:00",
        "number": None,
        "closure": None,
    }


def test_dwa_zgloszenia_w_kolejce_to_dwa_powiadomienia_o_roznych_id(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    cases = [queued_case("0123456789abcdef", "Nie znaleziono wzorca."), queued_case("fedcba9876543210", "Brak folderu.")]
    (config / DAD_CASES_FILE).write_text(json.dumps({"schema_version": 1, "sprawy": cases}), encoding="utf-8")

    items = plain_centrum(tmp_path).client.get("/api/notifications").json()["items"]

    assert sorted((item["what"], item["state"]) for item in items) == [
        ("Brak folderu.", QUEUED_FOR_KEY),
        ("Nie znaleziono wzorca.", QUEUED_FOR_KEY),
    ]
    assert len({item["id"] for item in items}) == 2
