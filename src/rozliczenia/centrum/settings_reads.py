"""Ustawienia dla odczytu okna Centrum, który odpowiada z nich tacie (Tablica okresów, ścieżki okresu, Uzupełnienie,
różnice Kontroli ilości, otwarcie Rejestru zleceń, podgląd zmiany reguły): plik Ustawień, którego system nie daje
teraz czytać, to odmowa 409 o tym pliku (``refusal.settings_file_unreadable``), a nie treść z Wydania, którą tata
wziąłby za niewskazany folder okresów albo za swoje Reguły ilości. Jedyne miejsce tej odmowy w odczytach okna. Odczyt
niczego nie zapisuje, więc odmowa nie jest regułą przyjęcia zmiany właściciela Ustawień.
"""

from __future__ import annotations

from rozliczenia.centrum import refusal
from rozliczenia.centrum.settings.files import Unreadable
from rozliczenia.centrum.settings.folders import FOLDERS, FolderSettings
from rozliczenia.centrum.settings.owner import CentrumSettings, QuantityRulesView


def readable_folders(settings: CentrumSettings) -> FolderSettings:
    """Foldery; plik Folderów bez odczytu to odmowa o nim, a nie Rejestr zleceń i folder okresów niewskazane."""

    folders = settings.folders()
    if isinstance(folders, Unreadable):
        raise refusal.settings_file_unreadable(FOLDERS.name)
    return folders


def readable_quantity_rules(settings: CentrumSettings) -> QuantityRulesView:
    """Reguły ilości z Listą Urządzeń; plik pary bez odczytu to odmowa o nim, a nie reguły z Wydania."""

    view = settings.quantity_rules()
    if view.unreadable is None:
        return view
    raise refusal.settings_file_unreadable(view.unreadable)
