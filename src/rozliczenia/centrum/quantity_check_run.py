"""Kontrola ilości po Przebiegu rozliczeń z Centrum: kiedy powstaje i do którego issue okresu idzie (ADR 0013).

Działanie po wyniku Uruchomienia (``runs.AfterRun``). Kontrola powstaje tylko po Przebiegu rozliczeń z zapisem,
którego wynik karta pokazuje jako zakończony (OK albo wymagający sprawdzenia, decyzja 7); podgląd, Zatrzymanie i
nieoczekiwany wyjątek jej nie dają, a Skrypt dla maszyn nie ma działań po wyniku. Na wątku Uruchomienia tylko
przelicza i zapisuje wysyłkę w kolejce; sieć zostaje w wątku kolejki. Tytuł i treść przechodzą przez strażnika
reguły danych (ADR 0025): ``URZĄDZENIA``, ``CZYNNOŚCI`` i ``UMOWA`` to tekst taty, w którym może stać adres albo telefon.
"""

from __future__ import annotations

from typing import Final

from rozliczenia import client_data, quantity_check
from rozliczenia.centrum.outbox import Outbox, PeriodThread, Post
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.domain import SettlementSummary

LABEL: Final = "kontrola-ilosci"


class QuantityCheckAfterRun:
    def __init__(self, outbox: Outbox, commit: CommitSource) -> None:
        self._outbox = outbox
        self._commit = commit

    def run_ended(self, run: EndedRun) -> None:
        summary = None if run.shown is None else run.shown.engine_summary
        if run.info.dry_run or not isinstance(summary, SettlementSummary):
            return
        period, run_id = run.info.period, run.info.id
        result = quantity_check.check(summary.orders)
        title = client_data.guard(quantity_check.title(period, result), "tytuł Kontroli ilości")
        blocks = [
            client_data.guard(block, "treść Kontroli ilości")
            for block in quantity_check.blocks(result, commit=self._commit(), run_id=run_id)
        ]
        notes = dict.fromkeys(note for guarded in (title, *blocks) for note in guarded.notes)
        tail = [] if not notes else ["## Uwagi techniczne\n\n" + "".join(f"- {note}\n" for note in notes)]

        def frame(number: int, count: int, text: str) -> str:
            return text if count == 1 else f"Kontrola ilości, część {number}/{count} (Uruchomienie {run_id})\n\n{text}"

        self._outbox.post(
            Post.of(
                PeriodThread(
                    label=LABEL,
                    line=f"- Kontrola ilości okresu: {period}",
                    closed="new_issue",
                    title=title.text,
                ),
                period=period,
                run_id=run_id,
                blocks=[*(block.text for block in blocks), *tail],
                frame=frame,
            )
        )
