"""Rdzeń raportów (``worker_reports.enter_reports``): Wpis raportu w dokładnym formacie trafia do pustych komórek
zlecenia Wykonawcy z dnia z tematu (#1227, ADR 0028, pojęcia Raport wykonawcy, Wpis raportu i Wpisanie raportów w
``GLOSSARY.md``).

Testy idą przez jedyną operację rdzenia, jak testy Reguł ilości: maile, adresy i zlecenia na wejściu, zmiany komórek,
problemy i liczby na wyjściu. Dane są syntetyczne, adresy w domenie ``.invalid``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import itertools
from pathlib import Path
from typing import get_args

from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

from rozliczenia.report_cells import CellChange, OrderRow, ReportColumn
from rozliczenia.settlement_period import period_of
from rozliczenia.worker_reports import (
    ForeignOrder,
    Login,
    MailId,
    ManualDifference,
    MissingVerdict,
    OrderKey,
    OrderNumber,
    OtherDay,
    OwnEntries,
    OwnEntry,
    ReadReport,
    ReadStranger,
    RegisterOrder,
    RepeatedOrder,
    ReportEntry,
    ReportInputs,
    ReportMail,
    ReportProblem,
    ReportsOutcome,
    SenderAddress,
    SubjectFault,
    UnknownNumber,
    UnknownSender,
    UnreadableSubject,
    Verdict,
    VerdictFault,
    Window,
    WorkerAddresses,
    WorkerDay,
    as_mail,
    enter_reports,
)
from rozliczenia.worker_reports.reasons import reason
from tests.fixtures.expect import assert_expected

DAY = date(2026, 11, 8)
JAN = "jan@przyklad.invalid"
EWA = "ewa@przyklad.invalid"
ADDRESSES = {"jan.testowy": [JAN], "ewa.probna": [EWA]}
TAPA = timezone(timedelta(hours=1))
EVENING = datetime(2026, 11, 8, 18, 5, tzinfo=TAPA)
ROW = OrderRow("Zlecenia", 120)
NUMBER = 40000001.0
SUBJECT = "Raport 08.11.2026"
TEXT = "40000001 tak wymiana routera"


def _mail(
    sender: str, subject: str, text: str, arrived: datetime = EVENING, message_id: str | None = None
) -> ReportMail:
    address = SenderAddress.of(sender)
    assert address is not None
    mail = MailId.of(message_id or f"<{subject}|{text}|{arrived.isoformat()}@{sender}>")
    return ReportMail(mail, address, subject, text, arrived)


def _order(
    row: OrderRow = ROW,
    *,
    number: object = NUMBER,
    day: date = DAY,
    worker: object = "Jan.Testowy",
    successful: object = None,
    completed: object = None,
) -> RegisterOrder:
    order = RegisterOrder.of(
        row,
        number=number,
        started=datetime(day.year, day.month, day.day, 9, 30),
        worker=worker,
        successful=successful,
        completed=completed,
    )
    assert order is not None
    return order


def _inputs(
    mails: Sequence[ReportMail],
    orders: Sequence[RegisterOrder],
    *,
    today: date = DAY,
    rollout: date | None = None,
    closed: Sequence[str] = (),
    memory: OwnEntries = OwnEntries.EMPTY,
) -> ReportInputs:
    logins = {}
    for login, senders in ADDRESSES.items():
        for sender in senders:
            address = SenderAddress.of(sender)
            assert address is not None
            logins[address] = Login(login)
    return ReportInputs(
        mails=mails,
        addresses=WorkerAddresses(logins),
        orders=orders,
        window=Window.of(today, rollout, closed),
        memory=memory,
        kept=frozenset(),
    )


def _key(number: str = "40000001", day: date = DAY, worker: str = "jan.testowy") -> OrderKey:
    return OrderKey(OrderNumber(number), day, Login(worker))


@pytest.mark.parametrize("number", [40000001.0, 40000001, "40000001", " #40000001 "])
@pytest.mark.parametrize("worker", ["Jan.Testowy", "JAN.TESTOWY", " jan.testowy "])
def test_wpis_raportu_trafia_do_pustych_komorek_zlecenia_wykonawcy_z_dnia_z_tematu(number: object, worker: str) -> None:
    """Numer zlecenia przychodzi z szybkiego czytnika INTERMAX jako liczba, a Wykonawca w dowolnej wielkości liter."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], [_order(number=number, worker=worker)]))

    assert outcome.changes == (
        CellChange(ROW, ReportColumn.SUCCESSFUL, "tak"),
        CellChange(ROW, ReportColumn.COMPLETED, "wymiana routera"),
    )
    assert outcome.problems == ()
    assert outcome.memory == OwnEntries(
        frozenset(
            {
                OwnEntry(_key(), ReportColumn.SUCCESSFUL, "tak"),
                OwnEntry(_key(), ReportColumn.COMPLETED, "wymiana routera"),
            }
        )
    )


