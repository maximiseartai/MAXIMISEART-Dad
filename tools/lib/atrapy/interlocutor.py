"""Rozmówca w testach rdzenia Uruchomienia procesu i silników, bez Centrum rozliczeń."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from rozliczenia.decision import Decision
from rozliczenia.progress import ProgressSnapshot


@dataclass
class Tata:
    """Rozmówca w teście: zapisuje każdą Decyzję, robi ``before_answer`` i odpowiada ``consent``."""

    consent: bool = True
    continue_hint: str = "przy decyzji wybierz „Kontynuuj”"
    before_answer: Callable[[], None] = lambda: None
    decisions: list[Decision] = field(default_factory=list)

    def confirm(self, decision: Decision) -> bool:
        self.decisions.append(decision)
        self.before_answer()
        return self.consent

    def show_progress(self, snapshot: ProgressSnapshot) -> None:
        pass
