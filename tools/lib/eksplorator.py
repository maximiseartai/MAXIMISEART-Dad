"""Wspólny silnik eksploratorów przeplotów skilli ``verify-*`` (``.agents/skills/*/scripts/explore_*.py``) i ich raport.

Eksplorator uruchamia prawdziwy kod raz na harmonogram: w każdym punkcie wyboru (który wątek robi krok, czy wywołanie
pada, czy proces ginie) bierze kolejną opcję z prefiksu, a za nim pierwszą. Ten moduł daje mu to, co każdy robił po
swojemu:

- ``Choices`` i ``schedules``: wybory po prefiksie i przejście całego drzewa harmonogramów, każdy liść raz, z budżetem
  awarii (``pick``), który zawęża opcje, gdy awaria danego rodzaju się wyczerpała.
- ``Interleaving``: wątki modelu jako greenlety na jednym wątku systemu; wątek parkuje przed krokiem (``park``), a
  eksplorator wybiera, który puścić (``release``), i dogania puszczone do ich kolejnego kroku (``settle``).
- ``Excuse``: jeden typ wpisu ``KNOWN_FINDINGS`` i ``ACCEPTED_RISKS``: nazwa, reguła, historia i kształt (dataklasa z
  ``holds``, której części pilnuje ``tests/fixtures/granice_ksztaltow.py``), a do tego jednostki sprawdzenia (zakresy,
  tryby albo przypadki), po których naruszenie zawsze występuje (``after``), albo ``flaky`` dla wyścigu, którego żadna
  jednostka nie gwarantuje.
- Raport: ``excused`` rozstrzyga naruszenie (przyjęte ryzyko przed znanym ustaleniem), ``excuse_line`` i ``gone_lines``
  to jedna postać linii wpisu i linii ``ZNALEZISKO ZNIKNĘŁO``, a ``verdict`` ostatnia linia z kodem wyjścia.

Wpis ``flaky`` nigdy nie zgłasza ``ZNALEZISKO ZNIKNĘŁO``, bo jego brak w przebiegu nie dowodzi poprawki: po poprawce
usuń go ręcznie.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Protocol, TypeVar

from greenlet import getcurrent, greenlet  # type: ignore[import-untyped]  # greenlet ships no type hints

__all__ = [
    "Choices",
    "Excuse",
    "Interleaving",
    "Kind",
    "Shape",
    "Thread",
    "excuse_line",
    "excused",
    "gone_lines",
    "schedules",
    "verdict",
]

T = TypeVar("T")
C = TypeVar("C", bound=str)


class Choices:
    """Wybory jednego harmonogramu: najpierw opcje z ``prefix``, potem zawsze pierwsza; zapisuje, co mógł wybrać.

    ``budget`` to rodzaj awarii → ile razy może się zdarzyć w harmonogramie; ``pick`` pomija rodzaj, którego budżet się
    wyczerpał, a wybrany zapisuje w ``faults`` z nazwą kroku.
    """

    def __init__(self, prefix: Sequence[int], budget: Mapping[str, int] | None = None) -> None:
        self._prefix = prefix
        self.taken: list[int] = []
        self.widths: list[int] = []
        self.left: dict[str, int] = dict(budget or {})
        self.faults: list[tuple[str, str]] = []

    @property
    def replaying(self) -> bool:
        """Czy harmonogram jeszcze powtarza prefiks: stan sprawdzony wcześniej nie ucina go wtedy."""

        return len(self.taken) < len(self._prefix)

    def choose(self, count: int) -> int:
        index = self._prefix[len(self.taken)] if self.replaying else 0
        self.taken.append(index)
        self.widths.append(count)
        return index

    def pick(self, offered: Sequence[C], step: str) -> C:
        allowed = [choice for choice in offered if self.left.get(choice, 1) > 0]
        chosen = allowed[self.choose(len(allowed))]
        if chosen in self.left:
            self.left[chosen] -= 1
            self.faults.append((chosen, step))
        return chosen

    def next_prefix(self) -> list[int] | None:
        """Prefiks następnego harmonogramu w głąb: ostatni wybór, który ma jeszcze dalszą opcję; ``None`` na końcu."""

        for depth in range(len(self.taken) - 1, -1, -1):
            if self.taken[depth] + 1 < self.widths[depth]:
                return [*self.taken[:depth], self.taken[depth] + 1]
        return None


def schedules(execute: Callable[[Choices], T], budget: Mapping[str, int] | None = None) -> Iterator[T]:
    """Wynik ``execute`` dla każdego harmonogramu drzewa, od pustego prefiksu; przerwanie pętli kończy przejście."""

    prefix: list[int] | None = []
    while prefix is not None:
        choices = Choices(prefix, budget)
        yield execute(choices)
        prefix = choices.next_prefix()


@dataclass
class Thread:
    """Wątek modelu: greenlet, który ``Interleaving`` puszcza od kroku do kroku. ``go`` to wynik kroku, który dostanie."""

    name: str
    status: Literal["new", "running", "parked", "done"] = "new"
    go: str | None = None
    history: list[str] = field(default_factory=list)
    greenlet: Any = None


W = TypeVar("W", bound=Thread)


class Interleaving(Generic[W]):
    """Wątki modelu na wątku eksploratora: jeden biegnie naraz, do swojego kolejnego kroku albo końca.

    Wątek systemu na każdy wątek modelu oddawał sterowanie przez jądro przy każdym kroku, a na runnerze CI zajętym innymi
    workerami xdist każdy krok czekał na wolny procesor, aż sprawdzenie doszło do limitu 120 s pytest (#565).
    Przełączenie greenletu nie czeka.
    """

    def __init__(self) -> None:
        self.home = getcurrent()  # eksplorator, który wybiera każdy krok
        self.threads: list[W] = []

    def spawn(self, thread: W, body: Callable[[], None]) -> W:
        """Dodaje wątek, który przy najbliższym ``settle`` biegnie do pierwszego kroku."""

        def main() -> None:
            try:
                body()
            finally:
                thread.status = "done"

        # Wątek założony przez inny wątek kończy się w eksploratorze, a nie w wątku, który go założył.
        thread.greenlet = greenlet(main, parent=self.home)
        thread.greenlet.thread = thread
        thread.status = "running"
        self.threads.append(thread)
        return thread

    @staticmethod
    def current() -> Thread | None:
        """Wątek modelu, w którym biegnie wywołujący; ``None`` poza wątkiem modelu."""

        thread: Thread | None = getattr(getcurrent(), "thread", None)
        return thread

    def park(self, thread: W) -> str:
        """Zatrzymuje ``thread`` przed krokiem, aż eksplorator go puści; zwraca wynik kroku z ``release``."""

        thread.status = "parked"
        self.home.switch()
        outcome, thread.go = thread.go, None
        assert outcome is not None  # release ustawił go przed przełączeniem tutaj
        return outcome

    def settle(self) -> None:
        """Puszcza każdy puszczony albo nowy wątek do jego kolejnego kroku albo końca."""

        while (thread := next((thread for thread in self.threads if thread.status == "running"), None)) is not None:
            self._switch(thread)

    def _switch(self, thread: W) -> None:
        thread.greenlet.switch()

    def release(self, thread: W, outcome: str) -> None:
        thread.status = "running"
        thread.go = outcome


# --- Wpisy i raport ---------------------------------------------------------------------------------------------------

Kind = Literal["known", "accepted"]
"""Rodzaj wybaczonego naruszenia: znane ustalenie (``KNOWN_FINDINGS``) albo przyjęte ryzyko (``ACCEPTED_RISKS``)."""


class Shape(Protocol):
    """Kształt wpisu: dataklasa, której każde pole to część historii wpisu (``tests/fixtures/granice_ksztaltow.py``)."""

    def holds(self, observed: Any, /) -> bool: ...


S = TypeVar("S", bound=Shape)


@dataclass(frozen=True)
class Excuse(Generic[S]):
    """Naruszenie reguły ``rule`` w kształcie ``shape``, które raport wymienia osobno od nowych; ``story`` mówi, czym
    jest (znane ustalenie: wada kodu dziś, przyjęte ryzyko: decyzja, która je przyjęła).

    ``after``: jednostki sprawdzenia (zakresy, tryby albo przypadki), po których naruszenie zawsze występuje: jednostka,
    która przeszła do końca bez niego, daje ``ZNALEZISKO ZNIKNĘŁO``. ``flaky``: wyścig, którego żadna jednostka nie
    gwarantuje, więc jego brak nie jest znakiem poprawki."""

    name: str
    rule: str
    story: str
    shape: S
    after: tuple[str, ...] = ()
    flaky: bool = False

    def __post_init__(self) -> None:
        if self.flaky == bool(self.after):
            raise ValueError(f"wpis {self.name} nazywa jednostki, po których występuje, albo jest flaky")

    def matches(self, rule: str, observed: object) -> bool:
        return rule == self.rule and observed is not None and self.shape.holds(observed)


def excused(
    rule: str, observed: object, *, known: Iterable[Excuse[Any]] = (), accepted: Iterable[Excuse[Any]] = ()
) -> tuple[Kind, Excuse[Any]] | None:
    """Wpis, który wybacza naruszenie ``rule`` z obserwacją ``observed``, z jego rodzajem; przyjęte ryzyko przed znanym
    ustaleniem. ``None``: naruszenie jest nowe, także każde bez obserwacji (``None``)."""

    if (risk := next((entry for entry in accepted if entry.matches(rule, observed)), None)) is not None:
        return "accepted", risk
    if (finding := next((entry for entry in known if entry.matches(rule, observed)), None)) is not None:
        return "known", finding
    return None


_LABELS: Mapping[Kind, str] = {"known": "ZNANE USTALENIE", "accepted": "ZAAKCEPTOWANE RYZYKO"}
_TABLES: Mapping[Kind, str] = {"known": "KNOWN_FINDINGS", "accepted": "ACCEPTED_RISKS"}
GONE = "ZNALEZISKO ZNIKNĘŁO"


def _named(entry: Excuse[Any]) -> str:
    return entry.name if entry.name == entry.rule else f"{entry.name} ({entry.rule})"


def excuse_line(kind: Kind, entry: Excuse[Any]) -> str:
    """Linia raportu o naruszeniu, które wpis wybacza."""

    return f"{_LABELS[kind]} {_named(entry)}: {entry.story}"


def gone_lines(
    ran: Collection[str],
    shown: Collection[tuple[str, str]],
    *,
    known: Iterable[Excuse[Any]] = (),
    accepted: Iterable[Excuse[Any]] = (),
) -> list[str]:
    """Linia ``ZNALEZISKO ZNIKNĘŁO`` każdego wpisu z jednostkami z jego ``after``, które przeszły do końca (``ran``), a
    nie pokazały go (``shown``: pary nazwa wpisu i jednostka), każda osobno, więc poprawka po jednej jednostce wychodzi,
    choć po innych wpis dalej występuje. Wpis ``flaky`` nie znika nigdy."""

    return [
        *(_gone_line("known", entry, units) for entry, units in _gone(known, ran, shown)),
        *(_gone_line("accepted", entry, units) for entry, units in _gone(accepted, ran, shown)),
    ]


def _gone(
    entries: Iterable[Excuse[Any]], ran: Collection[str], shown: Collection[tuple[str, str]]
) -> Iterator[tuple[Excuse[Any], list[str]]]:
    for entry in entries:
        if missing := [unit for unit in entry.after if unit in ran and (entry.name, unit) not in shown]:
            yield entry, missing


def _gone_line(kind: Kind, entry: Excuse[Any], units: Sequence[str]) -> str:
    return (
        f"{GONE} {_named(entry)} po {', '.join(units)}: zawęź je w {_TABLES[kind]} i w SKILL.md do jednostek, po których "
        "dalej występuje, albo je usuń"
    )


def verdict(
    name: str, *, new: int, gone: int, known: int = 0, accepted: int = 0, gaps: int = 0, gap_reason: str = ""
) -> tuple[str, int]:
    """Ostatnia linia raportu i kod wyjścia: luka modelu (2) przed nowym naruszeniem (1) przed zniknięciem wpisu (1)
    przed OK z liczbą wybaczonych (0)."""

    if gaps:
        return f"{name}: LUKA MODELU ({gaps}){gap_reason}", 2
    if new:
        return f"{name}: NOWE NARUSZENIE ({new})", 1
    if gone:
        return f"{name}: {GONE} ({gone})", 1
    counts = [f"ZNANE USTALENIA: {known}" if known else "", f"ZAAKCEPTOWANE RYZYKA: {accepted}" if accepted else ""]
    return ", ".join([f"{name} OK", *filter(None, counts)]), 0
