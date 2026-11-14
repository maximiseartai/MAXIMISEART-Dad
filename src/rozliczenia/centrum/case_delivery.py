"""Sprawy taty w Skrzynce (ADR 0007, 0015): co doręczenie przez Kolejkę wysyłki znaczy dla Sprawy taty.

``case_outbox`` to jedyna droga, którą Centrum buduje kolejkę Skrzynki Zgłoszeń: z jej słuchaczem doręczeń, który
wie, która wysyłka jest którą sprawą. Nowe issue z etykietą ``uwaga-taty`` to Uwaga taty o identyfikatorze wysyłki,
a jedno otwarte issue z etykietą Zgłoszenia (``reports.report_target``) to Zgłoszenie o odcisku problemu z wiersza
rozpoznawczego celu. Przyjęta wysyłka sprawy daje sprawie numer issue
(``DadCases.numbered``), a odrzucona treść zostaje w pamięci Spraw taty (``DadCases.rejected``). Logi, Kontrole
ilości i komentarze do znanego issue sprawami nie są.

Uwaga przypięta do Uruchomienia niesie w stopce linię jego Logów (``logs_line``). Gdy Logi jeszcze czekają w kolejce,
szkic mówi, że są w drodze, a wysyłka Uwagi niesie to w stanie (``note_post``, ``Post.state``). Słuchacz tuż przed
wysłaniem takiej Uwagi wymienia tę linię na odnośnik, jeśli Logi zdążyły dojść do skrzynki, a jeśli nie, na linię,
dlaczego ich nie ma. Logi idą przed Uwagą (starszy plik kolejki), więc Uwaga wychodzi bez
nich tylko wtedy, gdy skrzynka odrzuciła ich treść albo nie było ich w kolejce. Po odrzuconych Logach dostarczenie
Uwagi oddaje kolejce komentarz do jej issue, który czeka na te Logi i wychodzi z odnośnikiem, gdy dotrą przy którymś
następnym starcie Centrum, a gdy znikną z kolejki, z tym, że nie dotrą. Tworzy go tylko dostarczenie Uwagi, więc
każde jej issue dostaje najwyżej jeden taki komentarz, także po ponownym starcie.
"""

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
"""Napis linii Logów przypiętej Uwagi, a w niej odnośnika do nich."""
UNSENT_DIRECTORY: Final = "zgloszenia"
"""Katalog Zgłoszeń i Uwag taty, których Skrzynka jeszcze nie dostała, w ``config``; w nim Kolejka wysyłki."""
_LOGS_ON_THE_WAY: Final = "logi-w-drodze"
"""Stan wysyłki Uwagi (``Post.state``): stopka mówi, że Logi przypiętego Uruchomienia są w drodze."""
_LOGS_REJECTED: Final = "logi-odrzucone"
"""Stan Uwagi po ``prepare``: wychodzi z linią, że Skrzynka odrzuciła treść Logów, więc po niej idzie komentarz
z odnośnikiem."""


def queue_directory(config: Path) -> Path:
    """Kolejka wysyłki Skrzynki Zgłoszeń w ``config`` narzędzia: ``config/zgloszenia/kolejka``."""

    return config / UNSENT_DIRECTORY / QUEUE_DIRECTORY


def case_outbox(work: CentrumWork, box: KeyedBox, cases: DadCases) -> Outbox:
    """Kolejka Skrzynki Zgłoszeń pracy Centrum ``work`` w ``config/zgloszenia/kolejka``, z adresami dostarczonych wysyłek
    obok, której doręczenia dają Sprawom taty ``cases`` numer i odnośnik do Logów."""

    return Outbox(
        queue_directory(work.config),
        box,
        work.log,
        clock=work.clock,
        listener=_CaseDelivery(cases),
        addresses=work.config / ADDRESSES_FILE,
    )


