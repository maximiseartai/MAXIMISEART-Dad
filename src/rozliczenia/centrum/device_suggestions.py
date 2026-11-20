from __future__ import annotations

from collections import Counter
from typing import Final

from rozliczenia.centrum.contract import quantity_rules as contract
from rozliczenia.centrum.quantity_rules_preview import Recent
from rozliczenia.quantity_engine import QuantityRules, WithoutRule, evaluate

SHOWN_SUGGESTIONS: Final = 10


def device_suggestions(rules: QuantityRules, recent: Recent) -> contract.DeviceSuggestions:
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
