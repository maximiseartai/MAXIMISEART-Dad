"""Uporządkowanie INTERMAX z Centrum rozliczeń: karta poza okresami, wejście procesu z Ustawień Centrum i start.

INTERMAX to Rejestr zleceń z Ustawień Centrum, a Kopie INTERMAX trafiają do folderu narzędzia. Proces nie należy do
okresu: okres Uruchomienia to okres dzisiejszej daty z zegara procesu, ustalony przy starcie (ADR 0019), więc
Logi Uruchomienia trafiają do Skrzynki Zgłoszeń przy tym okresie, także przy Zatrzymaniu przed odczytem.

Dni na karcie (``days``) to Dni uporządkowane z silnika (``intermax_ordering.register_days``). Odczyt INTERMAX
trwa (0,17–0,21 s na Macu dla kopii INTERMAX taty, 6,5 MB: mediany 7 odczytów ``register_days`` dla dni od 28.09 do
26.10.2026), a karta pyta o dni przy każdym wejściu i powrocie do okna, więc Centrum czyta go od nowa tylko po
zmianie znacznika zapisu (``live_file.saved_version``) albo dnia; inaczej oddaje poprzedni udany odczyt. Nieudanego odczytu (Komunikatu) nie pamięta, więc ponawia go przy następnym pytaniu,
jak ``live_file.LastGoodReads``: OneDrive po pobraniu pliku nie zmienia jego znacznika. Uporządkowanie INTERMAX
zmienia ten znacznik, więc dni po nim są świeże.

Okno Ustawień wymienia Kopie INTERMAX z tego folderu i przywraca wybraną (``intermax_restore.restore``) w miejscu
„jedno naraz” ``RunHost``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timezone
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import intermax as intermax_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.catalog import Catalog, declaration_of
from rozliczenia.centrum.cloud_files import CloudFiles
from rozliczenia.centrum.configuration import InputWorkbook, open_in_excel
from rozliczenia.centrum.diagnosis_messages import file_only_in_cloud
from rozliczenia.centrum.live_file import saved_version
from rozliczenia.centrum.process_kind import HostParts, PreparedRun, start_from_settings
from rozliczenia.centrum.runs import RunHost
from rozliczenia import intermax_ordering, intermax_restore
from rozliczenia.intermax_copies import Copy
from rozliczenia.run_context import RunContexts
from rozliczenia.message import Message, StopError
from rozliczenia.text import short_day_label
from rozliczenia.centrum.settings.folders import FolderSettings
from rozliczenia.centrum.settings.owner import CentrumSettings

_KIND: Final = declaration_of("intermax")
_VIEW: Final = _KIND.view


@dataclass
class _DaysRead:
    register: Path
    version: str
    today: date
    found: tuple[intermax_ordering.RegisterDay, ...]


@dataclass
class _LastDaysRead:
    read: _DaysRead | None = None


@dataclass(frozen=True)
class IntermaxEntry:
    """Adapter startu Uporządkowania INTERMAX: katalog procesów, folder Kopii INTERMAX i zależności procesu od Centrum.

    ``parts``: zegar procesu, zegar Centrum i jego przerwa dla krótkiej ponownej próby podmiany, której odmawia
    OneDrive, i kroki podmiany INTERMAX na dysku, te same dla Uporządkowania i przywrócenia Kopii. ``cloud_files``
    rozpoznaje INTERMAX „tylko online” w OneDrive, gdy jego dni nie dają się odczytać. ``contexts``: Kontekst
    Uruchomienia pracy Centrum; jego uchwytem plików taty karta czyta dni.
    """

    settings: CentrumSettings
    catalog: Catalog
    copies_directory: Path
    parts: HostParts
    cloud_files: CloudFiles
    contexts: RunContexts
    _last_days: _LastDaysRead = field(default_factory=_LastDaysRead, compare=False, repr=False)

    @property
    def key(self) -> common_contract.ProcessKey:
        return "intermax"

    def setup(self, last: runs_contract.RunRestored | None) -> intermax_contract.IntermaxSetup:
        """Karta przed startem z ostatnim Uporządkowaniem INTERMAX ``last`` z Logów Uruchomienia."""

        settings = self.settings.snapshot().folders
        register = settings.register
        return intermax_contract.IntermaxSetup(
            title=_KIND.title,
            reminder=_VIEW.reminder,
            blocker=_KIND.settings_blocker(settings),
            open_in_excel=[] if register is None else open_in_excel([InputWorkbook(_VIEW.register_name, register, "data_file")]),
            last=last,
        )

    def days(self) -> intermax_contract.IntermaxDays:
        """Dni INTERMAX z Ustawień Centrum ze stanem; bez wskazanego Rejestru zleceń żadnych dni i żadnego Komunikatu."""

        register = self.settings.snapshot().folders.register
        if register is None:
            return intermax_contract.IntermaxDays(days=[], problem=None)
        today = self.parts.now().date()
        version = saved_version(register)
        last = self._last_days.read
        if last is not None and (last.register, last.version, last.today) == (register, version, today):
            found: tuple[intermax_ordering.RegisterDay, ...] | Message = last.found
        else:
            found = intermax_ordering.register_days(register, today, self.contexts.files)
            if version is not None and not isinstance(found, Message):
                self._last_days.read = _DaysRead(register, version, today, found)
        if isinstance(found, Message):
            problem = file_only_in_cloud(register) if self.cloud_files.online_only(register) else found
            return intermax_contract.IntermaxDays(days=[], problem=common_contract.Message.of(problem))
        return intermax_contract.IntermaxDays(days=[_day(day, today) for day in found], problem=None)

    def prepare(self) -> PreparedRun[Any, Any]:
        """Wejście procesu z Ustawień Centrum; ``Refusal``, gdy Rejestr zleceń nie jest wskazany."""

        snapshot = self.settings.snapshot()
        start = start_from_settings(
            _KIND, snapshot, {"register": _register(snapshot.folders), "copies_directory": self.copies_directory},
            period=None, dry_run=False,
        )
        return self.catalog.prepared(self.key, start, self.parts, self.contexts.new())

    def copies(self) -> intermax_contract.IntermaxCopies:
        """Kopie INTERMAX od najnowszej albo Komunikat, gdy folderu Kopii nie da się odczytać."""

        try:
            listed = intermax_restore.copies(self.copies_directory)
        except StopError as error:
            return intermax_contract.IntermaxCopies(copies=[], problem=common_contract.Message.of(error.message))
        return intermax_contract.IntermaxCopies(copies=[_copy(copy) for copy in listed], problem=None)

    def restore(self, name: str) -> intermax_contract.IntermaxRestore:
        """Przywraca Kopię INTERMAX ``name`` do INTERMAX z Ustawień Centrum; ``Refusal``, gdy go nie wskazano."""

        register = _register(self.settings.snapshot().folders)
        try:
            parts = self.parts
            restored = intermax_restore.restore(
                name, register, self.copies_directory, now=parts.now, waiting=parts.waiting, disk=parts.disk
            )
        except StopError as stop:
            return intermax_contract.IntermaxRestoreRefused(state="refused", message=common_contract.Message.of(stop.message))
        return intermax_contract.IntermaxRestored(
            state="restored",
            restored=_copy(restored.restored),
            warnings=[common_contract.Message.of(warning) for warning in restored.warnings],
        )


def _copy(copy: Copy) -> intermax_contract.IntermaxCopy:
    return intermax_contract.IntermaxCopy(
        name=copy.path.name,
        taken_at=copy.moment.astimezone(timezone.utc),
        before=copy.before,
        before_label=copy.before_label,
    )


def _day(day: intermax_ordering.RegisterDay, today: date) -> intermax_contract.IntermaxDay:
    label = short_day_label(day.day)
    return intermax_contract.IntermaxDay(day=day.day, label=label, today=day.day == today, ordered=day.ordered)


def _register(settings: FolderSettings) -> Path:
    return _KIND.required_paths(settings)["register"]


def intermax_router(
    host: RunHost, entry: IntermaxEntry, last: Callable[[], runs_contract.RunRestored | None]
) -> APIRouter:
    router = APIRouter(prefix="/api/intermax", tags=["uruchomienia"])

    @router.get("", operation_id="getIntermaxSetup")
    def setup() -> intermax_contract.IntermaxSetup:
        return entry.setup(last())

    @router.get("/days", operation_id="getIntermaxDays")
    def days() -> intermax_contract.IntermaxDays:
        return entry.days()

    @router.post("/run", operation_id="startIntermax", responses=NOT_FOUND_OR_CONFLICT)
    def start() -> runs_contract.RunView:
        return host.start(entry.prepare())

    return router


def intermax_copies_router(host: RunHost, entry: IntermaxEntry) -> APIRouter:
    """Kopie INTERMAX w Konfiguracji: lista od najnowszej i przywrócenie wybranej."""

    router = APIRouter(prefix="/api/intermax/copies", tags=["konfiguracja"])

    @router.get("", operation_id="getIntermaxCopies")
    def copies() -> intermax_contract.IntermaxCopies:
        return entry.copies()

    @router.post("/restore", operation_id="restoreIntermaxCopy", responses={409: {"model": common_contract.Problem}})
    def restore(request: intermax_contract.IntermaxRestoreRequest) -> intermax_contract.IntermaxRestore:
        host.begin_restore()
        try:
            return entry.restore(request.name)
        finally:
            host.end_restore()

    return router
