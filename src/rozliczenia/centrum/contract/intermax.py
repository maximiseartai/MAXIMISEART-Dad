"""Kontrakt Uporządkowania INTERMAX: karta „Uporządkuj INTERMAX”, jego dni i Kopie INTERMAX."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Message, Model
from rozliczenia.centrum.contract.runs import RunRestored


class IntermaxSetup(Model):
    """Karta „Uporządkuj INTERMAX” poza okresami: INTERMAX to Rejestr zleceń z Ustawień Centrum.

    ``reminder`` to przypomnienie przed uruchomieniem, ``blocker`` mówi, czego brakuje w Ustawieniach Centrum,
    ``open_in_excel`` to zdanie o INTERMAX otwartym w Excelu, a ``last`` to karta ostatniego Uporządkowania
    INTERMAX z jego Logów Uruchomienia (``None``: żadnego albo jego Logów nie da się odczytać).
    """

    title: str
    reminder: str
    blocker: str | None
    open_in_excel: list[str]
    last: RunRestored | None


class IntermaxDay(Model):
    """Dzień na karcie „Uporządkuj INTERMAX”: data, jej skrót z dniem tygodnia, czy to dziś i czy jest uporządkowany."""

    day: date
    label: str
    today: bool
    ordered: bool


class IntermaxDays(Model):
    """Dziś i 6 dni wstecz oraz późniejsze Dni uporządkowane INTERMAX, po kolei.

    ``problem`` to Komunikat, gdy INTERMAX nie da się odczytać; ``days`` jest wtedy puste, tak jak bez wskazanego
    Rejestru zleceń.
    """

    days: list[IntermaxDay]
    problem: Message | None


IntermaxCopyBefore = Literal["ordering", "restore"]
"""Przed czym powstała Kopia INTERMAX: przed Uporządkowaniem INTERMAX albo przed przywróceniem innej Kopii."""


class IntermaxCopy(Model):
    """Kopia INTERMAX w folderze Kopii: nazwa pliku, chwila z nazwy i to, przed czym powstała, także słowami z nazwy
    (``before_label``), które karta Kopii pokazuje."""

    name: str
    taken_at: datetime
    before: IntermaxCopyBefore
    before_label: str


class IntermaxCopies(Model):
    """Kopie INTERMAX w Konfiguracji, od najnowszej.

    ``problem`` to Komunikat, gdy folderu Kopii nie da się odczytać; ``copies`` jest wtedy puste.
    """

    copies: list[IntermaxCopy]
    problem: Message | None


class IntermaxRestoreRequest(Model):
    """Przywrócenie Kopii INTERMAX ``name``, którą wymieniła lista Kopii."""

    name: str


class IntermaxRestored(Model):
    """INTERMAX ma bajty Kopii ``restored``, a jego stan sprzed przywrócenia leży jako nowa Kopia na liście Kopii.

    ``warnings``: Komunikaty o tym, czego przywrócenie nie dokończyło (starsze Kopie zostały).
    """

    state: Literal["restored"]
    restored: IntermaxCopy
    warnings: list[Message]


class IntermaxRestoreRefused(Model):
    """Przywrócenie odmówiło z Komunikatem; INTERMAX i Kopie zostały takie, jak były."""

    state: Literal["refused"]
    message: Message


IntermaxRestore = Annotated[IntermaxRestored | IntermaxRestoreRefused, Field(discriminator="state")]
