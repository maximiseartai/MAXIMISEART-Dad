"""Rdzeń raportów (``worker_reports.enter_reports``): Wpis raportu trafia do pustych komórek zlecenia Wykonawcy z dnia
z tematu (#1227), a Raporty wykonawcy i Wpisy rdzeń rozpoznaje tak, jak piszą Wykonawcy (#1228; ADR 0028, pojęcia
Raport wykonawcy, Wpis raportu i Wpisanie raportów w ``GLOSSARY.md``).

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
    Kept,
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
    ReadUnreadable,
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
    kept: frozenset[Kept] = frozenset(),
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
        kept=kept,
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
    assert first.memory == OwnEntries(frozenset({OwnEntry(_key(), ReportColumn.COMPLETED, "wymiana routera")}))
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
    assert outcome.memory == OwnEntries(frozenset({OwnEntry(_key(), ReportColumn.SUCCESSFUL, "tak")}))


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
            [_order()],
            ForeignOrder(EWA_LOGIN, DAY, OrderNumber("40000001"), JAN_LOGIN),
            "Zlecenie 40000001 z 08.11.2026 jest zleceniem jan.testowy, a Wpis przysłał ewa.probna, więc Centrum go nie "
            "wpisało.",
            id="numer-zlecenia-innego-wykonawcy-z-tego-dnia-z-oboma-wykonawcami",
        ),
        pytest.param(
            JAN,
            "Raport 07.11.2026",
            [_order()],
            OtherDay(JAN_LOGIN, date(2026, 11, 7), OrderNumber("40000001"), (DAY,)),
            "Zlecenie 40000001 od jan.testowy jest z 08.11.2026, a temat Raportu wykonawcy ma 07.11.2026, więc Centrum "
            "go nie wpisało.",
            id="numer-zlecenia-wykonawcy-z-innego-dnia-z-obiema-datami",
        ),
        pytest.param(
            JAN,
            SUBJECT,
            [_order(day=date(2026, 11, 7)), _order(OrderRow("Zlecenia", 121), day=date(2026, 11, 5))],
            OtherDay(JAN_LOGIN, DAY, OrderNumber("40000001"), (date(2026, 11, 5), date(2026, 11, 7))),
            "Zlecenie 40000001 od jan.testowy jest z 05.11.2026, 07.11.2026, a temat Raportu wykonawcy ma 08.11.2026, "
            "więc Centrum go nie wpisało.",
            id="numer-zlecen-wykonawcy-z-dwoch-innych-dni",
        ),
        pytest.param(
            JAN,
            SUBJECT,
            [_order(day=date(2026, 11, 7), worker="Ewa.Probna")],
            UnknownNumber(JAN_LOGIN, DAY, OrderNumber("40000001")),
            "Numer 40000001 nie jest zleceniem jan.testowy z 08.11.2026.",
            id="numer-zlecenia-innego-wykonawcy-z-innego-dnia",
        ),
        pytest.param(
            JAN,
            SUBJECT,
            [_order(number="12345678")],
            UnknownNumber(JAN_LOGIN, DAY, OrderNumber("40000001")),
            "Numer 40000001 nie jest zleceniem jan.testowy z 08.11.2026.",
            id="numer-spoza-zlecen-wszystkich-wykonawcow",
        ),
    ],
)
def test_wpis_trafia_tylko_do_zlecenia_nadawcy_z_dnia_z_tematu_a_pomylka_ma_dokladny_powod(
    sender: str, subject: str, orders: list[RegisterOrder], problem: ReportProblem, sentence: str
) -> None:
    """Spec #1224 US 27–30: cudzy numer z oboma Wykonawcami, inny dzień z obiema datami, numer spoza zleceń Wykonawcy z
    dnia z dokładnym powodem; żadna komórka się nie zmienia."""

    outcome = enter_reports(_inputs([_mail(sender, subject, TEXT)], orders, rollout=date(2026, 11, 1)))

    assert outcome.changes == ()
    assert outcome.problems == (problem,)
    assert reason(problem) == sentence


def test_wlasne_zlecenie_z_innego_dnia_ma_pierwszenstwo_przed_cudzym_z_dnia_z_tematu() -> None:
    """Wpis trafia tylko do zlecenia nadawcy, więc jego zlecenie z innego dnia jest bliżej zamiaru Wykonawcy niż zlecenie
    innego Wykonawcy z dnia z tematu."""

    orders = [_order(day=date(2026, 11, 7)), _order(OrderRow("Zlecenia", 121), worker="Ewa.Probna")]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], orders, rollout=date(2026, 11, 1)))

    assert outcome.problems == (OtherDay(JAN_LOGIN, DAY, OrderNumber("40000001"), (date(2026, 11, 7),)),)


def test_numer_zlecen_dwoch_innych_wykonawcow_z_dnia_daje_problem_z_kazdym_z_nich() -> None:
    adam = _order(OrderRow("Zlecenia", 121), worker="Adam.Inny")
    orders = [_order(worker="Ewa.Probna"), adam]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, TEXT)], orders))

    assert outcome.changes == ()
    assert outcome.problems == (
        ForeignOrder(JAN_LOGIN, DAY, OrderNumber("40000001"), Login("adam.inny")),
        ForeignOrder(JAN_LOGIN, DAY, OrderNumber("40000001"), EWA_LOGIN),
    )


def test_zlecenie_wykonawcy_z_dnia_zamknietego_nie_jest_innym_dniem_wpisu() -> None:
    """Okres z Plikiem zbiorczym jest zamknięty (ADR 0028), więc jego zlecenie nie podpowiada innego dnia."""

    closed = date(2026, 11, 2)
    orders = [_order(day=closed), _order(OrderRow("Zlecenia", 121), day=date(2026, 11, 7))]

    outcome = enter_reports(
        _inputs([_mail(JAN, SUBJECT, TEXT)], orders, rollout=date(2026, 10, 30), closed=(period_of(closed).token,))
    )

    assert outcome.problems == (OtherDay(JAN_LOGIN, DAY, OrderNumber("40000001"), (date(2026, 11, 7),)),)


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
    assert closed == ReportsOutcome((), (), (), (), OwnEntries.EMPTY)


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

    assert outcome.memory == OwnEntries(frozenset({kept}))


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
    assert outcome.memory == OwnEntries(frozenset(remembered_after))


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
    assert second.memory == OwnEntries(frozenset(OwnEntry(_key(), column, value) for column, value in CORRECTED.items()))


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
    assert second.memory == OwnEntries(frozenset({OwnEntry(_key(), ReportColumn.COMPLETED, "klient nieobecny")}))
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
    assert second.memory == OwnEntries(
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
]
JAN_TYPO = UnknownNumber(Login("jan.testowy"), DAY, OrderNumber("40000092"))


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
            OtherDay(JAN_LOGIN, DAY, OrderNumber("40000003"), (NEXT_DAY,)),
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
    poprawki jest dzień zlecenia. Numer zlecenia Ewy od Jana (``problem`` ``None``) to do #1229 ``UnknownNumber``, a od
    niego ``ForeignOrder``: znika tak samo."""

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
            OtherDay(JAN_LOGIN, DAY, OrderNumber("40000003"), (NEXT_DAY,)),
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
_EXACT = st.builds(
    lambda number, mark, words: " ".join([number, mark, *words]),
    st.sampled_from(["40000001", "40000002", "40000003", "040000001", "12345678"]),
    st.sampled_from(["tak", "nie"]),
    _WORDS,
)
"""Wpis w dokładnym formacie: jedyny, który czyta każda gramatyka rdzenia, więc połowa maili go ma."""
_TEXTS = st.one_of(_EXACT, st.lists(st.lists(_LINES, min_size=1, max_size=2).map(" ".join), max_size=3).map("\n".join))
_SUBJECTS = st.one_of(
    st.sampled_from([SUBJECT, "Raport 07.11.2026"]),
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


def _read_back(read: ReadReport | ReadUnreadable) -> tuple[object, ...]:
    sender = SenderAddress.of(JAN)
    assert sender is not None
    return enter_reports(_inputs([as_mail(read, sender)], [_order()])).mails


@pytest.mark.parametrize("fault", list(SubjectFault), ids=lambda fault: fault.name)
def test_postac_kanoniczna_nieczytelnego_tematu_daje_ten_sam_powod(fault: SubjectFault) -> None:
    """Każdy powód nieczytelnego tematu, także taki, którego przykłady własności wyżej nie trafią."""

    read = ReadUnreadable(MailId.of("<1@przyklad.invalid>"), EVENING, Login("jan.testowy"), fault)

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
    """Zlecenia mają numer Jana z dwóch dni i numer Ewy, więc maile dają cele, cudze zlecenia, inne dni, nieznane numery
    i nieznanych nadawców; dwa kliknięcia z tymi samymi mailami w innej kolejności dają ten sam wynik."""

    mails, shuffled = pair
    inputs = _inputs(mails, _CANONICAL_ORDERS, today=DAY, rollout=date(2026, 11, 7), memory=_CANONICAL_MEMORY)

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
    assert outcome.mails == (ReadUnreadable(mail.id, EVENING, Login("jan.testowy"), fault),)


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
        pytest.param("40000001 t wymiana routera", VerdictFault.LETTER, id="t"),
        pytest.param("40000001 N, brak klienta", VerdictFault.LETTER, id="n"),
        pytest.param("40000001 skuteczne wymiana routera", VerdictFault.WORD, id="skuteczne"),
        pytest.param("40000001 Nieskuteczne: brak klienta", VerdictFault.WORD, id="nieskuteczne"),
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
    assert outcome.problems == (MissingVerdict(Login("jan.testowy"), DAY, OrderNumber("40000001"), VerdictFault.LETTER),)


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
            "40000001 tak wymiana routera\n40000002 nie klient nieobecny\n40000001 nie brak klienta",
            id="pierwszy-wpis-numeru-w-mailu",
        ),
    ],
)
def test_powitanie_podpis_i_cytat_nie_trafiaja_do_opisu(text: str) -> None:
    """US 23, 25: powód nieskuteczności przy ``nie`` też trafia do ``CZYNNOŚCI ZREALIZOWANE``; z cytowanej odpowiedzi
    nic. W jednym mailu liczy się pierwszy Wpis zlecenia, bo cytat stoi pod nową treścią."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], _orders()))

    assert outcome.changes == (*_both(ROWS[0], "tak", "wymiana routera"), *_both(ROWS[1], "nie", "klient nieobecny"))
    assert outcome.problems == ()


def test_opis_ma_pojedyncze_spacje_bez_spacji_na_brzegach() -> None:
    """US 24."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "  40000001\ttak   wymiana \xa0 routera ,  2 gniazda   ")], [_order()]))

    assert outcome.changes == _both(ROW, "tak", "wymiana routera , 2 gniazda")


