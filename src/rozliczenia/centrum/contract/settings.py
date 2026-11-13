"""Kontrakt Ustawień Centrum: Rejestr zleceń, folder okresów, motyw, start razem z Windows i Historia Ustawień."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model


class NotSetPath(Model):
    """Ścieżka jeszcze niewskazana."""

    state: Literal["not_set"]


class MissingPath(Model):
    """Zapamiętana ścieżka, pod którą nie ma już pliku albo folderu."""

    state: Literal["missing"]
    path: str
    name: str


class InaccessiblePath(Model):
    """Zapamiętana ścieżka, której nie da się teraz odczytać (np. folder bez dostępu albo OneDrive, który nie działa)."""

    state: Literal["inaccessible"]
    path: str
    name: str


class UnreadablePath(Model):
    """Pliku Ustawień Centrum nie da się teraz przeczytać, więc nie wiadomo, jaką ścieżkę wskazano."""

    state: Literal["unreadable"]


class ReadyPath(Model):
    state: Literal["ready"]
    path: str
    name: str


PathSetting = Annotated[
    NotSetPath | MissingPath | InaccessiblePath | UnreadablePath | ReadyPath, Field(discriminator="state")
]


Theme = Literal["dark", "light"]


class AutostartSetting(Model):
    """Start Centrum razem z Windows: skrót w folderze Autostart jest (``on``) albo go nie ma (``off``), komputer nie ma
    Autostartu Windows (``unsupported``) albo folderu Autostart nie da się teraz sprawdzić (``unreadable``). ``reason``:
    zdanie dla taty, dlaczego przełącznika nie da się teraz zmienić; przy ``on`` i ``off`` ``None``."""

    state: Literal["on", "off", "unsupported", "unreadable"]
    reason: str | None


class SettingProblem(Model):
    """Złe ustawienie w pliku: pole w pliku (``rejestr_zlecen``, ``folder_okresow``, ``motyw``) albo ``None`` dla całego
    pliku i zdanie dla taty."""

    field: str | None
    message: str


class Settings(Model):
    """Ustawienia Centrum naraz. Przy złym pliku Folderów i motywu (``folders_problem``) ścieżki i motyw to ostatnie
    dobre wartości, a bez nich nie ustawiono i motyw domyślny."""

    order_register: PathSetting
    periods_directory: PathSetting
    theme: Theme
    folders_problem: SettingProblem | None
    autostart: AutostartSetting


class Choice(Model):
    """Ustawienia po natywnym oknie wyboru, zapisie sekcji, przełączniku albo cofnięciu: wybór zapisuje ścieżkę,
    anulowanie niczego nie zmienia. ``change``: id wiersza Historii Ustawień tej zmiany (do „Zapisano · Cofnij”);
    ``None``: bez zmiany i bez wiersza."""

    settings: Settings
    change: str | None = None


class ThemeChange(Model):
    theme: Theme


class AutostartChange(Model):
    """Przełącznik „Uruchamiaj Centrum razem z Windows”: ``True`` zakłada skrót w folderze Autostart, ``False`` go usuwa."""

    enabled: bool


class FoldersChange(Model):
    """Sekcja Foldery naraz: pełne ścieżki Rejestru zleceń i folderu okresów, ``None`` czyści ustawienie."""

    order_register: str | None
    periods_directory: str | None


class HistoryChange(Model):
    """Zmiana jednego klucza (``foldery.folder_okresow``): wartość przed i po, ``None``: nie ustawiono albo sekret."""

    key: str
    before: str | None
    after: str | None


HistorySource = Literal["tata", "outside"]
"""Skąd zmiana: zapis taty w Centrum (także cofnięcie) albo plik w ``config`` zmieniony poza Centrum."""


class HistoryRow(Model):
    """Wiersz Historii Ustawień. ``undoes``: id cofniętego wiersza; ``undoable``: ma „Cofnij”; ``refused``: zła treść
    spoza Centrum, której Centrum nie przyjęło, z powodem ``reason``; ``removed``: plik usunięty poza Centrum."""

    id: str
    at: datetime
    source: HistorySource
    undoes: str | None
    file: str
    section: str | None
    changes: list[HistoryChange]
    secret: bool
    undoable: bool
    refused: bool
    removed: bool
    reason: str | None


class SettingsHistory(Model):
    """Historia Ustawień od najnowszej zmiany i liczba linii pliku, których nie dało się przeczytać."""

    rows: list[HistoryRow]
    skipped: int
