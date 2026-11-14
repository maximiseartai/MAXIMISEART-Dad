"""Typy rdzenia raportów, które pakiet ``worker_reports`` re-eksportuje, a jego moduły ``_*.py`` biorą stąd.

Osobny moduł, żeby pakiet importował moduły prywatne na górze bez cyklu: te biorą typy stąd, nie z pakietu.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.utils import parseaddr
from enum import Enum
import hashlib
from types import MappingProxyType
from typing import ClassVar, Final, NewType, assert_never

from ..report_cells import CellChange, OrderAdded, OrderMove, OrderRow, ReportColumn
from ..settlement_period import SettlementPeriod, period_of
from ..text import normalize_text

SUBJECT_WORD: Final = "raport"
"""Słowo tematu Raportu wykonawcy bez względu na wielkość liter: port bierze ze skrzynki tylko maile z nim w temacie,
a rdzeń rozstrzyga resztę tematu."""

Login = NewType("Login", str)
"""Identyfikator Wykonawcy z ``WYKONAWCA`` po ``normalize_text``: login Wykonawcy z Listy Wykonawców."""

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
    """Adres nadawcy → login Wykonawcy i każdy login Wykonawcy → login, pod którym rdzeń zna Wykonawcę (``workers``,
    pierwszy login jego wpisu), więc zlecenie spod drugiego loginu jest zleceniem tego samego Wykonawcy. Buduje go tylko
    ``WorkerList.addresses`` z Listy Wykonawców."""

    logins: Mapping[SenderAddress, Login]
    workers: Mapping[Login, Login] = field(default_factory=lambda: MappingProxyType({}))

    def worker(self, login: Login) -> Login:
        """Login, pod którym rdzeń zna Wykonawcę z loginem ``login``; login spoza Listy Wykonawców zostaje sobą."""

        return self.workers.get(login, login)


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
    (``completed``); ``None`` to pusta komórka. ``worker_name``: ``WYKONAWCA`` tak, jak stoi w komórce, bez spacji na
    brzegach: tę pisownię dostaje zlecenie przeniesione albo dopisane do tego Wykonawcy. ``addressed``: komórka
    ``ADRES`` ma wartość; samego adresu rdzeń nie dostaje (ADR 0028)."""

    row: OrderRow
    key: OrderKey
    successful: str | None
    completed: str | None
    worker_name: str
    addressed: bool

    @classmethod
    def of(
        cls,
        row: OrderRow,
        *,
        number: object,
        started: object,
        worker: object,
        successful: object,
        completed: object,
        address: object,
    ) -> RegisterOrder | None:
        """Zlecenie z wartości komórek, jak je daje czytnik INTERMAX: numer jako liczba albo tekst (z „#” albo bez),
        ``DATA GODZ. POCZ.`` jako data, Wykonawca po ``normalize_text``, a z ``ADRES`` tylko to, czy ma wartość.
        ``None``, gdy wiersz nie ma numeru, dnia albo Wykonawcy."""

        found = order_number(number)
        day = started.date() if isinstance(started, datetime) else started
        login = normalize_text(worker)
        if found is None or not isinstance(day, date) or not login:
            return None
        return cls(
            row,
            OrderKey(found, day, Login(login)),
            _cell(successful),
            _cell(completed),
            str(worker).strip(),
            _cell(address) is not None,
        )

    def cell(self, column: ReportColumn) -> str | None:
        match column:
            case ReportColumn.SUCCESSFUL:
                return self.successful
            case ReportColumn.COMPLETED:
                return self.completed


