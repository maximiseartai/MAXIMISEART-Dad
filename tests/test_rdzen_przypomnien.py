"""Rdzeń Przypomnień o raporcie (``worker_reports.reminders_due``, ADR 0030, spec #1344 US 31–44): które przypomnienia
należą się w danej chwili, ich temat i treść.

Testy idą przez operację rdzenia z chwilą na wejściu: zlecenia INTERMAX, maile ze Skrzynki raportów, przypomnienia z
„Wysłanych”, adresy Wykonawców i Ustawienia przypomnień, a przypomnienia na wyjściu. Pory domyślne (8:00–17:00,
18:00–22:00), dzień X+1 od 8:00 i treść biorą wartości ze speca #1344 i ADR 0030, a pory, godzina pierwszego
przypomnienia i treść z Ustawień Centrum (ADR 0032) działają tak samo jak domyślne. Dane są syntetyczne, adresy w domenie ``.invalid``, numery zmyślone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

from hypothesis import example, given, settings
from hypothesis import strategies as st
import pytest

from rozliczenia.activity_legend import WithCodes
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.report_cells import OrderRow
from rozliczenia.settlement_period import period_of
from rozliczenia.worker_list import WorkerEntry, WorkerList
from rozliczenia.worker_reports import (
    DEFAULT_REMINDERS,
    EXAMPLE_NUMBERS,
    MailId,
    OrderedDay,
    OrderNumber,
    OwnEntries,
    ReadNumber,
    RegisterOrder,
    Reminder,
    ReminderInputs,
    ReminderSchedule,
    ReminderSettings,
    ReportInputs,
    ReportMail,
    SchedulesInEffect,
    SenderAddress,
    SentReminder,
    SubjectLost,
    TimeRange,
    Window,
    reminder_day,
    enter_reports,
    reminder_subject,
    reminders_due,
)

TATA = timezone(timedelta(hours=1))
DAY = date(2026, 11, 9)
JAN = "jan@przyklad.invalid"
JAN_PRYWATNY = "jan.prywatny@przyklad.invalid"
EWA = "ewa@przyklad.invalid"
ADDRESSES = {"jan.testowy": [JAN, JAN_PRYWATNY], "ewa.probna": [EWA]}
ROLLOUT = date(2026, 11, 2)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TATA)


NEXT_MORNING = _at(DAY + timedelta(days=1), 8, 0)


def _address(text: str) -> SenderAddress:
    address = SenderAddress.of(text)
    assert address is not None
    return address


def _order(worker: str = "Jan.Testowy", day: date = DAY, number: int = 40000001, row: int = 120) -> RegisterOrder:
    order = RegisterOrder.of(
        OrderRow("Zlecenia", row),
        number=number,
        started=datetime(day.year, day.month, day.day, 9, 30),
        worker=worker,
        successful=None,
        completed=None,
        address=None,
    )
    assert order is not None
    return order


def _mail(sender: str, subject: str, text: str = "", arrived: datetime | None = None) -> ReportMail:
    moment = arrived or _at(DAY, 19)
    return ReportMail(MailId.of(f"<{subject}|{text}|{moment}@{sender}>"), _address(sender), subject, text, moment)


def _sent(day: date, sent_at: datetime, *recipients: str) -> SentReminder:
    return SentReminder(frozenset(_address(recipient) for recipient in recipients or (JAN,)), day, sent_at)


def _due(
    now: datetime,
    orders: Sequence[RegisterOrder] = (),
    *,
    mails: Sequence[ReportMail] = (),
    sent: Sequence[SentReminder] = (),
    rollout: date = ROLLOUT,
    closed: Sequence[str] = (),
    footer: str = "",
    workers: WorkerList | None = None,
    settings: ReminderSettings | None = None,
    in_effect: SchedulesInEffect | None = None,
    memory: OwnEntries = OwnEntries.EMPTY,
) -> tuple[Reminder, ...]:
    listed = workers or _workers()
    return reminders_due(
        ReminderInputs(
            now=now,
            reports=_reports(now, orders or (_order(),), mails, rollout=rollout, closed=closed, workers=listed, memory=memory),
            sent=sent,
            reminded=listed.reminded(),
            settings=settings or replace(DEFAULT_REMINDERS, enabled=True, since=rollout, footer=footer),
            in_effect=in_effect or SchedulesInEffect(),
        )
    )


def _reports(
    now: datetime,
    orders: Sequence[RegisterOrder],
    mails: Sequence[ReportMail],
    *,
    rollout: date = ROLLOUT,
    closed: Sequence[str] = (),
    workers: WorkerList | None = None,
    memory: OwnEntries = OwnEntries.EMPTY,
) -> ReportInputs:
    """Wejście odczytu okna, to samo dla Wpisania raportów i przypomnień: pamięć Wpisania ``memory`` (domyślnie przed
    pierwszym kliknięciem) bez decyzji taty, a każde zlecenie w swoim wierszu INTERMAX i w Dniu uporządkowanym."""

    return ReportInputs(
        mails=mails,
        addresses=(workers or _workers()).addresses(),
        orders=orders,
        window=Window.of(now.date(), rollout, closed),
        memory=memory,
        kept=frozenset(),
        present=[ReadNumber(order.key.number, order.key.day) for order in orders],
        legend=DEFAULT_ACTIVITY_LEGEND,
        ordered_days=frozenset(OrderedDay(order.row.sheet, order.key.day) for order in orders),
    )


def _after_click(
    clicked_at: datetime, orders: Sequence[RegisterOrder], mails: Sequence[ReportMail]
) -> tuple[tuple[RegisterOrder, ...], OwnEntries]:
    """Zlecenia INTERMAX i pamięć Wpisania raportów po kliknięciu w chwili ``clicked_at`` z mailami ``mails``:
    Przeniesienie daje wierszowi nowy dzień i Wykonawcę, a Zlecenie dopisane z raportu staje w nowym wierszu."""

    clicked = enter_reports(_reports(clicked_at, orders, mails))
    moved = {move.order: move for move in clicked.moves}
    after = [
        order if (move := moved.get(order.row)) is None else _order(move.worker, move.day, int(order.key.number), order.row.row)
        for order in orders
    ]
    rows = range(max(order.row.row for order in orders) + 1, max(order.row.row for order in orders) + 1 + len(clicked.added))
    after += [_order(added.worker, added.day, int(added.number), row) for added, row in zip(clicked.added, rows, strict=True)]
    return tuple(after), clicked.memory


def _workers(*, active: bool = True, reminders: bool = True) -> WorkerList:
    """Lista Wykonawców z ``ADDRESSES``; ``active`` i ``reminders`` dotyczą Wykonawcy ``jan.testowy``."""

    workers = WorkerList.of(
        [
            WorkerEntry(["jan.testowy"], "Jan Testowy", ADDRESSES["jan.testowy"], active=active, reminders=reminders),
            WorkerEntry(["ewa.probna"], "Ewa Próbna", ADDRESSES["ewa.probna"]),
        ]
    )
    assert isinstance(workers, WorkerList)
    return workers


def _days(found: Sequence[Reminder]) -> list[tuple[str, date]]:
    return [(reminder.worker, reminder.day) for reminder in found]


@pytest.mark.parametrize(
    ("active", "reminders", "expected"),
    [
        pytest.param(True, True, {"jan.testowy", "ewa.probna"}, id="aktywny-z-przypomnieniami"),
        pytest.param(False, True, {"ewa.probna"}, id="nieaktywny"),
        pytest.param(True, False, {"ewa.probna"}, id="przypomnienia-wylaczone"),
        pytest.param(False, False, {"ewa.probna"}, id="nieaktywny-bez-przypomnien"),
    ],
)
def test_przypomnienie_idzie_tylko_do_aktywnego_wykonawcy_z_wlaczonymi_przypomnieniami(
    active: bool, reminders: bool, expected: set[str]
) -> None:
    """ADR 0032: Przypomnienia o raporcie idą tylko do aktywnych Wykonawców z włączonymi przypomnieniami; Nieaktywny
    Wykonawca i Wykonawca z wyłączonymi przypomnieniami nie dostają ich, choć mają zlecenie dnia i adres."""

    orders = (_order(), _order(worker="ewa.probna", number=40000002, row=121))

    found = _due(NEXT_MORNING, orders, workers=_workers(active=active, reminders=reminders))

    assert {reminder.worker for reminder in found} == expected
    assert {reminder.day for reminder in found} == {DAY}


@pytest.mark.parametrize(
    ("now", "sent", "expected"),
    [
        pytest.param(_at(DAY + timedelta(days=1), 7, 59), [], [], id="7:59-noc"),
        pytest.param(NEXT_MORNING, [], [("jan.testowy", DAY)], id="8:00-pierwsze"),
        pytest.param(_at(DAY + timedelta(days=1), 17, 59), [NEXT_MORNING], [], id="17:59-poranna-juz-poszla"),
        pytest.param(_at(DAY + timedelta(days=1), 18, 0), [NEXT_MORNING], [("jan.testowy", DAY)], id="18:00-wieczorna"),
        pytest.param(_at(DAY + timedelta(days=1), 21, 59), [_at(DAY + timedelta(days=1), 18, 0)], [], id="21:59-wieczorna-juz-poszla"),
        pytest.param(_at(DAY + timedelta(days=1), 21, 59), [NEXT_MORNING], [("jan.testowy", DAY)], id="21:59-nadrabia"),
        pytest.param(_at(DAY + timedelta(days=1), 22, 0), [NEXT_MORNING], [], id="22:00-noc"),
        pytest.param(_at(DAY + timedelta(days=1), 23, 30), [], [], id="23:30-noc-bez-zadnego"),
        pytest.param(_at(DAY, 18, 30), [], [], id="dzien-x-wieczorem-za-wczesnie"),
        pytest.param(_at(DAY, 21, 59), [], [], id="dzien-x-przed-22-za-wczesnie"),
        pytest.param(_at(DAY + timedelta(days=1), 16, 30), [], [("jan.testowy", DAY)], id="16:30-poranna-nadrabia"),
        pytest.param(_at(DAY + timedelta(days=1), 16, 59), [], [("jan.testowy", DAY)], id="16:59-poranna-nadrabia"),
        pytest.param(_at(DAY + timedelta(days=1), 16, 59), [NEXT_MORNING], [], id="16:59-poranna-juz-poszla"),
        pytest.param(_at(DAY + timedelta(days=1), 17, 0), [], [], id="17:00-poranna-nie-nadrabia"),
        pytest.param(_at(DAY + timedelta(days=1), 17, 50), [], [], id="17:50-po-uspieniu-nic"),
        pytest.param(_at(DAY + timedelta(days=1), 17, 59), [], [], id="17:59-nic"),
        pytest.param(_at(DAY + timedelta(days=1), 18, 0), [], [("jan.testowy", DAY)], id="18:00-wieczorna-po-pominietej-porannej"),
        pytest.param(_at(DAY + timedelta(days=1), 18, 0), [_at(DAY + timedelta(days=1), 16, 59)], [("jan.testowy", DAY)], id="18:00-po-16:59"),
        pytest.param(_at(DAY + timedelta(days=1), 18, 0), [_at(DAY + timedelta(days=1), 17, 50)], [("jan.testowy", DAY)], id="18:00-po-17:50"),
        pytest.param(_at(DAY + timedelta(days=2), 8, 0), [_at(DAY + timedelta(days=1), 18, 0)], [("jan.testowy", DAY)], id="8:00-kolejnego-dnia"),
        pytest.param(_at(DAY + timedelta(days=2), 9, 0), [NEXT_MORNING], [("jan.testowy", DAY)], id="poranna-wczoraj-nie-blokuje-dzis"),
    ],
)
def test_przypomnienie_za_dzien_idzie_od_8_dnia_nastepnego_najwyzej_raz_w_porze_i_nigdy_w_nocy(
    now: datetime, sent: list[datetime], expected: list[tuple[str, date]]
) -> None:
    """Pierwsze przypomnienie za dzień X idzie od 8:00 dnia X+1, kolejne w każdej porze (8:00–17:00, 18:00–22:00), w
    której jeszcze nie poszło: poranne nadrabia się do 16:59, wieczorne do 21:59, a od 17:00 do 18:00 i w nocy nie
    idzie żadne (US 32–35, decyzja Maksa 12.11 w ADR 0030)."""

    assert _days(_due(now, sent=[_sent(DAY, moment) for moment in sent])) == expected



# Pory i godzina pierwszego przypomnienia, które tata ustawił inaczej niż ADR 0030 (ADR 0032, US 41–43).
SHIFTED = replace(
    DEFAULT_REMINDERS,
    enabled=True,
    since=ROLLOUT,
    schedule=ReminderSchedule(TimeRange(time(6, 30), time(12)), TimeRange(time(15), time(19, 30)), time(9, 15)),
)


def _shifted(day: date, hour: int, minute: int = 0) -> datetime:
    return _at(day + timedelta(days=1), hour, minute)


@pytest.mark.parametrize(
    ("now", "sent", "expected"),
    [
        pytest.param(_shifted(DAY, 9, 14), [], [], id="9:14-przed-pierwszym"),
        pytest.param(_shifted(DAY, 9, 15), [], [("jan.testowy", DAY)], id="9:15-pierwsze"),
        pytest.param(_shifted(DAY, 11, 59), [_shifted(DAY, 9, 15)], [], id="11:59-poranna-juz-poszla"),
        pytest.param(_shifted(DAY, 11, 59), [], [("jan.testowy", DAY)], id="11:59-poranna-nadrabia"),
        pytest.param(_shifted(DAY, 12, 0), [], [], id="12:00-koniec-porannej"),
        pytest.param(_shifted(DAY, 14, 59), [], [], id="14:59-miedzy-porami"),
        pytest.param(_shifted(DAY, 17, 30), [], [("jan.testowy", DAY)], id="17:30-wieczorna-choc-domyslnie-przerwa"),
        pytest.param(_shifted(DAY, 15, 0), [_shifted(DAY, 9, 15)], [("jan.testowy", DAY)], id="15:00-wieczorna-po-porannej"),
        pytest.param(_shifted(DAY, 19, 29), [_shifted(DAY, 15, 0)], [], id="19:29-wieczorna-juz-poszla"),
        pytest.param(_shifted(DAY, 19, 30), [], [], id="19:30-koniec-wieczornej"),
        pytest.param(_shifted(DAY + timedelta(days=1), 6, 30), [_shifted(DAY, 15, 0)], [("jan.testowy", DAY)], id="6:30-kolejnego-dnia"),
    ],
)
def test_pory_i_godzina_pierwszego_przypomnienia_z_ustawien_zastepuja_pory_z_adr_0030(
    now: datetime, sent: list[datetime], expected: list[tuple[str, date]]
) -> None:
    """ADR 0032: pory i godzina pierwszego przypomnienia z Ustawień Centrum działają jak dawne stałe. Pierwsze
    przypomnienie za dzień X idzie od 9:15 dnia X+1, najwyżej jedno w porze 6:30–12:00 i 15:00–19:30, bez końca pory, a
    poza nimi, także w dawnych porach z ADR 0030, nie idzie żadne. Praca przypomnień sprawdzała tylko przy tych porach,
    więc wysłane liczą się w nich."""

    always = SchedulesInEffect(frozenset({SHIFTED.schedule}))

    assert _days(_due(now, sent=[_sent(DAY, moment) for moment in sent], settings=SHIFTED, in_effect=always)) == expected


def test_pierwsze_zdanie_taty_ma_dzien_w_kazdym_miejscu_pola_a_wzor_i_przyklad_zostaja() -> None:
    """D-M1 projektu Ustawień: tata zmienia pierwsze zdanie z polem ``{dzień}`` i stopkę, a stały wzór Raportu wykonawcy
    z przykładem i temat zostają, bo po nich Wpisanie raportów poznaje odpowiedź (US 46, 48)."""

    settings = replace(SHIFTED, text="Raport za {dzień} proszę, bo {dzień} był dniem pracy.", footer="Tata")

    [reminder] = _due(_shifted(DAY, 10), settings=settings)

    assert reminder.subject == "Przypomnienie: raport za dzień 09.11.2026"
    assert reminder.text.splitlines() == [
        "Raport za 09.11.2026 proszę, bo 09.11.2026 był dniem pracy.",
        "",
        "Raport proszę wysłać według tego wzoru:",
        "Temat maila: Raport 09.11.2026",
        "Treść maila: NR. ZLECENIA [spacja] tak [spacja] kody czynności albo NR. ZLECENIA [spacja] nie [spacja] powód",
        "PRZYKŁAD:",
        "12345678 tak inst20m spawpg",
        "12345679 nie brak klienta",
        "",
        "Tata",
    ]


def test_laptop_wlaczony_przed_18_po_pominietej_porannej_daje_jedno_przypomnienie_o_18() -> None:
    """Laptop taty włączony o 17:50 po pominiętej porze porannej: sprawdzenia co minutę do 17:59 nic nie dają, o 18:00
    idzie jedno przypomnienie, a minuta później z nim w „Wysłanych” już żadne, więc Wykonawca nie dostaje dwóch maili w
    10 minut (decyzja Maksa 12.11, ADR 0030)."""

    evening = _at(DAY + timedelta(days=1), 18, 0)
    before_evening = [_due(_at(DAY + timedelta(days=1), 17, minute)) for minute in range(50, 60)]

    assert before_evening == [()] * 10
    assert _days(_due(evening)) == [("jan.testowy", DAY)]
    assert _due(_at(DAY + timedelta(days=1), 18, 1), sent=[_sent(DAY, evening)]) == ()

def test_przypomnienie_wyslane_w_utc_liczy_sie_w_porze_taty() -> None:
    """Chwila z „Wysłanych” w innej strefie liczy się w strefie chwili sprawdzenia: 7:30 UTC to 8:30 u taty, poranna."""

    sent = _sent(DAY, datetime(2026, 11, 10, 7, 30, tzinfo=timezone.utc))

    assert _due(_at(DAY + timedelta(days=1), 16, 59), sent=[sent]) == ()
    assert _days(_due(_at(DAY + timedelta(days=1), 18, 0), sent=[sent])) == [("jan.testowy", DAY)]


@given(
    minute=st.integers(min_value=0, max_value=3 * 24 * 60 - 1),
    workers=st.lists(st.sampled_from(["Jan.Testowy", "Ewa.Probna", "Obcy.Wykonawca"]), min_size=1, max_size=6),
    reported=st.sets(st.tuples(st.sampled_from([JAN, JAN_PRYWATNY, EWA]), st.integers(0, 3))),
    sent_before=st.sets(st.tuples(st.sampled_from([JAN, EWA]), st.integers(0, 3), st.integers(0, 3 * 24 * 60 - 1))),
)
@example(minute=24 * 60 + 8 * 60, workers=["Jan.Testowy", "Ewa.Probna"], reported=set(), sent_before=set())
@settings(derandomize=True, database=None, max_examples=200, deadline=None)
def test_drugie_sprawdzenie_w_tej_samej_chwili_z_wyslanymi_z_pierwszego_nie_daje_nic(
    minute: int,
    workers: list[str],
    reported: set[tuple[str, int]],
    sent_before: set[tuple[str, int, int]],
) -> None:
    """Własność: przypomnienia z pierwszego wywołania, wysłane w tej chwili, zamykają porę, więc drugie wywołanie w tej
    samej chwili nie daje żadnego, przy każdych zleceniach, raportach i wcześniejszych przypomnieniach (US 34)."""

    start = _at(DAY - timedelta(days=1), 0)
    now = start + timedelta(minutes=minute)
    orders = [
        _order(worker, DAY - timedelta(days=1) + timedelta(days=index % 3), 40000001 + index)
        for index, worker in enumerate(workers)
    ]
    mails = [_mail(sender, f"Raport {DAY + timedelta(days=offset - 1):%d.%m.%Y}") for sender, offset in reported]
    sent = [_sent(DAY + timedelta(days=offset - 1), start + timedelta(minutes=at), recipient) for recipient, offset, at in sent_before]

    first = _due(now, orders, mails=mails, sent=sent)
    sent_now = [_sent(reminder.day, now, *(address.shown() for address in reminder.recipients)) for reminder in first]

    assert _due(now, orders, mails=mails, sent=[*sent, *sent_now]) == ()


def test_przypomnienie_do_drugiego_adresu_wykonawcy_tez_zamyka_pore() -> None:
    """Wykonawca z dwoma adresami dostaje jedno przypomnienie na oba, a przypomnienie na którykolwiek zamyka porę."""

    [reminder] = _due(NEXT_MORNING)

    assert reminder.recipients == (_address(JAN_PRYWATNY), _address(JAN))
    assert _due(NEXT_MORNING, sent=[_sent(DAY, NEXT_MORNING, JAN_PRYWATNY)]) == ()


def test_przypomnienie_za_inny_dzien_albo_do_innego_wykonawcy_nie_zamyka_pory() -> None:
    sent = [_sent(DAY - timedelta(days=1), NEXT_MORNING, JAN), _sent(DAY, NEXT_MORNING, EWA)]

    assert _days(_due(NEXT_MORNING, sent=sent)) == [("jan.testowy", DAY)]


@pytest.mark.parametrize(
    ("mail", "ends"),
    [
        pytest.param(_mail(JAN, "Raport 09.11.2026", "40000001 tak inst20m"), True, id="pelny"),
        pytest.param(_mail(JAN, "Raport 09.11.2026", "40000002 tak inst20m"), True, id="niepelny-inne-zlecenie"),
        pytest.param(_mail(JAN_PRYWATNY, "raport 9.11.26", "40000001 nie brak klienta"), True, id="drugi-adres-krotka-data"),
        pytest.param(_mail(JAN, "Raport 09.11.2026", "dziś nic"), False, id="bez-wpisow"),
        pytest.param(_mail(JAN, "Raport 09.11.2016", "40000001 tak inst20m"), True, id="literowka-w-roku"),
        pytest.param(_mail(JAN, "Raport 9.11", "40000001 tak inst20m"), True, id="blad-tematu-bez-roku"),
        pytest.param(_mail(JAN, "Raport z poniedziałku", "40000001 tak inst20m"), True, id="blad-tematu-bez-daty"),
        pytest.param(_mail(JAN, "Re: Raport 09.11.2026 - BŁĘDY PROSZĘ POPRAW", "40000001 tak inst20m"), True, id="poprawka-w-odpowiedzi"),
        pytest.param(_mail(JAN, "Re: Zmiana w raportach 09.11.2026", "40000001 tak inst20m"), False, id="odpowiedz-o-czym-innym"),
        pytest.param(_mail(JAN, "Fwd: Raport 09.11.2026", "40000001 tak inst20m"), False, id="przekazany-raport"),
        pytest.param(_mail(JAN, "Raport 08.11.2026", "40000001 tak inst20m"), False, id="inny-dzien"),
        pytest.param(_mail(EWA, "Raport 09.11.2026", "40000001 tak inst20m"), False, id="inny-wykonawca"),
        pytest.param(_mail("obcy@przyklad.invalid", "Raport 09.11.2026", "40000001 tak"), False, id="adres-spoza-listy"),
    ],
)
def test_raport_za_dzien_nawet_niepelny_i_z_bledem_tematu_konczy_przypomnienia_a_raport_za_inny_dzien_nie(
    mail: ReportMail, ends: bool
) -> None:
    """Każdy Raport wykonawcy za dzień X od Wykonawcy z listy, nawet niepełny, kończy przypomnienia za X, także z błędem
    tematu, który liczy się za wskazany dzień (ADR 0041, historie 3, 5, 20), i poprawka raportu w odpowiedzi (historia 6),
    a odpowiedź na mail o czym innym, przekazany raport, raport za inny dzień, raport kogoś innego i mail bez żadnego
    Wpisu, który nie jest raportem (ADR 0041), nie (US 37–38)."""

    assert _days(_due(NEXT_MORNING, mails=[mail])) == ([] if ends else [("jan.testowy", DAY)])


def test_plik_zbiorczy_okresu_dzien_przed_wdrozeniem_dzien_bez_zlecen_i_wykonawca_spoza_listy_nie_dostaja_przypomnien() -> None:
    """Przypomnienia ustają, gdy okres dnia ma Plik zbiorczy, liczą się dni od wdrożenia przypomnień, dzień bez zleceń
    Wykonawcy go nie daje, a Wykonawca bez adresu na liście nie dostaje żadnego (US 36, 39, 41)."""

    later = _at(DAY + timedelta(days=2), 9)
    orders = [_order(), _order("Obcy.Wykonawca", number=40000002), _order(day=DAY + timedelta(days=1), number=40000003)]

    assert _days(_due(later, orders)) == [("jan.testowy", DAY), ("jan.testowy", DAY + timedelta(days=1))]
    # 9.11 (poniedziałek) kończy okres 03_09_11_2026, a 10.11 zaczyna następny.
    assert _days(_due(later, orders, closed=[period_of(DAY).token])) == [("jan.testowy", DAY + timedelta(days=1))]
    assert _days(_due(later, orders, rollout=DAY + timedelta(days=1))) == [("jan.testowy", DAY + timedelta(days=1))]
    assert _days(_due(later, [_order(day=DAY + timedelta(days=1))])) == [("jan.testowy", DAY + timedelta(days=1))]
    assert _due(later, [_order("Obcy.Wykonawca")]) == ()


def test_kilka_brakujacych_dni_daje_osobne_przypomnienie_za_kazdy_dzien() -> None:
    """Brak raportu za kilka dni daje osobny mail za każdy dzień, z jego datą w temacie i treści (US 40)."""

    orders = [_order(day=DAY), _order(day=DAY + timedelta(days=1), number=40000002), _order("Ewa.Probna", number=40000003)]

    found = _due(_at(DAY + timedelta(days=2), 8), orders)

    assert [(reminder.worker, reminder.day, reminder.subject) for reminder in found] == [
        ("ewa.probna", DAY, "Przypomnienie: raport za dzień 09.11.2026"),
        ("jan.testowy", DAY, "Przypomnienie: raport za dzień 09.11.2026"),
        ("jan.testowy", DAY + timedelta(days=1), "Przypomnienie: raport za dzień 10.11.2026"),
    ]
    assert "Temat maila: Raport 10.11.2026" in found[2].text


EXPECTED_TEXT = """Poproszę o wysłanie raportu za dzień 05.11.2026.