@pytest.mark.parametrize(
    ("text", "number"),
    [
        pytest.param("040000001 tak wymiana routera", "040000001", id="zero-wiodace"),
        pytest.param("Dzień dobry 12345678 tak wymiana routera", "12345678", id="po-powitaniu"),
    ],
)
def test_numer_z_tak_albo_nie_spoza_zlecen_wykonawcy_jest_problemem(text: str, number: str) -> None:
    """Zero wiodące to inny numer niż ``NUMER ZL.``, a pomyłka w numerze przed pierwszym Wpisem linii też jest Wpisem."""

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], [_order()]))

    assert outcome.changes == ()
    assert outcome.problems == (UnknownNumber(Login("jan.testowy"), DAY, OrderNumber(number)),)


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

EWA_ORDER = _order(OrderRow("Zlecenia", 123), number="40000009", worker="Ewa.Probna")
LONG = "40000001 tak wymiana routera,\nmontaż 2 gniazd"
LONG_CELLS = ((0, "tak", "wymiana routera, montaż 2 gniazd"),)


def _unknown(number: str) -> UnknownNumber:
    return UnknownNumber(Login("jan.testowy"), DAY, OrderNumber(number))


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
            (ForeignOrder(JAN_LOGIN, DAY, OrderNumber("40000009"), EWA_LOGIN),),
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
            (_unknown("600100200"),),
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

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, text)], [*_orders(), EWA_ORDER]))

    assert outcome.changes == _cells(entered)
    assert outcome.problems == problems


@pytest.mark.parametrize(
    ("numbers", "problems"),
    [
        pytest.param(("40000001", "400002"), (_unknown("400099"),), id="najkrotszy-numer-ma-6-cyfr"),
        pytest.param(("40000001", "40000002"), (), id="najkrotszy-numer-ma-8-cyfr"),
    ],
)
def test_ksztalt_numeru_zlecenia_wyznacza_najkrotszy_numer_zlecenia_z_dni_otwartych(
    numbers: tuple[str, ...], problems: tuple[ReportProblem, ...]
) -> None:
    orders = [_order(row, number=number) for row, number in zip(ROWS, numbers, strict=False)]

    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "40000001 tak router\n400099 nie brak")], orders))

    assert outcome.problems == problems


def test_raport_z_dnia_bez_zlecen_w_dniach_otwartych_daje_problem_numeru() -> None:
    outcome = enter_reports(_inputs([_mail(JAN, SUBJECT, "Dzień dobry 12 tak router")], []))

    assert outcome.problems == (_unknown("12"),)


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
            "40000001 tak wymiana routera wysłano z serwisu",
            ((0, "tak", "wymiana routera wysłano z serwisu"),),
            id="slowa-stopki-w-srodku-linii-to-opis",
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
