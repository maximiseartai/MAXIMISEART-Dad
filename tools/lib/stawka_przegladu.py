from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from rejestr_korzeni import Major
from repo import REMOTE, ROOT
from stan_pr import Pull
from szablon_werdyktu import Mechanism
import szczebel_straznika
import wplyw_zmiany

ZASADY = """Stawka przeglądu PR (aneks „Lekka runda przeglądu PR samych narzędzi” ADR 0042, zmieniony przez
[ADR 0046](../../docs/adr/0046-szczebel-straznika-wybiera-recenzent.md)) ma jednego właściciela, ``stake``: mówi bramce
korzenia (warunek 4 ``tools/scal_pr.py``), których Ważnych blok w ``## Korzeń`` jest wymagany (``Stake.required``),
których może stać, choć go nie żąda (``Stake.spare``), i których kody idą na listę korzeni (``Stake.listed``), a warunek 5
dowodzi strażnika każdego bloku, który stoi w sekcji. Recenzent widzi stawkę w linii ``STAWKA`` z ``--przeglad``.

PR dostaje lekką rundę (``light``), gdy ``wplyw_zmiany.light_review`` od ``origin/<baza PR>`` tak mówi; inaczej stawka
jest pełna: każde Ważne ma blok, a każdy kod bloku i każdy kod ``NOWY`` z werdyktów stoi na liście. W lekkiej rundzie
blok potrzebuje tylko Ważne ze szczeblem z ``LIGHT`` (``lint``, decyzja Maksa z 20.11.2026: taki strażnik jest tani)
w wątku, w którym obowiązuje szczebel strażnika (``szczebel_straznika.applies``), a blok każdego innego Ważnego może
stać; kod żadnego Ważnego nie musi stać na liście, bo dopisanie go do listy zmienia plik spoza ``tools/`` i wyprowadza
PR z lekkiej rundy. Blok czerwonego `main` jest wymagany, a jego kod stoi na liście w obu stawkach.
"""

LIGHT = frozenset({Mechanism.LINT})


@dataclass(frozen=True)
class Stake:
    """Stawka PR: ``full`` (pełna albo lekka runda), Ważne ``required``, których blok bramka żąda, i Ważne ``spare``,
    których blok może stać w sekcji, choć bramka go nie żąda."""

    full: bool
    required: frozenset[str]
    spare: frozenset[str]

    def listed(self, heading: str) -> bool:
        """Czy kod bloku ``heading`` (``W<n> r<k>`` albo ``Czerwony main #N``) stoi na liście korzeni."""

        return self.full or not heading.startswith("W")


def light(pull: Pull) -> bool:
    return wplyw_zmiany.light_review(ROOT, f"refs/remotes/{REMOTE}/{pull.base}", pull.head)


def stake(pull: Pull, majors: Mapping[str, Major]) -> Stake:
    """Stawka ``pull`` z Ważnymi ``majors`` werdyktów ``FAIL`` (``rejestr_korzeni.majors``); baza i HEAD PR są już
    pobrane z ``origin``."""

    if not light(pull):
        return Stake(full=True, required=frozenset(majors), spare=frozenset())
    ruled = szczebel_straznika.applies(pull)
    required = frozenset(heading for heading, major in majors.items() if ruled and major.mechanism in LIGHT)
    return Stake(full=False, required=required, spare=frozenset(majors) - required)
