"""Rdzeń raportów (``worker_reports.enter_reports``): Wpis raportu trafia do pustych komórek zlecenia Wykonawcy z dnia
z tematu (#1227), a Raporty wykonawcy i Wpisy rdzeń rozpoznaje tak, jak piszą Wykonawcy (#1228; ADR 0028, pojęcia
Raport wykonawcy, Wpis raportu i Wpisanie raportów w ``GLOSSARY.md``).

Testy idą przez jedyną operację rdzenia, jak testy Reguł ilości: maile, adresy i zlecenia na wejściu, zmiany komórek,
problemy i liczby na wyjściu. Dane są syntetyczne, adresy w domenie ``.invalid``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
import itertools
from pathlib import Path
from string import ascii_lowercase
from typing import get_args

from hypothesis import example, given, settings
from hypothesis import strategies as st
import pytest

from rozliczenia.report_cells import CellChange, OrderAdded, OrderMove, OrderRow, ReportColumn
from rozliczenia.settlement_period import period_of
from rozliczenia.worker_reports import (
    AddBar,
    Added,
    ConflictingVerdicts,
    HandedOver,
    Kept,
    Login,
    MailId,
    ManualDifference,
    MissingVerdict,
    MoveBar,
    MovedFrom,
    MovedTo,
    OrderDetail,
    OrderedDay,
    OrderKey,
    OrderNumber,
    OwnEntries,
    OwnEntry,
    OwnMove,
    ReadNumber,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    RefusedMove,
    RegisterOrder,
    ReminderInputs,
    RepeatedNumber,
    RepeatedOrder,
    ReportEntry,
    ReportInputs,
    ReportMail,
    ReportProblem,
    ReportsOutcome,
    SenderAddress,
    SubjectFault,
    SubjectLost,
    TakenOver,
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
    reminder_text,
    reminders_due,
)
from rozliczenia.worker_reports.reasons import note, reason
from tests.fixtures.expect import assert_expected

DAY = date(2026, 11, 8)
JAN = "jan@przyklad.invalid"
EWA = "ewa@przyklad.invalid"
ADAM = "adam@przyklad.invalid"
ADDRESSES = {"jan.testowy": [JAN], "ewa.probna": [EWA], "adam.inny": [ADAM]}
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
    address: object = "Ulica Testowa 1",
) -> RegisterOrder:
    order = RegisterOrder.of(
        row,
        number=number,
        started=datetime(day.year, day.month, day.day, 9, 30),
        worker=worker,
        successful=successful,
        completed=completed,
        address=address,
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
    kept: frozenset[Kept] = frozenset(),
    ordered: Sequence[date] = (),
    present: Sequence[ReadNumber] | None = None,
) -> ReportInputs:
    """Wejście rdzenia; bez ``present`` proces przeczytał tylko wiersze zleceń ``orders``, każdy raz."""

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
        kept=kept,
        present=tuple(ReadNumber(order.key.number, order.key.day) for order in orders) if present is None else present,
        ordered_days=frozenset(OrderedDay(ROW.sheet, day) for day in ordered),
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
    assert outcome.memory.entries == (
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


@pytest.mark.parametrize(
    "subject",
    [
        "Re: Raport 08.11.2026",
        "RE:Raport 08.11.2026",
        "Fwd: Raport 08.11.2026",
        "FW: raport 08.11.2026",
        " re: Fwd: Raport 08.11.2026",
        "Re: Raport bez daty",
        "ODP: Raport 08.11.2026",
        "Odp: Raport 08.11.2026",
        "odp :Raport 08.11.2026",
        "PD: Raport 08.11.2026",
        "pd: Raport bez daty",
        "Zlecenia na jutro 08.11.2026",
    ],
)
def test_mail_z_innym_tematem_niz_raport_z_data_nie_daje_niczego(subject: str) -> None:
    """Odpowiedź i przekazanie dalej nie są Raportem wykonawcy (US 9), także po polsku z Outlooka (``Odp:``, ``PD:``) i z
    tematem, którego nie da się odczytać."""

    outcome = enter_reports(_inputs([_mail(JAN, subject, TEXT)], [_order()]))

    assert (outcome.changes, outcome.problems, outcome.mails) == ((), (), ())


def test_komorka_rowna_wpisowi_nie_daje_zmiany_a_drugie_klikniecie_niczego_nie_zmienia() -> None:
    """Ręczne ``tak`` równe Wpisowi nie trafia do pamięci, bo późniejsza poprawka nadpisałaby wtedy tatę: poprawka od
    Wykonawcy w trzecim kliknięciu podmienia tylko własny opis, a przy ręcznym ``tak`` daje różnicę."""

    mails = [_mail(JAN, SUBJECT, TEXT)]
    correction = _mail(JAN, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(hours=1))
    entered = _order(successful="tak", completed="wymiana routera")

    first = enter_reports(_inputs(mails, [_order(successful="tak")]))
    second = enter_reports(_inputs(mails, [entered], memory=first.memory))
    third = enter_reports(_inputs([*mails, correction], [entered], memory=second.memory))

    assert first.changes == (CellChange(ROW, ReportColumn.COMPLETED, "wymiana routera"),)
    assert first.memory.entries == (frozenset({OwnEntry(_key(), ReportColumn.COMPLETED, "wymiana routera")}))
    assert (second.changes, second.problems) == ((), ())
    assert second.memory == first.memory
    assert third.changes == (CellChange(ROW, ReportColumn.COMPLETED, "klient nieobecny"),)
    assert third.problems == (ManualDifference(_key(), ReportColumn.SUCCESSFUL, "tak", "nie"),)


def test_reczny_opis_zostaje_z_roznica_dla_taty_a_puste_skuteczne_obok_dostaje_wpis() -> None:
    """US 35: ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` liczą się osobno."""

    order = _order(completed="wymiana modemu, klient prosi o telefon")

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], [order]))

    assert outcome.changes == (CellChange(ROW, ReportColumn.SUCCESSFUL, "tak"),)
    assert outcome.problems == (
        ManualDifference(_key(), ReportColumn.COMPLETED, "wymiana modemu, klient prosi o telefon", "wymiana routera"),
    )
    assert outcome.memory.entries == (frozenset({OwnEntry(_key(), ReportColumn.SUCCESSFUL, "tak")}))


def test_wpis_bez_opisu_wpisuje_tylko_skuteczne() -> None:
    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "40000001 nie")], [_order()]))

    assert outcome.changes == (CellChange(ROW, ReportColumn.SUCCESSFUL, "nie"),)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Dzień dobry, raport wyślę jutro.", id="bez-numeru"),
        pytest.param("Dzień dobry, mam 2 gniazda do wymiany", id="liczba-bez-tak-nie"),
        pytest.param("", id="pusta-tresc"),
    ],
)
def test_tresc_bez_wpisu_raportu_nie_zmienia_komorek(text: str) -> None:
    """Wpis zaczyna numer zlecenia Wykonawcy z dnia albo numer, po którym stoi ``tak``/``nie``; liczba bez nich nie."""

    mail = _mail(JAN, SUBJECT, text)

    outcome = enter_reports(_inputs([mail], [_order()]))

    assert outcome.changes == ()
    assert outcome.mails == (ReadReport(mail.id, EVENING, Login("jan.testowy"), DAY, ()),)


JAN_LOGIN, EWA_LOGIN = Login("jan.testowy"), Login("ewa.probna")


@pytest.mark.parametrize(
    ("sender", "subject", "orders", "problem", "sentence"),
    [
        pytest.param(
            EWA,
            SUBJECT,
            [_order(), _order(OrderRow("Zlecenia", 121))],
            RepeatedNumber(EWA_LOGIN, DAY, OrderNumber("40000001"), ((DAY, JAN_LOGIN), (DAY, JAN_LOGIN))),
            "Zlecenie 40000001 jest w INTERMAX więcej niż raz: u jan.testowy z 08.11.2026, u jan.testowy z "
            "08.11.2026. Centrum nie wie, którego z nich dotyczy Wpis od ewa.probna z 08.11.2026, więc nie zmieniło "
            "żadnego z nich przy tym kliknięciu.",
            id="numer-dwoch-zlecen-innego-wykonawcy-z-tego-dnia-z-kazdym-miejscem",
        ),
        pytest.param(
            JAN,
            "Raport 07.11.2026",
            [_order()],
            RefusedMove(JAN_LOGIN, date(2026, 11, 7), OrderNumber("40000001"), DAY, date(2026, 11, 7), MoveBar.NOT_ORDERED),
            "Wpis zlecenia 40000001 od jan.testowy ma w temacie 07.11.2026, a INTERMAX ma to zlecenie w 08.11.2026. "
            "Centrum go nie przeniosło i nie wpisało, bo dzień 07.11.2026 nie jest jeszcze uporządkowany w INTERMAX.",
            id="numer-zlecenia-wykonawcy-z-innego-dnia-bez-dnia-uporzadkowanego",
        ),
        pytest.param(
            JAN,
            SUBJECT,
            [_order(day=date(2026, 11, 7)), _order(OrderRow("Zlecenia", 121), day=date(2026, 11, 5))],
            RepeatedNumber(
                JAN_LOGIN, DAY, OrderNumber("40000001"), ((date(2026, 11, 5), JAN_LOGIN), (date(2026, 11, 7), JAN_LOGIN))
            ),
            "Zlecenie 40000001 jest w INTERMAX więcej niż raz: u jan.testowy z 05.11.2026, u jan.testowy z "
            "07.11.2026. Centrum nie wie, którego z nich dotyczy Wpis od jan.testowy z 08.11.2026, więc nie zmieniło "
            "żadnego z nich przy tym kliknięciu.",
            id="numer-zlecen-wykonawcy-z-dwoch-innych-dni",
        ),
        pytest.param(
            JAN,
            SUBJECT,
            [_order(day=date(2026, 11, 7), worker="Ewa.Probna")],
            RefusedMove(JAN_LOGIN, DAY, OrderNumber("40000001"), date(2026, 11, 7), DAY, MoveBar.NOT_ORDERED),
            "Wpis zlecenia 40000001 od jan.testowy ma w temacie 08.11.2026, a INTERMAX ma to zlecenie w 07.11.2026. "
            "Centrum go nie przeniosło i nie wpisało, bo dzień 08.11.2026 nie jest jeszcze uporządkowany w INTERMAX.",
            id="numer-zlecenia-innego-wykonawcy-z-innego-dnia-bez-dnia-uporzadkowanego",
        ),
        pytest.param(
            JAN,
            SUBJECT,
            [_order(number="40000077")],
            UnknownNumber(JAN_LOGIN, DAY, OrderNumber("40000001"), AddBar.NOT_ORDERED),
            "Numeru 40000001 z Wpisu od jan.testowy z 08.11.2026 nie ma w uporządkowanych zleceniach INTERMAX, a Centrum "
            "go nie dopisało, bo dzień 08.11.2026 nie jest jeszcze uporządkowany w INTERMAX.",
            id="numer-spoza-zlecen-wszystkich-wykonawcow-bez-dnia-uporzadkowanego",
        ),
    ],
)
def test_wpis_trafia_tylko_do_zlecenia_nadawcy_z_dnia_z_tematu_a_pomylka_ma_dokladny_powod(
    sender: str, subject: str, orders: list[RegisterOrder], problem: ReportProblem, sentence: str
) -> None:
    """Spec #1224 US 27–30: numer, którego nie da się przenieść, bo INTERMAX ma go więcej niż raz, z miejscem każdego
    zlecenia, numer z innego dnia, którego nie da się przenieść na dzień z tematu bez Dnia uporządkowanego (ADR 0029),
    i numer spoza zleceń z dokładnym powodem; żadna komórka się nie zmienia."""

    outcome = enter_reports(_inputs([_mail(sender, subject, TEXT)], orders, rollout=date(2026, 11, 1)))

    assert outcome.changes == ()
    assert outcome.problems == (problem,)
    assert reason(problem) == sentence


def test_numer_w_dwoch_miejscach_nie_przenosi_ani_zlecenia_nadawcy_z_innego_dnia_ani_cudzego_z_dnia_z_tematu() -> None:
    """Numer zlecenia Jana z 7.11 i zlecenia Ewy z 8.11, a Raport Jana za 8.11: Centrum nie wie, które z nich Jan
    wykonał, więc nie przenosi żadnego i nic nie wpisuje, a tata widzi oba miejsca."""

    orders = [_order(day=date(2026, 11, 7)), _order(OrderRow("Zlecenia", 121), worker="Ewa.Probna")]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], orders, rollout=date(2026, 11, 1), ordered=OPEN_DAYS))

    assert (outcome.changes, outcome.moves) == ((), ())
    assert outcome.problems == (
        RepeatedNumber(JAN_LOGIN, DAY, OrderNumber("40000001"), ((date(2026, 11, 7), JAN_LOGIN), (DAY, EWA_LOGIN))),
    )
    assert _days(outcome)[DAY, JAN_LOGIN].problems == 1


def test_numer_zlecen_dwoch_innych_wykonawcow_z_dnia_daje_jeden_problem_z_kazdym_z_nich() -> None:
    adam = _order(OrderRow("Zlecenia", 121), worker="Adam.Inny")
    orders = [_order(worker="Ewa.Probna"), adam]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], orders))

    assert outcome.changes == ()
    assert outcome.problems == (
        RepeatedNumber(JAN_LOGIN, DAY, OrderNumber("40000001"), ((DAY, Login("adam.inny")), (DAY, EWA_LOGIN))),
    )


def _after(orders: Sequence[RegisterOrder], outcome: ReportsOutcome) -> list[RegisterOrder]:
    """INTERMAX po zapisie kliknięcia, tak jak go przeczyta następne kliknięcie: komórki z ``changes``, a przeniesione
    zlecenie u nowego Wykonawcy i w nowym dniu, w tym samym wierszu (miejsce w dniu rdzeń dostaje tylko przez wiersz), a
    Zlecenie dopisane z raportu w nowym wierszu pod ostatnim wierszem arkusza, bez ``ADRES``."""

    written = {(change.order, change.column): change.value for change in outcome.changes}
    moved = {move.order: move for move in outcome.moves}
    found = []
    for order in orders:
        move = moved.get(order.row)
        day = order.key.day if move is None else move.day
        changed = RegisterOrder.of(
            order.row,
            number=order.key.number,
            started=datetime(day.year, day.month, day.day, 9, 30),
            worker=order.worker_name if move is None else move.worker,
            successful=written.get((order.row, ReportColumn.SUCCESSFUL), order.successful),
            completed=written.get((order.row, ReportColumn.COMPLETED), order.completed),
            address="Ulica Testowa 1" if order.addressed else None,
        )
        assert changed is not None
        found.append(changed)
    last = max((order.row.row for order in orders), default=1)
    for index, added in enumerate(outcome.added, start=1):
        new = RegisterOrder.of(
            OrderRow(added.sheet, last + index),
            number=added.number,
            started=datetime(added.day.year, added.day.month, added.day.day),
            worker=added.worker,
            successful=added.successful,
            completed=added.completed,
            address=None,
        )
        assert new is not None
        found.append(new)
    return found


EWA_ROW = OrderRow("Zlecenia", 125)
EWA_OWN = _order(EWA_ROW, number="40000005", worker="Ewa.Probna")
"""Zlecenie Ewy z tego samego dnia: z niego przeniesione zlecenie bierze pisownię ``WYKONAWCA`` Ewy."""


@pytest.mark.parametrize(
    ("ewa_orders", "name"),
    [
        pytest.param([EWA_OWN], "Ewa.Probna", id="pisownia-z-segmentu-nadawcy-w-tym-dniu"),
        pytest.param(
            [_order(EWA_ROW, number="40000005", worker="EWA.PROBNA", day=date(2026, 11, 7))],
            "EWA.PROBNA",
            id="pisownia-z-innego-dnia-otwartego",
        ),
        pytest.param([], "ewa.probna", id="bez-zlecen-nadawcy-login"),
    ],
)
def test_wpis_innego_wykonawcy_do_zlecenia_z_dnia_przenosi_je_do_nadawcy_z_informacja_po_obu_stronach(
    ewa_orders: list[RegisterOrder], name: str
) -> None:
    """ADR 0029, #1347: Wpis Ewy z numerem jedynego zlecenia Jana z dnia z tematu to Przeniesienie zlecenia, nie
    problem: zlecenie przechodzi do Ewy z jej pisownią ``WYKONAWCA``, dostaje jej Wpis, liczy się u niej na końcu
    zleceń dnia, a tata dostaje informację „przejęte od” u Ewy i „przekazane” u Jana. Pamięć ma Przeniesienie i własne
    wpisy pod kluczem zlecenia u Ewy."""

    orders = [_order(), *ewa_orders]

    outcome = enter_reports(
        _inputs([_mail(EWA, SUBJECT, "40000001 tak montaż")], orders, rollout=date(2026, 11, 1))
    )

    ewa_key = _key(worker="ewa.probna")
    assert outcome.moves == (OrderMove(ROW, DAY, name),)
    assert outcome.changes == (
        CellChange(ROW, ReportColumn.SUCCESSFUL, "tak"),
        CellChange(ROW, ReportColumn.COMPLETED, "montaż"),
    )
    assert outcome.problems == ()
    assert outcome.notes == (
        TakenOver(DAY, EWA_LOGIN, OrderNumber("40000001"), JAN_LOGIN),
        HandedOver(DAY, JAN_LOGIN, OrderNumber("40000001"), EWA_LOGIN),
    )
    assert [note(found) for found in outcome.notes] == ["przejęte od jan.testowy", "przekazane ewa.probna"]
    assert outcome.memory == OwnEntries(
        frozenset({OwnEntry(ewa_key, ReportColumn.SUCCESSFUL, "tak"), OwnEntry(ewa_key, ReportColumn.COMPLETED, "montaż")}),
        frozenset({OwnMove(OrderNumber("40000001"), DAY, EWA_LOGIN, DAY, JAN_LOGIN, "Jan.Testowy", EVENING)}),
    )
    days = {(worker.day, worker.worker): worker for worker in outcome.workers}
    assert [order.number for order in days[DAY, EWA_LOGIN].orders_detail] == [
        *(order.key.number for order in ewa_orders if order.key.day == DAY),
        "40000001",
    ]
    assert (DAY, JAN_LOGIN) not in days


def test_przeniesione_zlecenie_stoi_w_liczbach_nadawcy_za_jego_zleceniami_dnia_nawet_z_nizszego_wiersza() -> None:
    """Zapis stawia przeniesione zlecenie pod ostatnim zleceniem nadawcy, więc widok Raporty pokazuje je na końcu jego
    zleceń dnia, także gdy w INTERMAX przed zapisem stało wyżej niż jego zlecenia."""

    orders = [_order(OrderRow("Zlecenia", 100)), EWA_OWN, _order(OrderRow("Zlecenia", 130), number="40000006", worker="Ewa.Probna")]

    outcome = enter_reports(_inputs([_mail(EWA, SUBJECT, "40000001 tak montaż")], orders))

    [ewa] = outcome.workers
    assert [order.number for order in ewa.orders_detail] == ["40000005", "40000006", "40000001"]


def test_swiezszy_mail_wygrywa_miedzy_wykonawcami_w_kolejnych_kliknieciach_i_w_jednym() -> None:
    """US 3, kryterium #1347: Jan, potem Ewa, potem znów Jan. Kliknięcie po mailu Ewy przenosi zlecenie do Ewy z jej
    Wpisem, a kliknięcie po drugim mailu Jana oddaje je Janowi z jego Wpisem, bez informacji, bo zlecenie stoi tam, gdzie
    stało przed Centrum; Jan nie ma innych zleceń, więc wraca z pisownią ``WYKONAWCA``, którą pamięć ma sprzed
    Przeniesienia do Ewy. Jedno kliknięcie z trzema mailami w każdej
    kolejności daje to samo, co kolejne kliknięcia."""

    jan = _mail(JAN, SUBJECT, "40000001 tak wymiana routera", EVENING)
    ewa = _mail(EWA, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(minutes=10))
    again = _mail(JAN, SUBJECT, "40000001 tak montaż", EVENING + timedelta(minutes=20))
    orders = [_order(), EWA_OWN]

    first = enter_reports(_inputs([jan], orders))
    second_orders = _after(orders, first)
    second = enter_reports(_inputs([jan, ewa], second_orders, memory=first.memory))
    third_orders = _after(second_orders, second)
    third = enter_reports(_inputs([jan, ewa, again], third_orders, memory=second.memory))
    fourth_orders = _after(third_orders, third)

    assert first.moves == ()
    assert second.moves == (OrderMove(ROW, DAY, "Ewa.Probna"),)
    assert [change.value for change in second.changes] == ["nie", "klient nieobecny"]
    assert third.moves == (OrderMove(ROW, DAY, "Jan.Testowy"),)
    assert [change.value for change in third.changes] == ["tak", "montaż"]
    assert third.notes == ()
    final = [(order.key, order.successful, order.completed) for order in fourth_orders]
    assert final == [(_key(), "tak", "montaż"), (EWA_OWN.key, None, None)]
    for mails in itertools.permutations([jan, ewa, again]):
        once = enter_reports(_inputs(mails, orders))

        assert (once.moves, once.notes) == ((), ())
        assert [(order.key, order.successful, order.completed) for order in _after(orders, once)] == final


def test_drugie_klikniecie_bez_nowych_maili_nic_nie_zmienia_a_informacje_zostaja() -> None:
    """Kryterium #1347: po Przeniesieniu INTERMAX ma zlecenie u Ewy, więc powtórne kliknięcie nie daje zmian ani
    Przeniesień, a informacje po obu stronach stoją dalej z pamięci."""

    mails = [_mail(EWA, SUBJECT, "40000001 tak montaż")]
    orders = [_order(), EWA_OWN]
    first = enter_reports(_inputs(mails, orders))

    second = enter_reports(_inputs(mails, _after(orders, first), memory=first.memory))

    assert (second.changes, second.moves, second.problems) == ((), (), ())
    assert second.notes == first.notes != ()
    assert second.memory == first.memory


@pytest.mark.parametrize("manual", ["Jan.Testowy", "Adam.Inny"])
def test_reczna_zmiana_wykonawcy_po_przeniesieniu_wygrywa_bez_problemu(manual: str) -> None:
    """US 15, ADR 0029: tata oddał zlecenie Janowi albo dał je komuś innemu po Przeniesieniu do Ewy. Następne kliknięcie
    z tym samym mailem Ewy go nie przenosi, nie wpisuje Wpisu Ewy i nie daje problemu ani informacji, a pamięć dalej
    pamięta Przeniesienie i to, że tata je zmienił, żeby zmiana taty wygrywała też potem, także z późniejszym mailem Ewy
    (decyzja autora #1358 do potwierdzenia przez Maksa)."""

    mails = [_mail(EWA, SUBJECT, "40000001 nie klient nieobecny")]
    later = _mail(EWA, SUBJECT, "40000001 tak montaż", EVENING + timedelta(minutes=10))
    orders = [_order(), EWA_OWN]
    first = enter_reports(_inputs(mails, orders))
    by_tata = [replace(order, key=replace(order.key, worker=Login(manual.lower())), worker_name=manual) if order.row == ROW else order for order in _after(orders, first)]

    second = enter_reports(_inputs(mails, by_tata, memory=first.memory))
    third = enter_reports(_inputs([*mails, later], by_tata, memory=second.memory))

    for after in (second, third):
        assert (after.changes, after.moves, after.problems, after.notes) == ((), (), (), ())
    assert second.memory.moves == {replace(move, overridden=True) for move in first.memory.moves}


def test_po_recznym_oddaniu_zlecenia_janowi_liczy_sie_jego_wpis_a_nie_mail_ewy() -> None:
    """Gdy tata oddał przeniesione zlecenie Janowi, liczą się tylko Wpisy Jana: jego wcześniejszy Wpis wraca do komórek,
    które Centrum samo wpisało Wpisem Ewy, a pamięć dalej mówi o Przeniesieniu, więc mail Ewy nie przenosi zlecenia
    także w następnym kliknięciu."""

    jan = _mail(JAN, SUBJECT, "40000001 tak wymiana routera", EVENING)
    ewa = _mail(EWA, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(minutes=10))
    orders = [_order(), EWA_OWN]
    first = enter_reports(_inputs([jan, ewa], orders))
    by_tata = [replace(order, key=_key(), worker_name="Jan.Testowy") if order.row == ROW else order for order in _after(orders, first)]

    second = enter_reports(_inputs([jan, ewa], by_tata, memory=first.memory))
    third = enter_reports(_inputs([jan, ewa], _after(by_tata, second), memory=second.memory))

    assert second.moves == ()
    assert [change.value for change in second.changes] == ["tak", "wymiana routera"]
    assert (third.changes, third.moves) == ((), ())


def test_reczna_zmiana_miejsca_po_przeniesieniu_wygrywa() -> None:
    """US 15: tata przestawił przeniesione zlecenie w inne miejsce dnia, u Ewy. Rdzeń przenosi tylko przy zmianie
    Wykonawcy, więc następne kliknięcie zostawia wiersz tam, gdzie go postawił tata."""

    mails = [_mail(EWA, SUBJECT, "40000001 tak montaż")]
    orders = [_order(), EWA_OWN]
    first = enter_reports(_inputs(mails, orders))
    elsewhere = [replace(order, row=OrderRow("Zlecenia", 90)) if order.row == ROW else order for order in _after(orders, first)]

    second = enter_reports(_inputs(mails, elsewhere, memory=first.memory))

    assert (second.changes, second.moves) == ((), ())


def test_reczna_zmiana_wykonawcy_przed_raportem_poprawia_mail() -> None:
    """US 16: ręcznie wpisany ``WYKONAWCA`` sprzed Raportu wykonawcy (bez Przeniesienia w pamięci) poprawia mail."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], [_order(worker="Ewa.Probna")]))

    assert outcome.moves == (OrderMove(ROW, DAY, "jan.testowy"),)


def _given_to(orders: Sequence[RegisterOrder], name: str) -> list[RegisterOrder]:
    """Tata zmienia w Excelu ``WYKONAWCA`` zlecenia z wiersza ``ROW`` na ``name``."""

    return [
        replace(order, key=replace(order.key, worker=Login(name.lower())), worker_name=name) if order.row == ROW else order
        for order in orders
    ]


def test_reczna_zmiana_wykonawcy_po_wpisie_bez_przeniesienia_wygrywa_z_tym_samym_mailem() -> None:
    """ADR 0029 „Ręczna zmiana dalej wygrywa”, przegląd #1358 r1: Centrum wpisało Wpis Jana, a potem jego poprawkę, do
    jego własnego zlecenia, a tata dał potem zlecenie Ewie. Kolejne kliknięcia z tymi samymi mailami Jana nie przenoszą
    zlecenia z powrotem, nie dają informacji ani problemu, a komórki, które Centrum wpisało i których nikt nie ruszył,
    dalej są jego wpisem."""

    mails = [_mail(JAN, SUBJECT, TEXT), _mail(JAN, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(minutes=5))]
    orders = [_order()]
    first = enter_reports(_inputs(mails[:1], orders))
    corrected = enter_reports(_inputs(mails, _after(orders, first), memory=first.memory))
    by_tata = _given_to(_after(_after(orders, first), corrected), "Ewa.Probna")

    second = enter_reports(_inputs(mails, by_tata, memory=corrected.memory))
    third = enter_reports(_inputs(mails, by_tata, memory=second.memory))

    assert (first.moves, corrected.moves) == ((), ())
    assert [change.value for change in corrected.changes] == ["nie", "klient nieobecny"]
    for later in (second, third):
        assert (later.changes, later.moves, later.problems, later.notes) == ((), (), (), ())
    assert third.memory.entries == {
        OwnEntry(_key(worker="ewa.probna"), ReportColumn.SUCCESSFUL, "nie"),
        OwnEntry(_key(worker="ewa.probna"), ReportColumn.COMPLETED, "klient nieobecny"),
    }


def test_swiezszy_mail_po_recznej_zmianie_wykonawcy_po_wpisie_przenosi_zlecenie_z_pisownia_taty() -> None:
    """US 3: mail Jana, który przyszedł po Wpisie, który Centrum już wpisało, wygrywa z ręczną zmianą taty sprzed niego,
    więc przenosi zlecenie z powrotem do Jana z informacją po obu stronach. Jan nie ma innych zleceń w dniach otwartych,
    więc zlecenie dostaje pisownię ``WYKONAWCA``, którą miało u Jana, gdy Centrum przyjęło jego Wpis. Mail z tą samą
    chwilą przyjścia co przyjęty nie jest świeższy."""

    first_mail = _mail(JAN, SUBJECT, TEXT)
    orders = [_order(worker="JAN.Testowy")]
    first = enter_reports(_inputs([first_mail], orders))
    by_tata = _given_to(_after(orders, first), "Ewa.Probna")
    same_time = _mail(JAN, SUBJECT, "40000001 nie klient nieobecny", EVENING)
    newer = _mail(JAN, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(minutes=1))

    tie = enter_reports(_inputs([first_mail, same_time], by_tata, memory=first.memory))
    outcome = enter_reports(_inputs([first_mail, newer], by_tata, memory=first.memory))

    assert tie.moves == ()
    assert outcome.moves == (OrderMove(ROW, DAY, "JAN.Testowy"),)
    assert [change.value for change in outcome.changes] == ["nie", "klient nieobecny"]
    assert outcome.notes == (
        HandedOver(DAY, EWA_LOGIN, OrderNumber("40000001"), JAN_LOGIN),
        TakenOver(DAY, JAN_LOGIN, OrderNumber("40000001"), EWA_LOGIN),
    )


def test_druga_reczna_zmiana_po_wpisie_u_wykonawcy_od_taty_nie_wraca_starym_mailem() -> None:
    """Przegląd #1358 r2 (C), tabela przejść R1/R2: Centrum wpisało Wpis Jana u Jana, tata dał zlecenie Ewie, Centrum
    wpisało u niej jej Wpis (pamięć podnosi ``since`` do jej maila), a tata oddał zlecenie Janowi. Następne kliknięcie z
    tymi samymi mailami nie przenosi zlecenia do Ewy: jej mail Centrum już przyjęło. Liczy się Wpis Jana i wraca do
    komórek, które Centrum wpisało Wpisem Ewy, bo komórki idą z wierszem (bez różnicy z ręczną wartością)."""

    jan = _mail(JAN, SUBJECT, TEXT, EVENING)
    ewa = _mail(EWA, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(minutes=30))
    orders = [_order(), EWA_OWN]
    first = enter_reports(_inputs([jan], orders))
    to_ewa = _given_to(_after(orders, first), "Ewa.Probna")
    second = enter_reports(_inputs([jan, ewa], to_ewa, memory=first.memory))
    back = _given_to(_after(to_ewa, second), "Jan.Testowy")

    third = enter_reports(_inputs([jan, ewa], back, memory=second.memory))
    fourth = enter_reports(_inputs([jan, ewa], _after(back, third), memory=third.memory))

    assert (second.moves, [change.value for change in second.changes]) == ((), ["nie", "klient nieobecny"])
    assert (third.moves, third.problems, third.notes) == ((), (), ())
    assert [change.value for change in third.changes] == ["tak", "wymiana routera"]
    assert (fourth.changes, fourth.moves, fourth.problems) == ((), (), ())


def test_druga_reczna_zmiana_po_przeniesieniu_nie_wraca_starym_mailem() -> None:
    """Przegląd #1358 r2 (E), tabela przejść R3: Centrum przeniosło zlecenie Jana do Ewy, tata oddał je Janowi, Centrum
    wpisało Wpis Jana u Jana, a tata dał zlecenie znów Ewie, tam, gdzie postawiło je Centrum. Tata zmienił Wykonawcę po
    Przeniesieniu Centrum, więc żaden mail już zlecenia nie przenosi, także nowszy mail Jana."""

    ewa = _mail(EWA, SUBJECT, "40000001 nie klient nieobecny", EVENING)
    jan = _mail(JAN, SUBJECT, TEXT, EVENING + timedelta(minutes=30))
    newer = _mail(JAN, SUBJECT, "40000001 tak montaż", EVENING + timedelta(hours=1))
    orders = [_order(), EWA_OWN]
    first = enter_reports(_inputs([ewa], orders))
    to_jan = _given_to(_after(orders, first), "Jan.Testowy")
    second = enter_reports(_inputs([ewa, jan], to_jan, memory=first.memory))
    to_ewa = _given_to(_after(to_jan, second), "Ewa.Probna")

    third = enter_reports(_inputs([ewa, jan], to_ewa, memory=second.memory))
    fourth = enter_reports(_inputs([ewa, jan, newer], _after(to_ewa, third), memory=third.memory))

    assert first.moves == (OrderMove(ROW, DAY, "Ewa.Probna"),)
    assert (second.moves, [change.value for change in second.changes]) == ((), ["tak", "wymiana routera"])
    assert (third.moves, fourth.moves) == ((), ())
    assert ManualDifference not in {type(problem) for problem in (*third.problems, *fourth.problems)}


def test_zmiana_taty_przed_dzialaniem_centrum_a_potem_wpis_u_wykonawcy_od_taty_trzyma_tak_samo() -> None:
    """Przegląd #1358 r2 (D, kontrola do C): bez pierwszego Wpisu Jana tata dał zlecenie Ewie, zanim Centrum cokolwiek
    z nim zrobiło (US 16), Centrum wpisało Wpis Ewy u Ewy, a tata oddał zlecenie Janowi. Mail Ewy już przyjęty nie
    przenosi go z powrotem, tak samo jak w C."""

    ewa = _mail(EWA, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(minutes=30))
    orders = _given_to([_order(), EWA_OWN], "Ewa.Probna")
    second = enter_reports(_inputs([ewa], orders))
    back = _given_to(_after(orders, second), "Jan.Testowy")

    third = enter_reports(_inputs([ewa], back, memory=second.memory))

    assert (second.moves, third.moves) == ((), ())


def test_przeniesione_zlecenie_bez_zlecen_nadawcy_bierze_pisownie_z_najnowszego_miejsca_w_pamieci() -> None:
    """Nadawca bez zleceń w dniach otwartych, którego dwa zlecenia Centrum przeniosło wcześniej do Ewy: przejęte
    zlecenie dostaje pisownię ``WYKONAWCA`` z jego miejsca z najpóźniejszego dnia w pamięci, nie z najwcześniejszego
    ani pierwszej alfabetycznie."""

    earlier_day = date(2026, 11, 7)
    memory = OwnEntries(
        frozenset(),
        frozenset(
            {
                OwnMove(OrderNumber("40000007"), earlier_day, EWA_LOGIN, earlier_day, JAN_LOGIN, "Jan.Testowy", EVENING),
                OwnMove(OrderNumber("40000008"), DAY, EWA_LOGIN, DAY, JAN_LOGIN, "JAN.TESTOWY", EVENING),
            }
        ),
    )
    orders = [
        _order(worker="Ewa.Probna"),
        _order(OrderRow("Zlecenia", 110), number="40000007", day=earlier_day, worker="Ewa.Probna"),
        _order(OrderRow("Zlecenia", 121), number="40000008", worker="Ewa.Probna"),
    ]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], orders, rollout=earlier_day, memory=memory))

    assert outcome.moves == (OrderMove(ROW, DAY, "JAN.TESTOWY"),)


def test_pamiec_wpisow_numeru_pod_dwoma_kluczami_przepada_takze_przy_jednym_wierszu() -> None:
    """Pamięć sprzed #1367 r4 ma wpisy numeru pod kluczem Jana i Ewy z jednego dnia, czyli numer miał wtedy dwa wiersze, a
    teraz INTERMAX ma jeden, u Jana. Excel nie mówi, czy tata usunął wiersz Ewy, czy wiersz Jana i dał Janowi wiersz Ewy,
    więc wpisy przepadają: wartość w komórce liczy się jak wartość taty, a świeższy Wpis Jana daje różnicę zamiast
    nadpisać ją."""

    memory = OwnEntries(
        frozenset({OwnEntry(_key(), ReportColumn.SUCCESSFUL, "tak"), OwnEntry(_key(worker="ewa.probna"), ReportColumn.SUCCESSFUL, "nie")})
    )
    mail = _mail(JAN, SUBJECT, "40000001 nie")

    outcome = enter_reports(_inputs([mail], [_order(successful="tak")], memory=memory))

    assert outcome.memory.entries == frozenset()
    assert outcome.changes == ()
    assert outcome.problems == (ManualDifference(_key(), ReportColumn.SUCCESSFUL, "tak", "nie"),)


SEVENTH, SIXTH = date(2026, 11, 7), date(2026, 11, 6)
OPEN_DAYS = (SIXTH, SEVENTH, DAY)
"""Dni uporządkowane arkusza ``Zlecenia``: wszystkie dni otwarte okna od 6.11."""


_NAMES = {Login("jan.testowy"): "Jan.Testowy", Login("ewa.probna"): "Ewa.Probna", Login("adam.inny"): "Adam.Inny"}
_SENT_FROM = {Login("jan.testowy"): JAN, Login("ewa.probna"): EWA, Login("adam.inny"): ADAM}
_EVENTS = st.lists(
    st.one_of(
        st.tuples(st.just("mail"), st.sampled_from(sorted(_NAMES)), st.integers(0, 4), st.sampled_from(["tak", "nie", ""])),
        st.tuples(st.just("tata"), st.sampled_from(sorted(_NAMES))),
        st.just(("click",)),
    ),
    max_size=14,
)
_EVENTS_WITH_DAYS = st.lists(
    st.one_of(
        st.tuples(
            st.just("mail"),
            st.sampled_from(sorted(_NAMES)),
            st.integers(0, 4),
            st.sampled_from(["tak", "nie", ""]),
            st.sampled_from(OPEN_DAYS),
        ),
        st.tuples(st.just("tata"), st.sampled_from(sorted(_NAMES))),
        st.tuples(st.just("tata"), st.sampled_from(OPEN_DAYS)),
        st.just(("click",)),
    ),
    max_size=14,
)
"""Zdarzenia własności z Przeniesieniami między dniami (#1350): mail ma dzień z tematu, a tata zmienia też dzień."""

_Place = tuple[Login, date]
"""Miejsce zlecenia w tabeli przejść: Wykonawca i dzień."""


@dataclass(frozen=True)
class _Remembered:
    """Pamięć zlecenia w wyroczni, wprost z tabeli przejść: miejsce Centrum, miejsce sprzed pierwszego Przeniesienia,
    ``since`` i czy tata zmienił miejsce po Przeniesieniu Centrum."""

    placed: _Place
    origin: _Place
    since: datetime
    held: bool


def _table(
    remembered: _Remembered | None, current: _Place, mails: Sequence[tuple[ReportMail, _Place, str]]
) -> tuple[_Place, _Remembered | None, tuple[ReportMail, _Place, str] | None]:
    """Tabela przejść z opisu #1358 bez kodu produkcyjnego, z miejscem = Wykonawca i dzień (jeden Wpis w raporcie, więc
    każdy mail stawia zlecenie u nadawcy w dniu z tematu): miejsce zlecenia po kliknięciu, pamięć po kliknięciu i
    zwycięski mail (``None``: żaden Wpis się nie liczy)."""

    held = remembered is not None and (
        remembered.held or (current != remembered.placed and remembered.placed != remembered.origin)
    )
    counted = [
        found
        for found in mails
        if found[1] == current or remembered is None or (not held and found[0].arrived > remembered.since)
    ]
    if not counted:
        return current, None if remembered is None else replace(remembered, held=held), None
    winner = max(counted, key=lambda found: (found[0].arrived, found[0].id.digest))
    mail, target, verdict = winner
    if not verdict:
        return current, None if remembered is None else replace(remembered, held=held), winner
    if target == current:
        if remembered is None:
            return current, _Remembered(current, current, mail.arrived, held=False), winner
        return current, replace(remembered, since=max(remembered.since, mail.arrived), held=held), winner
    origin = remembered.origin if remembered is not None and remembered.placed == current else current
    return target, _Remembered(target, origin, mail.arrived, held=False), winner


def _follows_table(events: Sequence[tuple[object, ...]]) -> None:
    """Po każdym kliknięciu ciągu ``events`` zlecenie stoi w miejscu z tabeli przejść (``_table``), z Wpisem zwycięskiego
    maila w komórkach, bez różnicy z ręczną wartością (tata nie zmienia komórek, więc każda wartość jest wpisem Centrum),
    z informacjami tylko wtedy, gdy stoi tam, gdzie je przeniosło Centrum, a powtórne kliknięcie bez nowych zdarzeń nic
    nie zmienia."""

    orders = [_order()]
    mails: list[tuple[ReportMail, _Place, str]] = []
    memory = OwnEntries.EMPTY
    remembered: _Remembered | None = None
    for index, event in enumerate(events):
        match event:
            case ("mail", str(login), int(minutes), str(verdict), *rest):
                [day] = rest or [DAY]
                assert isinstance(day, date)
                text = f"40000001 {verdict} opis {index}".replace("  ", " ")
                subject = f"Raport {day:%d.%m.%Y}"
                sent = _mail(_SENT_FROM[Login(login)], subject, text, EVENING + timedelta(minutes=minutes), f"<{index}@x.invalid>")
                mails.append((sent, (Login(login), day), verdict))
            case ("tata", str(login)):
                orders = _given_to(orders, _NAMES[Login(login)])
            case ("tata", date() as day):
                [order] = orders
                orders = [
                    _order(
                        order.row,
                        number=order.key.number,
                        day=day,
                        worker=order.worker_name,
                        successful=order.successful,
                        completed=order.completed,
                    )
                ]
            case _:
                [order] = orders
                expected, remembered, winner = _table(remembered, (order.key.worker, order.key.day), mails)
                inputs = [found[0] for found in mails]
                outcome = enter_reports(_inputs(inputs, orders, memory=memory, rollout=SIXTH, ordered=OPEN_DAYS))
                orders, memory = _after(orders, outcome), outcome.memory
                again = enter_reports(_inputs(inputs, orders, memory=memory, rollout=SIXTH, ordered=OPEN_DAYS))

                [after] = orders
                assert (after.key.worker, after.key.day) == expected
                if winner is not None and winner[2]:
                    assert (after.successful, after.completed) == (winner[2], winner[0].text.split(maxsplit=2)[2])
                assert not [problem for problem in outcome.problems if isinstance(problem, ManualDifference)]
                standing = remembered is not None and remembered.placed == expected != remembered.origin
                assert bool(outcome.notes) == standing
                assert (again.changes, again.moves, again.memory) == ((), (), memory)


@settings(derandomize=True, database=None, max_examples=300)
@given(_EVENTS)
@example(
    [
        ("mail", "jan.testowy", 0, "tak"),
        ("click",),
        ("tata", "ewa.probna"),
        ("mail", "ewa.probna", 3, "nie"),
        ("click",),
        ("tata", "jan.testowy"),
        ("click",),
    ]
)
@example(
    [
        ("mail", "ewa.probna", 0, "nie"),
        ("click",),
        ("tata", "jan.testowy"),
        ("mail", "jan.testowy", 3, "tak"),
        ("click",),
        ("tata", "ewa.probna"),
        ("click",),
        ("mail", "jan.testowy", 4, "tak"),
        ("click",),
    ]
)
def test_zlecenie_po_kazdym_kliknieciu_stoi_tam_gdzie_mowi_tabela_przejsc(events: list[tuple[object, ...]]) -> None:
    """ADR 0029 „Ręczna zmiana dalej wygrywa”, US 3, 15, 16: dowolny ciąg maili (nadawca, chwila, ``tak``/``nie`` albo
    brak), ręcznych zmian ``WYKONAWCA`` przez tatę i kliknięć daje po każdym kliknięciu to, co tabela przejść
    (``_follows_table``)."""

    _follows_table(events)


@settings(derandomize=True, database=None, max_examples=300)
@given(_EVENTS_WITH_DAYS)
@example(
    [
        ("mail", "jan.testowy", 0, "tak", SEVENTH),
        ("click",),
        ("tata", SIXTH),
        ("mail", "ewa.probna", 3, "nie", SIXTH),
        ("click",),
        ("tata", SEVENTH),
        ("click",),
    ]
)
@example(
    [
        ("mail", "ewa.probna", 0, "nie", SEVENTH),
        ("click",),
        ("tata", DAY),
        ("mail", "jan.testowy", 3, "tak", DAY),
        ("click",),
        ("tata", SEVENTH),
        ("click",),
        ("mail", "jan.testowy", 4, "tak", DAY),
        ("click",),
    ]
)
@example(
    [
        ("mail", "jan.testowy", 0, "tak", DAY),
        ("click",),
        ("tata", SIXTH),
        ("mail", "jan.testowy", 3, "nie", SIXTH),
        ("click",),
        ("tata", DAY),
        ("click",),
    ]
).via("Wpis przyjęty w dniu od taty podnosi since pamięci z dnia Centrum")
@example(
    [
        ("mail", "jan.testowy", 0, "tak", SEVENTH),
        ("click",),
        ("mail", "jan.testowy", 1, "nie", SIXTH),
        ("click",),
        ("tata", SEVENTH),
        ("mail", "ewa.probna", 3, "tak", SEVENTH),
        ("click",),
    ]
).via("Przeniesienie na inny dzień zastępuje pamięć zlecenia, a tata oddaje je dniowi starej pamięci")
@example(
    [
        ("mail", "jan.testowy", 0, "tak", DAY),
        ("click",),
        ("tata", SIXTH),
        ("mail", "jan.testowy", 3, "nie", SIXTH),
        ("click",),
    ]
).via("własne wpisy idą za zleceniem, któremu tata zmienił dzień")
def test_zlecenie_po_kazdym_kliknieciu_stoi_tam_gdzie_mowi_tabela_przejsc_takze_miedzy_dniami(
    events: list[tuple[object, ...]],
) -> None:
    """#1350 z tabelą przejść #1358 (miejsce = Wykonawca i dzień): dowolny ciąg maili z dniem z tematu z dni otwartych,
    ręcznych zmian ``WYKONAWCA`` albo dnia przez tatę i kliknięć daje po każdym kliknięciu to, co tabela przejść
    (``_follows_table``): Przeniesienie na inny dzień podlega tej samej regule ``may_move`` co Przeniesienie do innego
    Wykonawcy."""

    _follows_table(events)


_EVENTS_WITH_SECOND_ORDER = st.lists(
    st.one_of(
        st.tuples(
            st.just("mail"),
            st.sampled_from(sorted(_NAMES)),
            st.integers(0, 4),
            st.sampled_from(["tak", "nie", ""]),
            st.sampled_from(OPEN_DAYS),
        ),
        st.tuples(st.just("tata"), st.integers(0, 1), st.sampled_from(sorted(_NAMES))),
        st.tuples(st.just("tata"), st.integers(0, 1), st.sampled_from(OPEN_DAYS)),
        st.just(("drugie",)),
        st.just(("click",)),
    ),
    max_size=16,
)
"""Zdarzenia własności z dwoma zleceniami numeru 40000001 (#1367 r3): mail z dniem z tematu, zmiana Wykonawcy albo dnia
zlecenia 0 albo 1 przez tatę, drugie zlecenie (1) znika albo wraca na swoje miejsce (``drugie``) i kliknięcie."""


def _keeps_rule_with_second_order(events: Sequence[tuple[object, ...]]) -> None:
    """Reguła #1367 r3 bez kodu produkcyjnego, z pamięcią każdego zlecenia osobno (wyrocznia wie, który wiersz jest
    którym zleceniem, Centrum nie): po każdym kliknięciu

    - dopóki INTERMAX ma numer w dwóch zleceniach, żadne nie zmienia miejsca;
    - zlecenie zmienia miejsce tylko na miejsce nadawcy najpóźniejszego maila do tego miejsca, z ``tak``/``nie``, i tylko
      gdy według tabeli przejść #1358 jego własnej pamięci ten mail może je przenieść: jest świeższy niż każdy mail, który
      Centrum wpisało do tego zlecenia albo którym je przeniosło, a tata nie zmienił jego miejsca po Przeniesieniu
      Centrum (obserwacja: w miejscu Centrum nie stoi żadne zlecenie numeru), więc stary mail nigdy nie cofa ręcznej
      decyzji taty;
    - Wpis bez Przeniesienia trafia tylko do zlecenia, które stoi u nadawcy w dniu z tematu;
    - powtórne kliknięcie bez nowych zdarzeń nic nie zmienia."""

    orders = {0: _order(OrderRow("Zlecenia", 201), day=SEVENTH), 1: _order(OrderRow("Zlecenia", 202), day=SIXTH, worker="Ewa.Probna")}
    present = {0, 1}
    mails: list[tuple[ReportMail, _Place, str]] = []
    memory = OwnEntries.EMPTY
    truth: dict[int, _Remembered] = {}
    for index, event in enumerate(events):
        match event:
            case ("mail", str(login), int(minutes), str(verdict), date() as day):
                text = f"40000001 {verdict} opis {index}".replace("  ", " ")
                arrived = EVENING + timedelta(minutes=minutes)
                sent = _mail(_SENT_FROM[Login(login)], f"Raport {day:%d.%m.%Y}", text, arrived, f"<{index}@x.invalid>")
                mails.append((sent, (Login(login), day), verdict))
            case ("tata", int(which), str(login)):
                [orders[which]] = _by_tata([orders[which]], orders[which].row, worker=_NAMES[Login(login)])
            case ("tata", int(which), date() as day):
                [orders[which]] = _by_tata([orders[which]], orders[which].row, day=day)
            case ("drugie",):
                present ^= {1}
            case _:
                which_present = sorted(present)
                places = {which: (orders[which].key.worker, orders[which].key.day) for which in which_present}
                standing = [orders[which] for which in which_present]
                inputs = [found[0] for found in mails]
                outcome = enter_reports(_inputs(inputs, standing, memory=memory, rollout=SIXTH, ordered=OPEN_DAYS))
                after = _after(standing, outcome)
                again = enter_reports(_inputs(inputs, after, memory=outcome.memory, rollout=SIXTH, ordered=OPEN_DAYS))

                assert (again.changes, again.moves, again.memory) == ((), (), outcome.memory)
                if len(which_present) > 1:
                    assert outcome.moves == ()
                for which, order in zip(which_present, after, strict=True):
                    current, now = places[which], (order.key.worker, order.key.day)
                    remembered = truth.get(which)
                    held = remembered is not None and (
                        remembered.held or (remembered.placed != remembered.origin and remembered.placed not in places.values())
                    )
                    if now != current:
                        mail, _, verdict = max(
                            (found for found in mails if found[1] == now), key=lambda found: (found[0].arrived, found[0].id.digest)
                        )
                        assert verdict
                        assert remembered is None or (mail.arrived > remembered.since and not held), (which, mail, remembered)
                        origin = remembered.origin if remembered is not None and remembered.placed == current else current
                        truth[which] = _Remembered(now, origin, mail.arrived, held=False)
                    elif order.completed != orders[which].completed:
                        [(mail, target, _)] = [found for found in mails if found[0].text.endswith(f" {order.completed}")]
                        assert target == current
                        truth[which] = (
                            _Remembered(current, current, mail.arrived, held=False)
                            if remembered is None
                            else replace(remembered, since=max(remembered.since, mail.arrived), held=held)
                        )
                    elif remembered is not None:
                        truth[which] = replace(remembered, held=held)
                    orders[which] = order
                memory = outcome.memory


@settings(derandomize=True, database=None, max_examples=300)
@given(_EVENTS_WITH_SECOND_ORDER)
@example(
    [
        ("mail", "jan.testowy", 0, "tak", SEVENTH),
        ("click",),
        ("tata", 0, DAY),
        ("click",),
        ("mail", "adam.inny", 3, "tak", SIXTH),
        ("click",),
        ("click",),
        ("drugie",),
        ("click",),
    ]
).via("przegląd #1367 r2 Ważne 1: Przeniesienie drugiego zlecenia numeru kasowało pamięć zlecenia przeniesionego przez tatę")
@example(
    [
        ("drugie",),
        ("mail", "ewa.probna", 0, "tak", SEVENTH),
        ("click",),
        ("drugie",),
        ("tata", 0, DAY),
        ("click",),
        ("tata", 0, SEVENTH),
        ("drugie",),
        ("mail", "jan.testowy", 3, "nie", SEVENTH),
        ("click",),
    ]
).via("zmiana taty po Przeniesieniu Centrum zauważona, gdy numer stał w dwóch miejscach")
def test_numer_w_dwoch_zleceniach_nie_zmienia_miejsca_a_stary_mail_nie_cofa_zmiany_taty(events: list[tuple[object, ...]]) -> None:
    """#1367 r3 (przegląd r2 Ważne 1): dowolny ciąg maili trzech Wykonawców z dniami z tematu, zmian Wykonawcy i dnia
    dwóch zleceń jednego numeru przez tatę, zniknięć i powrotów drugiego zlecenia oraz kliknięć daje po każdym
    kliknięciu to, co mówi reguła (``_keeps_rule_with_second_order``)."""

    _keeps_rule_with_second_order(events)


def test_miejsce_zlecenia_z_dnia_poza_oknem_wypada_z_pamieci() -> None:
    """Pamięć trzyma miejsca zleceń tylko z dni otwartych: okres z Plikiem zbiorczym zamyka dzień, więc jego
    Przeniesienie wypada z pamięci przy następnym kliknięciu, a Przeniesienie z dnia otwartego zostaje."""

    closed = date(2026, 11, 2)
    old = OwnMove(OrderNumber("40000009"), closed, EWA_LOGIN, closed, JAN_LOGIN, "Jan.Testowy", EVENING - timedelta(days=6))
    standing = OwnMove(OrderNumber("40000001"), DAY, EWA_LOGIN, DAY, JAN_LOGIN, "Jan.Testowy", EVENING)
    memory = OwnEntries(frozenset(), frozenset({old, standing}))

    outcome = enter_reports(
        _inputs([], [_order(worker="Ewa.Probna")], rollout=date(2026, 10, 30), closed=(period_of(closed).token,), memory=memory)
    )

    assert outcome.memory.moves == {standing}


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        pytest.param(
            "40000001 montaż", MissingVerdict(EWA_LOGIN, DAY, OrderNumber("40000001"), VerdictFault.MISSING), id="bez-tak-nie"
        ),
        pytest.param("40000001 tak montaż 40000001 nie brak klienta", None, id="przeciwny-zamiar"),
    ],
)
def test_zwycieski_wpis_bez_tak_albo_nie_nie_przenosi_zlecenia(text: str, problem: ReportProblem | None) -> None:
    """Zlecenie przechodzi tylko z Wpisem, który da się wpisać: Wpis bez ``tak``/``nie`` albo z przeciwnym zamiarem daje
    problem nadawcy, a zlecenie zostaje u Jana."""

    outcome = enter_reports(_inputs([_mail(EWA, SUBJECT, text)], [_order(), EWA_OWN]))

    assert (outcome.moves, outcome.changes, outcome.notes) == ((), (), ())
    assert len(outcome.problems) == 1
    assert problem is None or outcome.problems == (problem,)


def test_dwa_zlecenia_jana_przejete_przez_ewe_bez_segmentu_przechodza_razem_po_wierszach() -> None:
    """Dwa przejęte zlecenia jednego kliknięcia: każde ma swoje Przeniesienie, po arkuszu i wierszu, i swoje informacje;
    Ewa bez zleceń w dniach otwartych dostaje swój login."""

    second = OrderRow("Zlecenia", 121)
    orders = [_order(), _order(second, number="40000002")]

    outcome = enter_reports(_inputs([_mail(EWA, SUBJECT, "40000002 tak a\n40000001 nie b")], orders))

    assert outcome.moves == (OrderMove(ROW, DAY, "ewa.probna"), OrderMove(second, DAY, "ewa.probna"))
    assert len(outcome.notes) == 4


# --- Zlecenie z innego dnia (#1350, ADR 0029): Przeniesienie na dzień z tematu albo pomylony temat ---

def _numbered(index: int, day: date = DAY, worker: str = "Jan.Testowy") -> RegisterOrder:
    return _order(OrderRow("Zlecenia", 200 + index), number=f"4000{index:04d}", day=day, worker=worker)


def _days(outcome: ReportsOutcome) -> dict[tuple[date, Login], WorkerDay]:
    return {(worker.day, worker.worker): worker for worker in outcome.workers}


def test_jeden_niezgodny_wpis_przenosi_zlecenie_na_dzien_z_tematu_z_informacja_po_obu_stronach() -> None:
    """US 5, 12, 27: zlecenie Jana z 7.11 w Raporcie wykonawcy za 8.11 to jedyny niezgodny Wpis, więc przechodzi na 8.11
    pod jego zlecenia (pisownia ``WYKONAWCA`` z jego segmentu), z Wpisem i informacją „przeniesione z 7.11” w dniu
    docelowym i „przeniesione na 8.11” w źródłowym. Pamięć ma Przeniesienie na nowym dniu i własne wpisy pod nowym
    kluczem."""

    moved, own = _numbered(1, SEVENTH), _numbered(2)
    mail = _mail(JAN, SUBJECT, "40000001 tak montaż\n40000002 nie brak klienta")

    outcome = enter_reports(_inputs([mail], [moved, own], rollout=SIXTH, ordered=OPEN_DAYS))

    number = OrderNumber("40000001")
    assert outcome.moves == (OrderMove(moved.row, DAY, "Jan.Testowy"),)
    assert outcome.problems == ()
    assert [(change.order, change.value) for change in outcome.changes] == [
        (moved.row, "tak"),
        (moved.row, "montaż"),
        (own.row, "nie"),
        (own.row, "brak klienta"),
    ]
    assert outcome.notes == (MovedTo(SEVENTH, JAN_LOGIN, number, DAY), MovedFrom(DAY, JAN_LOGIN, number, SEVENTH))
    assert [note(found) for found in outcome.notes] == ["przeniesione na 8.11", "przeniesione z 7.11"]
    assert {move for move in outcome.memory.moves if move.number == number} == {
        OwnMove(number, DAY, JAN_LOGIN, SEVENTH, JAN_LOGIN, "Jan.Testowy", EVENING)
    }
    assert {entry.key for entry in outcome.memory.entries} == {_key("40000001"), _key("40000002")}
    days = _days(outcome)
    assert [order.number for order in days[DAY, JAN_LOGIN].orders_detail] == ["40000002", "40000001"]
    assert (SEVENTH, JAN_LOGIN) not in days


@pytest.mark.parametrize(
    "mistaken",
    [pytest.param((SIXTH, SEVENTH), id="dwa-rozne-dni"), pytest.param((SEVENTH, SEVENTH), id="ten-sam-dzien")],
)
def test_dwa_niezgodne_wpisy_to_pomylony_temat_wpisy_ida_do_zlecen_z_ich_dnia_bez_przeniesienia(
    mistaken: tuple[date, date],
) -> None:
    """US 6–8: Raport wykonawcy za 8.11 z 8 zgodnymi i 2 niezgodnymi Wpisami (także wskazującymi różne dni) to pomylony
    temat: niezgodne wpisują się do zleceń z ich dnia w INTERMAX bez Przeniesienia, zgodne normalnie, a tata dostaje w
    dniu z tematu informację o każdym przegranym temacie. Zlecenia z ich dnia liczą się jako wpisane z Wpisu."""

    matching = [_numbered(index) for index in range(1, 9)]
    other = [_numbered(9, mistaken[0]), _numbered(10, mistaken[1])]
    text = "\n".join(f"4000{index:04d} tak montaż {index}" for index in range(1, 11))

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], [*matching, *other], rollout=SIXTH, ordered=OPEN_DAYS))

    assert (outcome.moves, outcome.problems) == ((), ())
    assert {change.order for change in outcome.changes} == {order.row for order in [*matching, *other]}
    assert outcome.notes == (
        SubjectLost(DAY, JAN_LOGIN, OrderNumber("40000009"), mistaken[0]),
        SubjectLost(DAY, JAN_LOGIN, OrderNumber("40000010"), mistaken[1]),
    )
    assert note(outcome.notes[0]) == f"pomylony temat: wpisane do zlecenia z {mistaken[0].day}.11"
    assert {(move.day, move.worker) == (move.origin_day, move.origin_worker) for move in outcome.memory.moves} == {True}
    for order in other:
        [detail] = [found for found in _days(outcome)[order.key.day, JAN_LOGIN].orders_detail if found.number == order.key.number]
        assert detail == OrderDetail(order.key.number, "tak", detail.activities, reported=True)


@pytest.mark.parametrize("intermax_day", [SIXTH, SEVENTH], ids=["zlecenia-z-6", "zlecenia-z-7"])
def test_ta_sama_tresc_raportu_pod_dwoma_dniami_wpisuje_sie_raz_do_zlecen_z_ich_dnia_w_intermax(intermax_day: date) -> None:
    """Prawdziwa skrzynka 12.11.2026: Wykonawca wysłał treść jednego dnia jako ``Raport`` za 7.11 i zaraz jako
    ``Raport`` za 6.11, a potem prawdziwy Raport za 7.11. Dzień zleceń mówi INTERMAX: które z dwóch tematów jest
    pomylone, ten przegrywa (pomylony temat, ADR 0029), więc każde zlecenie dostaje Wpis raz, w swoim dniu, bez
    Przeniesienia i bez problemu dla taty, w każdej kolejności maili."""

    twice = [_numbered(index, intermax_day) for index in range(1, 4)]
    seventh = [_numbered(index, SEVENTH) for index in range(4, 6)]
    same = "40000001 tak montaż\n40000002 nie brak klienta\n40000003 tak"
    mails = [
        _mail(JAN, "Raport 07.11.2026", same, datetime(2026, 11, 8, 18, 54, tzinfo=TAPA)),
        _mail(JAN, "Raport 06.11.2026", same, datetime(2026, 11, 8, 18, 56, tzinfo=TAPA)),
        _mail(JAN, "Raport 07.11.2026", "40000004 tak\n40000005 tak", datetime(2026, 11, 8, 18, 59, tzinfo=TAPA)),
    ]

    for order in (mails, mails[::-1]):
        outcome = enter_reports(_inputs(order, [*twice, *seventh], rollout=SIXTH, ordered=OPEN_DAYS))

        assert (outcome.moves, outcome.problems) == ((), ())
        assert {change.order for change in outcome.changes} == {found.row for found in [*twice, *seventh]}
        assert len(outcome.changes) == len({(change.order, change.column) for change in outcome.changes})
        assert {entry.key.day for entry in outcome.memory.entries if entry.key.number in {"40000001", "40000002", "40000003"}} == {
            intermax_day
        }


def test_zlecenie_cudze_i_z_innego_dnia_zmienia_wykonawce_zawsze_a_dzien_wedlug_progu() -> None:
    """US 9: zlecenie Ewy z 7.11 w Raporcie Jana za 8.11. Jako jedyny niezgodny Wpis przechodzi do Jana i na 8.11, z
    informacjami o obu zmianach po obu stronach; z drugim niezgodnym Wpisem (pomylony temat) przechodzi do Jana w swoim
    dniu 7.11."""

    ewa = _numbered(1, SEVENTH, "Ewa.Probna")
    number = OrderNumber("40000001")

    single = enter_reports(_inputs([_mail(JAN, SUBJECT, "40000001 tak")], [ewa], rollout=SIXTH, ordered=OPEN_DAYS))
    mistaken = enter_reports(
        _inputs(
            [_mail(JAN, SUBJECT, "40000001 tak\n40000002 tak")],
            [ewa, _numbered(2, SIXTH)],
            rollout=SIXTH,
            ordered=OPEN_DAYS,
        )
    )

    assert single.moves == (OrderMove(ewa.row, DAY, "jan.testowy"),)
    assert set(single.notes) == {
        TakenOver(DAY, JAN_LOGIN, number, EWA_LOGIN),
        HandedOver(SEVENTH, EWA_LOGIN, number, JAN_LOGIN),
        MovedFrom(DAY, JAN_LOGIN, number, SEVENTH),
        MovedTo(SEVENTH, EWA_LOGIN, number, DAY),
    }
    assert mistaken.moves == (OrderMove(ewa.row, SEVENTH, "Jan.Testowy"),)
    assert set(mistaken.notes) == {
        TakenOver(SEVENTH, JAN_LOGIN, number, EWA_LOGIN),
        HandedOver(SEVENTH, EWA_LOGIN, number, JAN_LOGIN),
        SubjectLost(DAY, JAN_LOGIN, number, SEVENTH),
        SubjectLost(DAY, JAN_LOGIN, OrderNumber("40000002"), SIXTH),
    }


@pytest.mark.parametrize(
    ("orders", "places"),
    [
        pytest.param(
            [_numbered(1, SEVENTH), _numbered(2, SIXTH, "Ewa.Probna")],
            ((SIXTH, EWA_LOGIN), (SEVENTH, JAN_LOGIN)),
            id="zlecenie-nadawcy-i-cudze-z-innych-dni",
        ),
        pytest.param(
            [_numbered(1, SEVENTH, "Ewa.Probna"), _numbered(2, SIXTH, "Anna.Kowalska")],
            ((SIXTH, Login("anna.kowalska")), (SEVENTH, EWA_LOGIN)),
            id="dwa-cudze-z-innych-dni",
        ),
    ],
)
def test_niezgodny_wpis_z_numerem_w_dwoch_dniach_nie_przenosi_zadnego_zlecenia(
    orders: list[RegisterOrder], places: tuple[tuple[date, Login], ...]
) -> None:
    """Numer w kilku zleceniach dni otwartych (decyzja #1367 r3): Raport Jana za 8.11 z numerem, który INTERMAX ma w
    7.11 i 6.11, nie przenosi żadnego z tych zleceń, także zlecenia Jana, i nic nie wpisuje, a tata widzi każde miejsce
    numeru (``RepeatedNumber``)."""

    numbered = [replace(order, key=replace(order.key, number=OrderNumber("40000001"))) for order in orders]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "40000001 tak montaż")], numbered, rollout=SIXTH, ordered=OPEN_DAYS))

    assert (outcome.moves, outcome.changes) == ((), ())
    assert outcome.problems == (RepeatedNumber(JAN_LOGIN, DAY, OrderNumber("40000001"), places),)


@pytest.mark.parametrize(
    ("ordered", "bar"),
    [
        pytest.param((SIXTH, SEVENTH), MoveBar.NOT_ORDERED, id="dzien-z-tematu-nieuporzadkowany"),
        pytest.param((), MoveBar.OTHER_SHEET, id="dzien-z-tematu-uporzadkowany-w-innym-arkuszu"),
    ],
)
def test_przeniesienie_tylko_do_dnia_uporzadkowanego_arkusza_zlecenia(ordered: tuple[date, ...], bar: MoveBar) -> None:
    """US 13: Przeniesienie na dzień, który nie jest Dniem uporządkowanym arkusza zlecenia, zostawia INTERMAX bez zmiany
    i daje problem z powodem w dniu z tematu."""

    order = _numbered(1, SEVENTH)
    inputs = _inputs([_mail(JAN, SUBJECT, "40000001 tak")], [order], rollout=SIXTH, ordered=ordered)
    if bar is MoveBar.OTHER_SHEET:
        inputs = replace(inputs, ordered_days=frozenset({OrderedDay("ZLECENIA OD 08_11_2021", DAY)}))

    outcome = enter_reports(inputs)

    assert (outcome.changes, outcome.moves, outcome.notes) == ((), (), ())
    assert outcome.problems == (RefusedMove(JAN_LOGIN, DAY, OrderNumber("40000001"), SEVENTH, DAY, bar),)
    assert _days(outcome)[DAY, JAN_LOGIN].problems == 1


CLOSED_DAY = date(2026, 11, 2)
CLOSED = (period_of(CLOSED_DAY).token,)


def test_przeniesienie_z_okresu_z_plikiem_zbiorczym_jest_problemem_bez_zmiany() -> None:
    """US 14: zlecenie z dnia okresu z Plikiem zbiorczym w Raporcie za dzień otwarty to jedyny niezgodny Wpis, ale okres
    jest zamknięty, więc problem z powodem w dniu z tematu; przy pomylonym temacie zlecenie zostaje w zamkniętym dniu bez
    problemu, a drugi niezgodny Wpis wpisuje się do zlecenia ze swojego dnia."""

    closed = _numbered(1, CLOSED_DAY)
    inputs = _inputs([_mail(JAN, SUBJECT, "40000001 tak")], [closed], rollout=date(2026, 10, 30), closed=CLOSED, ordered=OPEN_DAYS)

    single = enter_reports(inputs)
    mistaken = enter_reports(
        replace(inputs, mails=[_mail(JAN, SUBJECT, "40000001 tak\n40000002 tak")], orders=[closed, _numbered(2, SEVENTH)])
    )

    assert (single.changes, single.moves) == ((), ())
    assert single.problems == (RefusedMove(JAN_LOGIN, DAY, OrderNumber("40000001"), CLOSED_DAY, CLOSED_DAY, MoveBar.CLOSED_SOURCE),)
    assert (mistaken.moves, mistaken.problems) == ((), ())
    assert [change.order for change in mistaken.changes] == [OrderRow("Zlecenia", 202)]
    assert mistaken.notes == (SubjectLost(DAY, JAN_LOGIN, OrderNumber("40000002"), SEVENTH),)


def test_przeniesienie_do_okresu_z_plikiem_zbiorczym_jest_problemem_w_dniu_zlecenia() -> None:
    """US 14: Raport za dzień okresu z Plikiem zbiorczym z jednym zleceniem z dnia otwartego nie przenosi go do
    zamkniętego okresu. Problem stoi w dniu zlecenia, bo dnia z tematu widok Raporty nie pokazuje; pomylony temat
    takiego raportu wpisuje się do zleceń z ich dnia, z informacją w dniu zlecenia. Zgodny Wpis do zamkniętego dnia
    niczego nie zmienia."""

    open_order, closed_order = _numbered(1, SEVENTH), _numbered(3, CLOSED_DAY)
    subject = f"Raport {CLOSED_DAY:%d.%m.%Y}"
    inputs = _inputs(
        [_mail(JAN, subject, "40000001 tak\n40000003 tak")],
        [open_order, closed_order],
        rollout=date(2026, 10, 30),
        closed=CLOSED,
        ordered=OPEN_DAYS,
    )

    single = enter_reports(inputs)
    mistaken = enter_reports(
        replace(
            inputs,
            mails=[_mail(JAN, subject, "40000001 tak\n40000002 tak\n40000003 tak")],
            orders=[open_order, _numbered(2, SIXTH), closed_order],
        )
    )

    refused = RefusedMove(JAN_LOGIN, CLOSED_DAY, OrderNumber("40000001"), SEVENTH, CLOSED_DAY, MoveBar.CLOSED_TARGET)
    assert (single.changes, single.moves, single.notes) == ((), (), ())
    assert single.problems == (refused,)
    assert refused.shown == SEVENTH
    assert _days(single)[SEVENTH, JAN_LOGIN].problems == 1
    assert "okres z dniem 02.11.2026 ma już Plik zbiorczy" in reason(refused)
    assert (mistaken.moves, mistaken.problems) == ((), ())
    assert {change.order for change in mistaken.changes} == {open_order.row, OrderRow("Zlecenia", 202)}
    assert set(mistaken.notes) == {
        SubjectLost(SEVENTH, JAN_LOGIN, OrderNumber("40000001"), SEVENTH),
        SubjectLost(SIXTH, JAN_LOGIN, OrderNumber("40000002"), SIXTH),
    }


def test_numer_dwa_razy_w_dniu_wpisuje_sie_do_jedynego_zlecenia_nadawcy_a_swiezszy_raport_z_innym_dniem_go_nie_przenosi() -> None:
    """Numer stoi 7.11 u Jana i u Ewy (decyzja #1367 r3): Raport Jana za 7.11 trafia do jego zlecenia, bez Przeniesienia.
    Świeższy Raport Jana za 8.11 nie przenosi żadnego z tych zleceń i niczego nie wpisuje, a tata widzi oba miejsca
    numeru. Pamięć nie ma wpisów numeru, który INTERMAX ma dwa razy (#1367 r4): Excel nie mówi, który wiersz jest
    którym, więc wpisy Centrum nie mogą przejść do zlecenia Ewy."""

    jan = _order(OrderRow("Zlecenia", 201), day=SEVENTH, worker="Jan.Testowy")
    ewa = _order(OrderRow("Zlecenia", 202), day=SEVENTH, worker="Ewa.Probna")
    entered = _mail(JAN, "Raport 07.11.2026", "40000001 tak montaż", EVENING)
    fresher = _mail(JAN, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(minutes=5))
    first = enter_reports(_inputs([entered], [jan, ewa], rollout=SIXTH, ordered=OPEN_DAYS))

    second = enter_reports(_inputs([entered, fresher], _after([jan, ewa], first), rollout=SIXTH, ordered=OPEN_DAYS, memory=first.memory))

    assert [(change.order, change.value) for change in first.changes] == [(jan.row, "tak"), (jan.row, "montaż")]
    assert (second.moves, second.changes) == ((), ())
    assert second.problems == (
        RepeatedNumber(JAN_LOGIN, DAY, OrderNumber("40000001"), ((SEVENTH, EWA_LOGIN), (SEVENTH, JAN_LOGIN))),
    )
    assert (first.memory.entries, second.memory.entries) == (frozenset(), frozenset())


# --- Numer w kilku zleceniach dni otwartych (#1367 r3): żadnego Przeniesienia, pamięć numeru nie ginie ---


def _by_tata(
    orders: Sequence[RegisterOrder], row: OrderRow, *, day: date | None = None, worker: str | None = None
) -> list[RegisterOrder]:
    """Tata zmienia w Excelu dzień albo ``WYKONAWCA`` zlecenia z wiersza ``row``; jego komórki zostają."""

    return [
        _order(
            order.row,
            number=order.key.number,
            day=order.key.day if day is None else day,
            worker=order.worker_name if worker is None else worker,
            successful=order.successful,
            completed=order.completed,
        )
        if order.row == row
        else order
        for order in orders
    ]


def _clicked(
    mails: Sequence[ReportMail], orders: Sequence[RegisterOrder], memory: OwnEntries
) -> tuple[list[RegisterOrder], ReportsOutcome]:
    """Kliknięcie w oknie od 6.11 z Dniami uporządkowanymi ``OPEN_DAYS`` i INTERMAX po jego zapisie."""

    outcome = enter_reports(_inputs(mails, orders, rollout=SIXTH, ordered=OPEN_DAYS, memory=memory))
    return _after(orders, outcome), outcome


N1 = OrderNumber("40000001")


@pytest.mark.parametrize(
    ("other", "sender", "day"),
    [
        pytest.param(
            _mail(ADAM, "Raport 06.11.2026", "40000001 tak wymiana", EVENING + timedelta(minutes=10)),
            Login("adam.inny"),
            SIXTH,
            id="inny-wykonawca-przejmuje-drugie-zlecenie-numeru",
        ),
        pytest.param(
            _mail(EWA, "Raport 07.11.2026", "40000001 tak wymiana", EVENING + timedelta(minutes=10)),
            EWA_LOGIN,
            SEVENTH,
            id="drugie-zlecenie-numeru-na-dzien-opuszczony-przez-tate",
        ),
    ],
)
def test_stary_mail_nie_cofa_recznej_zmiany_dnia_taty_gdy_numer_stoi_w_dwoch_miejscach(
    other: ReportMail, sender: Login, day: date
) -> None:
    """Przegląd #1367 r2 Ważne 1: numer 40000001 u Ewy 6.11 i u Jana 7.11. Centrum wpisuje Wpis Jana do jego zlecenia,
    tata przenosi je na 8.11, a potem przychodzi świeższy raport innego Wykonawcy z tym numerem. Numer w dwóch
    miejscach nie przenosi żadnego zlecenia, więc żadna pamięć numeru nie ginie, a stary mail Jana nie cofa ręcznej
    zmiany dnia taty w żadnym kliknięciu; tata widzi oba miejsca numeru przy każdym mailu, którego Centrum nie wpisało."""

    ewa, jan = _order(OrderRow("Zlecenia", 201), day=SIXTH, worker="Ewa.Probna"), _order(OrderRow("Zlecenia", 202), day=SEVENTH)
    jan_mail = _mail(JAN, "Raport 07.11.2026", "40000001 tak montaż", EVENING)

    orders, first = _clicked([jan_mail], [ewa, jan], OwnEntries.EMPTY)
    orders = _by_tata(orders, jan.row, day=DAY)
    orders, second = _clicked([jan_mail], orders, first.memory)
    orders, third = _clicked([jan_mail, other], orders, second.memory)
    orders, fourth = _clicked([jan_mail, other], orders, third.memory)

    places = ((SIXTH, EWA_LOGIN), (DAY, JAN_LOGIN))
    assert first.changes == (CellChange(jan.row, ReportColumn.SUCCESSFUL, "tak"), CellChange(jan.row, ReportColumn.COMPLETED, "montaż"))
    assert [outcome.moves for outcome in (first, second, third, fourth)] == [(), (), (), ()]
    assert [outcome.changes for outcome in (second, third, fourth)] == [(), (), ()]
    assert set(fourth.problems) == {RepeatedNumber(JAN_LOGIN, SEVENTH, N1, places), RepeatedNumber(sender, day, N1, places)}
    assert [(order.key.worker, order.key.day, order.successful, order.completed) for order in orders] == [
        (EWA_LOGIN, SIXTH, None, None),
        (JAN_LOGIN, DAY, "tak", "montaż"),
    ]
    assert fourth.memory.moves == first.memory.moves


def test_jedyne_zlecenie_numeru_przenosi_tylko_mail_swiezszy_od_kazdego_wpisu_centrum_do_zlecen_numeru() -> None:
    """Numer u Jana 7.11 i u Ewy 8.11, a Centrum wpisało do nich Wpis Ewy (18:15), a w następnym kliknięciu Wpis Jana
    (18:35): pamięć numeru (jedna, z miejscem pierwszego Wpisu) ma chwilę najświeższego z nich. Tata scala zlecenia:
    usuwa wiersz Ewy i przenosi zlecenie Jana na 8.11. Excel nie mówi, który wiersz został, więc przenosi je tylko mail
    świeższy od każdego Wpisu Centrum do zleceń numeru: Wpis Adama z 18:25 za 8.11 nie, bo jest starszy od Wpisu Jana,
    a Wpis Adama z 18:45 tak. Pamięć wpisów nie ma numeru, który miał dwa zlecenia, więc wartości w scalonym zleceniu
    liczą się jak wartości taty."""

    jan, ewa = _order(OrderRow("Zlecenia", 201), day=SEVENTH), _order(OrderRow("Zlecenia", 202), worker="Ewa.Probna")
    jan_mail = _mail(JAN, "Raport 07.11.2026", "40000001 tak montaż", EVENING + timedelta(minutes=30))
    ewa_mail = _mail(EWA, SUBJECT, "40000001 nie brak klienta", EVENING + timedelta(minutes=10))
    adam_older = _mail(ADAM, SUBJECT, "40000001 tak wymiana", EVENING + timedelta(minutes=20))
    adam_fresher = _mail(ADAM, SUBJECT, "40000001 tak wymiana routera", EVENING + timedelta(minutes=40))

    orders, earlier = _clicked([ewa_mail], [jan, ewa], OwnEntries.EMPTY)
    orders, first = _clicked([jan_mail, ewa_mail], orders, earlier.memory)
    merged = _by_tata([order for order in orders if order.row != ewa.row], jan.row, day=DAY)
    merged, second = _clicked([jan_mail, ewa_mail, adam_older], merged, first.memory)
    _, third = _clicked([jan_mail, ewa_mail, adam_older, adam_fresher], merged, second.memory)

    assert [change.order for change in (*earlier.changes, *first.changes)] == [ewa.row, ewa.row, jan.row, jan.row]
    assert first.memory.moves == {OwnMove(N1, DAY, EWA_LOGIN, DAY, EWA_LOGIN, "Ewa.Probna", jan_mail.arrived)}
    assert (second.moves, second.changes, second.problems) == ((), (), ())
    assert (first.memory.entries, second.memory.entries) == (frozenset(), frozenset())
    assert third.moves == (OrderMove(jan.row, DAY, "adam.inny"),)


def test_zmiana_taty_po_przeniesieniu_centrum_wygrywa_takze_gdy_numer_stal_wtedy_w_dwoch_miejscach() -> None:
    """Tabela przejść #1358 R3 z obserwacją przy numerze w kilku zleceniach: Centrum przeniosło jedyne zlecenie numeru
    od Jana do Ewy w 7.11. Tata wkleja ten numer drugi raz (Adam 6.11) i przenosi zlecenie Ewy na 8.11, więc w miejscu
    Centrum nie stoi żadne zlecenie numeru: Centrum to zapamiętuje, choć nie wie, które zlecenie tata przeniósł. Gdy
    tata odda je potem Ewie w 7.11 i usunie drugie, świeższy mail Jana go nie przenosi."""

    jan = _order(OrderRow("Zlecenia", 201), day=SEVENTH)
    adam = _order(OrderRow("Zlecenia", 202), day=SIXTH, worker="Adam.Inny")
    ewa_mail = _mail(EWA, "Raport 07.11.2026", "40000001 tak montaż", EVENING)
    jan_fresher = _mail(JAN, "Raport 07.11.2026", "40000001 nie klient nieobecny", EVENING + timedelta(minutes=10))

    orders, first = _clicked([ewa_mail], [jan], OwnEntries.EMPTY)
    orders = _by_tata([*orders, adam], jan.row, day=DAY)
    orders, second = _clicked([ewa_mail], orders, first.memory)
    alone = _by_tata([order for order in orders if order.row != adam.row], jan.row, day=SEVENTH)
    _, third = _clicked([ewa_mail, jan_fresher], alone, second.memory)

    assert first.moves == (OrderMove(jan.row, SEVENTH, "ewa.probna"),)
    assert second.moves == ()
    assert [move.overridden for move in second.memory.moves] == [True]
    assert (third.moves, third.changes) == ((), ())


def test_wpisy_do_dwoch_zlecen_numeru_z_jednego_dnia_w_jednym_kliknieciu_nie_cofaja_pamieci_najswiezszego() -> None:
    """Numer stoi 8.11 u Jana i u Ewy, a jedno kliknięcie wpisuje Wpis Ewy (18:10) do jej zlecenia i świeższy Wpis Jana
    (18:15) do jego, którego pierwszy mail (18:05) przyszedł przed mailem Ewy. Pamięć dnia ma najświeższy przyjęty mail,
    więc gdy tata usunie potem wiersz Ewy, Wpis Adama z 18:12 nie przenosi zlecenia Jana, a Wpis Adama z 18:20 tak."""

    jan, ewa = _order(OrderRow("Zlecenia", 201)), _order(OrderRow("Zlecenia", 202), worker="Ewa.Probna")
    mails = [
        _mail(JAN, SUBJECT, "40000001 tak montaż", EVENING),
        _mail(EWA, SUBJECT, "40000001 nie brak klienta", EVENING + timedelta(minutes=5)),
        _mail(JAN, SUBJECT, "40000001 tak montaż gniazda", EVENING + timedelta(minutes=10)),
    ]
    adam_older = _mail(ADAM, SUBJECT, "40000001 tak wymiana", EVENING + timedelta(minutes=7))
    adam_fresher = _mail(ADAM, SUBJECT, "40000001 tak wymiana routera", EVENING + timedelta(minutes=15))

    orders, first = _clicked(mails, [jan, ewa], OwnEntries.EMPTY)
    alone = [order for order in orders if order.row != ewa.row]
    _, second = _clicked([*mails, adam_older], alone, first.memory)
    _, third = _clicked([*mails, adam_older, adam_fresher], alone, first.memory)

    assert {(change.order, change.value) for change in first.changes} >= {(jan.row, "montaż gniazda"), (ewa.row, "brak klienta")}
    assert [move.since for move in first.memory.moves] == [EVENING + timedelta(minutes=10)]
    assert second.moves == ()
    assert third.moves == (OrderMove(jan.row, DAY, "adam.inny"),)


def test_wpisy_centrum_do_numeru_w_dwoch_wierszach_licza_sie_jak_reczne_gdy_tata_zostawi_jeden() -> None:
    """Numer stał 8.11 u Jana i u Ewy, Centrum wpisało oba Wpisy, a tata usunął wiersz Ewy. Excel nie mówi, który wiersz
    został, więc pamięć nie ma wpisów numeru z dwoma wierszami (#1367 r4): świeższy Wpis Adama przenosi jedyne zlecenie
    numeru do Adama, ale jego komórek nie nadpisuje, tylko pokazuje różnicę, jak przy wartości taty."""

    jan, ewa = _order(OrderRow("Zlecenia", 201)), _order(OrderRow("Zlecenia", 202), worker="Ewa.Probna")
    mails = [
        _mail(JAN, SUBJECT, "40000001 tak montaż", EVENING),
        _mail(EWA, SUBJECT, "40000001 nie brak klienta", EVENING + timedelta(minutes=5)),
    ]
    adam = _mail(ADAM, SUBJECT, "40000001 nie wymiana", EVENING + timedelta(minutes=10))

    orders, first = _clicked(mails, [jan, ewa], OwnEntries.EMPTY)
    _, second = _clicked([*mails, adam], [order for order in orders if order.row != ewa.row], first.memory)

    adam_key = _key(worker="adam.inny")
    assert {change.order for change in first.changes} == {jan.row, ewa.row}
    assert first.memory.entries == frozenset()
    assert second.moves == (OrderMove(jan.row, DAY, "adam.inny"),)
    assert second.changes == ()
    assert set(second.problems) == {
        ManualDifference(adam_key, ReportColumn.SUCCESSFUL, "tak", "nie"),
        ManualDifference(adam_key, ReportColumn.COMPLETED, "montaż", "wymiana"),
    }


def test_zlecenie_przeniesione_przez_centrum_dostaje_wpis_nadawcy_takze_gdy_numer_stanie_w_drugim_miejscu() -> None:
    """Centrum przeniosło jedyne zlecenie numeru od Jana z 7.11 do Adama na 8.11. Gdy tata wklei ten numer drugi raz
    (Ewa 6.11), poprawiony Raport Adama za 8.11 trafia do zlecenia, które INTERMAX ma u Adama w 8.11, bez Przeniesienia,
    a stary Raport Jana za 7.11 nie trafia nigdzie, bo Jan nie ma już w 7.11 zlecenia z tym numerem. Numer ma teraz dwa
    wiersze, więc Excel nie mówi, który z nich ma wpisy Centrum (tata mógł przestawić wiersz Adama i wkleić nowy): pamięć
    wpisów przepada, a poprawka daje różnicę z wartością w komórce zamiast jej nadpisać (#1367 r4)."""

    jan, ewa = _order(OrderRow("Zlecenia", 201), day=SEVENTH), _order(OrderRow("Zlecenia", 202), day=SIXTH, worker="Ewa.Probna")
    jan_mail = _mail(JAN, "Raport 07.11.2026", "40000001 tak montaż", EVENING)
    adam_mail = _mail(ADAM, SUBJECT, "40000001 tak wymiana", EVENING + timedelta(minutes=10))
    adam_fixed = _mail(ADAM, SUBJECT, "40000001 nie klient nieobecny", EVENING + timedelta(minutes=20))

    orders, first = _clicked([jan_mail, adam_mail], [jan], OwnEntries.EMPTY)
    _, second = _clicked([jan_mail, adam_mail, adam_fixed], [*orders, ewa], first.memory)

    adam = Login("adam.inny")
    adam_key = _key(worker="adam.inny")
    assert first.moves == (OrderMove(jan.row, DAY, "adam.inny"),)
    assert {entry.key for entry in first.memory.entries} == {adam_key}
    assert (second.moves, second.changes) == ((), ())
    assert set(second.problems) == {
        RepeatedNumber(JAN_LOGIN, SEVENTH, N1, ((SIXTH, EWA_LOGIN), (DAY, adam))),
        ManualDifference(adam_key, ReportColumn.SUCCESSFUL, "tak", "nie"),
        ManualDifference(adam_key, ReportColumn.COMPLETED, "wymiana", "klient nieobecny"),
    }
    assert second.memory.entries == frozenset()


def test_raport_z_dniem_okresu_z_plikiem_zbiorczym_z_numerem_w_dwoch_miejscach_nic_nie_zmienia_bez_problemu() -> None:
    """Raport Jana za 2.11 (okres z Plikiem zbiorczym) z numerem, który INTERMAX ma u Jana 7.11 i u Ewy 8.11: Centrum nie
    wie, którego zlecenia dotyczy, a dnia z tematu tata nie widzi, więc nic się nie zmienia i nie ma problemu."""

    orders = [_order(OrderRow("Zlecenia", 201), day=SEVENTH), _order(OrderRow("Zlecenia", 202), worker="Ewa.Probna")]
    mail = _mail(JAN, f"Raport {CLOSED_DAY:%d.%m.%Y}", "40000001 tak montaż")

    outcome = enter_reports(_inputs([mail], orders, rollout=date(2026, 10, 30), closed=CLOSED, ordered=OPEN_DAYS))

    assert (outcome.changes, outcome.moves, outcome.problems, outcome.notes) == ((), (), (), ())


def test_raport_za_dzien_zamkniety_nie_wpisuje_sie_do_zlecenia_nadawcy_z_okresu_z_plikiem_zbiorczym() -> None:
    """Numer stoi u Jana w 2.11 (okres z Plikiem zbiorczym) i u Ewy w 7.11. Rdzeń widzi zlecenie z dnia zamkniętego
    (#1367 r4), ale Raport Jana za 2.11 nie wpisuje się do niego, bo okres z Plikiem zbiorczym jest zamknięty, i nie daje
    problemu, bo dnia 2.11 tata nie widzi."""

    orders = [_order(OrderRow("Zlecenia", 201), day=CLOSED_DAY), _order(OrderRow("Zlecenia", 202), day=SEVENTH, worker="Ewa.Probna")]
    mail = _mail(JAN, f"Raport {CLOSED_DAY:%d.%m.%Y}", "40000001 tak montaż")

    outcome = enter_reports(_inputs([mail], orders, rollout=date(2026, 10, 30), closed=CLOSED, ordered=OPEN_DAYS))

    assert (outcome.changes, outcome.moves, outcome.problems, outcome.notes) == ((), (), (), ())


def test_poprawiony_raport_z_dniem_zlecenia_nadawcy_usuwa_problem_numeru_w_dwoch_miejscach() -> None:
    """US 40: Raport Jana za 8.11 z numerem, który INTERMAX ma u Jana 7.11 i u Ewy 8.11, daje ``RepeatedNumber``.
    Późniejszy Raport Jana za 7.11 z tym numerem trafia do jego zlecenia i problem znika: dzień poprawki to dzień
    któregoś ze zleceń numeru, nie tylko dzień z tematu."""

    orders = [_order(OrderRow("Zlecenia", 201), day=SEVENTH), _order(OrderRow("Zlecenia", 202), worker="Ewa.Probna")]
    wrong = _mail(JAN, SUBJECT, "40000001 tak montaż")
    fixed = _mail(JAN, "Raport 07.11.2026", "40000001 tak montaż", LATER)

    first = enter_reports(_inputs([wrong], orders, rollout=SIXTH, ordered=OPEN_DAYS))
    second = enter_reports(_inputs([wrong, fixed], orders, rollout=SIXTH, ordered=OPEN_DAYS))

    assert first.problems == (RepeatedNumber(JAN_LOGIN, DAY, N1, ((SEVENTH, JAN_LOGIN), (DAY, EWA_LOGIN))),)
    assert second.problems == ()
    assert [change.order for change in second.changes] == [OrderRow("Zlecenia", 201)] * 2


# --- Niezmienniki #1367 r4: numer w 1–3 zleceniach w dniach przed, w i po dziś, maile, zmiany taty i kliknięcia ---

NINTH = date(2026, 11, 9)
"""Dzień po dziś (8.11): tata wkleja i porządkuje zlecenia na jutro dzień wcześniej (ADR 0019)."""
READ_DAYS = (*OPEN_DAYS, NINTH)
"""Dni zleceń, które proces czyta przy dziś 8.11: od ``Window.start``, także po dziś."""
_SEQUENCE_NUMBERS = ("40000001", "40000002", "40000003")
"""Numer w 1–3 zleceniach, numer w jednym zleceniu i numer bez zlecenia."""
_LOGINS = sorted(_NAMES)
_BY_TATA = {
    ReportColumn.SUCCESSFUL: (None, "tak", "nie"),
    ReportColumn.COMPLETED: (None, "opis taty", "opis a", "opis b"),
}
"""Wartości komórek, które tata wpisuje ręcznie, także równe Wpisowi maila (``tak``, ``nie``, opis maila 0 albo 1)."""


def _described(index: int) -> str:
    """Opis Wpisów maila ``index`` ciągu: inny w każdym mailu, więc z komórki wiadomo, który mail Centrum wpisało."""

    return f"opis {ascii_lowercase[index]}"


@dataclass
class _Line:
    """Wiersz INTERMAX w wyroczni. Tożsamość wiersza (indeks) zna tylko test, a Centrum widzi numer, dzień, Wykonawcę i
    komórki. ``written``: wartość, którą Centrum ostatnio wpisało do komórki tego wiersza; ``since``: chwila przyjścia
    najświeższego maila, którego opis Centrum wpisało do tego wiersza; ``as_order``: proces robi z wiersza zlecenie, a
    bez tego czyta z niego tylko numer (wiersz bez ``WYKONAWCA``, z datą tekstem, z wyglądem z aplikacji)."""

    number: str
    day: date
    worker: Login
    cells: dict[ReportColumn, str | None]
    written: dict[ReportColumn, str] = field(default_factory=dict)
    since: datetime | None = None
    present: bool = True
    as_order: bool = True

    def order(self, index: int) -> RegisterOrder:
        return _order(
            OrderRow("Zlecenia", 300 + index),
            number=self.number,
            day=self.day,
            worker=_NAMES[self.worker],
            successful=self.cells[ReportColumn.SUCCESSFUL],
            completed=self.cells[ReportColumn.COMPLETED],
        )


_LineStart = tuple[date, str, int, int]
"""Wiersz na starcie: dzień, Wykonawca i indeksy ręcznych wartości ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE``."""
_SequenceStart = tuple[list[_LineStart], _LineStart, frozenset[date]]
"""Wiersze numeru 40000001 (1–3), wiersz numeru 40000002 i Dni uporządkowane poza dniami wierszy."""


def _line(number: str, start: _LineStart) -> _Line:
    day, login, successful, completed = start
    cells = {
        ReportColumn.SUCCESSFUL: _BY_TATA[ReportColumn.SUCCESSFUL][successful],
        ReportColumn.COMPLETED: _BY_TATA[ReportColumn.COMPLETED][completed],
    }
    return _Line(number, day, Login(login), cells)


def _lines(start: _SequenceStart) -> list[_Line]:
    numbered, other, _ = start
    return [*(_line(_SEQUENCE_NUMBERS[0], found) for found in numbered), _line(_SEQUENCE_NUMBERS[1], other)]


def _sent(index: int, login: str, day: date, minutes: int, entries: Sequence[tuple[int, str]]) -> ReportMail:
    """Mail ``index`` ciągu: Raport wykonawcy za ``day`` z Wpisem każdego numeru z ``entries`` z opisem maila."""

    text = "\n".join(f"{_SEQUENCE_NUMBERS[which]} {verdict} {_described(index)}".replace("  ", " ") for which, verdict in entries)
    arrived = EVENING + timedelta(minutes=minutes)
    return _mail(_SENT_FROM[Login(login)], f"Raport {day:%d.%m.%Y}", text, arrived, f"<r4-{index}@x.invalid>")


_LINE_START = st.tuples(st.sampled_from(READ_DAYS), st.sampled_from(_LOGINS), st.integers(0, 2), st.integers(0, 3))
_SEQUENCE_START = st.tuples(
    st.integers(1, 3).flatmap(lambda count: st.lists(_LINE_START, min_size=count, max_size=count)),
    _LINE_START,
    st.one_of(st.just(frozenset(READ_DAYS)), st.frozensets(st.sampled_from(READ_DAYS))),
)
_ROLLOUT = date(2026, 10, 30)
"""Dzień wdrożenia własności N0–N4: okres 27.10–2.11 ma Plik zbiorczy (``CLOSED``), więc dni 30.10–2.11 proces czyta
(od ``Window.start``), ale nie są otwarte."""
_SEQUENCE_DAYS = (date(2026, 11, 1), CLOSED_DAY, *READ_DAYS, date(2026, 11, 10))
"""Dni wierszy własności N0–N4: dwa dni okresu z Plikiem zbiorczym, dni otwarte, jutro i pojutrze, więc po zdarzeniu
„nowy dzień” (dziś 9.11) dalej jest dzień po dziś."""
_MAIL_DAYS = (CLOSED_DAY, *OPEN_DAYS, NINTH)
"""Dni z tematu maili: dzień okresu z Plikiem zbiorczym, dni otwarte i jutro, otwarte dopiero po „nowym dniu”."""


def _open(day: date, today: date) -> bool:
    """Dzień otwarty własności N0–N4 liczony bez kodu produkcyjnego: od 30.10 do dziś, poza okresem 27.10–2.11."""

    return _ROLLOUT <= day <= today and not date(2026, 10, 27) <= day <= CLOSED_DAY


_SEQUENCE_LINE = st.tuples(st.sampled_from(_SEQUENCE_DAYS), st.sampled_from(_LOGINS), st.integers(0, 2), st.integers(0, 3))
_SEQUENCE_ROWS = st.tuples(
    st.integers(1, 3).flatmap(lambda count: st.lists(_SEQUENCE_LINE, min_size=count, max_size=count)),
    _SEQUENCE_LINE,
    st.one_of(st.just(frozenset(_SEQUENCE_DAYS)), st.frozensets(st.sampled_from(_SEQUENCE_DAYS))),
)
_SEQUENCE_ENTRIES = st.lists(
    st.tuples(st.sampled_from((0, 0, 0, 1, 2)), st.sampled_from(("tak", "nie", "tak", "nie", ""))),
    min_size=1,
    max_size=3,
    unique_by=lambda entry: entry[0],
)
"""Wpisy maila: numer (najczęściej 40000001) i ``tak``/``nie`` albo brak."""
_SEQUENCE_MAIL = st.tuples(
    st.just("mail"), st.sampled_from(_LOGINS), st.sampled_from(_MAIL_DAYS), st.integers(0, 8), _SEQUENCE_ENTRIES
)
_SEQUENCE_TATA = st.one_of(
    st.tuples(st.just("komórka"), st.integers(0, 3), st.sampled_from(list(ReportColumn)), st.integers(0, 3)),
    st.tuples(st.just("wykonawca"), st.integers(0, 3), st.sampled_from(_LOGINS)),
    st.tuples(st.just("dzień"), st.integers(0, 3), st.sampled_from(_SEQUENCE_DAYS)),
    st.tuples(st.just("usuwa"), st.integers(0, 3)),
    st.tuples(st.just("wkleja"), st.integers(0, 1), _SEQUENCE_LINE),
    st.tuples(st.just("bez zlecenia"), st.integers(0, 2), st.sampled_from(_SEQUENCE_DAYS)),
    st.just(("zostaw",)),
    st.just(("nowy dzień",)),
)
_SEQUENCE_EVENTS = st.lists(
    st.tuples(st.lists(_SEQUENCE_TATA, max_size=3), st.lists(_SEQUENCE_MAIL, max_size=3)), min_size=1, max_size=6
).map(lambda rounds: [event for tata, mails in rounds for event in (*tata, *mails, ("klik",))])
"""Rundy zdarzeń: tata zmienia komórkę, Wykonawcę albo dzień wiersza (także na jutro i na dzień okresu z Plikiem
zbiorczym), usuwa wiersz, wkleja nowy wiersz numeru 40000001 albo 40000002, wkleja wiersz dowolnego numeru, z którego
proces nie robi zlecenia (bez ``WYKONAWCA``; wpisanie Wykonawcy robi z niego zlecenie), klika „Zostaw moją” przy każdej
różnicy z ostatniego kliknięcia albo przychodzi nowy dzień (dziś 9.11), przychodzą maile (nadawca, dzień z tematu, także
zamknięty i po dziś, minuta przyjścia, Wpisy: numer i ``tak``/``nie`` albo brak), a potem tata klika."""


def _click_keeping_invariants(
    lines: list[_Line],
    mails: Sequence[tuple[ReportMail, Login, frozenset[str]]],
    ordered: frozenset[date],
    memory: OwnEntries,
    kept: frozenset[Kept],
    today: date,
) -> ReportsOutcome:
    """Kliknięcie dnia ``today`` w oknie od 30.10 z okresem 27.10–2.11 z Plikiem zbiorczym, z wyroczniami N0–N4
    (``_keeps_invariants``); zmienia ``lines`` tak, jak zapis INTERMAX. Dni uporządkowane to ``ordered``, 2.11 i dzień
    każdego wiersza (uporządkowany wiersz ma swój dzień)."""

    present = {index: line for index, line in enumerate(lines) if line.present and line.as_order}
    counted = Counter(line.number for line in lines if line.present)
    ordered_count = Counter(line.number for line in present.values())
    read = frozenset(OrderNumber(line.number) for line in lines if line.present)

    def click(memory: OwnEntries) -> ReportsOutcome:
        orders = [line.order(index) for index, line in present.items()]
        days = sorted(ordered | {line.day for line in present.values()} | {CLOSED_DAY})
        sent = [mail for mail, _, _ in mails]
        rows = (
            *(ReadNumber(order.key.number, order.key.day) for order in orders),
            *(ReadNumber(OrderNumber(line.number)) for line in lines if line.present and not line.as_order),
        )
        inputs = _inputs(sent, orders, today=today, rollout=_ROLLOUT, closed=CLOSED, ordered=days, memory=memory, kept=kept)
        return enter_reports(replace(inputs, present=rows))

    outcome = click(memory)
    arrived = {_described(index): mail.arrived for index, (mail, _, _) in enumerate(mails)}
    described = {change.order.row - 300: change.value for change in outcome.changes if change.column is ReportColumn.COMPLETED}
    for move in outcome.moves:
        index, worker = move.order.row - 300, Login(move.worker.lower())
        line = present[index]
        assert counted[line.number] == 1, ("N2: Przeniesienie numeru, który INTERMAX ma w więcej niż jednym wierszu", move)
        assert _open(line.day, today) and _open(move.day, today), ("N0: Przeniesienie z dnia albo na dzień nieotwarty", move)
        assert any(
            sender == worker and line.number in numbers and (line.since is None or mail.arrived > line.since)
            for mail, sender, numbers in mails
        ), ("N3: Przeniesienie bez maila świeższego od wpisanego do tego wiersza", move, line)
        assert index not in described or line.since is None or arrived[described[index]] > line.since, ("N3", move, line)
        line.day, line.worker = move.day, worker
    for change in outcome.changes:
        line = present[change.order.row - 300]
        current = line.cells[change.column]
        assert _open(line.day, today), ("N0: zmiana komórki w dniu nieotwartym", change)
        assert current is None or current == line.written.get(change.column), ("N1: nadpisana wartość taty", change, line)
        line.cells[change.column] = line.written[change.column] = change.value
        if change.column is ReportColumn.COMPLETED:
            line.since = arrived[change.value] if line.since is None else max(line.since, arrived[change.value])
    assert len({added.number for added in outcome.added}) == len(outcome.added), ("N2: numer dopisany dwa razy", outcome)
    for added in outcome.added:
        worker, subject = Login(added.worker.lower()), f"Raport {added.day:%d.%m.%Y}"
        assert added.number not in read, ("N2: dopisany numer, który INTERMAX ma w przeczytanym wierszu", added)
        assert _open(added.day, today), ("N0: dopisanie w dniu, który nie jest otwarty", added)
        assert added.completed is not None
        mail, sender, numbers = mails[ascii_lowercase.index(added.completed.removeprefix("opis "))]
        assert (sender, mail.subject) == (worker, subject) and added.number in numbers, ("N2: dopisanie bez maila", added)
        assert all(
            line.since is None or mail.arrived > line.since for line in lines if line.number == added.number
        ), ("N3: dopisanie usuniętego wiersza bez maila świeższego od wpisanego do niego", added)
        cells: dict[ReportColumn, str | None] = {
            ReportColumn.SUCCESSFUL: added.successful,
            ReportColumn.COMPLETED: added.completed,
        }
        written = {column: value for column, value in cells.items() if value is not None}
        line = _Line(added.number, added.day, worker, cells, written, mail.arrived)
        present[len(lines)] = line
        lines.append(line)
    unknown = [problem for problem in outcome.problems if isinstance(problem, UnknownNumber)]
    assert all(ordered_count[problem.number] == 0 for problem in unknown), ("N2: numer zlecenia jako nieznany", unknown)
    assert all((problem.bar is AddBar.IN_INTERMAX) == (problem.number in read) for problem in unknown), (
        "N2: numer z przeczytanego wiersza bez powodu, że INTERMAX go ma",
        unknown,
    )
    again = click(outcome.memory)
    assert (again.changes, again.moves, again.memory) == ((), (), outcome.memory), ("N4: powtórne kliknięcie", again)
    return outcome


def _keeps_invariants(start: _SequenceStart, events: Sequence[tuple[object, ...]]) -> None:
    """Wyrocznie #1367 r4 bez kodu produkcyjnego, z tożsamością wiersza, której Centrum nie zna (``_Line``). Po każdym
    kliknięciu:

    - N0: Centrum zmienia komórki i przenosi tylko zlecenia z dni otwartych, i tylko na dzień otwarty, a dopisuje tylko
      w dniu otwartym, także przy mailu z dniem zamkniętym albo po dziś; dni okresu z Plikiem zbiorczym i dni po dziś
      (``_open``) nie są otwarte, także po nowym dniu;
    - N1: komórka zmienia się tylko, gdy jest pusta albo ma wartość, którą Centrum ostatnio wpisało do tego wiersza, więc
      ręczna wartość taty zostaje, także równa Wpisowi z maila, po „Zostaw moją”, po zmianie Wykonawcy, dnia, usunięciu
      innego wiersza numeru i po wklejeniu drugiego;
    - N2: Centrum przenosi tylko zlecenie, którego numer INTERMAX ma w przeczytanych wierszach (także z dnia po dziś i bez
      zlecenia, przegląd #1374 r3) jeden raz, dopisuje (Zlecenie dopisane z raportu, #1354) tylko numer, którego INTERMAX nie ma w żadnym przeczytanym wierszu
      (także bez zlecenia, przegląd #1374 r2), raz, z maila nadawcy z tym numerem i z dniem z tematu, i nie mówi, że
      numeru nie ma (``UnknownNumber``), gdy INTERMAX ma jego zlecenie, a przy numerze z wiersza bez zlecenia mówi, że
      INTERMAX go ma (``AddBar.IN_INTERMAX``);
    - N3: wiersz przenosi tylko mail nowego Wykonawcy z jego numerem, świeższy niż każdy mail, którego opis Centrum
      wpisało do tego wiersza, a mail, którego opis kliknięcie wpisuje do przenoszonego wiersza, jest świeższy, więc
      stary mail nigdy nie cofa ręcznej zmiany taty (tabela przejść #1358); numer, którego wiersze tata usunął, wraca
      tylko z mailem świeższym niż każdy mail, którego opis Centrum wpisało do któregoś z nich;
    - N4: powtórne kliknięcie bez nowych zdarzeń nic nie zmienia, a pamięć zostaje ta sama.

    Tożsamość wiersza to wiersz w arkuszu, z jednym wyjątkiem z reguły #1367 r4: numer, który ma w INTERMAX jeden
    wiersz po poprzednim kliknięciu i jeden teraz, ma ten sam wiersz, także gdy tata usunął go i wkleił numer na nowo,
    bo Excel nie odróżnia tego od zmiany Wykonawcy albo dnia (``_same_row``)."""

    lines = _lines(start)
    mails: list[tuple[ReportMail, Login, frozenset[str]]] = []
    memory, kept = OwnEntries.EMPTY, frozenset[Kept]()
    last: ReportsOutcome | None = None
    alone: dict[str, int] = {}
    today = DAY
    for event in events:
        match event:
            case ("mail", str(login), date() as day, int(minutes), list(entries)):
                numbers = frozenset(_SEQUENCE_NUMBERS[which] for which, _ in entries)
                arrived = minutes + (today - DAY).days * 24 * 60
                mails.append((_sent(len(mails), login, day, arrived, entries), Login(login), numbers))
            case ("komórka", int(which), ReportColumn() as column, int(value)):
                lines[which % len(lines)].cells[column] = _BY_TATA[column][value % len(_BY_TATA[column])]
            case ("wykonawca", int(which), str(login)):
                lines[which % len(lines)].worker = Login(login)
                lines[which % len(lines)].as_order = True
            case ("dzień", int(which), date() as day):
                lines[which % len(lines)].day = day
            case ("usuwa", int(which)):
                lines[which % len(lines)].present = False
            case ("wkleja", int(which), (date() as day, str(login), int(successful), int(completed))):
                lines.append(_line(_SEQUENCE_NUMBERS[which], (day, login, successful, completed)))
            case ("bez zlecenia", int(which), date() as day):
                lines.append(replace(_line(_SEQUENCE_NUMBERS[which], (day, _LOGINS[0], 0, 0)), as_order=False))
            case ("zostaw",):
                found = () if last is None else last.problems
                kept |= {Kept(shown.key, shown.column, shown.reported) for shown in found if isinstance(shown, ManualDifference)}
            case ("nowy dzień",):
                today = NINTH
            case ("klik",):
                _same_row(lines, alone)
                last = _click_keeping_invariants(lines, mails, start[2], memory, kept, today)
                memory = last.memory
                alone = _single_rows(lines)
            case _:
                raise AssertionError(f"Nieznane zdarzenie ciągu: {event}")


def _single_rows(lines: Sequence[_Line]) -> dict[str, int]:
    """Wiersz każdego numeru, który INTERMAX ma raz."""

    rows: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        if line.present and line.as_order:
            rows.setdefault(line.number, []).append(index)
    return {number: found for number, (found, *more) in rows.items() if not more}


def _same_row(lines: Sequence[_Line], alone: dict[str, int]) -> None:
    """Numer z jednym wierszem po poprzednim kliknięciu (``alone``) i jednym teraz ma ten sam wiersz (reguła #1367 r4):
    gdy tata usunął wiersz i wkleił numer na nowo, nowy wiersz przejmuje wpisy Centrum i ``since`` starego."""

    for number, index in _single_rows(lines).items():
        before = alone.get(number)
        if before is not None and before != index:
            lines[index].written, lines[index].since = dict(lines[before].written), lines[before].since


_JAN, _EWA, _ADAM = "jan.testowy", "ewa.probna", "adam.inny"


@settings(derandomize=True, database=None, deadline=None, max_examples=300)
@given(_SEQUENCE_ROWS, _SEQUENCE_EVENTS)
@example(
    ([(SIXTH, _EWA, 0, 0), (SEVENTH, _JAN, 0, 0)], (DAY, _ADAM, 0, 0), frozenset(READ_DAYS)),
    [
        ("mail", _JAN, SEVENTH, 0, [(0, "tak")]),
        ("klik",),
        ("dzień", 1, DAY),
        ("klik",),
        ("mail", _ADAM, SIXTH, 10, [(0, "tak")]),
        ("klik",),
        ("klik",),
    ],
).via("przegląd #1367 r2 Ważne 1: Przeniesienie drugiego zlecenia numeru kasowało pamięć, a stary mail cofał zmianę taty")
@example(
    ([(SEVENTH, _JAN, 0, 0), (SIXTH, _EWA, 1, 1)], (DAY, _ADAM, 0, 0), frozenset(READ_DAYS)),
    [
        ("mail", _EWA, SIXTH, 0, [(0, "nie")]),
        ("mail", _JAN, SEVENTH, 5, [(0, "tak")]),
        ("klik",),
        ("zostaw",),
        ("usuwa", 0),
        ("klik",),
    ],
).via("przegląd #1367 r3 Ważne 1: wpisy Jana przeszły na zlecenie Ewy, a stary mail nadpisał ręczne „tak” taty")
@example(
    ([(DAY, _JAN, 0, 0), (SEVENTH, _EWA, 1, 1)], (DAY, _ADAM, 0, 0), frozenset(READ_DAYS)),
    [
        ("mail", _EWA, SEVENTH, 0, [(0, "nie")]),
        ("mail", _JAN, DAY, 5, [(0, "tak")]),
        ("klik",),
        ("zostaw",),
        ("dzień", 0, NINTH),
        ("klik",),
    ],
).via("przegląd #1367 r3 Ważne 1: tata przełożył zlecenie Jana na jutro, a stary mail Ewy nadpisał jej „tak”")
@example(
    ([(SEVENTH, _JAN, 0, 0), (NINTH, _JAN, 0, 0)], (DAY, _ADAM, 0, 0), frozenset(READ_DAYS)),
    [("mail", _JAN, DAY, 0, [(0, "tak")]), ("klik",)],
).via("przegląd #1367 r3 Ważne 2: duplikat z jutra był niewidoczny, więc Centrum przeniosło zlecenie z 7.11")
@example(
    ([(SEVENTH, _JAN, 0, 0)], (DAY, _ADAM, 0, 0), frozenset(READ_DAYS)),
    [
        ("mail", _JAN, DAY, 0, [(2, "tak")]),
        ("klik",),
        ("dzień", 2, CLOSED_DAY),
        ("mail", _JAN, DAY, 5, [(2, "nie")]),
        ("klik",),
    ],
).via("przegląd #1374 r4 Ważne 1: dopisane zlecenie, które tata przełożył do okresu z Plikiem zbiorczym, wracało na 8.11")
@example(
    ([(SEVENTH, _JAN, 0, 0)], (DAY, _ADAM, 0, 0), frozenset(READ_DAYS)),
    [
        ("mail", _JAN, DAY, 0, [(2, "tak")]),
        ("klik",),
        ("dzień", 2, NINTH),
        ("mail", _JAN, DAY, 5, [(2, "nie")]),
        ("klik",),
    ],
).via("przegląd #1374 r4 Ważne 1: dopisane zlecenie, które tata przełożył na jutro, wracało na 8.11")
@example(
    ([(SIXTH, _EWA, 0, 0)], (SIXTH, _ADAM, 0, 0), frozenset(_SEQUENCE_DAYS)),
    [
        ("mail", _EWA, SIXTH, 1, [(0, "tak")]),
        ("mail", _EWA, SIXTH, 0, [(0, "tak"), (1, "tak"), (2, "tak")]),
        ("klik",),
    ],
).via("#1374 r5: zlecenie przejęte od Adama zmieniało poprawkę maila Ewy, więc drugie kliknięcie dopisywało literówkę")
@example(
    ([(SEVENTH, _ADAM, 0, 0)], (SIXTH, _ADAM, 0, 0), frozenset(_SEQUENCE_DAYS)),
    [
        ("mail", _ADAM, SEVENTH, 1, [(0, "tak")]),
        ("mail", _ADAM, SEVENTH, 0, [(0, "tak"), (1, "tak"), (2, "tak")]),
        ("klik",),
    ],
).via("#1374 r5: zlecenie przeniesione z 6.11 zmieniało poprawkę maila Adama, więc drugie kliknięcie dopisywało literówkę")
@example(
    ([(DAY, _JAN, 0, 0)], (DAY, _ADAM, 0, 0), frozenset(_SEQUENCE_DAYS)),
    [
        ("usuwa", 1),
        ("mail", _JAN, DAY, 0, [(0, "tak"), (2, "tak"), (1, "tak")]),
        ("mail", _JAN, DAY, 1, [(1, "tak")]),
        ("mail", _JAN, DAY, 2, [(0, "tak")]),
        ("klik",),
    ],
).via("#1374 r5: zlecenie dopisane w kliknięciu zmieniało poprawkę maila Jana, więc drugie kliknięcie dopisywało literówkę")
def test_wlasnosc_centrum_nie_nadpisuje_taty_nie_przenosi_numeru_z_kilku_miejsc_ani_starym_mailem(
    start: _SequenceStart, events: list[tuple[object, ...]]
) -> None:
    """#1367 r4, cel Maksa (ADR 0029 „Ręczna zmiana dalej wygrywa”): dowolny ciąg maili trzech Wykonawców, ręcznych zmian
    komórek, Wykonawcy, dnia (także na jutro) i usunięć wierszy przez tatę, „Zostaw moją”, nowego dnia i kliknięć, przy
    numerze w 1–3 zleceniach w dniach okresu z Plikiem zbiorczym, przed, w i po dziś, spełnia po każdym kliknięciu
    niezmienniki N0–N4 (``_keeps_invariants``; #1367 r5 dodał okres z Plikiem zbiorczym i nowy dzień)."""

    _keeps_invariants(start, events)


_SAME_MAILS = st.lists(
    st.tuples(
        st.sampled_from(_LOGINS),
        st.sampled_from(OPEN_DAYS),
        st.lists(
            st.tuples(st.integers(0, 1), st.sampled_from(["tak", "nie"])), min_size=1, max_size=2, unique_by=lambda entry: entry[0]
        ),
    ),
    min_size=1,
    max_size=6,
)
"""Maile z Wpisami z ``tak``/``nie`` i opisem do numerów ze zleceniem, każdy świeższy od poprzedniego: nadawca, dzień z
tematu i Wpisy. Bez numeru bez zlecenia, bo Zlecenie dopisane z raportu (#1354) jest nieodwracalne: wiersz dopisany
kliknięciem po wcześniejszym mailu zostaje, także gdy późniejszy mail (poprawka, pomylony temat) nie dopisałby go przy
jednym kliknięciu. Że powtórne kliknięcie z dopisaniami nic nie zmienia, sprawdza własność ciągu (N4)."""


@settings(derandomize=True, database=None, deadline=None, max_examples=200)
@given(_SEQUENCE_START, _SAME_MAILS)
@example(
    ([(SEVENTH, _JAN, 0, 0)], (SEVENTH, _JAN, 0, 0), frozenset(READ_DAYS)),
    [(_JAN, DAY, [(0, "tak")]), (_JAN, DAY, [(0, "tak"), (1, "nie")])],
).via("przegląd #1367 r3 Drobne 1: próg pomylonego tematu liczony z dnia sprzed Przeniesień Centrum")
def test_wlasnosc_klikniecie_po_kazdym_mailu_daje_ten_sam_intermax_co_jedno_klikniecie(
    start: _SequenceStart, sent: list[tuple[str, date, list[tuple[int, str]]]]
) -> None:
    """N4 #1367 r4 bez zmian taty: kliknięcie po każdym mailu daje te same miejsca wierszy co jedno kliknięcie po
    wszystkich mailach, bo próg pomylonego tematu i pomylony temat liczą dzień sprzed Przeniesień Centrum, a wiersze
    numerów z jednym zleceniem te same komórki. Numer w kilku zleceniach nie ma pamięci wpisów, więc późniejszy mail
    daje przy nim różnicę zamiast podmiany, a każdy dzień ma inne zlecenia, więc żaden nie przestaje być uporządkowany."""

    orders = [line.order(index) for index, line in enumerate(_lines(start))]
    mails = [_sent(index, login, day, index, entries) for index, (login, day, entries) in enumerate(sent)]
    step, memory = orders, OwnEntries.EMPTY
    for count in range(1, len(mails) + 1):
        outcome = enter_reports(_inputs(mails[:count], step, rollout=SIXTH, ordered=READ_DAYS, memory=memory))
        step, memory = _after(step, outcome), outcome.memory
    once = _after(orders, enter_reports(_inputs(mails, orders, rollout=SIXTH, ordered=READ_DAYS)))
    counted = Counter(order.key.number for order in orders)

    assert [order.key for order in step] == [order.key for order in once]
    cells = [(order.successful, order.completed) for order in step], [(order.successful, order.completed) for order in once]
    single = [index for index, order in enumerate(orders) if counted[order.key.number] == 1]
    assert [cells[0][index] for index in single] == [cells[1][index] for index in single]


def test_numer_przed_dzis_i_po_dzis_nie_przenosi_sie_a_tata_widzi_oba_dni() -> None:
    """Przegląd #1367 r3 Ważne 2: dziś 8.11, a INTERMAX ma numer u Jana 7.11 i 9.11 (zlecenia na jutro tata wkleja dzień
    wcześniej). Raport Jana za 8.11 nie przenosi zlecenia z 7.11, bo numer stoi w INTERMAX dwa razy, także gdy jedno z
    zleceń jest po dziś; tata widzi oba miejsca, a nazajutrz ten sam INTERMAX daje to samo."""

    orders = [_order(OrderRow("Zlecenia", 201), day=SEVENTH), _order(OrderRow("Zlecenia", 202), day=NINTH)]
    mail = _mail(JAN, SUBJECT, "40000001 tak montaż")

    today = enter_reports(_inputs([mail], orders, rollout=SIXTH, ordered=READ_DAYS))
    tomorrow = enter_reports(_inputs([mail], orders, today=NINTH, rollout=SIXTH, ordered=READ_DAYS))

    repeated = RepeatedNumber(JAN_LOGIN, DAY, N1, ((SEVENTH, JAN_LOGIN), (NINTH, JAN_LOGIN)))
    for outcome in (today, tomorrow):
        assert (outcome.changes, outcome.moves) == ((), ())
        assert outcome.problems == (repeated,)
    assert reason(repeated) == (
        "Zlecenie 40000001 jest w INTERMAX więcej niż raz: u jan.testowy z 07.11.2026, u jan.testowy z 09.11.2026. "
        "Centrum nie wie, którego z nich dotyczy Wpis od jan.testowy z 08.11.2026, więc nie zmieniło żadnego z nich przy "
        "tym kliknięciu."
    )


@pytest.mark.parametrize(
    ("text", "notes"),
    [
        pytest.param("40000001 tak montaż", (), id="jeden-niezgodny-wpis"),
        pytest.param(
            "40000001 tak montaż\n40000002 nie brak klienta",
            (SubjectLost(DAY, JAN_LOGIN, OrderNumber("40000002"), SEVENTH),),
            id="pomylony-temat",
        ),
    ],
)
def test_numer_tylko_w_dniu_po_dzis_nie_jest_nieznany_ani_zmieniany_a_tata_widzi_jego_dzien(
    text: str, notes: tuple[SubjectLost, ...]
) -> None:
    """Numer, który INTERMAX ma tylko w jutrzejszym zleceniu, nie jest nieznany (Zlecenie dopisane z raportu by go
    zdublowało, #1374), a Centrum nie zmienia dni po dziś: Wpis go nie przenosi i nie wpisuje, także przy pomylonym
    temacie, a tata widzi w dniu z tematu, w którym dniu INTERMAX ma to zlecenie."""

    orders = [_order(OrderRow("Zlecenia", 201), day=NINTH), _order(OrderRow("Zlecenia", 202), number="40000002", day=SEVENTH)]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], orders, rollout=SIXTH, ordered=READ_DAYS))

    refused = RefusedMove(JAN_LOGIN, DAY, N1, NINTH, NINTH, MoveBar.AFTER_TODAY)
    assert outcome.moves == ()
    assert {change.order for change in outcome.changes} <= {OrderRow("Zlecenia", 202)}
    assert outcome.problems == (refused,)
    assert outcome.notes == notes
    assert reason(refused) == (
        "Wpis zlecenia 40000001 od jan.testowy ma w temacie 08.11.2026, a INTERMAX ma to zlecenie w 09.11.2026. Centrum go "
        "nie przeniosło i nie wpisało, bo dzień 09.11.2026 jeszcze nie nadszedł."
    )
    assert _days(outcome)[DAY, JAN_LOGIN].problems == 1


def test_dwa_maile_z_numerem_tylko_z_jutra_z_pomylonym_tematem_i_bez_daja_tacie_jedna_odmowe() -> None:
    """Jan przysyła Raport za 8.11 z 40000001, który INTERMAX ma tylko jutro, a potem drugi z 40000001 i 40000002 z 7.11
    (pomylony temat). Odmowa z dnia zlecenia nie zależy od tego, dokąd Wpis by je przeniósł, więc tata widzi jedno
    zdanie, w każdej kolejności maili."""

    orders = [_order(OrderRow("Zlecenia", 201), day=NINTH), _order(OrderRow("Zlecenia", 202), number="40000002", day=SEVENTH)]
    single = _mail(JAN, SUBJECT, "40000001 tak montaż", EVENING)
    mistaken = _mail(JAN, SUBJECT, "40000001 tak montaż\n40000002 nie brak klienta", EVENING + timedelta(minutes=5))

    for mails in ([single, mistaken], [mistaken, single]):
        outcome = enter_reports(_inputs(mails, orders, rollout=SIXTH, ordered=READ_DAYS))

        assert [found for found in outcome.problems if isinstance(found, RefusedMove)] == [
            RefusedMove(JAN_LOGIN, DAY, N1, NINTH, NINTH, MoveBar.AFTER_TODAY)
        ]


@pytest.mark.parametrize(
    "tata",
    [
        pytest.param(lambda orders: [order for order in orders if order.row != OrderRow("Zlecenia", 201)], id="usuwa-wiersz-jana"),
        pytest.param(lambda orders: _by_tata(orders, OrderRow("Zlecenia", 201), day=NINTH), id="przeklada-zlecenie-jana-na-jutro"),
    ],
)
def test_wpisy_centrum_w_zleceniu_jana_nie_przechodza_na_zlecenie_ewy_z_reczna_wartoscia(
    tata: Callable[[list[RegisterOrder]], list[RegisterOrder]],
) -> None:
    """Przegląd #1367 r3 Ważne 1: numer u Jana 8.11 (pusty) i u Ewy 7.11 z ręcznym „tak” i opisem taty. Kliknięcie
    wpisuje Raport Jana do jego zlecenia, a stary Raport Ewy daje różnicę, którą tata zostawia („Zostaw moją”). Tata
    usuwa potem wiersz Jana albo przekłada jego zlecenie na jutro: wpisy Centrum z wiersza Jana nie przechodzą na
    zlecenie Ewy, więc stary mail Ewy nie nadpisuje jej ręcznego „tak”, a świeższy mail Ewy z nowym opisem daje tylko
    różnicę opisu (o „nie” tata już zdecydował „Zostaw moją”)."""

    jan = _order(OrderRow("Zlecenia", 201))
    ewa = _order(OrderRow("Zlecenia", 202), day=SEVENTH, worker="Ewa.Probna", successful="tak", completed="montaż taty")
    ewa_old = _mail(EWA, "Raport 07.11.2026", "40000001 nie brak klienta", EVENING - timedelta(minutes=5))
    mails = [ewa_old, _mail(JAN, SUBJECT, "40000001 tak wymiana", EVENING)]
    ewa_fresh = _mail(EWA, "Raport 07.11.2026", "40000001 nie klient nieobecny", EVENING + timedelta(minutes=5))

    orders, first = _clicked(mails, [jan, ewa], OwnEntries.EMPTY)
    kept = frozenset(Kept(found.key, found.column, found.reported) for found in first.problems if isinstance(found, ManualDifference))
    changed = tata(orders)
    second = enter_reports(_inputs(mails, changed, rollout=SIXTH, ordered=READ_DAYS, memory=first.memory, kept=kept))
    third = enter_reports(_inputs([*mails, ewa_fresh], changed, rollout=SIXTH, ordered=READ_DAYS, memory=second.memory, kept=kept))

    assert [change.order for change in first.changes] == [jan.row, jan.row]
    assert len(kept) == 2
    for later in (second, third):
        assert (later.changes, later.moves) == ((), ())
    assert not [found for found in second.problems if isinstance(found, ManualDifference)]
    assert [(found.column, found.manual) for found in third.problems if isinstance(found, ManualDifference)] == [
        (ReportColumn.COMPLETED, "montaż taty")
    ]


@pytest.mark.parametrize("pasted_first", [False, True], ids=["wklejony-pod-spodem", "wklejony-nad"])
def test_wpisy_centrum_nie_przechodza_na_wklejony_drugi_wiersz_numeru_z_reczna_wartoscia(pasted_first: bool) -> None:
    """Centrum wpisało Raport Jana do jedynego zlecenia numeru (Jan 8.11). Tata wkleja ten numer drugi raz, u Ewy w 7.11,
    z ręcznym „tak” i opisem równym Wpisowi Jana. Numer ma teraz dwa wiersze, a Excel nie mówi, który ma wpisy Centrum,
    więc pamięć wpisów numeru przepada: Raport Ewy za 7.11 z innym opisem nie nadpisuje jej ręcznych wartości, w którym
    miejscu arkusza by nie stał wiersz, tylko daje różnicę."""

    jan = _order(OrderRow("Zlecenia", 201))
    jan_mail = _mail(JAN, SUBJECT, "40000001 tak wymiana", EVENING)
    ewa_mail = _mail(EWA, "Raport 07.11.2026", "40000001 nie brak klienta", EVENING + timedelta(minutes=5))
    orders, first = _clicked([jan_mail], [jan], OwnEntries.EMPTY)
    pasted = _order(OrderRow("Zlecenia", 202), day=SEVENTH, worker="Ewa.Probna", successful="tak", completed="wymiana")
    both = [pasted, *orders] if pasted_first else [*orders, pasted]

    second = enter_reports(_inputs([jan_mail, ewa_mail], both, rollout=SIXTH, ordered=OPEN_DAYS, memory=first.memory))

    assert {entry.key for entry in first.memory.entries} == {_key()}
    assert (second.changes, second.moves) == ((), ())
    ewa_key = _key(day=SEVENTH, worker="ewa.probna")
    assert set(second.problems) == {
        ManualDifference(ewa_key, ReportColumn.SUCCESSFUL, "tak", "nie"),
        ManualDifference(ewa_key, ReportColumn.COMPLETED, "wymiana", "brak klienta"),
    }


def test_wpisy_jana_nie_przechodza_nazajutrz_na_reczne_tak_ewy_w_zleceniu_ktore_bylo_jutro() -> None:
    """Przegląd #1367 r4 Drobne 1: dziś 8.11, a INTERMAX ma 40000001 u Jana 8.11 i u Ewy 9.11 (zlecenie na jutro) z
    ręcznym „tak” i opisem taty. Raport Jana wpisuje się do jego zlecenia, ale numer ma dwa zlecenia w odczytanych dniach,
    także jutro, więc Centrum nie pamięta wpisów Jana. Tata usuwa wiersz Jana. Nazajutrz (dziś 9.11) Raport Ewy za 9.11
    „nie” nie nadpisuje jej „tak”: obie komórki są ręczne i zostają z różnicą."""

    jan = _order(OrderRow("Zlecenia", 201))
    ewa = _order(OrderRow("Zlecenia", 202), day=NINTH, worker="Ewa.Probna", successful="tak", completed="montaż taty")
    jan_mail = _mail(JAN, SUBJECT, "40000001 tak wymiana", EVENING)
    ewa_mail = _mail(EWA, "Raport 09.11.2026", "40000001 nie brak klienta", EVENING + timedelta(days=1))

    first = enter_reports(_inputs([jan_mail], [jan, ewa], rollout=SIXTH, ordered=READ_DAYS))
    second = enter_reports(
        _inputs([jan_mail, ewa_mail], [ewa], today=NINTH, rollout=SIXTH, ordered=READ_DAYS, memory=first.memory)
    )

    assert [change.order for change in first.changes] == [jan.row, jan.row]
    assert first.memory.entries == frozenset()
    assert (second.changes, second.moves) == ((), ())
    ewa_key = _key(day=NINTH, worker="ewa.probna")
    assert set(second.problems) == {
        ManualDifference(ewa_key, ReportColumn.SUCCESSFUL, "tak", "nie"),
        ManualDifference(ewa_key, ReportColumn.COMPLETED, "montaż taty", "brak klienta"),
    }


def test_odmowa_przeniesienia_najpozniejszego_maila_nie_oddaje_zlecenia_starszemu_mailowi() -> None:
    """Własność N4 #1367 r4: zlecenie 40000001 jest jedynym w 6.11, a 40000002 stoi u Jana w 7.11. Raport Jana za 7.11
    z 40000002 (18:00) jest starszy od Raportu Adama za 6.11 z 40000002 bez „tak”/„nie” (18:10), więc zwycięski Wpis
    40000002 nic nie zmienia. Raport Jana za 7.11 z 40000001 przenosi to zlecenie z 6.11, więc dzień 6.11 nie jest już
    Dniem uporządkowanym. Powtórne kliknięcie bez nowych maili odmawia Przeniesienia do 6.11 Wpisowi Adama, który dalej
    jest najpóźniejszy, więc starszy Wpis Jana nie wraca do komórek 40000002 i INTERMAX się nie zmienia."""

    moved, other = _numbered(1, SIXTH), _numbered(2, SEVENTH)
    mails = [
        _mail(JAN, "Raport 07.11.2026", "40000002 tak montaż", EVENING),
        _mail(JAN, "Raport 07.11.2026", "40000001 tak wymiana", EVENING + timedelta(minutes=5)),
        _mail(ADAM, "Raport 06.11.2026", "40000002 wymiana", EVENING + timedelta(minutes=10)),
    ]

    first = enter_reports(_inputs(mails, [moved, other], rollout=SIXTH, ordered=(SIXTH, SEVENTH)))
    orders = _after([moved, other], first)
    second = enter_reports(_inputs(mails, orders, rollout=SIXTH, ordered=(SEVENTH,), memory=first.memory))

    assert first.moves == (OrderMove(moved.row, SEVENTH, "Jan.Testowy"),)
    assert {change.order for change in first.changes} == {moved.row}
    assert MissingVerdict(Login("adam.inny"), SIXTH, OrderNumber("40000002"), VerdictFault.MISSING) in first.problems
    assert (second.changes, second.moves) == ((), ())
    assert RefusedMove(Login("adam.inny"), SIXTH, OrderNumber("40000002"), SEVENTH, SIXTH, MoveBar.NOT_ORDERED) in second.problems


def test_odmowa_przy_pomylonym_temacie_po_przeniesieniu_centrum_podaje_dzien_na_ktory_wpis_przenioslby_zlecenie() -> None:
    """Przegląd #1367 r4 Drobne 3: 40000001 jest jedynym zleceniem w 6.11, a Raport Jana za 7.11 przenosi je na 7.11, więc
    6.11 przestaje być Dniem uporządkowanym. Raport Ewy za 8.11 z 40000001 i 40000002 (zlecenie Ewy z 7.11) ma pomylony
    temat, a pomylony temat liczy dzień zlecenia sprzed Przeniesień Centrum, więc Wpis przeniósłby 40000001 do Ewy w
    6.11. Odmowa mówi tacie o 6.11, a nie o dniu z tematu 8.11, który jest uporządkowany."""

    moved, ewa = _numbered(1, SIXTH), _order(OrderRow("Zlecenia", 202), number="40000002", day=SEVENTH, worker="Ewa.Probna")
    jan_mail = _mail(JAN, "Raport 07.11.2026", "40000001 tak montaż", EVENING)
    ewa_mail = _mail(EWA, SUBJECT, "40000001 tak wymiana\n40000002 tak montaż", EVENING + timedelta(minutes=10))
    first = enter_reports(_inputs([jan_mail], [moved, ewa], rollout=SIXTH, ordered=OPEN_DAYS))

    second = enter_reports(
        _inputs([jan_mail, ewa_mail], _after([moved, ewa], first), rollout=SIXTH, ordered=(SEVENTH, DAY), memory=first.memory)
    )

    refused = RefusedMove(EWA_LOGIN, DAY, N1, SEVENTH, SIXTH, MoveBar.NOT_ORDERED)
    assert first.moves == (OrderMove(moved.row, SEVENTH, "Jan.Testowy"),)
    assert second.moves == ()
    assert refused in second.problems
    assert reason(refused) == (
        "Wpis zlecenia 40000001 od ewa.probna ma w temacie 08.11.2026, a INTERMAX ma to zlecenie w 07.11.2026. Centrum go "
        "nie przeniosło i nie wpisało, bo dzień 06.11.2026 nie jest jeszcze uporządkowany w INTERMAX."
    )


@pytest.mark.parametrize(("sixth", "seventh"), [pytest.param(10, 30, id="blokuje-pozniejszy-dzien"), pytest.param(30, 10, id="blokuje-wczesniejszy-dzien")])
def test_przeniesienie_jedynego_zlecenia_czeka_na_kazda_pamiec_numeru_w_kazdej_kolejnosci(sixth: int, seventh: int) -> None:
    """Pamięć numeru zapisana przed #1367 r4 ma Przeniesienie albo Wpis Centrum pod 6.11 i pod 7.11 (Wpisy do dwóch
    zleceń numeru, z których tata zostawił jedno, u Jana 8.11). Wpis Adama z 18:25 za 8.11 nie przenosi zlecenia, bo
    jest starszy od jednej z pamięci, którakolwiek to jest, a Wpis Adama z 18:45 przenosi."""

    memory = OwnEntries(
        frozenset(),
        frozenset(
            {
                OwnMove(N1, SIXTH, EWA_LOGIN, SIXTH, EWA_LOGIN, "Ewa.Probna", EVENING + timedelta(minutes=sixth)),
                OwnMove(N1, SEVENTH, JAN_LOGIN, SEVENTH, JAN_LOGIN, "Jan.Testowy", EVENING + timedelta(minutes=seventh)),
            }
        ),
    )
    older = _mail(ADAM, SUBJECT, "40000001 tak wymiana", EVENING + timedelta(minutes=20))
    fresher = _mail(ADAM, SUBJECT, "40000001 tak wymiana routera", EVENING + timedelta(minutes=40))

    blocked = enter_reports(_inputs([older], [_order()], rollout=SIXTH, ordered=OPEN_DAYS, memory=memory))
    moved = enter_reports(_inputs([older, fresher], [_order()], rollout=SIXTH, ordered=OPEN_DAYS, memory=memory))

    assert (blocked.moves, blocked.changes, blocked.problems) == ((), (), ())
    assert moved.moves == (OrderMove(ROW, DAY, "adam.inny"),)


def test_powtorne_klikniecie_po_przeniesieniu_na_inny_dzien_nic_nie_zmienia_a_informacje_zostaja() -> None:
    mails = [_mail(JAN, SUBJECT, "40000001 tak montaż")]
    orders = [_numbered(1, SEVENTH)]
    first = enter_reports(_inputs(mails, orders, rollout=SIXTH, ordered=OPEN_DAYS))

    second = enter_reports(_inputs(mails, _after(orders, first), rollout=SIXTH, ordered=OPEN_DAYS, memory=first.memory))

    assert (second.changes, second.moves, second.problems) == ((), (), ())
    assert second.notes == first.notes != ()
    assert second.memory == first.memory


@pytest.mark.parametrize("day", [SEVENTH, SIXTH], ids=["z-powrotem", "na-trzeci-dzien"])
def test_reczne_przeniesienie_po_zmianie_centrum_wygrywa_bez_problemu(day: date) -> None:
    """US 15: tata przeniósł zlecenie z powrotem na 7.11 albo na 6.11 po Przeniesieniu Centrum na 8.11. Kolejne
    kliknięcie z tym samym mailem zostawia je tam bez zmian, problemu i informacji, a pamięć pamięta Przeniesienie
    dalej i zmianę taty (``overridden``, wiersz R3 tabeli przejść #1358 z miejscem = Wykonawca i dzień)."""

    mails = [_mail(JAN, SUBJECT, "40000001 tak montaż")]
    orders = [_numbered(1, SEVENTH)]
    first = enter_reports(_inputs(mails, orders, rollout=SIXTH, ordered=OPEN_DAYS))
    [after] = _after(orders, first)
    by_tata = [_order(after.row, number=after.key.number, day=day, successful=after.successful, completed=after.completed)]

    second = enter_reports(_inputs(mails, by_tata, rollout=SIXTH, ordered=OPEN_DAYS, memory=first.memory))

    assert (second.changes, second.moves, second.problems, second.notes) == ((), (), (), ())
    assert second.memory.moves == {replace(move, overridden=True) for move in first.memory.moves}


def test_reczna_zmiana_dnia_po_przyjetym_wpisie_zostaje_przy_starym_mailu_a_swiezszy_mail_przenosi() -> None:
    """ADR 0029 „Ręczna zmiana dalej wygrywa” z regułą #1347 r2 (``OwnMove.since``): Centrum przyjęło Wpis Jana do jego
    zlecenia z 7.11, a tata przeniósł potem zlecenie na 6.11. Ten sam mail za 7.11 przy następnym kliknięciu nie cofa
    zmiany taty, a świeższy Raport Jana za 7.11 przenosi zlecenie z powrotem na 7.11."""

    mail = _mail(JAN, "Raport 07.11.2026", "40000001 tak montaż")
    orders = [_numbered(1, SEVENTH)]
    first = enter_reports(_inputs([mail], orders, rollout=SIXTH, ordered=OPEN_DAYS))
    [after] = _after(orders, first)
    by_tata = [_order(after.row, number=after.key.number, day=SIXTH, successful=after.successful, completed=after.completed)]
    fresher = _mail(JAN, "Raport 07.11.2026", "40000001 nie klient nieobecny", EVENING + timedelta(minutes=5))

    old_mail = enter_reports(_inputs([mail], by_tata, rollout=SIXTH, ordered=OPEN_DAYS, memory=first.memory))
    new_mail = enter_reports(_inputs([mail, fresher], by_tata, rollout=SIXTH, ordered=OPEN_DAYS, memory=first.memory))

    assert first.moves == ()
    assert (old_mail.changes, old_mail.moves, old_mail.problems, old_mail.notes) == ((), (), (), ())
    assert new_mail.moves == (OrderMove(after.row, SEVENTH, "Jan.Testowy"),)
    assert [change.value for change in new_mail.changes] == ["nie", "klient nieobecny"]


def test_przeniesienia_na_inny_dzien_daja_ten_sam_wynik_w_kazdej_kolejnosci_maili_i_w_kolejnych_kliknieciach() -> None:
    """Własność kolejności maili (#1350): raport Jana za 8.11 przenosi zlecenie z 7.11, późniejszy raport Jana za 6.11 z
    dwoma niezgodnymi Wpisami (pomylony temat) oddaje je dniowi 7.11, a najpóźniejszy raport Ewy za 7.11 przejmuje je.
    Jedno kliknięcie w każdej kolejności maili i kolejne kliknięcia po każdym mailu dają po każdym kliknięciu ten sam
    INTERMAX, bo próg i pomylony temat liczą dzień zlecenia sprzed Przeniesień Centrum."""

    moved, other = _numbered(1, SEVENTH), _numbered(2)
    first = _mail(JAN, SUBJECT, "40000001 tak a", EVENING)
    mistaken = _mail(JAN, "Raport 06.11.2026", "40000001 nie b\n40000002 tak c", EVENING + timedelta(minutes=10))
    taken = _mail(EWA, "Raport 07.11.2026", "40000001 tak d", EVENING + timedelta(minutes=20))
    orders = [moved, other]

    def state(found: Sequence[RegisterOrder]) -> list[tuple[OrderKey, str | None, str | None]]:
        return sorted((order.key, order.successful, order.completed) for order in found)

    clicks: list[RegisterOrder] = orders
    memory = OwnEntries.EMPTY
    for index in range(1, 4):
        prefix = [first, mistaken, taken][:index]
        outcome = enter_reports(_inputs(prefix, clicks, rollout=SIXTH, ordered=OPEN_DAYS, memory=memory))
        clicks, memory = _after(clicks, outcome), outcome.memory
        once = enter_reports(_inputs(prefix, orders, rollout=SIXTH, ordered=OPEN_DAYS))

        assert state(clicks) == state(_after(orders, once)), index

    expected = [
        (_key("40000001", SEVENTH, "ewa.probna"), "tak", "d"),
        (_key("40000002"), "tak", "c"),
    ]
    assert state(clicks) == expected
    for mails in itertools.permutations([first, mistaken, taken]):
        once = enter_reports(_inputs(mails, orders, rollout=SIXTH, ordered=OPEN_DAYS))

        assert state(_after(orders, once)) == expected
        assert once.notes == outcome.notes


def test_zlecenie_z_dnia_zamknietego_robi_numer_niejednoznacznym_jak_kazde_odczytane() -> None:
    """Numer, który INTERMAX ma w dniu okresu z Plikiem zbiorczym i w dniu otwartym, stoi w INTERMAX dwa razy (#1367 r4:
    o liczbie zleceń numeru mówi każdy odczytany dzień, a okno mówi tylko, gdzie wolno pisać). Raport Jana za 8.11 nie
    przenosi więc zlecenia z 7.11, a tata widzi oba miejsca numeru."""

    closed = date(2026, 11, 2)
    orders = [_order(day=closed), _order(OrderRow("Zlecenia", 121), day=date(2026, 11, 7))]

    outcome = enter_reports(
        _inputs(
            [_mail(JAN, SUBJECT, TEXT)],
            orders,
            rollout=date(2026, 10, 30),
            closed=(period_of(closed).token,),
            ordered=[DAY],
        )
    )

    assert (outcome.moves, outcome.changes) == ((), ())
    assert outcome.problems == (RepeatedNumber(JAN_LOGIN, DAY, N1, ((closed, JAN_LOGIN), (date(2026, 11, 7), JAN_LOGIN))),)


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
    """Problemy dopasowania i nieznanego nadawcy, w tym dwa obce adresy z jednym Message-ID; problemy rozpoznania ma
    ``test_wlasnosc_permutacja_maili_z_problemami_rozpoznania_daje_ten_sam_wynik``."""

    ewa = _mail(EWA, "Raport 07.11.2026", "40000009 tak montaż", EVENING + timedelta(minutes=1))
    first = _mail("obcy@przyklad.invalid", SUBJECT, TEXT, EVENING + timedelta(minutes=2), "<1@obcy.invalid>")
    second = _mail("inny@przyklad.invalid", SUBJECT, TEXT, EVENING + timedelta(minutes=3), "<1@obcy.invalid>")
    twice = [
        _mail(JAN, SUBJECT, "30000077 tak a", EVENING + timedelta(minutes=4)),
        _mail(JAN, SUBJECT, "30000077 tak b", EVENING + timedelta(minutes=5)),
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
        UnknownNumber(Login("ewa.probna"), date(2026, 11, 7), OrderNumber("40000009"), AddBar.NOT_ORDERED),
        UnknownSender(second.id, second.sender, DAY),
        UnknownSender(first.id, first.sender, DAY),
        UnknownNumber(Login("jan.testowy"), DAY, OrderNumber("30000077"), AddBar.NOT_ORDERED),
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
    """Raport z dniem w okresie z Plikiem zbiorczym rdzeń czyta (``mails``), bo jego niezgodne Wpisy mówią o dniach
    otwartych (ADR 0029), ale Wpis do zlecenia z dnia zamkniętego niczego nie zmienia i nie daje problemu."""

    mail = _mail(JAN, f"Raport {day:%d.%m.%Y}", TEXT)

    outcome = enter_reports(_inputs([mail], [_order(day=day)], rollout=rollout, closed=closed))

    assert replace(outcome, mails=()) == ReportsOutcome((), (), (), (), OwnEntries.EMPTY, (), (), ())
    assert [type(read) for read in outcome.mails] == ([ReadReport] if closed else [])


def test_raport_z_ostatniego_dnia_poprzedniego_okresu_wpisuje_sie_dopoki_okres_nie_ma_pliku_zbiorczego() -> None:
    """US 12: Raport z poniedziałku 9.11, ostatniego dnia okresu ``03_09_11_2026``, przychodzi we wtorek 10.11, już w
    nowym okresie."""

    monday, tuesday = date(2026, 11, 9), date(2026, 11, 10)
    mails = [_mail(JAN, "Raport 09.11.2026", TEXT, datetime(2026, 11, 10, 7, 40, tzinfo=TAPA))]
    orders = [_order(day=monday)]

    still_open = enter_reports(_inputs(mails, orders, today=tuesday, rollout=date(2026, 11, 4)))
    closed = enter_reports(
        _inputs(mails, orders, today=tuesday, rollout=date(2026, 11, 4), closed=(period_of(monday).token,))
    )

    assert [change.column for change in still_open.changes] == [ReportColumn.SUCCESSFUL, ReportColumn.COMPLETED]
    assert replace(closed, mails=()) == ReportsOutcome((), (), (), (), OwnEntries.EMPTY, (), (), ())


TUESDAY = date(2026, 11, 10)
OCTOBER_PERIOD, NOVEMBER_PERIOD, TODAY_PERIOD = "27_02_11_2026", "03_09_11_2026", "10_16_11_2026"


@pytest.mark.parametrize(
    ("rollout", "periods"),
    [
        pytest.param(None, (TODAY_PERIOD,), id="przed-pierwszym-kliknieciem-okres-dzis"),
        pytest.param(TUESDAY, (TODAY_PERIOD,), id="wdrozenie-dzis"),
        pytest.param(date(2026, 11, 9), (NOVEMBER_PERIOD, TODAY_PERIOD), id="wdrozenie-w-ostatni-dzien-okresu"),
        pytest.param(date(2026, 10, 30), (OCTOBER_PERIOD, NOVEMBER_PERIOD, TODAY_PERIOD), id="trzy-okresy"),
    ],
)
def test_okresy_do_sprawdzenia_pliku_zbiorczego_to_okresy_od_dnia_wdrozenia_do_dzis(
    rollout: date | None, periods: tuple[str, ...]
) -> None:
    assert tuple(period.token for period in Window.periods(TUESDAY, rollout)) == periods


@pytest.mark.parametrize(
    ("rollout", "closed", "first"),
    [
        pytest.param(date(2026, 10, 30), (), date(2026, 10, 30), id="bez-pliku-zbiorczego-od-dnia-wdrozenia"),
        pytest.param(date(2026, 10, 30), (OCTOBER_PERIOD,), date(2026, 11, 3), id="od-okresu-po-zamknietym"),
        pytest.param(
            date(2026, 10, 30), (OCTOBER_PERIOD, NOVEMBER_PERIOD), TUESDAY, id="od-dzis-gdy-poprzednie-zamkniete"
        ),
        pytest.param(date(2026, 11, 5), (OCTOBER_PERIOD,), date(2026, 11, 5), id="nie-przed-dniem-wdrozenia"),
    ],
)
def test_pierwszy_dzien_okna_to_pierwszy_dzien_otwarty_od_dnia_wdrozenia(
    rollout: date, closed: tuple[str, ...], first: date
) -> None:
    """Od pierwszego dnia okna proces czyta skrzynkę i INTERMAX: dni okresów z Plikiem zbiorczym przed nim nic nie
    zmienią, więc ich nie czyta."""

    assert Window.of(TUESDAY, rollout, closed).first == first


def test_okno_bez_dnia_otwartego_czyta_tylko_dzis() -> None:
    """Okres dziś też ma Plik zbiorczy: żaden dzień nie jest otwarty, więc skrzynka i INTERMAX tylko od dziś."""

    thursday = date(2026, 11, 12)

    assert Window.of(thursday, date(2026, 10, 30), (OCTOBER_PERIOD, NOVEMBER_PERIOD, TODAY_PERIOD)).first == thursday


def test_pamiec_zostawia_dawny_wpis_tylko_gdy_komorka_zlecenia_ma_dalej_wpisana_wartosc() -> None:
    kept = OwnEntry(_key("40000002"), ReportColumn.SUCCESSFUL, "tak")
    changed_by_tata = OwnEntry(_key("40000003"), ReportColumn.SUCCESSFUL, "tak")
    outside = OwnEntry(_key("40000004", date(2026, 11, 1)), ReportColumn.SUCCESSFUL, "tak")
    orders = [
        _order(OrderRow("Zlecenia", 121), number="40000002", successful="tak"),
        _order(OrderRow("Zlecenia", 122), number="40000003", successful="nie"),
    ]

    outcome = enter_reports(_inputs([], orders, memory=OwnEntries(frozenset({kept, changed_by_tata, outside}))))

    assert outcome.memory.entries == (frozenset({kept}))


def test_pamiec_z_dwoma_wpisami_jednej_komorki_zlecenia_jest_odrzucona() -> None:
    entries = {OwnEntry(_key(), ReportColumn.SUCCESSFUL, "tak"), OwnEntry(_key(), ReportColumn.SUCCESSFUL, "nie")}

    with pytest.raises(ValueError, match="dwa wpisy jednej komórki"):
        OwnEntries(frozenset(entries))


# --- Poprawki od Wykonawcy i pierwszeństwo ręcznej wartości (#1230, US 33–37, 40) ---

# Poprawka Jana: późniejszy mail z innym ``tak``/``nie`` i opisem niż wcześniejszy Wpis. W kolumnie obok stoi już wartość
# z poprawki, więc każdy przypadek dotyczy tylko jednej komórki.
CORRECTION = "40000001 nie klient nieobecny"
CORRECTED = {ReportColumn.SUCCESSFUL: "nie", ReportColumn.COMPLETED: "klient nieobecny"}
EARLIER = {ReportColumn.SUCCESSFUL: "tak", ReportColumn.COMPLETED: "wymiana routera"}
MANUAL = {ReportColumn.SUCCESSFUL: "tak, do sprawdzenia", ReportColumn.COMPLETED: "wymiana gniazda, klient prosi o fakturę"}


def _correction_order(column: ReportColumn, current: str | None) -> RegisterOrder:
    cells = {**CORRECTED, column: current}
    return _order(successful=cells[ReportColumn.SUCCESSFUL], completed=cells[ReportColumn.COMPLETED])


@pytest.mark.parametrize("column", list(ReportColumn), ids=lambda column: column.name)
@pytest.mark.parametrize(
    ("current", "remembered", "kept", "changed", "different", "remembers"),
    [
        pytest.param(None, None, None, True, False, True, id="pusta-dostaje-wpis"),
        pytest.param("corrected", None, None, False, False, False, id="reczna-rowna-wpisowi-bez-pamieci"),
        pytest.param("corrected-upper", None, None, False, False, False, id="reczna-rowna-wpisowi-inna-wielkoscia-liter"),
        pytest.param("corrected", "corrected", None, False, False, True, id="wlasny-wpis-rowny-poprawce-zostaje-w-pamieci"),
        pytest.param("earlier", "earlier", None, True, False, True, id="nietkniety-wlasny-wpis-dostaje-poprawke"),
        pytest.param("earlier", None, None, False, True, False, id="reczna-rowna-wczesniejszemu-wpisowi-bez-pamieci"),
        pytest.param("manual", None, None, False, True, False, id="reczna-wartosc-zostaje-z-roznica"),
        pytest.param("manual", "earlier", None, False, True, False, id="wlasny-wpis-zmieniony-recznie-zostaje-z-roznica"),
        pytest.param(
            "earlier-upper", "earlier", None, False, True, False, id="wlasny-wpis-zmieniony-recznie-tylko-wielkoscia-liter-zostaje-z-roznica"
        ),
        pytest.param("manual", None, "corrected", False, False, False, id="zostaw-moja-przy-tej-tresci-bez-roznicy"),
        pytest.param("manual", None, "earlier", False, True, False, id="zostaw-moja-przy-innej-tresci-z-roznica"),
    ],
)
def test_regula_komorki_dla_kazdej_kolumny_osobno(
    column: ReportColumn,
    current: str | None,
    remembered: str | None,
    kept: str | None,
    changed: bool,
    different: bool,
    remembers: bool,
) -> None:
    """Reguła komórki z projektu #1227 (§2.1): pusta dostaje Wpis, równa Wpisowi zostaje, własny nietknięty wpis
    dostaje poprawkę, a inna wartość zostaje z różnicą dla taty, chyba że tata kliknął „Zostaw moją” przy tej treści
    Wpisu. Własny wpis zmieniony przez tatę choćby wielkością liter jest już ręczny. Ręczna wartość równa Wpisowi do
    pamięci nie trafia (GLOSSARY „Wpisanie raportów”, US 33–36, 38–39)."""

    values = {
        "corrected": CORRECTED[column],
        "corrected-upper": CORRECTED[column].upper(),
        "earlier": EARLIER[column],
        "earlier-upper": EARLIER[column].upper(),
        "manual": MANUAL[column],
    }
    cell = None if current is None else values[current]
    memory = () if remembered is None else (OwnEntry(_key(), column, values[remembered]),)
    decisions = frozenset(() if kept is None else (Kept(_key(), column, values[kept]),))
    mails = [_mail(JAN, SUBJECT, TEXT), _mail(JAN, SUBJECT, CORRECTION, EVENING + timedelta(hours=1))]

    outcome = enter_reports(
        _inputs(mails, [_correction_order(column, cell)], memory=OwnEntries(frozenset(memory)), kept=decisions)
    )

    assert outcome.changes == ((CellChange(ROW, column, CORRECTED[column]),) if changed else ())
    assert outcome.problems == ((ManualDifference(_key(), column, values[current or ""], CORRECTED[column]),) if different else ())
    remembered_after = (OwnEntry(_key(), column, CORRECTED[column]),) if remembers else ()
    assert outcome.memory.entries == (frozenset(remembered_after))


@pytest.mark.parametrize("reverse", [False, True])
def test_poprawka_wykonawcy_w_drugim_kliknieciu_podmienia_nietkniety_wlasny_wpis_najpozniejszym_mailem(
    reverse: bool,
) -> None:
    """US 36–37: drugi mail Jana z poprawką, a potem trzeci z jeszcze jedną: wygrywa najpóźniejszy, w każdej kolejności
    maili ze skrzynki, a pamięć ma po kliknięciu jego wartości."""

    first_mail = _mail(JAN, SUBJECT, TEXT)
    later = [
        _mail(JAN, SUBJECT, "40000001 tak wymiana routera i gniazda", EVENING + timedelta(minutes=20)),
        _mail(JAN, SUBJECT, CORRECTION, EVENING + timedelta(minutes=40)),
    ]
    mails = [first_mail, *later]

    first = enter_reports(_inputs([first_mail], [_order()]))
    second = enter_reports(
        _inputs(mails[::-1] if reverse else mails, [_order(successful="tak", completed="wymiana routera")], memory=first.memory)
    )

    assert second.changes == (
        CellChange(ROW, ReportColumn.SUCCESSFUL, "nie"),
        CellChange(ROW, ReportColumn.COMPLETED, "klient nieobecny"),
    )
    assert second.problems == ()
    assert second.memory.entries == (frozenset(OwnEntry(_key(), column, value) for column, value in CORRECTED.items()))


def test_reczna_zmiana_miedzy_kliknieciami_wygrywa_z_poprawka_a_kolumna_obok_dostaje_poprawke() -> None:
    """Kryterium #1230: tata zmienia ``SKUTECZNE`` wpisane z raportu między kliknięciami, a Jan przysyła poprawkę. Ręczne
    ``SKUTECZNE`` zostaje z różnicą, a nietknięty własny opis dostaje poprawkę. Różnica nie znika w trzecim kliknięciu."""

    correction = _mail(JAN, SUBJECT, CORRECTION, EVENING + timedelta(hours=1))
    first = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], [_order()]))
    by_tata = _order(successful="nie wiem", completed="wymiana routera")

    second = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT), correction], [by_tata], memory=first.memory))
    corrected = _order(successful="nie wiem", completed="klient nieobecny")
    third = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT), correction], [corrected], memory=second.memory))

    difference = ManualDifference(_key(), ReportColumn.SUCCESSFUL, "nie wiem", "nie")
    assert second.changes == (CellChange(ROW, ReportColumn.COMPLETED, "klient nieobecny"),)
    assert second.problems == (difference,)
    assert second.memory.entries == (frozenset({OwnEntry(_key(), ReportColumn.COMPLETED, "klient nieobecny")}))
    assert (third.changes, third.problems, third.memory) == ((), (difference,), second.memory)


def test_poprawka_nie_rusza_pamieci_innego_zlecenia_ani_wpisu_wczesniejszego_maila_w_innym_zleceniu() -> None:
    """Poprawka jednego zlecenia z drugiego maila nie cofa Wpisu innego zlecenia z pierwszego maila: oba zostają w
    pamięci."""

    other = OrderRow("Zlecenia", 121)
    first_mail = _mail(JAN, SUBJECT, "40000001 tak wymiana routera 40000002 tak montaż")
    orders = [_order(), _order(other, number="40000002")]
    first = enter_reports(_inputs([first_mail], orders))
    entered = [
        _order(successful="tak", completed="wymiana routera"),
        _order(other, number="40000002", successful="tak", completed="montaż"),
    ]

    second = enter_reports(
        _inputs([first_mail, _mail(JAN, SUBJECT, CORRECTION, EVENING + timedelta(hours=1))], entered, memory=first.memory)
    )

    assert second.changes == (
        CellChange(ROW, ReportColumn.SUCCESSFUL, "nie"),
        CellChange(ROW, ReportColumn.COMPLETED, "klient nieobecny"),
    )
    assert second.memory.entries == (
        frozenset(
            {
                *(OwnEntry(_key(), column, value) for column, value in CORRECTED.items()),
                OwnEntry(_key("40000002"), ReportColumn.SUCCESSFUL, "tak"),
                OwnEntry(_key("40000002"), ReportColumn.COMPLETED, "montaż"),
            }
        )
    )


LATER = EVENING + timedelta(hours=1)
NEXT_DAY = date(2026, 11, 9)
# Raport Jana z 8.11 z literówką w drugim numerze, ten sam raport wysłany jeszcze raz z dobrym numerem, a obok Raport
# z samym zleceniem 40000002 (kolejny raport, nie poprawka) i mail z tematem bez roku.
TYPO = "40000001 tak wymiana routera 40000092 tak montaż"
RESENT = "40000001 tak wymiana routera 40000002 tak montaż"
NO_YEAR = "Raport 08.11"
JAN_ORDERS = [
    _order(),
    _order(OrderRow("Zlecenia", 121), number="40000002"),
    _order(OrderRow("Zlecenia", 122), number="40000003", day=NEXT_DAY),
    _order(OrderRow("Zlecenia", 123), number="40000004", worker="Ewa.Probna"),
    _order(OrderRow("Zlecenia", 124), number="40000004", worker="Ewa.Probna"),
]
JAN_TYPO = UnknownNumber(Login("jan.testowy"), DAY, OrderNumber("40000092"), AddBar.NOT_ORDERED)


def _no_year(arrived: datetime = EVENING, text: str = TEXT) -> UnreadableSubject:
    return UnreadableSubject(_mail(JAN, NO_YEAR, text, arrived).id, Login("jan.testowy"), arrived, SubjectFault.NO_YEAR)


@pytest.mark.parametrize(
    ("wrong", "fixed", "closed", "problem"),
    [
        pytest.param(
            _mail(JAN, SUBJECT, TYPO), _mail(JAN, SUBJECT, RESENT, LATER), (), JAN_TYPO, id="nieznany-numer-raport-jeszcze-raz"
        ),
        pytest.param(
            _mail(JAN, NO_YEAR, TEXT), _mail(JAN, SUBJECT, TEXT, LATER), (), _no_year(), id="nieczytelny-temat-raport-jeszcze-raz"
        ),
        pytest.param(
            _mail(JAN, SUBJECT, "40000001 tak wymiana routera 40000004 tak montaż"),
            _mail(JAN, SUBJECT, RESENT, LATER),
            (),
            None,
            id="zlecenie-innego-wykonawcy-raport-jeszcze-raz",
        ),
        pytest.param(
            _mail(JAN, SUBJECT, "40000001 tak wymiana routera 40000003 tak montaż"),
            _mail(JAN, "Raport 09.11.2026", "40000003 tak montaż", LATER),
            (),
            RefusedMove(JAN_LOGIN, DAY, OrderNumber("40000003"), NEXT_DAY, DAY, MoveBar.NOT_ORDERED),
            id="inna-data-raport-z-dniem-zlecenia",
        ),
        pytest.param(_mail(JAN, SUBJECT, TYPO), None, (period_of(DAY).token,), JAN_TYPO, id="okres-dostal-plik-zbiorczy"),
    ],
)
def test_problem_z_bledu_wykonawcy_znika_w_nastepnym_kliknieciu_po_poprawionym_mailu_albo_pliku_zbiorczym(
    wrong: ReportMail, fixed: ReportMail | None, closed: tuple[str, ...], problem: ReportProblem | None
) -> None:
    """US 40: wynik rdzenia jest liczony od nowa z maili, a stary mail z błędem zostaje w skrzynce. Poprawionym mailem
    jest późniejszy Raport wykonawcy tego Wykonawcy, który powtarza każdy Wpis starego maila do zleceń Wykonawcy z dnia
    poprawki, więc znika problem starego maila; okres z Plikiem zbiorczym jest zamknięty. Przy innej dacie dniem
    poprawki jest dzień zlecenia. Numer dwóch zleceń Ewy od Jana (``problem`` ``None``) to do #1229 ``UnknownNumber``, a
    od #1367 ``RepeatedNumber``, bo dwóch wierszy nie da się przenieść: znika tak samo."""

    first = enter_reports(_inputs([wrong], JAN_ORDERS, today=NEXT_DAY, rollout=DAY))
    second = enter_reports(
        _inputs([wrong] if fixed is None else [wrong, fixed], JAN_ORDERS, today=NEXT_DAY, rollout=DAY, closed=closed)
    )

    assert len(first.problems) == 1
    assert problem is None or first.problems == (problem,)
    assert second.problems == ()


@pytest.mark.parametrize(
    ("wrong", "later", "problem"),
    [
        pytest.param(
            _mail(JAN, SUBJECT, TYPO),
            _mail(JAN, SUBJECT, "40000002 tak montaż", LATER),
            JAN_TYPO,
            id="kolejny-raport-z-innym-zleceniem",
        ),
        pytest.param(
            _mail(JAN, SUBJECT, "40000092 tak montaż"),
            _mail(JAN, SUBJECT, "40000002 tak montaż", LATER),
            JAN_TYPO,
            id="raport-po-jednym-zleceniu-bez-wpisu-do-zlecenia-wykonawcy",
        ),
        pytest.param(
            _mail(JAN, SUBJECT, TYPO), _mail(JAN, SUBJECT, TYPO, LATER), JAN_TYPO, id="raport-jeszcze-raz-z-tym-samym-bledem"
        ),
        pytest.param(
            _mail(JAN, SUBJECT, f"{RESENT} 40000092 tak"),
            _mail(JAN, SUBJECT, "40000001 nie", LATER),
            JAN_TYPO,
            id="poprawka-jednego-z-dwoch-wpisow-do-zlecen-wykonawcy",
        ),
        pytest.param(
            _mail(JAN, SUBJECT, TYPO),
            _mail(JAN, "Raport 09.11.2026", "40000001 tak 40000002 tak 40000003 tak", LATER),
            JAN_TYPO,
            id="raport-z-innego-dnia",
        ),
        pytest.param(
            _mail(JAN, SUBJECT, f"{TYPO} 40000003 tak"),
            _mail(JAN, "Raport 09.11.2026", "40000003 tak", LATER),
            JAN_TYPO,
            id="raport-z-innego-dnia-z-wpisem-do-zlecenia-tego-dnia",
        ),
        pytest.param(
            _mail(JAN, SUBJECT, TYPO), _mail(EWA, SUBJECT, f"{RESENT} 40000004 tak", LATER), JAN_TYPO, id="raport-innego-wykonawcy"
        ),
        pytest.param(_mail(JAN, SUBJECT, TYPO, LATER), _mail(JAN, SUBJECT, RESENT), JAN_TYPO, id="wczesniejszy-raport"),
        pytest.param(
            _mail(JAN, NO_YEAR, TEXT),
            _mail(JAN, "Raport 09.11.2026", "40000003 tak montaż", LATER),
            _no_year(),
            id="temat-raport-z-innego-dnia",
        ),
        pytest.param(
            _mail(JAN, NO_YEAR, TEXT, LATER), _mail(JAN, SUBJECT, TEXT), _no_year(LATER), id="temat-wczesniejszy-raport"
        ),
        pytest.param(
            _mail(JAN, NO_YEAR, "wyślę jutro"),
            _mail(JAN, SUBJECT, TEXT, LATER),
            _no_year(text="wyślę jutro"),
            id="temat-bez-wpisow",
        ),
        pytest.param(
            _mail(JAN, SUBJECT, "40000001 tak wymiana routera 40000003 tak montaż"),
            _mail(JAN, SUBJECT, "40000001 tak wymiana routera", LATER),
            RefusedMove(JAN_LOGIN, DAY, OrderNumber("40000003"), NEXT_DAY, DAY, MoveBar.NOT_ORDERED),
            id="inna-data-raport-jeszcze-raz-z-dnia-z-tematu",
        ),
    ],
)
def test_problem_z_bledu_wykonawcy_zostaje_bez_raportu_wyslanego_jeszcze_raz(
    wrong: ReportMail, later: ReportMail, problem: ReportProblem
) -> None:
    """Późniejszy mail nie jest poprawką, gdy nie powtarza każdego Wpisu starego maila do zleceń Wykonawcy z dnia
    poprawki albo nie ma ich wcale: nieznany numer w kolejnym raporcie może być zleceniem, którego brak w INTERMAX, więc
    zostaje. Przy innej dacie dniem poprawki jest dzień zlecenia, więc ponowny raport z dnia z tematu jej nie usuwa."""

    outcome = enter_reports(_inputs([wrong, later], JAN_ORDERS, today=NEXT_DAY, rollout=DAY))

    assert problem in outcome.problems


@pytest.mark.parametrize(
    ("worker", "taken_by", "problems"),
    [
        pytest.param("Jan.Testowy", ADAM, (), id="przeniesione-od-nadawcy"),
        pytest.param(
            "Adam.Inny",
            JAN,
            (UnknownNumber(JAN_LOGIN, DAY, OrderNumber("400000091"), AddBar.FORM),),
            id="przeniesione-do-nadawcy",
        ),
    ],
)
def test_regula_poprawki_liczy_zlecenia_wykonawcy_sprzed_przeniesien_centrum_w_kazdym_kliknieciu(
    worker: str, taken_by: str, problems: tuple[ReportProblem, ...]
) -> None:
    """ADR 0029, reguła poprawionego maila (US 40), przegląd #1374 r5 Drobne 2: zlecenie 40000001 z 8.11 stoi u
    ``worker``, a pierwsze kliknięcie przenosi je Raportem ``taken_by``. Potem Jan przysyła Raport za 8.11 z 40000001 i
    numerem z 9 cyframi, a zaraz poprawkę z 40000001 i 40000009. Reguła liczy zlecenia Jana z 8.11 sprzed Przeniesień
    Centrum, więc gdy 40000001 było jego, poprawka zdejmuje problem nieznanego numeru, a gdy przeniosło je do niego
    Centrum, nie jest poprawką i problem stoi; tak samo w drugim i trzecim kliknięciu, choć między nimi Raport Jana
    przenosi zlecenie."""

    orders = [_order(worker=worker)]
    taken = _mail(taken_by, SUBJECT, "40000001 tak montaż")
    mails = [
        taken,
        _mail(JAN, SUBJECT, "40000001 tak montaż\n400000091 tak montaż", EVENING + timedelta(hours=1)),
        _mail(JAN, SUBJECT, "40000001 tak montaż\n40000009 tak montaż", EVENING + timedelta(hours=2)),
    ]

    first = enter_reports(_inputs([taken], orders, ordered=[DAY]))
    after_first = _after(orders, first)
    second = enter_reports(_inputs(mails, after_first, ordered=[DAY], memory=first.memory))
    third = enter_reports(_inputs(mails, _after(after_first, second), ordered=[DAY], memory=second.memory))

    assert [move.order for move in first.moves] == [ROW]
    assert (second.problems, third.problems) == (problems, problems)


def test_liczby_i_zlecenia_wykonawcy_z_dnia_dla_widoku_raporty_w_kolejnosci_z_intermax() -> None:
    """``entered`` liczy zlecenia z ``tak`` albo ``nie`` w ``SKUTECZNE`` po kliknięciu, także wpisane ręcznie, a zlecenia
    dnia idą od góry arkusza, choć proces czyta je od dołu, z ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` po zapisie
    zmian kliknięcia, kto by ich nie wpisał, i z tym, czy mają Wpis (#1322)."""

    orders = [
        _order(OrderRow("Zlecenia", 124), number="40000010", worker="Ewa.Probna"),
        _order(OrderRow("Zlecenia", 123), number="40000004", successful="???", completed="ręcznie"),
        _order(OrderRow("Zlecenia", 122), number="40000003"),
        _order(OrderRow("Zlecenia", 121), number="40000002", successful=" NIE "),
        _order(OrderRow("Zlecenia", 120), number="40000001"),
    ]
    mails = [_mail(JAN, SUBJECT, TEXT), _mail(JAN, SUBJECT, "40000077 tak montaż", EVENING + timedelta(hours=1))]

    outcome = enter_reports(_inputs(mails, orders))

    assert outcome.workers == (
        WorkerDay(
            DAY,
            Login("ewa.probna"),
            orders=1,
            entered=0,
            mails=0,
            problems=0,
            without_report=(OrderNumber("40000010"),),
            orders_detail=(OrderDetail(OrderNumber("40000010"), None, None, reported=False),),
        ),
        WorkerDay(
            DAY,
            Login("jan.testowy"),
            orders=4,
            entered=2,
            mails=2,
            problems=1,
            without_report=(OrderNumber("40000002"), OrderNumber("40000003"), OrderNumber("40000004")),
            orders_detail=(
                OrderDetail(OrderNumber("40000001"), "tak", "wymiana routera", reported=True),
                OrderDetail(OrderNumber("40000002"), " NIE ", None, reported=False),
                OrderDetail(OrderNumber("40000003"), None, None, reported=False),
                OrderDetail(OrderNumber("40000004"), "???", "ręcznie", reported=False),
            ),
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
        RegisterOrder.of(
            ROW, number=number, started=started, worker=worker, successful=None, completed=None, address=None
        )
        is None
    )


def test_dzien_zlecenia_z_daty_bez_godziny_i_pusta_komorka_z_samych_spacji() -> None:
    order = RegisterOrder.of(
        ROW, number=NUMBER, started=DAY, worker="Jan.Testowy", successful="  ", completed="x", address="  "
    )

    assert order == RegisterOrder(ROW, _key(), None, "x", "Jan.Testowy", addressed=False)


# Maile Raportów wykonawców z tym, co rdzeń czyta albo pomija: Wpisy z ``tak``/``nie``, literą, słowem albo bez znaku, z
# numerem zlecenia, spoza zleceń, z przykładu w przypomnieniu i z „#”, z czynnościami z interpunkcją, maską strażnika,
# pożegnaniem, numerem i słowami stopki w opisie, po kilka w mailu i w linii, także jednego numeru z tym samym i z
# przeciwnym znakiem, linie samego tekstu, cytatu, stopki i puste, tematy z dniem, bez dnia i odpowiedzi na
# przypomnienie, od Wykonawców i spoza listy adresów, z remisem chwil przyjścia.
_NUMBERS = st.sampled_from(["40000001", "40000002", "40000003", "#40000001", "040000001", "40000077", "12345678"])
_MARKS = st.sampled_from(["tak", "nie", "Tak,", "NIE.", "t", "N", "skuteczne", "nieskuteczne", "", "tak:"])
_WORDS = st.lists(
    st.sampled_from(
        [
            "wymiana",
            "routera,",
            "2",
            "gniazda",
            "[telefon]",
            "40000002",
            "tak",
            "-",
            "pozdrawiam",
            "Jan",
            "wysłano z magazynu",
        ]
    ),
    max_size=3,
).flatmap(
    lambda words: st.sampled_from(["", "wysłano z magazynu", "Wysłano z aplikacji mobilnej Poczty o2"]).map(
        lambda ending: [*words, ending] if ending else words
    )
)
"""Słowa opisu, a na końcu co drugiego słowa stopki."""
_LINES = st.builds(lambda number, mark, words: " ".join([number, mark, *words]), _NUMBERS, _MARKS, _WORDS)
_EXACT = st.builds(
    lambda number, mark, words: " ".join([number, mark, *words]),
    st.sampled_from(["40000001", "40000002", "40000003", "040000001", "40000077"]),
    st.sampled_from(["tak", "nie"]),
    _WORDS,
)
"""Wpis w dokładnym formacie: jedyny, który czyta każda gramatyka rdzenia, więc połowa maili go ma."""
_TEXT_LINES = st.one_of(
    st.lists(_LINES, min_size=1, max_size=2).map(" ".join),
    st.sampled_from(["kurier jutro", "", "Wysłano z aplikacji mobilnej Poczty o2", "> 40000002 nie brak klienta"]),
)
"""Linia treści: jeden albo dwa Wpisy, sam tekst pod opisem, pusta linia, stopka albo linia cytatu."""
_TEXTS = st.one_of(_EXACT, st.lists(_TEXT_LINES, max_size=4).map("\n".join))
_SUBJECTS = st.one_of(
    st.sampled_from([SUBJECT, "Raport 07.11.2026", "Re: Przypomnienie: raport za dzień 08.11.2026"]),
    st.sampled_from(["Raport 8.11.26", "raport 08_11_2026", "Raport", "Raport 08.11", "Raport 31.02.2026"]),
    st.sampled_from(["Raport z 08.11.2026", "Raport 2026.11.08", "Raport 08-11-2026", "Raport 08.11.202"]),
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
_CANONICAL_MEMORY = OwnEntries(
    frozenset({OwnEntry(_key("40000002"), ReportColumn.COMPLETED, "ręcznie")}),
    frozenset({OwnMove(OrderNumber("40000003"), DAY, Login("ewa.probna"), DAY, Login("jan.testowy"), "Jan.Testowy", EVENING)}),
)
"""Pamięć z ręczną wartością równą Wpisowi i Przeniesieniem zlecenia Jana do Ewy, które INTERMAX ma dalej u Ewy."""
_CANONICAL_DAYS = (date(2026, 11, 7), DAY)
"""Oba dni zleceń są Dniami uporządkowanymi, więc nowy numer z 8 cyframi z maila się dopisuje."""


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
@example(
    [
        _mail(JAN, "Raport", "40000001 tak wymiana", EVENING, "<1@przyklad.invalid>"),
        _mail(JAN, SUBJECT, "40000001 tak wymiana", EVENING + timedelta(minutes=1), "<2@przyklad.invalid>"),
    ]
)
@example(
    [
        _mail(JAN, "Raport", "40000001 tak wymiana", EVENING, "<1@przyklad.invalid>"),
        _mail(JAN, "Raport", "kurier jutro", EVENING, "<1@przyklad.invalid>"),
        _mail(JAN, SUBJECT, "40000001 tak wymiana", EVENING + timedelta(minutes=1), "<2@przyklad.invalid>"),
    ]
)
def test_postac_kanoniczna_odczytu_maila_daje_ten_sam_wynik_rdzenia(mails: list[ReportMail]) -> None:
    """Odtworzenie z Logów (#1233) ma z maila tylko odczyt: mail z ``as_mail`` w miejscu każdego przeczytanego maila daje
    ten sam odczyt, te same zmiany komórek, problemy (poza adresem nieznanego nadawcy), liczby i pamięć wpisów."""

    inputs = _inputs(
        mails, _CANONICAL_ORDERS, today=DAY, rollout=date(2026, 11, 7), memory=_CANONICAL_MEMORY, ordered=_CANONICAL_DAYS
    )
    outcome = enter_reports(inputs)
    canonical = list(map(as_mail, outcome.mails, _canonical_senders(outcome)))

    again = enter_reports(replace(inputs, mails=canonical))

    assert (again.mails, again.changes, again.added, again.workers, again.memory) == (
        outcome.mails,
        outcome.changes,
        outcome.added,
        outcome.workers,
        outcome.memory,
    )
    assert sorted(map(repr, map(_seen, again.problems))) == sorted(map(repr, map(_seen, outcome.problems)))


def _read_back(read: ReadReport | ReadUnreadable) -> tuple[object, ...]:
    sender = SenderAddress.of(JAN)
    assert sender is not None
    return enter_reports(_inputs([as_mail(read, sender)], [_order()])).mails


@pytest.mark.parametrize("fault", list(SubjectFault), ids=lambda fault: fault.name)
def test_postac_kanoniczna_nieczytelnego_tematu_daje_ten_sam_powod(fault: SubjectFault) -> None:
    """Każdy powód nieczytelnego tematu, także taki, którego przykłady własności wyżej nie trafią, z numerami Wpisów."""

    numbers = frozenset({OrderNumber("40000001"), OrderNumber("40000002")})
    read = ReadUnreadable(MailId.of("<1@przyklad.invalid>"), EVENING, Login("jan.testowy"), fault, numbers)

    assert _read_back(read) == (read,)


@pytest.mark.parametrize("activities", ["", "wymiana routera"])
@pytest.mark.parametrize(
    ("verdict", "fault"),
    [*((verdict, None) for verdict in Verdict), *((None, fault) for fault in VerdictFault)],
    ids=lambda mark: mark.name if mark is not None else "-",
)
def test_postac_kanoniczna_wpisu_z_kazdym_znakiem_daje_ten_sam_wpis(
    verdict: Verdict | None, fault: VerdictFault | None, activities: str
) -> None:
    """Każdy ``tak``/``nie`` i każdy powód jego braku, z opisem i bez, także Wpis bez żadnego znaku."""

    entry = ReportEntry(OrderNumber("40000001"), verdict, fault, activities)
    read = ReadReport(MailId.of("<1@przyklad.invalid>"), EVENING, Login("jan.testowy"), DAY, (entry,))

    assert _read_back(read) == (read,)


@settings(derandomize=True, database=None)
@given(_MAILS.flatmap(lambda mails: st.tuples(st.just(mails), st.permutations(mails))))
def test_wlasnosc_te_same_maile_w_dowolnej_kolejnosci_daja_ten_sam_wynik_dopasowania(
    pair: tuple[list[ReportMail], list[ReportMail]],
) -> None:
    """Zlecenia mają numer Jana z dwóch dni i numer Ewy, a oba dni są Dniami uporządkowanymi, więc maile dają cele,
    Przeniesienia zleceń w obie strony, inne dni, Zlecenia dopisane z raportu (40000077), nieznane numery i nieznanych
    nadawców; dwa kliknięcia z tymi samymi mailami w innej kolejności dają ten sam wynik, z tymi samymi Przeniesieniami,
    dopisaniami i informacjami."""

    mails, shuffled = pair
    inputs = _inputs(
        mails, _CANONICAL_ORDERS, today=DAY, rollout=date(2026, 11, 7), memory=_CANONICAL_MEMORY, ordered=_CANONICAL_DAYS
    )

    assert enter_reports(replace(inputs, mails=shuffled)) == enter_reports(inputs)


def _every_problem() -> list[ReportProblem]:
    jan, ewa, number = Login("jan.testowy"), Login("ewa.probna"), OrderNumber("40000001")
    mail = MailId.of("<1@przyklad.invalid>")
    sender = SenderAddress.of("obcy@przyklad.invalid")
    assert sender is not None
    return [
        *(UnreadableSubject(mail, jan, EVENING, fault) for fault in SubjectFault),
        UnknownSender(mail, sender, DAY),
        *(MissingVerdict(jan, DAY, number, fault) for fault in VerdictFault),
        ConflictingVerdicts(
            jan,
            DAY,
            OrderNumber("40000011"),
            mail,
            EVENING,
            (
                ReportEntry(OrderNumber("40000011"), Verdict.YES, None, "inst25m"),
                ReportEntry(OrderNumber("40000011"), Verdict.NO, None, "brak klienta od umowy"),
            ),
        ),
        ConflictingVerdicts(
            jan,
            DAY,
            number,
            mail,
            EVENING,
            (ReportEntry(number, Verdict.NO, None, ""), ReportEntry(number, Verdict.YES, None, "montaż")),
        ),
        ConflictingVerdicts(
            jan,
            DAY,
            number,
            mail,
            EVENING,
            (
                ReportEntry(number, None, VerdictFault.LETTER_YES, "wymiana"),
                ReportEntry(number, None, VerdictFault.WORD_NO, "brak klienta"),
            ),
        ),
        UnknownNumber(jan, DAY, OrderNumber("40000099"), AddBar.IN_INTERMAX),
        UnknownNumber(jan, DAY, OrderNumber("40000099"), AddBar.BEFORE_WINDOW),
        UnknownNumber(jan, DAY, OrderNumber("4000009"), AddBar.FORM),
        UnknownNumber(jan, DAY, OrderNumber("40000099"), AddBar.MISTAKEN_SUBJECT),
        UnknownNumber(jan, DAY, OrderNumber("40000099"), AddBar.NOT_ORDERED),
        RepeatedOrder(jan, DAY, number),
        RepeatedNumber(jan, DAY, number, ((date(2026, 11, 6), ewa), (date(2026, 11, 7), jan))),
        RepeatedNumber(jan, DAY, number, ((date(2026, 11, 7), jan),)),
        RefusedMove(jan, DAY, number, SEVENTH, DAY, MoveBar.NOT_ORDERED),
        RefusedMove(jan, DAY, number, SEVENTH, DAY, MoveBar.OTHER_SHEET),
        RefusedMove(jan, DAY, number, SEVENTH, DAY, MoveBar.CLOSED_TARGET),
        RefusedMove(jan, DAY, number, SEVENTH, SEVENTH, MoveBar.CLOSED_SOURCE),
        RefusedMove(jan, DAY, number, NINTH, NINTH, MoveBar.AFTER_TODAY),
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


# --- Odpowiedź na Przypomnienie o raporcie (#1352, US 48–51, ADR 0030) ---

# Przypomnienie za 8.11 wysłane ze skrzynki raportów taty, tak jak je cytują Gmail i Outlook. Treść z przykładem
# (``12345678``, ``12345679``) pisze rdzeń przypomnień, a stopka jest zmyślona.
REMINDER = "Przypomnienie: raport za dzień 08.11.2026"
REMINDER_TEXT = reminder_text(DAY, "Pozdrawiam\nTata Testowy")
QUOTED = "".join(f"> {line}\n" if line else ">\n" for line in REMINDER_TEXT.splitlines())
INBOX = "Raporty <raporty.taty@przyklad.invalid>"
OUTLOOK_HEADERS = f"Wysłane: poniedziałek, 9 listopada 2026 08:00\nDo: {JAN}\nTemat: {REMINDER}\n\n"
REPLY = "40000001 tak wymiana routera"


@pytest.mark.parametrize(
    "subject",
    [
        f"Re: {REMINDER}",
        f"Odp: Re: {REMINDER}",
        f"RE: {REMINDER}",
        f"ODP: {REMINDER}",
        f"re:Re: odp: {REMINDER}",
        f" Re : {REMINDER} ",
    ],
)
def test_odpowiedz_na_przypomnienie_jest_raportem_wykonawcy_za_dzien_z_tematu_przypomnienia(subject: str) -> None:
    """US 48–49: ``Re:`` albo ``Odp:`` raz albo więcej, w dowolnej wielkości liter, przed tematem przypomnienia daje dzień
    zleceń z tematu przypomnienia."""

    mail = _mail(JAN, subject, REPLY)

    outcome = enter_reports(_inputs([mail], [_order()]))

    assert outcome.changes == _both(ROW, "tak", "wymiana routera")
    assert outcome.mails == (
        ReadReport(
            mail.id, EVENING, Login("jan.testowy"), DAY, (ReportEntry(OrderNumber("40000001"), Verdict.YES, None, "wymiana routera"),)
        ),
    )


@pytest.mark.parametrize(
    "subject",
    [
        f"Fwd: {REMINDER}",
        f"Fw: {REMINDER}",
        f"PD: {REMINDER}",
        f"Re: Fwd: {REMINDER}",
        f"Fwd: Re: {REMINDER}",
        f"Odp: PD: {REMINDER}",
        "Re: przypomnienie: raport za dzień 08.11.2026",
        "Re: Przypomnienie: raport za dzień 8.11.2026",
        "Re: Przypomnienie: raport za dzień 08.11.2026 poprawka",
        "Re: Przypomnienie: raport za dzień 31.11.2026",
    ],
)
def test_przekazanie_przypomnienia_i_odpowiedz_na_inny_temat_nie_sa_raportem(subject: str) -> None:
    """US 51: przekazanie dalej (``Fwd:``, ``Fw:``, ``PD:``) gdziekolwiek przed tematem przypomnienia i odpowiedź na
    temat, którego nie napisało Centrum, nie są Raportem wykonawcy."""

    outcome = enter_reports(_inputs([_mail(JAN, subject, REPLY)], [_order()]))

    assert (outcome.changes, outcome.problems, outcome.mails) == ((), (), ())


_PREFIXES = st.sampled_from(["Re:", "RE:", "re :", "Odp:", "ODP:", "odp:", "Fwd:", "FW:", "PD:", "pd :"])


@settings(derandomize=True, database=None, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(["", " ", "  "]), _PREFIXES), min_size=1, max_size=3))
def test_wlasnosc_odpowiedz_na_przypomnienie_jest_raportem_tylko_gdy_kazdy_przedrostek_to_re_albo_odp(
    prefixes: list[tuple[str, str]],
) -> None:
    subject = "".join(space + prefix for space, prefix in prefixes) + " " + REMINDER
    replies = all(prefix.replace(" ", "").casefold() in {"re:", "odp:"} for _, prefix in prefixes)

    assert _subject_day(subject) == (_both(ROW, "tak", "wymiana routera") if replies else ())


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(f"{REPLY}\n\nW dniu pon., 9 lis 2026 o 08:00 {INBOX} napisał(a):\n\n{QUOTED}", id="gmail"),
        pytest.param(
            f"{REPLY}\n\nW dniu pon., 9 lis 2026 o 08:00 Skrzynka Raportów Taty Testowego\n"
            f"<raporty.taty@przyklad.invalid> napisał(a):\n\n{QUOTED}",
            id="gmail-naglowek-w-dwoch-liniach",
        ),
        pytest.param(f"{REPLY}\nW dniu pon., 9 lis 2026 o 08:00 {INBOX} napisał(a):\n{QUOTED}", id="gmail-bez-pustych-linii"),
        pytest.param(f"{REPLY}\n\nOn Mon, 9 Nov 2026 at 08:00 {INBOX} wrote:\n\n{QUOTED}", id="gmail-po-angielsku"),
        pytest.param(f"{REPLY}\n{QUOTED}", id="same-linie-cytatu"),
        pytest.param(f"{REPLY}\n\n________________________________\nOd: {INBOX}\n{OUTLOOK_HEADERS}{REMINDER_TEXT}", id="outlook"),
        pytest.param(f"{REPLY}\n________________________________\nOd: {INBOX}\n{OUTLOOK_HEADERS}{REMINDER_TEXT}", id="outlook-bez-pustej-linii"),
        pytest.param(
            f"{REPLY}\n\nFrom: {INBOX}\nSent: Monday, November 9, 2026 8:00 AM\nTo: {JAN}\nSubject: {REMINDER}\n\n{REMINDER_TEXT}",
            id="outlook-po-angielsku",
        ),
        pytest.param(f"{REPLY}\n\nOd: {INBOX}\n{OUTLOOK_HEADERS}{REMINDER_TEXT}", id="outlook-z-telefonu"),
    ],
)
def test_z_odpowiedzi_na_przypomnienie_licza_sie_tylko_wpisy_nad_cytatem(text: str) -> None:
    """US 50: treść kończy pierwsza linia cytatu przypomnienia: linia ``>``, nagłówek cytatu Gmaila (także w dwóch
    liniach i po angielsku) albo Outlooka (z linią ``_`` nad nim albo bez)."""

    outcome = enter_reports(_inputs([_mail(JAN, f"Re: {REMINDER}", text)], _orders()))

    assert outcome.changes == _both(ROWS[0], "tak", "wymiana routera")
    assert outcome.problems == ()


