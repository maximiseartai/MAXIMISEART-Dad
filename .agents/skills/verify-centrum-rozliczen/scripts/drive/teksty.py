"""Texts of Centrum's screen that more than one feature of the drive checks, each written once, as Dad reads it."""

from __future__ import annotations

import re

# Diagnoza: no cause on Dad's computer, a missing Wzorzec, and the update it offers besides (Diagnoza, Aktualność,
# Zgłoszenie).
NOT_FOUND = "Nie znalazłem przyczyny na tym komputerze."
TEMPLATE_MISSING = "Nie znaleziono wzorca, z którego powstają pliki okresu."
PROPOSAL = "Jest też nowsza wersja narzędzia."
FILES_UNCHANGED = "Nic nie zapisano, Twoje pliki są bez zmian."
# The one element of Uwaga taty, Zgłoszenie and Powiadomienia when the Token do Zgłoszeń is missing or refused (Q17).
FOR_KEY = "Token do Zgłoszeń nie działa. Skontaktuj się z Maksem."
# Aktualizacja narzędzia.
UPDATE_BUTTON = "Zaktualizuj narzędzie"
UP_TO_DATE = "Masz najnowszą wersję."
FETCHING = "Pobieranie nowej wersji…"
# The header: the bell with something new and Uwaga taty's button.
BELL_FRESH = "Powiadomienia, są nowe"
WRITE = "Napisz do Maksa"
# What Dad could read about the Logi: the word in any of its cases, or their folder.
ABOUT_LOGS = re.compile(r"\bLog(i|ów|ach|ami)\b|uruchomienia/")