def test_raport_z_adresu_spoza_listy_nie_zmienia_komorek_i_jest_problemem_nieznanego_nadawcy() -> None:
    mail = _mail("obcy@przyklad.invalid", SUBJECT, TEXT)

    outcome = enter_reports(_inputs([mail], [_order()]))

    assert outcome.changes == ()
    assert outcome.problems == (UnknownSender(mail.id, mail.sender, DAY),)
    assert outcome.mails == (ReadStranger(mail.id, EVENING, DAY),)


@pytest.mark.parametrize("subject", ["Re: Raport 08.11.2026", "Fwd: Raport 08.11.2026", "Zlecenia na jutro 08.11.2026"])
def test_mail_z_innym_tematem_niz_raport_z_data_nie_daje_niczego(subject: str) -> None:
    outcome = enter_reports(_inputs([_mail(JAN, subject, TEXT)], [_order()]))

    assert (outcome.changes, outcome.problems, outcome.mails) == ((), (), ())


def test_komorka_rowna_wpisowi_nie_daje_zmiany_a_drugie_klikniecie_niczego_nie_zmienia() -> None:
    """Ręczne ``tak`` równe Wpisowi nie trafia do pamięci, bo późniejsza poprawka nadpisałaby wtedy tatę."""

    mails = [_mail(JAN, SUBJECT, TEXT)]

    first = enter_reports(_inputs(mails, [_order(successful="tak")]))
    second = enter_reports(_inputs(mails, [_order(successful="tak", completed="wymiana routera")], memory=first.memory))

    assert first.changes == (CellChange(ROW, ReportColumn.COMPLETED, "wymiana routera"),)
    assert first.memory == OwnEntries(frozenset({OwnEntry(_key(), ReportColumn.COMPLETED, "wymiana routera")}))
    assert second.changes == ()
    assert second.memory == first.memory


def test_reczna_wartosc_w_komorce_zostaje_a_pusta_komorka_obok_dostaje_wpis() -> None:
    order = _order(completed="wymiana modemu, klient prosi o telefon")

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], [order]))

    assert outcome.changes == (CellChange(ROW, ReportColumn.SUCCESSFUL, "tak"),)


def test_wpis_bez_opisu_wpisuje_tylko_skuteczne() -> None:
    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "40000001 nie")], [_order()]))

    assert outcome.changes == (CellChange(ROW, ReportColumn.SUCCESSFUL, "nie"),)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Dzień dobry, raport wyślę jutro.", id="bez-numeru"),
        pytest.param("40000001 nieobecny", id="slowo-od-nie-to-nie-werdykt"),
        pytest.param("40000001 tak wymiana routera\nPozdrawiam", id="druga-linia"),
    ],
)
def test_tresc_bez_wpisu_raportu_nie_zmienia_komorek(text: str) -> None:
    """Wpis w dokładnym formacie #1227 to cała treść w jednej linii, a ``tak``/``nie`` to całe słowo."""

    mail = _mail(JAN, SUBJECT, text)

    outcome = enter_reports(_inputs([mail], [_order()]))

    assert outcome.changes == ()
    assert outcome.mails == (ReadReport(mail.id, EVENING, Login("jan.testowy"), DAY, ()),)