def test_wpis_pod_linia_cytatu_sie_nie_liczy() -> None:
    """Treść kończy pierwsza linia ``>``: Wpis pod cytatem (odpowiedź pod spodem) nie jest Wpisem tej odpowiedzi."""

    text = f"{REPLY}\n> Poproszę o wysłanie raportu za dzień 08.11.2026.\n40000002 nie brak klienta"

    outcome = enter_reports(_inputs([_mail(JAN, f"Re: {REMINDER}", text)], _orders()))

    assert outcome.changes == _both(ROWS[0], "tak", "wymiana routera")


@pytest.mark.parametrize("subject", [f"Re: {REMINDER}", SUBJECT])
@pytest.mark.parametrize(
    "text",
    [
        pytest.param(f"{REPLY}\n12345678 tak montaż ONT\n12345679 nie brak klienta", id="przyklad-bez-cytatu"),
        pytest.param(f"12345678 tak montaż ONT 12345679 nie brak klienta {REPLY}", id="przyklad-w-jednej-linii"),
        pytest.param(f"{REPLY}\n\n{REMINDER_TEXT}", id="cale-przypomnienie-bez-cytatu"),
        pytest.param(f"{REPLY}\n\n#12345678 t\n12345679", id="przyklad-z-krzyzykiem-i-bez-znaku"),
    ],
)
def test_numery_z_przykladu_nie_daja_wpisu_ani_problemu_nawet_gdy_sa_zleceniami(subject: str, text: str) -> None:
    """US 50: numery z przykładu w przypomnieniu (``12345678``, ``12345679``) nie dają Wpisu ani problemu numeru, z którego
    powstałoby Zlecenie dopisane z raportu, także bez znaku cytatu i gdy INTERMAX ma zlecenie o tym numerze, a linia
    przykładu kończy opis Wpisu nad nią."""

    example = _order(OrderRow("Zlecenia", 125), number="12345678")
    mail = _mail(JAN, subject, text)

    outcome = enter_reports(_inputs([mail], [_order(), example]))

    assert outcome.changes == _both(ROW, "tak", "wymiana routera")
    assert outcome.problems == ()
    assert [entry.number for read in outcome.mails if isinstance(read, ReadReport) for entry in read.entries] == ["40000001"]