def order_number(value: object) -> OrderNumber | None:
    """``NUMER ZL.`` z wartości komórki, jak ją daje czytnik INTERMAX (liczba albo tekst z „#” albo bez); ``None``, gdy
    to nie numer."""

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

    @property
    def start(self) -> date:
        """Pierwszy dzień, od którego proces czyta zlecenia INTERMAX: ``first`` i tydzień przed nim, nie przed dniem
        wdrożenia. Zlecenia dni zamkniętych z tego tygodnia i spomiędzy dni otwartych rdzeń zna tylko po to, żeby nie
        przenieść zlecenia z okresu z Plikiem zbiorczym (ADR 0029); starsze numery zna tylko z ``numbers_since``."""

        return max(self.rollout, self.numbers_since)

    @property
    def numbers_since(self) -> date:
        """Granica dni, od której proces czyta numer każdego wiersza INTERMAX (``ReportInputs.present``): ``first`` i
        tydzień przed nim, także sprzed dnia wdrożenia. W tygodniach po wdrożeniu ``start`` to dzień wdrożenia, a
        Wykonawca może przysłać numer zlecenia, które tata wkleił dzień albo kilka dni przed wdrożeniem: bez tego
        tygodnia Centrum dopisałoby je drugi raz (przegląd #1374 r3)."""

        return self.first - timedelta(days=7)

    def opens(self, day: date) -> bool:
        return self.rollout <= day <= self.today and period_of(day).token not in self.closed

    def closes(self, day: date) -> bool:
        """Dzień od dnia wdrożenia do dziś w okresie z Plikiem zbiorczym."""

        return self.rollout <= day <= self.today and period_of(day).token in self.closed


@dataclass(frozen=True)
class OwnEntry:
    """Wartość ``value``, którą Wpisanie raportów samo wpisało do komórki ``column`` zlecenia ``key``."""

    key: OrderKey
    column: ReportColumn
    value: str


@dataclass(frozen=True)
class OwnMove:
    """Pamięć zlecenia ``number``, na które Wpisanie raportów już zadziałało (ADR 0029 „Ręczna zmiana dalej wygrywa”,
    tabela przejść w opisie #1358, z miejscem = Wykonawca i dzień).

    ``day`` i ``worker``: gdzie Centrum zostawiło zlecenie, czyli przeniosło je tam albo przyjęło tam Wpis, gdy pamięć
    numeru była pusta; ręczna zmiana taty go nie przesuwa. ``origin_day``, ``origin_worker`` i ``origin_name`` (pisownia
    ``WYKONAWCA``): gdzie zlecenie stało przed pierwszym Przeniesieniem Centrum; bez Przeniesienia to samo miejsce co
    ``day`` i ``worker``. ``since``: chwila przyjścia najświeższego maila, na który Centrum zadziałało (przyjęło jego
    Wpis, przeniosło nim zlecenie albo je nim dopisało), gdziekolwiek zlecenie wtedy stało; nigdy nie maleje.
    ``overridden``: tata zmienił Wykonawcę albo dzień po Przeniesieniu Centrum, co zostaje, dopóki dzień ``day`` jest
    otwarty. ``added``: Centrum dopisało to zlecenie z raportu (Zlecenie dopisane z raportu), a miejsce dopisania jest
    jego miejscem sprzed Przeniesień. Pamięć dotyczy każdego zlecenia numeru (``memories_of``).

    Tata widzi informację o Przeniesieniu, dopóki INTERMAX ma zlecenie tam, gdzie je zostawiło Centrum, a to miejsce
    różni się od miejsca sprzed pierwszego Przeniesienia."""

    number: OrderNumber
    day: date
    worker: Login
    origin_day: date
    origin_worker: Login
    origin_name: str
    since: datetime
    overridden: bool = False
    added: bool = False

    def overridden_at(self, worker: Login, day: date) -> bool:
        """Czy tata zmienił miejsce zlecenia po Przeniesieniu Centrum, gdy INTERMAX ma je u ``worker`` w dniu ``day``:
        wcześniej (``overridden``) albo teraz (``left``)."""

        return self.overridden or self.left(((worker, day),))

    def left(self, places: Iterable[tuple[Login, date]]) -> bool:
        """Czy Przeniesienie stoi w pamięci (miejsce Centrum inne niż sprzed pierwszego Przeniesienia), a żadne z
        zleceń tego numeru, które INTERMAX ma w miejscach ``places`` (Wykonawca i dzień), nie stoi tam, gdzie je
        zostawiło Centrum: którekolwiek z nich to było, tata je stamtąd zabrał."""

        placed = (self.worker, self.day)
        return placed != (self.origin_worker, self.origin_day) and placed not in set(places)


