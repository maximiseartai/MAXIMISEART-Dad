"""Kontrakt sekcji Przypomnienia o raporcie w Ustawieniach Centrum: czy idą, pory, godzina pierwszego przypomnienia,
pierwsze zdanie treści i stopka taty, ich zapis i podgląd maila bez wysyłki."""

from __future__ import annotations

from datetime import date
from typing import Literal

from rozliczenia.centrum.contract.common import Model
from rozliczenia.centrum.contract.settings_workers import SettingProblem


class ReminderRange(Model):
    """Pora przypomnień od ``start`` do ``end`` (``GG:MM``), bez końca pory: przy 8:00–17:00 o 17:00 już nie idą."""

    start: str
    end: str


class RemindersForm(Model):
    """Formularz sekcji Przypomnienia: pory, godzina pierwszego przypomnienia następnego dnia, pierwsze zdanie z polem
    ``{dzień}`` i stopka (pusta: bez stopki). Godziny sprawdza serwer, a złą wartość odrzuca zdaniem przy polu."""

    morning: ReminderRange
    evening: ReminderRange
    first: str
    text: str
    footer: str


class RemindersSetting(RemindersForm):
    """Przypomnienia o raporcie: ``good``, ``bad`` (zły plik: ``problem`` i ostatnie dobre wartości, a bez nich domyślne)
    albo ``unreadable`` (system nie daje teraz czytać pliku, wartości domyślne). ``enabled``: przypomnienia idą;
    ``since``: dzień wdrożenia, od którego liczą się dni (``None``: jeszcze nie włączone)."""

    state: Literal["good", "bad", "unreadable"]
    enabled: bool
    since: date | None
    problem: SettingProblem | None


class RemindersEnabledChange(Model):
    """Przełącznik Przypomnień o raporcie; pierwsze włączenie ustawia dzień wdrożenia na dziś."""

    enabled: bool


class ReminderPreview(Model):
    """Przypomnienie z formularza na przykładowy dzień (wczoraj), takie, jakie dostałby Wykonawca: stały temat i treść
    ze wzorem Raportu wykonawcy i stopką. Nic się nie zapisuje ani nie wysyła."""

    subject: str
    text: str
