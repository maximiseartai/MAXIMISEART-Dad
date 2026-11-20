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
                run_id=tool(run_id),
                blocks=[*(block.text for block in blocks), *tail],
                frame=frame,
            )
        )