def may_move(memory: Iterable[OwnMove], worker: Login, day: date, arrived: datetime) -> bool:
    """Reguła „Ręczna zmiana dalej wygrywa” (ADR 0029) w jednym miejscu: czy Wpis innego Wykonawcy z maila z chwilą
    ``arrived`` może przenieść zlecenie, które INTERMAX ma teraz u ``worker`` w dniu ``day``, przy pamięci jego numeru
    ``memory`` (``memories_of``, tabela przejść w opisie #1358).

    Bez pamięci (Centrum jeszcze nic z tym zleceniem nie zrobiło, także ręczny ``WYKONAWCA`` sprzed raportu, US 16)
    przenosi każdy mail. Z pamięcią tylko mail świeższy niż ``since`` każdej z nich (ściśle: mail, na który Centrum już
    zadziałało, i każdy starszy nigdy, gdziekolwiek zlecenie teraz stoi), i żaden po zmianie taty po Przeniesieniu
    Centrum (US 15, ``OwnMove.overridden_at``)."""

    return all(arrived > found.since and not found.overridden_at(worker, day) for found in memory)


def memories_of(moves: Iterable[OwnMove], number: OrderNumber) -> tuple[OwnMove, ...]:
    """Pamięć zleceń numeru ``number`` po dniach, czyli pamięć każdego jego zlecenia w INTERMAX.

    Excel nie mówi, który wiersz numeru tata przeniósł albo usunął, więc pamięć nie należy do jednego wiersza. Brak
    pamięci znaczy „każdy mail przenosi”, więc bezpieczny kierunek to pamięć dla każdego zlecenia numeru: Przeniesienie
    jedynego zlecenia czeka na ``may_move`` każdej. Wpisanie raportów zakłada pamięć numeru tylko wtedy, gdy numer nie ma
    żadnej, więc kilka pamięci jednego numeru ma tylko pamięć zapisana przed #1367 r4."""

    return tuple(sorted((move for move in moves if move.number == number), key=lambda move: move.day))


def single_orders(orders: Iterable[RegisterOrder]) -> dict[OrderNumber, OrderKey]:
    """Klucz zlecenia każdego numeru, który INTERMAX ma w odczytanych dniach raz. Tylko przy takim numerze wiadomo,
    który wiersz jest którym, więc tylko jego własne wpisy Centrum pamięta i niesie za wierszem (``_cells.reconcile``,
    ``_moves._carried``): tata może usunąć, scalić albo zamienić wiersze jednego numeru, a Excel tego nie mówi."""

    found: dict[OrderNumber, OrderKey | None] = {}
    for order in orders:
        found[order.key.number] = None if order.key.number in found else order.key
    return {number: key for number, key in found.items() if key is not None}


@dataclass(frozen=True)
class OwnEntries:
    """Pamięć własnych wpisów: najwyżej jeden wpis na komórkę zlecenia i najwyżej jedno Przeniesienie na numer i dzień
    (``moves``; pamięć sprzed Przeniesień ich nie ma). Wpisy ma tylko numer, który w chwili zapisu miał w odczytanych
    dniach jedno zlecenie (``_cells.reconcile``), więc następne kliknięcie wie, że to był jeden wiersz. Tę obietnicę daje
    plik stanu w wersji 4; pamięć ze starszego pliku to ``OlderOwnEntries``."""

    entries: frozenset[OwnEntry]
    moves: frozenset[OwnMove] = frozenset()
    EMPTY: ClassVar[OwnEntries]

    def __post_init__(self) -> None:
        if len({(entry.key, entry.column) for entry in self.entries}) != len(self.entries):
            raise ValueError("Pamięć własnych wpisów ma dwa wpisy jednej komórki zlecenia.")
        if len({(move.number, move.day) for move in self.moves}) != len(self.moves):
            raise ValueError("Pamięć własnych wpisów ma dwa Przeniesienia jednego zlecenia w jednym dniu.")


