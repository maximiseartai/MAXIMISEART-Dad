"""Rdzeń raportów (``worker_reports.enter_reports``): Wpis raportu w dokładnym formacie trafia do pustych komórek
zlecenia Wykonawcy z dnia z tematu (#1227, ADR 0028, pojęcia Raport wykonawcy, Wpis raportu i Wpisanie raportów w
``GLOSSARY.md``).

Testy idą przez jedyną operację rdzenia, jak testy Reguł ilości: maile, adresy i zlecenia na wejściu, zmiany komórek,
problemy i liczby na wyjściu. Dane są syntetyczne, adresy w domenie ``.invalid``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
import itertools
from pathlib import Path
from typing import get_args

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


def _mail(sender: str, subject: str, text: str, arrived: datetime = EVENING) -> ReportMail:
    address = SenderAddress.of(sender)
    assert address is not None
    return ReportMail(MailId.of(f"<{subject}|{text}|{arrived.isoformat()}@{sender}>"), address, subject, text, arrived)


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


def test_problemy_sa_bez_powtorzen_i_w_tej_samej_kolejnosci_dla_kazdej_kolejnosci_maili() -> None:
    ewa = _mail(EWA, "Raport 07.11.2026", "40000009 tak montaż")
    stranger = _mail("obcy@przyklad.invalid", SUBJECT, TEXT)
    twice = [_mail(JAN, SUBJECT, "12345678 tak a"), _mail(JAN, SUBJECT, "12345678 tak b")]
    mails = [*twice, stranger, ewa]

    forward = enter_reports(_inputs(mails, [], rollout=date(2026, 11, 7)))
    backward = enter_reports(_inputs(mails[::-1], [], rollout=date(2026, 11, 7)))

    assert forward == backward
    assert forward.problems == (
        UnknownNumber(Login("ewa.probna"), date(2026, 11, 7), OrderNumber("40000009")),
        UnknownSender(stranger.id, stranger.sender, DAY),
        UnknownNumber(Login("jan.testowy"), DAY, OrderNumber("12345678")),
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


def test_wynik_przyjmuje_dwa_rozne_problemy_tylko_w_jednej_kolejnosci() -> None:
    """Kolejność problemów nie zależy od kolejności maili ani od ``PYTHONHASHSEED`` także dla problemów jednego
    zlecenia, które dadzą #1228 i #1229: dwa braki ``tak``/``nie`` z innym powodem, dwóch właścicieli, inne dni."""

    jan, number = Login("jan.testowy"), OrderNumber("40000001")
    problems = [
        *_every_problem(),
        ForeignOrder(jan, DAY, number, Login("adam.inny")),
        OtherDay(jan, DAY, number, (date(2026, 11, 5),)),
    ]

    for first, second in itertools.combinations(problems, 2):
        accepted = [pair for pair in [(first, second), (second, first)] if _outcome_accepts(pair)]
        assert len(accepted) == 1, (first, second)
    assert not _outcome_accepts((problems[0], problems[0]))


def _outcome_accepts(problems: tuple[ReportProblem, ...]) -> bool:
    try:
        ReportsOutcome((), problems, (), (), OwnEntries.EMPTY)
    except ValueError:
        return False
    return True


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
