"""Kontrakt Uwag taty: pisanie, podgląd, wysłanie i Uruchomienia do przypięcia."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import StringConstraints, computed_field

from rozliczenia import domain
from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.runs import ResultTone, result_tone
from rozliczenia.domain import RunMode
from rozliczenia.process_run import RunResult


class PinnableRun(Model):
    """Uruchomienie z Centrum, do którego tata może przypiąć Uwagę: to, co o nim mówi wiersz okna Uwagi i stopka.

    Pola jak w ``ProcessRun``, z którego powstaje; identyfikator jest zawsze, bo bez niego nie ma czego przypiąć.
    """

    run_id: str
    process_label: str
    started_at: datetime
    mode: RunMode
    period: str
    result: RunResult
    stop_kind: domain.StopKind | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mode_word(self) -> str:
        """Słowo trybu w wierszu okna Uwagi, to samo co w Uwadze taty (``RunMode.word``)."""

        return self.mode.word

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tone(self) -> ResultTone:
        """Ton wyniku (``runs.result_tone``): plakietka w wierszu okna Uwagi i słowo wyniku w stopce Uwagi."""

        return result_tone(self.result, self.stop_kind)


DAD_NOTE_TITLE_MAX_LENGTH = 120


DAD_NOTE_BODY_MAX_LENGTH = 10_000


DadNoteTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=DAD_NOTE_TITLE_MAX_LENGTH, pattern=r"^[^\r\n]*$")
]
"""Tytuł Uwagi taty to jedna linia: issue w Skrzynce Zgłoszeń i Powiadomienie nazywają ją tym tytułem."""


DadNoteBody = Annotated[str, StringConstraints(strip_whitespace=True, max_length=DAD_NOTE_BODY_MAX_LENGTH)]


class DadNoteText(Model):
    """Tytuł i treść Uwagi taty w trakcie pisania, do podglądu „Maks dostanie”; tytuł może być jeszcze pusty.

    ``run_id`` to Uruchomienie z Centrum (``ProcessRun.run_id``), do którego tata przypina Uwagę; ``None``: ogólna.
    """

    title: DadNoteTitle
    body: DadNoteBody = ""
    run_id: str | None = None


class DadNoteRequest(Model):
    """Uwaga taty do wysłania: tytuł wymagany, treść nie jest konieczna; białe znaki na brzegach znikają.

    ``run_id`` jak w ``DadNoteText``: Uruchomienie, do którego Uwaga jest przypięta; ``None``: ogólna.
    """

    title: Annotated[DadNoteTitle, StringConstraints(min_length=1)]
    body: DadNoteBody = ""
    run_id: str | None = None


class DadNoteDraft(Model):
    """Dokładnie to, co dostanie Maks: tytuł i treść issue Uwagi taty w Skrzynce Zgłoszeń.

    ``shown_body`` to ta treść tak, jak pokazuje ją tacie „Maks dostanie”: odnośnik do Logów Uruchomienia jako sam
    napis, jak na GitHubie, bez adresu prywatnej Skrzynki, którego tata i tak nie otworzy.
    """

    title: str
    body: str
    shown_body: str
