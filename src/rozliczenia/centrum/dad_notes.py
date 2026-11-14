"""Uwaga taty (ADR 0015): treść issue, wysyłka przez kolejkę Skrzynki Zgłoszeń i stan Uwag na tym komputerze.

Treść issue powstaje tylko w ``note_issue``: podgląd „Maks dostanie” i wysyłka wołają tę samą funkcję, więc tata widzi
dokładnie to, co dostanie Maks. „Wyślij” zapisuje Uwagę bez numeru issue jako sprawę taty (``DadCases``), kładzie ją w
kolejce Skrzynki Zgłoszeń jako osobne issue z etykietą ``uwaga-taty`` i czeka na skrzynkę najwyżej ``DELIVERY_WAIT_S``,
a gdy jej nie przyjęła, mówi, na co Uwaga czeka (``DadCases.queued``). Numer issue dopisuje wątek kolejki, także po
następnym starcie Centrum, a zamknięcie issue przez Maksa sprawdzanie Powiadomień. Sprawa ma tylko tytuł Uwagi i
przypięte Uruchomienie, bez treści.

Uwaga przypięta do Uruchomienia procesu z Centrum niesie w stopce jego proces, okres, tryb, wynik i datę oraz
odnośnik do jego Logów Uruchomienia w Skrzynce. Uruchomienia do wyboru i do przypięcia pochodzą z historii metryk
(``History``). Gdy Logi jeszcze czekają w kolejce, stopka szkicu mówi, że są w drodze; co z tą linią dzieje się w
kolejce, wiedzą Sprawy taty w Skrzynce (``case_delivery``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from fastapi import APIRouter

from rozliczenia.client_data import ForbiddenValues, Outgoing, guarded, tool
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import dad_notes as dad_notes_contract
from rozliczenia.centrum.contract import metrics as metrics_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.case_delivery import logs_line, note_post, shown_logs_line
from rozliczenia.centrum.dad_cases import NOTE, Case, DadCases
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.outbox import DELIVERY_WAIT_S, Outbox
from rozliczenia.centrum.tool_freshness import CommitSource
from rozliczenia.centrum.version import version_label
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.wall_clock import utc_now

RECENT_RUNS: Final = 6

History = Callable[[], list[metrics_contract.ProcessRun]]
"""Uruchomienia procesu z plików metryk od najnowszego (``metrics.History.runs``); ``OSError``: pliki nieczytelne."""
LogsAddress = Callable[[str], str | None]
"""Adres pierwszego komentarza Logów Uruchomienia o tym identyfikatorze w Skrzynce; ``None``: jeszcze ich tam nie ma."""


@dataclass(frozen=True)
class PinnedRun:
    """Uruchomienie z Centrum, do którego tata przypiął Uwagę, i adres jego Logów.

    ``logs`` ``None``: Logi Uruchomienia jeszcze nie doszły do Skrzynki Zgłoszeń.
    """

    run: dad_notes_contract.PinnableRun
    logs: str | None


@dataclass(frozen=True)
class NoteIssue:
    """Issue Uwagi taty do wysyłki i jego treść w podglądzie „Maks dostanie” (``DadNoteDraft.shown_body``)."""

    title: Outgoing
    body: Outgoing
    shown_body: str


def note_issue(
    title: str, body: str, commit: str | None, pinned: PinnedRun | None, forbidden: ForbiddenValues
) -> NoteIssue:
    """Issue Uwagi taty: jej tytuł, a w treści jej tekst i stopka (bez tekstu sama stopka).

    Stopka Uwagi ogólnej to wersja narzędzia; przypiętej to linia Uruchomienia z wersją i linia jego Logów. Tytuł i
    tekst przechodzą przez strażnika reguły danych pracy Centrum (ADR 0025), a uwaga techniczna o zamaskowanej wartości
    staje pod tekstem, więc tata widzi w podglądzie dokładnie to, co dostanie Maks, z odnośnikiem do Logów jako samym
    napisem.
    """

    version = f"wersja narzędzia {version_label(commit)}"
    title_guarded = guarded(forbidden, title, "tytuł Uwagi taty")
    body_guarded = guarded(forbidden, body, "treść Uwagi taty")
    notes = "".join(f"\n{note}" for note in (*title_guarded.notes, *body_guarded.notes))
    text = f"{body_guarded.text}{notes}".strip("\n")

    def with_footer(logs: Callable[[str, str | None], str]) -> str:
        footer = f"Uwaga ogólna · {version}" if pinned is None else _pinned_footer(pinned, version, logs)
        return f"{text}\n\n{footer}" if text else footer

    return NoteIssue(title_guarded.text, tool(with_footer(logs_line)), with_footer(shown_logs_line))


def _pinned_footer(pinned: PinnedRun, version: str, logs: Callable[[str, str | None], str]) -> str:
    run = pinned.run
    started = run.started_at.astimezone()
    facts = (run.process_label, run.period, run.mode.word, runs_contract.result_word(run.tone), f"{started:%d.%m.%Y, %H:%M}")
    return f"Uruchomienie: {' · '.join((*facts, version))}\n{logs(run.run_id, pinned.logs)}"


def _pinnable(history: History) -> list[dad_notes_contract.PinnableRun]:
    """Uruchomienia z Centrum z historii, od najnowszego; Uruchomienie bez identyfikatora nie ma czego przypiąć."""

    try:
        runs = history()
    except OSError:
        raise refusal.history_unreadable() from None
    return [dad_notes_contract.PinnableRun.model_validate(run, from_attributes=True) for run in runs if run.run_id is not None]


def _pickable(own: list[dad_notes_contract.PinnableRun], selected: str | None) -> list[dad_notes_contract.PinnableRun]:
    """Uruchomienia do wyboru w oknie Uwagi: ``RECENT_RUNS`` najnowszych i starsze ``selected``.

    ``selected`` to Uruchomienie z karty, z której tata otworzył okno; nieznane jest pomijane.
    """

    return own[:RECENT_RUNS] + [run for run in own[RECENT_RUNS:] if run.run_id == selected]


def _pinned(run_id: str | None, history: History, logs: LogsAddress) -> PinnedRun | None:
    """Uruchomienie spoza historii to odmowa 404."""

    if run_id is None:
        return None
    run = next((run for run in _pinnable(history) if run.run_id == run_id), None)
    if run is None:
        raise refusal.run_not_in_history()
    return PinnedRun(run, logs(run_id))


def send(
    request: dad_notes_contract.DadNoteRequest,
    cases: DadCases,
    outbox: Outbox,
    box: KeyedBox,
    commit: str | None,
    pinned: PinnedRun | None,
    forbidden: ForbiddenValues,
) -> common_contract.SendState:
    """Uwaga, której kolejka nie zapisała, to odmowa: inaczej tekst taty przepadłby po cichu."""

    issue = note_issue(request.title, request.body, commit, pinned, forbidden)
    run_id = None if pinned is None else pinned.run.run_id
    note = Case(NOTE, uuid.uuid4().hex, issue.title, commit, utc_now(), number=None, run_id=run_id)
    cases.add(note)
    logs_on_the_way = pinned is not None and pinned.logs is None
    queued = outbox.post(note_post(note.id, issue.title, issue.body, logs_on_the_way=logs_on_the_way))
    if not queued:
        cases.forget(NOTE, note.id)
        raise refusal.note_not_queued()
    if outbox.wait_delivered(note.id, NOTE.label, timeout_s=DELIVERY_WAIT_S):
        return common_contract.Sent(state="sent")
    return cases.queued(note.id, box)


def dad_notes_router(
    work: CentrumWork,
    cases: DadCases,
    outbox: Outbox,
    box: KeyedBox,
    commit: CommitSource,
    history: History,
    logs: LogsAddress,
) -> APIRouter:
    forbidden = work.forbidden
    router = APIRouter(prefix="/api/dad-notes", tags=["uwagi-taty"])
    refusals: dict[int | str, dict[str, object]] = {status: {"model": common_contract.Problem} for status in (404, 500)}

    @router.get("/runs", operation_id="getDadNoteRuns", responses={500: {"model": common_contract.Problem}})
    def runs(selected: str | None = None) -> list[dad_notes_contract.PinnableRun]:
        return _pickable(_pinnable(history), selected)

    @router.post("/draft", operation_id="draftDadNote", responses=refusals)
    def draft(text: dad_notes_contract.DadNoteText) -> dad_notes_contract.DadNoteDraft:
        issue = note_issue(text.title, text.body, commit(), _pinned(text.run_id, history, logs), forbidden)
        return dad_notes_contract.DadNoteDraft.model_validate(issue, from_attributes=True)

    @router.post("", operation_id="sendDadNote", responses=refusals)
    def send_note(request: dad_notes_contract.DadNoteRequest) -> common_contract.SendState:
        return send(request, cases, outbox, box, commit(), _pinned(request.run_id, history, logs), forbidden)

    return router
