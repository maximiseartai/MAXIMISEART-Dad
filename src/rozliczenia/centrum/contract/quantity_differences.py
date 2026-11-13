"""Kontrakt listy „Tu wpisałeś inaczej niż reguła” w sekcji Reguły ilości okna Ustawień: różnice z Kontroli ilości
ostatnich Plików zbiorczych jako podpowiedzi z „Popraw regułę” i „To był wyjątek” (ADR 0033, US 62, 63)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.quantity_rules import PreviewFile, RuleForm
from rozliczenia.centrum.contract.settings_workers import SettingProblem


class QuantityDifference(Model):
    """Komórka, w której tata wpisał inaczej niż Reguły ilości: okres, numer wiersza Pliku zbiorczego, ``URZĄDZENIA``,
    ``CZYNNOŚCI``, dzień tygodnia z pełną godziną (``when``, np. „pt 16”), kolumna z nazwą pozycji cennika, ilość z
    reguł i wpis taty. Bez adresu, numeru zlecenia, ``UMOWA`` i daty dziennej.

    ``id``: id wyjątku, który zapisze „To był wyjątek”. ``draft``: formularz nowej reguły dla „Popraw regułę”, z
    warunkami z ``URZĄDZENIA`` tej różnicy i, gdy tata wpisał więcej niż reguła w kolumnie, którą reguła może wpisać,
    z wpisaniem brakującej ilości."""

    id: str
    period: str
    row: int
    devices: str
    activities: str
    when: str
    column: str
    name: str | None
    rule: int
    tata: int | Literal["nieliczbowa"]
    draft: RuleForm


class DifferencesReady(Model):
    """Różnice z Kontroli ilości ostatnich Plików zbiorczych po Przebiegu rozliczeń, liczone bieżącymi Regułami ilości,
    od najnowszego okresu, bez różnic oznaczonych jako wyjątek.

    ``unread``: okresy, których Pliku zbiorczego nie dało się przeczytać. ``differences``: najwyżej ``SHOWN`` różnic, a
    ``more`` reszta. ``exceptions``: różnice tych plików ukryte jako wyjątek. ``exceptions_problem``: zły plik wyjątków
    (lista liczy wtedy z ostatnimi dobrymi wyjątkami)."""

    state: Literal["ready"]
    files: list[PreviewFile]
    unread: list[str]
    differences: list[QuantityDifference]
    more: int
    exceptions: int
    exceptions_problem: SettingProblem | None


class DifferencesWithoutFiles(Model):
    """Różnic nie ma na czym policzyć: folder okresów nie jest wskazany (``no_periods_directory``) albo żaden okres nie
    ma jeszcze Rozliczeń pracowników (``no_settled_periods``)."""

    state: Literal["no_periods_directory", "no_settled_periods"]
    exceptions_problem: SettingProblem | None


QuantityDifferences = Annotated[DifferencesReady | DifferencesWithoutFiles, Field(discriminator="state")]


class ExceptionSaved(Model):
    """Lista różnic po zapisie wyjątku; ``change``: id wiersza Historii Ustawień („Zapisano · Cofnij”), ``None``: ta
    różnica już była wyjątkiem."""

    differences: QuantityDifferences
    change: str | None