def test_numer_spoza_zlecen_wykonawcy_z_dnia_jest_problemem_bez_zmian() -> None:
    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "12345678 tak wymiana routera")], [_order()]))

    assert outcome.changes == ()
    assert outcome.problems == (UnknownNumber(Login("jan.testowy"), DAY, OrderNumber("12345678")),)


@pytest.mark.parametrize(
    ("sender", "subject", "rollout", "problem"),
    [
        pytest.param(
            EWA,
            SUBJECT,
            None,
            UnknownNumber(Login("ewa.probna"), DAY, OrderNumber("40000001")),
            id="numer-zlecenia-innego-wykonawcy-z-tego-dnia",
        ),
        pytest.param(
            JAN,
            "Raport 07.11.2026",
            date(2026, 11, 7),
            UnknownNumber(Login("jan.testowy"), date(2026, 11, 7), OrderNumber("40000001")),
            id="numer-zlecenia-wykonawcy-z-innego-dnia",
        ),
    ],
)
def test_wpis_trafia_tylko_do_zlecenia_nadawcy_z_dnia_z_tematu(
    sender: str, subject: str, rollout: date | None, problem: UnknownNumber
) -> None:
    """Zlecenie ``40000001`` jest Jana z 08.11. Do #1229 cudze zlecenie i inny dzień to ``UnknownNumber``."""

    outcome = enter_reports(_inputs([_mail(sender, subject, TEXT)], [_order()], rollout=rollout))

    assert outcome.changes == ()
    assert outcome.problems == (problem,)


def test_ten_sam_numer_dwa_razy_w_dniu_wykonawcy_nie_daje_zmian() -> None:
    orders = [_order(), _order(OrderRow("Zlecenia", 121))]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], orders))

    assert outcome.changes == ()
    assert outcome.problems == (RepeatedOrder(Login("jan.testowy"), DAY, OrderNumber("40000001")),)


@pytest.mark.parametrize("reverse", [False, True])
def test_przy_dwoch_wpisach_zlecenia_wygrywa_pozniejszy_mail_w_kazdej_kolejnosci_maili(reverse: bool) -> None:
    earlier = _mail(JAN, SUBJECT, TEXT, EVENING)
    later = _mail(JAN, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(minutes=30))
    mails = [later, earlier] if reverse else [earlier, later]

    outcome = enter_reports(_inputs(mails, [_order()]))

    assert outcome.changes == (
        CellChange(ROW, ReportColumn.SUCCESSFUL, "nie"),
        CellChange(ROW, ReportColumn.COMPLETED, "klient nieobecny"),
    )
    assert [read.mail for read in outcome.mails] == [earlier.id, later.id]


@pytest.mark.parametrize(
    "senders",
    [
        pytest.param(["a@obcy.invalid", "b@inny.invalid"], id="sonda-recenzenta-dwa-adresy"),
        pytest.param(["d@obcy.invalid", "b@obcy.invalid", "c@inny.invalid", "a@inny.invalid"], id="cztery-adresy"),
    ],
)
def test_obce_maile_z_jednym_message_id_daja_po_problemie_nieznanego_nadawcy_po_adresie(senders: list[str]) -> None:
    """Message-ID ustawia nadawca, więc dwa obce maile mogą go dzielić: każdy daje swój ``UnknownSender``, w kolejności
    adresów dla każdej kolejności maili, a reszta kliknięcia biegnie dalej."""

    mails = [
        _mail(sender, SUBJECT, TEXT, EVENING + timedelta(minutes=index), "<1@obcy.invalid>")
        for index, sender in enumerate(senders)
    ]
    expected = tuple(
        UnknownSender(mail.id, mail.sender, DAY) for mail in sorted(mails, key=lambda mail: mail.sender.shown())
    )

    for order in itertools.permutations([*mails, _mail(JAN, SUBJECT, TEXT)]):
        outcome = enter_reports(_inputs(order, [_order()]))

        assert outcome.problems == expected
        assert [change.column for change in outcome.changes] == [ReportColumn.SUCCESSFUL, ReportColumn.COMPLETED]