def test_numery_z_przykladu_nie_sa_numerami_nieczytelnego_tematu() -> None:
    """Mail z nieczytelnym tematem pamięta numery swoich Wpisów dla poprawionego maila, bez numerów z przykładu."""

    mail = _mail(JAN, "Raport 08.11", f"{REPLY}\n12345678 tak montaż ONT")

    outcome = enter_reports(_inputs([mail], [_order()]))

    assert outcome.mails == (
        ReadUnreadable(mail.id, EVENING, Login("jan.testowy"), SubjectFault.NO_YEAR, frozenset({OrderNumber("40000001")})),
    )


@pytest.mark.parametrize(
    ("subject", "due"),
    [
        pytest.param(f"Re: {REMINDER}", [], id="odpowiedz"),
        pytest.param(f"Odp: Re: {REMINDER}", [], id="odpowiedz-z-outlooka"),
        pytest.param(f"Fwd: {REMINDER}", [(Login("jan.testowy"), DAY)], id="przekazanie"),
        pytest.param("Re: Przypomnienie: raport za dzień 07.11.2026", [(Login("jan.testowy"), DAY)], id="inny-dzien"),
    ],
)
def test_odpowiedz_na_przypomnienie_konczy_przypomnienia_za_ten_dzien(subject: str, due: list[tuple[Login, date]]) -> None:
    """US 49 i ADR 0030: odpowiedź na przypomnienie za dzień jest czytelnym Raportem wykonawcy za ten dzień, więc
    przypomnienia za niego ustają; przekazanie dalej i odpowiedź za inny dzień ich nie kończą."""

    mail = _mail(JAN, subject, f"{REPLY}\n\nW dniu pon., 9 lis 2026 o 08:00 {INBOX} napisał(a):\n{QUOTED}")
    now = datetime(2026, 11, 9, 18, 0, tzinfo=TAPA)
    inputs = _inputs([mail], [_order()], today=now.date(), rollout=DAY - timedelta(days=1))

    found = reminders_due(
        ReminderInputs(
            now,
            inputs.window,
            inputs.orders,
            inputs.mails,
            (),
            inputs.addresses,
            frozenset(inputs.addresses.logins.values()),
            footer=None,
        )
    )

    assert [(reminder.worker, reminder.day) for reminder in found] == due


