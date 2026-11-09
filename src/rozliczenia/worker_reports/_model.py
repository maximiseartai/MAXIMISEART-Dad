"""Typy rdzenia raportów, które pakiet ``worker_reports`` re-eksportuje, a jego moduły ``_*.py`` biorą stąd.

Osobny moduł, żeby pakiet importował moduły prywatne na górze bez cyklu: te biorą typy stąd, nie z pakietu.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parseaddr
from enum import Enum, auto
import hashlib
from typing import ClassVar, Final, NewType, assert_never

from ..report_cells import CellChange, OrderRow, ReportColumn
from ..settlement_period import period_of
from ..text import normalize_text

SUBJECT_WORD: Final = "raport"
"""Słowo tematu Raportu wykonawcy bez względu na wielkość liter: port bierze ze skrzynki tylko maile z nim w temacie,
a rdzeń rozstrzyga resztę tematu."""

Login = NewType("Login", str)
"""Identyfikator Wykonawcy z ``WYKONAWCA`` po ``normalize_text``: klucz Konfiguracji wykonawców i pliku adresów."""

_DIGEST_LETTERS: Final = 16
_LETTERS: Final = str.maketrans("0123456789abcdef", "abcdefghijklmnop")


@dataclass(frozen=True, order=True)
class MailId:
    """Mail ze Skrzynki raportów: 16 liter a–p ze skrótu SHA-256 jego Message-ID.

    Same litery, żeby strażnik reguły danych nie wziął skrótu za numer telefonu. Sam Message-ID do rdzenia nie wchodzi.
    """

    digest: str

    @classmethod
    def of(cls, message_id: str) -> MailId:
        hexdigest = hashlib.sha256(message_id.encode("utf-8", "surrogateescape")).hexdigest()
        return cls(hexdigest[:_DIGEST_LETTERS].translate(_LETTERS))


class SenderAddress:
    """Adres nadawcy Raportu wykonawcy: addr-spec po ``casefold``.

    Nie jest ``str``, więc pole tekstowe Logów go nie przyjmie: ``str()`` i f-string zgłaszają ``TypeError``, a ``repr``
    nie pokazuje adresu. Adres daje tylko ``shown()``, które woła jedynie zapis wyniku dla widoku Raporty (ADR 0028).
    Równość i skrót idą po adresie, bo adres jest kluczem ``WorkerAddresses``, a kolejność po adresie odróżnia w
    ``problem_order`` dwa problemy ``UnknownSender`` z jednym Message-ID.
    """

    __slots__ = ("_address",)

    def __init__(self, address: str) -> None:
        self._address = address

    @classmethod
    def of(cls, header: str) -> SenderAddress | None:
        """Adres z nagłówka ``From`` albo z linii pliku; ``None``, gdy nie ma w nim jednego adresu ``lokalna@domena``."""

        local, at, domain = parseaddr(header)[1].casefold().partition("@")
        if not (local and at and domain) or "@" in domain or any(character.isspace() for character in local + domain):
            return None
        return cls(f"{local}@{domain}")

    def shown(self) -> str:
        return self._address

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SenderAddress) and other._address == self._address

    def __hash__(self) -> int:
        return hash(self._address)

    def __lt__(self, other: SenderAddress) -> bool:
        return self._address < other._address

    def __repr__(self) -> str:
        return "SenderAddress(…)"

    def __str__(self) -> str:
        raise TypeError("Adres nadawcy nie jest tekstem: daje go tylko SenderAddress.shown() dla widoku Raporty.")

    def __format__(self, spec: str) -> str:
        raise TypeError("Adres nadawcy nie jest tekstem: daje go tylko SenderAddress.shown() dla widoku Raporty.")


@dataclass(frozen=True)
class ReportMail:
    """Mail ze Skrzynki raportów ze słowem ``SUBJECT_WORD`` w temacie: temat i treść jako tekst, ``arrived`` ze strefą
    taty. Od ``arrived`` zależy, który Wpis raportu jest poprawką wcześniejszego."""

    id: MailId
    sender: SenderAddress
    subject: str
    text: str
    arrived: datetime


@dataclass(frozen=True)
class WorkerAddresses:
    """Adres nadawcy → login Wykonawcy; buduje go tylko ``worker_addresses.load`` z pliku adresów Maksa."""

    logins: Mapping[SenderAddress, Login]


OrderNumber = NewType("OrderNumber", str)
"""``NUMER ZL.`` jako same cyfry: bez „#” i bez „.0”, które szybki czytnik INTERMAX daje liczbie."""


@dataclass(frozen=True, order=True)
class OrderKey:
    """Tożsamość zlecenia we Wpisaniu raportów: numer, dzień i Wykonawca. Nie przesuwa się, gdy tata wstawi wiersz, więc
    to klucz pamięci własnych wpisów i decyzji „Zostaw moją”."""

    number: OrderNumber
    day: date
    worker: Login


