"""Klucz do Zgłoszeń i werdykt Skrzynki o nim (``KeyedBox``) na fałszywej skrzynce i zegarze testu.

Seam z kilkoma wejściami (kolejka Skrzynki, Powiadomienia, Zgłoszenia, Konfiguracja, Diagnoza), więc macierz
werdyktu jest sprawdzona tu raz; każde wejście ma swój test tłumaczenia przez HTTP.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from rozliczenia.centrum.github import NO_ANSWER_KEPT_S
from rozliczenia.centrum.keyed_box import (
    ACCEPTED_KEPT_S,
    LIST_LAG_S,
    OPENING_FILE,
    REFUSED_KEPT_S,
    KeyedBox,
    NoKey,
    NotesFile,
)
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.outbox import RETRY_S
from rozliczenia.centrum.report_box import Archive, Asset, Commented, Refused, Rejected, Sent, Unreachable

from atrapy.skrzynka import BoxIssue
from tests.fixtures.centrum import FakeReportBox
from tests.fixtures.clock import ManualClock

KEY = "github_pat_SYNTETYCZNY_KLUCZ"
NEW_KEY = "github_pat_SYNTETYCZNY_NOWY_KLUCZ"
WAIT_S = 30.0


@dataclass
class Skrzynka:
    """Skrzynka z kluczem taty: fałszywa skrzynka, plik klucza (``key``, ``None``: brak) i zegar Centrum."""

    box: FakeReportBox = field(default_factory=FakeReportBox)
    key: str | None = KEY
    clock: ManualClock = field(default_factory=ManualClock)

    def __post_init__(self) -> None:
        self.keyed = KeyedBox(self.box, lambda: self.key, clock=self.clock)

    def requests(self) -> int:
        """Zapytania z kluczem, które doszły do skrzynki: listy, nowe issue i komentarze."""

        return len(self.box.listed) + len(self.box.keys)


def accepted(skrzynka: Skrzynka) -> None:
    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "accepted"


def refused(skrzynka: Skrzynka) -> None:
    skrzynka.box.search_failure = Refused()
    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "refused"
    skrzynka.box.search_failure = None


def test_bez_pliku_klucza_klucza_brak_a_skrzynki_nikt_nie_pyta() -> None:
    skrzynka = Skrzynka(key=None)

    answers = (
        skrzynka.keyed.open_issue("zgloszenie", "tytuł", "treść"),
        skrzynka.keyed.comment(1, "treść"),
        skrzynka.keyed.comments(1),
        skrzynka.keyed.edit_comment(1, "treść"),
        skrzynka.keyed.labelled_issues("zgloszenie", include_closed=True),
        skrzynka.keyed.find_issue("zgloszenie", "- Odcisk problemu: 0", include_closed=False),
    )

    assert answers == (NoKey(),) * 6
    assert (skrzynka.keyed.judge(wait_s=WAIT_S), skrzynka.requests()) == ("missing", 0)


REFUSALS: dict[str, Callable[[Skrzynka], object]] = {
    "lista": lambda s: s.keyed.labelled_issues("uwaga-taty", include_closed=True),
    "nowe-issue": lambda s: s.keyed.open_issue("uwaga-taty", "tytuł", "treść"),
}


@pytest.mark.parametrize("ask", REFUSALS.values(), ids=REFUSALS.keys())
def test_odmowa_listy_albo_zalozenia_issue_to_klucz_odrzucony(ask: Callable[[Skrzynka], object]) -> None:
    skrzynka = Skrzynka(FakeReportBox(search_failure=Refused(), outcomes=[Refused()]))

    assert ask(skrzynka) == Refused()

    assert skrzynka.keyed.judge(wait_s=0) == "refused"
    assert skrzynka.requests() == 1


ANSWERS: dict[str, tuple[Callable[[], FakeReportBox], Callable[[Skrzynka], object], object]] = {
    "lista": (FakeReportBox, lambda s: s.keyed.labelled_issues("uwaga-taty", include_closed=False), ()),
    "nowe-issue": (FakeReportBox, lambda s: s.keyed.open_issue("uwaga-taty", "tytuł", "treść"), Sent(1)),
    "odmowa-tresci-issue": (
        lambda: FakeReportBox(outcomes=[Rejected()]),
        lambda s: s.keyed.open_issue("uwaga-taty", "tytuł", "treść"),
        Rejected(),
    ),
    "komentarz": (
        lambda: FakeReportBox(issues=[BoxIssue(7, "uwaga-taty", "tytuł", "treść")]),
        lambda s: s.keyed.comment(7, "treść"),
        Commented(1, "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/7#issuecomment-1"),
    ),
    "odmowa-tresci-komentarza": (
        lambda: FakeReportBox(comment_outcomes=[Rejected()]),
        lambda s: s.keyed.comment(7, "treść"),
        Rejected(),
    ),
}


@pytest.mark.parametrize(("box", "ask", "answer"), ANSWERS.values(), ids=ANSWERS.keys())
def test_kazda_odpowiedz_skrzynki_takze_odmowa_tresci_to_klucz_przyjety(
    box: Callable[[], FakeReportBox], ask: Callable[[Skrzynka], object], answer: object
) -> None:
    skrzynka = Skrzynka(box())

    assert ask(skrzynka) == answer

    assert skrzynka.keyed.judge(wait_s=0) == "accepted"
    assert skrzynka.requests() == 1


def test_brak_sieci_nie_zmienia_werdyktu_o_kluczu() -> None:
    skrzynka = Skrzynka(FakeReportBox(search_failure=Unreachable()))
    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "unchecked"
    skrzynka.box.search_failure = None
    skrzynka.clock.advance(NO_ANSWER_KEPT_S)
    accepted(skrzynka)

    skrzynka.box.search_failure = Unreachable()
    skrzynka.clock.advance(ACCEPTED_KEPT_S)

    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "accepted"
    assert len(skrzynka.box.listed) == 3


ABOUT_DELETED: dict[str, Callable[[Skrzynka], object]] = {
    "komentarz": lambda s: s.keyed.comment(99, "do issue, które Maks usunął"),
    "komentarze": lambda s: s.keyed.comments(99),
    "poprawka-komentarza": lambda s: s.keyed.edit_comment(99_001, "w issue, które Maks usunął"),
}


@pytest.mark.parametrize("ask", ABOUT_DELETED.values(), ids=ABOUT_DELETED.keys())
def test_odmowa_o_issue_ktore_maks_usunal_nie_odrzuca_klucza(ask: Callable[[Skrzynka], object]) -> None:
    skrzynka = Skrzynka()
    accepted(skrzynka)

    assert ask(skrzynka) == Refused()

    assert skrzynka.keyed.judge(wait_s=0) == "accepted"


def test_nowy_klucz_wpisany_przez_maksa_jest_sprawdzany_od_razu() -> None:
    skrzynka = Skrzynka()
    refused(skrzynka)

    skrzynka.key = NEW_KEY

    assert skrzynka.keyed.open_issue("uwaga-taty", "tytuł", "treść") == Sent(1)
    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "accepted"
    assert skrzynka.box.keys == [NEW_KEY]


def test_nowy_klucz_bez_odpowiedzi_skrzynki_nie_dziedziczy_odmowy_ani_przerwy_po_braku_odpowiedzi() -> None:
    skrzynka = Skrzynka()
    refused(skrzynka)
    skrzynka.box.search_failure = Unreachable()

    skrzynka.key = NEW_KEY
    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "unchecked"
    skrzynka.key = KEY + "_TRZECI"
    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "unchecked"

    assert len(skrzynka.box.listed) == 3


def test_odrzucony_klucz_przez_kwadrans_nie_idzie_do_skrzynki_a_potem_raz() -> None:
    skrzynka = Skrzynka()
    refused(skrzynka)

    skrzynka.clock.advance(REFUSED_KEPT_S - 1)
    answers = (
        skrzynka.keyed.open_issue("uwaga-taty", "tytuł", "treść"),
        skrzynka.keyed.comment(1, "treść"),
        skrzynka.keyed.labelled_issues("uwaga-taty", include_closed=True),
        skrzynka.keyed.judge(wait_s=WAIT_S),
    )
    assert answers == (Refused(), Refused(), Refused(), "refused")
    assert skrzynka.requests() == 1

    skrzynka.clock.advance(1)

    assert skrzynka.keyed.open_issue("uwaga-taty", "tytuł", "treść") == Sent(1)
    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "accepted"
    assert skrzynka.requests() == 2


def test_przyjety_klucz_nie_jest_sprawdzany_drugi_raz_przez_10_minut() -> None:
    skrzynka = Skrzynka()
    accepted(skrzynka)

    skrzynka.clock.advance(ACCEPTED_KEPT_S - 1)
    accepted(skrzynka)
    assert len(skrzynka.box.listed) == 1

    skrzynka.clock.advance(1)
    accepted(skrzynka)
    assert skrzynka.box.listed == [("zgloszenie", False), ("zgloszenie", False)]


def test_po_braku_odpowiedzi_sprawdzenie_klucza_wraca_po_minucie() -> None:
    skrzynka = Skrzynka(FakeReportBox(search_failure=Unreachable()))
    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "unchecked"
    skrzynka.box.search_failure = None

    skrzynka.clock.advance(NO_ANSWER_KEPT_S - 1)
    assert skrzynka.keyed.judge(wait_s=WAIT_S) == "unchecked"
    assert len(skrzynka.box.listed) == 1

    skrzynka.clock.advance(1)
    accepted(skrzynka)
    assert len(skrzynka.box.listed) == 2


def test_bez_odpowiedzi_na_ponowne_sprawdzenie_przyjetego_klucza_nastepne_dopiero_po_minucie() -> None:
    skrzynka = Skrzynka()
    accepted(skrzynka)
    skrzynka.box.search_failure = Unreachable()
    skrzynka.clock.advance(ACCEPTED_KEPT_S)
    accepted(skrzynka)

    skrzynka.clock.advance(NO_ANSWER_KEPT_S - 1)
    accepted(skrzynka)

    assert len(skrzynka.box.listed) == 2


def test_spozniona_zgoda_sprzed_odmowy_nie_cofa_odmowy() -> None:
    hold = threading.Event()
    skrzynka = Skrzynka(FakeReportBox(search_hold=hold, outcomes=[Refused()]))
    late = threading.Thread(target=skrzynka.keyed.labelled_issues, args=("uwaga-taty",), kwargs={"include_closed": True})
    late.start()
    assert skrzynka.box.searching.wait(WAIT_S), "pytanie o listę nie doszło do skrzynki"

    skrzynka.clock.advance(1)
    assert skrzynka.keyed.open_issue("uwaga-taty", "tytuł", "treść") == Refused()
    hold.set()
    late.join(WAIT_S)

    assert skrzynka.keyed.judge(wait_s=0) == "refused"


def test_jedno_sprawdzenie_klucza_naraz_a_odczyt_czeka_najwyzej_podany_czas() -> None:
    hold = threading.Event()
    skrzynka = Skrzynka(FakeReportBox(search_hold=hold))

    assert skrzynka.keyed.judge(wait_s=0.01) == "unchecked"
    assert skrzynka.keyed.judge(wait_s=0.01) == "unchecked"
    hold.set()

    accepted(skrzynka)
    assert len(skrzynka.box.listed) == 1


def _numbers(listed: object) -> list[int]:
    """Numery issue z listy ``KeyedBox``; inna odpowiedź (odmowa, brak sieci, brak klucza) psuje test."""

    assert isinstance(listed, tuple), listed
    return [issue.number for issue in listed]


def _notes(pending: dict[str, list[object]]) -> str:
    """Plik zapisów ``KeyedBox`` z zapisami bez odpowiedzi ``pending`` i bez skutków."""

    return json.dumps({"zapisy": pending, "issue": [], "archiwa": [], "pliki": [], "usuniete": []})


# Plik zapisów, który nie wstrzymuje: chwila sprzed restartu komputera (zegar Centrum liczy od jego startu, więc jest
# większa od dzisiejszych) i treść w innej postaci (następny zapis ją nadpisze).
OPENINGS_FREE = {
    "chwila-z-przyszlosci": _notes({"uwaga-taty": [1_000_000.0, "inny-zapis"]}),
    "nie-json": "uwaga-taty 3.0",
    "nie-slownik": "[3.0]",
    "stara-postac": json.dumps({"uwaga-taty": [3.0, "inny-zapis"]}),
    "nie-para": _notes({"uwaga-taty": [3.0]}),
    "nie-liczba": _notes({"uwaga-taty": ["trzy", "inny-zapis"]}),
}


@pytest.mark.parametrize("text", OPENINGS_FREE.values(), ids=OPENINGS_FREE.keys())
def test_plik_zapisow_bez_swiezego_zapisu_nie_wstrzymuje_zakladania_a_odpowiedz_zostawia_w_nim_skutek(
    tmp_path: Path, text: str
) -> None:
    opening = tmp_path / OPENING_FILE
    opening.write_text(text, encoding="utf-8")
    keyed = KeyedBox(FakeReportBox(), lambda: KEY, clock=ManualClock(seconds=5.0), opening=NotesFile(opening, replace_atomically))

    assert keyed.open_issue("uwaga-taty", "tytuł", "treść") == Sent(1)
    notes = json.loads(opening.read_text(encoding="utf-8"))
    assert (notes["zapisy"], notes["issue"]) == ({}, [[5.0, "uwaga-taty", 1, "treść"]])


def test_issue_ktore_maks_zamknal_zaraz_po_zalozeniu_nie_wraca_na_liste_otwartych() -> None:
    """Lista otwartych nie ma ani issue, za którym nie nadążyła, ani zamkniętego; dołącza tylko to pierwsze (#879)."""

    box = FakeReportBox(list_lag=True)
    clock = ManualClock(seconds=100.0)
    keyed = KeyedBox(box, lambda: KEY, clock=clock)
    assert keyed.open_issue("zgloszenie", "tytuł", "- Odcisk problemu: abc") == Sent(1)
    assert _numbers(keyed.labelled_issues("zgloszenie", include_closed=False)) == [1]

    box.list_caught_up()
    box.close(1)
    clock.pause(10.0)

    assert keyed.labelled_issues("zgloszenie", include_closed=False) == ()
    assert keyed.find_issue("zgloszenie", "- Odcisk problemu: abc", include_closed=False) is None
    every = keyed.labelled_issues("zgloszenie", include_closed=True)
    assert isinstance(every, tuple)
    assert [(issue.number, issue.closure is not None) for issue in every] == [(1, True)]


def test_nowe_centrum_zaraz_po_zapisie_starego_zna_jego_issue_i_nie_czeka(tmp_path: Path) -> None:
    """Ponowny start Centrum po wysyłce: skutek z odpowiedzią jest w pliku, więc nic nie wstrzymuje (#879)."""

    box = FakeReportBox(list_lag=True)
    clock = ManualClock(seconds=100.0)
    opening = tmp_path / OPENING_FILE
    old = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(opening, replace_atomically))
    assert old.open_issue("zgloszenie", "pierwsze", "- Odcisk problemu: abc") == Sent(1)

    clock.pause(2.0)
    new = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(opening, replace_atomically))
    assert _numbers(new.labelled_issues("zgloszenie", include_closed=False)) == [1]
    assert new.open_issue("zgloszenie", "drugie", "- Odcisk problemu: def") == Sent(2)