@pytest.mark.parametrize("count", [2, 5])
def test_obce_maile_z_jednego_adresu_i_dnia_daja_po_problemie_nieznanego_nadawcy_po_mailu(count: int) -> None:
    mails = [
        _mail("obcy@przyklad.invalid", SUBJECT, f"4000000{index} tak", EVENING + timedelta(minutes=index))
        for index in range(count)
    ]

    outcome = enter_reports(_inputs(mails[::-1], []))

    assert outcome.problems == tuple(
        UnknownSender(mail.id, mail.sender, DAY) for mail in sorted(mails, key=lambda mail: mail.id)
    )


def test_problemy_sa_bez_powtorzen_i_ten_sam_wynik_dla_kazdej_kolejnosci_maili() -> None:
    """Problemy z każdego rodzaju, który rdzeń dziś daje, w tym dwa obce adresy z jednym Message-ID."""

    ewa = _mail(EWA, "Raport 07.11.2026", "40000009 tak montaż", EVENING + timedelta(minutes=1))
    first = _mail("obcy@przyklad.invalid", SUBJECT, TEXT, EVENING + timedelta(minutes=2), "<1@obcy.invalid>")
    second = _mail("inny@przyklad.invalid", SUBJECT, TEXT, EVENING + timedelta(minutes=3), "<1@obcy.invalid>")
    twice = [
        _mail(JAN, SUBJECT, "12345678 tak a", EVENING + timedelta(minutes=4)),
        _mail(JAN, SUBJECT, "12345678 tak b", EVENING + timedelta(minutes=5)),
    ]
    repeated = _mail(JAN, SUBJECT, "40000002 tak", EVENING + timedelta(minutes=6))
    entered = _mail(JAN, SUBJECT, TEXT, EVENING + timedelta(minutes=7))
    mails = [ewa, first, second, *twice, repeated, entered]
    orders = [
        _order(),
        _order(OrderRow("Zlecenia", 121), number="40000002"),
        _order(OrderRow("Zlecenia", 122), number="40000002"),
    ]

    outcomes = [
        enter_reports(_inputs(order, orders, rollout=date(2026, 11, 7))) for order in itertools.permutations(mails)
    ]

    assert all(outcome == outcomes[0] for outcome in outcomes)
    assert outcomes[0].problems == (
        UnknownNumber(Login("ewa.probna"), date(2026, 11, 7), OrderNumber("40000009")),
        UnknownSender(second.id, second.sender, DAY),
        UnknownSender(first.id, first.sender, DAY),
        UnknownNumber(Login("jan.testowy"), DAY, OrderNumber("12345678")),
        RepeatedOrder(Login("jan.testowy"), DAY, OrderNumber("40000002")),
    )


def test_wpis_z_dnia_od_wdrozenia_trafia_do_zlecenia_tego_dnia() -> None:
    earlier = date(2026, 11, 6)

    outcome = enter_reports(
        _inputs([_mail(JAN, "Raport 06.11.2026", TEXT)], [_order(day=earlier)], rollout=date(2026, 11, 5))
    )

    assert [change.column for change in outcome.changes] == [ReportColumn.SUCCESSFUL, ReportColumn.COMPLETED]


