"""Uporządkowanie INTERMAX z Centrum rozliczeń: karta poza okresami, wejście procesu z Ustawień taty i start.

INTERMAX to Rejestr zleceń z Ustawień taty, a Kopie INTERMAX trafiają do folderu narzędzia. Proces nie należy do
okresu: okres Uruchomienia to okres dzisiejszej daty z zegara procesu, ustalony przy starcie (ADR 0019), więc
Logi Uruchomienia trafiają do Skrzynki Zgłoszeń przy tym okresie, także przy Zatrzymaniu przed odczytem.

Dni na karcie (``days``) to Dni uporządkowane z silnika (``intermax_ordering.register_days``). Odczyt INTERMAX
trwa (0,17–0,21 s na Macu dla kopii INTERMAX taty, 6,5 MB: mediany 7 odczytów ``register_days`` dla dni od 28.09 do
26.10.2026), a karta pyta o dni przy każdym wejściu i powrocie do okna, więc Centrum czyta go od nowa tylko po
zmianie znacznika zapisu (``live_file.saved_version``) albo dnia; inaczej oddaje poprzedni udany odczyt. Nieudanego odczytu (Komunikatu) nie pamięta, więc ponawia go przy następnym pytaniu,
jak ``live_file.LastGoodReads``: OneDrive po pobraniu pliku nie zmienia jego znacznika. Uporządkowanie INTERMAX
zmienia ten znacznik, więc dni po nim są świeże.

Konfiguracja wymienia Kopie INTERMAX z tego folderu i przywraca wybraną (``intermax_restore.restore``). Przywrócenie
zajmuje w ``RunHost`` miejsce „jedno naraz”, bo podmienia INTERMAX, więc nie biegnie obok Uporządkowania INTERMAX.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.catalog import INTERMAX
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import InputWorkbook, open_in_excel
from rozliczenia.centrum.diagnosis_messages import file_only_in_cloud
from rozliczenia.centrum.live_file import saved_version
from rozliczenia.centrum.processes import Processes
from rozliczenia.centrum.runs import PreparedRun, RunHost
from rozliczenia import intermax_copies, intermax_messages, intermax_ordering, intermax_restore
from rozliczenia.client_data import ForbiddenValues
from rozliczenia.input_copy import InputCopy
from rozliczenia.intermax_copies import Copy
from rozliczenia.intermax_replace import Disk, Waiting
from rozliczenia.intermax_process import OrderingInputs
from rozliczenia.message import Message, StopError
from rozliczenia.text import short_day_label
from rozliczenia.centrum.settings import Settings, SettingsStore

_VIEW: Final = INTERMAX.view


@dataclass
class _DaysRead:
    """Ostatni udany odczyt dni: INTERMAX, jego znacznik zapisu, dzień zegara i dni z silnika."""

    register: Path
    version: str
    today: date
    found: tuple[intermax_ordering.RegisterDay, ...]


@dataclass
class _LastDaysRead:
    read: _DaysRead | None = None


@dataclass(frozen=True)
class IntermaxEntry:
    """Adapter startu Uporządkowania INTERMAX: rdzenie procesów, folder Kopii INTERMAX i zegar procesu.

    ``waiting``: zegar Centrum i jego przerwa dla krótkiej ponownej próby podmiany, której odmawia OneDrive, a
    ``disk`` kroki podmiany INTERMAX na dysku, te same dla Uporządkowania i przywrócenia Kopii. ``cloud_files``
    rozpoznaje INTERMAX „tylko online” w OneDrive, gdy jego dni nie dają się odczytać. ``forbidden``: pamięć reguły
    danych pracy Centrum dla Uporządkowania i dni na karcie.
    """

    store: SettingsStore
    processes: Processes
    copies_directory: Path
    now: Callable[[], datetime]
    waiting: Waiting
    disk: Disk
    cloud_files: CloudFiles
    forbidden: ForbiddenValues
    _last_days: _LastDaysRead = field(default_factory=_LastDaysRead, compare=False, repr=False)

    @property
    def key(self) -> contract.ProcessKey:
        return INTERMAX.key

    def setup(self, last: contract.RunRestored | None) -> contract.IntermaxSetup:
        """Karta przed startem z ostatnim Uporządkowaniem INTERMAX ``last`` z Logów Uruchomienia."""

        settings = self.store.load()
        register = settings.register
        return contract.IntermaxSetup(
            title=INTERMAX.title,
            reminder=_VIEW.reminder,
            blocker=INTERMAX.settings_blocker(settings),
            open_in_excel=[] if register is None else open_in_excel([InputWorkbook("INTERMAX", register, "data_file")]),
            last=last,
        )

    def days(self) -> contract.IntermaxDays:
        """Dni INTERMAX z Ustawień taty ze stanem; bez wskazanego Rejestru zleceń żadnych dni i żadnego Komunikatu."""

        register = self.store.load().register
        if register is None:
            return contract.IntermaxDays(days=[], problem=None)
        today = self.now().date()
        version = saved_version(register)
        last = self._last_days.read
        if last is not None and (last.register, last.version, last.today) == (register, version, today):
            found: tuple[intermax_ordering.RegisterDay, ...] | Message = last.found
        else:
            found = intermax_ordering.register_days(register, today, self.forbidden)
            if version is not None and not isinstance(found, Message):
                self._last_days.read = _DaysRead(register, version, today, found)
        if isinstance(found, Message):
            problem = file_only_in_cloud(register) if self.cloud_files.online_only(register) else found
            return contract.IntermaxDays(days=[], problem=contract.Message.of(problem))
        return contract.IntermaxDays(days=[_day(day, today) for day in found], problem=None)

    def prepare(self) -> PreparedRun[Any, Any]:
        """Wejście procesu z Ustawień taty; ``contract.Refusal``, gdy Rejestr zleceń nie jest wskazany."""

        register = _register(self.store.load())
        copy = InputCopy()
        inputs = OrderingInputs(
            register,
            self.copies_directory,
            now=self.now,
            waiting=self.waiting,
            disk=self.disk,
            forbidden=self.forbidden,
            copy=copy,
        )
        return PreparedRun(
            declaration=INTERMAX,
            period=inputs.period,
            process=INTERMAX.core(self.processes),
            inputs=inputs,
            input_copy=copy,
        )

    def copies(self) -> contract.IntermaxCopies:
        """Kopie INTERMAX od najnowszej albo Komunikat, gdy folderu Kopii nie da się odczytać."""

        try:
            listed = intermax_copies.listed(self.copies_directory)
        except OSError:
            problem = intermax_messages.copies_unreadable(self.copies_directory)
            return contract.IntermaxCopies(copies=[], problem=contract.Message.of(problem))
        return contract.IntermaxCopies(copies=[_copy(copy) for copy in listed], problem=None)

    def restore(self, name: str) -> contract.IntermaxRestore:
        """Przywraca Kopię INTERMAX ``name`` do INTERMAX z Ustawień taty; ``contract.Refusal``, gdy go nie wskazano."""

        register = _register(self.store.load())
        try:
            restored = intermax_restore.restore(
                name, register, self.copies_directory, now=self.now, waiting=self.waiting, disk=self.disk
            )
        except StopError as stop:
            return contract.IntermaxRestoreRefused(state="refused", message=contract.Message.of(stop.message))
        return contract.IntermaxRestored(
            state="restored",
            restored=_copy(restored.restored),
            previous=_copy(restored.previous),
            warnings=[contract.Message.of(warning) for warning in restored.warnings],
        )


def _copy(copy: Copy) -> contract.IntermaxCopy:
    return contract.IntermaxCopy(
        name=copy.path.name, taken_at=copy.moment.astimezone(timezone.utc), before=copy.before
    )


def _day(day: intermax_ordering.RegisterDay, today: date) -> contract.IntermaxDay:
    label = short_day_label(day.day)
    return contract.IntermaxDay(day=day.day, label=label, today=day.day == today, ordered=day.ordered)


def _register(settings: Settings) -> Path:
    return INTERMAX.required_paths(settings)["register"]


def intermax_router(
    host: RunHost, entry: IntermaxEntry, last: Callable[[], contract.RunRestored | None]
) -> APIRouter:
    router = APIRouter(prefix="/api/intermax", tags=["uruchomienia"])

    @router.get("", operation_id="getIntermaxSetup")
    def setup() -> contract.IntermaxSetup:
        return entry.setup(last())

    @router.get("/days", operation_id="getIntermaxDays")
    def days() -> contract.IntermaxDays:
        return entry.days()

    @router.post("/run", operation_id="startIntermax", responses=contract.NOT_FOUND_OR_CONFLICT)
    def start() -> contract.RunView:
        return host.start(entry.prepare())

    return router


def intermax_copies_router(host: RunHost, entry: IntermaxEntry) -> APIRouter:
    """Kopie INTERMAX w Konfiguracji: lista od najnowszej i przywrócenie wybranej."""

    router = APIRouter(prefix="/api/intermax/copies", tags=["konfiguracja"])

    @router.get("", operation_id="getIntermaxCopies")
    def copies() -> contract.IntermaxCopies:
        return entry.copies()

    @router.post("/restore", operation_id="restoreIntermaxCopy", responses={409: {"model": contract.Problem}})
    def restore(request: contract.IntermaxRestoreRequest) -> contract.IntermaxRestore:
        host.begin_restore()
        try:
            return entry.restore(request.name)
        finally:
            host.end_restore()

    return router