def test_nowe_centrum_po_zakladaniu_bez_odpowiedzi_czeka_na_liste_po_lag(tmp_path: Path) -> None:
    box = FakeReportBox(list_lag=True, lost_answers=1)
    clock = ManualClock(seconds=100.0)
    opening = tmp_path / OPENING_FILE
    old = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(opening, replace_atomically))
    assert old.open_issue("zgloszenie", "pierwsze", "- Odcisk problemu: abc") == Unreachable()

    new = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(opening, replace_atomically))
    assert new.labelled_issues("zgloszenie", include_closed=False) == ()
    assert new.open_issue("zgloszenie", "pierwsze", "- Odcisk problemu: abc") == Unreachable()
    assert len(box.issues) == 1

    clock.pause(LIST_LAG_S)
    box.list_caught_up()
    assert _numbers(new.labelled_issues("zgloszenie", include_closed=False)) == [1]


def test_zakladanie_wstrzymane_po_zakladaniu_bez_odpowiedzi_mija_przed_budzeniem_kolejki(tmp_path: Path) -> None:
    """Kolejka po porażce próbuje znowu po ``RETRY_S``: lista z tego budzenia zdejmuje wstrzymanie, więc ponowienie nie
    czeka na następne budzenie."""

    box = FakeReportBox(list_lag=True, lost_answers=1)
    clock = ManualClock(seconds=100.0)
    keyed = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(tmp_path / OPENING_FILE, replace_atomically))
    assert keyed.open_issue("zgloszenie", "pierwsze", "- Odcisk problemu: abc") == Unreachable()

    clock.pause(RETRY_S)
    box.list_caught_up()
    assert _numbers(keyed.labelled_issues("zgloszenie", include_closed=False)) == [1]
    assert keyed.open_issue("zgloszenie", "drugie", "- Odcisk problemu: def") == Sent(2)