OwnEntries.EMPTY = OwnEntries(frozenset())


@dataclass(frozen=True)
class OlderOwnEntries:
    """Pamięć własnych wpisów z pliku stanu w wersji 1–3 (wersję 1 zapisują Wydania v0.7.0 i v0.8.0, wersję 3
    ``main`` przed #1367): jej pisarz zapisywał wpisy do zlecenia nadawcy także przy numerze w kilku zleceniach, więc
    wpis należy do miejsca z chwili zapisu (numer, dzień, Wykonawca), a nie do numeru, i nie spełnia obietnicy
    ``OwnEntries``. Rdzeń jej nie przyjmuje: proces zamienia ją na ``OwnEntries`` przez ``upgraded`` przy odczytanych
    zleceniach."""

    memory: OwnEntries

    def upgraded(self, orders: Iterable[RegisterOrder]) -> OwnEntries:
        """Pamięć dla rdzenia przy zleceniach ``orders``, które proces odczytał przed kliknięciem: wpis zostaje tylko
        przy jedynym zleceniu numeru w odczytanych dniach (``single_orders``), które ma dokładnie jego klucz. Wpis nie
        idzie za wierszem: gdy numer ma teraz kilka zleceń albo jego zlecenie ma inny dzień lub Wykonawcę, wpis
        przepada, a komórka liczy się jak wartość taty. Pamięć zleceń (``moves``) zostaje, bo ona tylko wstrzymuje
        Przeniesienie (``may_move``)."""

        single = single_orders(orders)
        entries = frozenset(entry for entry in self.memory.entries if single.get(entry.key.number) == entry.key)
        return OwnEntries(entries, self.memory.moves)


@dataclass(frozen=True)
class Kept:
    """Decyzja taty „Zostaw moją” dla komórki ``column`` zlecenia ``key`` przy treści Wpisu ``reported``: różnica z tą
    treścią nie wraca, a nowa treść od Wykonawcy pokazuje różnicę znowu."""

    key: OrderKey
    column: ReportColumn
    reported: str


@dataclass(frozen=True, order=True)
class OrderedDay:
    """Dzień uporządkowany ``day`` w arkuszu zleceń ``sheet`` (``raw_orders.ordered_days``, ta sama reguła co karta
    Uporządkowania INTERMAX): tylko do niego Przeniesienie zlecenia przenosi wiersz z tego arkusza (ADR 0029)."""

    sheet: str
    day: date


@dataclass(frozen=True)
class ReadNumber:
    """``NUMER ZL.`` ``number`` jednego wiersza INTERMAX, który proces przeczytał (``ReportInputs.present``), i dzień
    zlecenia z tego wiersza (``order_day``), gdy wiersz ma numer, dzień i ``WYKONAWCA`` (``RegisterOrder.of``); ``None``:
    wiersz bez ``WYKONAWCA`` albo bez daty, np. z datą tekstem. Pełny wiersz z dniem sprzed ``Window.start`` rdzeń zna
    tylko stąd, bo ``orders`` go nie mają."""

    number: OrderNumber
    order_day: date | None = None