@pytest.mark.parametrize(
    ("day", "rollout", "closed"),
    [
        pytest.param(date(2026, 11, 7), None, (), id="przed-pierwszym-kliknieciem-tylko-dzis"),
        pytest.param(date(2026, 11, 6), date(2026, 11, 7), (), id="przed-dniem-wdrozenia"),
        pytest.param(date(2026, 11, 9), None, (), id="po-dzisiejszym-dniu"),
        pytest.param(date(2026, 11, 6), date(2026, 11, 1), (period_of(date(2026, 11, 6)).token,), id="okres-zamkniety"),
    ],
)
def test_raport_z_dnia_spoza_dni_otwartych_jest_pomijany_po_cichu(
    day: date, rollout: date | None, closed: tuple[str, ...]
) -> None:
    mail = _mail(JAN, f"Raport {day:%d.%m.%Y}", TEXT)

    outcome = enter_reports(_inputs([mail], [_order(day=day)], rollout=rollout, closed=closed))

    assert outcome == ReportsOutcome((), (), (), (), OwnEntries.EMPTY)


def test_pamiec_zostawia_dawny_wpis_tylko_gdy_komorka_zlecenia_ma_dalej_wpisana_wartosc() -> None:
    kept = OwnEntry(_key("40000002"), ReportColumn.SUCCESSFUL, "tak")
    changed_by_tata = OwnEntry(_key("40000003"), ReportColumn.SUCCESSFUL, "tak")
    outside = OwnEntry(_key("40000004", date(2026, 11, 1)), ReportColumn.SUCCESSFUL, "tak")
    orders = [
        _order(OrderRow("Zlecenia", 121), number="40000002", successful="tak"),
        _order(OrderRow("Zlecenia", 122), number="40000003", successful="nie"),
    ]

    outcome = enter_reports(_inputs([], orders, memory=OwnEntries(frozenset({kept, changed_by_tata, outside}))))

    assert outcome.memory == OwnEntries(frozenset({kept}))


def test_pamiec_z_dwoma_wpisami_jednej_komorki_zlecenia_jest_odrzucona() -> None:
    entries = {OwnEntry(_key(), ReportColumn.SUCCESSFUL, "tak"), OwnEntry(_key(), ReportColumn.SUCCESSFUL, "nie")}

    with pytest.raises(ValueError, match="dwa wpisy jednej komórki"):
        OwnEntries(frozenset(entries))


def test_liczby_wykonawcy_z_dnia_dla_widoku_raporty() -> None:
    """``entered`` liczy zlecenia z ``tak`` albo ``nie`` w ``SKUTECZNE`` po kliknięciu, także wpisane ręcznie."""

    orders = [
        _order(OrderRow("Zlecenia", 120), number="40000001"),
        _order(OrderRow("Zlecenia", 121), number="40000002", successful=" NIE "),
        _order(OrderRow("Zlecenia", 122), number="40000003"),
        _order(OrderRow("Zlecenia", 123), number="40000004", successful="???"),
        _order(OrderRow("Zlecenia", 124), number="40000010", worker="Ewa.Probna"),
    ]
    mails = [_mail(JAN, SUBJECT, TEXT), _mail(JAN, SUBJECT, "12345678 tak montaż", EVENING + timedelta(hours=1))]

    outcome = enter_reports(_inputs(mails, orders))

    assert outcome.workers == (
        WorkerDay(DAY, Login("ewa.probna"), orders=1, entered=0, mails=0, problems=0, without_report=(OrderNumber("40000010"),)),
        WorkerDay(
            DAY,
            Login("jan.testowy"),
            orders=4,
            entered=2,
            mails=2,
            problems=1,
            without_report=(OrderNumber("40000002"), OrderNumber("40000003"), OrderNumber("40000004")),
        ),
    )


@pytest.mark.parametrize(
    ("number", "started", "worker"),
    [
        pytest.param(None, DAY, "Jan.Testowy", id="bez-numeru"),
        pytest.param("ZL-12", DAY, "Jan.Testowy", id="numer-z-literami"),
        pytest.param(True, DAY, "Jan.Testowy", id="numer-prawda-falsz"),
        pytest.param(40000001.5, DAY, "Jan.Testowy", id="numer-ulamek"),
        pytest.param(NUMBER, None, "Jan.Testowy", id="bez-dnia"),
        pytest.param(NUMBER, "08.11.2026", "Jan.Testowy", id="dzien-tekstem"),
        pytest.param(NUMBER, DAY, "  ", id="bez-wykonawcy"),
    ],
)
def test_wiersz_bez_numeru_dnia_albo_wykonawcy_nie_jest_zleceniem_rdzenia(
    number: object, started: object, worker: object
) -> None:
    assert (
        RegisterOrder.of(ROW, number=number, started=started, worker=worker, successful=None, completed=None) is None
    )