def test_lista_innego_watku_nie_zdejmuje_wstrzymania_zakladania(tmp_path: Path) -> None:
    """Liczy się lista, na której kolejka opiera zapis, nie późniejsza lista podglądu w innym wątku."""

    box = FakeReportBox()
    clock = ManualClock(seconds=100.0)
    opening = tmp_path / OPENING_FILE
    opening.write_text(_notes({"zgloszenie": [100.0, "zapis-innego-centrum"]}), encoding="utf-8")
    keyed = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(opening, replace_atomically))
    clock.pause(1.0)
    keyed.labelled_issues("zgloszenie", include_closed=False)

    clock.pause(LIST_LAG_S)
    other = threading.Thread(target=lambda: keyed.labelled_issues("zgloszenie", include_closed=False))
    other.start()
    other.join()

    assert keyed.open_issue("zgloszenie", "tytuł", "treść") == Unreachable()
    assert box.issues == []


def test_plik_zapisow_po_wielu_uruchomieniach_ma_tylko_swieze_wpisy(tmp_path: Path) -> None:
    box = FakeReportBox()
    clock = ManualClock(seconds=1000.0)
    opening = tmp_path / OPENING_FILE
    opening.write_text(_notes({"plik zgubiony.log.gz": [1000.0, "wyslanie-bez-odpowiedzi"]}), encoding="utf-8")
    keyed = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(opening, replace_atomically))
    archive = keyed.open_archive("logi-2026-10", "tytuł", "opis")
    assert isinstance(archive, Archive)
    for run in range(5):
        clock.pause(60 * 60)
        keyed.archive("logi-2026-10")
        assert isinstance(keyed.upload(archive.id, f"uruchomienie-{run}.log.gz", "etykieta", b"x"), Asset)

    notes = json.loads(opening.read_text(encoding="utf-8"))
    assert (notes["zapisy"], notes["archiwa"], [entry[3] for entry in notes["pliki"]]) == ({}, [], ["uruchomienie-4.log.gz"])


