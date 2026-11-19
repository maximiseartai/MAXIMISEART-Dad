"""Odczyty maili okna (ADR 0041): ``WindowMails`` trzyma odczyt każdego maila, który odczyt okna
(``_reading.read_window``) wziął do Raportów wykonawców okna, a na zewnątrz daje tylko fakty z nich (liczba Raportów
wykonawców, zlecenia z Wpisem, loginy nadawców), maile w postaci kanonicznej dla odtworzenia z Logów oraz zapis do Logów
i odczyt z nich jako JSON. Wariant odczytu (``ReadReport``, ``ReadUnreadable``, ``ReadStranger``) nie wychodzi z
pakietu, a kapsuła nie jest iterowalna, więc moduł spoza pakietu nie ma po czym przejść.

Rekord ``WindowMails.log`` to JSON w schemacie odczytu maila Logów Wpisania raportów, którego właścicielem jest
``LoggedMail`` w ``centrum.report_entering_logs``: Logi walidują nim każdy rekord przed zapisem, a ``from_log`` dostaje
od nich tylko rekordy, które przeszły ten schemat.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from typing import TypeAlias, assert_never, final

from . import _canonical
from ._model import (
    Login,
    MailId,
    MailRead,
    OrderKey,
    OrderNumber,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    ReportEntry,
    ReportMail,
    ReportSubject,
    RequestedEntry,
    SenderAddress,
    SubjectFault,
    Verdict,
    VerdictFault,
)

JsonValue: TypeAlias = "str | int | bool | None | list[JsonValue] | dict[str, JsonValue]"
"""Wartość JSON rekordu odczytu maila w Logach (``WindowMails.log``, ``WindowMails.from_log``)."""


@final
class WindowMails:
    """Odczyty maili okna w kolejności odczytu okna (``_reading._mail_order``): Raporty wykonawców z dniem z tematu,
    raporty z błędem tematu i maile od nieznanych nadawców, każdy z mailem i chwilą przyjścia, bez adresu, tematu i
    treści poza Wpisami (temat raportu z błędem tematu ma tylko problem ``UnreadableSubject``). Dwie kapsuły są równe,
    gdy mają te same odczyty w tej samej kolejności. Odczyty są w slocie z name mangling (``__reads``), więc wzorzec
    klasy ani atrybut spoza klasy nie nazwie ich tak, żeby przeszło mypy, a podklasa, która dałaby odczyty, nie
    przechodzi mypy (``final``)."""

    __slots__ = ("__reads",)

    def __init__(self, reads: Iterable[MailRead]) -> None:
        self.__reads = tuple(reads)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, WindowMails) and self.__reads == other.__reads

    def __hash__(self) -> int:
        return hash(self.__reads)

    def __repr__(self) -> str:
        return f"WindowMails({self.__reads!r})"

    @property
    def worker_report_count(self) -> int:
        """Raporty wykonawców z dniem z tematu, bez raportów z błędem tematu i maili od nieznanych nadawców."""

        return sum(isinstance(found, ReadReport) for found in self.__reads)

    def said(self, requested: Iterable[RequestedEntry]) -> frozenset[OrderKey]:
        """Zlecenia (numer, dzień, Wykonawca) z Wpisem Raportów wykonawców Wpisania raportów: Wpis Raportu wykonawcy z
        dniem z tematu i Wpis na życzenie raportu z błędem tematu z dniem decyzji taty z ``requested``
        (``requested_reports``); bez decyzji same Wpisy Raportów wykonawców z dniem z tematu."""

        reports = [found for found in self.__reads if isinstance(found, ReadReport)]
        unreadable = [found for found in self.__reads if isinstance(found, ReadUnreadable)]
        asked = requested_reports(unreadable, decided(unreadable, requested))
        return frozenset(OrderKey(entry.number, report.day, report.worker) for report in (*reports, *asked) for entry in report.entries)

    def workers(self) -> tuple[Login, ...]:
        """Loginy Wykonawców, od których są odczyty (bez nieznanych nadawców), alfabetycznie, każdy raz."""

        return tuple(sorted({found.worker for found in self.__reads if not isinstance(found, ReadStranger)}))

    def canonical(
        self, workers: Mapping[Login, SenderAddress], stranger: Callable[[MailId, date], SenderAddress]
    ) -> tuple[ReportMail, ...]:
        """Mail w postaci kanonicznej (``_canonical.as_mail``) w miejscu każdego odczytu, po kolei, z którego rdzeń czyta
        ten sam odczyt: od adresu ``workers`` jego Wykonawcy, a mail od nieznanego nadawcy od adresu, który ``stranger``
        daje dla jego maila i dnia z tematu, jak problem ``UnknownSender`` (wołany raz na taki mail, po kolei)."""

        return tuple(
            _canonical.as_mail(found, stranger(found.mail, found.day) if isinstance(found, ReadStranger) else workers[found.worker])
            for found in self.__reads
        )

    def log(self) -> tuple[dict[str, JsonValue], ...]:
        """Zapis każdego odczytu do Logów Wpisania raportów, po kolei, jako JSON w schemacie ``LoggedMail``: Raport
        wykonawcy z loginem, dniem z tematu i Wpisami, raport z błędem tematu z loginem, powodem, numerami Wpisów
        rosnąco, dniem z tematu (``None``: bez dnia) i Wpisami, a mail od nieznanego nadawcy z dniem z tematu; każdy ze
        skrótem maila i chwilą przyjścia, bez adresu, tematu i reszty treści maila."""

        return tuple(map(_logged, self.__reads))

    @classmethod
    def from_log(cls, records: Iterable[Mapping[str, JsonValue]]) -> WindowMails:
        """Odczyty z ich zapisu w Logach (``log``) dla odtworzenia Uruchomienia z Logów. Raport z błędem tematu ma pusty
        temat, bo Logi tematów nie mają, a postać kanoniczna bierze z odczytu tylko powód i dzień z tematu. Logi sprzed
        Wpisów przy błędzie tematu (``entries`` ``None``) dają numery z ``numbers`` rosnąco jako Wpisy bez znaku i
        czynności (``VerdictFault.MISSING``), bo wtedy Wpisy takiego maila niczego nie zmieniały, a Logi sprzed numerów
        (oba ``None``) mail bez Wpisów. Rekord spoza schematu (``ValueError``) Logi odrzucają wcześniej."""

        return cls(map(_read, records))


def decided(
    unreadable: Iterable[ReadUnreadable], requested: Iterable[RequestedEntry]
) -> dict[tuple[MailId, OrderNumber], tuple[RequestedEntry, ReportEntry]]:
    """Decyzja taty przy każdym Wpisie raportu z błędem tematu, przy którym kliknął: jedyny Wpis numeru w tym mailu z
    zamiarem i czynnościami z decyzji; przy kilku decyzjach jednego Wpisu najnowsza."""

    said = {(found.mail, found.worker): found.entries for found in unreadable}
    chosen: dict[tuple[MailId, OrderNumber], tuple[RequestedEntry, ReportEntry]] = {}
    for decision in sorted(requested, key=lambda decision: (decision.at, decision.day)):
        entries = [entry for entry in said.get((decision.mail, decision.worker), ()) if entry.number == decision.number]
        match entries:
            case [entry] if (entry.leaning, entry.activities) == (decision.verdict, decision.activities):
                chosen[decision.mail, decision.number] = (decision, entry)
            case _:
                pass
    return chosen


def requested_reports(
    unreadable: Iterable[ReadUnreadable], chosen: Mapping[tuple[MailId, OrderNumber], tuple[RequestedEntry, ReportEntry]]
) -> tuple[ReadReport, ...]:
    """Wpisy na życzenie raportów z błędem tematu jako Raporty wykonawcy tego maila, jeden na dzień decyzji, z Wpisami
    w kolejności maila; znak zamiast ``tak``/``nie`` zamienia dopasowanie tą samą decyzją (``_matching._requested``)."""

    found_reports: list[ReadReport] = []
    for found in unreadable:
        days: dict[date, list[ReportEntry]] = {}
        for entry in found.entries:
            if (pick := chosen.get((found.mail, entry.number))) is not None and pick[1] == entry:
                days.setdefault(pick[0].day, []).append(entry)
        found_reports += [
            ReadReport(found.mail, found.arrived, found.worker, day, tuple(entries)) for day, entries in sorted(days.items())
        ]
    return tuple(found_reports)


def _logged(found: MailRead) -> dict[str, JsonValue]:
    match found:
        case ReadReport():
            return {
                "kind": "report",
                "mail": found.mail.digest,
                "arrived": found.arrived.isoformat(),
                "worker": found.worker,
                "day": found.day.isoformat(),
                "entries": _logged_entries(found.entries),
            }
        case ReadUnreadable():
            return {
                "kind": "unreadable",
                "mail": found.mail.digest,
                "arrived": found.arrived.isoformat(),
                "worker": found.worker,
                "fault": found.fault.value,
                "numbers": [number for number in sorted(found.numbers)],
                "day": None if found.day is None else found.day.isoformat(),
                "entries": _logged_entries(found.entries),
            }
        case ReadStranger():
            return {"kind": "stranger", "mail": found.mail.digest, "arrived": found.arrived.isoformat(), "day": found.day.isoformat()}
        case _:
            assert_never(found)


def _logged_entries(entries: Iterable[ReportEntry]) -> list[JsonValue]:
    return [
        {
            "number": entry.number,
            "verdict": None if entry.verdict is None else entry.verdict.value,
            "fault": None if entry.fault is None else entry.fault.value,
            "activities": entry.activities,
        }
        for entry in entries
    ]


def _read(record: Mapping[str, JsonValue]) -> MailRead:
    mail, arrived = MailId(_text(record, "mail")), datetime.fromisoformat(_text(record, "arrived"))
    match record["kind"]:
        case "report":
            day = date.fromisoformat(_text(record, "day"))
            return ReadReport(mail, arrived, Login(_text(record, "worker")), day, _entries(record["entries"]))
        case "unreadable":
            logged = record["entries"]
            if logged is None:
                numbers = sorted(OrderNumber(_json_text(number)) for number in _list(record["numbers"] or []))
                entries = tuple(ReportEntry(number, None, VerdictFault.MISSING, "") for number in numbers)
            else:
                entries = _entries(logged)
            fault = SubjectFault(_text(record, "fault"))
            subject_day = None if record["day"] is None else date.fromisoformat(_text(record, "day"))
            return ReadUnreadable(mail, arrived, Login(_text(record, "worker")), fault, entries, subject_day, ReportSubject(""))
        case "stranger":
            return ReadStranger(mail, arrived, date.fromisoformat(_text(record, "day")))
        case kind:
            raise ValueError(f"rodzaj odczytu maila spoza schematu Logów: {kind!r}")


def _entries(logged: JsonValue) -> tuple[ReportEntry, ...]:
    return tuple(map(_entry, _list(logged)))


def _entry(logged: JsonValue) -> ReportEntry:
    if not isinstance(logged, dict):
        raise ValueError("Wpis odczytu maila w Logach nie jest obiektem JSON")
    verdict = None if logged["verdict"] is None else Verdict(_text(logged, "verdict"))
    fault = None if logged["fault"] is None else VerdictFault(_text(logged, "fault"))
    return ReportEntry(OrderNumber(_text(logged, "number")), verdict, fault, _text(logged, "activities"))


def _list(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ValueError("pole odczytu maila w Logach nie jest listą JSON")
    return value


def _text(record: Mapping[str, JsonValue], key: str) -> str:
    return _json_text(record[key])


def _json_text(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise ValueError("pole odczytu maila w Logach nie jest tekstem")
    return value
