"""Sprawy taty (ADR 0015): jeden plik stanu Uwag taty i wysłanych Zgłoszeń oraz pliki sprzed niego u taty.

Pliki w ``tests/fixtures`` zapisał kod sprzed jednego magazynu (``SentReports`` i ``DadNotes``): z `main` przed
zmianą oraz z pierwszych wersji Zgłoszeń (2026-10-20) i Uwag taty (2026-10-23).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import threading
from typing import Any

import pytest

from rozliczenia.centrum.case_delivery import case_outbox
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE, NOTE, OLD_NOTES_FILE, OLD_REPORTS_FILE, REPORT, Case, DadCases
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import KnownIssue, NewIssue, PeriodThread, Post
from rozliczenia.centrum.report_box import (
    Closure,
    CommentOutcome,
    CommentsOutcome,
    Issue,
    IssuesOutcome,
    Label,
    Refused,
    SendOutcome,
    Sent,
    Unreachable,
)

from tests.fixtures.centrum import RUN_LOGS_IN_BACKGROUND, FakeIssue, FakeReportBox, centrum
from tests.fixtures.clock import ManualClock
from tests.fixtures.locked_file import lock_file

FIXTURES = Path(__file__).parent / "fixtures"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"
QUEUED_NOTE = "ffeeddccbbaa49988776655443322110"


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


OLD_CASES = [
    Case(
        REPORT,
        "3f0c1b2a9d8e7f60",
        "Nie znaleziono Wzorca pliku zbiorczego.",
        COMMIT,
        at(20, 8),
        7,
        Closure("completed", at(22, 10)),
    ),
    Case(REPORT, "a1b2c3d4e5f60718", "Brak połączenia z GitHubem.", None, at(21, 9, 30), 9),
    Case(
        NOTE,
        "5e1f0c2d3b4a49e8b7c6d5e4f3a2b1c0",
        "Plik zbiorczy otwiera się długo",
        COMMIT,
        at(23, 7, 45),
        11,
        Closure("not_planned", at(24, 9)),
    ),
    Case(
        NOTE,
        "0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d",
        "Brakuje ilości przy montażu",
        None,
        at(23, 8, 15),
        12,
        run_id="b4c3d2e1f0a94b8c",
    ),
    Case(NOTE, QUEUED_NOTE, "Wiersz zniknął", None, at(24, 6), None),
]
NEW = Case(NOTE, "1234abcd1234abcd1234abcd1234abcd", "Nowa Uwaga", COMMIT, at(24, 12), None)
VALID_ENTRY: dict[str, Any] = {
    "kind": "uwaga",
    "id": "1234abcd1234abcd1234abcd1234abcd",
    "title": "Nowa Uwaga",
    "commit": COMMIT,
    "sent_at": "2026-10-24T12:00:00+00:00",
    "number": None,
    "closure": None,
    "run_id": None,
}


def log(tmp_path: Path) -> CentrumLog:
    return CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log")


def old_files(tmp_path: Path, reports: str = "zgloszenia-wyslane.json", notes: str = "uwagi-taty.json") -> Path:
    config = tmp_path / "config"
    config.mkdir()
    shutil.copy(FIXTURES / reports, config / OLD_REPORTS_FILE)
    shutil.copy(FIXTURES / notes, config / OLD_NOTES_FILE)
    return config


def cases(tmp_path: Path) -> list[Case]:
    return DadCases(tmp_path / "config", log(tmp_path), pause=ManualClock().pause).all()


def with_document(tmp_path: Path, name: str, document: object) -> None:
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / name).write_text(json.dumps(document), encoding="utf-8")


def test_stare_pliki_zgloszen_i_uwag_wczytuja_sie_jako_sprawy_taty(tmp_path: Path) -> None:
    old_files(tmp_path)

    assert cases(tmp_path) == OLD_CASES


def test_wpisy_sprzed_powiadomien_wczytuja_sie_a_zgloszenie_nie_ma_tytulu_ani_czasu(tmp_path: Path) -> None:
    old_files(tmp_path, "zgloszenia-wyslane-sprzed-powiadomien.json", "uwagi-taty-sprzed-powiadomien.json")

    assert cases(tmp_path) == [
        Case(REPORT, "3f0c1b2a9d8e7f60", None, COMMIT, None, 4),
        Case(NOTE, "c0ffee00c0ffee00c0ffee00c0ffee00", "Uwaga sprzed Powiadomień", None, at(23, 12), 5),
    ]


def test_pierwszy_zapis_przenosi_stare_sprawy_do_pliku_spraw_taty_a_stare_pliki_zostaja(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    old = {name: (config / name).read_bytes() for name in (OLD_REPORTS_FILE, OLD_NOTES_FILE)}

    DadCases(config, log(tmp_path), pause=ManualClock().pause).add(NEW)
    restarted = cases(tmp_path)
    for name in old:
        (config / name).unlink()

    assert {name: (FIXTURES / name).read_bytes() for name in old} == old
    assert restarted == cases(tmp_path) == [*OLD_CASES, NEW]


def test_uszkodzony_plik_spraw_taty_to_brak_spraw_takze_przy_starych_plikach(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    (config / DAD_CASES_FILE).write_text('{"schema_version": 1, "sprawy": [', encoding="utf-8")

    assert cases(tmp_path) == []


@pytest.mark.parametrize("document", [[VALID_ENTRY], {"schema_version": 2, "sprawy": [VALID_ENTRY]}])
def test_plik_spraw_taty_w_nieznanym_schemacie_to_brak_spraw(tmp_path: Path, document: object) -> None:
    with_document(tmp_path, DAD_CASES_FILE, document)

    assert cases(tmp_path) == []


@pytest.mark.parametrize("damaged", [OLD_REPORTS_FILE, OLD_NOTES_FILE])
def test_uszkodzony_stary_plik_nie_zabiera_spraw_z_drugiego(tmp_path: Path, damaged: str) -> None:
    config = old_files(tmp_path)
    (config / damaged).write_bytes(b"\xff\xfe uszkodzony")

    kept = REPORT if damaged == OLD_NOTES_FILE else NOTE
    assert cases(tmp_path) == [case for case in OLD_CASES if case.kind == kept]


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": 1},
        {"schema_version": 2, "uwagi": json.loads((FIXTURES / "uwagi-taty.json").read_text(encoding="utf-8"))["uwagi"]},
        [],
    ],
    ids=["bez-uwag", "nieznany-schemat", "lista"],
)
def test_stary_plik_uwag_w_nieznanym_ksztalcie_to_brak_uwag(tmp_path: Path, document: object) -> None:
    with_document(tmp_path, OLD_NOTES_FILE, document)

    assert cases(tmp_path) == []


def test_stary_plik_zgloszen_w_nieznanym_ksztalcie_to_brak_zgloszen(tmp_path: Path) -> None:
    with_document(tmp_path, OLD_REPORTS_FILE, {"zgloszenia": []})

    assert cases(tmp_path) == []


OLD_REPORT = {"fingerprint": "3f0c1b2a9d8e7f60", "number": 4, "commit": None}
OLD_NOTE = {"id": "c0ffee00", "title": "Uwaga", "commit": None, "written_at": "2026-10-23T12:00:00+00:00", "number": 5}


@pytest.mark.parametrize(
    ("name", "entry"),
    [
        (OLD_REPORTS_FILE, "nie wpis"),
        (OLD_REPORTS_FILE, {**OLD_REPORT, "number": None}),
        (OLD_REPORTS_FILE, {**OLD_REPORT, "number": True}),
        (OLD_REPORTS_FILE, {**OLD_REPORT, "fingerprint": None}),
        (OLD_NOTES_FILE, "nie wpis"),
        (OLD_NOTES_FILE, {**OLD_NOTE, "title": 7}),
        (OLD_NOTES_FILE, {**OLD_NOTE, "written_at": "2026-10-23T12:00:00"}),
        (OLD_NOTES_FILE, {**OLD_NOTE, "id": None}),
    ],
    ids=[
        "zgloszenie-nie-obiekt",
        "zgloszenie-bez-numeru",
        "zgloszenie-numer-bool",
        "zgloszenie-bez-odcisku",
        "uwaga-nie-obiekt",
        "uwaga-tytul-liczba",
        "uwaga-czas-bez-strefy",
        "uwaga-bez-identyfikatora",
    ],
)
def test_wpis_starego_pliku_ktorego_nie_da_sie_odczytac_jest_pominiety(
    tmp_path: Path, name: str, entry: object
) -> None:
    if name == OLD_REPORTS_FILE:
        with_document(tmp_path, name, [entry, OLD_REPORT])
    else:
        with_document(tmp_path, name, {"schema_version": 1, "uwagi": [entry, OLD_NOTE]})

    [case] = cases(tmp_path)

    assert case.number == (4 if name == OLD_REPORTS_FILE else 5)


@pytest.mark.parametrize("run_id", [3, "b4c3d2e1f0a94b8c"])
def test_zgloszenie_ze_starego_pliku_nie_bierze_uruchomienia_z_wpisu(tmp_path: Path, run_id: object) -> None:
    with_document(tmp_path, OLD_REPORTS_FILE, [{**OLD_REPORT, "run_id": run_id}])

    [case] = cases(tmp_path)

    assert (case.kind, case.number, case.run_id) == (REPORT, 4, None)


@pytest.mark.parametrize(
    "entry",
    [
        "nie wpis",
        {**VALID_ENTRY, "kind": "kontrola-ilosci"},
        {**VALID_ENTRY, "kind": None},
        {**VALID_ENTRY, "kind": ["uwaga"]},
        {**VALID_ENTRY, "id": 7},
        {**VALID_ENTRY, "commit": 7},
        {**VALID_ENTRY, "run_id": 7},
        {**VALID_ENTRY, "number": "7"},
    ],
    ids=[
        "nie-obiekt",
        "nieznany-rodzaj",
        "bez-rodzaju",
        "rodzaj-lista",
        "identyfikator",
        "commit",
        "uruchomienie",
        "numer",
    ],
)
def test_wpis_pliku_spraw_taty_z_polem_zlego_typu_jest_pominiety(tmp_path: Path, entry: object) -> None:
    with_document(tmp_path, DAD_CASES_FILE, {"schema_version": 1, "sprawy": [entry, VALID_ENTRY]})

    assert cases(tmp_path) == [NEW]


def test_tytul_nie_tekst_i_nieczytelny_czas_zostawiaja_sprawe_bez_nich(tmp_path: Path) -> None:
    entry = {**VALID_ENTRY, "title": ["Nowa"], "sent_at": "wczoraj", "closure": {"reason": "spam", "at": "jutro"}}
    with_document(tmp_path, DAD_CASES_FILE, {"schema_version": 1, "sprawy": [entry]})

    assert cases(tmp_path) == [Case(NOTE, NEW.id, None, COMMIT, None, None, Closure(None, None))]


def test_numer_issue_dostaje_tylko_sprawa_z_wysylki_o_jej_etykiecie_i_identyfikatorze(tmp_path: Path) -> None:
    stored = DadCases(old_files(tmp_path), log(tmp_path), pause=ManualClock().pause)
    skrzynka = Skrzynka(tmp_path, stored, FakeReportBox(outcomes=[Sent(20)], issues=[ZGLOSZENIE_3], background=LOGS))

    skrzynka.sent(
        *(
            Post(target, period=None, run_id=QUEUED_NOTE, header=None, parts=("treść",))
            for target in (
                NewIssue("uwaga-taty", "Wiersz zniknął"),
                PeriodThread(label="logi-uruchomienia", line="- Logi", closed="reuse", title="Logi"),
                KnownIssue("zgloszenie", 3),
            )
        )
    )

    assert [case.number for case in cases(tmp_path)] == [7, 9, 11, 12, 20]


def test_uwaga_dostarczona_drugi_raz_ma_numer_nowego_issue(tmp_path: Path) -> None:
    stored = DadCases(tmp_path / "config", log(tmp_path), pause=ManualClock().pause)
    stored.add(NEW)

    answers = (stored.numbered(NOTE, NEW.id, 20), stored.numbered(NOTE, NEW.id, 21))

    assert answers == (True, True)
    assert [case.number for case in cases(tmp_path)] == [21]


def test_sprawe_wskazuje_rodzaj_i_identyfikator_a_z_kilku_wysylek_liczy_sie_ostatnia(tmp_path: Path) -> None:
    stored = DadCases(tmp_path / "config", log(tmp_path), pause=ManualClock().pause)
    first = Case(REPORT, "3f0c1b2a9d8e7f60", "Brak Wzorca", None, at(20, 8), 7, Closure("completed", at(21, 8)))
    again = Case(REPORT, "3f0c1b2a9d8e7f60", "Brak Wzorca", None, at(22, 8), 15)
    note = Case(NOTE, "3f0c1b2a9d8e7f60", "Uwaga o tym samym identyfikatorze", None, at(23, 8), 16)
    for case in (first, again, note):
        stored.add(case)

    found = (stored.find(REPORT, "3f0c1b2a9d8e7f60"), stored.find(NOTE, "3f0c1b2a9d8e7f60"))
    stored.forget(NOTE, "3f0c1b2a9d8e7f60")

    assert found == (again, note)
    assert cases(tmp_path) == [first, again]


def test_numer_zgloszenia_dostaje_tylko_czekajace_zgloszenie_a_bez_niego_nic_sie_nie_zmienia(tmp_path: Path) -> None:
    stored = DadCases(tmp_path / "config", log(tmp_path), pause=ManualClock().pause)
    queued = Case(REPORT, "3f0c1b2a9d8e7f60", "Brak Wzorca", None, at(22, 8), None)
    note = Case(NOTE, "3f0c1b2a9d8e7f60", "Uwaga o tym samym identyfikatorze", None, at(23, 8), None)
    for case in (queued, note):
        stored.add(case)

    answers = (stored.numbered(REPORT, "3f0c1b2a9d8e7f60", 15), stored.numbered(REPORT, "3f0c1b2a9d8e7f60", 16))

    assert answers == (True, False)
    assert cases(tmp_path) == [Case(REPORT, "3f0c1b2a9d8e7f60", "Brak Wzorca", None, at(22, 8), 15), note]


class AnsweringBox:
    """Skrzynka, która na pytanie o issue z etykietą odpowiada z góry ustaloną odpowiedzią i zapisuje pytania."""

    def __init__(self, answers: dict[Label, IssuesOutcome]) -> None:
        self.answers = answers
        self.asked: list[tuple[Label, bool, str]] = []

    def open_issue(self, label: Label, title: str, body: str, *, key: str) -> SendOutcome:
        raise AssertionError("Sprawy taty nie zakładają issue")

    def comment(self, number: int, body: str, *, key: str) -> CommentOutcome:
        raise AssertionError("Sprawy taty nie komentują issue")

    def comments(self, number: int, *, key: str) -> CommentsOutcome:
        raise AssertionError("Sprawy taty nie czytają komentarzy issue")

    def edit_comment(self, comment_id: int, body: str, *, key: str) -> CommentOutcome:
        raise AssertionError("Sprawy taty nie zmieniają komentarzy issue")

    def labelled_issues(self, label: Label, *, include_closed: bool, key: str) -> IssuesOutcome:
        self.asked.append((label, include_closed, key))
        return self.answers[label]


def keyed(box: AnsweringBox) -> KeyedBox:
    return KeyedBox(box, lambda: KEY, clock=ManualClock())


def test_skrzynka_jest_pytana_o_rodzaj_z_otwartymi_sprawami_a_jej_zamkniecia_trafiaja_do_spraw(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    closed = Closure("completed", at(24, 15))
    box = AnsweringBox({"uwaga-taty": (Issue(12, "", closed), Issue(11, "", None), Issue(40, "", closed))})
    stored = DadCases(config, log(tmp_path), pause=ManualClock().pause)
    stored.forget(REPORT, "a1b2c3d4e5f60718")

    stored.ask_box(keyed(box))

    assert box.asked == [("uwaga-taty", True, KEY)]
    assert [case.closure for case in cases(tmp_path)] == [OLD_CASES[0].closure, None, closed, None]


def test_uwaga_w_kolejce_i_zamkniete_sprawy_nie_pytaja_skrzynki(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    stored = DadCases(config, log(tmp_path), pause=ManualClock().pause)
    stored.forget(REPORT, "a1b2c3d4e5f60718")
    stored.forget(NOTE, "0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d")
    box = AnsweringBox({})

    stored.ask_box(keyed(box))

    assert box.asked == []


def test_bez_odpowiedzi_skrzynki_zostaje_ostatni_znany_stan(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    closed = Closure("completed", at(24, 15))
    box = AnsweringBox({"zgloszenie": Unreachable(), "uwaga-taty": (Issue(12, "", closed),)})

    DadCases(config, log(tmp_path), pause=ManualClock().pause).ask_box(keyed(box))

    assert [label for label, _, _ in box.asked] == ["zgloszenie", "uwaga-taty"]
    assert [case.closure for case in cases(tmp_path)] == [
        OLD_CASES[0].closure,
        None,
        OLD_CASES[2].closure,
        closed,
        None,
    ]


def test_po_odmowie_klucza_skrzynka_nie_jest_pytana_o_drugi_rodzaj_a_stan_zostaje(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    box = AnsweringBox({"zgloszenie": Refused(), "uwaga-taty": (Issue(12, "", Closure("completed", at(24, 15))),)})

    DadCases(config, log(tmp_path), pause=ManualClock().pause).ask_box(keyed(box))

    assert [label for label, _, _ in box.asked] == ["zgloszenie"]
    assert [case.closure for case in cases(tmp_path)] == [case.closure for case in OLD_CASES]


def test_sprawa_niedostepnego_pliku_czeka_w_pamieci_az_zapisze_ja_zmiana_ktora_nic_nie_zmienia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = lock_file(monkeypatch, DAD_CASES_FILE)
    stored = DadCases(tmp_path / "config", log(tmp_path), pause=ManualClock().pause)

    stored.add(NEW)
    waiting = (stored.all(), stored.file.unavailable, cases(tmp_path))
    locked.release()
    stored.forget(NOTE, "nieznana")

    assert waiting == ([NEW], True, [])
    assert "stan Spraw taty" in (tmp_path / "logs" / "centrum-rozliczen.log").read_text(encoding="utf-8")
    assert (stored.file.unavailable, cases(tmp_path)) == (False, [NEW])


def test_sprawa_bez_zmian_nie_zapisuje_pliku(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    stored = DadCases(config, log(tmp_path), pause=ManualClock().pause)

    stored.forget(NOTE, "nieznana")
    stored.numbered(NOTE, "nieznana", 3)

    assert not (config / DAD_CASES_FILE).exists()


def notifications(tmp_path: Path) -> list[tuple[str, str, bool, str]]:
    items = centrum(tmp_path).client.get("/api/notifications").json()["items"]
    return [
        (item["kind"], item["id"], item["unread"], item.get("title") or item.get("what"))
        for item in items
        if item["kind"] in ("uwaga", "zgloszenie")
    ]


def test_sprawy_ze_starych_plikow_daja_te_same_powiadomienia(tmp_path: Path) -> None:
    old_files(tmp_path)

    assert notifications(tmp_path) == [
        ("uwaga", "uwaga-5e1f0c2d3b4a49e8b7c6d5e4f3a2b1c0-przeczytana", True, "Plik zbiorczy otwiera się długo"),
        ("uwaga", f"uwaga-{QUEUED_NOTE}-czeka_na_token", False, "Wiersz zniknął"),
        ("uwaga", "uwaga-0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d-wyslana", False, "Brakuje ilości przy montażu"),
        ("zgloszenie", "zgloszenie-7-rozwiazana", True, "Nie znaleziono Wzorca pliku zbiorczego."),
        ("zgloszenie", "zgloszenie-9-wyslana", False, "Brak połączenia z GitHubem."),
    ]


def test_zgloszenie_bez_co_sie_stalo_albo_czytelnego_czasu_nie_daje_powiadomienia(tmp_path: Path) -> None:
    old_files(tmp_path, "zgloszenia-wyslane-sprzed-powiadomien.json", "uwagi-taty-sprzed-powiadomien.json")
    with_document(
        tmp_path,
        OLD_REPORTS_FILE,
        [
            *json.loads((FIXTURES / "zgloszenia-wyslane-sprzed-powiadomien.json").read_text(encoding="utf-8")),
            {
                "fingerprint": "a1b2c3d4e5f60718",
                "number": 9,
                "commit": None,
                "what": "Brak sieci",
                "sent_at": "wczoraj",
            },
            {"fingerprint": "b2c3d4e5f6071829", "number": 10, "commit": None, "sent_at": "2026-10-21T09:30:00+00:00"},
        ],
    )

    assert notifications(tmp_path) == [
        ("uwaga", "uwaga-c0ffee00c0ffee00c0ffee00c0ffee00-wyslana", False, "Uwaga sprzed Powiadomień")
    ]


def test_uszkodzony_plik_spraw_taty_w_innym_kodowaniu_to_brak_spraw(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    (config / DAD_CASES_FILE).write_bytes(json.dumps({"schema_version": 1, "sprawy": []}).encode("utf-16"))

    assert cases(tmp_path) == []


def test_stary_plik_z_urwanym_json_nie_zabiera_spraw_z_drugiego(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    text = (config / OLD_REPORTS_FILE).read_text(encoding="utf-8")
    (config / OLD_REPORTS_FILE).write_text(text[: len(text) // 2], encoding="utf-8")

    assert cases(tmp_path) == [case for case in OLD_CASES if case.kind == NOTE]


def test_sprawa_bez_czasow_i_z_polskimi_literami_wraca_z_pliku_bez_zmian(tmp_path: Path) -> None:
    case = Case(REPORT, "3f0c1b2a9d8e7f60", None, None, None, 7, Closure("not_planned", None))
    note = Case(NOTE, NEW.id, "Brakuje ilości", None, at(24, 12), 8, run_id="b4c3d2e1f0a94b8c")
    stored = DadCases(tmp_path / "config", log(tmp_path), pause=ManualClock().pause)
    stored.add(case)
    stored.add(note)

    assert cases(tmp_path) == [case, note]
    assert "Brakuje ilości" in (tmp_path / "config" / DAD_CASES_FILE).read_text(encoding="utf-8")


PINNED_ID = "0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d"
PINNED_RUN = "b4c3d2e1f0a94b8c"
WAITING_LOGS = f"Logi Uruchomienia: w drodze (Uruchomienie {PINNED_RUN})"
REJECTED_LOGS = (
    f"Logi Uruchomienia: nie dotarły, Skrzynka odrzuciła ich treść (Uruchomienie {PINNED_RUN}). "
    "Odnośnik przyjdzie w komentarzu, gdy dotrą."
)
LOGS_GONE = f"Logi Uruchomienia nie dotrą: Centrum przestało je wysyłać (Uruchomienie {PINNED_RUN})."
LOGS: frozenset[Label] = RUN_LOGS_IN_BACKGROUND
ZGLOSZENIE_3 = FakeIssue(3, "zgloszenie", "Zgłoszenie", "- Odcisk problemu: 3f0c1b2a9d8e7f60")
UWAGA_12 = FakeIssue(12, "uwaga-taty", "Brakuje ilości przy montażu", "Uwaga")


class Skrzynka:
    """Kolejka Skrzynki Zgłoszeń Centrum ze Sprawami taty ``stored`` (``case_outbox``) na fałszywej skrzynce."""

    def __init__(self, tmp_path: Path, stored: DadCases, box: FakeReportBox) -> None:
        clock = ManualClock()
        self.box = box
        self.directory = tmp_path / "kolejka"
        self.directory.mkdir()
        self.outbox = case_outbox(
            self.directory, KeyedBox(box, lambda: KEY, clock=clock), log(tmp_path), stored, clock=clock, addresses=None
        )

    def sent(self, *posts: Post) -> None:
        """Kładzie ``posts`` w kolejce i czeka na koniec przejścia, także wysyłek następczych z tego przejścia."""

        for post in posts:
            assert self.outbox.post(post)
        assert not self.outbox.wait_delivered("", "kontrola-ilosci", timeout_s=30)
        assert sorted(self.directory.glob("*.json")) == []

    def logs_delivered(self, *run_ids: str) -> None:
        """Logi Uruchomień ``run_ids`` doszły do Skrzynki z adresem komentarza."""

        logs = PeriodThread(label="logi-uruchomienia", line="- Logi", closed="reuse", title="Logi")
        self.sent(*(Post(logs, period=None, run_id=run_id, header="Logi okresu", parts=("Logi",)) for run_id in run_ids))
        assert all(self.outbox.delivered(run_id, "logi-uruchomienia") is not None for run_id in run_ids)

    def texts(self) -> list[str]:
        """Treści i komentarze wszystkich issue skrzynki, także Logów."""

        return [text for issue in (*self.box.issues, *self.box.background_issues) for text in (issue.body, *issue.comments)]


OTHER_TARGETS = {
    "logi-uruchomienia": PeriodThread(label="logi-uruchomienia", line="- Logi", closed="reuse", title="Logi"),
    "komentarz-zgloszenia": KnownIssue("zgloszenie", 3),
    "nowe-zgloszenie": NewIssue("zgloszenie", "Zgłoszenie"),
}


@pytest.mark.parametrize("target", OTHER_TARGETS.values(), ids=OTHER_TARGETS.keys())
def test_wysylka_innej_etykiety_o_identyfikatorze_uwagi_idzie_bez_zmian(
    tmp_path: Path, target: PeriodThread | KnownIssue | NewIssue
) -> None:
    stored = DadCases(old_files(tmp_path), log(tmp_path), pause=ManualClock().pause)
    skrzynka = Skrzynka(tmp_path, stored, FakeReportBox(issues=[ZGLOSZENIE_3], background=LOGS))
    # Logi także pod identyfikatorem Uwagi: wysyłka innej etykiety nie dostaje odnośnika, choć Logi o nim są.
    skrzynka.logs_delivered(PINNED_RUN, PINNED_ID)

    skrzynka.sent(Post(target, period=None, run_id=PINNED_ID, header=None, parts=(f"Treść\n{WAITING_LOGS}",)))

    assert f"Treść\n{WAITING_LOGS}" in skrzynka.texts()


@pytest.mark.parametrize(
    "target", [*OTHER_TARGETS.values(), KnownIssue("uwaga-taty", 12)], ids=[*OTHER_TARGETS.keys(), "komentarz-uwagi"]
)
def test_tylko_nowa_uwaga_dostaje_komentarz_o_odrzuconych_logach(
    tmp_path: Path, target: PeriodThread | KnownIssue | NewIssue
) -> None:
    stored = DadCases(old_files(tmp_path), log(tmp_path), pause=ManualClock().pause)
    skrzynka = Skrzynka(tmp_path, stored, FakeReportBox(issues=[ZGLOSZENIE_3, UWAGA_12], background=LOGS))

    skrzynka.sent(Post(target, period=None, run_id=PINNED_ID, header=None, parts=(f"Treść\n{REJECTED_LOGS}",)))

    assert LOGS_GONE not in skrzynka.texts()


def test_nowa_uwaga_po_odrzuconych_logach_dostaje_komentarz(tmp_path: Path) -> None:
    stored = DadCases(old_files(tmp_path), log(tmp_path), pause=ManualClock().pause)
    skrzynka = Skrzynka(tmp_path, stored, FakeReportBox(background=LOGS))
    note = Post(NewIssue("uwaga-taty", "Uwaga"), period=None, run_id=PINNED_ID, header=None, parts=(REJECTED_LOGS,))

    skrzynka.sent(note)

    [issue] = skrzynka.box.issues_with("uwaga-taty")
    assert (issue.body, issue.comments) == (REJECTED_LOGS, [LOGS_GONE])
    assert stored.find(NOTE, PINNED_ID) == replace(OLD_CASES[3], number=issue.number)


def test_wysylka_uwagi_nieznanej_temu_komputerowi_idzie_bez_zmian(tmp_path: Path) -> None:
    stored = DadCases(old_files(tmp_path), log(tmp_path), pause=ManualClock().pause)
    skrzynka = Skrzynka(tmp_path, stored, FakeReportBox(background=LOGS))
    skrzynka.logs_delivered(PINNED_RUN)

    skrzynka.sent(Post(NewIssue("uwaga-taty", "Uwaga"), period=None, run_id="nieznana", header=None, parts=(WAITING_LOGS,)))

    [issue] = skrzynka.box.issues_with("uwaga-taty")
    assert (issue.body, issue.comments) == (WAITING_LOGS, [])


def test_sprawdzanie_powiadomien_w_tle_nie_wstrzymuje_zamkniecia_centrum(tmp_path: Path) -> None:
    config = old_files(tmp_path)
    (config / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    started = centrum(tmp_path)
    hold = started.report_box.search_hold = threading.Event()
    try:
        started.client.get("/api/notifications")
        checks = [thread for thread in threading.enumerate() if thread.name == "powiadomienia-sprawdzanie"]
    finally:
        hold.set()

    assert checks
    assert all(thread.daemon for thread in checks)