def test_dzien_zlecenia_z_daty_bez_godziny_i_pusta_komorka_z_samych_spacji() -> None:
    order = RegisterOrder.of(ROW, number=NUMBER, started=DAY, worker="Jan.Testowy", successful="  ", completed="x")

    assert order == RegisterOrder(ROW, _key(), None, "x")


# Maile Raportów wykonawców z tym, co rdzeń czyta albo pomija: Wpisy z ``tak``/``nie``, literą, słowem albo bez znaku, z
# numerem zlecenia, spoza zleceń i z „#”, z czynnościami z interpunkcją, maską strażnika, pożegnaniem i numerem w opisie,
# po kilka w mailu i w linii, tematy z dniem i bez dnia, od Wykonawców i spoza listy adresów, z remisem chwil przyjścia.
_NUMBERS = st.sampled_from(["40000001", "40000002", "40000003", "#40000001", "040000001", "12345678"])
_MARKS = st.sampled_from(["tak", "nie", "Tak,", "NIE.", "t", "n", "skuteczne", "", "tak:"])
_WORDS = st.lists(
    st.sampled_from(["wymiana", "routera,", "2", "gniazda", "[telefon]", "40000002", "tak", "-", "pozdrawiam", "Jan"]),
    max_size=4,
)
_LINES = st.builds(lambda number, mark, words: " ".join([number, mark, *words]), _NUMBERS, _MARKS, _WORDS)
_TEXTS = st.lists(st.lists(_LINES, min_size=1, max_size=2).map(" ".join), max_size=3).map("\n".join)
_SUBJECTS = st.sampled_from(
    [SUBJECT, "Raport 07.11.2026", "Raport 8.11.26", "raport 08_11_2026", "Raport", "Raport 08.11", "Raport 31.02.2026"]
)
_SENDERS = st.sampled_from([JAN, EWA, "obcy@przyklad.invalid"])
_MAILS = st.lists(
    st.builds(
        lambda sender, subject, text, minutes, index: _mail(
            sender, subject, text, EVENING + timedelta(minutes=minutes), f"<{index}@przyklad.invalid>"
        ),
        _SENDERS,
        _SUBJECTS,
        _TEXTS,
        st.integers(0, 2),
        st.integers(0, 3),
    ),
    max_size=5,
)
_CANONICAL_ORDERS = (
    _order(number=40000001.0),
    _order(OrderRow("Zlecenia", 121), number=40000002.0, completed="ręcznie"),
    _order(OrderRow("Zlecenia", 122), number="040000001", successful="nie"),
    _order(OrderRow("Zlecenia", 123), number=40000003.0, worker="ewa.probna"),
    _order(OrderRow("Zlecenia", 124), number=40000002.0, day=date(2026, 11, 7)),
)
_CANONICAL_MEMORY = OwnEntries(frozenset({OwnEntry(_key("40000002"), ReportColumn.COMPLETED, "ręcznie")}))


def _canonical_senders(outcome: ReportsOutcome) -> list[SenderAddress]:
    """Adres każdego odczytu: Wykonawcy z listy adresów, a maila spoza listy jeden z tylu adresów spoza niej, ile
    problemów nieznanego nadawcy ma jego mail z dniem, bo tyle różnych nadawców miały maile z tym Message-ID."""

    senders = Counter((problem.mail, problem.day) for problem in outcome.problems if isinstance(problem, UnknownSender))
    seen: Counter[tuple[MailId, date]] = Counter()
    found: list[str] = []
    for read in outcome.mails:
        if isinstance(read, ReadStranger):
            key = (read.mail, read.day)
            found.append(f"obcy-{seen[key] % senders[key]}@odtworzenie.invalid")
            seen[key] += 1
        else:
            found.append(ADDRESSES[read.worker][0])
    addresses = [SenderAddress.of(address) for address in found]
    assert None not in addresses
    return [address for address in addresses if address is not None]


