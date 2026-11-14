"""Dziennik działań taty w Centrum dla Logów Uruchomienia (wpisy: ``dad_actions``).

Start Centrum to chwila, w której Centrum zbudowało swoją aplikację (``DadActionJournal`` powstaje razem z nią); jego
wpis trafia do pliku razem z pierwszym działaniem tej pracy Centrum, a każde Uruchomienie zaczyna się przyciskiem, więc
praca Centrum bez działań (eksport kontraktu, Centrum zamknięte bez otwartej karty) wpisu nie zostawia. Widok to strona
z menu, którą przeglądarka zgłasza pomiarem gotowego widoku (``recordViewTiming``), więc widok, który się nie wczytał,
wpisu nie ma. Przycisk to każde zapytanie API, które coś zmienia (wszystko poza ``GET``), nazwane operacją API z
kontraktu (``operation_id``): start Uruchomienia procesu z procesem i trybem, Decyzja taty, Diagnoza, Aktualizacja
narzędzia, zamknięcie Centrum, wysłanie Uwagi taty i każdy inny. Wpis nie ma treści zapytania, więc nie ma tytułu ani
treści Uwagi taty, ścieżek, adresu zapytania ani tokenu okresu.

Wpisy leżą w jednym pliku obok Logów Uruchomienia, dopisywane linia po linii, więc przeżywają zamknięcie Centrum i
trafiają do Logów pierwszego Uruchomienia po ponownym starcie. Logi Uruchomienia zabierają przy swoim powstaniu
wszystkie wpisy z pliku (``DadActionJournal.take``), więc Logi każdego Uruchomienia mają działania od Logów
poprzedniego do swojego końca, także start tego Uruchomienia i Decyzję taty w jego trakcie. Logi biorą najwyżej
``MAX_ENTRIES`` najnowszych wpisów, a liczba pominiętych (starszych albo nieczytelnych, np. linia urwana zgaśnięciem
Centrum) stoi obok. Nieudany zapis wpisu to linia dziennika Centrum, nigdy błąd zapytania taty.
"""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Final, TypeGuard, get_args

from fastapi import Request
from pydantic import RootModel, ValidationError

from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.contract import timing as timing_contract
from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.dad_actions import ButtonPressed, CentrumStarted, DadAction, DadActions, ViewOpened
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.wall_clock import utc_now

DAD_ACTIONS_FILE: Final = "dzialania-taty.jsonl"
MAX_ENTRIES: Final = 1000
_API_OPERATIONS: Final[frozenset[str]] = frozenset(get_args(timing_contract.ApiOperation))
_NOT_PRESSED: Final[frozenset[timing_contract.ApiOperation]] = frozenset({"draftDadNote"})
"""Zapytanie, które nie jest przyciskiem taty: szkic Uwagi okno wysyła samo przy pisaniu."""


class _Line(RootModel[DadAction]):
    """Jedna linia pliku dziennika: jeden wpis w JSON."""


class DadActionJournal:
    """Plik ``DAD_ACTIONS_FILE`` w katalogu Logów z działaniami taty, które czekają na Logi następnego Uruchomienia.

    ``_started`` to start tej pracy Centrum, dopóki nie trafił do pliku z jej pierwszym działaniem.
    """

    def __init__(self, work: CentrumWork) -> None:
        self._path = work.log.directory / DAD_ACTIONS_FILE
        self._log = work.log
        self._lock = threading.Lock()
        self._started: CentrumStarted | None = CentrumStarted(at=utc_now(), action="start Centrum")

    async def observe(self, request: Request) -> None:
        """Zależność każdej trasy API: wpis widoku albo przycisku, zanim trasa zacznie działać.

        Wpis powstaje przed trasą, więc start Uruchomienia jest w dzienniku przed jego Logami, nawet gdy proces
        skończy się, zanim przeglądarka dostanie odpowiedź. Pomiar widoku, którego kontrakt nie przyjmie, nie daje
        wpisu, a odrzuca go trasa.
        """

        operation = getattr(request.scope.get("route"), "operation_id", None)
        if request.method == "GET" or operation is None:
            return
        at = utc_now()
        if operation == "recordViewTiming":
            try:
                timing = timing_contract.ViewTiming.model_validate_json(await request.body())
            except ValidationError:
                return
            self._add(ViewOpened(at=at, action="widok", page=timing.page, kind=timing.kind))
        elif _is_api_operation(operation) and operation not in _NOT_PRESSED:
            self._add(_pressed(at, operation, await request.body()))

    def take(self) -> DadActions:
        """Wszystkie wpisy z pliku dla Logów Uruchomienia; plik zostaje pusty, a następne Logi mają tylko nowsze wpisy.

        Plik, którego nie da się opróżnić, da te same wpisy także następnym Logom: lepiej dwa razy niż wcale.
        """

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


def _is_api_operation(operation: str) -> TypeGuard[timing_contract.ApiOperation]:
    """Operacja trasy, która jest operacją API z kontraktu (``ApiOperation``); poza nią tylko pomiar widoku i trasy
    ``GET`` (``tests/test_centrum_rozliczen.py``)."""

    return operation in _API_OPERATIONS


def _pressed(at: datetime, operation: timing_contract.ApiOperation, body: bytes) -> ButtonPressed:
    """Przycisk bez treści zapytania; ze startu Uruchomienia procesu (``RunRequest``) tylko proces i tryb."""

    if operation == "startRun":
        try:
            request = runs_contract.RunRequest.model_validate_json(body)
        except ValidationError:
            pass
        else:
            return ButtonPressed(
                at=at, action="przycisk", operation=operation, process=request.process, mode=request.mode
            )
    return ButtonPressed(at=at, action="przycisk", operation=operation)