def test_nieczytelny_plik_chwil_zakladania_wstrzymuje_zakladanie_bez_zapytania(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pliku, którego nie da się odczytać, nie da się wykluczyć: inne Centrum mogło właśnie założyć issue (#879)."""

    opening = tmp_path / OPENING_FILE
    read_text = Path.read_text

    def locked(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == opening:  # odczyt odmawia jak przy pliku, który trzyma antywirus; zapis by przeszedł
            raise PermissionError(13, "Odmowa dostępu", str(path))
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", locked)
    box = FakeReportBox()
    keyed = KeyedBox(box, lambda: KEY, clock=ManualClock(), opening=NotesFile(opening, replace_atomically))

    assert keyed.open_issue("uwaga-taty", "tytuł", "treść") == Unreachable()
    assert box.keys == []


def unreadable(monkeypatch: pytest.MonkeyPatch, opening: Path, times: int | None) -> None:
    """``read_text`` pliku zapisów rzuca ``PermissionError`` ``times`` razy od teraz (``None``: zawsze), jak plik, który
    trzyma antywirus bez współdzielenia odczytu; zapis by przeszedł."""

    read_text = Path.read_text
    failures = itertools.count(1)

    def locked(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == opening and (times is None or next(failures) <= times):
            raise PermissionError(13, "Odmowa dostępu", str(path))
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", locked)


REPORT_LINE = "- Odcisk problemu: abc"


def test_chwilowo_nieczytelny_plik_zapisow_przy_liscie_nie_daje_drugiego_issue_tej_samej_wysylki(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sonda rundy 2 #897 (#909): lista issue nie nadążyła za issue pierwszej wysyłki, a odczyt pliku zapisów w liście
    drugiej pada raz. Kolejka zakłada issue tylko wtedy, gdy lista go nie ma, a takie zakładanie nie daje drugiego."""

    box = FakeReportBox(list_lag=True)
    clock = ManualClock(seconds=100.0)
    opening = tmp_path / OPENING_FILE
    keyed = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(opening, replace_atomically))
    assert keyed.find_issue("zgloszenie", REPORT_LINE, include_closed=False) is None
    assert keyed.open_issue("zgloszenie", "tytuł", REPORT_LINE) == Sent(1)

    clock.pause(2.0)
    unreadable(monkeypatch, opening, times=1)
    if keyed.find_issue("zgloszenie", REPORT_LINE, include_closed=False) is None:
        keyed.open_issue("zgloszenie", "tytuł", REPORT_LINE)

    assert [issue.number for issue in box.issues] == [1]
    assert keyed.find_issue("zgloszenie", REPORT_LINE, include_closed=False) == 1


def test_chwilowo_nieczytelny_plik_zapisow_przy_liscie_archiwow_nie_zaklada_drugiego_archiwum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Jak przy issue (#909): lista Release'ów nie nadążyła za Archiwum, a odczyt pliku zapisów w ``archive`` pada raz;
    zakładanie po niej nie dostaje odmowy drugiego Archiwum tego tagu (422)."""

    box = FakeReportBox(list_lag=True)
    clock = ManualClock(seconds=100.0)
    opening = tmp_path / OPENING_FILE
    keyed = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(opening, replace_atomically))
    assert keyed.archive("logi-2026-10") is None
    assert isinstance(keyed.open_archive("logi-2026-10", "tytuł", "opis"), Archive)

    clock.pause(2.0)
    unreadable(monkeypatch, opening, times=1)
    found = keyed.archive("logi-2026-10")
    second = keyed.open_archive("logi-2026-10", "tytuł", "opis") if found is None else found

    assert (len(box.archives), isinstance(second, Rejected)) == (1, False)
    again = keyed.archive("logi-2026-10")
    assert isinstance(again, Archive) and again.id == 1


def test_lista_archiwum_bez_odczytu_pliku_zapisow_wstrzymuje_wyslanie_i_usuniecie_pliku_archiwum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Jak zakładanie Archiwum (#909): lista plików Archiwum, przy której odczyt pliku zapisów padł, mogła nie pokazać
    pliku, który już poszedł, więc wysłanie i usunięcie pliku Archiwum czekają bez zapytania do listy z odczytem."""

    box = FakeReportBox()
    clock = ManualClock(seconds=100.0)
    opening = tmp_path / OPENING_FILE
    keyed = KeyedBox(box, lambda: KEY, clock=clock, opening=NotesFile(opening, replace_atomically))
    archive = keyed.open_archive("logi-2026-10", "tytuł", "opis")
    assert isinstance(archive, Archive)
    sent = keyed.upload(archive.id, "pierwsze.log.gz", "etykieta", b"x")
    assert isinstance(sent, Asset)

    clock.pause(2.0)
    unreadable(monkeypatch, opening, times=1)
    assert isinstance(keyed.archive("logi-2026-10"), Archive)
    asked = len(box.keys)

    assert keyed.upload(archive.id, "drugie.log.gz", "etykieta", b"y") == Unreachable()
    assert keyed.remove(sent.id) == Unreachable()
    assert len(box.keys) == asked
    assert isinstance(keyed.archive("logi-2026-10"), Archive)
    assert isinstance(keyed.upload(archive.id, "drugie.log.gz", "etykieta", b"y"), Asset)


def test_plik_zapisow_ktory_nie_jest_utf8_nie_wstrzymuje_zakladania_a_zapis_go_zastepuje(tmp_path: Path) -> None:
    """Treść pliku zapisów, która nie jest UTF-8, to treść w innej postaci, nie plik nieczytelny na stałe (#909)."""

    opening = tmp_path / OPENING_FILE
    opening.write_bytes(b"\xff\xfe zapisy")
    box = FakeReportBox()
    keyed = KeyedBox(box, lambda: KEY, clock=ManualClock(seconds=5.0), opening=NotesFile(opening, replace_atomically))

    assert keyed.open_issue("uwaga-taty", "tytuł", "treść") == Sent(1)
    assert json.loads(opening.read_text(encoding="utf-8"))["issue"] == [[5.0, "uwaga-taty", 1, "treść"]]


def test_pierwszy_blad_pliku_zapisow_w_pracy_centrum_trafia_raz_do_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opening = tmp_path / OPENING_FILE
    failures: list[OSError] = []
    unreadable(monkeypatch, opening, times=None)
    keyed = KeyedBox(
        FakeReportBox(), lambda: KEY, clock=ManualClock(), opening=NotesFile(opening, replace_atomically, failures.append)
    )

    for _ in range(3):
        assert keyed.open_issue("uwaga-taty", "tytuł", "treść") == Unreachable()
        assert keyed.labelled_issues("uwaga-taty", include_closed=False) == ()

    assert [type(failure) for failure in failures] == [PermissionError]


def test_zapis_pliku_zapisow_ktory_sie_nie_udaje_wstrzymuje_zakladanie_i_trafia_do_unavailable(tmp_path: Path) -> None:
    failures: list[OSError] = []

    def refused(path: Path, text: str) -> None:
        raise PermissionError(13, "Odmowa dostępu", str(path))

    box = FakeReportBox()
    keyed = KeyedBox(box, lambda: KEY, clock=ManualClock(), opening=NotesFile(tmp_path / OPENING_FILE, refused, failures.append))

    assert keyed.open_issue("uwaga-taty", "tytuł", "treść") == Unreachable()
    assert (box.keys, [type(failure) for failure in failures]) == ([], [PermissionError])
