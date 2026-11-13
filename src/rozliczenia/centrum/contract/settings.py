"""Kontrakt Ustawień Centrum: Rejestr zleceń, folder okresów, motyw, skrzynka raportów, Lista Wykonawców, start razem
z Windows i Historia Ustawień."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.quantity_rules import SentencePart
from rozliczenia.centrum.contract.settings_workers import SettingProblem, WorkerListSetting


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


class InboxSetting(Model):
    """Skrzynka raportów: adres (``None``: nie ustawiono) i to, czy plik ma hasło; samego hasła serwer nie wysyła nigdy."""

    address: str | None
    password: bool


class Settings(Model):
    """Ustawienia Centrum naraz. Przy złym pliku Folderów i motywu (``folders_problem``) ścieżki i motyw to ostatnie
    dobre wartości, a bez nich nie ustawiono i motyw domyślny. Przy złym pliku skrzynki (``inbox_problem``) skrzynka
    jest bez adresu i hasła. ``periods_all_years``: folder okresów to korzeń układu folderów taty, z którego Centrum
    widzi Foldery okresu wszystkich lat (``Załączniki``)."""

    order_register: PathSetting
    periods_directory: PathSetting
    periods_all_years: bool
    theme: Theme
    folders_problem: SettingProblem | None
    workers: WorkerListSetting
    inbox: InboxSetting
    inbox_problem: SettingProblem | None
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


class InboxPasswordChange(Model):
    """Nowe hasło aplikacji skrzynki raportów, tak jak je wpisał tata (spacje Google pomija zapis)."""

    password: str


InboxLogin = Literal["accepted", "rejected", "no_network"]
"""Wynik próby logowania po zapisie hasła: skrzynka przyjęła hasło, odrzuciła je albo nie odpowiedziała."""


class InboxPasswordSaved(Choice):
    """Ustawienia po zapisie hasła skrzynki z wynikiem jednej próby logowania; wiersz Historii nie ma „Cofnij”."""

    login: InboxLogin


class FoldersChange(Model):
    """Sekcja Foldery naraz: pełne ścieżki Rejestru zleceń i folderu okresów, ``None`` czyści ustawienie."""

    order_register: str | None
    periods_directory: str | None


class HistoryChange(Model):
    """Zmiana jednego klucza (``foldery.folder_okresow``): wartość przed i po, ``None``: nie ustawiono albo sekret."""

    key: str
    before: str | None
    after: str | None


class HistoryRuleChange(Model):
    """Zmiana reguły ilości (klucz ``reguly.<id>``) jako zdanie „jeśli … to …” przed i po, zamiast zapisu z pliku;
    ``None``: reguły nie było."""

    key: str
    before: list[SentencePart] | None
    after: list[SentencePart] | None


HistorySource = Literal["tata", "outside", "release"]
"""Skąd zmiana: zapis taty w Centrum (także cofnięcie), plik w ``config`` zmieniony poza Centrum albo zmiana z Wydania."""


class HistoryRelease(Model):
    """Zmiana z Wydania: numer Wydania (``0.9.0``) i skrót commitu narzędzia (``None``: nie wiadomo) oraz id zmiany."""

    version: str | None
    commit: str | None
    change: str


class HistoryRow(Model):
    """Wiersz Historii Ustawień. ``release``: Wydanie zmiany ze źródłem ``release``; ``undoes``: id cofniętego wiersza;
    ``undoable``: ma „Cofnij”; ``refused``: zła treść spoza Centrum albo zmiana z Wydania, których Centrum nie przyjęło,
    z powodem ``reason``; ``removed``: plik usunięty poza Centrum."""

    id: str
    at: datetime
    source: HistorySource
    release: HistoryRelease | None
    undoes: str | None
    file: str
    section: str | None
    changes: list[HistoryChange]
    secret: bool
    undoable: bool
    refused: bool
    removed: bool
    reason: str | None
    rules: list[HistoryRuleChange]
    """Zmienione reguły ilości wiersza jako zdania, po jednej na klucz ``reguly.<id>``; pusta w wierszu innej sekcji."""


class SettingsHistory(Model):
    """Historia Ustawień od najnowszej zmiany i liczba linii pliku, których nie dało się przeczytać."""

    rows: list[HistoryRow]
    skipped: int