@dataclass(frozen=True)
class RegisterOrder:
    """Uporządkowane zlecenie INTERMAX z bieżącą wartością ``SKUTECZNE`` (``successful``) i ``CZYNNOŚCI ZREALIZOWANE``
    (``completed``); ``None`` to pusta komórka."""

    row: OrderRow
    key: OrderKey
    successful: str | None
    completed: str | None

    @classmethod
    def of(
        cls, row: OrderRow, *, number: object, started: object, worker: object, successful: object, completed: object
    ) -> RegisterOrder | None:
        """Zlecenie z wartości komórek, jak je daje czytnik INTERMAX: numer jako liczba albo tekst (z „#” albo bez),
        ``DATA GODZ. POCZ.`` jako data, Wykonawca po ``normalize_text``. ``None``, gdy wiersz nie ma numeru, dnia albo
        Wykonawcy."""

        order_number = _order_number(number)
        day = started.date() if isinstance(started, datetime) else started
        login = normalize_text(worker)
        if order_number is None or not isinstance(day, date) or not login:
            return None
        return cls(row, OrderKey(order_number, day, Login(login)), _cell(successful), _cell(completed))

    def cell(self, column: ReportColumn) -> str | None:
        match column:
            case ReportColumn.SUCCESSFUL:
                return self.successful
            case ReportColumn.COMPLETED:
                return self.completed


def _order_number(value: object) -> OrderNumber | None:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip().removeprefix("#")
    else:
        return None
    return OrderNumber(text) if text.isascii() and text.isdigit() else None


def _cell(value: object) -> str | None:
    text = "" if value is None else str(value)
    return text if text.strip() else None


@dataclass(frozen=True)
class Window:
    """Dni otwarte dla Wpisania raportów: od dnia wdrożenia (``rollout``) do dziś, bez dni okresów, których tokeny są w
    ``closed`` (okresy z Plikiem zbiorczym, ADR 0028)."""

    today: date
    rollout: date
    closed: frozenset[str]

    @classmethod
    def of(cls, today: date, rollout: date | None = None, closed: Iterable[str] = ()) -> Window:
        """Okno dzisiejszego dnia taty; przed pierwszym udanym kliknięciem (``rollout`` ``None``) wdrożenie jest dziś."""

        return cls(today, today if rollout is None else rollout, frozenset(closed))

    @property
    def first(self) -> date:
        """Pierwszy dzień okna: od niego proces czyta skrzynkę i zlecenia INTERMAX."""

        return self.rollout

    def opens(self, day: date) -> bool:
        return self.rollout <= day <= self.today and period_of(day).token not in self.closed


@dataclass(frozen=True)
class OwnEntry:
    """Wartość ``value``, którą Wpisanie raportów samo wpisało do komórki ``column`` zlecenia ``key``."""

    key: OrderKey
    column: ReportColumn
    value: str


@dataclass(frozen=True)
class OwnEntries:
    """Pamięć własnych wpisów: najwyżej jeden wpis na komórkę zlecenia."""

    entries: frozenset[OwnEntry]
    EMPTY: ClassVar[OwnEntries]

    def __post_init__(self) -> None:
        if len({(entry.key, entry.column) for entry in self.entries}) != len(self.entries):
            raise ValueError("Pamięć własnych wpisów ma dwa wpisy jednej komórki zlecenia.")


OwnEntries.EMPTY = OwnEntries(frozenset())


@dataclass(frozen=True)
class Kept:
    """Decyzja taty „Zostaw moją” dla komórki ``column`` zlecenia ``key`` przy treści Wpisu ``reported``: nowa treść od
    Wykonawcy pokazuje różnicę znowu. ``enter_reports`` jeszcze jej nie czyta, bo nie pokazuje różnic z ręczną
    wartością."""

    key: OrderKey
    column: ReportColumn
    reported: str


@dataclass(frozen=True)
class ReportInputs:
    """Wejście rdzenia: maile ze Skrzynki raportów, adresy Wykonawców, uporządkowane zlecenia INTERMAX z dni od
    ``window.first``, dni otwarte, pamięć własnych wpisów i decyzje „Zostaw moją”."""

    mails: Sequence[ReportMail]
    addresses: WorkerAddresses
    orders: Sequence[RegisterOrder]
    window: Window
    memory: OwnEntries
    kept: frozenset[Kept]


class Verdict(Enum):
    """``tak`` albo ``nie`` Wpisu raportu, tak jak trafia do ``SKUTECZNE``."""

    YES = "tak"
    NO = "nie"


class VerdictFault(Enum):
    """Dlaczego Wpis raportu nie ma ``tak`` ani ``nie``: brak słowa, sama litera albo inne słowo."""

    MISSING = auto()
    LETTER = auto()
    WORD = auto()


class SubjectFault(Enum):
    """Dlaczego temat ze słowem Raportu wykonawcy nie daje dnia zleceń: brak daty, brak roku albo data, która nie jest
    dniem."""

    NO_DATE = auto()
    NO_YEAR = auto()
    NOT_A_DAY = auto()


@dataclass(frozen=True)
class ReportEntry:
    """Wpis raportu: numer zlecenia, ``tak``/``nie`` albo powód jego braku (``fault``) i czynności."""

    number: OrderNumber
    verdict: Verdict | None
    fault: VerdictFault | None
    activities: str