# --- Rozpoznanie tematu i Wpisów tak, jak piszą Wykonawcy (#1228, US 8–10, 18–26) ---

PROPERTY = settings(derandomize=True, database=None, deadline=None, max_examples=150)
ROWS = (ROW, OrderRow("Zlecenia", 121), OrderRow("Zlecenia", 122))
NUMBERS = ("40000001", "40000002", "40000003")


def _orders() -> list[RegisterOrder]:
    return [_order(row, number=number) for row, number in zip(ROWS, NUMBERS, strict=True)]


def _both(row: OrderRow, verdict: str, activities: str) -> tuple[CellChange, CellChange]:
    return CellChange(row, ReportColumn.SUCCESSFUL, verdict), CellChange(row, ReportColumn.COMPLETED, activities)


def _subject_day(subject: str) -> tuple[CellChange, ...]:
    return enter_reports(_inputs([_mail(JAN, subject, TEXT)], [_order()])).changes


@pytest.mark.parametrize(
    "subject",
    [
        "raport 08.11.2026",
        "RAPORT 08.11.2026",
        "Raport 8.11.2026",
        "Raport 08_11_2026",
        "Raport 08/11/2026",
        "Raport 8/11/26",
        "Raport 08.11.26",
        "  Raport    08.11.2026  ",
        "Raport08.11.2026",
        "Raport 08 . 11 . 2026",
        "Raport\t8_11/2026",
        "Raport\xa008.11.2026",
        "Raport 08.11.2026r.",
        "Raport 8.11.2026 r",
        "Raport 08.11.26 r.",
    ],
)
def test_temat_raportu_w_kazdym_zapisie_daty_daje_dzien_zlecen(subject: str) -> None:
    """US 8: ``Raport`` bez względu na wielkość liter i spacje, separator ``.``, ``_`` albo ``/``, rok dwu- albo
    czterocyfrowy, dzień i miesiąc bez zera, rok z dopiskiem ``r.``."""

    assert _subject_day(subject) == _both(ROW, "tak", "wymiana routera")


