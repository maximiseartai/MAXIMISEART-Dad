"""Ustawienia ze startu gospodarza bez Ustawień Centrum (``settings_at_start.SettingsAtStart``): Skryptu dla maszyn,
wyroczni skilli i testów. Jest w ``tools/lib``, bo treść z Wydania plików Ustawień czyta w ``src/`` tylko ich właściciel
(``src/ruff.toml``).
"""

from __future__ import annotations

from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.centrum.settings_at_start import SettingsAtStart
from rozliczenia.quantity_rules_file import DEFAULT_QUANTITY_RULES
from rozliczenia.worker_list import WorkerList


def ustawienia_z_wydania(workers: WorkerList | None) -> SettingsAtStart:
    """Reguły ilości i Legenda czynności z Wydania, Lista Wykonawców ``workers`` od gospodarza (``None``: proces jej
    nie potrzebuje), bez migawki Ustawień Centrum i bez ostrzeżeń startu."""

    return SettingsAtStart(
        snapshot=None,
        workers=workers,
        quantity_rules=DEFAULT_QUANTITY_RULES,
        activity_legend=DEFAULT_ACTIVITY_LEGEND,
        warnings=(),
    )