def logs_line(run_id: str, logs: str | None) -> str:
    """Linia Logów przypiętej Uwagi: odnośnik albo „w drodze”, którą słuchacz kolejki zamienia tuż przed wysłaniem.

    Odnośnik to link Markdown, z którego GitHub pokazuje Maksowi sam napis (``shown_logs_line``).
    """

    return f"[{_LOGS}]({logs})" if logs is not None else _logs_on_the_way_line(run_id)


def shown_logs_line(run_id: str, logs: str | None) -> str:
    """``logs_line`` tak, jak pokazuje ją tacie „Maks dostanie”: odnośnik jako sam napis, jak na GitHubie, bez adresu
    prywatnej Skrzynki, którego tata i tak nie otworzy."""

    return _LOGS if logs is not None else _logs_on_the_way_line(run_id)


def _logs_on_the_way_line(run_id: str) -> str:
    return f"{_LOGS}: w drodze (Uruchomienie {run_id})"


def note_post(note_id: str, title: Outgoing, body: Outgoing, *, logs_on_the_way: bool) -> Post:
    """``logs_on_the_way``: stopka ma linię Logów w drodze (``logs_line`` bez adresu), którą słuchacz wymieni tuż przed
    wysłaniem."""

    state = _LOGS_ON_THE_WAY if logs_on_the_way else None
    return Post(NewIssue(NOTE.label, title), period=None, run_id=note_id, header=None, parts=(body,), state=state)


class _CaseDelivery:
    """Słuchacz doręczeń kolejki (``outbox.Listener``) dla Spraw taty."""

    def __init__(self, cases: DadCases) -> None:
        self._cases = cases

    def prepare(self, post: Post, sent: Deliveries) -> Post | None:
        """Logi w Uwadze przypiętej do Uruchomienia tuż przed wysłaniem; każda inna wysyłka idzie bez zmian.

        Uwaga, której stopka mówi, że Logi są w drodze, dostaje w miejsce tej linii odnośnik albo linię, dlaczego Logów
        nie ma. Komentarz
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
        if run_id is None or not _logs_on_the_way(post, run_id):
            return post
        lines, waiting = post.parts[0].split("\n"), logs_line(run_id, None)
        if waiting not in lines:
            return post
        line, state = _sent_logs_line(run_id, sent)
        lines[len(lines) - 1 - lines[::-1].index(waiting)] = line
        return replace(post, parts=(tool("\n".join(lines)), *post.parts[1:]), state=state)

    def delivered(self, post: Post, number: int) -> tuple[Post, ...]:
        """Sprawa wysyłki dostaje numer issue; Uwaga, która wyszła przed odrzuconymi Logami swojego Uruchomienia,
        oddaje komentarz z odnośnikiem do nich."""

        case = _case(post)
        if case is None:
            return ()
        kind, case_id = case
        self._cases.numbered(kind, case_id, number)
        run_id = self._pinned_run(case_id) if post.state == _LOGS_REJECTED else None
        if run_id is None:
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
        case OpenIssue(label=REPORT.label, line=line) if (fingerprint := fingerprint_of(line)) is not None:
            return REPORT, fingerprint
        case _:
            return None


def _logs_on_the_way(post: Post, run_id: str) -> bool:
    """Czy stopka Uwagi mówi, że Logi Uruchomienia ``run_id`` są w drodze.

    Plik kolejki sprzed ``Post.state`` stanu nie ma, a mówi to końcówka tekstu, jak w Centrum, które go zapisało. Warunek
    usunięcia tego odczytu jak przy ``outbox._parse``: w kolejce taty nie ma pliku sprzed ``Post.state``.
    """

    if post.state is not None:
        return post.state == _LOGS_ON_THE_WAY
    return post.parts[0].endswith(logs_line(run_id, None))


def _sent_logs_line(run_id: str, sent: Deliveries) -> tuple[str, str | None]:
    """Linia Logów przypiętej Uwagi w chwili wysłania (odnośnik albo dlaczego Logów nie ma w Skrzynce) i stan Uwagi."""

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