@dataclass(frozen=True)
class ReportInputs:
    """Wejście rdzenia: maile ze Skrzynki raportów, adresy Wykonawców, uporządkowane zlecenia INTERMAX z dni od
    ``window.start``, także po dziś, dni otwarte, pamięć własnych wpisów, decyzje „Zostaw moją”, ``NUMER ZL.`` każdego
    wiersza INTERMAX, który proces przeczytał, raz na wiersz (``present``, ``ReadNumber``) i Dni uporządkowane każdego
    arkusza zleceń od ``window.start`` (``ordered_days``).

    ``present`` ma wiersz każdego zlecenia z ``orders`` i każdy wiersz, z którego nie powstało zlecenie: Surowe
    zlecenie, wiersz bez ``WYKONAWCA`` albo bez daty z godziną, wiersz z wyglądem z aplikacji między uporządkowanymi i
    nad nim oraz wiersz z dniem od ``Window.numbers_since`` sprzed ``window.start``. Tylko ``present`` mówi, czy
    INTERMAX ma numer, więc numeru z niego rdzeń nigdy nie dopisuje, i tylko ``present`` mówi, czy numer stoi w
    kilku wierszach, więc zlecenia takiego numeru rdzeń nie przenosi; ``orders`` mówią, które z tych wierszy są
    zleceniami, a okno, do których z nich wolno pisać. Pole nie ma wartości domyślnej, bo bez niego rdzeń
    dopisywałby każdy nowy numer i przenosił zlecenie numeru z kilku wierszy (przegląd #1374 r3)."""

    mails: Sequence[ReportMail]
    addresses: WorkerAddresses
    orders: Sequence[RegisterOrder]
    window: Window
    memory: OwnEntries
    kept: frozenset[Kept]
    present: Sequence[ReadNumber]
    ordered_days: frozenset[OrderedDay] = frozenset()


class Verdict(Enum):
    """``tak`` albo ``nie`` Wpisu raportu, tak jak trafia do ``SKUTECZNE``."""

    YES = "tak"
    NO = "nie"


