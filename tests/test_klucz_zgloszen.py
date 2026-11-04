"""Klucz do Zgłoszeń i werdykt Skrzynki o nim (``KeyedBox``) na fałszywej skrzynce i zegarze testu.

Seam z kilkoma wejściami (kolejka Skrzynki, Powiadomienia, Zgłoszenia, Konfiguracja, Diagnoza), więc macierz
werdyktu jest sprawdzona tu raz; każde wejście ma swój test tłumaczenia przez HTTP.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from rozliczenia.centrum.keyed_box import ACCEPTED_KEPT_S, NO_ANSWER_KEPT_S, REFUSED_KEPT_S, KeyedBox, NoKey
from rozliczenia.centrum.report_box import Commented, Refused, Rejected, Sent, Unreachable

from tests.fixtures.centrum import FakeIssue, FakeReportBox
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
        lambda: FakeReportBox(issues=[FakeIssue(7, "uwaga-taty", "tytuł", "treść")]),
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
