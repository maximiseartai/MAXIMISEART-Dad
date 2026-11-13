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

from dataclasses import replace
from typing import Any, Final

from rozliczenia.centrum.settings.files import Good
from rozliczenia.centrum.settings.folders import FOLDERS, FolderSettings
from rozliczenia.centrum.settings.migrations import workers as workers_migration
from rozliczenia.centrum.settings.proposal import Edit, Later, Nothing, Proposal, ReleaseChange, ReleaseInputs
from rozliczenia.period_folder import PeriodFolderInaccessible, layout_root


def periods_directory_from_layout_root(inputs: ReleaseInputs[FolderSettings]) -> Proposal[FolderSettings]:
    """Folder okresów zapisany w środku układu folderów taty (tydzień, ``INEA``, miesiąc) zamienia się na korzeń
    układu (``Załączniki``), od którego Centrum i tak liczy (ADR 0032, #1472); tata może to cofnąć.

    Korzeń i układ płaski zostają bez wiersza. Na później zostaje plik Ustawień zły albo nieczytelny (zmiana nie
    nadpisuje go ostatnią dobrą wartością), folder bez dostępu i folder, którego nie ma, a nad nim nie widać układu
    (OneDrive mógł go jeszcze nie oddać).
    """

    if not isinstance(inputs.current, Good):
        return Later("plik Ustawień ma złą treść albo nie da się go teraz przeczytać")
    settings = inputs.current.value
    saved = settings.periods_directory
    if saved is None:
        return Nothing()
    try:
        root = layout_root(saved).directory
    except PeriodFolderInaccessible:
        return Later("folderu okresów nie da się teraz odczytać")
    if root != saved:
        return Edit(lambda current: replace(current, periods_directory=root))
    if settings.periods_directory_state == "missing":
        return Later("folderu okresów nie ma")
    return Nothing()


RELEASE_CHANGES: Final[tuple[ReleaseChange[Any], ...]] = (
    workers_migration.CHANGE,
    ReleaseChange("2026-11-folder-okresow-od-zalacznikow", FOLDERS, periods_directory_from_layout_root),
)
"""Zmiany Ustawień Centrum, które niesie to Wydanie i każde poprzednie."""
