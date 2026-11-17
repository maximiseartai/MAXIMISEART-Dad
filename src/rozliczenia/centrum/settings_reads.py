"""Ustawienia dla odczytu okna Centrum, który odpowiada z nich tacie (Tablica okresów, ścieżki okresu, Uzupełnienie,
różnice Kontroli ilości, otwarcie Rejestru zleceń, podgląd zmiany reguły): plik Ustawień, którego system nie daje
teraz czytać, to odmowa 409 o tym pliku (``refusal.settings_file_unreadable``), a nie treść z Wydania, którą tata
wziąłby za niewskazany folder okresów albo za swoje Reguły ilości. Odczyt niczego nie zapisuje, więc odmowa nie jest
regułą przyjęcia zmiany właściciela Ustawień.

Jedno wejście odczytu okna z odmową w właścicielu (prototyp P5, kształt X, 17.11.2026) nie zabija treści zastępczej:
wołający dalej ma migawkę i widoki z unią na tym samym obiekcie, więc literał albo stała w gałęzi unii przechodzą mypy i
ruff; ciche pola widoków zamyka typ (``QuantityRulesView.rules``, ``shown``), a stałe zakaz TID251. Wróć do X, gdy
odczyt okna z odmową potrzebuje trzech albo więcej plików naraz albo gdy druga droga tej odmowy wróci w przeglądzie.
"""

from __future__ import annotations

from rozliczenia.activity_legend import ActivityLegend
from rozliczenia.centrum import refusal
from rozliczenia.centrum.settings.files import Unreadable
from rozliczenia.centrum.settings.folders import FOLDERS, FolderSettings
from rozliczenia.centrum.settings.owner import CentrumSettings, UnreadableFile
from rozliczenia.quantity_engine import QuantityRules


def readable_folders(settings: CentrumSettings) -> FolderSettings:
    """Foldery; plik Folderów bez odczytu to odmowa o nim, a nie Rejestr zleceń i folder okresów niewskazane."""

    folders = settings.folders()
    if isinstance(folders, Unreadable):
        raise refusal.settings_file_unreadable(FOLDERS.name)
    return folders


def readable_quantity_rules(settings: CentrumSettings) -> QuantityRules:
    """Reguły ilości z Listą Urządzeń; plik pary bez odczytu to odmowa o nim, a nie reguły z Wydania."""

    rules = settings.quantity_rules().rules
    if isinstance(rules, UnreadableFile):
        raise refusal.settings_file_unreadable(rules.name)
    return rules


def readable_activity_legend(settings: CentrumSettings) -> ActivityLegend:
    """Legenda czynności; plik legendy bez odczytu to odmowa o nim, a nie legenda z Wydania."""

    legend = settings.counted_activity_legend()
    if isinstance(legend, UnreadableFile):
        raise refusal.settings_file_unreadable(legend.name)
    return legend
