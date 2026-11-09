"""Kontrakt Ustawień taty: Rejestr zleceń, folder okresów i motyw."""

from __future__ import annotations

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
    """Pliku Ustawień taty nie da się teraz przeczytać, więc nie wiadomo, jaką ścieżkę wskazano."""

    state: Literal["unreadable"]


class ReadyPath(Model):
    state: Literal["ready"]
    path: str
    name: str


PathSetting = Annotated[
    NotSetPath | MissingPath | InaccessiblePath | UnreadablePath | ReadyPath, Field(discriminator="state")
]


Theme = Literal["dark", "light"]


class Settings(Model):
    order_register: PathSetting
    periods_directory: PathSetting
    theme: Theme


class Choice(Model):
    """Ustawienia po natywnym oknie wyboru: wybór zapisuje ścieżkę, anulowanie niczego nie zmienia."""

    settings: Settings


class ThemeChange(Model):
    theme: Theme
