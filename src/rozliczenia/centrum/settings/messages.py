"""Zdania Ustawień Centrum dla taty: złe ustawienie w pliku i zła wartość zmiany, każde z próbką w
``tests/expected/komunikaty.txt``. Odmowa API niesie je przez ``refusal.setting_refused``."""

from __future__ import annotations

from typing import Final, Literal

from rozliczenia.centrum.settings.files import FieldPath

SAVE_AGAIN: Final = "Zapisz Ustawienia jeszcze raz."
"""Naprawa złego pliku, który zapis taty w oknie Ustawień pisze od nowa z ostatniej dobrej wartości."""
MAKS_FIXES: Final = "Poprawia go Maks."
"""Naprawa złego pliku Listy Wykonawców: zła treść bierze się z ręcznej zmiany Maksa w ``config``, a zmiana taty w
sekcji Wykonawcy zapisałaby plik od nowa z ostatniej dobrej listy (zła treść trafia wtedy do ``odrzucone``)."""


def not_text(file: str, repair: str = SAVE_AGAIN) -> str:
    return f"Plik {file} w folderze config nie jest tekstem UTF-8. {repair}"


def damaged(file: str, repair: str = SAVE_AGAIN) -> str:
    return f"Plik {file} w folderze config ma uszkodzoną treść. {repair}"


def other_schema(file: str, repair: str = SAVE_AGAIN) -> str:
    return f"Plik {file} w folderze config zapisała inna wersja narzędzia. {repair}"


def unknown_key(file: str, position: int, repair: str = SAVE_AGAIN) -> str:
    """Nieznane pole na górze pliku po numerze, nie po nazwie: nazwa to tekst z pliku, a zdanie trafia do Zgłoszenia."""

    return f"Plik {file} w folderze config ma nieznane pole ({position}. od góry pliku). {repair}"


def worker_unknown_key(file: str, worker: int, position: int) -> str:
    """Nieznane pole we wpisie Wykonawcy po numerach: stary kształt wpisu (``login: Nazwa``) ma login w miejscu pola."""

    return (
        f"Plik {file} w folderze config ma nieznane pole we wpisie {worker}. Wykonawcy ({position}. pole wpisu). "
        f"{MAKS_FIXES}"
    )


def register_path() -> str:
    return "Rejestr zleceń to plik Excel .xlsx podany pełną ścieżką. Wybierz go oknem wyboru."


def periods_directory_path() -> str:
    return "Folder okresów trzeba podać pełną ścieżką. Wybierz go oknem wyboru."


def unknown_theme() -> str:
    return "Motyw może być tylko ciemny albo jasny."


def bad_field(file: str, place: FieldPath, repair: str) -> str:
    return f"Plik {file} w folderze config ma złą wartość pola {place.text}. {repair}"


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


def worker_unknown() -> str:
    return "Tego Wykonawcy nie ma już na Liście Wykonawców. Zamknij formularz i sprawdź listę."


def worker_list_changed() -> str:
    return "Lista Wykonawców zmieniła się w trakcie sprawdzania okresów. Spróbuj jeszcze raz."


def worker_rename_old_files(periods: tuple[str, ...]) -> str:
    """Ostrzeżenie przed zmianą nazwy: ``periods`` to tokeny okresów (od najnowszego) z Rozliczeniem pracownika o starej
    nazwie; zdanie podaje ich liczbę i najnowszy."""

    count = len(periods)
    where = f"w okresie {periods[0]}" if count == 1 else f"w {count} okresach, ostatnio {periods[0]}"
    return (
        f"Rozliczenie pracownika ze starą nazwą jest już {where}. Ten plik zostanie ze starą nazwą, a nowa będzie w "
        "plikach następnych Przebiegów rozliczeń."
    )


def worker_suggestions_not_set() -> str:
    """Sekcja Wykonawcy bez podpowiedzi nowych loginów, bo tata nie wskazał Rejestru zleceń."""

    return "Wskaż Rejestr zleceń w sekcji Foldery, a Centrum podpowie loginy nowych Wykonawców z ostatnich zleceń."


def worker_suggestions_unreadable() -> str:
    """Sekcja Wykonawcy bez podpowiedzi nowych loginów, bo Rejestru zleceń nie da się teraz przeczytać (nie ma go, brak
    dostępu, nie jest skoroszytem, wierszy nie da się rozdzielić); stan pliku pokazuje sekcja Foldery. Rejestr bez
    obszaru wklejania ma zamiast tego zdanie Komunikatu procesów (``worker_suggestions``)."""

    return (
        "Nie da się teraz przeczytać Rejestru zleceń, więc Centrum nie podpowie loginów nowych Wykonawców. Sprawdź "
        "Rejestr w sekcji Foldery."
    )


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


def worker_list_waiting() -> str:
    return (
        "Listy Wykonawców jeszcze nie ma: przeniesienie starych plików Wykonawców czeka na dostęp do pliku w folderze "
        "config i spróbuje znowu przy następnym starcie Centrum."
    )


def addresses_not_moved(old_file: str, reason: str) -> str:
    return (
        f"Adresów Wykonawców nie przeniesiono ze starego pliku {old_file} w folderze config: {reason}. Dopisz je "
        "Wykonawcom w Ustawieniach."
    )


def reminders_time() -> str:
    return "Wpisz godzinę jako GG:MM, np. 08:00."


def reminders_empty_morning() -> str:
    return "Poranna pora musi kończyć się później, niż się zaczyna."


def reminders_empty_evening() -> str:
    return "Wieczorna pora musi kończyć się później, niż się zaczyna."


def reminders_overlap() -> str:
    return "Pory zachodzą na siebie: wieczorna może zacząć się dopiero wtedy, gdy kończy się poranna."


