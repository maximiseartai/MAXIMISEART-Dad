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


def inbox_not_text() -> str:
    return "Plik skrzynka-raportow.txt w folderze config nie jest tekstem. Poproś Maksa o nowy plik."


def inbox_address() -> str:
    return "Adres skrzynki raportów w pliku skrzynka-raportow.txt jest zły. Poprawia go Maks."


def inbox_no_address() -> str:
    return "Skrzynka raportów nie ma jeszcze adresu. Adres wpisuje Maks."


def inbox_password_text() -> str:
    return "Hasło aplikacji ma tylko litery i cyfry, bez polskich znaków."


def inbox_password_empty() -> str:
    return "Wpisz nowe hasło aplikacji."
def quantity_rules_problem(file: str, problem: str) -> str:
    """Zły plik Reguł ilości albo Listy Urządzeń: ``problem`` to zdanie silnika Reguł ilości o pierwszym złym polu."""

    return f"Plik {file} w folderze config: {problem}"


def needed_by_rules(file: str, problem: str) -> str:
    """Lista Urządzeń bez składnika, którego potrzebują Reguły ilości: ``problem`` to zdanie silnika o tym składniku."""

    return f"Plik {file} w folderze config: {problem} Potrzebują go Reguły ilości."


def unavailable(file: str) -> str:
    return f"Pliku {file} w folderze config nie da się teraz przeczytać. Do tego czasu Centrum bierze jego treść z Wydania."
