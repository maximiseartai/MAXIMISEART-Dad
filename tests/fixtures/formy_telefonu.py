"""Tabela form telefonu reguły danych (ADR 0025, „Telefon: formy i znane granice”): jak telefon albo liczba podobna do
telefonu stoi w komórce pliku taty i w wolnym tekście, i co z niej wychodzi do pliku Logów i Skrzynki Zgłoszeń.

Wartość tekstowa to komórka z tekstem albo wolny tekst (strażnik ``ForbiddenValues.guard``), a liczba to komórka, którą
Excel trzyma jako liczbę (strażnik liczby ``ForbiddenValues.guard_number``): format General gubi „+” i zera z przodu,
więc wpis ``+48600123456`` i ``0048600123456`` to liczba ``48600123456``, a liczbę zapisaną w pliku w notacji E
(``4.8600123456E10``) openpyxl czyta jako ułamek. ``masked``: tekst po strażniku albo ``None``, gdy wartość wychodzi
bez zmian. Liczba policzona przez narzędzie (``COMPUTED``) nie przechodzi przez strażnika liczby, bo nie stoi w polu
z wartościami z komórek (``READ_VALUES`` w ``run_logs``). Wartości są syntetyczne, a „0 w plikach taty” to wynik skanu
kopii prawdziwych plików w PR #863.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhoneForm:
    """Forma z tabeli: ``form`` nazywa ją w identyfikatorze testu, ``why`` mówi, czemu wynik jest taki."""

    form: str
    value: str | int | float
    masked: str | None
    why: str


PHONE = "[telefon]"

MASKED: tuple[PhoneForm, ...] = (
    PhoneForm("9 cyfr bez separatorów", "600123456", PHONE, "komórkowy 3-3-3"),
    PhoneForm("3-3-3 ze spacjami", "600 123 456", PHONE, "komórkowy 3-3-3"),
    PhoneForm("3-3-3 z kreskami", "600-123-456", PHONE, "komórkowy 3-3-3"),
    PhoneForm("+48 ze spacjami", "+48 600 123 456", PHONE, "numer kierunkowy z +"),
    PhoneForm("+48 bez separatorów", "+48600123456", PHONE, "numer kierunkowy z +"),
    PhoneForm("0048 z kreskami", "0048 600-123-456", PHONE, "numer kierunkowy z 00"),
    PhoneForm("0048 bez separatorów", "0048600123456", PHONE, "numer kierunkowy z 00"),
    PhoneForm("48 ze spacjami", "48 600 123 456", PHONE, "numer kierunkowy bez + i 00"),
    PhoneForm("48 bez separatorów", "48600123456", PHONE, "numer kierunkowy bez + i 00, jak liczba z komórki"),
    PhoneForm("48 z kreskami", "48-600-123-456", PHONE, "numer kierunkowy bez + i 00"),
    PhoneForm("stacjonarny 2-3-2-2", "12 345 67 89", PHONE, "stacjonarny 2-3-2-2"),
    PhoneForm("stacjonarny 2-3-2-2 z kreskami", "12-345-67-89", PHONE, "stacjonarny 2-3-2-2"),
    PhoneForm("stacjonarny z +48", "+48 12 345 67 89", PHONE, "stacjonarny z numerem kierunkowym"),
    PhoneForm("stacjonarny z 48", "48 12 345 67 89", PHONE, "stacjonarny z numerem kierunkowym bez +"),
    PhoneForm("+48 w nawiasie", "(+48) 600 123 456", f"(+48) {PHONE}", "9 cyfr numeru maskowane, kierunkowy zostaje"),
    PhoneForm("liczba 9 cyfr", 600123456, PHONE, "telefon wpisany bez innego tekstu"),
    PhoneForm("liczba 9 cyfr jako ułamek", 600123456.0, PHONE, "Excel zapisał liczbę całkowitą jako ułamek"),
    PhoneForm("liczba 11 cyfr od 48", 48600123456, PHONE, "+48 albo 0048 zgubione przez format General"),
    PhoneForm("ułamek 11 cyfr od 48", 48600123456.0, PHONE, "+48 albo 0048 zgubione, liczba jako ułamek"),
    PhoneForm("stacjonarny jako liczba 11 cyfr od 48", 48123456789, PHONE, "+48 zgubione przez format General"),
    PhoneForm("liczba 9 cyfr w notacji E", float("6.00123456E8"), PHONE, "openpyxl czyta notację E jako ułamek"),
    PhoneForm("liczba 11 cyfr od 48 w notacji E", float("4.8600123456E10"), PHONE, "notacja E i zgubione +48"),
)
"""Telefon, który strażnik maskuje."""

KNOWN_LIMITS: tuple[PhoneForm, ...] = (
    PhoneForm("z kropkami", "600.123.456", None, "0 w plikach taty; grupy cyfr z kropkami to też daty i adresy IP"),
    PhoneForm("komórkowy w nawiasie", "(600) 123 456", None, "0 w plikach taty"),
    PhoneForm("stacjonarny z kierunkowym w nawiasie", "(12) 345 67 89", None, "0 w plikach taty"),
    PhoneForm("komórkowy 3-2-2-2", "600 12 34 56", None, "0 w plikach taty"),
    PhoneForm("sklejony z literami", "tel600123456", None, "jedno słowo, jak numer urządzenia w opisie technika"),
)
"""Znane granice: telefon, którego strażnik nie maskuje."""

OVER_MASKED: tuple[PhoneForm, ...] = (
    PhoneForm("NUMER ZL. bez # z 9 cyframi", 123456789, PHONE, "bez # ma kształt telefonu; dziś NUMER ZL. ma 8 cyfr"),
    PhoneForm("numer seryjny 11 cyfr od 48", "SN 48123456789", f"SN {PHONE}", "kształt +48 i 9 cyfr; 0 w plikach taty"),
)
"""Znane granice w drugą stronę: wartość, która nie jest telefonem, a strażnik ją maskuje."""

NOT_PHONES: tuple[PhoneForm, ...] = (
    PhoneForm("ilość", 2, None, "ilość pozycji"),
    PhoneForm("ilość ułamkowa", 0.5, None, "ilość pozycji"),
    PhoneForm("kwota", 1234.56, None, "kwota zlecenia"),
    PhoneForm("kwota w tekście", "1 234,56 zł", None, "kwota zlecenia"),
    PhoneForm("NUMER ZL. 8 cyfr", "#12345678", None, "cyfry zaraz po # to NUMER ZL."),
    PhoneForm("NUMER ZL. 9 cyfr", "#123456789", None, "cyfry zaraz po # to NUMER ZL."),
    PhoneForm("liczba 8 cyfr", 12345678, None, "za krótka na telefon"),
    PhoneForm("liczba 10 cyfr od 48", 4801234567, None, "za krótka na 48 i 9 cyfr; numer Orange zna pamięć"),
    PhoneForm("liczba 11 cyfr nie od 48", 14123456789, None, "bez numeru kierunkowego Polski"),
    PhoneForm("liczba 11 cyfr od 47", 47600123456, None, "numer kierunkowy innego kraju niż 48, tuż obok 48"),
    PhoneForm("liczba 12 cyfr od 48", 486001234567, None, "za długa na 48 i 9 cyfr"),
    PhoneForm("ułamek z 9 cyframi po przecinku", 0.123456789, None, "telefon w komórce nie ma części ułamkowej"),
    PhoneForm("ułamek policzony przez formułę", 0.12345678901234568, None, "wynik formuły Excela"),
    PhoneForm("duża liczba w notacji E", 1e20, None, "21 cyfr"),
    PhoneForm("data", "05.11.2026", None, "data"),
    PhoneForm("data z godziną", "05.11.2026 8:30", None, "data i godzina to 9 cyfr z separatorami"),
    PhoneForm("data ISO", "2026-11-05", None, "data"),
    PhoneForm("data Excela jako liczba", 46331, None, "numer dnia daty"),
)
"""Wartość, która nie jest telefonem i wychodzi bez zmian."""

COMPUTED: tuple[PhoneForm, ...] = (
    PhoneForm("numer wiersza", 600123456, None, "policzyło narzędzie, poza READ_VALUES"),
    PhoneForm("rozmiar pliku", 48600123456, None, "policzyło narzędzie, poza READ_VALUES"),
)
"""Liczba policzona przez narzędzie w kształcie telefonu, która wychodzi bez zmian."""

CELL_FORMS: tuple[PhoneForm, ...] = (*MASKED, *KNOWN_LIMITS, *OVER_MASKED, *NOT_PHONES)
"""Każda forma wartości z komórki albo wolnego tekstu, którą sprawdza strażnik."""