@pytest.mark.parametrize(
    ("subject", "arrived", "day"),
    [
        pytest.param("Raport 08.11.2016", EVENING, DAY, id="rok-sprzed-dziesieciu-lat"),
        pytest.param("Raport 08.11.2025", EVENING, DAY, id="rok-poprzedni"),
        pytest.param("Raport 08.11.27", EVENING, DAY, id="rok-nastepny"),
        pytest.param("Raport 29.12.2027", datetime(2027, 1, 2, 18, tzinfo=TAPA), date(2026, 12, 29), id="nowy-rok-po-dniu"),
        pytest.param("Raport 02.01.2026", datetime(2027, 1, 3, 18, tzinfo=TAPA), date(2027, 1, 2), id="stary-rok-po-nowym"),
        pytest.param("Raport 29.12.2026", datetime(2027, 1, 2, 18, tzinfo=TAPA), date(2026, 12, 29), id="grudzien-w-styczniu"),
        pytest.param("Raport 02.01.2026", datetime(2026, 12, 30, 18, tzinfo=TAPA), date(2027, 1, 2), id="styczen-w-grudniu"),
        pytest.param("Raport 09.11.2026", EVENING, date(2026, 11, 9), id="jutro-zostaje"),
        pytest.param("Raport 08.12.2026", EVENING, date(2026, 12, 8), id="literowka-w-miesiacu-zostaje"),
        pytest.param("Raport 09.01.2027", EVENING, date(2027, 1, 9), id="za-62-dni-zostaje"),
        pytest.param("Raport 10.01.2027", EVENING, date(2026, 1, 10), id="za-63-dni-rok-wstecz"),
        pytest.param("Raport 10.01.2026", EVENING, date(2026, 1, 10), id="302-dni-wstecz-zostaje"),
        pytest.param("Raport 09.01.2026", EVENING, date(2027, 1, 9), id="303-dni-wstecz-rok-naprzod"),
    ],
)
def test_literowka_w_roku_tematu_daje_dzien_z_tym_dniem_i_miesiacem_w_granicach_wokol_przyjscia_maila(
    subject: str, arrived: datetime, day: date
) -> None:
    """Wykonawca pomylił rok (Raport z 10.11.2026 z tematem ``Raport 10.11.2016``, prawdziwa skrzynka 12.11.2026):
    data z tematu ponad 302 dni przed dniem przyjścia albo ponad 62 dni po nim to ten sam dzień i miesiąc w roku, w
    którym wypada w tych granicach, więc Raport wpisuje się do zleceń tego dnia bez taty. Data w granicach zostaje."""

    order = _order(day=day)
    mail = _mail(JAN, subject, TEXT, arrived)

    outcome = enter_reports(_inputs([mail], [order], today=max(day, arrived.date()), rollout=day))

    assert outcome.changes == _both(ROW, "tak", "wymiana routera")
    assert [found.day for found in outcome.mails if isinstance(found, ReadReport)] == [day]


