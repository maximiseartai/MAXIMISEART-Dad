from __future__ import annotations

from typing import Final

_INBOX_SECTION: Final = "Ustawieniach, w sekcji Skrzynka raportów"


def mailbox_without_access() -> str:
    return f"Centrum nie ma hasła do skrzynki raportów: wpisz je w {_INBOX_SECTION}. Do tego czasu wysyłka nie działa."


def mailbox_password_rejected() -> str:
    return f"Skrzynka raportów odrzuciła hasło: wpisz nowe w {_INBOX_SECTION}. Do tego czasu wysyłka nie działa."


def mailbox_unreachable() -> str:
    return "Nie ma połączenia ze skrzynką raportów, więc nie wiadomo, co już poszło. Sprawdź internet i odśwież stronę."


def sent_unread() -> str:
    return "Nie dało się sprawdzić w skrzynce, czy to rozliczenie już poszło, więc Centrum go nie wysłało. Wyślij jeszcze raz."


def file_open_in_excel() -> str:
    return "Plik jest otwarty w Excelu. Zapisz go, zamknij i wyślij jeszcze raz."


def file_unreadable() -> str:
    return "Pliku nie dało się przeczytać. Sprawdź, czy jest w Folderze rozliczeń pracowników, i wyślij jeszcze raz."


def password_rejected() -> str:
    return f"Skrzynka raportów odrzuciła hasło: wpisz nowe w {_INBOX_SECTION} i wyślij jeszcze raz."


def no_network() -> str:
    return "Nie ma połączenia ze skrzynką raportów. Sprawdź internet i wyślij jeszcze raz."


def mail_refused() -> str:
    return "Gmail nie przyjął maila. Sprawdź adresy Wykonawcy w Ustawieniach, w sekcji Wykonawcy, i wyślij jeszcze raz."


def worker_list_unusable() -> str:
    return "Listy Wykonawców nie da się teraz przeczytać, więc nie wiadomo, do kogo wysłać rozliczenia. Sprawdź ją w Ustawieniach."


def periods_directory_not_set() -> str:
    return "Wskaż folder okresów w Ustawieniach, w sekcji Foldery."


def periods_directory_missing() -> str:
    return "Folderu okresów nie ma już na dysku. Wskaż go jeszcze raz w Ustawieniach, w sekcji Foldery."
