"""Typy rdzenia raportów, które pakiet ``worker_reports`` re-eksportuje, a jego moduły ``_*.py`` biorą stąd.

Osobny moduł, żeby pakiet importował moduły prywatne na górze bez cyklu: te biorą typy stąd, nie z pakietu.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parseaddr
from enum import Enum, auto
import hashlib
from typing import ClassVar, Final, NewType, assert_never

from ..report_cells import CellChange, OrderRow, ReportColumn
from ..settlement_period import SettlementPeriod, period_of
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

    @staticmethod
    def periods(today: date, rollout: date | None = None) -> tuple[SettlementPeriod, ...]:
        """Okresy dni okna po kolei, od okresu dnia wdrożenia do okresu dziś: w nich proces sprawdza Plik zbiorczy, a
        tokeny okresów z nim podaje jako ``closed``."""

        last = period_of(today).tuesday
        tuesday = period_of(min(today if rollout is None else rollout, today)).tuesday
        found = []
        while tuesday <= last:
            found.append(SettlementPeriod(tuesday))
            tuesday += timedelta(days=7)
        return tuple(found)

    @property
    def first(self) -> date:
        """Pierwszy dzień otwarty okna (dziś, gdy żaden nie jest otwarty): od niego proces czyta skrzynkę i zlecenia
        INTERMAX."""

        for period in self.periods(self.today, self.rollout):
            if period.token not in self.closed:
                return max(period.tuesday, self.rollout)
        return self.today

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
    """Decyzja taty „Zostaw moją” dla komórki ``column`` zlecenia ``key`` przy treści Wpisu ``reported``: różnica z tą
    treścią nie wraca, a nowa treść od Wykonawcy pokazuje różnicę znowu."""

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
    """Dlaczego Wpis raportu nie ma ``tak`` ani ``nie``: brak słowa (``MISSING``), sama litera ``t`` albo ``n``
    (``LETTER_YES``, ``LETTER_NO``) albo ``skuteczne``/``nieskuteczne`` (``WORD_YES``, ``WORD_NO``). Litera i słowo
    niosą zamiar Wykonawcy (``leaning``), choć Centrum ich nie wpisuje (Decyzja Maksa D13)."""

    MISSING = auto()
    LETTER_YES = auto()
    LETTER_NO = auto()
    WORD_YES = auto()
    WORD_NO = auto()

    @property
    def leaning(self) -> Verdict | None:
        """``tak`` albo ``nie``, które znak ma na myśli; ``None`` bez znaku."""

        match self:
            case VerdictFault.MISSING:
                return None
            case VerdictFault.LETTER_YES | VerdictFault.WORD_YES:
                return Verdict.YES
            case VerdictFault.LETTER_NO | VerdictFault.WORD_NO:
                return Verdict.NO

    @property
    def mark(self) -> str:
        """Znak, z którego rdzeń czyta ten powód, małymi literami; bez znaku pusty."""

        match self:
            case VerdictFault.MISSING:
                return ""
            case VerdictFault.LETTER_YES:
                return "t"
            case VerdictFault.LETTER_NO:
                return "n"
            case VerdictFault.WORD_YES:
                return "skuteczne"
            case VerdictFault.WORD_NO:
                return "nieskuteczne"


class SubjectFault(Enum):
    """Dlaczego temat ze słowem Raportu wykonawcy nie daje dnia zleceń, w kolejności, w jakiej rdzeń to sprawdza: brak
    liczb, inny tekst poza słowem i datą, dwie liczby, liczby nie w postaci dzień.miesiąc.rok, separator inny niż ``.``,
    ``_`` albo ``/``, rok bez dwóch ani czterech cyfr i data, która nie jest dniem."""

    NO_DATE = auto()
    OTHER_TEXT = auto()
    NO_YEAR = auto()
    DATE_FORM = auto()
    SEPARATOR = auto()
    YEAR_DIGITS = auto()
    NOT_A_DAY = auto()


@dataclass(frozen=True)
class ReportEntry:
    """Wpis raportu: numer zlecenia, ``tak``/``nie`` albo powód jego braku (``fault``) i czynności."""

    number: OrderNumber
    verdict: Verdict | None
    fault: VerdictFault | None
    activities: str

    @property
    def leaning(self) -> Verdict | None:
        """``tak`` albo ``nie`` Wpisu albo to, które ma na myśli jego litera lub słowo; ``None`` bez znaku."""

        return self.fault.leaning if self.verdict is None and self.fault is not None else self.verdict

    @property
    def mark(self) -> str:
        """Znak Wpisu małymi literami (``tak``, ``t``, ``nieskuteczne``), z którego rdzeń czyta go z powrotem; bez znaku
        pusty."""

        if self.verdict is not None:
            return self.verdict.value
        return "" if self.fault is None else self.fault.mark


@dataclass(frozen=True)
class ReadReport:
    """Raport wykonawcy od Wykonawcy ``worker`` z dniem zleceń ``day`` z tematu i jego Wpisami: jeden Wpis na numer, a
    przy numerze z Wpisami o przeciwnym zamiarze (``ReportEntry.leaning``) pierwszy Wpis każdego zamiaru, w kolejności
    maila (``_entries.entries``)."""

    mail: MailId
    arrived: datetime
    worker: Login
    day: date
    entries: tuple[ReportEntry, ...]


@dataclass(frozen=True)
class ReadUnreadable:
    """Mail od Wykonawcy ze słowem Raportu wykonawcy w temacie, z którego tematu nie da się odczytać dnia. ``numbers``:
    numery Wpisów jego treści, po których poprawiony mail zdejmuje ostrzeżenie (``_corrections.standing``)."""

    mail: MailId
    arrived: datetime
    worker: Login
    fault: SubjectFault
    numbers: frozenset[OrderNumber]


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
class ConflictingVerdicts:
    """Raport wykonawcy ``mail``, który przyszedł ``arrived``, ma dla numeru zlecenia Wpisy o przeciwnym zamiarze:
    ``tak``/``t``/``skuteczne`` i ``nie``/``n``/``nieskuteczne`` (``entries``: pierwszy Wpis każdego zamiaru, w
    kolejności maila)."""

    worker: Login
    day: date
    number: OrderNumber
    mail: MailId
    arrived: datetime
    entries: tuple[ReportEntry, ...]


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
    | ConflictingVerdicts
    | UnknownNumber
    | ForeignOrder
    | OtherDay
    | RepeatedOrder
    | ManualDifference
)
"""Problem, który tata widzi z powodem (``reasons.reason``): nierozpoznany temat, nieznany nadawca, brak ``tak``/``nie``,
przeciwny zamiar Wpisów jednego zlecenia w jednym mailu, nieznany numer, cudze zlecenie, inna data, ten sam numer dwa razy w dniu i różnica z ręczną wartością."""


class OrderState(Enum):
    """Stan zlecenia dnia Wykonawcy w widoku Raporty: problem, którego tata nie zostawił „Zostaw moją”, bez żadnego Wpisu
    (bez raportu, także gdy tata sam wpisał ``tak``) albo wpisane z Wpisu."""

    ENTERED = "entered"
    WITHOUT_REPORT = "without_report"
    PROBLEM = "problem"

    @classmethod
    def of(cls, *, reported: bool, problem: bool) -> OrderState:
        """Stan zlecenia z Wpisem (``reported``) albo bez niego, z problemem w widoku albo bez; problem ma tylko zlecenie
        z Wpisem, bo każdy problem przy numerze zlecenia z dnia Wykonawcy pochodzi z jego Wpisu."""

        if problem:
            return cls.PROBLEM
        return cls.ENTERED if reported else cls.WITHOUT_REPORT


@dataclass(frozen=True)
class OrderDetail:
    """Zlecenie dnia Wykonawcy w widoku Raporty: numer, ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` po zapisie zmian
    kliknięcia, kto by ich nie wpisał (``None``: pusta komórka), i czy zlecenie ma jakikolwiek Wpis (``reported``)."""

    number: OrderNumber
    successful: str | None
    activities: str | None
    reported: bool


@dataclass(frozen=True)
class WorkerDay:
    """Liczby Wykonawcy z dnia dla widoku Raporty: zlecenia, zlecenia z ``tak`` albo ``nie`` w ``SKUTECZNE`` po
    kliknięciu (``entered``), Raporty wykonawcy, problemy, numery zleceń bez żadnego Wpisu i zlecenia dnia w kolejności
    z INTERMAX (``orders_detail``)."""

    day: date
    worker: Login
    orders: int
    entered: int
    mails: int
    problems: int
    without_report: tuple[OrderNumber, ...]
    orders_detail: tuple[OrderDetail, ...]


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
    każde pole, którym mogą się różnić dwa problemy jednego wyniku, więc dwa różne problemy nigdy nie mają równego
    miejsca, a kolejność nie zależy od kolejności maili ani od ``PYTHONHASHSEED``. ``ConflictingVerdicts`` jest
    najwyżej jeden na zlecenie, bo daje go tylko jego zwycięski mail (``_matching.match``), więc wystarczy mu dzień,
    Wykonawca i numer."""

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
        case ConflictingVerdicts() | UnknownNumber() | RepeatedOrder():
            return problem.day, problem.worker, problem.number, kind, ()
        case ManualDifference(key=key, column=column, manual=manual, reported=reported):
            return key.day, key.worker, key.number, kind, (column.value, manual, reported)
        case _:
            assert_never(problem)
