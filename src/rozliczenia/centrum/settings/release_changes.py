"""Zmiany Ustawień Centrum w Wydaniu (ADR 0032, furtka Maksa): jawne, nazwane, jednorazowe zmiany, które Wydanie niesie
w kodzie, bo Aktualizacja narzędzia nie nadpisuje plików w ``config``.

Właściciel (``CentrumSettings.apply_release_changes``) stosuje przy każdym starcie Centrum, przed pierwszym zapytaniem,
każdą zmianę, której jeszcze nie zapamiętał, z tymi samymi sprawdzeniami co zmiana taty. Zmiana, która weszła, ma w
Historii Ustawień źródło z numerem Wydania i „Cofnij”, a odrzucona ma powód i nie wraca. Wydanie bez wpisu niczego nie pisze.

Wpis dopisuje się do ``RELEASE_CHANGES`` obok wpisów tej samej funkcji, nigdy nie zmienia się ani nie usuwa wpisu z
Wydania, które już wyszło: jego id jest w pamięci właściciela u taty. Edycja jest deklaratywna („ustaw”, „dodaj, jeśli
nie ma”), bo po utracie pamięci właściciela zmiana biegnie jeszcze raz i wtedy nie może dać różnicy ani wiersza.
"""

from __future__ import annotations

from typing import Any, Final

from rozliczenia.centrum.settings.migrations import workers as workers_migration
from rozliczenia.centrum.settings.proposal import ReleaseChange

RELEASE_CHANGES: Final[tuple[ReleaseChange[Any], ...]] = (workers_migration.CHANGE,)
"""Zmiany Ustawień Centrum, które niesie to Wydanie i każde poprzednie."""
