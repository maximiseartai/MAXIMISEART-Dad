"""Kontrakt samego Centrum rozliczeń: tożsamość działającego Centrum i jego zamknięcie."""

from __future__ import annotations

from typing import Literal


from rozliczenia.centrum.contract.common import Model


class Health(Model):
    """Tożsamość działającego Centrum.

    ``commit`` to skrócony commit narzędzia, z którego Centrum wystartowało, jak na Konfiguracji (``None`` poza
    klonem Gita); po nim launcher i opiekun ponownego startu rozpoznają wersję działającego Centrum, a karta
    pokazuje go w „Zaktualizowano”. ``instance`` to losowy identyfikator tego startu Centrum: po ponownym starcie
    jest inny, także gdy commit się nie zmienił.
    """

    service: Literal["centrum-rozliczen"]
    commit: str | None
    instance: str


class Closing(Model):
    """Centrum przyjęło prośbę o zamknięcie i kończy pracę po tej odpowiedzi."""

    state: Literal["closing"]