def test_29_lutego_z_innego_roku_przestepnego_daje_29_lutego_roku_przestepnego_w_granicach() -> None:
    mail = _mail(JAN, "Raport 29.02.2024", TEXT, datetime(2028, 3, 10, 18, tzinfo=TAPA))

    outcome = enter_reports(_inputs([mail], [_order(day=date(2028, 2, 29))], today=date(2028, 3, 10), rollout=date(2028, 2, 1)))

    assert [found.day for found in outcome.mails if isinstance(found, ReadReport)] == [date(2028, 2, 29)]
    assert outcome.changes == _both(ROW, "tak", "wymiana routera")


def test_29_lutego_bez_roku_przestepnego_w_granicach_zostaje_z_tematu() -> None:
    """Dzień, którego nie ma w żadnym roku wokół przyjścia maila, zostaje z tematu, więc poza oknem rdzeń go pomija."""

    mail = _mail(JAN, "Raport 29.02.2024", TEXT, datetime(2026, 11, 8, 18, tzinfo=TAPA))

    outcome = enter_reports(_inputs([mail], [_order()], rollout=date(2024, 1, 1)))

    assert [found.day for found in outcome.mails if isinstance(found, ReadReport)] == [date(2024, 2, 29)]


@st.composite
def _subject_of_day(draw: st.DrawFn) -> str:
    word = "".join(letter.upper() if draw(st.booleans()) else letter for letter in "raport")
    spaces = st.sampled_from(["", " ", "  ", "\t", "\xa0"])
    separator = st.builds(lambda before, mark, after: before + mark + after, spaces, st.sampled_from("._/"), spaces)
    day = draw(st.sampled_from(["8", "08"]))
    year = draw(st.sampled_from(["26", "2026"]))
    return f"{draw(spaces)}{word}{draw(spaces)}{day}{draw(separator)}11{draw(separator)}{year}{draw(spaces)}"


@PROPERTY
@given(_subject_of_day())
def test_wlasnosc_kazdy_zapis_tematu_raportu_daje_ten_sam_dzien_co_zapis_kanoniczny(subject: str) -> None:
    assert _subject_day(subject) == _subject_day(SUBJECT)


@pytest.mark.parametrize(
    ("subject", "fault"),
    [
        pytest.param("Raport", SubjectFault.NO_DATE, id="samo-slowo"),
        pytest.param("raport z dzisiaj", SubjectFault.NO_DATE, id="bez-liczb"),
        pytest.param("Raport 08.11", SubjectFault.NO_YEAR, id="bez-roku"),
        pytest.param("Raport 8/11 ", SubjectFault.NO_YEAR, id="bez-roku-ukosnik"),
        pytest.param("Raport 31.11.2026", SubjectFault.NOT_A_DAY, id="31-listopada"),
        pytest.param("Raport 08.13.2026", SubjectFault.NOT_A_DAY, id="miesiac-13"),
        pytest.param("Raport 0.11.2026", SubjectFault.NOT_A_DAY, id="dzien-zero"),
        pytest.param("Raport 29.02.27", SubjectFault.NOT_A_DAY, id="29-lutego-roku-zwyklego"),
        pytest.param("Raport 08,11,2026", SubjectFault.SEPARATOR, id="przecinek"),
        pytest.param("Raport 08-11-2026", SubjectFault.SEPARATOR, id="myslnik"),
        pytest.param("Raport 08 11 2026", SubjectFault.SEPARATOR, id="spacja"),
        pytest.param("Raport 08..11.2026", SubjectFault.SEPARATOR, id="dwie-kropki"),
        pytest.param("Raport 08.11.226", SubjectFault.YEAR_DIGITS, id="rok-trzy-cyfry"),
        pytest.param("Raport 08.11.20226", SubjectFault.YEAR_DIGITS, id="rok-piec-cyfr"),
        pytest.param("Raport 08112026", SubjectFault.DATE_FORM, id="bez-separatorow"),
        pytest.param("Raport 008.11.2026", SubjectFault.DATE_FORM, id="dzien-trzy-cyfry"),
        pytest.param("Raport 08.011.2026", SubjectFault.DATE_FORM, id="miesiac-trzy-cyfry"),
        pytest.param("Raport 08.11.2026.1", SubjectFault.DATE_FORM, id="cztery-liczby"),
        pytest.param("Raporty 08.11.2026", SubjectFault.OTHER_TEXT, id="slowo-z-litera"),
        pytest.param("Raport z 08.11.2026", SubjectFault.OTHER_TEXT, id="slowo-przed-data"),
        pytest.param("Mój raport 08.11.2026", SubjectFault.OTHER_TEXT, id="tekst-przed-slowem"),
        pytest.param("Raport 08.11.2026 poprawka", SubjectFault.OTHER_TEXT, id="tekst-po-dacie"),
        pytest.param("Raport: 08.11.2026", SubjectFault.OTHER_TEXT, id="dwukropek"),
        pytest.param("Odpowiedź: Raport 08.11.2026", SubjectFault.OTHER_TEXT, id="slowo-odpowiedz"),
        pytest.param("Raport 08.11.2026 rok", SubjectFault.OTHER_TEXT, id="slowo-rok-po-dacie"),
    ],
)
def test_temat_ze_slowem_raport_ktorego_nie_da_sie_odczytac_jest_problemem_z_powodem(
    subject: str, fault: SubjectFault
) -> None:
    """US 10: mail od Wykonawcy ze słowem „raport” w temacie bez dnia zleceń nic nie wpisuje i mówi tacie dlaczego."""

    mail = _mail(JAN, subject, TEXT)

    outcome = enter_reports(_inputs([mail], [_order()]))

    assert outcome.changes == ()
    assert outcome.problems == (UnreadableSubject(mail.id, Login("jan.testowy"), EVENING, fault),)
    assert outcome.mails == (ReadUnreadable(mail.id, EVENING, Login("jan.testowy"), fault, frozenset({OrderNumber("40000001")})),)


@pytest.mark.parametrize(
    ("sender", "arrived", "rollout", "closed"),
    [
        pytest.param("obcy@przyklad.invalid", EVENING, None, (), id="adres-spoza-listy"),
        pytest.param(
            JAN, EVENING - timedelta(days=3), date(2026, 11, 1), (period_of(date(2026, 11, 5)).token,), id="okres-zamkniety"
        ),
    ],
)
def test_nieczytelny_temat_spoza_wykonawcow_albo_z_okresu_z_plikiem_zbiorczym_jest_pomijany_po_cichu(
    sender: str, arrived: datetime, rollout: date | None, closed: tuple[str, ...]
) -> None:
    """Problem ma tylko mail od Wykonawcy, który przyszedł w dniu otwartym (US 10, 40)."""

    outcome = enter_reports(_inputs([_mail(sender, "Raport 08.11", TEXT, arrived)], [], rollout=rollout, closed=closed))

    assert (outcome.problems, outcome.mails) == ((), ())


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("40000001 tak wymiana routera\n40000002 nie brak klienta\n40000003 TAK montaż", id="osobne-linie"),
        pytest.param("40000001 tak wymiana routera 40000002 nie brak klienta 40000003 TAK montaż", id="jedna-linia"),
        pytest.param("#40000001 tak wymiana routera, #40000002 nie brak klienta; 40000003 TAK montaż", id="z-krzyzykiem"),
        pytest.param(
            "Dzień dobry 40000001 tak wymiana routera\n\n40000002 nie brak klienta 40000003 TAK montaż", id="mieszane"
        ),
        pytest.param("1. 40000001 tak wymiana routera\n2. 40000002 nie brak klienta\n3. 40000003 TAK montaż", id="lista"),
    ],
)
def test_wiele_wpisow_w_jednym_mailu_takze_w_jednej_linii(text: str) -> None:
    """US 18, 19: nowy Wpis zaczyna numer zlecenia Wykonawcy z dnia, z ``#`` albo bez, po którym stoi ``tak``/``nie``."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], _orders()))

    assert outcome.changes == (
        *_both(ROWS[0], "tak", "wymiana routera"),
        *_both(ROWS[1], "nie", "brak klienta"),
        *_both(ROWS[2], "tak", "montaż"),
    )
    assert outcome.problems == ()


@pytest.mark.parametrize(
    ("text", "first"),
    [
        pytest.param("40000001 tak montaż 2 gniazda stb2 40000002 nie brak klienta", "montaż 2 gniazda stb2", id="liczby"),
        pytest.param("40000001 tak 3 nie działały, wymiana 40000002 nie brak klienta", "3 nie działały, wymiana", id="liczba-i-nie"),
        pytest.param(
            "40000001 tak jak w 40000003 wymiana 40000002 nie brak klienta",
            "jak w 40000003 wymiana",
            id="numer-zlecenia-bez-tak-nie",
        ),
    ],
)
def test_liczby_w_opisie_nie_rozcinaja_wpisu(text: str, first: str) -> None:
    """US 20: po liczbie z opisu nie stoi ``tak``/``nie`` albo nie jest ona numerem zlecenia Wykonawcy z dnia."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], _orders()))

    assert outcome.changes == (*_both(ROWS[0], "tak", first), *_both(ROWS[1], "nie", "brak klienta"))


@st.composite
def _entries_text(draw: st.DrawFn) -> str:
    """Trzy Wpisy z ``_EXPECTED`` w dowolnym układzie linii, z ``#`` albo bez, ``tak``/``nie`` w dowolnej wielkości liter
    i z interpunkcją, z dodatkowymi spacjami."""

    def verdict(word: str) -> str:
        cased = "".join(letter.upper() if draw(st.booleans()) else letter for letter in word)
        return draw(st.sampled_from(["{}", "{},", "{}.", "{}:", "({})", "{} -", "- {}"])).format(cased)

    spaces = st.sampled_from([" ", "  ", "\t", "\xa0"])
    parts = []
    for number, (word, activities) in zip(NUMBERS, _EXPECTED, strict=True):
        hash_mark = draw(st.sampled_from(["", "#"]))
        words = activities.split(" ")
        parts.append(hash_mark + number + draw(spaces) + verdict(word) + draw(spaces) + draw(spaces).join(words))
    joins = [draw(st.sampled_from(["\n", " ", ", ", "; ", "\n\n", "  \n"])) for _ in parts[1:]]
    return parts[0] + "".join(join + part for join, part in zip(joins, parts[1:], strict=True))


_EXPECTED = (("tak", "wymiana routera, 2 gniazda"), ("nie", "brak klienta, stb2 nie odpowiada"), ("tak", "montaż 3 szt."))


@PROPERTY
@given(_entries_text())
def test_wlasnosc_wpisy_w_dowolnym_ukladzie_daja_te_same_komorki(text: str) -> None:
    """US 19–21, 24, 26: układ linii, ``#``, wielkość liter, interpunkcja przy ``tak``/``nie`` i spacje nie zmieniają
    komórek, a ``SKUTECZNE`` dostaje ``tak``/``nie`` małymi literami."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], _orders()))

    assert outcome.changes == tuple(
        change for row, (word, activities) in zip(ROWS, _EXPECTED, strict=True) for change in _both(row, word, activities)
    )
    assert outcome.problems == ()


@pytest.mark.parametrize(
    ("text", "verdict"),
    [
        pytest.param("40000001 TAK wymiana routera", "tak", id="wielkie"),
        pytest.param("40000001 Tak, wymiana routera", "tak", id="przecinek"),
        pytest.param("40000001 tak. wymiana routera", "tak", id="kropka"),
        pytest.param("40000001 NIE: wymiana routera", "nie", id="dwukropek"),
        pytest.param("40000001 - nie - wymiana routera", "nie", id="myslniki"),
        pytest.param("40000001: tak wymiana routera", "tak", id="dwukropek-po-numerze"),
    ],
)
def test_tak_albo_nie_bez_wzgledu_na_wielkosc_liter_i_interpunkcje_trafia_malymi_literami(text: str, verdict: str) -> None:
    """US 21, 26."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], [_order()]))

    assert outcome.changes == _both(ROW, verdict, "wymiana routera")


@pytest.mark.parametrize(
    ("text", "fault"),
    [
        pytest.param("40000001 t wymiana routera", VerdictFault.LETTER_YES, id="t"),
        pytest.param("40000001 N, brak klienta", VerdictFault.LETTER_NO, id="n"),
        pytest.param("40000001 skuteczne wymiana routera", VerdictFault.WORD_YES, id="skuteczne"),
        pytest.param("40000001 Nieskuteczne: brak klienta", VerdictFault.WORD_NO, id="nieskuteczne"),
        pytest.param("40000001 wymiana routera", VerdictFault.MISSING, id="bez-tak-nie"),
        pytest.param("40000001 nieobecny", VerdictFault.MISSING, id="slowo-od-nie"),
        pytest.param("40000001", VerdictFault.MISSING, id="sam-numer"),
        pytest.param("#40000001 takie same gniazda", VerdictFault.MISSING, id="slowo-od-tak"),
    ],
)
def test_wpis_bez_tak_ani_nie_jest_problemem_a_nie_zgadnieta_wartoscia(text: str, fault: VerdictFault) -> None:
    """US 22: ani ``SKUTECZNE``, ani ``CZYNNOŚCI ZREALIZOWANE`` takiego Wpisu nie dostają."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], [_order()]))

    assert outcome.changes == ()
    assert outcome.problems == (MissingVerdict(Login("jan.testowy"), DAY, OrderNumber("40000001"), fault),)


def test_pozniejszy_wpis_bez_tak_ani_nie_zastepuje_wczesniejszy_i_nic_nie_wpisuje() -> None:
    """US 37: o zleceniu decyduje najpóźniejszy Wpis, a ten nie mówi, czy zlecenie było skuteczne."""

    mails = [_mail(JAN, SUBJECT, TEXT), _mail(JAN, SUBJECT, "40000001 t wymiana routera", EVENING + timedelta(hours=1))]

    outcome = enter_reports(_inputs(mails, [_order()]))

    assert outcome.changes == ()
    assert outcome.problems == (MissingVerdict(Login("jan.testowy"), DAY, OrderNumber("40000001"), VerdictFault.LETTER_YES),)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            "Dzień dobry,\n\n40000001 tak wymiana routera\n40000002 nie klient nieobecny\n\nPozdrawiam\nJan\n\n"
            "Wysłane z iPhone'a",
            id="powitanie-podpis-iphone",
        ),
        pytest.param(
            "40000001 tak wymiana routera 40000002 nie klient nieobecny Pozdrawiam, Jan", id="podpis-w-tej-samej-linii"
        ),
        pytest.param(
            "40000001 tak wymiana routera\n40000002 nie klient nieobecny\n\n"
            "W dniu pon., 8 lis 2026 o 12:00 Jan <jan@przyklad.invalid> napisał(a):\n"
            "> 40000001 nie brak klienta\n> 40000003 tak montaż\n",
            id="cytat-gmaila",
        ),
        pytest.param(
            "40000001 tak wymiana routera\n40000002 nie klient nieobecny\n\n"
            "W dniu pon., 8 lis 2026 o 12:00 Jan Testowy <jan@przyklad.invalid>\nnapisał(a):\n\n"
            "> 40000001 nie brak klienta\n> 40000003 tak montaż\n",
            id="cytat-gmaila-z-zawinietym-naglowkiem",
        ),
        pytest.param(
            "40000001 tak wymiana routera\n40000002 nie klient nieobecny\n\nOd: Jan <jan@przyklad.invalid>\n"
            "Wysłano: poniedziałek, 8 listopada 2026 12:00\nTemat: Raport 08.11.2026\n\n40000003 tak montaż\n",
            id="cytat-outlooka",
        ),
        pytest.param(
            "40000001 tak wymiana routera\n40000002 nie klient nieobecny\n-- \nJan Testowy\n40000003 tak 600 100 200",
            id="separator-podpisu",
        ),
        pytest.param(
            "40000001 tak wymiana routera\n40000002 nie klient nieobecny\n40000001 tak montaż gniazda",
            id="pierwszy-wpis-numeru-z-tym-samym-tak",
        ),
    ],
)
def test_powitanie_podpis_i_cytat_nie_trafiaja_do_opisu(text: str) -> None:
    """US 23, 25: powód nieskuteczności przy ``nie`` też trafia do ``CZYNNOŚCI ZREALIZOWANE``; z cytowanej odpowiedzi
    nic. Z dwóch Wpisów zlecenia z tym samym ``tak`` w jednym mailu liczy się pierwszy."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], _orders()))

    assert outcome.changes == (*_both(ROWS[0], "tak", "wymiana routera"), *_both(ROWS[1], "nie", "klient nieobecny"))
    assert outcome.problems == ()


def test_opis_ma_pojedyncze_spacje_bez_spacji_na_brzegach() -> None:
    """US 24."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "  40000001\ttak   wymiana \xa0 routera ,  2 gniazda   ")], [_order()]))

    assert outcome.changes == _both(ROW, "tak", "wymiana routera , 2 gniazda")


@pytest.mark.parametrize(
    ("text", "number", "bar"),
    [
        pytest.param("040000001 tak wymiana routera", "040000001", AddBar.FORM, id="zero-wiodace"),
        pytest.param("Dzień dobry 40000077 tak wymiana routera", "40000077", AddBar.NOT_ORDERED, id="po-powitaniu"),
    ],
)
def test_numer_z_tak_albo_nie_spoza_zlecen_wykonawcy_jest_problemem(text: str, number: str, bar: AddBar) -> None:
    """Zero wiodące to inny numer niż ``NUMER ZL.`` (9 cyfr, więc bez dopisania), a pomyłka w numerze przed pierwszym
    Wpisem linii też jest Wpisem (dzień nie jest Dniem uporządkowanym, więc bez dopisania)."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], [_order()]))

    assert outcome.changes == ()
    assert outcome.problems == (UnknownNumber(Login("jan.testowy"), DAY, OrderNumber(number), bar),)


def test_dwa_maile_z_jednym_message_id_i_chwila_przyjscia_daja_ten_sam_wynik_w_kazdej_kolejnosci() -> None:
    """Remis ``(arrived, MailId)``: rozstrzyga treść Wpisów, nie kolejność maili na wejściu."""

    mails = [
        _mail(JAN, SUBJECT, "40000001 tak montaż", EVENING, "<1@przyklad.invalid>"),
        _mail(JAN, SUBJECT, "40000001 nie brak klienta", EVENING, "<1@przyklad.invalid>"),
    ]

    outcomes = [enter_reports(_inputs(order, [_order()])) for order in (mails, mails[::-1])]

    assert outcomes[0] == outcomes[1]
    assert len(outcomes[0].changes) == 2


def test_wlasnosc_permutacja_maili_z_problemami_rozpoznania_daje_ten_sam_wynik() -> None:
    mails = [
        _mail(JAN, "Raport 08.11", TEXT, EVENING),
        _mail(JAN, "Raport 8/11/26", "40000001 t wymiana", EVENING + timedelta(minutes=1)),
        _mail(JAN, "raport 08.11.2026", "40000002 tak a 40000003 NIE b", EVENING, "<1@przyklad.invalid>"),
        _mail(JAN, "RAPORT 08_11_2026", "40000002 nie c", EVENING, "<1@przyklad.invalid>"),
        _mail(EWA, "Raport 08.11.2026", "40000009 tak d", EVENING),
    ]

    outcomes = [enter_reports(_inputs(order, _orders())) for order in itertools.permutations(mails)]

    assert all(outcome == outcomes[0] for outcome in outcomes)


# --- Wpis przez kilka linii (#1228 runda 2): granica Wpisu nie zależy od końca linii ---

EWA_ORDERS = (
    _order(OrderRow("Zlecenia", 123), number="40000009", worker="Ewa.Probna"),
    _order(OrderRow("Zlecenia", 124), number="40000009", worker="Adam.Inny"),
)
"""Numer 40000009 u dwóch innych Wykonawców: Wpis Jana nie przenosi go, tylko daje ``RepeatedNumber`` z każdym z nich."""
LONG = "40000001 tak wymiana routera,\nmontaż 2 gniazd"
LONG_CELLS = ((0, "tak", "wymiana routera, montaż 2 gniazd"),)


def _unknown(number: str, bar: AddBar = AddBar.NOT_ORDERED) -> UnknownNumber:
    return UnknownNumber(Login("jan.testowy"), DAY, OrderNumber(number), bar)


def _cells(entered: Sequence[tuple[int, str, str]]) -> tuple[CellChange, ...]:
    return tuple(
        change
        for index, verdict, activities in entered
        for change in (_both(ROWS[index], verdict, activities) if activities else (CellChange(ROWS[index], ReportColumn.SUCCESSFUL, verdict),))
    )