def _seen(problem: ReportProblem) -> object:
    """Problem bez adresu nieznanego nadawcy: postać kanoniczna ma inny adres spoza listy."""

    return (problem.mail, problem.day) if isinstance(problem, UnknownSender) else problem


@settings(derandomize=True, database=None)
@given(_MAILS)
def test_postac_kanoniczna_odczytu_maila_daje_ten_sam_wynik_rdzenia(mails: list[ReportMail]) -> None:
    """Odtworzenie z Logów (#1233) ma z maila tylko odczyt: mail z ``as_mail`` w miejscu każdego przeczytanego maila daje
    ten sam odczyt, te same zmiany komórek, problemy (poza adresem nieznanego nadawcy), liczby i pamięć wpisów."""

    inputs = _inputs(mails, _CANONICAL_ORDERS, today=DAY, rollout=date(2026, 11, 7), memory=_CANONICAL_MEMORY)
    outcome = enter_reports(inputs)
    canonical = list(map(as_mail, outcome.mails, _canonical_senders(outcome)))

    again = enter_reports(replace(inputs, mails=canonical))

    assert (again.mails, again.changes, again.workers, again.memory) == (
        outcome.mails,
        outcome.changes,
        outcome.workers,
        outcome.memory,
    )
    assert sorted(map(repr, map(_seen, again.problems))) == sorted(map(repr, map(_seen, outcome.problems)))


def _every_problem() -> list[ReportProblem]:
    jan, ewa, number = Login("jan.testowy"), Login("ewa.probna"), OrderNumber("40000001")
    mail = MailId.of("<1@przyklad.invalid>")
    sender = SenderAddress.of("obcy@przyklad.invalid")
    assert sender is not None
    return [
        *(UnreadableSubject(mail, jan, EVENING, fault) for fault in SubjectFault),
        UnknownSender(mail, sender, DAY),
        *(MissingVerdict(jan, DAY, number, fault) for fault in VerdictFault),
        UnknownNumber(jan, DAY, OrderNumber("12345678")),
        ForeignOrder(jan, DAY, number, ewa),
        OtherDay(jan, DAY, number, (date(2026, 11, 6), date(2026, 11, 7))),
        RepeatedOrder(jan, DAY, number),
        *(ManualDifference(_key(), column, "ręcznie", "z raportu") for column in ReportColumn),
    ]


def test_powod_dla_taty_kazdego_rodzaju_problemu() -> None:
    problems = _every_problem()
    text = "".join(f"{type(problem).__name__}\n  {reason(problem)}\n" for problem in problems)

    assert {type(problem) for problem in problems} == set(get_args(ReportProblem))
    assert "obcy@przyklad.invalid" not in text
    assert_expected(text, Path(__file__).parent / "expected" / "powody_raportow.txt")


def test_wpis_raportu_ma_numer_tak_albo_nie_i_czynnosci() -> None:
    mail = _mail(JAN, SUBJECT, "  40000001 tak wymiana routera, 2 gniazda  \n")

    outcome = enter_reports(_inputs([mail], [_order()]))

    assert outcome.mails == (
        ReadReport(
            mail.id,
            EVENING,
            Login("jan.testowy"),
            DAY,
            (ReportEntry(OrderNumber("40000001"), Verdict.YES, None, "wymiana routera, 2 gniazda"),),
        ),
    )
    assert outcome.changes[1] == CellChange(ROW, ReportColumn.COMPLETED, "wymiana routera, 2 gniazda")
