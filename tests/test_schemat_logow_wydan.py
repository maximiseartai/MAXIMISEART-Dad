"""Logi Uruchomienia każdego Wydania przechodzą dzisiejszy schemat Logów, więc karta z Historii, Uwaga taty i odtworzenie
czytają każdy plik Logów z dysku taty i z Archiwum Logów okresu.

Zapis ``tests/fixtures/schemat_logow_wydan.json`` ma fakty schematu Logów każdego Wydania od v0.1.1 i dzisiejszego
(``tests/fixtures/schemat_logow.py``). Strażnik łapie zmianę schematu, po której plik zgodny z zapisem jej nie
przechodzi. Tabela przypadków (``PRZYPADKI``, każdy wiersz biegnie w teście):

| Zmiana schematu | Przykład | Strażnik |
|---|---|---|
| usunięta wartość zamkniętej listy | widok ``konfiguracja`` usunięty z ``PageId`` | łapie |
| usunięte pole (Logi nie przyjmują pól spoza schematu) | pole ``omitted`` usunięte | łapie |
| nowe pole wymagane | pole bez wartości domyślnej | łapie |
| pole opcjonalne staje się wymagane | ``process`` bez ``= None`` | łapie |
| usunięty wariant unii z polem rozróżniającym | wpis ``widok`` usunięty z unii | łapie |
| nowa wartość, nowe pole opcjonalne | strona ``raporty`` | przepuszcza: stary plik przechodzi |
| węższy typ otwartego pola | ``str`` na ``int`` | znana luka (``ZNANE_LUKI``) |
| węższe ograniczenie albo walidator | ``max_length``, ``field_validator`` | znana luka (``ZNANE_LUKI``) |
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
import pytest

from rozliczenia.centrum.run_logs import RunLog
from tests.fixtures.schemat_logow import Fakty, fakty, niezapisane, wczytaj, zwezenia


def test_logi_kazdego_wydania_przechodza_dzisiejszy_schemat_logow() -> None:
    znalezione = zwezenia(wczytaj(), fakty(RunLog.model_json_schema()))

    assert znalezione == [], (
        "Plik Logów starszego Wydania nie przejdzie schematu, więc u taty nie da karty z Historii, a u Maksa "
        "odtworzenia. Zostaw w schemacie dawną wartość albo pole (jak StoredPageId w dad_actions.py) albo daj nowemu "
        f"polu wartość domyślną: {znalezione}"
    )


def test_zapis_wydan_ma_kazdy_fakt_dzisiejszego_schematu_logow() -> None:
    braki = niezapisane(wczytaj(), fakty(RunLog.model_json_schema()))

    assert braki == [], (
        "Zapis faktów Wydań nie ma nowych wartości albo pól schematu Logów, więc nie złapie ich usunięcia w następnym "
        f"Wydaniu: uruchom .venv/bin/python -m tests.fixtures.schemat_logow --zapisz i dołącz zmieniony plik: {braki}"
    )


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Widok(_Model):
    action: Literal["widok"]
    page: Literal["okresy", "konfiguracja"]


class _Przycisk(_Model):
    action: Literal["przycisk"]
    process: str | None = None


class _Dawne(_Model):
    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int


class _BezWartosci(_Model):
    class _Widok(_Model):
        action: Literal["widok"]
        page: Literal["okresy"]

    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int


class _BezPola(_Model):
    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]


class _NowePoleWymagane(_Model):
    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int
    source: str


class _OpcjonalneWymagane(_Model):
    class _Przycisk(_Model):
        action: Literal["przycisk"]
        process: str | None

    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int


class _BezWariantu(_Model):
    entries: list[_Przycisk]
    omitted: int


class _Szersze(_Model):
    class _Widok(_Model):
        action: Literal["widok"]
        page: Literal["okresy", "konfiguracja", "raporty"]

    entries: list[Annotated[_Widok | _Przycisk, Field(discriminator="action")]]
    omitted: int
    note: str | None = None


PRZYPADKI: list[tuple[str, type[BaseModel], bool]] = [
    ("usunięta wartość zamkniętej listy", _BezWartosci, True),
    ("usunięte pole", _BezPola, True),
    ("nowe pole wymagane", _NowePoleWymagane, True),
    ("pole opcjonalne staje się wymagane", _OpcjonalneWymagane, True),
    ("usunięty wariant unii z polem rozróżniającym", _BezWariantu, True),
    ("nowa wartość i nowe pole opcjonalne", _Szersze, False),
]


def _fakty(model: type[BaseModel]) -> Fakty:
    return fakty(model.model_json_schema())


@pytest.mark.parametrize(("zmiana", "teraz", "lapie"), PRZYPADKI, ids=[zmiana for zmiana, _, _ in PRZYPADKI])
def test_straznik_schematu_logow_lapie_kazda_zmiane_z_tabeli(zmiana: str, teraz: type[BaseModel], lapie: bool) -> None:
    assert bool(zwezenia(_fakty(_Dawne), _fakty(teraz))) is lapie, zmiana


class _Tekst(_Model):
    value: str


class _Liczba(_Model):
    value: int


class _Krotki(_Model):
    value: Annotated[str, Field(max_length=3)]


class _Walidator(_Model):
    value: str

    @field_validator("value")
    @classmethod
    def _tylko_cyfry(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError(value)
        return value


ZNANE_LUKI: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "węższy typ otwartego pola: str na int": (_Tekst, _Liczba),
    "węższe ograniczenie: max_length": (_Tekst, _Krotki),
    "walidator, którego schemat JSON nie pokazuje: field_validator": (_Tekst, _Walidator),
}
"""Zmiana, po której stary plik Logów nie przechodzi schematu, a strażnik jej nie łapie, bo czyta tylko zamknięte listy,
pola i pola wymagane schematu JSON. Gdy strażnik zacznie ją łapać, próbka znika stąd i staje się wierszem tabeli."""


@pytest.mark.parametrize("luka", ZNANE_LUKI)
def test_znane_luki_straznika_schematu_logow_przechodza_przez_niego(luka: str) -> None:
    dawne, teraz = ZNANE_LUKI[luka]
    dawny_plik = dawne(value="abcd").model_dump_json()

    with pytest.raises(ValueError, match="validation error"):
        teraz.model_validate_json(dawny_plik)
    assert zwezenia(_fakty(dawne), _fakty(teraz)) == [], f"strażnik łapie już „{luka}”: przenieś ją do PRZYPADKI"
