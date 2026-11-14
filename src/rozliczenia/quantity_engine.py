"""Silnik Reguł ilości (ADR 0033): Ilości usług i Ilości tylko dla INEA z treści zlecenia według Reguł ilości jako danych.

Jedyną operacją jest ``evaluate(rules, order)``, czysta funkcja bez plików i bez Centrum rozliczeń. Reguły ilości
(``QuantityRules``) to reguły „jeśli … to …” i Lista Urządzeń; ich niezmienniki sprawdza sam typ przy tworzeniu, więc
reguła z błędem nie powstaje (``QuantityRulesRefused`` z polem i zdaniem). Plik reguł ↔ typy: ``quantity_rules_file``.

Rachunek jednego zlecenia:

1. ``URZĄDZENIA`` dają słowa: małe litery, przecinki jak spacje, bez ``xg`` (także doklejonego), ``n *`` jako ``n*``.
   Składniki Listy Urządzeń są dopasowane od lewej najdłuższym zapisem; ``n*`` przed pierwszym słowem zapisu to
   krotność, a słowo bez dopasowania to składnik spoza listy.
2. Reguła działa, gdy jej zakres zgadza się z tym, czy lista zna każdy składnik, i wszystkie warunki są prawdziwe
   (warunek zaprzeczony odwrotnie). Warunek ``DATA`` przy zleceniu bez ``DATA`` nie działa ani zaprzeczony.
3. „Zostaw pustą w Rozliczeniu pracownika” działa zawsze, obok każdego innego działania.
4. Pierwszeństwo ma „nic nie wpisuj” (zlecenie z opisu), potem reguły „wpisz” z warunkiem „``URZĄDZENIA`` są
   dokładnie tekstem” (tylko one, bez P, Q i S). W pozostałych zleceniach pasujące reguły „wpisz” się sumują.
5. Gdy lista zna każdy składnik, dochodzą wbudowane P i Q (przy routerze pierwszy TV do P, następne do Q, bez routera
   wszystkie do Q) i S, liczba urządzeń z grup router, TV i extender.

Silnik nie zna dni świątecznych: reguła z ``DATA`` widzi tylko dzień tygodnia i godzinę (ADR 0033).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Final

from .collective_layout import QUANTITY_LETTERS
from .text import normalize_text

BUILT_IN_COLUMNS: Final = ("P", "Q", "S")
"""Kolumny wbudowanych rachunków (P i Q z urządzeń TV, S z liczby urządzeń): reguła taty w nie nie wpisuje, może je
tylko zostawić puste w Rozliczeniu pracownika."""
DESCRIPTION_COLUMNS: Final = ("Y", "AB", "AD", "AJ", "AK", "AL", "AM")
"""Kolumny Ilości usług z opisu technika (``CZYNNOŚCI ZREALIZOWANE``), poza słownikiem Reguł ilości (ADR 0033); reguła
może wpisać w AK i AM tylko część z nich."""
MAX_VALUE: Final = 999


class DeviceGroup(StrEnum):
    ROUTER = "router"
    TV = "tv"
    EXTENDER = "extender"


@dataclass(frozen=True)
class Component:
    """Składnik Listy Urządzeń: stały identyfikator, zapisy tej samej rzeczy i grupa."""

    id: str
    spellings: tuple[str, ...]
    """Zapisy w postaci słów ``URZĄDZENIA``: małe litery, pojedyncze spacje, bez ``xg``, gwiazdki i przecinków."""
    group: DeviceGroup | None = None


@dataclass(frozen=True)
class RulesProblem:
    """Pierwsza rzecz, przez którą Reguły ilości albo Lista Urządzeń nie mogą powstać: pole pliku i zdanie dla taty."""

    field: str
    message: str
    component: str | None = None
    """Składnik, do którego reguła się odwołuje, a którego Lista Urządzeń nie ma; ``None``: problem innego rodzaju."""


class QuantityRulesRefused(ValueError):
    def __init__(self, problem: RulesProblem) -> None:
        super().__init__(f"{problem.field}: {problem.message}")
        self.problem = problem


@dataclass(frozen=True)
class _Unknown:
    """Słowo ``URZĄDZENIA``, którego Lista Urządzeń nie zna, bez krotności ``n*``; ``counted``: miało krotność."""

    word: str
    counted: bool


@dataclass(frozen=True)
class DeviceList:
    """Lista Urządzeń: identyfikatory składników są różne, a jeden zapis należy do jednego składnika."""

    components: tuple[Component, ...]
    _by_spelling: Mapping[str, Component] = field(init=False, repr=False, compare=False)
    _longest: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_spelling: dict[str, Component] = {}
        ids: set[str] = set()
        for component in self.components:
            path = f"urzadzenia[{component.id}]"
            _require(_is_id(component.id), f"{path}.id", "Składnik potrzebuje nazwy bez spacji na początku i końcu.")
            _require(component.id not in ids, f"{path}.id", f"Składnik „{component.id}” jest na liście dwa razy.")
            ids.add(component.id)
            _require(bool(component.spellings), f"{path}.zapisy", "Składnik potrzebuje co najmniej jednego zapisu.")
            for spelling in component.spellings:
                _require(
                    bool(spelling) and "*" not in spelling and spelling == " ".join(_words(spelling)),
                    f"{path}.zapisy",
                    f"Zapis „{spelling}” wpisz małymi literami, z pojedynczymi spacjami, bez „xg”, gwiazdki i przecinków.",
                )
                owner = by_spelling.setdefault(spelling, component)
                _require(
                    owner is component,
                    f"{path}.zapisy",
                    f"Zapis „{spelling}” ma już składnik „{owner.id}”.",
                )
        object.__setattr__(self, "_by_spelling", MappingProxyType(by_spelling))
        object.__setattr__(self, "_longest", max((len(spelling.split()) for spelling in by_spelling), default=0))

    def ids(self) -> frozenset[str]:
        return frozenset(component.id for component in self.components)

    def find(self, words: list[str]) -> tuple[list[tuple[Component, int]], bool]:
        """Składniki słów ``URZĄDZENIA`` z krotnością, najdłuższy zapis od lewej, i czy lista zna każde słowo."""

        scanned = self._scan(words)
        return [item for item in scanned if not isinstance(item, _Unknown)], not any(isinstance(item, _Unknown) for item in scanned)

    def unknown_spellings(self, devices: str) -> tuple[str, ...]:
        """Zapisy w ``URZĄDZENIA`` ``devices``, których lista nie zna: kolejne nieznane słowa to jeden zapis, bez krotności
        ``n*``. Słowo z krotnością zaczyna nowy zapis, bo krotność stoi przed pierwszym słowem składnika, a słowo z
        gwiazdką, które nie jest krotnością, nie może być zapisem, więc dzieli zapisy i nim nie jest."""

        found: list[str] = []
        run: list[str] = []
        for item in [*self._scan(_words(devices)), None]:
            if run and not (isinstance(item, _Unknown) and "*" not in item.word and not item.counted):
                found.append(" ".join(run))
                run = []
            if isinstance(item, _Unknown) and "*" not in item.word:
                run.append(item.word)
        return tuple(found)

    def _scan(self, words: list[str]) -> list[tuple[Component, int] | _Unknown]:
        """Słowa ``URZĄDZENIA`` od lewej: składnik najdłuższego zapisu z krotnością albo słowo, którego lista nie zna."""

        scanned: list[tuple[Component, int] | _Unknown] = []
        position = 0
        while position < len(words):
            counted = _COUNTED.fullmatch(words[position])
            count, first = (int(counted[1]), counted[2]) if counted else (1, words[position])
            for length in range(min(self._longest, len(words) - position), 0, -1):
                component = self._by_spelling.get(" ".join([first, *words[position + 1 : position + length]]))
                if component is not None:
                    scanned.append((component, count))
                    position += length
                    break
            else:
                scanned.append(_Unknown(first, counted is not None))
                position += 1
        return scanned


class TextMode(StrEnum):
    EMPTY = "puste"
    EXACTLY = "dokladnie"
    CONTAINS = "zawieraja"
    """Fragment tekstu ``URZĄDZENIA`` po ``normalize_text``, nie składnik (Ilości tylko dla INEA)."""


@dataclass(frozen=True)
class ContainsComponent:
    """``URZĄDZENIA`` zawierają składnik, także obok składnika spoza listy."""

    component: str
    negated: bool = False


@dataclass(frozen=True)
class DevicesText:
    """``URZĄDZENIA`` są puste, są dokładnie tekstem (słowa po normalizacji) albo zawierają tekst."""

    mode: TextMode
    text: str = ""
    negated: bool = False


@dataclass(frozen=True)
class ActivitiesContain:
    """``CZYNNOŚCI`` zawierają tekst: fragment po małych literach i zwinięciu spacji."""

    text: str
    negated: bool = False


@dataclass(frozen=True)
class ContractFirstWord:
    """Pierwsze słowo ``UMOWA`` (małe litery) jest tym słowem: ``u`` nie pasuje do ``U/123`` ani ``usługa``."""

    word: str
    negated: bool = False


@dataclass(frozen=True)
class StartedAt:
    """``DATA`` przypada w jeden z dni tygodnia (0 to poniedziałek) od godziny do końca dnia."""

    days: frozenset[int]
    since: time
    negated: bool = False


@dataclass(frozen=True)
class HasGroup:
    """Zlecenie ma urządzenie z grupy."""

    group: DeviceGroup
    negated: bool = False


Condition = ContainsComponent | DevicesText | ActivitiesContain | ContractFirstWord | StartedAt | HasGroup


class Scope(StrEnum):
    """Dla których zleceń reguła działa: wszystkie składniki znane, jest składnik spoza listy, każde."""

    KNOWN = "znane"
    UNKNOWN = "nieznane"
    EVERY = "kazde"


class Multiplier(StrEnum):
    ONCE = "raz"
    """Wartość raz na zlecenie."""
    COMPONENT = "liczba"
    """Wartość razy liczba składnika (suma krotności ``n*``)."""
    PIECES = "sztuki"
    """Wartość razy „N szt” z ``CZYNNOŚCI`` (bez liczby 1) razy wystąpienia składnika; krotność ``n*`` się nie liczy."""


@dataclass(frozen=True)
class Write:
    column: str
    """Litera kolumny ``N:AP`` bez P, Q i S."""
    value: int
    multiplier: Multiplier = Multiplier.ONCE
    component: str | None = None
    """Składnik mnożnika ``liczba`` i ``sztuki``; przy ``raz`` brak."""


@dataclass(frozen=True)
class Fill:
    """Wpisz w kolumny."""

    writes: tuple[Write, ...]


@dataclass(frozen=True)
class WriteNothing:
    """Nic nie wpisuj w tym zleceniu: zlecenie rozliczane z opisu."""


@dataclass(frozen=True)
class LeaveEmpty:
    """Zostaw kolumny puste w Rozliczeniu pracownika (Ilości tylko dla INEA)."""

    columns: tuple[str, ...]


Action = Fill | WriteNothing | LeaveEmpty


@dataclass(frozen=True)
class QuantityRule:
    id: str
    conditions: tuple[Condition, ...]
    scope: Scope
    action: Action


@dataclass(frozen=True)
class QuantityRules:
    """Reguły ilości z Listą Urządzeń, do których się odwołują; kolejność reguł nie zmienia ilości."""

    rules: tuple[QuantityRule, ...]
    devices: DeviceList

    def __post_init__(self) -> None:
        _check_rules(self.rules, self.devices.ids())

    @property
    def rule_columns(self) -> tuple[str, ...]:
        """Kolumny, w które Reguły ilości wpisują: kolumny reguł „wpisz” i wbudowane P, Q i S, w kolejności ``N:AP``."""

        written = {write.column for rule in self.rules if isinstance(rule.action, Fill) for write in rule.action.writes}
        return tuple(column for column in QUANTITY_LETTERS if column in written or column in BUILT_IN_COLUMNS)

    @property
    def leave_empty_columns(self) -> tuple[str, ...]:
        """Kolumny reguł „zostaw pustą w Rozliczeniu pracownika” (Ilości tylko dla INEA), w kolejności reguł."""

        return tuple(
            dict.fromkeys(column for rule in self.rules if isinstance(rule.action, LeaveEmpty) for column in rule.action.columns)
        )

    @property
    def without_rule_columns(self) -> tuple[str, ...]:
        """Kolumny, w które reguły mogą wpisać przy składniku spoza listy, w kolejności reguł."""

        return tuple(
            dict.fromkeys(
                write.column
                for rule in self.rules
                if rule.scope is not Scope.KNOWN and isinstance(rule.action, Fill)
                for write in rule.action.writes
            )
        )


@dataclass(frozen=True, order=True)
class WeekTime:
    """Dzień tygodnia (0 to poniedziałek) i godzina z minutą z ``DATA``, bez daty dziennej."""

    weekday: int
    at: time


@dataclass(frozen=True)
class OrderContent:
    """Treść zlecenia, z której Reguły ilości wyznaczają ilości: tekst komórek i pora zlecenia."""

    contract: str
    """``UMOWA``; pusta komórka to ``""``."""
    devices: str
    """``URZĄDZENIA``, dokładny tekst."""
    activities: str
    """``CZYNNOŚCI`` (kolumna wejścia, nigdy ``CZYNNOŚCI ZREALIZOWANE``)."""
    started: WeekTime | None
    """``DATA``; ``None`` tylko w Wierszu danych Przebiegu bez daty, w którym liczą się Ilości tylko dla INEA."""

    @classmethod
    def of(cls, contract: object, devices: object, activities: object, started: datetime | None) -> OrderContent:
        """Treść zlecenia z wartości komórek Wiersza danych i daty z ``DATA``: komórka jako tekst, pusta to ``""``."""

        return cls(
            _cell_text(contract),
            _cell_text(devices),
            _cell_text(activities),
            None if started is None else WeekTime(started.weekday(), started.time().replace(second=0, microsecond=0)),
        )


@dataclass(frozen=True)
class Contribution:
    """Skąd jest część ilości w kolumnie: identyfikator reguły, ``"P/Q"`` albo ``"S"``."""

    source: str
    column: str
    value: int


Quantities = Mapping[str, int]
"""Kolumna ``N:AP`` → ilość, tylko różne od zera, w kolejności kolumn."""


@dataclass(frozen=True)
class ServiceQuantities:
    """Reguły ilości znają każdy składnik ``URZĄDZENIA`` albo zadziałała reguła „``URZĄDZENIA`` są dokładnie tekstem”."""

    quantities: Quantities
    leave_empty: frozenset[str]
    contributions: tuple[Contribution, ...]
    fired: tuple[str, ...]


@dataclass(frozen=True)
class WithoutRule:
    """``URZĄDZENIA`` mają składnik spoza Listy Urządzeń: tylko ilości reguł z zakresem „nieznane” i „każde”."""

    quantities: Quantities
    leave_empty: frozenset[str]
    contributions: tuple[Contribution, ...]
    fired: tuple[str, ...]


@dataclass(frozen=True)
class FromDescription:
    """Zadziałała reguła „nic nie wpisuj”: zlecenie rozliczane z opisu, bez żadnych ilości."""

    leave_empty: frozenset[str]
    fired: tuple[str, ...]
    quantities: Quantities = field(default_factory=lambda: MappingProxyType({}), init=False)
    contributions: tuple[Contribution, ...] = field(default=(), init=False)


RuleResult = ServiceQuantities | WithoutRule | FromDescription


def evaluate(rules: QuantityRules, order: OrderContent) -> RuleResult:
    """Wynik Reguł ilości dla zlecenia: rodzaj, ilości, kolumny do zostawienia pustymi i źródło każdej ilości."""

    facts = _Facts.of(rules.devices, order)
    matching = [rule for rule in rules.rules if _matches(rule, facts)]
    leave_empty = frozenset(column for rule in matching if isinstance(rule.action, LeaveEmpty) for column in rule.action.columns)
    if any(isinstance(rule.action, WriteNothing) for rule in matching):
        return FromDescription(leave_empty, _fired(matching, (WriteNothing, LeaveEmpty)))
    filling = [rule for rule in matching if isinstance(rule.action, Fill)]
    exact = [rule for rule in filling if any(_is_exact(condition) for condition in rule.conditions)]
    if exact:
        contributions = _contributions(exact, facts)
        return ServiceQuantities(_sum(contributions), leave_empty, contributions, _fired(matching, (LeaveEmpty,), exact))
    contributions = _contributions(filling, facts)
    fired = _fired(matching, (Fill, LeaveEmpty))
    if not facts.all_known:
        return WithoutRule(_sum(contributions), leave_empty, contributions, fired)
    contributions += _built_in(facts)
    return ServiceQuantities(_sum(contributions), leave_empty, contributions, fired)


def device_spelling(text: str) -> str:
    """Zapis składnika z tekstu taty tak, jak silnik czyta słowa ``URZĄDZENIA``; pusty, gdy tekst nie ma słów."""

    return _devices_words(text)


@dataclass(frozen=True)
class DevicesRead:
    """``URZĄDZENIA`` zlecenia tak, jak je czytają Reguły ilości: składniki Listy Urządzeń w kolejności z tekstu, bez
    powtórzeń, i czy lista zna każde słowo."""

    components: tuple[str, ...]
    all_known: bool


def devices_read(devices: DeviceList, order: OrderContent) -> DevicesRead:
    found, all_known = devices.find(_words(order.devices))
    return DevicesRead(tuple(dict.fromkeys(component.id for component, _ in found)), all_known)


_SEPARATORS = re.compile(r"[\s,]+")
_MULTIPLIER = re.compile(r"\s*\*\s*")
_COUNTED = re.compile(r"([1-9][0-9]*)\*(.+)")
_PIECES = re.compile(r"([1-9][0-9]*)\s*szt", re.IGNORECASE)


def _cell_text(value: object) -> str:
    return "" if value is None else str(value)


def _words(devices: str) -> list[str]:
    text = devices.casefold().replace("xg", "")
    return [word for word in _SEPARATORS.split(_MULTIPLIER.sub("*", text)) if word]


def _activities_phrase(text: str) -> str:
    """Tekst ``CZYNNOŚCI`` tak, jak go czyta warunek „``CZYNNOŚCI`` zawierają”: małe litery, pojedyncze spacje."""

    return " ".join(text.casefold().split())


def _devices_words(text: str) -> str:
    """Tekst ``URZĄDZENIA`` tak, jak go czytają zapisy składników i warunek „są dokładnie tekstem”."""

    return " ".join(_words(text))


@dataclass(frozen=True)
class _Facts:
    """Wszystko, co warunki i mnożniki czytają ze zlecenia, policzone raz."""

    words: tuple[str, ...]
    all_known: bool
    counts: Counter[str]
    """Składnik → suma krotności ``n*``."""
    occurrences: Counter[str]
    groups: Counter[DeviceGroup]
    """Grupa → suma krotności jej składników."""
    devices_words: str
    """Słowa ``URZĄDZENIA`` złączone spacją, jak zapisy składników."""
    devices_text: str
    """``URZĄDZENIA`` po ``normalize_text``."""
    activities: str
    pieces: int
    contract_word: str
    started: WeekTime | None

    @classmethod
    def of(cls, devices: DeviceList, order: OrderContent) -> _Facts:
        words = _words(order.devices)
        found, all_known = devices.find(words)
        counts: Counter[str] = Counter()
        occurrences: Counter[str] = Counter()
        groups: Counter[DeviceGroup] = Counter()
        for component, count in found:
            counts[component.id] += count
            occurrences[component.id] += 1
            if component.group is not None:
                groups[component.group] += count
        pieces = _PIECES.search(order.activities)
        contract = order.contract.casefold().split()
        return cls(
            tuple(words),
            all_known,
            counts,
            occurrences,
            groups,
            " ".join(words),
            normalize_text(order.devices),
            _activities_phrase(order.activities),
            int(pieces[1]) if pieces else 1,
            contract[0] if contract else "",
            order.started,
        )


def _matches(rule: QuantityRule, facts: _Facts) -> bool:
    if (rule.scope is Scope.KNOWN and not facts.all_known) or (rule.scope is Scope.UNKNOWN and facts.all_known):
        return False
    for condition in rule.conditions:
        holds = _holds(condition, facts)
        if holds is None or holds == condition.negated:
            return False
    return True


def _holds(condition: Condition, facts: _Facts) -> bool | None:
    """Czy warunek bez zaprzeczenia jest prawdziwy; ``None``, gdy zlecenie nie ma tego, o co pyta (``DATA``)."""

    match condition:
        case ContainsComponent(component=component):
            return facts.counts[component] > 0
        case DevicesText(mode=mode, text=text):
            return _devices_text_holds(mode, text, facts)
        case ActivitiesContain(text=text):
            return text in facts.activities
        case ContractFirstWord(word=word):
            return facts.contract_word == word
        case StartedAt(days=days, since=since):
            if facts.started is None:
                return None
            return facts.started.weekday in days and facts.started.at >= since
        case HasGroup(group=group):
            return facts.groups[group] > 0
    raise AssertionError(condition)


def _devices_text_holds(mode: TextMode, text: str, facts: _Facts) -> bool:
    match mode:
        case TextMode.EMPTY:
            return not facts.words
        case TextMode.EXACTLY:
            return facts.devices_words == text
        case TextMode.CONTAINS:
            return text in facts.devices_text


def _is_exact(condition: Condition) -> bool:
    return isinstance(condition, DevicesText) and condition.mode is TextMode.EXACTLY and not condition.negated


def _contributions(rules: Iterable[QuantityRule], facts: _Facts) -> tuple[Contribution, ...]:
    contributions: list[Contribution] = []
    for rule in rules:
        assert isinstance(rule.action, Fill)
        for write in rule.action.writes:
            amount = write.value * _times(write, facts)
            if amount:
                contributions.append(Contribution(rule.id, write.column, amount))
    return tuple(contributions)


def _times(write: Write, facts: _Facts) -> int:
    match write.multiplier:
        case Multiplier.ONCE:
            return 1
        case Multiplier.COMPONENT:
            return facts.counts[write.component or ""]
        case Multiplier.PIECES:
            return facts.pieces * facts.occurrences[write.component or ""]


def _built_in(facts: _Facts) -> tuple[Contribution, ...]:
    tv = facts.groups[DeviceGroup.TV]
    first_tv = 1 if tv and facts.groups[DeviceGroup.ROUTER] else 0
    devices = facts.groups[DeviceGroup.ROUTER] + tv + facts.groups[DeviceGroup.EXTENDER]
    built_in = (Contribution("P/Q", "P", first_tv), Contribution("P/Q", "Q", tv - first_tv), Contribution("S", "S", devices))
    return tuple(contribution for contribution in built_in if contribution.value)


def _sum(contributions: Iterable[Contribution]) -> Quantities:
    total: Counter[str] = Counter()
    for contribution in contributions:
        total[contribution.column] += contribution.value
    return MappingProxyType({column: total[column] for column in QUANTITY_LETTERS if total[column]})


def _fired(
    matching: Iterable[QuantityRule], kinds: tuple[type[Fill] | type[WriteNothing] | type[LeaveEmpty], ...], extra: Iterable[QuantityRule] = ()
) -> tuple[str, ...]:
    chosen = {rule.id for rule in extra}
    return tuple(rule.id for rule in matching if isinstance(rule.action, kinds) or rule.id in chosen)


def _is_id(text: str) -> bool:
    return bool(text) and text == text.strip()


def _is_number(value: object) -> bool:
    """Liczba całkowita, ale nie ``True`` ani ``False``, które Python liczy jako 1 i 0."""

    return isinstance(value, int) and not isinstance(value, bool)


def _require(holds: bool, path: str, message: str, *, component: str | None = None) -> None:
    if not holds:
        raise QuantityRulesRefused(RulesProblem(path, message, component))


def rule_list_problem(rules: Iterable[QuantityRule]) -> RulesProblem | None:
    """Pierwszy problem reguł bez Listy Urządzeń: każdy niezmiennik ``QuantityRules`` poza tym, czy składnik, do którego
    reguła się odwołuje, jest na liście; ``None``: reguły są dobre same w sobie."""

    try:
        _check_rules(tuple(rules), None)
    except QuantityRulesRefused as refused:
        return refused.problem
    return None


def without_components(rules: tuple[QuantityRule, ...], absent: frozenset[str]) -> tuple[QuantityRule, ...]:
    """Reguły ``rules`` tak, jakby żadne zlecenie nie miało składników ``absent``, bez odwołań do nich: reguła z warunkiem
    „zawierają” taki składnik nie działa nigdy, więc odpada, warunek „nie zawierają” go zachodzi zawsze, więc odpada sam,
    a wpis razy liczba albo sztuki takiego składnika jest zerem, więc odpada wpis. Reguła „wpisz”, której nie zostaje żaden
    wpis, odpada; jedyna różnica od reguły z takim składnikiem nigdy nieznalezionym jest wtedy, gdy jej warunki go nie
    wymagają: działałaby, wpisując zero (``fired``, a z warunkiem „dokładnie” brałaby zlecenie innym regułom)."""

    if not absent:
        return rules
    kept: list[QuantityRule] = []
    for rule in rules:
        conditions = tuple(
            condition for condition in rule.conditions if not (isinstance(condition, ContainsComponent) and condition.component in absent)
        )
        if any(isinstance(condition, ContainsComponent) and condition.component in absent and not condition.negated for condition in rule.conditions):
            continue
        action = rule.action
        if isinstance(action, Fill):
            writes = tuple(write for write in action.writes if write.component not in absent)
            if not writes:
                continue
            action = Fill(writes)
        kept.append(QuantityRule(rule.id, conditions, rule.scope, action))
    return tuple(kept)


def _check_rules(rules: tuple[QuantityRule, ...], components: frozenset[str] | None) -> None:
    """Niezmienniki reguł; ``components``: identyfikatory składników Listy Urządzeń, ``None``: bez sprawdzania odwołań."""

    ids: set[str] = set()
    for rule in rules:
        path = f"reguly[{rule.id}]"
        _require(_is_id(rule.id), f"{path}.id", "Reguła potrzebuje nazwy bez spacji na początku i końcu.")
        _require(rule.id not in ids, f"{path}.id", f"Reguła „{rule.id}” jest dwa razy.")
        ids.add(rule.id)
        for index, condition in enumerate(rule.conditions):
            _check_condition(condition, components, f"{path}.jesli[{index}]")
        _check_action(rule.action, components, f"{path}.to")


def _check_component(component: str | None, components: frozenset[str] | None, path: str) -> None:
    if components is None:
        _require(component is not None, path, "Wybierz składnik.")
    else:
        _require(component in components, path, f"Składnika „{component}” nie ma na Liście Urządzeń.", component=component)


def _check_condition(condition: Condition, components: frozenset[str] | None, path: str) -> None:
    match condition:
        case ContainsComponent(component=component):
            _check_component(component, components, f"{path}.skladnik")
        case DevicesText(mode=mode, text=text):
            _check_devices_text(mode, text, f"{path}.tekst")
        case ActivitiesContain(text=text):
            _require(bool(text) and text == _activities_phrase(text), f"{path}.tekst", "Tekst wpisz małymi literami, z pojedynczymi spacjami.")
        case ContractFirstWord(word=word):
            _require(word.casefold().split() == [word], f"{path}.slowo", "Wpisz jedno słowo małymi literami.")
        case StartedAt(days=days, since=since):
            _require(bool(days), f"{path}.dni", "Wybierz co najmniej jeden dzień tygodnia.")
            _require(
                all(_is_number(day) and 0 <= day <= 6 for day in days),
                f"{path}.dni",
                "Dzień tygodnia to liczba od 0 (poniedziałek) do 6 (niedziela).",
            )
            _require(since.second == 0 and since.microsecond == 0, f"{path}.od", "Godzinę wpisz z minutą, bez sekund.")
        case HasGroup():
            pass


def _check_devices_text(mode: TextMode, text: str, path: str) -> None:
    match mode:
        case TextMode.EMPTY:
            _require(not text, path, "Warunek „URZĄDZENIA są puste” nie ma tekstu.")
        case TextMode.EXACTLY:
            _require(
                bool(text) and text == _devices_words(text),
                path,
                "Tekst wpisz małymi literami, z pojedynczymi spacjami, bez „xg” i przecinków.",
            )
        case TextMode.CONTAINS:
            _require(bool(text) and text == normalize_text(text), path, "Tekst wpisz małymi literami, z pojedynczymi spacjami.")


def _check_action(action: Action, components: frozenset[str] | None, path: str) -> None:
    match action:
        case Fill(writes=writes):
            _require(bool(writes), f"{path}.wpisy", "Reguła „wpisz” potrzebuje co najmniej jednej kolumny.")
            for index, write in enumerate(writes):
                _check_write(write, components, f"{path}.wpisy[{index}]")
        case LeaveEmpty(columns=columns):
            _require(bool(columns), f"{path}.kolumny", "Wybierz co najmniej jedną kolumnę.")
            for column in columns:
                _require(column in QUANTITY_LETTERS, f"{path}.kolumny", f"Kolumna „{column}” nie jest kolumną Ilości usług N:AP.")
        case WriteNothing():
            pass


def _check_write(write: Write, components: frozenset[str] | None, path: str) -> None:
    _require(write.column in QUANTITY_LETTERS, f"{path}.kolumna", f"Kolumna „{write.column}” nie jest kolumną Ilości usług N:AP.")
    _require(
        write.column not in BUILT_IN_COLUMNS,
        f"{path}.kolumna",
        f"Kolumnę {write.column} liczy narzędzie samo: P i Q z urządzeń TV, S z liczby urządzeń.",
    )
    _require(
        _is_number(write.value) and 1 <= write.value <= MAX_VALUE,
        f"{path}.wartosc",
        f"Wartość musi być liczbą całkowitą od 1 do {MAX_VALUE}.",
    )
    if write.multiplier is Multiplier.ONCE:
        _require(write.component is None, f"{path}.skladnik", "Wartość „raz na zlecenie” nie liczy składnika.")
    else:
        _check_component(write.component, components, f"{path}.skladnik")
