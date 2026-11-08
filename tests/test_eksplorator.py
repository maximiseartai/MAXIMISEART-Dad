"""Wspólny silnik eksploratorów przeplotów skilli (``tools/lib/eksplorator.py``): drzewo harmonogramów, wątki modelu,
wpisy wybaczeń i werdykt.

Pięć eksploratorów (``explore_runs``, ``explore_publication``, ``explore_outbox``, ``explore_intermax``,
``explore_wycena_efenix``) bierze z niego to, co każdy robił po swojemu, więc jego reguły sprawdzamy raz, na jego
interfejsie, na małych drzewach i wpisach testu.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

from eksplorator import Choices, Excuse, Interleaving, Thread, excuse_line, excused, gone_lines, schedules, verdict  # noqa: E402


def _leaves(execute: Callable[[Choices], tuple[int, ...]], budget: dict[str, int] | None = None) -> list[tuple[int, ...]]:
    """Harmonogramy drzewa testu, najwyżej 20: przejście, które się nie kończy, daje listę inną od oczekiwanej, a nie
    zawieszony test."""

    return list(islice(schedules(execute, budget), 20))


def test_przejscie_drzewa_odwiedza_kazdy_harmonogram_raz_w_glab() -> None:
    """Drzewo o szerokości zależnej od wcześniejszego wyboru: każdy liść raz, w kolejności w głąb, od pierwszych opcji."""

    def execute(choices: Choices) -> tuple[int, ...]:
        first = choices.choose(3)
        second = choices.choose(first + 1)
        return (first, second)

    assert _leaves(execute) == [(0, 0), (1, 0), (1, 1), (2, 0), (2, 1), (2, 2)]


def test_harmonogram_powtarza_prefiks_az_do_nowego_wyboru() -> None:
    """``replaying`` jest prawdą dokładnie dla wyborów z prefiksu: eksplorator nie ucina harmonogramu w stanie, który
    znał, dopóki nie doszedł do wyboru, którego jeszcze nie sprawdził."""

    def execute(choices: Choices) -> tuple[int, ...]:
        replayed = []
        for _ in range(3):
            replayed.append(int(choices.replaying))
            choices.choose(2)
        return tuple(replayed)

    # Prefiksy kolejnych harmonogramów drzewa 2×2×2: [], [0,0,1], [0,1], [0,1,1], [1], [1,0,1], [1,1], [1,1,1].
    assert _leaves(execute) == [(0, 0, 0), (1, 1, 1), (1, 1, 0), (1, 1, 1), (1, 0, 0), (1, 1, 1), (1, 1, 0), (1, 1, 1)]


def test_budzet_awarii_wyklucza_rodzaj_po_wyczerpaniu_i_zapisuje_awarie_z_krokiem() -> None:
    faults = []

    def execute(choices: Choices) -> tuple[int, ...]:
        picked = (choices.pick(("ok", "awaria"), "zapis"), choices.pick(("ok", "awaria"), "zamiana"))
        faults.append(tuple(choices.faults))
        return tuple(int(choice == "awaria") for choice in picked)

    assert _leaves(execute, {"awaria": 1}) == [(0, 0), (0, 1), (1, 0)]
    assert faults == [(), (("awaria", "zamiana"),), (("awaria", "zapis"),)]


@dataclass
class _Watek(Thread):
    log: tuple[str, ...] = ()


class _Przeplot(Interleaving[_Watek]):
    """``Interleaving`` z limitem przełączeń: ``settle``, które przełącza wątki bez końca, pada zamiast wisieć."""

    switches = 0

    def _switch(self, thread: _Watek) -> None:
        self.switches += 1
        assert self.switches < 100, f"settle przełącza wątek {thread.name} bez końca"
        super()._switch(thread)


def test_watki_modelu_biegna_po_jednym_do_kolejnego_kroku_z_wynikiem_wybranym_przez_eksplorator() -> None:
    interleaving = _Przeplot()

    def body(thread: _Watek) -> Callable[[], None]:
        def run() -> None:
            for _ in range(2):
                assert Interleaving.current() is thread
                thread.log += (interleaving.park(thread),)
            if thread.name == "a":
                interleaving.spawn(_Watek("c"), body_of_c)

        return run

    def body_of_c() -> None:
        return None

    first, second = _Watek("a"), _Watek("b")
    interleaving.spawn(first, body(first))
    interleaving.spawn(second, body(second))
    interleaving.settle()
    assert [thread.status for thread in interleaving.threads] == ["parked", "parked"]

    for thread, outcome in ((second, "b1"), (first, "a1"), (first, "a2"), (second, "b2")):
        interleaving.release(thread, outcome)
        interleaving.settle()

    assert (first.log, second.log) == (("a1", "a2"), ("b1", "b2"))
    assert [(thread.name, thread.status) for thread in interleaving.threads] == [("a", "done"), ("b", "done"), ("c", "done")]
    assert Interleaving.current() is None


def test_wynik_kroku_daje_tylko_release_eksploratora() -> None:
    """Wątek przełączony bez ``release`` nie dostaje wyniku poprzedniego kroku: taki błąd eksploratora pada od razu,
    zamiast powtórzyć krok, którego eksplorator nie wybrał."""

    interleaving = _Przeplot()
    thread = _Watek("a")

    def body() -> None:
        thread.log += (interleaving.park(thread), interleaving.park(thread))

    interleaving.spawn(thread, body)
    interleaving.settle()
    interleaving.release(thread, "pierwszy")
    interleaving.settle()

    with pytest.raises(AssertionError):
        thread.greenlet.switch()


@dataclass(frozen=True)
class _Ksztalt:
    krok: frozenset[str]

    def holds(self, observed: str) -> bool:
        return observed in self.krok


def _wpis(name: str, rule: str = "REGULA", *, after: tuple[str, ...] = ("zakres",), flaky: bool = False) -> Excuse[_Ksztalt]:
    return Excuse(name, rule, f"historia {name}", _Ksztalt(frozenset({"zapis"})), after=after, flaky=flaky)


def test_wpis_nazywa_jednostki_po_ktorych_wystepuje_albo_jest_flaky() -> None:
    _wpis("pewny")
    _wpis("wyscig", after=(), flaky=True)
    with pytest.raises(ValueError, match="nazywa jednostki"):
        _wpis("bez jednostek", after=())
    with pytest.raises(ValueError, match="nazywa jednostki"):
        _wpis("oba", flaky=True)


def test_naruszenie_wybacza_tylko_wpis_jego_reguly_w_jego_ksztalcie_a_przyjete_ryzyko_przed_znanym() -> None:
    known, risk = _wpis("znane"), _wpis("ryzyko")

    assert excused("REGULA", "zapis", known=(known,), accepted=(risk,)) == ("accepted", risk)
    assert excused("REGULA", "zapis", known=(known,)) == ("known", known)
    assert excused("INNA", "zapis", known=(known,), accepted=(risk,)) is None
    assert excused("REGULA", "odczyt", known=(known,), accepted=(risk,)) is None
    assert excused("REGULA", None, known=(known,), accepted=(risk,)) is None


@dataclass(frozen=True)
class _KazdaObserwacja:
    def holds(self, observed: object) -> bool:
        return True


def test_naruszenie_bez_obserwacji_jest_nowe_takze_dla_ksztaltu_ktory_przyjmuje_kazda_obserwacje() -> None:
    """Docstring ``excused``: naruszenie bez obserwacji (``None``) nie ma historii, którą wpis mógłby rozpoznać, więc
    żaden wpis go nie wybacza, nawet taki, którego kształt przyjąłby wszystko."""

    wszystko = Excuse("wszystko", "REGULA", "historia wszystko", _KazdaObserwacja(), after=("zakres",))

    assert excused("REGULA", "zapis", known=(wszystko,)) == ("known", wszystko)
    assert excused("REGULA", None, known=(wszystko,), accepted=(wszystko,)) is None


def test_linia_wpisu_ma_rodzaj_nazwe_regule_i_historie() -> None:
    assert excuse_line("known", _wpis("zabity proces")) == "ZNANE USTALENIE zabity proces (REGULA): historia zabity proces"
    assert excuse_line("accepted", _wpis("REGULA")) == "ZAAKCEPTOWANE RYZYKO REGULA: historia REGULA"


def test_wpis_znika_po_kazdej_jednostce_ktora_przeszla_bez_niego_a_flaky_nigdy() -> None:
    known = _wpis("znane", after=("a", "b", "c"))
    risk = _wpis("ryzyko", after=("a",))
    race = _wpis("wyscig", after=(), flaky=True)

    lines = gone_lines(("a", "b"), {("znane", "a")}, known=(known, race), accepted=(risk,))

    assert lines == [
        "ZNALEZISKO ZNIKNĘŁO znane (REGULA) po b: zawęź je w KNOWN_FINDINGS i w SKILL.md do jednostek, po których dalej "
        "występuje, albo je usuń",
        "ZNALEZISKO ZNIKNĘŁO ryzyko (REGULA) po a: zawęź je w ACCEPTED_RISKS i w SKILL.md do jednostek, po których "
        "dalej występuje, albo je usuń",
    ]
    assert gone_lines(("a", "b"), {("znane", "a"), ("znane", "b"), ("ryzyko", "a")}, known=(known,), accepted=(risk,)) == []


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({"gaps": 1, "new": 2, "gone": 3}, ("X: LUKA MODELU (1): powód.", 2)),
        ({"new": 2, "gone": 3, "known": 1}, ("X: NOWE NARUSZENIE (2)", 1)),
        ({"new": 0, "gone": 3, "known": 1}, ("X: ZNALEZISKO ZNIKNĘŁO (3)", 1)),
        ({"new": 0, "gone": 0, "known": 1, "accepted": 2}, ("X OK, ZNANE USTALENIA: 1, ZAAKCEPTOWANE RYZYKA: 2", 0)),
        ({"new": 0, "gone": 0, "accepted": 2}, ("X OK, ZAAKCEPTOWANE RYZYKA: 2", 0)),
        ({"new": 0, "gone": 0}, ("X OK", 0)),
    ],
)
def test_werdykt_luka_przed_nowym_naruszeniem_przed_zniknieciem_przed_ok(counts: dict[str, int], expected: tuple[str, int]) -> None:
    assert verdict("X", gap_reason=": powód.", **counts) == expected
