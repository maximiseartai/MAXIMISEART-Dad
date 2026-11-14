"""Kontrakt Konfiguracji: Wzorce, Token do Zgłoszeń i Aktualność narzędzia."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, computed_field

from rozliczenia.centrum.contract.common import Message, Model


class TemplateReady(Model):
    """Wzorzec jest na miejscu, nie jest otwarty i przechodzi Sprawdzanie."""

    state: Literal["ready"]
    label: str
    file_name: str


TemplateProblemKind = Literal["missing", "open_in_excel", "unreadable"]


class TemplateProblem(Model):
    """Wzorca nie ma, jest otwarty w Excelu albo nie przechodzi Sprawdzania."""

    state: Literal["problem"]
    label: str
    file_name: str
    problem: TemplateProblemKind
    message: Message

    @computed_field  # type: ignore[prop-decorator]
    @property
    def level(self) -> Literal["stop", "warning"]:
        """Jak karta Wzorców pokazuje Komunikat: Wzorzec otwarty w Excelu ostrzega (wystarczy go zamknąć), brak Wzorca i
        porażka Sprawdzania to Zatrzymanie."""

        return "warning" if self.problem == "open_in_excel" else "stop"


TemplateStatus = Annotated[TemplateReady | TemplateProblem, Field(discriminator="state")]


ReportKeyState = Literal["ready", "missing_key", "refused_key"]
"""Token do Zgłoszeń na tym komputerze: ``ready`` („Zgłoszenia: gotowe”: jest, a Skrzynka go nie odrzuciła, także bez
sieci), ``missing_key`` albo ``refused_key`` (Skrzynka Zgłoszeń odmówiła tego tokenu); nigdy jego wartość."""


ToolFreshnessState = Literal["current", "newer", "not_checked"]
"""Aktualność narzędzia: ``current`` (commit narzędzia zawiera najnowsze Wydanie), ``newer`` (jest nowsze Wydanie),
``not_checked`` (brak sieci, brak Wydania albo narzędzie bez commitu Gita)."""


class ToolVersion(Model):
    """Wersja narzędzia, z której działa Centrum: skrót commitu i dzień, od którego narzędzie jest na tym commicie."""

    commit: str
    since: date | None


class Configuration(Model):
    """Konfiguracja tylko do odczytu, wyliczana z katalogu konfiguracji przy każdym odczycie.

    ``version`` jest ``None``, gdy narzędzie nie leży w klonie Gita; ``freshness`` to Aktualność tej wersji
    względem najnowszego Wydania na GitHubie (ADR 0014), sprawdzana jak w Diagnozie. ``update_offered`` mówi,
    czy Konfiguracja proponuje Aktualizację narzędzia: tylko przy nowszym Wydaniu (``tool_freshness.offers_update``).
    """

    version: ToolVersion | None
    freshness: ToolFreshnessState
    update_offered: bool
    templates: list[TemplateStatus]
    reports: ReportKeyState