@dataclass(frozen=True)
class ReadReport:
    """Raport wykonawcy od Wykonawcy ``worker`` z dniem zleceń ``day`` z tematu i jego Wpisami."""

    mail: MailId
    arrived: datetime
    worker: Login
    day: date
    entries: tuple[ReportEntry, ...]


@dataclass(frozen=True)
class ReadUnreadable:
    """Mail od Wykonawcy ze słowem Raportu wykonawcy w temacie, z którego tematu nie da się odczytać dnia."""

    mail: MailId
    arrived: datetime
    worker: Login
    fault: SubjectFault


@dataclass(frozen=True)
class ReadStranger:
    """Raport wykonawcy z adresu spoza adresów Wykonawców; adres ma tylko problem ``UnknownSender``."""

    mail: MailId
    arrived: datetime
    day: date


MailRead = ReadReport | ReadUnreadable | ReadStranger


@dataclass(frozen=True)
class UnreadableSubject:
    mail: MailId
    worker: Login
    arrived: datetime
    fault: SubjectFault


@dataclass(frozen=True)
class UnknownSender:
    mail: MailId
    sender: SenderAddress
    day: date


@dataclass(frozen=True)
class MissingVerdict:
    worker: Login
    day: date
    number: OrderNumber
    fault: VerdictFault


@dataclass(frozen=True)
class UnknownNumber:
    worker: Login
    day: date
    number: OrderNumber


@dataclass(frozen=True)
class ForeignOrder:
    worker: Login
    day: date
    number: OrderNumber
    owner: Login


@dataclass(frozen=True)
class OtherDay:
    worker: Login
    day: date
    number: OrderNumber
    order_days: tuple[date, ...]


@dataclass(frozen=True)
class RepeatedOrder:
    worker: Login
    day: date
    number: OrderNumber


@dataclass(frozen=True)
class ManualDifference:
    key: OrderKey
    column: ReportColumn
    manual: str
    reported: str


ReportProblem = (
    UnreadableSubject
    | UnknownSender
    | MissingVerdict
    | UnknownNumber
    | ForeignOrder
    | OtherDay
    | RepeatedOrder
    | ManualDifference
)
"""Problem, który tata widzi z powodem (``reasons.reason``): nierozpoznany temat, nieznany nadawca, brak ``tak``/``nie``,
nieznany numer, cudze zlecenie, inna data, ten sam numer dwa razy w dniu i różnica z ręczną wartością."""


@dataclass(frozen=True)
class WorkerDay:
    """Liczby Wykonawcy z dnia dla widoku Raporty: zlecenia, zlecenia z ``tak`` albo ``nie`` w ``SKUTECZNE`` po
    kliknięciu (``entered``), Raporty wykonawcy, problemy i numery zleceń bez żadnego Wpisu."""

    day: date
    worker: Login
    orders: int
    entered: int
    mails: int
    problems: int
    without_report: tuple[OrderNumber, ...]


@dataclass(frozen=True)
class ReportsOutcome:
    """Wynik rdzenia. ``changes`` po arkuszu, wierszu i kolumnie, każda komórka najwyżej raz; ``problems`` bez
    powtórzeń, w kolejności ``problem_order``; ``workers`` po dniu i Wykonawcy; ``mails`` po chwili przyjścia.
    ``memory`` proces zapisuje dopiero po udanym zapisie INTERMAX."""

    changes: tuple[CellChange, ...]
    problems: tuple[ReportProblem, ...]
    workers: tuple[WorkerDay, ...]
    mails: tuple[MailRead, ...]
    memory: OwnEntries


def problem_order(
    problem: ReportProblem,
) -> tuple[date, str, str, str, tuple[str | SenderAddress | datetime, ...]]:
    """Miejsce problemu w widoku Raporty: dzień, Wykonawca, numer, rodzaj i pozostałe pola problemu. Klucz bierze
    każde pole problemu, więc dwa różne problemy nigdy nie mają równego miejsca, a kolejność nie zależy od kolejności
    maili ani od ``PYTHONHASHSEED``."""

    kind = type(problem).__name__
    match problem:
        case UnreadableSubject(mail=mail, worker=worker, arrived=arrived, fault=fault):
            return arrived.date(), worker, "", kind, (mail.digest, fault.name, arrived)
        case UnknownSender(mail=mail, sender=sender, day=day):
            return day, "", "", kind, (mail.digest, sender)
        case MissingVerdict(fault=fault):
            return problem.day, problem.worker, problem.number, kind, (fault.name,)
        case ForeignOrder(owner=owner):
            return problem.day, problem.worker, problem.number, kind, (owner,)
        case OtherDay(order_days=order_days):
            return problem.day, problem.worker, problem.number, kind, tuple(map(date.isoformat, order_days))
        case UnknownNumber() | RepeatedOrder():
            return problem.day, problem.worker, problem.number, kind, ()
        case ManualDifference(key=key, column=column, manual=manual, reported=reported):
            return key.day, key.worker, key.number, kind, (column.value, manual, reported)
        case _:
            assert_never(problem)
