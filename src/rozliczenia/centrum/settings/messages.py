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


def bad_field(file: str, key: str) -> str:
    return f"Plik {file} w folderze config ma złą wartość pola {key}. Zapisz Ustawienia jeszcze raz."


def worker_without_login() -> str:
    return "Każdy Wykonawca musi mieć co najmniej jeden login z kolumny WYKONAWCA."


def worker_login_empty() -> str:
    return "Login Wykonawcy nie może być pusty. Wpisz go tak, jak w kolumnie WYKONAWCA."


def worker_login_repeated() -> str:
    return "Ten login jest już na Liście Wykonawców. Jeden login należy do jednego Wykonawcy."


def worker_name_empty() -> str:
    return "Wpisz nazwę Wykonawcy, taką jak w nazwie jego Rozliczenia pracownika."


def worker_name_invalid() -> str:
    return (
        'Nazwa Wykonawcy jest częścią nazwy pliku, więc nie może mieć znaków < > : " / \\ | ? * ani kropki albo spacji '
        "na końcu."
    )


def worker_name_too_long() -> str:
    return "Nazwa Wykonawcy jest za długa na nazwę pliku Rozliczenia pracownika. Skróć ją."


def worker_same_file() -> str:
    return "Dwóch Wykonawców ma nazwę, która daje ten sam plik Rozliczenia pracownika. Nazwy muszą się różnić."


def worker_address_invalid() -> str:
    return "Adres Wykonawcy to jeden adres e-mail w postaci nazwa@domena."


def worker_address_repeated() -> str:
    return "Ten adres jest już na Liście Wykonawców. Jeden adres należy do jednego Wykonawcy."


def workers_not_moved(old_file: str, reason: str) -> str:
    return (
        f"Listy Wykonawców nie utworzono ze starego pliku {old_file} w folderze config: {reason}. Dodaj Wykonawców w "
        "Ustawieniach."
    )


def addresses_not_moved(old_file: str, reason: str) -> str:
    return (
        f"Adresów Wykonawców nie przeniesiono ze starego pliku {old_file} w folderze config: {reason}. Dopisz je "
        "Wykonawcom w Ustawieniach."
    )
