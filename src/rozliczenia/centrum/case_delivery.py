from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Final

from rozliczenia.centrum.comment_versions import LABEL as RUN_LOGS_LABEL
from rozliczenia.centrum.dad_cases import NOTE, REPORT, CaseKind, DadCases
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.outbox import ADDRESSES_FILE, QUEUE_DIRECTORY, Deliveries, KnownIssue, NewIssue, OpenIssue, Outbox, Post
from rozliczenia.centrum.report_issue import fingerprint_of
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.client_data import Outgoing, tool

_LOGS: Final = "Logi Uruchomienia"
UNSENT_DIRECTORY: Final = "zgloszenia"
_LOGS_ON_THE_WAY: Final = "logi-w-drodze"
_LOGS_REJECTED: Final = "logi-odrzucone"


def queue_directory(config: Path) -> Path:
    return config / UNSENT_DIRECTORY / QUEUE_DIRECTORY


def case_outbox(work: CentrumWork, box: KeyedBox, cases: DadCases) -> Outbox:
    return Outbox(
        queue_directory(work.config),
        box,
        work.log,
        clock=work.clock,
        listener=_CaseDelivery(cases),
        addresses=work.config / ADDRESSES_FILE,
    )


def logs_line(run_id: str, logs: str | None) -> str:
    return f"[{_LOGS}]({logs})" if logs is not None else _logs_on_the_way_line(run_id)


def shown_logs_line(run_id: str, logs: str | None) -> str:
    return _LOGS if logs is not None else _logs_on_the_way_line(run_id)


def _logs_on_the_way_line(run_id: str) -> str:
    return f"{_LOGS}: w drodze (Uruchomienie {run_id})"


def note_post(note_id: str, title: Outgoing, body: Outgoing, *, logs_on_the_way: bool) -> Post:
    state = _LOGS_ON_THE_WAY if logs_on_the_way else None
    return Post(NewIssue(NOTE.label, title), period=None, run_id=tool(note_id), header=None, parts=(body,), state=state)


class _CaseDelivery:
    def __init__(self, cases: DadCases) -> None:
        self._cases = cases

    def prepare(self, post: Post, sent: Deliveries) -> Post | None:
        if post.target.label != NOTE.label:
            return post
        if isinstance(post.target, KnownIssue):
            if (address := sent.delivered(post.run_id, RUN_LOGS_LABEL)) is not None:
                return replace(post, parts=(_logs_arrived(post.run_id, address),))
            return None if sent.rejected(post.run_id, RUN_LOGS_LABEL) else post
        run_id = self._pinned_run(post.run_id)
        if run_id is None or not _logs_on_the_way(post, run_id):
            return post
        lines, waiting = post.parts[0].split("\n"), logs_line(run_id, None)
        if waiting not in lines:
            return post
        line, state = _sent_logs_line(run_id, sent)
        lines[len(lines) - 1 - lines[::-1].index(waiting)] = line
        return replace(post, parts=(tool("\n".join(lines)), *post.parts[1:]), state=state)

    def delivered(self, post: Post, number: int) -> tuple[Post, ...]:
        case = _case(post)
        if case is None:
            return ()
        kind, case_id = case
        self._cases.numbered(kind, case_id, number)
        run_id = self._pinned_run(case_id) if post.state == _LOGS_REJECTED else None
        if run_id is None:
            return ()
        return (Post(KnownIssue(NOTE.label, number), period=None, run_id=tool(run_id), header=None, parts=(_logs_gone(run_id),)),)

    def rejected(self, post: Post) -> None:
        case = _case(post)
        if case is not None:
            self._cases.rejected(*case)

    def _pinned_run(self, note_id: str) -> str | None:
        note = self._cases.find(NOTE, note_id)
        return None if note is None else note.run_id


def _case(post: Post) -> tuple[CaseKind, str] | None:
    match post.target:
        case NewIssue(label=NOTE.label):
            return NOTE, post.run_id
        case OpenIssue(label=REPORT.label, line=line) if (fingerprint := fingerprint_of(line)) is not None:
            return REPORT, fingerprint
        case _:
            return None


def _logs_on_the_way(post: Post, run_id: str) -> bool:
    if post.state is not None:
        return post.state == _LOGS_ON_THE_WAY
    return post.parts[0].endswith(logs_line(run_id, None))


def _sent_logs_line(run_id: str, sent: Deliveries) -> tuple[str, str | None]:
    if (address := sent.delivered(run_id, RUN_LOGS_LABEL)) is not None:
        return logs_line(run_id, address), None
    if sent.rejected(run_id, RUN_LOGS_LABEL):
        return _rejected_logs_line(run_id), _LOGS_REJECTED
    return f"Logi Uruchomienia: nie powstały albo nie da się ich wysłać (Uruchomienie {run_id})", None


def _rejected_logs_line(run_id: str) -> str:
    return (
        f"Logi Uruchomienia: nie dotarły, Skrzynka odrzuciła ich treść (Uruchomienie {run_id}). "
        "Odnośnik przyjdzie w komentarzu, gdy dotrą."
    )


def _logs_arrived(run_id: str, address: str) -> Outgoing:
    return tool(f"{logs_line(run_id, address)} dotarły do Skrzynki po tej Uwadze (Uruchomienie {run_id}).")


def _logs_gone(run_id: str) -> Outgoing:
    return tool(f"Logi Uruchomienia nie dotrą: Centrum przestało je wysyłać (Uruchomienie {run_id}).")
