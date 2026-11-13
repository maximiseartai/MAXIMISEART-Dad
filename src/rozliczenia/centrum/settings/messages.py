"""Zdania Ustawień Centrum dla taty: złe ustawienie w pliku i zła wartość zmiany, każde z próbką w
``tests/expected/komunikaty.txt``. Odmowa API niesie je przez ``refusal.setting_refused``."""

from __future__ import annotations


def not_text(file: str) -> str:
    return f"Plik {file} w folderze config nie jest tekstem UTF-8. Zapisz Ustawienia jeszcze raz."


def damaged(file: str) -> str:
    return f"Plik {file} w folderze config ma uszkodzoną treść. Zapisz Ustawienia jeszcze raz."


def other_schema(file: str) -> str:
    return f"Plik {file} w folderze config zapisała inna wersja narzędzia. Zapisz Ustawienia jeszcze raz."


def unknown_key(file: str, key: str) -> str:
    return f"Plik {file} w folderze config ma nieznane pole {key}. Zapisz Ustawienia jeszcze raz."


def register_path() -> str:
    return "Rejestr zleceń to plik Excel .xlsx podany pełną ścieżką. Wybierz go oknem wyboru."


def periods_directory_path() -> str:
    return "Folder okresów trzeba podać pełną ścieżką. Wybierz go oknem wyboru."


def unknown_theme() -> str:
    return "Motyw może być tylko ciemny albo jasny."


def autostart_unsupported() -> str:
    return "Start razem z Windows działa tylko na komputerze z Windows."


def autostart_unreadable() -> str:
    return "Nie da się teraz sprawdzić folderu Autostart. Odśwież okno za chwilę."