Raport proszę wysłać według tego wzoru:
Temat maila: Raport 05.11.2026
Treść maila: NR. ZLECENIA [spacja] tak [spacja] kody czynności albo NR. ZLECENIA [spacja] nie [spacja] powód
PRZYKŁAD:
12345678 tak inst20m spawpg
12345679 nie brak klienta
"""


@pytest.mark.parametrize(
    ("footer", "expected"),
    [
        pytest.param("Pozdrawiam\nTata Testowy\ntel. w stopce\n", EXPECTED_TEXT + "\nPozdrawiam\nTata Testowy\ntel. w stopce\n", id="ze-stopka"),
        pytest.param("", EXPECTED_TEXT, id="bez-stopki"),
        pytest.param(" \n", EXPECTED_TEXT, id="pusta-stopka"),
    ],
)
def test_tresc_przypomnienia_ma_temat_wzor_i_przyklad_ze_speca_a_na_koncu_stopke_taty(footer: str, expected: str) -> None:
    """Temat i treść ustalone przez Maksa (spec #1344, Implementation Decisions) są treścią domyślną, a na końcu stopka
    z Ustawień albo nic (US 43–44)."""

    day = date(2026, 11, 5)

    [reminder] = _due(_at(date(2026, 11, 6), 8), [_order(day=day)], footer=footer)

    assert reminder.subject == "Przypomnienie: raport za dzień 05.11.2026"
    assert reminder.text == expected
    assert EXAMPLE_NUMBERS == {OrderNumber("12345678"), OrderNumber("12345679")}


@pytest.mark.parametrize(
    ("subject", "day"),
    [
        pytest.param("Przypomnienie: raport za dzień 05.11.2026", date(2026, 11, 5), id="postac-centrum"),
        pytest.param("  Przypomnienie: raport za dzień 05.11.2026 ", date(2026, 11, 5), id="biale-znaki-wokol"),
        pytest.param("przypomnienie: raport za dzień 05.11.2026", None, id="mala-litera"),
        pytest.param("Przypomnienie: raport za dzień 5.11.2026", None, id="bez-zera"),
        pytest.param("Przypomnienie: raport za dzień 31.11.2026", None, id="nie-dzien"),
        pytest.param("Re: Przypomnienie: raport za dzień 05.11.2026", None, id="odpowiedz"),
        pytest.param("Przypomnienie: raport za dzień 05.11.2026 pilne", None, id="dopisek"),
        pytest.param("Raport 05.11.2026", None, id="raport"),
    ],
)
def test_dzien_z_tematu_przypomnienia_czyta_tylko_postac_ktora_pisze_centrum(subject: str, day: date | None) -> None:
    """„Wysłane” liczą jako przypomnienie tylko temat, który pisze Centrum; inne postacie to granica, nie przypomnienie."""

    assert reminder_day(subject) == day


@given(st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31)))
@settings(derandomize=True, database=None)
def test_temat_przypomnienia_czyta_sie_z_powrotem_jako_jego_dzien(day: date) -> None:
    assert reminder_day(reminder_subject(day)) == day


# --- Przypomnienie tylko bez raportu: jedna reguła dnia raportu z Wpisaniem raportów (ADR 0041) ---


@pytest.mark.parametrize(
    ("text", "problems"),
    [
        pytest.param("40000001 tak montaż ONT", [], id="zwykly-opis"),
        pytest.param("40000001 tak utp18m", [], id="wlasny-zapis"),
        pytest.param("40000001 tak inst20m, klient zadowolony", [], id="kod-obok-opisu"),
        pytest.param("40000001 tak instutp40m", ["FaultyDescription"], id="liczba-spoza-przedzialow"),
        pytest.param("40000001 tak instmdik inst20m", ["FaultyDescription"], id="kolumna-drugi-raz"),
        pytest.param("40000001 tak montaż instutp0m", ["FaultyDescription"], id="kod-spoza-przedzialow-obok-opisu"),
    ],
)
@pytest.mark.parametrize(
    "arrived", [pytest.param(_at(DAY, 19), id="tego-dnia"), pytest.param(_at(DAY + timedelta(days=1), 7), id="nastepnego-rana")]
)
@pytest.mark.parametrize(
    "now",
    [
        pytest.param(NEXT_MORNING, id="poranna"),
        pytest.param(_at(DAY + timedelta(days=1), 18), id="wieczorna"),
        pytest.param(_at(DAY + timedelta(days=2), 8), id="poranna-kolejnego-dnia"),
    ],
)
def test_raport_z_bledem_opisu_albo_zwyklym_opisem_konczy_przypomnienia_za_swoj_dzien_w_kazdej_porze(
    text: str, problems: list[str], arrived: datetime, now: datetime
) -> None:
    """ADR 0041 (historie 1, 2, 9, 33): Raport wykonawcy za dzień X z Wpisem ``tak`` z Błędem opisu albo ze zwykłym
    opisem jest przysłany, także gdy przyjdzie rano dnia X+1, więc Wykonawca nie dostaje przypomnienia za X w żadnej
    porze; Błąd opisu widzi tylko tata, przy zleceniu we Wpisaniu raportów, a zwykły opis nie jest problemem."""

    mails = [_mail(JAN, "Raport 09.11.2026", text, arrived)]

    assert [type(problem).__name__ for problem in enter_reports(_reports(now, [_order()], mails)).problems] == problems
    assert _due(now, mails=mails) == ()


MISTAKEN_ORDERS = (
    _order(day=date(2026, 11, 16), number=40000001, row=120),
    _order(day=date(2026, 11, 16), number=40000002, row=121),
    _order(day=date(2026, 11, 26), number=40000003, row=122),
)


@pytest.mark.parametrize(
    ("now", "figures", "due"),
    [
        pytest.param(_at(date(2026, 11, 17), 8), {date(2026, 11, 16): 1}, [], id="dzien-z-tematu-po-dzis"),
        pytest.param(
            _at(date(2026, 11, 27), 8),
            {date(2026, 11, 16): 1, date(2026, 11, 26): 0},
            [("jan.testowy", date(2026, 11, 26))],
            id="dzien-z-tematu-w-oknie",
        ),
    ],
)
def test_raport_z_pomylonym_tematem_konczy_przypomnienia_za_dzien_swoich_zlecen_a_nie_za_dzien_z_tematu(
    now: datetime, figures: dict[date, int], due: list[tuple[str, date]]
) -> None:
    """ADR 0041 (historia 4) i ADR 0029: ``Raport 26.11.2026`` z dwoma numerami zleceń Jana z 16.11 to pomylony temat.
    Wpisanie raportów wpisuje go do zleceń z 16.11 z informacją dla taty, także gdy 26.11 jest jeszcze po dziś, a
    kafelek liczy go za 16.11; przypomnienia za 16.11 ustają, a za 26.11 idą, bo za ten dzień raportu nie ma."""

    mails = [_mail(JAN, "Raport 26.11.2026", "40000001 tak inst20m\n40000002 tak spawpg", _at(date(2026, 11, 16), 21))]

    entered = enter_reports(_reports(now, MISTAKEN_ORDERS, mails))

    assert {change.order for change in entered.changes} == {MISTAKEN_ORDERS[0].row, MISTAKEN_ORDERS[1].row}
    assert {note.order_day for note in entered.notes if isinstance(note, SubjectLost)} == {date(2026, 11, 16)}
    assert {figure.day: figure.mails for figure in entered.workers} == figures
    assert _days(_due(now, MISTAKEN_ORDERS, mails=mails)) == due


SAME = (
    _order(),
    _order(number=40000002, row=121),
    _order("Ewa.Probna", number=40000003, row=122),
    _order(day=DAY + timedelta(days=1), number=40000004, row=123),
    _order(day=DAY + timedelta(days=1), number=40000005, row=124),
    _order("Ewa.Probna", number=40000005, row=125),
)
"""Zlecenia Jana z 9.11 i 10.11 i Ewy z 9.11, a numer 40000005 u Jana 10.11 i u Ewy 9.11: o 8:00 11.11 należą się
przypomnienia za oba dni."""
JAN_9 = ("jan.testowy", DAY)
JAN_10 = ("jan.testowy", DAY + timedelta(days=1))
EWA_9 = ("ewa.probna", DAY)
ADDED_TEXT = "40000007 tak inst20m\n40000008 tak spawpg"
"""Dwa numery, których INTERMAX nie ma: raport z nimi dopisuje oba Janowi (Zlecenia dopisane z raportu)."""
TIE = MailId.of("<ten-sam@przyklad.invalid>")
TIE_FAULTY = ReportMail(TIE, _address(JAN), "Raport 09.11.2026", "40000001 tak montaż", _at(DAY, 19))
TIE_GOOD = ReportMail(TIE, _address(JAN), "Raport 09.11.2026", "40000001 tak inst20m", _at(DAY, 19))


@pytest.mark.parametrize(
    ("earlier", "mails", "reported"),
    [
        pytest.param([], [], set(), id="bez-maila"),
        pytest.param([], [_mail(JAN, "Raport 09.11.2026", "40000001 tak inst20m")], {JAN_9}, id="czytelny"),
        pytest.param([], [_mail(JAN, "Raport 09.11.2026", "40000001 tak montaż")], {JAN_9}, id="blad-opisu"),
        pytest.param([], [_mail(JAN, "Raport 09.11.2026", "dziś nic")], set(), id="bez-wpisow"),
        pytest.param([], [_mail(JAN, "Raport 10.11.2026", "40000001 tak inst20m\n40000002 tak spawpg")], {JAN_9}, id="pomylony-temat"),
        pytest.param([], [_mail(JAN, "Raport 26.11.2026", "40000001 tak inst20m\n40000002 tak spawpg")], {JAN_9}, id="pomylony-temat-po-dzis"),
        pytest.param(
            [],
            [_mail(JAN, "Raport 30.10.2026", "40000001 tak inst20m\n40000002 tak spawpg")],
            {JAN_9},
            id="pomylony-temat-sprzed-wdrozenia",
        ),
        pytest.param(
            [],
            [_mail(JAN, "Raport 08.11.2026", "40000001 tak inst20m\n40000002 tak spawpg\n40000005 tak inst20m")],
            {JAN_9},
            id="pomylony-temat-z-numerem-w-kilku-zleceniach",
        ),
        pytest.param(
            [],
            [_mail(JAN, "Raport 10.11.2026", "40000001 tak inst20m\n40000004 tak spawpg")],
            {JAN_10},
            id="jeden-niezgodny-wpis",
        ),
        pytest.param([], [_mail(JAN, f"Re: {reminder_subject(DAY)}", "40000001 tak inst20m")], {JAN_9}, id="odpowiedz-na-przypomnienie"),
        pytest.param([], [_mail(EWA, "Raport 09.11.2026", "40000001 tak inst20m")], {EWA_9}, id="raport-innego-wykonawcy"),
        pytest.param(
            [], [_mail(JAN, "Raport 09.11.2026 Kowalski", "40000001 tak inst20m", _at(DAY + timedelta(days=1), 20))], {JAN_9}, id="inne-slowa"
        ),
        pytest.param(
            [],
            [_mail(JAN, "Raport za 10.11.2026 2 montaże 8 usterek", "40000004 tak inst20m", _at(DAY + timedelta(days=1), 20))],
            {JAN_10},
            id="inne-slowa-z-liczbami",
        ),
        pytest.param([], [_mail(JAN, "raport 10.11", "40000004 tak", _at(DAY + timedelta(days=1), 20))], {JAN_10}, id="bez-roku"),
        pytest.param([], [_mail(JAN, "Raport 9.11", "40000001 tak inst20m")], {JAN_9}, id="bez-roku-dzien-bez-zera"),
        pytest.param(
            [],
            [_mail(JAN, "Raport 10.11.2026 Kowalski", "40000001 tak inst20m\n40000002 tak spawpg", _at(DAY + timedelta(days=1), 20))],
            {JAN_9},
            id="inne-slowa-numery-wygrywaja-z-data",
        ),
        pytest.param([], [_mail(JAN, "Raport", "40000004 tak", _at(DAY + timedelta(days=1), 20))], {JAN_10}, id="bez-dnia"),
        pytest.param([], [_mail(JAN, "Raport", "40000004 tak")], {JAN_9}, id="bez-dnia-nie-pozniej-niz-przyjscie"),
        pytest.param(
            [],
            [
                _mail(JAN, "Raport 10.11.2026", "40000004 tak", _at(DAY + timedelta(days=1), 19)),
                _mail(JAN, "Raport", "40000005 tak", _at(DAY + timedelta(days=1), 20)),
            ],
            {JAN_9, JAN_10},
            id="bez-dnia-za-dzien-bez-innego-raportu",
        ),
        pytest.param(
            [],
            [
                _mail(JAN, "Raport", "40000005 tak", _at(DAY + timedelta(days=1), 21)),
                _mail(JAN, "Raport", "40000004 tak", _at(DAY + timedelta(days=1), 20)),
            ],
            {JAN_9, JAN_10},
            id="dwa-bez-dnia-po-kolei-przyjscia",
        ),
        pytest.param(
            [],
            [
                _mail(JAN, "Raport", "40000005 tak", _at(DAY + timedelta(days=1), 20)),
                _mail(JAN, "Raport 10.11.2026 Kowalski", "40000004 tak", _at(DAY + timedelta(days=1), 21)),
            ],
            {JAN_9, JAN_10},
            id="bez-dnia-po-dniu-z-tematu-pozniejszego-maila",
        ),
        pytest.param([], [_mail(JAN, "Raport", "40000001 tak", _at(DAY - timedelta(days=1), 20))], set(), id="bez-dnia-bez-takiego-dnia"),
        pytest.param([], [_mail(JAN, "Raport 31.11.2026", "40000004 tak")], {JAN_9}, id="data-ktora-nie-jest-dniem"),
        pytest.param([], [_mail(JAN, "Montaże 09.11.2026", "40000001 tak inst20m")], set(), id="bez-slowa-raport"),
        pytest.param([], [_mail(JAN, "Re: Raport 09.11.2026 - BŁĘDY PROSZĘ POPRAW", "40000001 tak inst20m")], {JAN_9}, id="poprawka-w-odpowiedzi"),
        pytest.param(
            [],
            [
                _mail(
                    JAN,
                    "Re: Raport 10.11.2026 - BŁĘDY PROSZĘ POPRAW",
                    "40000004 tak inst20m\n\n> 40000001 tak inst20m\n> 40000002 tak spawpg",
                    _at(DAY + timedelta(days=1), 20),
                )
            ],
            {JAN_10},
            id="poprawka-w-odpowiedzi-cytat-nie-daje-wpisow",
        ),
        pytest.param(
            [],
            [_mail(JAN, "Odp: Re: Rapotr 10.11.2026 popraw", "40000004 tak inst20m", _at(DAY + timedelta(days=1), 20))],
            {JAN_10},
            id="poprawka-w-odpowiedzi-z-outlooka-z-literowka",
        ),
        pytest.param([], [_mail(JAN, "Fwd: Raport 09.11.2026", "40000001 tak inst20m")], set(), id="przekazany-raport"),
        pytest.param([], [_mail(JAN, "Re: Zmiana w raportach 09.11.2026", "40000001 tak inst20m")], set(), id="odpowiedz-o-czym-innym"),
        pytest.param([], [_mail("obcy@przyklad.invalid", "Raport 09.11.2026", "40000001 tak")], set(), id="adres-spoza-listy"),
        pytest.param([], [TIE_FAULTY, TIE_GOOD], {JAN_9}, id="remis-blad-opisu-pierwszy"),
        pytest.param([], [TIE_GOOD, TIE_FAULTY], {JAN_9}, id="remis-blad-opisu-drugi"),
        pytest.param(
            [_mail(JAN, "Raport 09.11.2026", ADDED_TEXT, _at(DAY + timedelta(days=1), 6))],
            [_mail(JAN, "Raport 10.11.2026", ADDED_TEXT, _at(DAY + timedelta(days=1), 20))],
            {JAN_9, JAN_10},
            id="pamiec-po-dopisaniu-z-raportu",
        ),
        pytest.param(
            [_mail(JAN, "Raport 09.11.2026", "40000001 tak inst20m\n40000004 tak spawpg", _at(DAY + timedelta(days=1), 6))],
            [_mail(JAN, "Raport 10.11.2026", "40000001 tak inst20m\n40000004 tak spawpg", _at(DAY + timedelta(days=1), 20))],
            {JAN_9, JAN_10},
            id="pamiec-po-przeniesieniu",
        ),
    ],
)
def test_wpisanie_raportow_i_przypomnienia_licza_ten_sam_zbior_dni_z_przyslanym_raportem(
    earlier: list[ReportMail], mails: list[ReportMail], reported: set[tuple[str, date]]
) -> None:
    """ADR 0041 (historia 14): dla tych samych maili i zleceń dzień Wykonawcy, za który kafelek Wpisania raportów liczy
    Raport wykonawcy, to dokładnie dzień, za który przypomnienie nie idzie: Raport z Błędem opisu jest
    przysłany, mail bez Wpisów nie jest raportem, pomylony temat (dwa numery z innego dnia, także z dniem z tematu po dziś albo sprzed wdrożenia) liczy się za
    dzień zleceń (bez dni numeru, który INTERMAX ma w kilku zleceniach, bo jego Wpis niczego nie wpisuje), a jeden
    niezgodny Wpis za dzień z tematu. Mail z tą samą chwilą i tym samym Message-ID daje ten sam
    wynik w każdej kolejności skrzynki. Raport z błędem tematu (historie 3, 5, 19–20) liczy się za dzień z tematu, gdy
    da się go przeczytać (inne słowa obok daty, data bez roku), z numerami zleceń, które dalej wygrywają z datą, a bez
    niego (temat bez daty albo z datą, która nie jest dniem) za ostatni dzień Wykonawcy ze zleceniami, za który nie ma
    innego raportu, także z błędem tematu z dniem z tematu, nie późniejszy niż dzień przyjścia maila, kolejne takie maile
    po kolei przyjścia; bez takiego dnia
    niczego nie kończy. Poprawka raportu w odpowiedzi (historie 6, 26–29) liczy się za dzień z tematu po przedrostkach
    z Wpisami tylko nad cytatem, a przekazany raport, odpowiedź na mail o czym innym (historie 30–31), mail bez słowa
    ``Raport`` i adres spoza listy nie są raportem Wykonawcy. Po wcześniejszym kliknięciu (``earlier``) obie operacje biorą tę samą pamięć Wpisania raportów i INTERMAX
    po nim: numery dopisane przez Centrum nie robią z poprawionego tematu pomylonego, a zlecenie po Przeniesieniu liczy
    się za dzień sprzed niego, więc ten sam raport z dobrą datą liczy się za dzień z tematu (W1 r1 #2059)."""

    now = _at(DAY + timedelta(days=2), 8)
    orders, memory = _after_click(_at(DAY + timedelta(days=1), 7), SAME, earlier)

    entered = enter_reports(_reports(now, orders, [*earlier, *mails], memory=memory))
    due = _due(now, orders, mails=[*earlier, *mails], memory=memory)

    open_days = {(order.key.worker, order.key.day) for order in SAME}
    assert {(figure.worker, figure.day) for figure in entered.workers if figure.mails} & open_days == reported
    assert open_days - set(_days(due)) == reported


def test_raport_wolnym_tekstem_z_wpisem_tak_konczy_przypomnienia_a_mail_bez_wpisu_nie() -> None:
    """Historia 10 speca #2032 (ADR 0041, „Co nie jest raportem”): 13–14.11 Wykonawcy pisali raporty wolnym tekstem.
    Raport za 13.11 z Wpisem ``tak`` ze zwykłym opisem jest przysłany: Wpisanie raportów wpisuje go bez problemu, bo
    zwykły opis nie jest Błędem opisu, a po Aktualizacji 17.11 rano przypomnienie za 13.11 nie idzie. Mail za 14.11 bez żadnego numeru zlecenia nie jest
    raportem, więc przypomnienie za 14.11 idzie."""

    day_13, day_14 = date(2026, 11, 13), date(2026, 11, 14)
    orders = (_order(day=day_13, number=40012345, row=120), _order(day=day_14, number=40012346, row=121))
    now = _at(date(2026, 11, 17), 8)
    mails = [
        _mail(JAN, "Raport 13.11.2026", "Dzień dobry,\n40012345 tak montaż ONT, klient zadowolony\nPozdrawiam Jan", _at(day_13, 19)),
        _mail(JAN, "Raport 14.11.2026", "Dzień dobry, dziś zrobiłem montaż ONT i jedną awarię.\nPozdrawiam Jan", _at(day_14, 19)),
    ]

    entered = enter_reports(_reports(now, orders, mails, rollout=date(2026, 11, 12)))

    assert entered.problems == ()
    assert [change.value for change in entered.changes] == ["tak", "montaż ONT, klient zadowolony"]
    assert _days(_due(now, orders, mails=mails, rollout=date(2026, 11, 12))) == [("jan.testowy", day_14)]


def test_przyklad_w_przypomnieniu_to_wpis_tak_z_samymi_kodami_legendy_z_wydania_i_wpis_nie_z_powodem() -> None:
    """ADR 0039: wzór treści i przykład pokazują kody, więc Wykonawca, który przepisze przykład, nie dostanie Błędu
    opisu przy legendzie z Wydania."""

    [reminder] = _due(NEXT_MORNING)
    lines = reminder.text.splitlines()
    example = lines.index("PRZYKŁAD:")
    yes, no = (line.split(maxsplit=2) for line in lines[example + 1 : example + 3])

    read = DEFAULT_ACTIVITY_LEGEND.read(yes[2])
    assert yes[1] == "tak" and isinstance(read, WithCodes) and read.spelled == tuple(yes[2].split())
    assert no[1:] == ["nie", "brak klienta"]


@pytest.mark.parametrize(
    ("gmail", "same"),
    [
        (_sent(DAY, NEXT_MORNING + timedelta(minutes=2)), True),
        (_sent(DAY, NEXT_MORNING - timedelta(minutes=2)), True),
        (_sent(DAY, NEXT_MORNING + timedelta(minutes=2, seconds=1)), False),
        (_sent(DAY, NEXT_MORNING - timedelta(minutes=2, seconds=1)), False),
        (_sent(DAY + timedelta(days=1), NEXT_MORNING), False),
        (_sent(DAY, NEXT_MORNING, EWA), False),
        (_sent(DAY, NEXT_MORNING, JAN, JAN_PRYWATNY), False),
    ],
)
def test_przypomnienie_z_wyslanych_to_ten_sam_mail_co_wyslane_w_pracy_przy_tych_samych_adresatach_dniu_i_zegarze_do_2_minut(
    gmail: SentReminder, same: bool
) -> None:
    """Przypomnienie, które praca Centrum pamięta z wysyłki (zegar laptopa taty), i przypomnienie z „Wysłanych” (zegar
    Gmaila) to ten sam mail przy tych samych adresatach i dniu przypomnienia i chwilach najwyżej zapas zegara
    (``CLOCK_MARGIN``, 2 minuty) od siebie w obie strony; inny dzień albo inni adresaci to inny mail."""

    assert _sent(DAY, NEXT_MORNING).same_mail(gmail) is same
