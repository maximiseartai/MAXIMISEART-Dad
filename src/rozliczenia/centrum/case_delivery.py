"""Sprawy taty w Skrzynce (ADR 0007, 0015): co doręczenie przez Kolejkę wysyłki znaczy dla Sprawy taty.

``case_outbox`` to jedyna droga, którą Centrum buduje kolejkę Skrzynki Zgłoszeń: z jej słuchaczem doręczeń, który
wie, która wysyłka jest którą sprawą. Nowe issue z etykietą ``uwaga-taty`` to Uwaga taty o identyfikatorze wysyłki,
a ``ReportIssue`` to Zgłoszenie o odcisku problemu z celu wysyłki. Przyjęta wysyłka sprawy daje sprawie numer issue
(``DadCases.numbered``), a odrzucona treść zostaje w pamięci Spraw taty (``DadCases.rejected``). Logi, Kontrole
ilości i komentarze do znanego issue sprawami nie są.

Uwaga przypięta do Uruchomienia niesie w stopce linię jego Logów (``logs_line``). Gdy Logi jeszcze czekają w kolejce,
szkic mówi, że są w drodze, a słuchacz tuż przed wysłaniem Uwagi wstawia odnośnik, jeśli Logi zdążyły dojść do
skrzynki, a jeśli nie, mówi, dlaczego ich nie ma. Logi idą przed Uwagą (starszy plik kolejki), więc Uwaga wychodzi bez
nich tylko wtedy, gdy skrzynka odrzuciła ich treść albo nie było ich w kolejce. Po odrzuconych Logach dostarczenie
Uwagi oddaje kolejce komentarz do jej issue, który czeka na te Logi i wychodzi z odnośnikiem, gdy dotrą przy którymś
następnym starcie Centrum, a gdy znikną z kolejki, z tym, że nie dotrą. Tworzy go tylko dostarczenie Uwagi, więc
każde jej issue dostaje najwyżej jeden taki komentarz, także po ponownym starcie.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.comment_versions import LABEL as RUN_LOGS_LABEL
from rozliczenia.centrum.dad_cases import NOTE, REPORT, CaseKind, DadCases
from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import Deliveries, KnownIssue, NewIssue, Outbox, Post, ReportIssue


def case_outbox(
    directory: Path, box: KeyedBox, log: CentrumLog, cases: DadCases, *, clock: Clock, addresses: Path | None
) -> Outbox:
    """Kolejka Skrzynki Zgłoszeń w ``directory``, której doręczenia dają Sprawom taty ``cases`` numer i odnośnik do Logów."""

    return Outbox(directory, box, log, clock=clock, listener=_CaseDelivery(cases), addresses=addresses)


def logs_line(run_id: str, logs: str | None) -> str:
    """Linia Logów przypiętej Uwagi: odnośnik albo „w drodze”, którą słuchacz kolejki zamienia tuż przed wysłaniem.

    Odnośnik to link Markdown: GitHub pokazuje Maksowi sam napis, a „Maks dostanie” pokazuje tacie ten sam napis
    bez adresu prywatnej Skrzynki, którego tata i tak nie otworzy.
    """

    return f"[Logi Uruchomienia]({logs})" if logs is not None else f"Logi Uruchomienia: w drodze (Uruchomienie {run_id})"


class _CaseDelivery:
    """Słuchacz doręczeń kolejki (``outbox.Listener``) dla Spraw taty."""

    def __init__(self, cases: DadCases) -> None:
        self._cases = cases

    def prepare(self, post: Post, sent: Deliveries) -> Post | None:
        """Logi w Uwadze przypiętej do Uruchomienia tuż przed wysłaniem; każda inna wysyłka idzie bez zmian.

        Uwaga, której stopka mówi, że Logi są w drodze, dostaje odnośnik albo linię, dlaczego Logów nie ma. Komentarz
        z odnośnikiem do issue Uwagi (``run_id`` to Uruchomienie) czeka (``None``), dopóki skrzynka odrzuca Logi w tej
        pracy Centrum, a gdy Logów nie ma ani w Skrzynce, ani w kolejce, idzie z zapisanym tekstem, że nie dotrą.
        """

        if post.target.label != NOTE.label:
            return post
        if isinstance(post.target, KnownIssue):
            if (address := sent.delivered(post.run_id, RUN_LOGS_LABEL)) is not None:
                return replace(post, parts=(_logs_arrived(post.run_id, address),))
            return None if sent.rejected(post.run_id, RUN_LOGS_LABEL) else post
        run_id = self._pinned_run(post.run_id)
        if run_id is None:
            return post
        first, waiting = post.parts[0], logs_line(run_id, None)
        if not first.endswith(waiting):
            return post
        return replace(post, parts=(first.removesuffix(waiting) + _sent_logs_line(run_id, sent), *post.parts[1:]))

    def delivered(self, post: Post, number: int) -> tuple[Post, ...]:
        """Sprawa wysyłki dostaje numer issue; Uwaga, która wyszła przed odrzuconymi Logami swojego Uruchomienia,
        oddaje komentarz z odnośnikiem do nich."""

        case = _case(post)
        if case is None:
            return ()
        kind, case_id = case
        self._cases.numbered(kind, case_id, number)
        run_id = self._pinned_run(case_id) if kind == NOTE else None
        if run_id is None or not post.parts[0].endswith(_rejected_logs_line(run_id)):
            return ()
        return (Post(KnownIssue(NOTE.label, number), period=None, run_id=run_id, header=None, parts=(_logs_gone(run_id),)),)

    def rejected(self, post: Post) -> None:
        case = _case(post)
        if case is not None:
            self._cases.rejected(*case)

    def _pinned_run(self, note_id: str) -> str | None:
        """Uruchomienie, do którego przypięta jest Uwaga ``note_id``; ``None``: Uwaga ogólna albo nieznana."""

        note = self._cases.find(NOTE, note_id)
        return None if note is None else note.run_id


def _case(post: Post) -> tuple[CaseKind, str] | None:
    """Rodzaj i identyfikator sprawy, którą niesie wysyłka; ``None``: wysyłka nie jest sprawą."""

    match post.target:
        case NewIssue(label=NOTE.label):
            return NOTE, post.run_id
        case ReportIssue(fingerprint=fingerprint):
            return REPORT, fingerprint
        case _:
            return None


def _sent_logs_line(run_id: str, sent: Deliveries) -> str:
    """Linia Logów przypiętej Uwagi w chwili wysłania: odnośnik albo dlaczego Logów nie ma w Skrzynce."""

    if (address := sent.delivered(run_id, RUN_LOGS_LABEL)) is not None:
        return logs_line(run_id, address)
    if sent.rejected(run_id, RUN_LOGS_LABEL):
        return _rejected_logs_line(run_id)
    return f"Logi Uruchomienia: nie powstały albo nie da się ich wysłać (Uruchomienie {run_id})"


def _rejected_logs_line(run_id: str) -> str:
    return (
        f"Logi Uruchomienia: nie dotarły, Skrzynka odrzuciła ich treść (Uruchomienie {run_id}). "
        "Odnośnik przyjdzie w komentarzu, gdy dotrą."
    )


def _logs_arrived(run_id: str, address: str) -> str:
    return f"{logs_line(run_id, address)} dotarły do Skrzynki po tej Uwadze (Uruchomienie {run_id})."


def _logs_gone(run_id: str) -> str:
    return f"Logi Uruchomienia nie dotrą: Centrum przestało je wysyłać (Uruchomienie {run_id})."
