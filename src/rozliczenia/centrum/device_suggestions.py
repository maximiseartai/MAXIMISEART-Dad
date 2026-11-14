"""Podpowiedzi sekcji Urządzenia (ADR 0033, US 70): zapisy z ``URZĄDZENIA`` ostatnich okresów, których Lista Urządzeń nie
zna, do dodania jednym przyciskiem.

Pliki to te same ostatnie Pliki zbiorcze po Przebiegu rozliczeń, które czyta podgląd Reguł ilości
(``RecentCollectiveFiles``). Podpowiedź daje tylko zlecenie bez reguły (``WithoutRule``): zlecenie z opisu i zlecenie,
w którym zadziałała reguła „``URZĄDZENIA`` są dokładnie tekstem”, ma już swoją regułę. Zapis to kolejne słowa, których
lista nie zna (``DeviceList.unknown_spellings``), więc po dodaniu go do Listy Urządzeń podpowiedź znika. Odpowiedź ma
tylko zapisy z ``URZĄDZENIA`` i liczby zleceń, jak podgląd: bez adresu, numeru zlecenia, ``UMOWA`` i daty.
"""

from __future__ import annotations

from collections import Counter
from typing import Final

from rozliczenia.centrum.contract import quantity_rules as contract
from rozliczenia.centrum.quantity_rules_preview import Recent
from rozliczenia.quantity_engine import QuantityRules, WithoutRule, evaluate

SHOWN_SUGGESTIONS: Final = 10
"""Najwyżej tyle podpowiedzi pokazuje sekcja Urządzenia, od najczęstszej."""


def device_suggestions(rules: QuantityRules, recent: Recent) -> contract.DeviceSuggestions:
    """Zapisy spoza Listy Urządzeń ``rules`` w zleceniach bez reguły plików ``recent``, z liczbą tych zleceń."""

    orders: Counter[str] = Counter()
    for file in recent.files:
        for numbered in file.orders.rows:
            content = numbered.order.content
            if content is not None and isinstance(evaluate(rules, content), WithoutRule):
                orders.update(set(rules.devices.unknown_spellings(content.devices)))
    ranked = sorted(orders.items(), key=lambda item: (-item[1], item[0]))[:SHOWN_SUGGESTIONS]
    return contract.DeviceSuggestions(
        suggestions=[contract.DeviceSuggestion(spelling=spelling, orders=count) for spelling, count in ranked],
        unread=list(recent.unread),
    )