def reminders_empty_text() -> str:
    return "Wpisz pierwsze zdanie przypomnienia."


def reminders_unknown_field() -> str:
    return "W treści przypomnienia może stać tylko pole {dzień}, bez innych nawiasów klamrowych."


def reminders_without_since() -> str:
    return "Włączone przypomnienia muszą mieć dzień wdrożenia. Wyłącz je i włącz jeszcze raz."


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


def rule_without_action() -> str:
    """Reguła z edytora Reguł ilości bez działania."""

    return "Wybierz, co reguła ma zrobić: wpisz w kolumnę, nic nie wpisuj albo zostaw kolumnę pustą."


def rule_hour() -> str:
    """Godzina warunku DATA z edytora Reguł ilości nie jest godziną z minutą."""

    return "Godzinę wpisz jako GG:MM, np. 17:00."


def component_name_empty() -> str:
    """Składnik z sekcji Urządzenia bez nazwy (pierwszego zapisu)."""

    return "Wpisz nazwę składnika tak, jak stoi w URZĄDZENIA."


def spelling_with_star(spelling: str) -> str:
    """Zapis składnika z gwiazdką: Reguły ilości czytają ją w ``URZĄDZENIA`` jako krotność."""

    return f"Zapis „{spelling}” nie może mieć gwiazdki: w URZĄDZENIA gwiazdka to liczba sztuk, np. 2*fut."


def spelling_taken(spelling: str, component: str) -> str:
    """Zapis, który ma już inny składnik; ``component``: jego nazwa, jak w sekcji Urządzenia."""

    return f"Zapis „{spelling}” ma już składnik „{component}”. Jeden zapis należy do jednego składnika."


def component_used_by_rule(component: str, rule: str) -> str:
    """Usunięcie składnika, którego potrzebuje reguła; ``rule``: jej zdanie „jeśli … to …”."""

    return f"Składnika „{component}” potrzebuje reguła: {rule} Najpierw zmień albo usuń tę regułę w sekcji Reguły ilości."


def rule_needs_component(component: str, rule: str) -> str:
    """Reguła, której składnika nie ma na Liście Urządzeń (np. „Cofnij” jej usunięcia po usunięciu składnika);
    ``component``: jego nazwa, jak ostatnio na liście, ``rule``: zdanie reguły „jeśli … to …”."""

    return (
        f"Reguła potrzebuje składnika „{component}”, którego nie ma na Liście Urządzeń: {rule} Najpierw dodaj ten składnik "
        "w sekcji Urządzenia."
    )


def needed_by_release_rules(component: str) -> str:
    """Lista Urządzeń taty bez składnika, którego potrzebują Reguły ilości z Wydania (tata nie ma pliku reguł);
    ``component``: jego nazwa z Listy Urządzeń z Wydania."""

    return (
        f"Reguły ilości z Wydania potrzebują składnika „{component}”, którego nie ma na Liście Urządzeń, więc Centrum "
        "bierze go z Listy Urządzeń z Wydania. Żeby został na liście, zapisz go: ołówek przy nim, potem „Zapisz”."
    )


TakenAction = Literal["zapis", "skladnik", "nazwa"]
"""Jak tata zwalnia zapis składnika z Wydania: usuwa go ze składnika z innymi zapisami, usuwa cały składnik albo zmienia
jego nazwę."""


def release_component_taken(component: str, owner: str, how: TakenAction) -> str:
    """Składnik z Listy Urządzeń z Wydania, którego potrzebują Reguły ilości z Wydania, a którego każdy zapis ma składnik z
    listy taty, więc Centrum liczy bez niego; ``component``: jego pierwszy zapis, który ma składnik ``owner``."""

    return (
        f"Reguły ilości z Wydania mają składnik „{component}”, ale ten zapis ma już składnik „{owner}” z listy, więc "
        f"Centrum liczy bez niego. Żeby liczyło z nim, {_freed(component, owner, how)}."
    )


def rules_wait_for_release_component(component: str, owner: str, how: TakenAction) -> str:
    """Sekcja Reguły ilości i odmowa pierwszego zapisu reguł taty w miejsce Reguł ilości z Wydania, które mają składnik
    z Listy Urządzeń z Wydania, a każdy jego zapis ma składnik ``owner`` z listy taty: plik reguł taty musi pasować do
    jego listy, więc zapisze się dopiero, gdy tata zwolni zapis ``component`` w sekcji Urządzenia."""

    return (
        f"Reguły ilości z Wydania mają składnik „{component}”, ale ten zapis ma już składnik „{owner}” z listy, więc "
        "Centrum liczy bez niego, a zmiana reguł zapisze się dopiero, gdy go zwolnisz: w sekcji Urządzenia "
        f"{_freed(component, owner, how)}."
    )


def _freed(component: str, owner: str, how: TakenAction) -> str:
    return {
        "zapis": f"usuń zapis „{component}” ze składnika „{owner}”: ołówek przy nim, potem „Zapisz”",
        "skladnik": f"usuń składnik „{owner}”: ołówek przy nim, potem „Usuń składnik”",
        "nazwa": f"zmień nazwę składnika „{owner}”: ołówek przy nim, potem „Zapisz”",
    }[how]


def needed_by_rules(file: str, component: str) -> str:
    """Lista Urządzeń bez składnika, którego potrzebują Reguły ilości; ``component``: jego nazwa, jak w sekcji Urządzenia."""

    return (
        f"Plik {file} w folderze config nie ma składnika „{component}”, którego potrzebują Reguły ilości, "
        "więc Centrum liczy ostatnią dobrą Listą Urządzeń."
    )


def unavailable(file: str) -> str:
    return f"Pliku {file} w folderze config nie da się teraz przeczytać. Do tego czasu Centrum bierze jego treść z Wydania."
