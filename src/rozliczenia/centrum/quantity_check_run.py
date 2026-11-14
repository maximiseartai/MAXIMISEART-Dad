"""Kontrola ilości po Przebiegu rozliczeń z Centrum: kiedy powstaje i do którego issue okresu idzie (ADR 0013).

Działanie po wyniku Uruchomienia (``runs.AfterRun``). Kontrola powstaje tylko po procesie, którego wpis w katalogu ma
Kontrolę ilości (``ProcessKind.quantity_check``: Przebieg rozliczeń, Regułami ilości swojego Uruchomienia), z zapisem,
którego wynik karta pokazuje jako zakończony (OK albo wymagający sprawdzenia, decyzja 7); podgląd, Zatrzymanie i
nieoczekiwany wyjątek jej nie dają, a Skrypt dla maszyn nie ma działań po wyniku. Na wątku Uruchomienia tylko
przelicza i zapisuje wysyłkę w kolejce; sieć zostaje w wątku kolejki. Tytuł i treść przechodzą przez strażnika
reguły danych pracy Centrum (ADR 0025): ``URZĄDZENIA``, ``CZYNNOŚCI`` i ``UMOWA`` to tekst taty, w którym może stać
adres albo telefon. Strażnik dostaje gotowe bloki Markdown, bo zapis komórki w tabeli (``⏎``, ``\\|``) zmienia tylko
znaki między słowami, a strażnik szuka słów wartości bez względu na znaki między nimi.
"""

from __future__ import annotations

from typing import Final

from rozliczenia import quantity_check
from rozliczenia.centrum.catalog import declaration_of
from rozliczenia.centrum.outbox import Outbox, PeriodThread, Post
from rozliczenia.centrum.runs import EndedRun
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.client_data import Outgoing, guarded, tool

LABEL: Final = "kontrola-ilosci"


class QuantityCheckAfterRun:
    def __init__(self, work: CentrumWork, outbox: Outbox, commit: CommitSource) -> None:
        self._outbox = outbox
        self._commit = commit
        self._forbidden = work.forbidden

    def run_ended(self, run: EndedRun) -> None:
        checked = declaration_of(run.info.process).quantity_check
        if run.info.mode.dry_run or checked is None or run.shown is None:
            return
        period, run_id = run.info.period, run.info.id
        result = checked(run.shown.engine_summary)
        title = guarded(self._forbidden, quantity_check.title(period, result), "tytuł Kontroli ilości")
        blocks = [
            guarded(self._forbidden, block, "treść Kontroli ilości")
            for block in quantity_check.blocks(result, commit=self._commit(), run_id=run_id)
        ]
        notes = dict.fromkeys(note for guarded in (title, *blocks) for note in guarded.notes)
        tail = [] if not notes else [tool("## Uwagi techniczne\n\n" + "".join(f"- {note}\n" for note in notes))]

        def frame(number: int, count: int, text: Outgoing) -> Outgoing:
            return text if count == 1 else tool(f"Kontrola ilości, część {number}/{count} (Uruchomienie {run_id})\n\n") + text

        self._outbox.post(
            Post.of(
                PeriodThread(
                    label=LABEL,
                    line=tool(f"- Kontrola ilości okresu: {period}"),
                    closed="new_issue",
                    title=title.text,
                ),
                period=period,
                run_id=run_id,
                blocks=[*(block.text for block in blocks), *tail],
                frame=frame,
            )
        )
