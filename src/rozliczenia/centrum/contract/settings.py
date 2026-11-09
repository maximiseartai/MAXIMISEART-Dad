"""Kontrakt Ustawień taty: Rejestr zleceń, folder okresów i motyw."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model


class NotSetPath(Model):
    """Ścieżka jeszcze niewskazana albo plik ustawień nieczytelny."""

    state: Literal["not_set"]


class MissingPath(Model):
    """Zapamiętana ścieżka, pod którą nie ma już pliku albo folderu."""

    state: Literal["missing"]
    path: str
    name: str


class ReadyPath(Model):
    state: Literal["ready"]
    path: str
    name: str


PathSetting = Annotated[NotSetPath | MissingPath | ReadyPath, Field(discriminator="state")]


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
