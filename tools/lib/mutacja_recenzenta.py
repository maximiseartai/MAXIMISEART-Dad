"""Blok mutacji recenzenta ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md), aneks „Test jako
strażnik z mutacją recenzenta”): zła postać, którą dowód strażnika ``pytest <węzeł>`` (``straznik.prove_test``) nanosi
na HEAD PR, a której autor nie pisze.

W werdykcie blok to nagłówek ``### Mutacja W<n> r<k>`` (``HEADING``: Ważne ``W<n>`` werdyktu ``FAIL`` rundy ``k``)
i pod nim jeden blok kodu ``` bez nazwy języka z JSON w postaci pliku ``tools/mutacje.py --plik``
(``silnik_mutacji.FILE_SHAPE``), z samymi kluczami ``nazwa`` i ``zmiany``, bo polecenie daje selektor strażnika, i bez
zmian w ``tests/``, bo zła postać to kod, który test ma złapać; GitHub
renderuje blok z nazwą języka jako ``<div>`` ze ściśniętymi spacjami, więc kotwica nie przeszłaby nietknięta. Postać
sprawdza szablon werdyktu (``szablon_werdyktu``) przy ``--werdykt`` i przy zgodzie na merge. Blok może stać w werdykcie
``FAIL``, który zgłosił Ważne, i w każdym późniejszym werdykcie PR, a obowiązuje najnowszy (``newest``), więc recenzent
następnej rundy odnawia blok, którego kotwicy nie ma na HEAD dokładnie raz, albo zastępuje blok, który nie przywraca
błędu z Ważnego.

Plik wyznacza też chwilę wdrożenia dowodu testu (``bramka_straznika.TEST_MARKER``): w wątku z pierwszym werdyktem
sprzed niej ``brak - test`` kończy po staremu. Moduł bierze tylko bibliotekę standardową, bo ``tools/scal_pr.py``
czyta szablon werdyktu Pythonem runnera.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re

from silnik_mutacji import Mutation, from_json

HEADING = re.compile(r"Mutacja (W\d+) r(\d+)")
TESTS = "tests"  # katalog testów: zmiana w nim nie jest złą postacią kodu, którą test ma złapać


@dataclass(frozen=True)
class Block:
    """Blok mutacji Ważnego ``label`` (``W1``) z rundy ``round`` (``k``-ty werdykt PR) z tekstem JSON ``text``."""

    label: str
    round: int
    text: str

    def __str__(self) -> str:
        return f"Mutacja {self.label} r{self.round}"


def mutations(block: Block, command: tuple[str, ...]) -> list[Mutation]:
    """Mutacje bloku z poleceniem ``command``, co najmniej jedna, żadna w ``tests/``; tekst innej postaci niż plik
    mutacji z samymi ``nazwa`` i ``zmiany`` to ``ValueError`` z przyczyną."""

    found = from_json(block.text, command, f"blok ### {block}")
    if not found:
        raise ValueError(f"blok ### {block}: lista bez wpisu, a dowód potrzebuje co najmniej jednej mutacji")
    if any(mutation.command != command or mutation.expected is not None for mutation in found):
        raise ValueError(f"blok ### {block}: wpis ma tylko klucze nazwa i zmiany, bo polecenie daje selektor strażnika pytest")
    if tested := sorted({edit.file.as_posix() for mutation in found for edit in mutation.edits if edit.file.parts[0] == TESTS}):
        raise ValueError(f"blok ### {block}: zmiana w {', '.join(tested)}: zła postać to kod, konfiguracja albo reguła, które test ma złapać, a nie test")
    return found


def newest(blocks: Iterable[Block], label: str, round_: int) -> Block | None:
    """Najnowszy blok Ważnego ``label`` rundy ``round_`` z ``blocks`` w kolejności werdyktów PR; ``None``, gdy go nie ma."""

    found = [block for block in blocks if (block.label, block.round) == (label, round_)]
    return found[-1] if found else None
