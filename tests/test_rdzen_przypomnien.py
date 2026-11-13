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

from rozliczenia.report_cells import OrderRow
from rozliczenia.settlement_period import period_of
from rozliczenia.worker_list import WorkerEntry, WorkerList
from rozliczenia.worker_reports import (
    DEFAULT_REMINDERS,
    EXAMPLE_NUMBERS,
    MailId,
    OrderNumber,
    RegisterOrder,
    Reminder,
    ReminderInputs,
    ReminderSchedule,
    ReminderSettings,
    ReportMail,
    SchedulesInEffect,
    SenderAddress,
    SentReminder,
    TimeRange,
    Window,
    reminder_day,
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
) -> tuple[Reminder, ...]:
    listed = workers or _workers()
    return reminders_due(
        ReminderInputs(
            now=now,
            window=Window.of(now.date(), rollout, closed),
            orders=orders or (_order(),),
            mails=mails,
            sent=sent,
            addresses=listed.addresses(),
            reminded=listed.reminded(),
            settings=settings or replace(DEFAULT_REMINDERS, enabled=True, since=rollout, footer=footer),
            in_effect=in_effect or SchedulesInEffect(),
        )
    )


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
        "Treść maila: NR. ZLECENIA [spacja] tak/nie [spacja] opis zrealizowanej czynności",
        "PRZYKŁAD:",
        "12345678 tak montaż ONT",
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
        pytest.param(_mail(JAN, "Raport 09.11.2026", "40000001 tak montaż"), True, id="pelny"),
        pytest.param(_mail(JAN, "Raport 09.11.2026", "dziś nic"), True, id="niepelny-bez-wpisu"),
        pytest.param(_mail(JAN_PRYWATNY, "raport 9.11.26", ""), True, id="drugi-adres-krotka-data"),
        pytest.param(_mail(JAN, "Raport 09.11.2016", "40000001 tak montaż"), True, id="literowka-w-roku"),
        pytest.param(_mail(JAN, "Raport 9.11", "40000001 tak montaż"), False, id="nieczytelny-bez-roku"),
        pytest.param(_mail(JAN, "Raport z poniedziałku", "40000001 tak montaż"), False, id="nieczytelny-bez-daty"),
        pytest.param(_mail(JAN, "Re: Raport 09.11.2026", "40000001 tak montaż"), False, id="odpowiedz"),
        pytest.param(_mail(JAN, "Raport 08.11.2026", "40000001 tak montaż"), False, id="inny-dzien"),
        pytest.param(_mail(EWA, "Raport 09.11.2026", "40000001 tak montaż"), False, id="inny-wykonawca"),
        pytest.param(_mail("obcy@przyklad.invalid", "Raport 09.11.2026", "40000001 tak"), False, id="adres-spoza-listy"),
    ],
)
def test_czytelny_raport_za_dzien_nawet_niepelny_konczy_przypomnienia_a_nieczytelny_temat_nie(
    mail: ReportMail, ends: bool
) -> None:
    """Każdy czytelny Raport wykonawcy za dzień X od Wykonawcy z listy, nawet niepełny, kończy przypomnienia za X, a
    mail z nieczytelnym tematem, odpowiedź, raport za inny dzień i raport kogoś innego nie (US 37–38)."""

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
Treść maila: NR. ZLECENIA [spacja] tak/nie [spacja] opis zrealizowanej czynności
PRZYKŁAD:
12345678 tak montaż ONT
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