class VerdictFault(Enum):
    """Dlaczego Wpis raportu nie ma ``tak`` ani ``nie``: brak słowa (``MISSING``), sama litera ``t`` albo ``n``
    (``LETTER_YES``, ``LETTER_NO``) albo ``skuteczne``/``nieskuteczne`` (``WORD_YES``, ``WORD_NO``). Litera i słowo
    niosą zamiar Wykonawcy (``leaning``), choć Centrum ich nie wpisuje (Decyzja Maksa D13). Wartość to słowo powodu w
    Logach Uruchomienia: czytają je stare Logi i odtworzenie, więc się nie zmienia."""

    MISSING = "missing"
    LETTER_YES = "letter_yes"
    LETTER_NO = "letter_no"
    WORD_YES = "word_yes"
    WORD_NO = "word_no"

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
    ``_`` albo ``/``, rok bez dwóch ani czterech cyfr i data, która nie jest dniem. Wartość to słowo powodu w Logach
    Uruchomienia: czytają je stare Logi i odtworzenie, więc się nie zmienia."""

    NO_DATE = "no_date"
    OTHER_TEXT = "other_text"
    NO_YEAR = "no_year"
    DATE_FORM = "date_form"
    SEPARATOR = "separator"
    YEAR_DIGITS = "year_digits"
    NOT_A_DAY = "not_a_day"


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


class AddBar(Enum):
    """Dlaczego numer z Wpisu raportu, którego INTERMAX nie ma w uporządkowanych zleceniach żadnego odczytanego dnia, nie
    stał się Zleceniem dopisanym z raportu (ADR 0029), w kolejności, w jakiej rdzeń to sprawdza: INTERMAX ma go w
    przeczytanym wierszu, z którego nie powstało zlecenie (``IN_INTERMAX``, ``ReportInputs.present``; dopisanie dałoby
    zlecenie dwa razy), a gdy każdy taki wiersz to zlecenie z dniem i ``WYKONAWCA`` z dnia sprzed ``Window.start``,
    którego Centrum nie zmienia (``BEFORE_WINDOW``), numer nie ma postaci numeru z aplikacji firmowej, czyli dokładnie
    ``ADDED_DIGITS`` cyfr (``FORM``), Raport wykonawcy ma pomylony temat (``MISTAKEN_SUBJECT``) albo dzień z tematu nie
    jest Dniem uporządkowanym w żadnym arkuszu zleceń (``NOT_ORDERED``). Wartość to słowo powodu w Logach Uruchomienia:
    czytają je stare Logi i odtworzenie, więc się nie zmienia."""

    IN_INTERMAX = "in_intermax"
    BEFORE_WINDOW = "before_window"
    FORM = "form"
    MISTAKEN_SUBJECT = "mistaken_subject"
    NOT_ORDERED = "not_ordered"


ADDED_DIGITS: Final = 8
"""Tyle cyfr ma numer z aplikacji firmowej (jak w INTERMAX): tylko taki numer staje się Zleceniem dopisanym z raportu."""


@dataclass(frozen=True)
class UnknownNumber:
    """Numeru z Wpisu Wykonawcy ``worker`` z dniem z tematu ``day`` nie ma w uporządkowanych zleceniach żadnego
    odczytanego dnia INTERMAX, a Centrum go nie dopisało z powodu ``bar``."""

    worker: Login
    day: date
    number: OrderNumber
    bar: AddBar


@dataclass(frozen=True)
class RepeatedOrder:
    worker: Login
    day: date
    number: OrderNumber


@dataclass(frozen=True)
class RepeatedNumber:
    """Wpis Wykonawcy ``worker`` z dniem z tematu ``day`` ma numer ``number``, który INTERMAX ma w przeczytanych
    wierszach (także z dni zamkniętych i po dziś) więcej niż raz (``places``: dzień i Wykonawca każdego zlecenia z tym
    numerem, po kolei; jedno miejsce, gdy pozostałe wiersze to wiersze bez zlecenia, ``ReportInputs.present``), a
    nadawca nie ma w dniu ``day`` żadnego z tych zleceń. Centrum nie wie, którego wiersza dotyczy Wpis, więc nie zmienia
    żadnego z nich."""

    worker: Login
    day: date
    number: OrderNumber
    places: tuple[tuple[date, Login], ...]


class MoveBar(Enum):
    """Dlaczego Wpis raportu nie przenosi zlecenia na inny dzień (ADR 0029): dzień docelowy nie jest Dniem
    uporządkowanym (``NOT_ORDERED``), jest Dniem uporządkowanym tylko w innym arkuszu zleceń (``OTHER_SHEET``), jest w
    okresie z Plikiem zbiorczym (``CLOSED_TARGET``), zlecenie jest w takim okresie (``CLOSED_SOURCE``) albo w dniu po
    dziś (``AFTER_TODAY``: tata wkleja zlecenia na jutro dzień wcześniej, ADR 0019, a Centrum nie zmienia dni po dziś).
    Wartość to słowo powodu w Logach Uruchomienia: czytają je stare Logi i odtworzenie, więc się nie zmienia."""

    NOT_ORDERED = "not_ordered"
    OTHER_SHEET = "other_sheet"
    CLOSED_TARGET = "closed_target"
    CLOSED_SOURCE = "closed_source"
    AFTER_TODAY = "after_today"


@dataclass(frozen=True)
class RefusedMove:
    """Wpis Wykonawcy ``worker`` z dniem z tematu ``day`` do jedynego zlecenia ``number``, które INTERMAX ma w dniu
    ``order_day``, przeniósłby je tam, skąd albo dokąd nie wolno (``bar``); INTERMAX zostaje bez zmiany. ``target``:
    dzień, na który Wpis przeniósłby zlecenie, gdy nie wolno pisać tam (``NOT_ORDERED``, ``OTHER_SHEET``,
    ``CLOSED_TARGET``): dzień z tematu, a przy pomylonym temacie dzień zlecenia sprzed Przeniesień Centrum. Odmowa z
    dnia zlecenia (``CLOSED_SOURCE``, ``AFTER_TODAY``) nie wybiera celu, więc ``target`` to ``order_day``, a dwa maile
    nadawcy z tym dniem i numerem, z pomylonym tematem i bez, dają jedną odmowę."""

    worker: Login
    day: date
    number: OrderNumber
    order_day: date
    target: date
    bar: MoveBar

    @property
    def shown(self) -> date:
        """Dzień, w którym tata widzi problem: dzień otwarty, czyli dzień z tematu, a gdy ten jest w okresie z Plikiem
        zbiorczym, dzień zlecenia."""

        return self.order_day if self.bar is MoveBar.CLOSED_TARGET else self.day


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
    | RepeatedOrder
    | RepeatedNumber
    | RefusedMove
    | ManualDifference
)
"""Problem, który tata widzi z powodem (``reasons.reason``): nierozpoznany temat, nieznany nadawca, brak ``tak``/``nie``,
przeciwny zamiar Wpisów jednego zlecenia w jednym mailu, nieznany numer, którego Centrum nie dopisało, ten sam numer
dwa razy w dniu u nadawcy, numer w kilku zleceniach INTERMAX bez jednego zlecenia nadawcy w dniu z tematu, Przeniesienie
skąd albo dokąd nie wolno (także jedyne zlecenie numeru w dniu po dziś) i różnica z ręczną wartością."""


@dataclass(frozen=True)
class TakenOver:
    """Informacja dla taty przy Wykonawcy ``worker`` z dnia ``day``: zlecenie ``number`` Centrum przeniosło do niego od
    ``previous`` („przejęte od”)."""

    day: date
    worker: Login
    number: OrderNumber
    previous: Login


@dataclass(frozen=True)
class HandedOver:
    """Informacja dla taty przy Wykonawcy ``worker`` z dnia ``day``: jego zlecenie ``number`` Centrum przeniosło do
    ``successor`` („przekazane”)."""

    day: date
    worker: Login
    number: OrderNumber
    successor: Login


@dataclass(frozen=True)
class MovedFrom:
    """Informacja dla taty przy Wykonawcy ``worker`` z dnia ``day``: zlecenie ``number`` Centrum przeniosło tu z dnia
    ``origin_day`` („przeniesione z”)."""

    day: date
    worker: Login
    number: OrderNumber
    origin_day: date


@dataclass(frozen=True)
class MovedTo:
    """Informacja dla taty przy Wykonawcy ``worker`` z dnia ``day``: jego zlecenie ``number`` Centrum przeniosło na
    dzień ``target_day`` („przeniesione na”)."""

    day: date
    worker: Login
    number: OrderNumber
    target_day: date


@dataclass(frozen=True)
class SubjectLost:
    """Informacja dla taty przy Wykonawcy ``worker`` z dnia ``day`` (dzień z tematu): jego Raport wykonawcy ma pomylony
    temat, więc Wpis zlecenia ``number`` Centrum wpisało do zlecenia z dnia ``order_day`` z INTERMAX (ADR 0029)."""

    day: date
    worker: Login
    number: OrderNumber
    order_day: date


@dataclass(frozen=True)
class Added:
    """Informacja dla taty przy Wykonawcy ``worker`` z dnia ``day``: zlecenie ``number`` Centrum dopisało z raportu, a
    INTERMAX nie ma jeszcze jego ``ADRES`` („dopisane z raportu, uzupełnij resztę”)."""

    day: date
    worker: Login
    number: OrderNumber


ReportNote = TakenOver | HandedOver | MovedFrom | MovedTo | SubjectLost | Added
"""Informacja dla taty o zmianie, którą Wpisanie raportów zrobiło w INTERMAX (ADR 0029): tylko numer, Wykonawca i dzień.
Nie jest problemem ani Zgłoszeniem; zdanie daje ``reasons.note``. Przeniesienie stoi, dopóki INTERMAX ma zlecenie tam,
gdzie postawiło je Centrum, przegrany temat, dopóki jego Wpis jest zwycięskim Wpisem zlecenia, a dopisane zlecenie,
dopóki nie ma ``ADRES``."""


def note_order(note: ReportNote) -> tuple[date, str, str, str, str]:
    """Miejsce informacji w widoku Raporty: dzień, Wykonawca, numer, rodzaj i drugi Wykonawca albo drugi dzień."""

    match note:
        case TakenOver(previous=other) | HandedOver(successor=other):
            return note.day, note.worker, note.number, type(note).__name__, other
        case MovedFrom(origin_day=other_day) | MovedTo(target_day=other_day) | SubjectLost(order_day=other_day):
            return note.day, note.worker, note.number, type(note).__name__, other_day.isoformat()
        case Added():
            return note.day, note.worker, note.number, type(note).__name__, ""
        case _:
            assert_never(note)


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
    """Wynik rdzenia. ``changes`` po arkuszu, wierszu i kolumnie, każda komórka najwyżej raz, w wierszach tak, jak je
    przeczytał proces; ``moves`` (Przeniesienia zleceń) po arkuszu i wierszu, każdy wiersz najwyżej raz, a zapis
    przenosi wiersz już z komórkami z ``changes``; ``added`` (Zlecenia dopisane z raportu) po arkuszu, dniu, Wykonawcy i
    numerze, każdy numer najwyżej raz, a zapis dopisuje je po Przeniesieniach; ``problems`` bez powtórzeń, w kolejności
    ``problem_order``; ``notes`` (informacje dla taty) w kolejności ``note_order``; ``workers`` po dniu i Wykonawcy, po
    Przeniesieniach i dopisaniach; ``mails`` po chwili przyjścia. ``memory`` proces zapisuje dopiero po udanym zapisie
    INTERMAX."""

    changes: tuple[CellChange, ...]
    problems: tuple[ReportProblem, ...]
    workers: tuple[WorkerDay, ...]
    mails: tuple[MailRead, ...]
    memory: OwnEntries
    moves: tuple[OrderMove, ...]
    notes: tuple[ReportNote, ...]
    added: tuple[OrderAdded, ...]


def problem_order(
    problem: ReportProblem,
) -> tuple[date, str, str, str, tuple[str | SenderAddress | datetime, ...]]:
    """Miejsce problemu w widoku Raporty: dzień, Wykonawca, numer, rodzaj i pozostałe pola problemu. Klucz bierze
    każde pole, którym mogą się różnić dwa problemy jednego wyniku, więc dwa różne problemy nigdy nie mają równego
    miejsca, a kolejność nie zależy od kolejności maili ani od ``PYTHONHASHSEED``. ``ConflictingVerdicts`` jest
    najwyżej jeden na zlecenie, bo daje go tylko jego zwycięski mail (``_matching.Board.match``), a miejsca zleceń
    ``RepeatedNumber`` zależą tylko od numeru i INTERMAX kliknięcia, więc obu wystarczy dzień, Wykonawca i numer."""

    kind = type(problem).__name__
    match problem:
        case UnreadableSubject(mail=mail, worker=worker, arrived=arrived, fault=fault):
            return arrived.date(), worker, "", kind, (mail.digest, fault.name, arrived)
        case UnknownSender(mail=mail, sender=sender, day=day):
            return day, "", "", kind, (mail.digest, sender)
        case MissingVerdict(fault=fault):
            return problem.day, problem.worker, problem.number, kind, (fault.name,)
        case UnknownNumber(bar=bar):
            return problem.day, problem.worker, problem.number, kind, (bar.name,)
        case ConflictingVerdicts() | RepeatedOrder() | RepeatedNumber():
            return problem.day, problem.worker, problem.number, kind, ()
        case RefusedMove(day=day, order_day=order_day, target=target, bar=bar):
            days = (day.isoformat(), order_day.isoformat(), target.isoformat())
            return problem.shown, problem.worker, problem.number, kind, (*days, bar.name)
        case ManualDifference(key=key, column=column, manual=manual, reported=reported):
            return key.day, key.worker, key.number, kind, (column.value, manual, reported)
        case _:
            assert_never(problem)
