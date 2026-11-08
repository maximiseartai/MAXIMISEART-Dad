"""Dziennik działań taty w Centrum dla Logów Uruchomienia: co tata robił w Centrum od poprzedniego Uruchomienia.

Wpisy to start Centrum, otwarty widok i wciśnięty przycisk, każdy z chwilą (UTC). Start Centrum to chwila, w której
Centrum zbudowało swoją aplikację (``DadActionJournal`` powstaje razem z nią); jego wpis trafia do pliku razem z
pierwszym działaniem tej pracy Centrum, a każde Uruchomienie zaczyna się przyciskiem, więc praca Centrum bez działań
(eksport kontraktu, Centrum zamknięte bez otwartej karty) wpisu nie zostawia. Widok to strona z menu, którą
przeglądarka zgłasza pomiarem gotowego widoku (``recordViewTiming``), więc widok, który się nie wczytał, wpisu nie ma.
Przycisk to każde zapytanie API, które coś zmienia (wszystko poza ``GET``), nazwane operacją API z kontraktu
(``operation_id``): start Uruchomienia procesu z procesem i trybem (podgląd albo zapis), Decyzja taty, Diagnoza,
Aktualizacja narzędzia, zamknięcie Centrum, wysłanie Uwagi taty i każdy inny. Wpis nie ma treści zapytania, więc nie
ma tytułu ani treści Uwagi taty, ścieżek, adresu zapytania ani tokenu okresu. Szkic Uwagi taty (``draftDadNote``) nie
jest przyciskiem: okno pyta o niego samo przy pisaniu.

Wpisy leżą w jednym pliku obok Logów Uruchomienia, dopisywane linia po linii, więc przeżywają zamknięcie Centrum i
trafiają do Logów pierwszego Uruchomienia po ponownym starcie. Logi Uruchomienia zabierają przy swoim powstaniu
wszystkie wpisy z pliku (``DadActionJournal.take``), więc Logi każdego Uruchomienia mają działania od Logów
poprzedniego do swojego końca, także start tego Uruchomienia i Decyzję taty w jego trakcie. Logi biorą najwyżej
``MAX_ENTRIES`` najnowszych wpisów, a liczba pominiętych (starszych albo nieczytelnych, np. linia urwana zgaśnięciem
Centrum) stoi obok. Nieudany zapis wpisu to linia dziennika Centrum, nigdy błąd zapytania taty.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Annotated, Final, Literal

from fastapi import Request
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, RootModel, ValidationError

from rozliczenia.centrum import contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.log import CentrumLog

DAD_ACTIONS_FILE: Final = "dzialania-taty.jsonl"
MAX_ENTRIES: Final = 1000
# Zapytania, które nie są przyciskiem taty: szkic Uwagi okno wysyła samo przy pisaniu, a pomiar widoku jest widokiem.
_NOT_PRESSED: Final = frozenset({"draftDadNote", "recordViewTiming"})


StoredRunMode = Annotated[contract.RunMode, BeforeValidator(contract.RunMode.stored)]
"""Tryb Uruchomienia w pliku na dysku taty (ten dziennik, Logi Uruchomienia, plik ostatniego startu, dziennik Wyceny w
efenix): wartość ``RunMode``, a w plikach sprzed schematu Logów 3 jego słowo."""


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CentrumStarted(_Record):
    """Start Centrum rozliczeń (nowa praca Centrum, np. po zamknięciu, Aktualizacji narzędzia albo restarcie Windows)."""

    at: datetime
    action: Literal["start Centrum"]


class ViewOpened(_Record):
    """Gotowy widok strony z menu; ``kind``: zimny start strony (otwarcie albo odświeżenie karty) albo przejście w menu."""

    at: datetime
    action: Literal["widok"]
    page: contract.PageId
    kind: contract.ViewKind


class ButtonPressed(_Record):
    """Zapytanie API, które coś zmienia, nazwane operacją API; start Uruchomienia procesu ma też proces i tryb."""

    at: datetime
    action: Literal["przycisk"]
    operation: str
    process: contract.ProcessKey | None = None
    mode: StoredRunMode | None = None


DadAction = Annotated[CentrumStarted | ViewOpened | ButtonPressed, Field(discriminator="action")]


class _Line(RootModel[DadAction]):
    """Jedna linia pliku dziennika: jeden wpis w JSON."""


class DadActions(_Record):
    """Działania taty w Logach Uruchomienia, po kolei; ``omitted``: wpisy starsze od ``MAX_ENTRIES`` najnowszych albo
    nieczytelne."""

    entries: list[DadAction]
    omitted: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DadActionJournal:
    """Plik ``path`` z działaniami taty, które czekają na Logi następnego Uruchomienia."""

    def __init__(self, path: Path, log: CentrumLog) -> None:
        self._path = path
        self._log = log
        self._lock = threading.Lock()
        # Start tej pracy Centrum, dopóki nie trafił do pliku z jej pierwszym działaniem.
        self._started: CentrumStarted | None = CentrumStarted(at=_utc_now(), action="start Centrum")

    async def observe(self, request: Request) -> None:
        """Zależność każdej trasy API: wpis widoku albo przycisku, zanim trasa zacznie działać.

        Wpis powstaje przed trasą, więc start Uruchomienia jest w dzienniku przed jego Logami, nawet gdy proces
        skończy się, zanim przeglądarka dostanie odpowiedź.
        """

        operation = getattr(request.scope.get("route"), "operation_id", None)
        if request.method == "GET" or operation is None:
            return
        at = _utc_now()
        if operation == "recordViewTiming":
            try:
                timing = contract.ViewTiming.model_validate_json(await request.body())
            except ValidationError:
                return  # pomiar, którego kontrakt nie przyjmie, trasa i tak odrzuci
            self._add(ViewOpened(at=at, action="widok", page=timing.page, kind=timing.kind))
        elif operation not in _NOT_PRESSED:
            self._add(_pressed(at, operation, await request.body()))

    def take(self) -> DadActions:
        """Wszystkie wpisy z pliku dla Logów Uruchomienia; plik zostaje pusty, a następne Logi mają tylko nowsze wpisy."""

        with self._lock:
            try:
                lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
            except FileNotFoundError:
                lines = []
            except OSError as failure:
                self._log.dad_actions_unavailable(failure)
                return DadActions(entries=[], omitted=0)
            try:
                replace_atomically(self._path, "")
            except OSError as failure:
                # Plik, którego nie da się opróżnić, da te same wpisy także następnym Logom; lepiej dwa razy niż wcale.
                self._log.dad_actions_unavailable(failure)
        entries: list[DadAction] = []
        for line in lines:
            try:
                entries.append(_Line.model_validate_json(line).root)
            except ValidationError:
                continue
        kept = entries[-MAX_ENTRIES:]
        return DadActions(entries=kept, omitted=len(lines) - len(kept))

    def _add(self, action: DadAction) -> None:
        try:
            with self._lock:
                pending = [action] if self._started is None else [self._started, action]
                text = "".join(_Line(entry).model_dump_json() + "\n" for entry in pending)
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as journal:
                    journal.write(text)
                self._started = None
        except OSError as failure:
            self._log.dad_actions_unavailable(failure)


def _pressed(at: datetime, operation: str, body: bytes) -> ButtonPressed:
    """Przycisk bez treści zapytania; ze startu Uruchomienia procesu (``RunRequest``) tylko proces i tryb."""

    if operation == "startRun":
        try:
            request = contract.RunRequest.model_validate_json(body)
        except ValidationError:
            pass
        else:
            return ButtonPressed(
                at=at, action="przycisk", operation=operation, process=request.process, mode=request.mode
            )
    return ButtonPressed(at=at, action="przycisk", operation=operation)