@pytest.mark.parametrize(
    ("text", "entered", "problems"),
    [
        pytest.param("40000001 tak\nwymiana routera", ((0, "tak", "wymiana routera"),), (), id="opis-w-nastepnej-linii"),
        pytest.param(LONG, LONG_CELLS, (), id="opis-zawiniety"),
        pytest.param(
            "40000001 tak wymiana routera 40000002 nie brak klienta 40000003\ntak montaż",
            ((0, "tak", "wymiana routera"), (1, "nie", "brak klienta"), (2, "tak", "montaż")),
            (),
            id="lamanie-miedzy-numerem-a-tak",
        ),
        pytest.param("40000001\ntak wymiana routera", ((0, "tak", "wymiana routera"),), (), id="numer-sam-w-linii"),
        pytest.param(
            "40000001 tak wymiana routera\n3 nie działały", ((0, "tak", "wymiana routera 3 nie działały"),), (), id="linia-od-liczby-i-nie"
        ),
        pytest.param(
            "40000001 tak wymiana routera\n2 tak jak ustalono",
            ((0, "tak", "wymiana routera 2 tak jak ustalono"),),
            (),
            id="linia-od-liczby-i-tak",
        ),
        pytest.param(
            "40000001 tak router\n4000002 nie brak", ((0, "tak", "router 4000002 nie brak"),), (), id="liczba-krotsza-niz-numer-zlecenia"
        ),
        pytest.param(
            "40000001 tak wymiana routera\n40000099 nie brak klienta",
            ((0, "tak", "wymiana routera"),),
            (_unknown("40000099"),),
            id="literowka-w-numerze-w-nastepnej-linii",
        ),
        pytest.param(
            "40000001 tak wymiana routera 40000099 nie brak klienta",
            ((0, "tak", "wymiana routera"),),
            (_unknown("40000099"),),
            id="literowka-w-numerze-w-tej-samej-linii",
        ),
        pytest.param(
            "40000001 tak wymiana routera\n40000099 brak klienta",
            ((0, "tak", "wymiana routera"),),
            (_unknown("40000099"),),
            id="literowka-w-numerze-bez-tak-nie-na-poczatku-linii",
        ),
        pytest.param(
            "40000001 tak router jak\n40000009 nie działał",
            ((0, "tak", "router jak"),),
            (RepeatedNumber(JAN_LOGIN, DAY, OrderNumber("40000009"), ((DAY, Login("adam.inny")), (DAY, EWA_LOGIN))),),
            id="zlecenie-innego-wykonawcy-ze-znakiem",
        ),
        pytest.param(
            "40000001 tak router\n40000002 wymiana",
            ((0, "tak", "router"),),
            (MissingVerdict(Login("jan.testowy"), DAY, OrderNumber("40000002"), VerdictFault.MISSING),),
            id="zlecenie-na-poczatku-linii-bez-tak-nie",
        ),
        pytest.param(
            "40000001 tak wymiana routera, montaż 2\ngniazd 40000002 nie brak klienta",
            ((0, "tak", "wymiana routera, montaż 2 gniazd"), (1, "nie", "brak klienta")),
            (),
            id="koniec-opisu-przed-wpisem-w-linii",
        ),
        pytest.param(
            "- 40000001 tak router\n• 40000002 nie brak klienta\n(3) 40000003 tak montaż",
            ((0, "tak", "router"), (1, "nie", "brak klienta"), (2, "tak", "montaż")),
            (),
            id="lista-z-punktorami",
        ),
        pytest.param(
            "40000001 tak gniazda 2 40000002 nie brak klienta",
            ((0, "tak", "gniazda 2"), (1, "nie", "brak klienta")),
            (),
            id="liczba-przed-wpisem-w-srodku-linii",
        ),
        pytest.param(
            "40000001 tak klient nie odbiera tel 600100200 nie odbiera",
            ((0, "tak", "klient nie odbiera tel"),),
            (_unknown("600100200", AddBar.FORM),),
            id="telefon-ze-znakiem-po-nim-to-problem",
        ),
        pytest.param(
            "Dzień dobry, 2 tak jak ustalono:\n40000001 tak router", ((0, "tak", "router"),), (), id="liczba-w-powitaniu"
        ),
        pytest.param(f"{LONG}\nPozdrawiam\nJan", LONG_CELLS, (), id="pozdrawiam"),
        pytest.param(f"{LONG}\nPozdr. Jan", LONG_CELLS, (), id="pozdr"),
        pytest.param(f"{LONG}\npozdrowienia", LONG_CELLS, (), id="pozdrowienia"),
        pytest.param(f"{LONG}\nDziękuję\nJan", LONG_CELLS, (), id="dziekuje"),
        pytest.param(f"{LONG}\nZ poważaniem\nJan Testowy", LONG_CELLS, (), id="z-powazaniem"),
        pytest.param(f"{LONG} z\npoważaniem Jan", LONG_CELLS, (), id="z-powazaniem-zawiniete"),
        pytest.param(f"{LONG}\n-- \nJan 40000002 tak x", LONG_CELLS, (), id="separator-podpisu"),
        pytest.param(f"{LONG}\n--\nJan 40000002 tak x", LONG_CELLS, (), id="separator-podpisu-bez-spacji"),
        pytest.param(f"{LONG}\nWysłane z iPhone'a", LONG_CELLS, (), id="wyslane-z-iphonea"),
        pytest.param(f"{LONG}\n\nSent from my iPhone", LONG_CELLS, (), id="sent-from-my-iphone"),
        pytest.param(f"{LONG}\nWysłano z aplikacji Poczta\n40000002 nie brak", (*LONG_CELLS, (1, "nie", "brak")), (), id="wyslano-z"),
        pytest.param(f"{LONG}\n> stary cytat\nmontaż", LONG_CELLS, (), id="linia-cytatu"),
        pytest.param(
            "40000001 tak router 40000002\n> cytat\ntak montaż", ((0, "tak", "router 40000002"),), (), id="znak-za-cytatem"
        ),
        pytest.param(
            f"{LONG}\n\nW dniu pon., 8 lis 2026 o 12:00 Jan <jan@przyklad.invalid> napisał(a):\n> 40000001 nie brak klienta",
            LONG_CELLS,
            (),
            id="cytat-gmaila",
        ),
        pytest.param(
            f"{LONG}\nOn Mon, 8 Nov 2026 at 12:00 Jan <jan@przyklad.invalid> wrote:\n40000002 nie brak klienta",
            LONG_CELLS,
            (),
            id="cytat-po-angielsku-bez-znakow-cytatu",
        ),
        pytest.param(
            f"{LONG}\nOn Mon, 8 Nov 2026 at 12:00\nJan <jan@przyklad.invalid> wrote:\n40000002 nie brak klienta",
            LONG_CELLS,
            (),
            id="cytat-po-angielsku-zawiniety",
        ),
        pytest.param(
            f"{LONG}\n---------- Forwarded message ---------\n40000002 nie brak klienta",
            LONG_CELLS,
            (),
            id="przekazanie-dalej",
        ),
        pytest.param(
            f"{LONG}\n---------- Wiadomość przekazana dalej ----------\n40000002 nie brak klienta",
            LONG_CELLS,
            (),
            id="wiadomosc-przekazana-dalej",
        ),
        pytest.param(
            "40000001 tak router ４００００００２ nie brak",
            ((0, "tak", "router ４００００００２ nie brak"),),
            (),
            id="cyfry-spoza-ascii-to-opis",
        ),
    ],
)
def test_opis_wpisu_ciagnie_sie_przez_kolejne_linie_do_nastepnego_wpisu_podpisu_albo_cytatu(
    text: str, entered: tuple[tuple[int, str, str], ...], problems: tuple[ReportProblem, ...]
) -> None:
    """US 19, 20, 23, 24: łamanie linii w opisie to pojedyncza spacja, a Wpis zaczyna numer w kształcie numeru zlecenia
    (tyle cyfr co najkrótszy numer zlecenia) ze znakiem po nim albo na początku linii; krótsza liczba to słowo opisu.
    Literówka w numerze daje problem i nie dokleja się do opisu poprzedniego Wpisu."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], [*_orders(), *EWA_ORDERS]))

    assert outcome.changes == _cells(entered)
    assert outcome.problems == problems


@pytest.mark.parametrize(
    ("numbers", "problems"),
    [
        pytest.param(("40000001", "400002"), (_unknown("400099", AddBar.FORM),), id="najkrotszy-numer-ma-6-cyfr"),
        pytest.param(("40000001", "40000002"), (), id="najkrotszy-numer-ma-8-cyfr"),
    ],
)
@pytest.mark.parametrize("second_day", [DAY, date(2026, 11, 9)], ids=["dzis", "po-dzis"])
def test_ksztalt_numeru_zlecenia_wyznacza_najkrotszy_numer_odczytanego_zlecenia(
    numbers: tuple[str, ...], problems: tuple[ReportProblem, ...], second_day: date
) -> None:
    """Numer drugiego zlecenia wyznacza kształt numeru także wtedy, gdy zlecenie stoi w dniu po dziś: o tym, jakie numery
    ma INTERMAX, mówi każde odczytane zlecenie (#1367 r4)."""

    orders = [_order(ROWS[0], number=numbers[0]), _order(ROWS[1], number=numbers[1], day=second_day)]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "40000001 tak router\n400099 nie brak")], orders))

    assert outcome.problems == problems


def test_raport_z_dnia_bez_zlecen_w_dniach_otwartych_daje_problem_numeru() -> None:
    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "Dzień dobry 12 tak router")], []))

    assert outcome.problems == (_unknown("12", AddBar.FORM),)


_WHITESPACE = st.sampled_from([" ", "  ", "\n", " \n ", "\t", "\r\n"])


@PROPERTY
@given(st.lists(_WHITESPACE, min_size=40, max_size=40))
def test_wlasnosc_dowolne_lamanie_linii_miedzy_slowami_daje_te_same_komorki(gaps: list[str]) -> None:
    """US 19, 24: granica Wpisu i opis nie zależą od tego, gdzie Wykonawca albo jego program pocztowy złamał linię.
    Zawijanie (także ``format=flowed``) nie robi pustych linii, a pusta linia kończy opis."""

    words = [word for number, (verdict, activities) in zip(NUMBERS, _EXPECTED, strict=True) for word in (number, verdict, *activities.split())]
    text = words[0] + "".join(gap + word for gap, word in zip(gaps, words[1:], strict=False))

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], _orders()))

    assert outcome.changes == tuple(
        change for row, (word, activities) in zip(ROWS, _EXPECTED, strict=True) for change in _both(row, word, activities)
    )
    assert outcome.problems == ()


# --- Koniec opisu Wpisu (#1228 runda 3): tylko wyliczone znaczniki, reszta pod opisem należy do opisu ---

ROUTER = "40000001 tak wymiana routera"
ROUTER_CELLS = ((0, "tak", "wymiana routera"),)
TWO = f"{ROUTER}\n40000002 nie brak klienta"
TWO_CELLS = ((0, "tak", "wymiana routera"), (1, "nie", "brak klienta"))


@pytest.mark.parametrize(
    ("text", "entered"),
    [
        pytest.param(f"{TWO}\n\nJan", TWO_CELLS, id="pusta-linia-i-imie"),
        pytest.param(f"{ROUTER}\n\nJan Testowy\ntel. 600 100 200", ROUTER_CELLS, id="pusta-linia-imie-nazwisko-telefon"),
        pytest.param(
            f"{ROUTER}\n\nJan Testowy\nTechnik serwisu\nFirma Testowa Sp. z o.o.", ROUTER_CELLS, id="pusta-linia-podpis-outlooka"
        ),
        pytest.param(f"{TWO}\n\nJutro dokończę 40000003", TWO_CELLS, id="pusta-linia-i-zdanie-z-numerem"),
        pytest.param(f"{ROUTER}\n \t \nJan", ROUTER_CELLS, id="linia-z-samych-bialych-znakow"),
        pytest.param(f"{ROUTER}\n\n40000002 nie brak klienta", TWO_CELLS, id="pusta-linia-miedzy-wpisami"),
        pytest.param("40000001 tak\n\nwymiana routera", ((0, "tak", ""),), id="opis-po-pustej-linii-to-granica"),
        pytest.param(f"{TWO}\nJan", ((0, "tak", "wymiana routera"), (1, "nie", "brak klienta Jan")), id="imie-bez-pustej-linii-to-granica"),
        pytest.param(f"{ROUTER}\nDziekuje\nJan", ROUTER_CELLS, id="dziekuje-bez-polskich-liter"),
        pytest.param(f"{ROUTER}\nDZIĘKUJĘ!", ROUTER_CELLS, id="dziekuje-wielkimi-literami"),
        pytest.param(f"{ROUTER}\nDzięki, Jan", ROUTER_CELLS, id="dzieki"),
        pytest.param(f"{ROUTER}\ndzieki", ROUTER_CELLS, id="dzieki-bez-polskich-liter"),
        pytest.param(f"{ROUTER}\nZ powazaniem\nJan Testowy", ROUTER_CELLS, id="z-powazaniem-bez-polskich-liter"),
        pytest.param(f"{ROUTER}\nPzdr Jan", ROUTER_CELLS, id="pzdr"),
        pytest.param(f"{ROUTER}\nPozdro!", ROUTER_CELLS, id="pozdro"),
        pytest.param(f"{ROUTER}\nPozdrawiam serdecznie\nJan", ROUTER_CELLS, id="pozdrawiam-serdecznie"),
        pytest.param(f"{ROUTER}\nSerdecznie pozdrawiam\nJan", ROUTER_CELLS, id="serdecznie-pozdrawiam"),
        pytest.param(f"{ROUTER}\nMiłego dnia", ROUTER_CELLS, id="milego-dnia"),
        pytest.param(f"{ROUTER}\nmilego dnia.", ROUTER_CELLS, id="milego-dnia-bez-polskich-liter"),
        pytest.param(f"{ROUTER}\nMiłego wieczoru", ROUTER_CELLS, id="milego-wieczoru"),
        pytest.param(f"{ROUTER} serdecznie pozdrawiam", ROUTER_CELLS, id="pozegnanie-w-tej-samej-linii"),
        pytest.param(f"{ROUTER}, pozdrawiam Jan Testowy", ROUTER_CELLS, id="pozegnanie-i-podpis-w-tej-samej-linii"),
        pytest.param(f"{ROUTER} z poważaniem Jan Testowy", ROUTER_CELLS, id="dwuwyrazowe-pozegnanie-i-podpis-w-tej-samej-linii"),
        pytest.param(
            f"{ROUTER}, pozdrawiam\nJan Testowy technik serwisu", ROUTER_CELLS, id="pozegnanie-na-koncu-linii-i-podpis-pod-nim"
        ),
        pytest.param(
            "40000001 tak wymiana dzięki drabinie", ((0, "tak", "wymiana dzięki drabinie"),), id="dzieki-w-srodku-linii-to-opis"
        ),
        pytest.param(
            "40000001 tak wymiana routera, klient dziękuje za szybką obsługę",
            ((0, "tak", "wymiana routera, klient dziękuje za szybką obsługę"),),
            id="dziekuje-w-srodku-zdania-to-opis",
        ),
        pytest.param(
            "40000001 tak wymiana routera, klient dziękuje\nza szybką obsługę",
            ((0, "tak", "wymiana routera, klient"),),
            id="dziekuje-na-koncu-zawinietej-linii-to-granica",
        ),
        pytest.param(
            "40000001 tak przekazałem pozdrowienia od szefa, router wymieniony",
            ((0, "tak", "przekazałem pozdrowienia od szefa, router wymieniony"),),
            id="pozdrowienia-w-srodku-zdania-to-opis",
        ),
        pytest.param(f"{ROUTER}\nSent from my iPhone", ROUTER_CELLS, id="stopka-sent-from"),
        pytest.param(f"{ROUTER}\nGet Outlook for Android", ROUTER_CELLS, id="stopka-get-outlook"),
        pytest.param(
            "Zlecenie 40000001 tak wymiana routera\nZlecenie 40000002 nie brak klienta", TWO_CELLS, id="przedrostek-zlecenie"
        ),
        pytest.param("Nr 40000001 tak wymiana routera\nNr 40000002 nie brak klienta", TWO_CELLS, id="przedrostek-nr"),
        pytest.param(
            "zl. 40000001 - tak wymiana routera\nzl. 40000002 - nie, brak klienta", TWO_CELLS, id="przedrostek-zl-z-kropka"
        ),
        pytest.param(f"{ROUTER}\nZlec. #40000002 nie brak klienta", TWO_CELLS, id="przedrostek-zlec-z-krzyzykiem"),
        pytest.param(f"{ROUTER}\nNr. 40000002 nie brak klienta", TWO_CELLS, id="przedrostek-nr-z-kropka"),
        pytest.param(f"{ROUTER}\nZlecenie nr 40000002 nie brak klienta", TWO_CELLS, id="dwa-przedrostki"),
        pytest.param(f"{ROUTER}\n2. Zlecenie 40000002 nie brak klienta", TWO_CELLS, id="znacznik-listy-i-przedrostek"),
        pytest.param(f"{ROUTER} zl. 40000002 nie brak klienta", TWO_CELLS, id="przedrostek-w-srodku-linii"),
        pytest.param(
            "40000001 tak wymiana routera wysłano z serwisu\n40000002 nie brak klienta",
            ((0, "tak", "wymiana routera wysłano z serwisu"), (1, "nie", "brak klienta")),
            id="slowa-stopki-w-srodku-linii-przed-nastepnym-wpisem-to-opis",
        ),
        pytest.param(
            f"{ROUTER}\nW dniu pon., 8 lis 2026 o 12:00\nJan Testowy\n<jan@przyklad.invalid> napisał(a):\n"
            "40000002 nie brak klienta",
            ROUTER_CELLS,
            id="naglowek-cytatu-zawiniety-na-trzy-linie",
        ),
    ],
)
def test_opis_wpisu_konczy_pusta_linia_pozegnanie_z_tabeli_albo_przedrostek_nastepnego_numeru(
    text: str, entered: tuple[tuple[int, str, str], ...]
) -> None:
    """US 23, 24: podpis, imię i zdanie pod pustą linią, pożegnanie (także bez polskich liter i potoczne) ani słowo
    ``Zlecenie``/``Nr``/``Zl.`` przed numerem następnego Wpisu nie trafiają do ``CZYNNOŚCI ZREALIZOWANE``. Opis kończą
    tylko wyliczone znaczniki, więc imię bez pustej linii pod opisem i opis dopiero pod pustą linią to nazwane granice.
    Pożegnanie w środku zdania opisu (``klient dziękuje za szybką obsługę``) opisu nie ucina, a pożegnanie w środku linii
    z najwyżej dwoma słowami do jej końca ucina, więc zdanie opisu złamane tuż po ``dziękuje`` to nazwana granica."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], _orders()))

    assert outcome.changes == _cells(entered)
    assert outcome.problems == ()


def test_poprawiony_mail_zdejmuje_ostrzezenie_tylko_nieczytelnego_maila_sprzed_niego() -> None:
    """Dwa maile z tematem bez dnia i jeden Raport z dniem między nimi: ostrzeżenie zostaje tylko przy mailu, który
    przyszedł po poprawce."""

    before = _mail(JAN, "Raport", "40000001 tak wymiana", EVENING, "<1@przyklad.invalid>")
    corrected = _mail(JAN, SUBJECT, "40000001 tak wymiana", EVENING + timedelta(minutes=1), "<2@przyklad.invalid>")
    after = _mail(JAN, "Raport", "40000001 tak wymiana", EVENING + timedelta(minutes=2), "<3@przyklad.invalid>")

    outcome = enter_reports(_inputs([before, corrected, after], [_order()]))

    assert outcome.problems == (
        UnreadableSubject(after.id, Login("jan.testowy"), EVENING + timedelta(minutes=2), SubjectFault.NO_DATE),
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_poprawiony_mail_nie_zdejmuje_ostrzezenia_drugiego_nieczytelnego_maila_z_tym_samym_message_id(reverse: bool) -> None:
    """Dwa maile z tematem bez dnia, z tym samym Message-ID i chwilą przyjścia, i późniejszy Raport, który poprawia
    tylko jeden z nich: ostrzeżenie zostaje w każdej kolejności maili na wejściu."""

    unreadable = [
        _mail(JAN, "Raport", "40000001 tak wymiana", EVENING, "<1@przyklad.invalid>"),
        _mail(JAN, "Raport", "kurier jutro", EVENING, "<1@przyklad.invalid>"),
    ]
    corrected = _mail(JAN, SUBJECT, "40000001 tak wymiana", EVENING + timedelta(minutes=1), "<2@przyklad.invalid>")

    outcome = enter_reports(_inputs([*(unreadable[::-1] if reverse else unreadable), corrected], [_order()]))

    assert outcome.problems == (UnreadableSubject(unreadable[0].id, Login("jan.testowy"), EVENING, SubjectFault.NO_DATE),)


def test_dwa_nieczytelne_tematy_z_jednym_message_id_chwila_i_powodem_rozstrzygaja_numery_wpisow() -> None:
    """Remis ``(arrived, MailId)`` i powodu nieczytelnego tematu rozstrzygają numery Wpisów treści, nie kolejność maili
    na wejściu."""

    mails = [
        _mail(JAN, "Raport", "40000001 tak wymiana", EVENING, "<1@przyklad.invalid>"),
        _mail(JAN, "Raport", "40000002 tak wymiana", EVENING, "<1@przyklad.invalid>"),
    ]

    outcomes = [enter_reports(_inputs(order, [_order()])) for order in (mails, mails[::-1])]

    assert outcomes[0] == outcomes[1]
    assert [read.numbers for read in outcomes[0].mails if isinstance(read, ReadUnreadable)] == [
        frozenset({OrderNumber("40000001")}),
        frozenset({OrderNumber("40000002")}),
    ]


def test_dwa_nieczytelne_tematy_z_jednym_message_id_i_chwila_przyjscia_daja_ten_sam_wynik_w_kazdej_kolejnosci() -> None:
    """Remis ``(arrived, MailId)`` nieczytelnych tematów rozstrzyga powód, nie kolejność maili na wejściu."""

    mails = [
        _mail(JAN, "Raport 08.11", TEXT, EVENING, "<1@przyklad.invalid>"),
        _mail(JAN, "Raport 08.11.226", TEXT, EVENING, "<1@przyklad.invalid>"),
    ]

    outcomes = [enter_reports(_inputs(order, [_order()])) for order in (mails, mails[::-1])]

    assert outcomes[0] == outcomes[1]
    assert {read.fault for read in outcomes[0].mails if isinstance(read, ReadUnreadable)} == {
        SubjectFault.NO_YEAR,
        SubjectFault.YEAR_DIGITS,
    }


# --- Stopka w środku ostatniej linii i sprzeczne Wpisy jednego numeru (Część #1224, przegląd prawdziwych Raportów) ---

FOOTER_ORDERS = [_order(row, number=number) for row, number in zip(ROWS, NUMBERS, strict=True)]


@pytest.mark.parametrize(
    ("text", "entered"),
    [
        pytest.param(
            "40000001 tak inst25m  40000002 nie klientka nie wyraża zgody  40000003 tak   Wysłano z aplikacji mobilnej Poczty o2",
            ((0, "tak", "inst25m"), (1, "nie", "klientka nie wyraża zgody"), (2, "tak", "")),
            id="poczta-o2-po-wpisie-bez-opisu",
        ),
        pytest.param(
            "40000001 tak 40000002 nie   40000003 tak montaż   Wysłano z aplikacji mobilnej WP Poczty",
            ((0, "tak", ""), (1, "nie", ""), (2, "tak", "montaż")),
            id="wp-poczta-po-opisie",
        ),
        pytest.param(f"{ROUTER}   Wysłane z iPhone'a", ROUTER_CELLS, id="wyslane-z"),
        pytest.param(f"{ROUTER}   Wysłane ze smartfona Samsung Galaxy", ROUTER_CELLS, id="wyslane-ze"),
        pytest.param(f"{ROUTER} Sent from my iPhone", ROUTER_CELLS, id="sent-from-po-jednej-spacji"),
        pytest.param(f"{ROUTER}   GET OUTLOOK FOR ANDROID", ROUTER_CELLS, id="get-outlook-wielkimi-literami"),
        pytest.param(f"{ROUTER}   Wysłano z aplikacji mobilnej Poczty o2\n\n \t\n", ROUTER_CELLS, id="pod-stopka-biale-znaki"),
        pytest.param(
            f"{ROUTER}   Wysłano z aplikacji mobilnej Poczty o2\n\nW dniu pon., 8 lis 2026 o 12:00 Jan "
            "<jan@przyklad.invalid> napisał(a):\n> 40000002 nie brak klienta",
            ROUTER_CELLS,
            id="pod-stopka-cytat-gmaila",
        ),
        pytest.param(
            f"{ROUTER}   Wysłano z aplikacji mobilnej Poczty o2\n> 40000002 nie brak klienta",
            ROUTER_CELLS,
            id="pod-stopka-linie-cytatu",
        ),
        pytest.param(
            f"{ROUTER} pozdrawiam Jan   Wysłano z aplikacji mobilnej Poczty o2", ROUTER_CELLS, id="pozegnanie-podpis-i-stopka"
        ),
        pytest.param(
            f"{ROUTER}\n40000002 nie brak klienta   Sent from my iPhone",
            TWO_CELLS,
            id="stopka-w-drugiej-linii-wpisu",
        ),
        pytest.param(
            "40000001 tak wymiana routera,\nmontaż 2 gniazd   Wysłano z aplikacji mobilnej Poczty o2",
            LONG_CELLS,
            id="stopka-w-zawinietej-linii-opisu",
        ),
        pytest.param(
            "40000001 nie sprzęt wysłano z magazynu 40000002 tak",
            ((0, "nie", "sprzęt wysłano z magazynu"), (1, "tak", "")),
            id="slowa-stopki-przed-kolejnym-wpisem-to-opis",
        ),
        pytest.param(
            "40000001 nie sprzęt wysłano z magazynu 40000002 tak   Wysłano z aplikacji mobilnej Poczty o2",
            ((0, "nie", "sprzęt wysłano z magazynu"), (1, "tak", "")),
            id="slowa-stopki-w-opisie-i-stopka-na-koncu-linii",
        ),
        pytest.param(
            "40000001 nie sprzęt wysłano z magazynu\nkurier jutro",
            ((0, "nie", "sprzęt wysłano z magazynu kurier jutro"),),
            id="slowa-stopki-przed-tekstem-w-nastepnej-linii-to-opis",
        ),
        pytest.param(
            "40000001 nie sprzęt wysłano z magazynu\n\nJan",
            ((0, "nie", "sprzęt wysłano z magazynu"),),
            id="slowa-stopki-przed-tekstem-pod-pusta-linia-to-opis",
        ),
        pytest.param(
            "40000001 nie sprzęt wysłano z magazynu", ((0, "nie", "sprzęt"),), id="slowa-stopki-do-konca-tresci-to-stopka"
        ),
    ],
)
def test_stopka_aplikacji_pocztowej_w_srodku_ostatniej_linii_nie_trafia_do_opisu(
    text: str, entered: tuple[tuple[int, str, str], ...]
) -> None:
    """US 23: aplikacja pocztowa pisze raport w jednej linii, a stopkę na jej końcu. Stopka z wyliczonych (``Wysłano z``,
    ``Wysłane z``/``ze``, ``Sent from``, ``Get Outlook for``), która zaczyna się w środku ostatniej linii treści i biegnie
    do jej końca, a pod nią są tylko białe znaki albo cytat, kończy opis jak stopka w osobnej linii. Takie słowa, po
    których stoi kolejny Wpis albo tekst w tej linii lub pod nią, to opis; te same słowa na samym końcu treści to
    stopka, bo rdzeń ich od stopki nie odróżni."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], FOOTER_ORDERS))

    assert outcome.changes == _cells(entered)
    assert outcome.problems == ()


_FOOTERS = (
    "Wysłano z aplikacji mobilnej Poczty o2",
    "WYSŁANO Z APLIKACJI MOBILNEJ WP POCZTY",
    "Wysłane z iPhone'a",
    "wysłane ze smartfona",
    "Sent from my iPhone",
    "Get Outlook for Android",
)


@PROPERTY
@given(
    st.lists(st.sampled_from(["montaż", "z", "from", "routera", "2", "gniazda", "Outlook", "for", "aplikacji", "wysłanie"]), max_size=5),
    st.sampled_from(_FOOTERS),
    st.sampled_from([" ", "  ", "\t", "\xa0 ", "   "]),
    st.sampled_from([("", ""), ("\n", ""), ("\n\n \t\n", ""), ("\n> 40000002 nie brak klienta", ""), ("\nkurier jutro", "kurier jutro")]),
    st.sampled_from([None, "\n", "  ", "\n\n"]),
)
def test_wlasnosc_stopka_konczy_opis_tylko_na_koncu_ostatniej_linii_tresci(
    words: list[str], footer: str, gap: str, tail: tuple[str, str], more: str | None
) -> None:
    """US 23: stopka po dowolnych słowach opisu, w dowolnej wielkości liter i po dowolnych odstępach, z samymi białymi
    znakami albo cytatem pod nią, nie trafia do opisu. Gdy po niej stoi kolejny Wpis (``more``), w tej samej linii albo
    niżej, albo tekst w następnej linii, należy do opisu."""

    after, kept = tail
    text = f"40000001 tak {' '.join(words)}{gap}{footer}"
    if more is None:
        entered = [(0, "tak", " ".join([*words, *footer.split(), kept] if kept else words))]
    else:
        text += f"{more}40000002 nie brak klienta"
        entered = [(0, "tak", " ".join([*words, *footer.split()])), (1, "nie", " ".join(filter(None, ["brak klienta", kept])))]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text + after)], FOOTER_ORDERS))

    assert outcome.changes == _cells(entered)


CONFLICT_ORDERS = [
    _order(OrderRow("Zlecenia", 130), number="40000010"),
    _order(OrderRow("Zlecenia", 131), number="40000011"),
    _order(OrderRow("Zlecenia", 132), number="40000012"),
]
CONFLICT = "40000010 tak\n40000011 tak inst25m\n40000011 nie brak klienta od umowy\n40000012 tak"


def _said(number: str, verdict: Verdict, activities: str) -> ReportEntry:
    return ReportEntry(OrderNumber(number), verdict, None, activities)


def _signed(number: str, fault: VerdictFault, activities: str) -> ReportEntry:
    return ReportEntry(OrderNumber(number), None, fault, activities)


def _conflict(mail: ReportMail, *entries: ReportEntry, number: str = "40000011") -> ConflictingVerdicts:
    return ConflictingVerdicts(JAN_LOGIN, DAY, OrderNumber(number), mail.id, mail.arrived, entries)


def test_tak_i_nie_jednego_zlecenia_w_jednym_mailu_niczego_do_niego_nie_wpisuja_a_tata_dostaje_oba_wpisy() -> None:
    """Decyzja Maksa 11.11: ten sam numer z ``tak`` i z ``nie`` w treści jednego maila to ostrzeżenie z Wykonawcą,
    mailem (dzień z tematu, chwila przyjścia), numerem i oboma Wpisami; do tego zlecenia Centrum nie wpisuje nic, a
    pozostałe Wpisy maila wpisuje."""

    mail = _mail(JAN, SUBJECT, CONFLICT)

    outcome = enter_reports(_inputs([mail], CONFLICT_ORDERS))

    assert outcome.changes == (
        CellChange(OrderRow("Zlecenia", 130), ReportColumn.SUCCESSFUL, "tak"),
        CellChange(OrderRow("Zlecenia", 132), ReportColumn.SUCCESSFUL, "tak"),
    )
    assert outcome.problems == (
        _conflict(mail, _said("40000011", Verdict.YES, "inst25m"), _said("40000011", Verdict.NO, "brak klienta od umowy")),
    )
    assert outcome.memory.entries == {
        OwnEntry(_key("40000010"), ReportColumn.SUCCESSFUL, "tak"),
        OwnEntry(_key("40000012"), ReportColumn.SUCCESSFUL, "tak"),
    }
    assert [(worker.entered, worker.problems, worker.without_report) for worker in outcome.workers] == [(2, 1, ())]


