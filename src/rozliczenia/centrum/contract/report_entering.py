"""Kontrakt Wpisania raportów: karta „Wpisz raporty z maili” poza okresami (ADR 0028)."""

from __future__ import annotations

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.runs import RunRestored


class ReportEnteringSetup(Model):
    """Karta „Wpisz raporty z maili” poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty.

    ``reminder`` to przypomnienie przed kliknięciem, ``blocker`` mówi, czego brakuje w Ustawieniach taty albo w
    ``config`` (plik dostępu do skrzynki raportów, plik adresów Wykonawców), albo jaka kopia konfliktu OneDrive leży
    obok INTERMAX, ``open_in_excel`` to zdanie o INTERMAX otwartym w Excelu, a ``last`` to karta ostatniego Wpisania
    raportów z jego Logów Uruchomienia (``None``: żadnego albo jego Logów nie da się odczytać).
    """

    title: str
    reminder: str
    blocker: str | None
    open_in_excel: list[str]
    last: RunRestored | None
