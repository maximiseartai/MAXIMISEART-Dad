"""Zdania Ustawień Centrum dla taty: złe ustawienie w pliku i zła wartość zmiany, każde z próbką w
``tests/expected/komunikaty.txt``. Odmowa API niesie je przez ``refusal.setting_refused``."""

from __future__ import annotations

from rozliczenia.centrum.settings.files import FieldPath


def not_text(file: str) -> str:
    return f"Plik {file} w folderze config nie jest tekstem UTF-8. Zapisz Ustawienia jeszcze raz."


def damaged(file: str) -> str:
    return f"Plik {file} w folderze config ma uszkodzoną treść. Zapisz Ustawienia jeszcze raz."


def other_schema(file: str) -> str:
    return f"Plik {file} w folderze config zapisała inna wersja narzędzia. Zapisz Ustawienia jeszcze raz."


def unknown_key(file: str, position: int) -> str:
    """Nieznane pole na górze pliku po numerze, nie po nazwie: nazwa to tekst z pliku, a zdanie trafia do Zgłoszenia."""

    return f"Plik {file} w folderze config ma nieznane pole ({position}. od góry pliku). Zapisz Ustawienia jeszcze raz."


def worker_unknown_key(file: str, worker: int, position: int) -> str:
    """Nieznane pole we wpisie Wykonawcy po numerach: stary kształt wpisu (``login: Nazwa``) ma login w miejscu pola."""

    return (
        f"Plik {file} w folderze config ma nieznane pole we wpisie {worker}. Wykonawcy ({position}. pole wpisu). Zapisz "
        "Ustawienia jeszcze raz."
    )


def register_path() -> str:
    return "Rejestr zleceń to plik Excel .xlsx podany pełną ścieżką. Wybierz go oknem wyboru."


def periods_directory_path() -> str:
    return "Folder okresów trzeba podać pełną ścieżką. Wybierz go oknem wyboru."


def unknown_theme() -> str:
    return "Motyw może być tylko ciemny albo jasny."


def bad_field(file: str, place: FieldPath) -> str:
    return f"Plik {file} w folderze config ma złą wartość pola {place.text}. Zapisz Ustawienia jeszcze raz."


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


def worker_list_unreadable() -> str:
    return "Nie można teraz odczytać Listy Wykonawców. Plik może być zajęty przez inny program. Spróbuj za chwilę."


def worker_list_not_created() -> str:
    return (
        "Listy Wykonawców nie ma: nie udało się jej utworzyć ze starych plików Wykonawców w folderze config. Powód jest "
        "w Historii."
    )


def addresses_not_moved(old_file: str, reason: str) -> str:
    return (
        f"Adresów Wykonawców nie przeniesiono ze starego pliku {old_file} w folderze config: {reason}. Dopisz je "
        "Wykonawcom w Ustawieniach."
    )
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


def needed_by_rules(file: str, component: str) -> str:
    """Lista Urządzeń bez składnika, którego potrzebują Reguły ilości; ``component``: jego nazwa, jak w sekcji Urządzenia."""

    return (
        f"Plik {file} w folderze config nie ma składnika „{component}”, którego potrzebują Reguły ilości, "
        "więc Centrum liczy ostatnią dobrą Listą Urządzeń."
    )


def unavailable(file: str) -> str:
    return f"Pliku {file} w folderze config nie da się teraz przeczytać. Do tego czasu Centrum bierze jego treść z Wydania."