@pytest.mark.parametrize(
    ("text", "changes", "problems"),
    [
        pytest.param(
            "40000011 tak inst25m\n40000011 tak montaż", _both(ROW, "tak", "inst25m"), (), id="ten-sam-tak-pierwszy-wpis"
        ),
        pytest.param(
            "40000011 nie brak klienta 40000011 NIE, nikt nie otworzył",
            _both(ROW, "nie", "brak klienta"),
            (),
            id="to-samo-nie-w-jednej-linii-pierwszy-wpis",
        ),
        pytest.param(
            "40000011 inst25m\n40000011 tak montaż", _both(ROW, "tak", "montaż"), (), id="wpis-bez-znaku-i-wpis-z-tak"
        ),
        pytest.param(
            "40000011 t wymiana\n40000011 tak montaż", _both(ROW, "tak", "montaż"), (), id="litera-i-tak-w-zgodzie-liczy-sie-tak"
        ),
        pytest.param(
            "40000011 nieskuteczne\n40000011 n\n40000011 NIE brak klienta",
            _both(ROW, "nie", "brak klienta"),
            (),
            id="slowo-litera-i-nie-w-zgodzie-liczy-sie-nie",
        ),
        pytest.param(
            "40000011 inst25m\n40000011 t montaż",
            (),
            (MissingVerdict(JAN_LOGIN, DAY, OrderNumber("40000011"), VerdictFault.MISSING),),
            id="dwa-wpisy-bez-tak-nie-pierwszy-wpis",
        ),
        pytest.param(
            "40000011 skuteczne\n40000011 t montaż\n40000011 inst25m",
            (),
            (MissingVerdict(JAN_LOGIN, DAY, OrderNumber("40000011"), VerdictFault.WORD_YES),),
            id="slowo-i-litera-w-zgodzie-pierwszy-wpis",
        ),
        pytest.param(
            "40000011 tak inst25m\n\nW dniu pon., 8 lis 2026 o 12:00 Jan <jan@przyklad.invalid> napisał(a):\n"
            "> 40000011 nie brak klienta",
            _both(ROW, "tak", "inst25m"),
            (),
            id="nie-tylko-w-cytacie",
        ),
    ],
)
def test_z_wpisow_numeru_w_jednym_mailu_liczy_sie_pierwszy_z_tak_albo_nie(
    text: str, changes: tuple[CellChange, ...], problems: tuple[ReportProblem, ...]
) -> None:
    """Decyzje Maksa 11.11 (D13): z Wpisów numeru w treści maila (cytat do niej nie należy), których litera albo słowo
    nie mają przeciwnego zamiaru, liczy się pierwszy z ``tak`` albo ``nie``, a Wpis bez nich tylko wtedy, gdy żaden
    ich nie ma (pierwszy)."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], [_order(number="40000011")]))

    assert (outcome.changes, outcome.problems) == (changes, problems)


@pytest.mark.parametrize(
    ("text", "entries"),
    [
        pytest.param(
            "40000011 nie\n40000011 inst25m\n40000011 tak montaż\n40000011 nie brak klienta",
            (_said("40000011", Verdict.NO, ""), _said("40000011", Verdict.YES, "montaż")),
            id="pierwszy-wpis-z-kazdym-znakiem-w-kolejnosci-maila",
        ),
        pytest.param(
            "40000011 tak inst25m   40000011 nie brak klienta   Wysłano z aplikacji mobilnej Poczty o2",
            (_said("40000011", Verdict.YES, "inst25m"), _said("40000011", Verdict.NO, "brak klienta")),
            id="w-jednej-linii-ze-stopka",
        ),
        pytest.param(
            "#40000011 Tak, inst25m\nZlecenie 40000011 - nie: brak klienta",
            (_said("40000011", Verdict.YES, "inst25m"), _said("40000011", Verdict.NO, "brak klienta")),
            id="z-krzyzykiem-przedrostkiem-i-interpunkcja",
        ),
        pytest.param(
            "40000011 t wymiana\n40000011 nie brak klienta",
            (_signed("40000011", VerdictFault.LETTER_YES, "wymiana"), _said("40000011", Verdict.NO, "brak klienta")),
            id="litera-t-i-nie",
        ),
        pytest.param(
            "40000011 nie brak klienta\n40000011 Skuteczne",
            (_said("40000011", Verdict.NO, "brak klienta"), _signed("40000011", VerdictFault.WORD_YES, "")),
            id="nie-i-slowo-skuteczne",
        ),
        pytest.param(
            "40000011 t wymiana 40000011 N. brak klienta",
            (_signed("40000011", VerdictFault.LETTER_YES, "wymiana"), _signed("40000011", VerdictFault.LETTER_NO, "brak klienta")),
            id="litery-t-i-n-bez-tak-nie",
        ),
        pytest.param(
            "40000011 nieskuteczne brak klienta\n40000011 inst25m\n40000011 tak montaż",
            (_signed("40000011", VerdictFault.WORD_NO, "brak klienta"), _said("40000011", Verdict.YES, "montaż")),
            id="slowo-nieskuteczne-wpis-bez-znaku-i-tak",
        ),
        pytest.param(
            "40000011 t wymiana\n40000011 tak montaż\n40000011 nie brak klienta",
            (_signed("40000011", VerdictFault.LETTER_YES, "wymiana"), _said("40000011", Verdict.NO, "brak klienta")),
            id="pierwszy-wpis-zamiaru-takze-z-litera",
        ),
    ],
)
def test_ostrzezenie_o_przeciwnym_zamiarze_wpisow_numeru_ma_pierwszy_wpis_kazdego_zamiaru_w_kolejnosci_maila(
    text: str, entries: tuple[ReportEntry, ...]
) -> None:
    """Decyzja Maksa 11.11 (D13): litera ``t``/``n`` i słowo ``skuteczne``/``nieskuteczne`` niosą zamiar, więc Wpis z
    nimi przeciw Wpisowi z ``tak``/``nie`` albo z przeciwną literą lub słowem to też sprzeczność."""
    mail = _mail(JAN, SUBJECT, text)

    outcome = enter_reports(_inputs([mail], [_order(number="40000011")]))

    assert (outcome.changes, outcome.problems) == ((), (_conflict(mail, *entries),))


@pytest.mark.parametrize("reverse", [False, True])
def test_pozniejszy_mail_z_jednym_wpisem_numeru_rozwiazuje_ostrzezenie_a_pozniejsze_sprzeczne_wpisy_je_daja(
    reverse: bool,
) -> None:
    """US 37, 40: o zleceniu decyduje najpóźniejszy mail, także w kolejnym kliknięciu: jasny Wpis po sprzecznych daje
    wpis bez ostrzeżenia, a sprzeczne Wpisy po jasnym dają ostrzeżenie i nie wpisują niczego nowego, a własny wpis z
    wcześniejszego kliknięcia zostaje w komórce i pamięci. Zdanie ostrzeżenia jest prawdziwe przy pustej komórce i przy
    własnym wpisie w niej: Centrum nie zmienia zlecenia przy tym kliknięciu, a nie „nic do niego nie wpisało”."""

    conflict = _mail(JAN, SUBJECT, CONFLICT)
    fixed = _mail(JAN, SUBJECT, "40000011 nie brak klienta od umowy", LATER)
    late_conflict = _mail(JAN, SUBJECT, CONFLICT, LATER + timedelta(hours=1))
    orders = CONFLICT_ORDERS

    first = enter_reports(_inputs([conflict], orders))
    second = enter_reports(_inputs([fixed, conflict][:: -1 if reverse else 1], orders, memory=first.memory))
    written = [replace(order, successful="nie", completed="brak klienta od umowy") if order.key.number == "40000011" else order for order in orders]
    third = enter_reports(_inputs([conflict, fixed, late_conflict], written, memory=second.memory))

    assert [type(problem) for problem in first.problems] == [ConflictingVerdicts]
    assert second.problems == ()
    assert _both(OrderRow("Zlecenia", 131), "nie", "brak klienta od umowy") == tuple(
        change for change in second.changes if change.order == OrderRow("Zlecenia", 131)
    )
    assert third.problems == (
        _conflict(
            late_conflict, _said("40000011", Verdict.YES, "inst25m"), _said("40000011", Verdict.NO, "brak klienta od umowy")
        ),
    )
    assert [change for change in third.changes if change.order == OrderRow("Zlecenia", 131)] == []
    for problem in (*first.problems, *third.problems):
        assert "Centrum nie zmieniło tego zlecenia przy tym kliknięciu." in reason(problem)
        assert "nie wpisało" not in reason(problem)
    assert {entry for entry in third.memory.entries if entry.key.number == "40000011"} == {
        OwnEntry(_key("40000011"), ReportColumn.SUCCESSFUL, "nie"),
        OwnEntry(_key("40000011"), ReportColumn.COMPLETED, "brak klienta od umowy"),
    }


def test_postac_kanoniczna_maila_ze_sprzecznymi_wpisami_daje_te_same_wpisy_i_ostrzezenie() -> None:
    """Odtworzenie z Logów (#1233): mail z ``as_mail`` w miejscu maila ze sprzecznymi Wpisami daje ten sam odczyt (oba
    Wpisy numeru) i to samo ostrzeżenie."""

    mail = _mail(JAN, SUBJECT, f"{CONFLICT}   Wysłano z aplikacji mobilnej Poczty o2")
    outcome = enter_reports(_inputs([mail], CONFLICT_ORDERS))
    sender = SenderAddress.of(JAN)
    assert sender is not None

    again = enter_reports(_inputs([as_mail(read, sender) for read in outcome.mails], CONFLICT_ORDERS))

    assert again == outcome
    assert [type(problem) for problem in again.problems] == [ConflictingVerdicts]


# Zlecenie dopisane z raportu (#1354, ADR 0029): Wpis numeru z aplikacji firmowej (8 cyfr), którego INTERMAX nie ma w
# żadnym odczytanym dniu, dopisuje zlecenie pod zleceniami nadawcy w dniu z tematu, gdy ten jest Dniem uporządkowanym.

ADDED = "40000077"
ADDED_TEXT = f"{ADDED} tak montaż ONT"


def _added(
    worker: str = "Jan.Testowy", successful: str = "tak", completed: str | None = "montaż ONT", sheet: str = ROW.sheet
) -> OrderAdded:
    return OrderAdded(sheet, DAY, worker, ADDED, successful, completed)


def _added_note(worker: Login = JAN_LOGIN) -> Added:
    return Added(DAY, worker, OrderNumber(ADDED))


def test_numer_z_aplikacji_spoza_dni_otwartych_to_zlecenie_dopisane_pod_zleceniami_nadawcy_w_dniu_z_tematu() -> None:
    """Kryterium #1354 (US 17, 18, 22): numer z 8 cyframi, którego nie ma w żadnym dniu, dopisuje się z pisownią
    ``WYKONAWCA`` nadawcy, ``tak`` i czynnościami z Wpisu, z informacją dla taty, bez problemu; pamięć ma jego komórki jak
    własne wpisy i zlecenie jako dopisane, a widok liczy je na końcu zleceń nadawcy."""

    orders = [_order(), _order(OrderRow("Zlecenia", 121), number="40000002", worker="Ewa.Probna")]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, ADDED_TEXT)], orders, ordered=[DAY]))

    assert outcome.added == (_added(),)
    assert (outcome.changes, outcome.moves, outcome.problems) == ((), (), ())
    assert outcome.notes == (_added_note(),)
    key = _key(ADDED)
    assert {entry for entry in outcome.memory.entries if entry.key == key} == {
        OwnEntry(key, ReportColumn.SUCCESSFUL, "tak"),
        OwnEntry(key, ReportColumn.COMPLETED, "montaż ONT"),
    }
    assert outcome.memory.moves == {
        OwnMove(OrderNumber(ADDED), DAY, JAN_LOGIN, DAY, JAN_LOGIN, "Jan.Testowy", EVENING, added=True)
    }
    [jan] = [worker for worker in outcome.workers if worker.worker == JAN_LOGIN]
    assert (jan.orders, jan.entered, jan.without_report) == (2, 1, (OrderNumber("40000001"),))
    assert jan.orders_detail[-1] == OrderDetail(OrderNumber(ADDED), "tak", "montaż ONT", True)


@pytest.mark.parametrize(
    ("text", "orders", "ordered", "problem"),
    [
        pytest.param(
            "4000007 tak montaż",
            [_order(number="4000001")],
            [DAY],
            UnknownNumber(JAN_LOGIN, DAY, OrderNumber("4000007"), AddBar.FORM),
            id="7-cyfr",
        ),
        pytest.param(
            "400000077 tak montaż",
            [_order()],
            [DAY],
            UnknownNumber(JAN_LOGIN, DAY, OrderNumber("400000077"), AddBar.FORM),
            id="9-cyfr",
        ),
        pytest.param(
            f"40000003 tak a\n40000004 nie b\n{ADDED_TEXT}",
            [
                _order(OrderRow("Zlecenia", 121), number="40000003", day=date(2026, 11, 7)),
                _order(OrderRow("Zlecenia", 122), number="40000004", day=date(2026, 11, 7)),
            ],
            [date(2026, 11, 7), DAY],
            UnknownNumber(JAN_LOGIN, DAY, OrderNumber(ADDED), AddBar.MISTAKEN_SUBJECT),
            id="pomylony-temat-z-nowym-numerem",
        ),
        pytest.param(
            ADDED_TEXT,
            [_order(), _order(OrderRow("Zlecenia", 121), number="40000002", day=date(2026, 11, 7))],
            [date(2026, 11, 7)],
            UnknownNumber(JAN_LOGIN, DAY, OrderNumber(ADDED), AddBar.NOT_ORDERED),
            id="dzien-nieuporzadkowany",
        ),
    ],
)
def test_numer_bez_postaci_numeru_z_aplikacji_pomylony_temat_albo_dzien_nieuporzadkowany_daja_problem_bez_dopisania(
    text: str, orders: list[RegisterOrder], ordered: list[date], problem: UnknownNumber
) -> None:
    """Kryteria #1354 (US 19, 21): numer z 7 albo 9 cyframi (gdy jest Wpisem, bo INTERMAX ma numer z 7 cyframi albo
    numer ma więcej cyfr niż najkrótszy), Raport wykonawcy z pomylonym tematem (dwa zlecenia z 7.11) i dzień z tematu,
    który nie jest Dniem uporządkowanym, dają problem z powodem i nic nie dopisują."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], orders, rollout=date(2026, 11, 7), ordered=ordered))

    assert outcome.added == ()
    assert outcome.problems == (problem,)
    assert not any(isinstance(note, Added) for note in outcome.notes)


def test_numer_z_przeczytanego_wiersza_bez_zlecenia_nie_jest_dopisany_i_nie_liczy_sie_do_progu_pomylonego_tematu() -> None:
    """Przegląd #1374 r2 Ważne 1: proces przeczytał w INTERMAX wiersz z numerem, z którego nie powstało zlecenie
    (Surowe zlecenie, wiersz bez ``WYKONAWCA`` albo z datą tekstem, wiersz z wyglądem z aplikacji między
    uporządkowanymi), więc numer jest w ``present`` bez zlecenia w ``orders``. Dopisanie dałoby go dwa razy: problem z
    powodem, bez dopisania. Jego dnia rdzeń nie zna, więc nie jest niezgodnym Wpisem, a jedyne zlecenie Jana z 7.11 dalej
    przechodzi na dzień z tematu."""

    text = f"40000001 tak a\n{ADDED_TEXT}"
    inputs = _inputs([_mail(JAN, SUBJECT, text)], [_order(day=date(2026, 11, 7))], rollout=date(2026, 11, 7), ordered=[date(2026, 11, 7), DAY])

    outcome = enter_reports(replace(inputs, present=(*inputs.present, ReadNumber(OrderNumber(ADDED)))))

    assert outcome.added == ()
    assert outcome.problems == (UnknownNumber(JAN_LOGIN, DAY, OrderNumber(ADDED), AddBar.IN_INTERMAX),)
    assert outcome.moves == (OrderMove(ROW, DAY, "Jan.Testowy"),)
    assert reason(outcome.problems[0]).startswith(f"Zlecenie {ADDED} z Wpisu od jan.testowy z 08.11.2026 jest już w INTERMAX")


def test_numer_obecny_w_innym_otwartym_dniu_nie_jest_dopisany_tylko_przenoszony() -> None:
    """Kryterium #1354 (US 20): numer, który INTERMAX ma w innym otwartym dniu, nie dopisuje drugiego zlecenia, tylko
    idzie regułą #1350 (jeden niezgodny Wpis: Przeniesienie na dzień z tematu)."""

    orders = [_order(day=date(2026, 11, 7))]

    outcome = enter_reports(
        _inputs([_mail(JAN, SUBJECT, "40000001 tak montaż")], orders, rollout=date(2026, 11, 7), ordered=[date(2026, 11, 7), DAY])
    )

    assert outcome.added == ()
    assert outcome.moves == (OrderMove(ROW, DAY, "Jan.Testowy"),)


LATER_ROW = OrderRow("Zlecenia", 125)


def test_numer_z_dnia_po_dzis_nie_jest_dopisany_a_nastepnego_dnia_przechodzi_na_dzien_z_tematu() -> None:
    """Przegląd #1374 r1: tata wkleja i porządkuje zlecenia jutra dzień wcześniej (ADR 0019), więc INTERMAX ma już
    zlecenie 40000055 z 9.11, a Jan zrobił je 8.11 i wpisał do Raportu za 8.11. Kliknięcie 8.11 nie dopisuje go drugi
    raz i niczego nie zmienia w INTERMAX, a tata dostaje problem z tym numerem: dzień zlecenia jeszcze nie nadszedł
    (#1367 r4). Kliknięcie 9.11 widzi zlecenie w dniu otwartym i przenosi je na dzień z tematu z Wpisem (#1350)."""

    orders = [_order(), _order(LATER_ROW, number="40000055", day=NEXT_DAY)]
    mail = _mail(JAN, SUBJECT, "40000055 tak montaż ONT")

    today = enter_reports(_inputs([mail], orders, today=DAY, ordered=[DAY, NEXT_DAY]))
    tomorrow = enter_reports(_inputs([mail], orders, today=NEXT_DAY, rollout=DAY, ordered=[DAY, NEXT_DAY]))

    assert (today.added, today.moves, today.changes) == ((), (), ())
    assert today.problems == (RefusedMove(JAN_LOGIN, DAY, OrderNumber("40000055"), NEXT_DAY, NEXT_DAY, MoveBar.AFTER_TODAY),)
    assert tomorrow.added == ()
    assert tomorrow.moves == (OrderMove(LATER_ROW, DAY, "Jan.Testowy"),)
    assert tomorrow.problems == ()


def test_nowy_numer_w_raporcie_z_dwoma_zleceniami_z_jutra_nie_jest_dopisany_ani_dzis_ani_jutro() -> None:
    """Przegląd #1374 r1 z regułą #1367 r4: Raport Jana za 8.11 ma dwa zlecenia, które INTERMAX ma już w 9.11 (tata
    wkleja jutro dzień wcześniej), i numer, którego INTERMAX nie ma. Dwa niezgodne Wpisy to pomylony temat także dziś,
    bo rdzeń widzi dzień po dziś, więc kliknięcie 8.11 i 9.11 zgadzają się: nowego numeru nie dopisują, a tata dostaje
    problem pomylonego tematu."""

    orders = [
        _order(),
        _order(LATER_ROW, number="40000055", day=NEXT_DAY),
        _order(OrderRow("Zlecenia", 126), number="40000056", day=NEXT_DAY),
    ]
    mail = _mail(JAN, SUBJECT, "40000055 tak montaż\n40000056 tak montaż\n40000099 tak montaż")

    today = enter_reports(_inputs([mail], orders, today=DAY, ordered=[DAY, NEXT_DAY]))
    tomorrow = enter_reports(_inputs([mail], orders, today=NEXT_DAY, rollout=DAY, ordered=[DAY, NEXT_DAY]))

    for outcome in (today, tomorrow):
        assert (outcome.added, outcome.moves) == ((), ())
        assert _unknown("40000099", AddBar.MISTAKEN_SUBJECT) in outcome.problems
    assert today.changes == ()

def test_numery_z_przykladu_przypomnienia_nigdy_nie_daja_dopisania() -> None:
    """Kryterium #1354 i US 50: Wykonawca przepisał przykład z Przypomnienia o raporcie; jego numery mają 8 cyfr i nie ma
    ich w INTERMAX, ale nie są Wpisami, więc nic się nie dopisuje i nie ma problemu."""

    text = "12345678 tak montaż ONT\n12345679 nie brak klienta"

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], [_order()], ordered=[DAY]))

    assert (outcome.added, outcome.changes, outcome.problems, outcome.notes) == ((), (), (), ())


def test_drugie_klikniecie_nie_dubluje_dopisanego_zlecenia_a_informacja_stoi_do_wpisania_adresu() -> None:
    """Kryteria #1354 (US 22, 24): kolejne kliknięcie z tym samym mailem widzi dopisane zlecenie w INTERMAX, więc nic
    nie dopisuje ani nie zmienia; informacja „dopisane z raportu” stoi, dopóki tata nie wpisze ``ADRES``."""

    orders = [_order()]
    mail = _mail(JAN, SUBJECT, ADDED_TEXT)
    first = enter_reports(_inputs([mail], orders, ordered=[DAY]))
    after = _after(orders, first)

    second = enter_reports(_inputs([mail], after, ordered=[DAY], memory=first.memory))
    addressed = [replace(order, addressed=True) if order.key.number == ADDED else order for order in after]
    third = enter_reports(_inputs([mail], addressed, ordered=[DAY], memory=second.memory))

    assert (second.added, second.changes, second.moves, second.problems) == ((), (), (), ())
    assert second.notes == (_added_note(),)
    assert second.memory == first.memory
    assert (third.added, third.changes, third.notes) == ((), (), ())


@pytest.mark.parametrize(
    ("manual", "changed", "differences"),
    [
        pytest.param(None, ("nie", "klient nieobecny"), (), id="poprawka-wykonawcy"),
        pytest.param(
            "montaż ONT i gniazda",
            ("nie",),
            (ManualDifference(_key(ADDED), ReportColumn.COMPLETED, "montaż ONT i gniazda", "klient nieobecny"),),
            id="reczna-wartosc-taty-wygrywa",
        ),
    ],
)
def test_poprawka_wykonawcy_zmienia_komorki_dopisanego_zlecenia_a_reczna_wartosc_wygrywa(
    manual: str | None, changed: tuple[str, ...], differences: tuple[ManualDifference, ...]
) -> None:
    """Kryterium #1354 (US 25): świeższy mail Jana zmienia ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` dopisanego zlecenia,
    bo Centrum samo je wpisało, a wartość, którą tata wpisał ręcznie, zostaje z różnicą."""

    orders = [_order()]
    mail = _mail(JAN, SUBJECT, ADDED_TEXT)
    first = enter_reports(_inputs([mail], orders, ordered=[DAY]))
    after = [
        replace(order, completed=manual) if order.key.number == ADDED and manual is not None else order
        for order in _after(orders, first)
    ]
    fresher = _mail(JAN, SUBJECT, f"{ADDED} nie klient nieobecny", LATER)

    second = enter_reports(_inputs([mail, fresher], after, ordered=[DAY], memory=first.memory))

    [row] = [order.row for order in after if order.key.number == ADDED]
    assert [(change.order, change.value) for change in second.changes] == [(row, value) for value in changed]
    assert second.problems == differences
    assert second.added == ()


def test_dopisane_zlecenie_przejete_przez_innego_wykonawce_dalej_przypomina_o_adresie() -> None:
    """Świeższy mail Ewy przenosi dopisane zlecenie Jana do niej (ADR 0029): informacja o dopisaniu idzie za zleceniem,
    bo pamięć Przeniesienia niesie dopisanie, a obok stoi przejęcie po obu stronach."""

    orders = [_order()]
    mail = _mail(JAN, SUBJECT, ADDED_TEXT)
    first = enter_reports(_inputs([mail], orders, ordered=[DAY]))
    ewa = _mail(EWA, SUBJECT, f"{ADDED} nie brak klienta", LATER)

    second = enter_reports(_inputs([mail, ewa], _after(orders, first), ordered=[DAY], memory=first.memory))

    assert [move.worker for move in second.moves] == ["ewa.probna"]
    assert second.notes == (
        _added_note(EWA_LOGIN),
        TakenOver(DAY, EWA_LOGIN, OrderNumber(ADDED), JAN_LOGIN),
        HandedOver(DAY, JAN_LOGIN, OrderNumber(ADDED), EWA_LOGIN),
    )


def test_dopisane_zlecenie_usuniete_przez_tate_wraca_tylko_ze_swiezszym_mailem() -> None:
    """Granica #1354: tata usunął dopisany wiersz. Kolejne kliknięcie z tym samym mailem go nie dopisuje i nie daje
    problemu (pamięć dopisania, reguła ``may_move``), a świeższy mail Jana dopisuje je znowu, ze swoimi wartościami."""

    orders = [_order()]
    mail = _mail(JAN, SUBJECT, ADDED_TEXT)
    first = enter_reports(_inputs([mail], orders, ordered=[DAY]))

    same = enter_reports(_inputs([mail], orders, ordered=[DAY], memory=first.memory))
    fresher = _mail(JAN, SUBJECT, f"{ADDED} nie klient nieobecny", LATER)
    newer = enter_reports(_inputs([mail, fresher], orders, ordered=[DAY], memory=same.memory))

    assert (same.added, same.problems, same.notes) == ((), (), ())
    assert newer.added == (_added(successful="nie", completed="klient nieobecny"),)


def test_przy_kilku_mailach_z_nowym_numerem_dopisuje_najswiezszy_a_problem_starszego_znika() -> None:
    """US 3 dla dopisania: Jan przysłał numer za 9.11 (dzień nieuporządkowany), a potem Ewa ten sam numer za 8.11.
    Dopisuje mail Ewy, w nowym segmencie Ewy (jej login, bo nie ma zleceń w INTERMAX), a problem starszego maila Jana
    znika, bo zlecenie już jest; numer bez ``tak`` ani ``nie`` w najświeższym mailu nic nie dopisuje."""

    orders = [_order()]
    jan = _mail(JAN, "Raport 09.11.2026", ADDED_TEXT)
    ewa = _mail(EWA, SUBJECT, f"{ADDED} nie brak klienta", LATER)
    letter = _mail(EWA, SUBJECT, f"{ADDED} t montaż", LATER + timedelta(minutes=1))

    outcome = enter_reports(_inputs([ewa, jan], orders, today=NEXT_DAY, rollout=DAY, ordered=[DAY]))
    without = enter_reports(_inputs([jan, ewa, letter], orders, today=NEXT_DAY, rollout=DAY, ordered=[DAY]))

    assert outcome.added == (_added("ewa.probna", "nie", "brak klienta"),)
    assert outcome.problems == ()
    assert outcome.notes == (_added_note(EWA_LOGIN),)
    assert without.added == ()
    assert without.problems == (
        MissingVerdict(EWA_LOGIN, DAY, OrderNumber(ADDED), VerdictFault.LETTER_YES),
        UnknownNumber(JAN_LOGIN, NEXT_DAY, OrderNumber(ADDED), AddBar.NOT_ORDERED),
    )


@pytest.mark.parametrize(
    ("orders", "newest", "rollout", "closed", "ordered", "problems"),
    [
        pytest.param(
            [
                _order(),
                _order(OrderRow("Zlecenia", 121), number="40000003", day=date(2026, 11, 7), worker="Ewa.Probna"),
                _order(OrderRow("Zlecenia", 122), number="40000004", day=date(2026, 11, 7), worker="Ewa.Probna"),
            ],
            _mail(EWA, SUBJECT, f"40000003 tak a\n40000004 nie b\n{ADDED} nie brak klienta", LATER),
            date(2026, 11, 7),
            (),
            [date(2026, 11, 7), DAY],
            (UnknownNumber(EWA_LOGIN, DAY, OrderNumber(ADDED), AddBar.MISTAKEN_SUBJECT),),
            id="pomylony-temat",
        ),
        pytest.param(
            [_order()],
            _mail(EWA, "Raport 02.11.2026", f"{ADDED} nie brak klienta", LATER),
            CLOSED_DAY,
            CLOSED,
            [DAY],
            (),
            id="dzien-okresu-z-plikiem-zbiorczym",
        ),
    ],
)
def test_starszy_mail_nie_dopisuje_numeru_gdy_najswiezszy_wpis_tego_numeru_nie_dopisuje(
    orders: list[RegisterOrder],
    newest: ReportMail,
    rollout: date,
    closed: tuple[str, ...],
    ordered: list[date],
    problems: tuple[ReportProblem, ...],
) -> None:
    """Przegląd #1374 r1: o numerze, którego INTERMAX nie ma, decyduje najświeższy Raport wykonawcy z tym numerem (US 3),
    także gdy jego Wpis niczego nie dopisuje. Jan (starszy mail) ma nowy numer z ``tak``, a Ewa (świeższy) ten sam numer
    z ``nie`` w Raporcie z pomylonym tematem (dwa jej zlecenia z 7.11) albo w Raporcie za dzień okresu z Plikiem
    zbiorczym. Kliknięcie nie dopisuje więc Wpisu Jana, a drugie kliknięcie daje to samo co pierwsze, zamiast przenieść
    dopisane zlecenie do Ewy albo dać problem Przeniesienia do zamkniętego okresu."""

    jan = _mail(JAN, SUBJECT, ADDED_TEXT)
    inputs = _inputs([jan, newest], orders, rollout=rollout, closed=closed, ordered=ordered)

    first = enter_reports(inputs)
    second = enter_reports(replace(inputs, orders=_after(orders, first), memory=first.memory))

    assert (first.added, first.problems) == ((), problems)
    assert (second.added, second.moves, second.changes, second.problems) == ((), (), (), problems)

def test_literowka_poprawiona_swiezszym_mailem_tego_samego_wykonawcy_nie_jest_dopisana() -> None:
    """Przegląd #1374 r1, reguła poprawionego maila (US 40) dla dopisania: Jan wysłał raport z literówką w drugim numerze
    (40000092 zamiast 40000002), a potem ten sam raport z dobrym numerem. Świeższy mail powtarza zlecenie Jana z 8.11 z
    pierwszego, więc go poprawia, a numer, którego w nim nie ma, nie staje się Zleceniem dopisanym z raportu, także gdy
    oba maile są w skrzynce przy jednym kliknięciu. Kolejny raport Jana bez zlecenia z pierwszego nie jest poprawką, więc
    numer pierwszego się dopisuje."""

    orders = [_order(), _order(OrderRow("Zlecenia", 121), number="40000002")]
    typo = _mail(JAN, SUBJECT, TYPO)

    corrected = enter_reports(_inputs([typo, _mail(JAN, SUBJECT, RESENT, LATER)], orders, ordered=[DAY]))
    another = enter_reports(_inputs([typo, _mail(JAN, SUBJECT, "40000002 tak montaż", LATER)], orders, ordered=[DAY]))

    assert (corrected.added, corrected.problems) == ((), ())
    assert {(change.order.row, change.value) for change in corrected.changes} == {
        (120, "tak"),
        (120, "wymiana routera"),
        (121, "tak"),
        (121, "montaż"),
    }
    assert [added.number for added in another.added] == ["40000092"]


def test_raport_za_inny_dzien_z_numerem_zlecenia_z_tamtego_dnia_nie_poprawia_raportu_z_nowym_numerem() -> None:
    """Przegląd #1374 r2 Drobne 1, reguła poprawionego maila (US 40) dla dopisania: poprawką Raportu wykonawcy za D jest
    tylko późniejszy Raport tego Wykonawcy za D. Jan wpisał do raportu za 8.11 nowy numer i numer swojego zlecenia z
    7.11, a potem przysłał raport za 7.11 z tym zleceniem. Ten raport powtarza zlecenie Jana ze swojego dnia, ale nie
    poprawia raportu za 8.11, więc nowy numer się dopisuje, a zlecenie z 7.11 dostaje Wpis świeższego maila."""

    first = _mail(JAN, SUBJECT, f"40000001 tak a\n{ADDED_TEXT}")
    other_day = _mail(JAN, "Raport 07.11.2026", "40000001 tak b", LATER)

    outcome = enter_reports(
        _inputs([first, other_day], [_order(day=SEVENTH)], rollout=SEVENTH, ordered=[SEVENTH, DAY])
    )

    assert outcome.added == (_added(),)
    assert (outcome.moves, outcome.problems) == ((), ())
    assert {(change.order.row, change.value) for change in outcome.changes} == {(120, "tak"), (120, "b")}


def test_dopisanie_idzie_do_arkusza_z_zleceniem_nadawcy_w_dniu_z_tematu() -> None:
    """Dzień z tematu jest Dniem uporządkowanym w dwóch arkuszach zleceń: dopisanie idzie do arkusza, w którym nadawca ma
    zlecenie tego dnia."""

    other = OrderRow("Zlecenia 2026", 40)
    inputs = _inputs([_mail(JAN, SUBJECT, ADDED_TEXT)], [_order(other)], ordered=[DAY])

    outcome = enter_reports(replace(inputs, ordered_days=frozenset({OrderedDay(ROW.sheet, DAY), OrderedDay(other.sheet, DAY)})))

    assert outcome.added == (_added(sheet=other.sheet),)



def test_dopisane_zlecenie_nie_robi_ze_starszego_raportu_pomylonego_tematu_w_nastepnym_kliknieciu() -> None:
    """Własność N4 po scaleniu #1367 r5 (#1374 r4): INTERMAX ma 40000001 u Jana w 6.11. Starszy Raport Jana za 2.11
    (okres z Plikiem zbiorczym) ma 40000001 i nowy numer 40000077, a świeższy Raport Jana za 6.11 dopisuje 40000077 w
    6.11. Następne kliknięcie widzi dopisane zlecenie, ale jego dzień dał Raport wykonawcy, a nie tata, więc starszy
    raport dalej ma jeden niezgodny Wpis, a nie pomylony temat, i nie wpisuje się do 40000001: dwa kliknięcia dają to
    samo co jedno."""

    orders = [_order(day=SIXTH)]
    old = _mail(JAN, "Raport 02.11.2026", f"40000001 tak montaż\n{ADDED} tak montaż", EVENING)
    new = _mail(JAN, "Raport 06.11.2026", ADDED_TEXT, EVENING + timedelta(minutes=5))
    first = enter_reports(_inputs([old, new], orders, rollout=CLOSED_DAY, closed=CLOSED, ordered=[SIXTH, DAY]))

    second = enter_reports(
        _inputs([old, new], _after(orders, first), rollout=CLOSED_DAY, closed=CLOSED, ordered=[SIXTH, DAY], memory=first.memory)
    )

    assert [(added.day, added.number) for added in first.added] == [(SIXTH, ADDED)]
    assert first.changes == ()
    assert (second.changes, second.moves, second.added) == ((), (), ())
    assert second.memory == first.memory
    assert second.problems == first.problems


@pytest.mark.parametrize(
    ("moved_to", "bar"),
    [
        pytest.param(CLOSED_DAY, MoveBar.CLOSED_SOURCE, id="na-dzien-okresu-z-plikiem-zbiorczym"),
        pytest.param(NINTH, MoveBar.AFTER_TODAY, id="na-jutro"),
    ],
)
def test_dopisane_zlecenie_przelozone_przez_tate_na_dzien_nieotwarty_zostaje_tam_bez_zmiany(moved_to: date, bar: MoveBar) -> None:
    """Przegląd #1374 r4 Ważne 1 (ADR 0029): Raport Jana za 8.11 dopisuje 40000077 w 8.11, a tata przekłada to zlecenie
    na 2.11 (okres z Plikiem zbiorczym) albo na 9.11 (jutro). Świeższy Raport Jana za 8.11 z tym numerem nie przenosi go
    z powrotem i nie zmienia jego komórek, tylko daje odmowę Przeniesienia, jak przy każdym jedynym zleceniu z dnia,
    który nie jest otwarty: dopisane zlecenie pomija tylko próg pomylonego tematu."""

    def click(mails: list[ReportMail], orders: list[RegisterOrder], memory: OwnEntries = OwnEntries.EMPTY) -> ReportsOutcome:
        inputs = _inputs(mails, orders, rollout=_ROLLOUT, closed=CLOSED, ordered=[SEVENTH, DAY, NINTH], memory=memory)
        return enter_reports(inputs)

    orders = [_order(day=SEVENTH)]
    first_mail = _mail(JAN, SUBJECT, ADDED_TEXT)
    first = click([first_mail], orders)
    [added] = [order for order in _after(orders, first) if order.key.number == ADDED]
    moved = _order(added.row, number=ADDED, day=moved_to, successful="tak", completed="montaż ONT", address=None)
    fresher = _mail(JAN, SUBJECT, f"{ADDED} nie brak klienta", LATER)

    second = click([first_mail, fresher], [*orders, moved], first.memory)

    assert [(found.day, found.number) for found in first.added] == [(DAY, ADDED)]
    assert (second.moves, second.changes, second.added) == ((), (), ())
    assert second.problems == (RefusedMove(JAN_LOGIN, DAY, OrderNumber(ADDED), moved_to, moved_to, bar),)


def test_raport_z_pomylonym_tematem_wpisuje_sie_do_dopisanego_zlecenia_w_jego_dniu_bez_przeniesienia() -> None:
    """Przegląd #1374 r4 Ważne 1 (ADR 0029): Raport Jana za 7.11 dopisuje 40000077 w 7.11. Świeższy Raport Jana za 8.11 ma
    dwa jego zlecenia z 7.11, więc temat jest pomylony, i 40000077 z „nie”. Dopisane zlecenie nie liczy się do progu, ale
    przy pomylonym temacie zostaje w swoim dniu jak każde zlecenie raportu i dostaje Wpis z informacją o przegranym
    temacie, więc tata nie dostaje sprzecznych informacji, że temat to pomyłka, a zlecenie przeszło na dzień z tematu."""

    orders = [_order(day=SEVENTH), _order(OrderRow("Zlecenia", 121), number="40000002", day=SEVENTH)]
    first_mail = _mail(JAN, "Raport 07.11.2026", ADDED_TEXT)
    first = enter_reports(_inputs([first_mail], orders, rollout=SEVENTH, ordered=[SEVENTH, DAY]))
    mistaken = _mail(JAN, SUBJECT, f"40000001 tak montaż\n40000002 tak montaż\n{ADDED} nie brak klienta", LATER)

    second = enter_reports(
        _inputs([first_mail, mistaken], _after(orders, first), rollout=SEVENTH, ordered=[SEVENTH, DAY], memory=first.memory)
    )

    assert [(found.day, found.number) for found in first.added] == [(SEVENTH, ADDED)]
    assert (second.moves, second.added, second.problems) == ((), (), ())
    assert {(change.order.row, change.value) for change in second.changes} == {
        (row, value) for row in (120, 121) for value in ("tak", "montaż")
    } | {(122, "nie"), (122, "brak klienta")}
    assert [found for found in second.notes if isinstance(found, SubjectLost)] == [
        SubjectLost(DAY, JAN_LOGIN, OrderNumber(number), SEVENTH) for number in ("40000001", "40000002", ADDED)
    ]


def test_zlecenie_numeru_z_drugim_przeczytanym_wierszem_nie_przechodzi_a_zlecenie_nadawcy_z_dnia_z_tematu_ma_wpis() -> None:
    """Reguła #1367 „numer w kilku miejscach się nie przenosi” z przeczytanymi wierszami (przegląd #1374 r3): proces
    przeczytał 40000001 w zleceniu i drugi raz w wierszu bez zlecenia (Surowe zlecenie albo wiersz bez ``WYKONAWCA``).
    Raport Jana za 8.11 nie przenosi jego zlecenia z 7.11 (8.11 miałby wtedy ten numer dwa razy), tylko daje problem z
    miejscem zlecenia, a zlecenie Jana z 8.11 dostaje Wpis bez Przeniesienia. Bez drugiego wiersza to samo zlecenie z
    7.11 przechodzi na 8.11."""

    mail = _mail(JAN, SUBJECT, "40000001 tak montaż")
    seventh, eighth = _order(day=SEVENTH), _order()

    def click(order: RegisterOrder, twice: bool) -> ReportsOutcome:
        rows = (ReadNumber(N1, order.key.day), *((ReadNumber(N1),) if twice else ()))
        return enter_reports(_inputs([mail], [order], rollout=SEVENTH, ordered=[SEVENTH, DAY], present=rows))

    moved, repasted, own = click(seventh, False), click(seventh, True), click(eighth, True)

    assert moved.moves == (OrderMove(ROW, DAY, "Jan.Testowy"),)
    assert (repasted.moves, repasted.changes) == ((), ())
    assert repasted.problems == (RepeatedNumber(JAN_LOGIN, DAY, N1, ((SEVENTH, JAN_LOGIN),)),)
    assert own.moves == ()
    assert {(change.order, change.value) for change in own.changes} == {(ROW, "tak"), (ROW, "montaż")}


@pytest.mark.parametrize(
    ("rollout", "rows", "bar"),
    [
        pytest.param(SEVENTH, (date(2026, 11, 5),), AddBar.BEFORE_WINDOW, id="zlecenie-sprzed-okna"),
        pytest.param(SEVENTH, (date(2026, 11, 5), date(2026, 11, 4)), AddBar.BEFORE_WINDOW, id="dwa-zlecenia-sprzed-okna"),
        pytest.param(SEVENTH, (date(2026, 11, 5), None), AddBar.IN_INTERMAX, id="zlecenie-sprzed-okna-i-wiersz-bez-zlecenia"),
        pytest.param(SEVENTH, (SEVENTH,), AddBar.IN_INTERMAX, id="pelny-wiersz-w-oknie-bez-zlecenia-rdzenia"),
        pytest.param(SEVENTH, (None,), AddBar.IN_INTERMAX, id="wiersz-bez-zlecenia"),
        pytest.param(CLOSED_DAY, (CLOSED_DAY,), AddBar.IN_INTERMAX, id="pierwszy-czytany-dzien-przed-pierwszym-otwartym"),
        pytest.param(CLOSED_DAY, (date(2026, 11, 1),), AddBar.BEFORE_WINDOW, id="dzien-przed-pierwszym-czytanym"),
    ],
)
def test_numer_przeczytany_tylko_w_zleceniach_sprzed_okna_ma_wlasny_powod(
    rollout: date, rows: tuple[date | None, ...], bar: AddBar
) -> None:
    """Przegląd #1374 r3 Drobne 3: okno czyta zlecenia od dnia wdrożenia (7.11), a proces przeczytał numer z Wpisu Jana
    tylko w wierszach, z których rdzeń nie ma zlecenia. Gdy każdy z nich to zlecenie z dniem i ``WYKONAWCA`` sprzed dni,
    których zlecenia czyta okno, powód mówi o dniu sprzed okna (``BEFORE_WINDOW``), a inaczej o wierszu bez zlecenia
    (``IN_INTERMAX``); w obu przypadkach Centrum go nie dopisuje. Przegląd #1374 r4 Drobne 1: przy dniu wdrożenia 2.11
    w okresie z Plikiem zbiorczym pierwszy dzień otwarty to 3.11, a zlecenia okno czyta od 2.11 (``Window.start``), więc
    wiersz z 2.11 nie jest sprzed okna, a z 1.11 jest."""

    present = tuple(ReadNumber(OrderNumber(ADDED), day) for day in rows)
    mail = _mail(JAN, SUBJECT, ADDED_TEXT)
    inputs = _inputs([mail], [], rollout=rollout, closed=CLOSED, ordered=[SEVENTH, DAY], present=present)

    outcome = enter_reports(inputs)

    assert outcome.added == ()
    assert outcome.problems == (UnknownNumber(JAN_LOGIN, DAY, OrderNumber(ADDED), bar),)
