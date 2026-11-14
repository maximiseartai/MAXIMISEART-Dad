"""Exhaustively check that every consumer of the Status okresu reads the same Folder okresu the same way.

For every state of one Folder okresu in a scope, the checker builds the folder on the real disk (a temporary
directory, real files, access taken away with ``chmod`` or, on Windows, a deny entry of ``icacls``) and asks each consumer through its public entry point:

- Tablica okresów (``GET /api/periods`` of the real ``create_app``): the Status okresu and the steps it offers;
- the start cards of Przygotowanie, Przebieg rozliczeń and Wycena w efenix (``GET /api/runs/setup``);
- Uzupełnienie (``GET /api/periods/{token}/quantities-to-fill``): whether Dad may still fill the Plik zbiorczy;
- Wpisanie raportów (``report_entering.enter_from_mail``): from which day it reads the Skrzynka raportów, so whether
  the period is open for it;
- the start of Przygotowanie pliku zbiorczego (``input_checks.check_preparation``) and of Przebieg rozliczeń
  (``input_checks.check_settlement``): their Sprawdzanie passes or stops.

It compares each answer with the reference Status okresu of the folder (``reference``), which the checker derives
from what it built, as GLOSSARY.md says: a Folder rozliczeń pracowników makes Rozliczenia pracowników gotowe and the
period closed (Droga okresu), else a Plik zbiorczy makes Plik zbiorczy przygotowany, else Brak plików okresu. Two
rules:

- OTWARCIE: each process lets itself act on the period exactly when the reference Status okresu allows it:
  Przygotowanie and Wpisanie raportów only in Brak plików okresu, Przebieg rozliczeń and Uzupełnienie only in Plik
  zbiorczy przygotowany. A consumer that cannot read the folder must say so, and may say so only when something in
  the folder cannot be read.
- TA_SAMA_NAZWA: each consumer that names a Status okresu (Tablica okresów, the start cards, Uzupełnienie with its
  ``settled``) names the reference one.

The states are few (``SCOPES``), so the checker walks all of them, once each, in a fresh Centrum: no sampling.
"""

from __future__ import annotations

import argparse
import enum
import itertools
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from fastapi.testclient import TestClient

from atrapy import pliki_taty
from atrapy.preparation import PreparationFixture, make_preparation_fixture
from atrapy.settlement import MARKED, worker_list, write_quantity_source, write_template
from atrapy.skrzynka_raportow import FakeInbox
from eksplorator import Excuse, Kind, excuse_line, excused, gone_lines, verdict
from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.catalog import CATALOG
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import NO_AUTOSTART
from rozliczenia.centrum.settings.folders import FOLDERS
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.dad_files import DadFiles
from rozliczenia.input_checks import check_preparation, check_settlement
from rozliczenia.message import StopError
from rozliczenia.report_entering import EnteringInputs, ReportEnteringParts, ReportStateInMemory, SavedState, enter_from_mail
from rozliczenia.run_context import RunContext, check_on_disk
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.wall_clock import local_now
from rozliczenia.worker_list import WorkerList
from rozliczenia.worker_periods import WorkerPeriods
from rozliczenia.worker_report_inbox import PasswordRejected
from rozliczenia.worker_reports import OwnEntries
import rozjazd_modelu

REPO_ROOT = Path(__file__).resolve().parents[4]

PERIOD = parse_period_token("08_14_09_2026")
NEXT_PERIOD = parse_period_token("15_21_09_2026")
# Wednesday after the period: the period is the last complete one, so Tablica okresów shows it even without its Folder
# okresu, and Wpisanie raportów, deployed on the period's Tuesday, reads both periods.
TODAY = date(2026, 9, 16)
CLICKED_AT = datetime(2026, 9, 16, 12)
WORKER = "Adrian Testowy"


# --- Folder okresu states --------------------------------------------------------------------------------------------


class Folder(enum.Enum):
    BRAK = "brak Folderu okresu"
    JEST = "Folder okresu"
    NIEDOSTEPNY = "Folder okresu bez dostępu"


class Internal(enum.Enum):
    BRAK = "bez Rozliczenia wewnętrznego"
    PLIK = "Rozliczenie wewnętrzne"


class Collective(enum.Enum):
    BRAK = "bez Pliku zbiorczego"
    PLIK = "Plik zbiorczy"
    NIEDOSTEPNY = "Plik zbiorczy bez dostępu"


class Workers(enum.Enum):
    BRAK = "bez Folderu rozliczeń pracowników"
    PUSTY = "pusty Folder rozliczeń pracowników"
    Z_ROZLICZENIEM = "Folder rozliczeń pracowników z Rozliczeniem pracownika"
    NIEDOSTEPNY = "Folder rozliczeń pracowników bez dostępu"


@dataclass(frozen=True)
class FolderState:
    folder: Folder
    internal: Internal
    collective: Collective
    workers: Workers

    def describe(self) -> str:
        if self.folder is Folder.BRAK:
            return f"{Folder.BRAK.value} {PERIOD.token}"
        return f"{self.folder.value} {PERIOD.token}: {self.internal.value}, {self.collective.value}, {self.workers.value}"

    @property
    def unreadable(self) -> bool:
        """Something in the folder cannot be read, so a consumer may answer that it cannot read it."""

        return (
            self.folder is Folder.NIEDOSTEPNY
            or self.collective is Collective.NIEDOSTEPNY
            or self.workers is Workers.NIEDOSTEPNY
        )


def states(
    folder: Sequence[Folder] = (Folder.JEST,),
    internal: Sequence[Internal] = tuple(Internal),
    collective: Sequence[Collective] = tuple(Collective),
    workers: Sequence[Workers] = tuple(Workers),
) -> frozenset[FolderState]:
    return frozenset(FolderState(*combination) for combination in itertools.product(folder, internal, collective, workers))


NO_FOLDER = FolderState(Folder.BRAK, Internal.BRAK, Collective.BRAK, Workers.BRAK)
READABLE_COLLECTIVE = (Collective.BRAK, Collective.PLIK)
READABLE_WORKERS = (Workers.BRAK, Workers.PUSTY, Workers.Z_ROZLICZENIEM)
READABLE = states(collective=READABLE_COLLECTIVE, workers=READABLE_WORKERS)


class System(enum.Enum):
    WINDOWS = "Windows"
    INNY = "macOS i Linux"


# Where the states are built. Windows (Bypass Traverse Checking) answers a name missing from a folder without access
# „no such file”, and macOS and Linux under ``chmod 0`` „access denied”, so the consumers answer differently there.
SYSTEM = System.WINDOWS if sys.platform == "win32" else System.INNY


def unit(scope: str, system: System) -> str:
    """The unit of ``Excuse.after`` for a scope run on one system: an entry that shows only on Windows names it."""

    return f"{scope} na {system.value}"


@dataclass(frozen=True)
class Scope:
    name: str
    states: frozenset[FolderState]
    needs_unreadable: bool
    what: str


SCOPES = {
    scope.name: scope
    for scope in (
        Scope(
            "czytelne",
            frozenset({NO_FOLDER}) | READABLE,
            needs_unreadable=False,
            what="brak Folderu okresu i każdy Folder okresu z plikami, które da się odczytać",
        ),
        Scope(
            "niedostepne",
            (states() - READABLE)
            | states(folder=(Folder.NIEDOSTEPNY,), collective=READABLE_COLLECTIVE, workers=READABLE_WORKERS),
            needs_unreadable=True,
            what="Plik zbiorczy, Folder rozliczeń pracowników albo sam Folder okresu bez dostępu",
        ),
    )
}


# --- Reference Status okresu -----------------------------------------------------------------------------------------


class Status(enum.Enum):
    # Names from GLOSSARY.md, as Dad reads them on the board (copied on purpose, docs/agents/skille.md).
    BRAK_PLIKOW = "Brak plików okresu"
    PRZYGOTOWANY = "Plik zbiorczy przygotowany"
    GOTOWE = "Rozliczenia pracowników gotowe"


def reference(state: FolderState) -> Status | None:
    """The Status okresu of the folder by GLOSSARY.md; ``None`` when the Folder okresu cannot be read.

    GLOSSARY.md names a folder with Rozliczenia pracowników but without a Plik zbiorczy twice (Brak plików okresu „gdy
    nie ma Pliku zbiorczego”, Rozliczenia pracowników gotowe „gdy jest Folder rozliczeń pracowników”); Droga okresu
    settles it: „Okres z Rozliczeniami pracowników jest zamknięty”. ``PeriodFolderObservation.status`` decides the same,
    and ``model/definicje.json`` reports when it changes.
    """

    if state.folder is Folder.NIEDOSTEPNY:
        return None
    if state.folder is Folder.BRAK:
        return Status.BRAK_PLIKOW
    if state.workers is not Workers.BRAK:
        return Status.GOTOWE
    if state.collective is not Collective.BRAK:
        return Status.PRZYGOTOWANY
    return Status.BRAK_PLIKOW


# --- Consumers and their answers -------------------------------------------------------------------------------------


class Consumer(enum.Enum):
    TABLICA = "Tablica okresów"
    TABLICA_PRZYGOTUJ = "Tablica okresów, krok „Przygotuj plik zbiorczy”"
    TABLICA_ROZLICZ = "Tablica okresów, krok „Utwórz rozliczenia pracowników”"
    KARTA_PRZYGOTOWANIA = "karta startu Przygotowania pliku zbiorczego"
    KARTA_PRZEBIEGU = "karta startu Przebiegu rozliczeń"
    KARTA_WYCENY = "karta startu Wyceny w efenix"
    UZUPELNIANIE = "Uzupełnienie (quantities-to-fill)"
    PODGLAD_REGUL = "podgląd zmiany Reguł ilości (quantity-rules/preview)"
    LISTA_ROZNIC = "lista różnic Kontroli ilości (quantity-rules/differences)"
    WPISANIE_RAPORTOW = "Wpisanie raportów (enter_from_mail)"
    START_PRZYGOTOWANIA = "Sprawdzanie Przygotowania pliku zbiorczego (check_preparation)"
    START_PRZEBIEGU = "Sprawdzanie Przebiegu rozliczeń (check_settlement)"


class Act(enum.Enum):
    DZIALA = "działa na okresie"
    ODMAWIA = "odmawia"
    NIE_CZYTA = "mówi, że nie może odczytać folderu"


# Rule OTWARCIE: the one Status okresu in which each process may act on the period.
ALLOWED: dict[Consumer, Status] = {
    Consumer.TABLICA_PRZYGOTUJ: Status.BRAK_PLIKOW,
    Consumer.START_PRZYGOTOWANIA: Status.BRAK_PLIKOW,
    Consumer.WPISANIE_RAPORTOW: Status.BRAK_PLIKOW,
    Consumer.TABLICA_ROZLICZ: Status.PRZYGOTOWANY,
    Consumer.KARTA_PRZEBIEGU: Status.PRZYGOTOWANY,
    Consumer.START_PRZEBIEGU: Status.PRZYGOTOWANY,
    Consumer.UZUPELNIANIE: Status.PRZYGOTOWANY,
    Consumer.PODGLAD_REGUL: Status.GOTOWE,
    Consumer.LISTA_ROZNIC: Status.GOTOWE,
}

# Rule TA_SAMA_NAZWA: the consumers that show Dad a Status okresu.
NAMING = frozenset(
    {Consumer.TABLICA, Consumer.KARTA_PRZYGOTOWANIA, Consumer.KARTA_PRZEBIEGU, Consumer.KARTA_WYCENY, Consumer.UZUPELNIANIE}
)


@dataclass(frozen=True)
class Answer:
    """``act``: what the consumer does for its process (rule OTWARCIE); ``named``: the Status okresu it shows, or
    ``Act.NIE_CZYTA``, or ``None`` when it shows none for the period (rule TA_SAMA_NAZWA)."""

    consumer: Consumer
    act: Act | None = None
    named: Status | Act | None = None
    detail: str = ""


@dataclass(frozen=True)
class Observed:
    """What an Excuse's shape judges: the folder state, the consumer that broke the rule, what it did and the system the
    state was built on."""

    state: FolderState
    consumer: Consumer
    act: Act | None = None
    system: System = SYSTEM


@dataclass(frozen=True)
class Violation:
    rule: str
    observed: Observed
    text: str


# Komunikat codes and texts Dad reads, copied on purpose (docs/agents/skille.md, „Co wyrocznia bierze z src”): a code
# renamed in src makes the answer unexpected and the check red, instead of following src silently.
UNREADABLE_STOPS = frozenset({"NIEDOSTEPNY_FOLDER", "NIEDOSTEPNY_PLIK_ZBIORCZY", "BLAD_ZAPISU", "RAPORTY_NIEDOSTEPNY_FOLDER_OKRESOW"})
PASSWORD_REJECTED = "RAPORTY_HASLO_ODRZUCONE"
FOLDER_UNREADABLE = "Nie udało się odczytać folderu"
# A rule of the Reguły ilości from the Wydanie, which the preview takes away (copied on purpose: a renamed rule makes the
# preview refuse with 404 and the check red).
PREVIEW_RULE = "t-umowa-u"
NO_COLLECTIVE_FILE = "Nie ma Pliku zbiorczego"
COLLECTIVE_FILE_UNREADABLE = "Nie można teraz odczytać Pliku zbiorczego"
# Actions of the steps on the board, the contract the page reads.
PREPARE_STEP = "prepare_collective_file"
SETTLE_STEP = "create_worker_settlements"


class Unexpected(Exception):
    """A consumer answered in a way the checker does not know how to read; reported as a new violation."""


# --- Files of one run ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Inputs:
    """Synthetic files every consumer reads besides the Folder okresu: Rejestr zleceń, Wzorce, Lista Wykonawców
    with the addresses of the Wykonawcy, and the bytes of a Plik zbiorczy that Uzupełnienie reads."""

    preparation: PreparationFixture
    worker_template: Path
    workers: WorkerList
    collective_bytes: Path


def make_inputs(root: Path) -> Inputs:
    root.mkdir()
    preparation = make_preparation_fixture(root)
    worker_template = root / "config" / pliki_taty.WORKER_TEMPLATE_NAME
    write_template(worker_template)
    workers = worker_list(addresses={"adrian.testowy": ["adrian.testowy@przyklad.invalid"]})
    collective_bytes = root / "plik-zbiorczy.xlsx"
    write_quantity_source(collective_bytes, [MARKED, {}])
    return Inputs(preparation, worker_template, workers, collective_bytes)


@contextmanager
def built(periods: Path, state: FolderState, inputs: Inputs) -> Iterator[None]:
    """The Folder okresu of ``state`` in ``periods``; access taken away for the time of the block.

    A path the state calls unreadable that still reads after ``take_access`` stops the run: the checker would judge a
    state it did not build.
    """

    locked: list[tuple[Path, bool]] = []
    try:
        if state.folder is not Folder.BRAK:
            directory = periods / PERIOD.token
            directory.mkdir()
            if state.internal is Internal.PLIK:
                shutil.copyfile(inputs.collective_bytes, directory / pliki_taty.internal_settlement_name(PERIOD.token))
            if state.collective is not Collective.BRAK:
                collective = directory / pliki_taty.collective_file_name(PERIOD.token)
                shutil.copyfile(inputs.collective_bytes, collective)
                if state.collective is Collective.NIEDOSTEPNY:
                    locked.append((collective, False))
            if state.workers is not Workers.BRAK:
                workers = directory / pliki_taty.worker_settlements_name(PERIOD.token)
                workers.mkdir()
                if state.workers is Workers.Z_ROZLICZENIEM:
                    shutil.copyfile(inputs.collective_bytes, workers / pliki_taty.worker_settlement_name(PERIOD.token, WORKER))
                if state.workers is Workers.NIEDOSTEPNY:
                    locked.append((workers, True))
            if state.folder is Folder.NIEDOSTEPNY:
                locked.append((directory, True))
        for path, folder in locked:
            take_access(path, folder=folder)
        for path, folder in locked:
            if not refuses_reading(path, folder=folder):
                raise RuntimeError(f"{path.name} daje się odczytać, choć stan mówi, że jest bez dostępu")
        yield
    finally:
        for path, _ in reversed(locked):
            give_access(path)


def take_access(path: Path, *, folder: bool) -> None:
    """Takes the user's access to read ``path`` away, as Dad loses it to a folder or file of the Folder okresu.

    On macOS and Linux ``chmod 0``. On Windows ``chmod`` only sets the read-only attribute, so a deny entry for the user
    (``icacls``) takes reading the data away; on a folder it also takes its attributes and is inherited by everything in
    it, so a file inside cannot be read or even looked up, as under ``chmod 0``.
    """

    if sys.platform == "win32":
        rights = "(OI)(CI)(RD,RA)" if folder else "(RD)"
        subprocess.run(["icacls", str(path), "/deny", f"{os.environ['USERNAME']}:{rights}"], check=True, capture_output=True)
    else:
        path.chmod(0)


def give_access(path: Path) -> None:
    """Gives back what ``take_access`` took, so the run can delete its temporary folder."""

    if sys.platform == "win32":
        subprocess.run(["icacls", str(path), "/remove:d", os.environ["USERNAME"]], check=True, capture_output=True)
    else:
        path.chmod(stat.S_IRWXU)


def refuses_reading(path: Path, *, folder: bool) -> bool:
    """Whether listing the folder or opening the file ``path`` gives ``PermissionError``, as a consumer would see it."""

    try:
        if folder:
            with os.scandir(path):
                pass
        else:
            with path.open("rb"):
                pass
    except PermissionError:
        return True
    return False


def access_can_be_taken() -> bool:
    """Whether ``take_access`` makes a folder and a file in it unreadable here: not for root on macOS or Linux, whom
    ``chmod`` does not stop, and not where ``icacls`` fails on Windows."""

    with tempfile.TemporaryDirectory(prefix="status-okresu-proba-") as probe:
        folder = Path(probe) / "folder"
        folder.mkdir()
        inside = folder / "plik"
        inside.write_bytes(b"")
        try:
            take_access(folder, folder=True)
        except (OSError, subprocess.CalledProcessError):
            return False
        try:
            return refuses_reading(folder, folder=True) and refuses_reading(inside, folder=False)
        finally:
            give_access(folder)


# --- Asking each consumer --------------------------------------------------------------------------------------------


class _Platform:
    """Centrum's link to the desktop; the checker never opens a file or a dialog."""

    def open_path(self, path: Path) -> None:
        raise AssertionError(f"sprawdzenie nie otwiera {path.name}")

    def choose_file(self, title: str, filetypes: object) -> Path | None:
        return None

    def choose_folder(self, title: str) -> Path | None:
        return None


def _centrum(case: Path, periods: Path) -> TestClient:
    config = case / "config"
    config.mkdir()
    log = CentrumLog(config / "centrum.log")
    app = create_app(
        config=config,
        platform=_Platform(),
        autostart=NO_AUTOSTART,
        log=log,
        shutdown=Shutdown(log),
        today=lambda: TODAY,
        # No Historia: the Wycena w efenix of the period was never run.
        catalog=CATALOG.with_metrics({key: config / f"metryki-{key}.jsonl" for key in CATALOG.metrics_paths}),
    )
    CentrumSettings(
        config,
        log=log,
        now=local_now,
        pause=lambda _: None,
        autostart=NO_AUTOSTART,
        periods=WorkerPeriods(DadFiles()),
        # The folder change below refuses nothing, so no rule sentence needs column names.
        column_names=lambda: {},
    ).change(FOLDERS, lambda folders: replace(folders, periods_directory=periods))
    # Without ``with``: the lifespan (Powiadomienia, Skrzynka Zgłoszeń, Kolejka wysyłki) never starts.
    return TestClient(app, base_url="http://127.0.0.1")


def _status_of(label: str) -> Status:
    for status in Status:
        if status.value == label:
            return status
    raise Unexpected(f"nieznana nazwa Statusu okresu {label!r}")


def _unreadable_refusal(response: Any) -> str | None:  # TestClient's response type lives in httpx or httpx2
    """The refusal Centrum gives for a folder it cannot read (HTTP 500 with its Komunikat), else ``None``."""

    if response.status_code != 500:
        return None
    message = str(response.json().get("message", ""))
    return message if message.startswith(FOLDER_UNREADABLE) else None


def ask_board(client: TestClient) -> list[Answer]:
    response = client.get("/api/periods")
    board = (Consumer.TABLICA, Consumer.TABLICA_PRZYGOTUJ, Consumer.TABLICA_ROZLICZ)
    if (unreadable := _unreadable_refusal(response)) is not None:
        return [Answer(consumer, Act.NIE_CZYTA, Act.NIE_CZYTA, unreadable) for consumer in board]
    if response.status_code != 200:
        raise Unexpected(f"Tablica okresów: HTTP {response.status_code} {response.text[:200]}")
    [row] = [row for row in response.json()["periods"] if row["token"] == PERIOD.token]
    steps = [row["next_step"]["action"], (row["secondary_step"] or {}).get("action")]
    shown = f"Status okresu „{row['status_label']}”, następny krok „{row['next_step']['label']}”"
    return [
        Answer(Consumer.TABLICA, named=_status_of(row["status_label"]), detail=shown),
        Answer(Consumer.TABLICA_PRZYGOTUJ, Act.DZIALA if PREPARE_STEP in steps else Act.ODMAWIA, detail=shown),
        Answer(Consumer.TABLICA_ROZLICZ, Act.DZIALA if SETTLE_STEP in steps else Act.ODMAWIA, detail=shown),
    ]


def ask_cards(client: TestClient) -> list[Answer]:
    cards = (
        ("preparation", Consumer.KARTA_PRZYGOTOWANIA),
        ("settlement", Consumer.KARTA_PRZEBIEGU),
        ("efenix", Consumer.KARTA_WYCENY),
    )
    response = client.get("/api/runs/setup")
    if (unreadable := _unreadable_refusal(response)) is not None:
        return [Answer(consumer, Act.NIE_CZYTA, Act.NIE_CZYTA, unreadable) for _, consumer in cards]
    if response.status_code != 200:
        raise Unexpected(f"karty startu: HTTP {response.status_code} {response.text[:200]}")
    processes = {process["process"]: process for process in response.json()["processes"]}
    answers = []
    for key, consumer in cards:
        chosen = [choice for choice in processes[key]["periods"] if choice["token"] == PERIOD.token]
        named = _status_of(chosen[0]["status_label"]) if chosen else None
        detail = f"okres do wyboru z etykietą „{chosen[0]['status_label']}”" if chosen else "okresu nie ma do wyboru"
        answers.append(Answer(consumer, Act.DZIALA if chosen else Act.ODMAWIA, named, detail))
    return answers


def ask_filling(client: TestClient) -> Answer:
    response = client.get(f"/api/periods/{PERIOD.token}/quantities-to-fill")
    if (unreadable := _unreadable_refusal(response)) is not None:
        return Answer(Consumer.UZUPELNIANIE, Act.NIE_CZYTA, Act.NIE_CZYTA, unreadable)
    if response.status_code != 200:
        raise Unexpected(f"Uzupełnienie: HTTP {response.status_code} {response.text[:200]}")
    page = response.json()
    if page["state"] == "ready":
        if page["settled"]:
            return Answer(Consumer.UZUPELNIANIE, Act.ODMAWIA, Status.GOTOWE, "podgląd po Przebiegu rozliczeń (settled)")
        return Answer(Consumer.UZUPELNIANIE, Act.DZIALA, Status.PRZYGOTOWANY, "Ilości do uzupełnienia do wpisania")
    what = str(page["message"]["what"])
    if what.startswith(COLLECTIVE_FILE_UNREADABLE):
        return Answer(Consumer.UZUPELNIANIE, Act.NIE_CZYTA, Act.NIE_CZYTA, what)
    if what.startswith(NO_COLLECTIVE_FILE):
        return Answer(Consumer.UZUPELNIANIE, Act.ODMAWIA, None, what)
    raise Unexpected(f"Uzupełnienie: Komunikat {what!r}")


def ask_rules_preview(client: TestClient) -> Answer:
    """Whether the preview of a Reguły ilości change takes the period: only a period after Przebieg rozliczeń, whose
    quantities Dad settled; a Plik zbiorczy it takes but cannot read it names among ``unread``."""

    response = client.post(
        "/api/settings/quantity-rules/preview",
        json={"kind": "remove", "rule_id": PREVIEW_RULE},
        headers={"Origin": "http://127.0.0.1"},
    )
    if (unreadable := _unreadable_refusal(response)) is not None:
        return Answer(Consumer.PODGLAD_REGUL, Act.NIE_CZYTA, detail=unreadable)
    if response.status_code != 200:
        raise Unexpected(f"podgląd Reguł ilości: HTTP {response.status_code} {response.text[:200]}")
    preview = response.json()
    if preview["state"] == "no_settled_periods":
        return Answer(Consumer.PODGLAD_REGUL, Act.ODMAWIA, detail="nie ma okresu po Przebiegu rozliczeń")
    if preview["state"] != "ready":
        raise Unexpected(f"podgląd Reguł ilości: stan {preview['state']!r}")
    if PERIOD.token in preview["unread"]:
        return Answer(Consumer.PODGLAD_REGUL, Act.DZIALA, detail="bierze okres, a Pliku zbiorczego nie dało się przeczytać")
    if [file["period"] for file in preview["files"]] == [PERIOD.token]:
        return Answer(Consumer.PODGLAD_REGUL, Act.DZIALA, detail="liczy na Pliku zbiorczym okresu")
    raise Unexpected(f"podgląd Reguł ilości: pliki {preview['files']}, nieprzeczytane {preview['unread']}")


def ask_differences(client: TestClient) -> Answer:
    """Whether the list of Kontrola ilości differences in the Reguły ilości section takes the period: only a period
    after Przebieg rozliczeń, like the preview; a Plik zbiorczy it takes but cannot read it names among ``unread``."""

    response = client.get("/api/settings/quantity-rules/differences")
    if (unreadable := _unreadable_refusal(response)) is not None:
        return Answer(Consumer.LISTA_ROZNIC, Act.NIE_CZYTA, detail=unreadable)
    if response.status_code != 200:
        raise Unexpected(f"lista różnic: HTTP {response.status_code} {response.text[:200]}")
    found = response.json()
    if found["state"] == "no_settled_periods":
        return Answer(Consumer.LISTA_ROZNIC, Act.ODMAWIA, detail="nie ma okresu po Przebiegu rozliczeń")
    if found["state"] != "ready":
        raise Unexpected(f"lista różnic: stan {found['state']!r}")
    if PERIOD.token in found["unread"]:
        return Answer(Consumer.LISTA_ROZNIC, Act.DZIALA, detail="bierze okres, a Pliku zbiorczego nie dało się przeczytać")
    if [file["period"] for file in found["files"]] == [PERIOD.token]:
        return Answer(Consumer.LISTA_ROZNIC, Act.DZIALA, detail="liczy różnice na Pliku zbiorczym okresu")
    raise Unexpected(f"lista różnic: pliki {found['files']}, nieprzeczytane {found['unread']}")


def ask_entering(inputs: Inputs, periods: Path) -> Answer:
    """From which day Wpisanie raportów, deployed on the period's Tuesday, reads the Skrzynka raportów (``Window.first``).

    The Skrzynka refuses the password, so the click stops right after the window is set and before INTERMAX is read.
    """

    inbox = FakeInbox(outcome=PasswordRejected())
    entering = EnteringInputs(
        inputs.preparation.register_path,
        periods,
        inputs.workers,
        ReportEnteringParts(inbox, ReportStateInMemory(SavedState(PERIOD.tuesday, OwnEntries.EMPTY))),
        now=lambda: CLICKED_AT,
    )
    try:
        enter_from_mail(entering, RunContext())
    except StopError as stop:
        code = stop.message.code
        if code in UNREADABLE_STOPS:
            return Answer(Consumer.WPISANIE_RAPORTOW, Act.NIE_CZYTA, detail=f"zatrzymanie {code}")
        if code == PASSWORD_REJECTED and inbox.days == [PERIOD.tuesday]:
            return Answer(
                Consumer.WPISANIE_RAPORTOW,
                Act.DZIALA,
                detail=f"czyta Skrzynkę raportów od {PERIOD.tuesday:%d.%m.%Y}, więc wpisze do dni okresu",
            )
        if code == PASSWORD_REJECTED and inbox.days == [NEXT_PERIOD.tuesday]:
            return Answer(
                Consumer.WPISANIE_RAPORTOW,
                Act.ODMAWIA,
                detail=f"czyta Skrzynkę raportów dopiero od {NEXT_PERIOD.tuesday:%d.%m.%Y}: okres zamknięty",
            )
        raise Unexpected(f"Wpisanie raportów: zatrzymanie {code}, odczyty skrzynki od {inbox.days}") from stop
    raise Unexpected("Wpisanie raportów skończyło się bez zatrzymania, choć Skrzynka odrzuca hasło")


def _start(consumer: Consumer, check: Callable[[], object]) -> Answer:
    try:
        check()
    except StopError as stop:
        code = stop.message.code
        return Answer(consumer, Act.NIE_CZYTA if code in UNREADABLE_STOPS else Act.ODMAWIA, detail=f"zatrzymanie {code}")
    return Answer(consumer, Act.DZIALA, detail="Sprawdzanie przechodzi")


def ask_starts(inputs: Inputs, periods: Path) -> list[Answer]:
    fixture = inputs.preparation
    # Centrum gives Przebieg rozliczeń the Plik zbiorczy path of the Folder okresu (``PeriodStarts.prepare``).
    collective_file = periods / PERIOD.token / pliki_taty.collective_file_name(PERIOD.token)
    return [
        _start(
            Consumer.START_PRZYGOTOWANIA,
            lambda: check_preparation(
                fixture.register_path,
                periods,
                PERIOD.token,
                inputs.workers,
                internal_template=fixture.internal_template_path,
                collective_template=fixture.collective_template_path,
                template_check=check_on_disk,
            ),
        ),
        _start(
            Consumer.START_PRZEBIEGU,
            lambda: check_settlement(collective_file, inputs.workers, inputs.worker_template, check_on_disk),
        ),
    ]


def ask_all(case: Path, state: FolderState, inputs: Inputs) -> list[Answer]:
    periods = case / "INEA"
    periods.mkdir(parents=True)
    with built(periods, state, inputs):
        client = _centrum(case, periods)
        return [
            *ask_board(client),
            *ask_cards(client),
            ask_filling(client),
            ask_rules_preview(client),
            ask_differences(client),
            ask_entering(inputs, periods),
            *ask_starts(inputs, periods),
        ]


# --- Rules -----------------------------------------------------------------------------------------------------------


def _expected(status: Status | None) -> str:
    return "nieznany, bo Folderu okresu nie da się odczytać" if status is None else f"„{status.value}”"


def judge(state: FolderState, answers: Sequence[Answer]) -> list[Violation]:
    status = reference(state)
    found = []
    for answer in answers:
        observed = Observed(state, answer.consumer, answer.act)
        if answer.consumer in ALLOWED and answer.act is not None:
            allowed = status is ALLOWED[answer.consumer]
            wrong = {
                Act.DZIALA: not allowed,
                Act.ODMAWIA: allowed or status is None,
                Act.NIE_CZYTA: not state.unreadable,
            }[answer.act]
            if wrong:
                found.append(
                    Violation(
                        "OTWARCIE",
                        observed,
                        f"{answer.consumer.value} {answer.act.value} ({answer.detail}), a Status okresu jest "
                        f"{_expected(status)}; działać wolno tylko przy „{ALLOWED[answer.consumer].value}”",
                    )
                )
        named = answer.named
        if answer.consumer not in NAMING or named is None:
            continue
        if (not state.unreadable) if named is Act.NIE_CZYTA else named is not status:
            found.append(
                Violation(
                    "TA_SAMA_NAZWA",
                    observed,
                    f"{answer.consumer.value} pokazuje „{named.value}” ({answer.detail}), a Status okresu jest {_expected(status)}",
                )
            )
    return found


# --- Excuses ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StateShape:
    """The shape of a known finding or accepted risk, each part from its story (#920):

    - ``states``: the Folder okresu states in which the consumer breaks the rule, exactly;
    - ``consumers``: the consumers that break it there;
    - ``acts``: what they do there (every act when the story does not narrow it);
    - ``systems``: the systems on which they do it (every system when the story does not narrow it).

    Each part that narrows something has in ``check_status_okresu_mutations.BOUNDARIES`` a broken variant just outside
    it, which must give a new violation (``tests/test_mutacje_skilli.py``)."""

    states: frozenset[FolderState]
    consumers: frozenset[Consumer]
    acts: frozenset[Act] = frozenset(Act)
    systems: frozenset[System] = frozenset(System)

    def holds(self, observed: Observed) -> bool:
        return (
            observed.state in self.states
            and observed.consumer in self.consumers
            and observed.act in self.acts
            and observed.system in self.systems
        )


# Windows: a Folder okresu without access, without a Plik zbiorczy, its other files readable or not there.
WINDOWS_UNREADABLE_WITHOUT_COLLECTIVE = states(
    folder=(Folder.NIEDOSTEPNY,), collective=(Collective.BRAK,), workers=READABLE_WORKERS
)


KNOWN_FINDINGS: tuple[Excuse[StateShape], ...] = (
    Excuse(
        "Wpisanie raportów w zamkniętym okresie",
        "OTWARCIE",
        "Folder rozliczeń pracowników jest, a Pliku zbiorczego nie ma (tata przeniósł, usunął albo przemianował go po "
        "Przebiegu rozliczeń): Tablica okresów pokazuje „Rozliczenia pracowników gotowe” i „Okres zamknięty”, a "
        "report_entering.closed_periods patrzy tylko na collective_file_exists, więc Wpisanie raportów czyta Skrzynkę raportów "
        "od wtorku okresu i wpisuje do INTERMAX w jego dniach",
        StateShape(
            states(collective=(Collective.BRAK,), workers=(Workers.PUSTY, Workers.Z_ROZLICZENIEM)),
            frozenset({Consumer.WPISANIE_RAPORTOW}),
        ),
        after=("czytelne",),
    ),
    Excuse(
        "Przygotowanie w zamkniętym okresie",
        "OTWARCIE",
        "Folder rozliczeń pracowników jest (także bez dostępu), a obu plików okresu nie ma: Tablica okresów nie daje "
        "kroku „Przygotuj plik zbiorczy”, bo okres jest zamknięty, a ensure_period_files_absent sprawdza tylko "
        "Rozliczenie wewnętrzne i Plik zbiorczy, więc Sprawdzanie Przygotowania przechodzi i Przygotowanie zapisze "
        "nowy Plik zbiorczy do okresu z Rozliczeniami pracowników",
        StateShape(
            states(
                internal=(Internal.BRAK,),
                collective=(Collective.BRAK,),
                workers=(Workers.PUSTY, Workers.Z_ROZLICZENIEM, Workers.NIEDOSTEPNY),
            ),
            frozenset({Consumer.START_PRZYGOTOWANIA}),
        ),
        after=("czytelne", "niedostepne"),
    ),
    Excuse(
        "Windows: Folder okresu bez dostępu jak okres bez Pliku zbiorczego",
        "OTWARCIE",
        "na Windows Folder okresu bez dostępu odpowiada na nazwę Pliku zbiorczego, którego w nim nie ma, „nie ma takiego "
        "pliku” (Bypass Traverse Checking), a nie „odmowa dostępu”: Tablica okresów mówi „Nie udało się odczytać "
        "folderu”, a Uzupełnienie mówi „Nie ma Pliku zbiorczego tego okresu” i Sprawdzanie Przebiegu rozliczeń "
        "zatrzymuje się na BRAK_PLIKU_ZBIORCZEGO, zamiast powiedzieć, że folderu nie da się odczytać",
        StateShape(
            WINDOWS_UNREADABLE_WITHOUT_COLLECTIVE,
            frozenset({Consumer.UZUPELNIANIE, Consumer.START_PRZEBIEGU}),
            acts=frozenset({Act.ODMAWIA}),
            systems=frozenset({System.WINDOWS}),
        ),
        after=(unit("niedostepne", System.WINDOWS),),
    ),
    Excuse(
        "Windows: Przygotowanie w Folderze okresu bez dostępu",
        "OTWARCIE",
        "na Windows Folder okresu bez dostępu odpowiada na nazwy obu plików okresu, których w nim nie ma, „nie ma "
        "takiego pliku”: Tablica okresów mówi „Nie udało się odczytać folderu”, a ensure_period_files_absent nie "
        "widzi żadnego pliku okresu, więc Sprawdzanie Przygotowania przechodzi w okresie, którego Statusu nikt nie zna, "
        "także gdy jest w nim Folder rozliczeń pracowników",
        StateShape(
            states(folder=(Folder.NIEDOSTEPNY,), internal=(Internal.BRAK,), collective=(Collective.BRAK,), workers=READABLE_WORKERS),
            frozenset({Consumer.START_PRZYGOTOWANIA}),
            acts=frozenset({Act.DZIALA}),
            systems=frozenset({System.WINDOWS}),
        ),
        after=(unit("niedostepne", System.WINDOWS),),
    ),
)

ACCEPTED_RISKS: tuple[Excuse[StateShape], ...] = (
    Excuse(
        "ADR 0005",
        "OTWARCIE",
        "samo Rozliczenie wewnętrzne po przerwanej publikacji: Tablica okresów pokazuje „Brak plików okresu” i krok "
        "„Przygotuj plik zbiorczy”, a Sprawdzanie Przygotowania zatrzymuje się na PLIK_OKRESU_ISTNIEJE i wskazuje plik, "
        "jak przyjmuje ADR 0005",
        StateShape(
            states(internal=(Internal.PLIK,), collective=(Collective.BRAK,), workers=(Workers.BRAK,)),
            frozenset({Consumer.START_PRZYGOTOWANIA}),
        ),
        after=("czytelne",),
    ),
)


# --- Exploration and report ------------------------------------------------------------------------------------------


@dataclass
class ScopeReport:
    scope: Scope
    states: int = 0
    seconds: float = 0.0
    violations: list[tuple[Violation, list[str]]] = field(default_factory=list)
    skipped: str = ""


def story(state: FolderState, answers: Sequence[Answer]) -> list[str]:
    return [
        state.describe(),
        f"Status okresu według GLOSSARY.md: {_expected(reference(state))}",
        *(f"{answer.consumer.value}: {answer.act.value + ', ' if answer.act else ''}{answer.detail}" for answer in answers),
    ]


def explore(scope: Scope, inputs: Inputs, root: Path, *, can_take_access: bool) -> ScopeReport:
    report = ScopeReport(scope)
    if scope.needs_unreadable and not can_take_access:
        report.skipped = "system nie odbiera tu dostępu do folderu (root, którego chmod nie zatrzymuje, albo icacls bez skutku)"
        return report
    started = time.perf_counter()
    for number, state in enumerate(sorted(scope.states, key=FolderState.describe)):
        case = root / f"{scope.name}-{number}"
        try:
            answers = ask_all(case, state, inputs)
        except Unexpected as error:
            report.violations.append(
                (Violation("NIEOCZEKIWANA_ODPOWIEDZ", Observed(state, Consumer.TABLICA), str(error)), [state.describe()])
            )
            continue
        except Exception:  # noqa: BLE001 - a crash of a consumer is a new violation with its traceback
            lines = traceback.format_exc().strip().splitlines()
            report.violations.append(
                (Violation("WYJATEK", Observed(state, Consumer.TABLICA), lines[-1]), [state.describe(), *lines[-6:]])
            )
            continue
        report.states += 1
        report.violations.extend((violation, story(state, answers)) for violation in judge(state, answers))
    report.seconds = time.perf_counter() - started
    return report


@dataclass(frozen=True)
class Outcome:
    lines: list[str]
    exit_code: int


VERDICT = "STATUS OKRESU"
GAP_REASON = ": stanów bez dostępu nie da się tu zbudować."


def summarize(reports: Sequence[ScopeReport], *, strict: bool = False) -> Outcome:
    lines = ["Status okresu u każdego konsumenta: sprawdzenie wyczerpujące", ""]
    new = gaps = 0
    counted: dict[str, Kind] = {}
    shown: set[tuple[str, str]] = set()
    for report in reports:
        lines.append(f"zakres {report.scope.name}: {report.scope.what}")
        if report.skipped:
            gaps += 1
            lines.extend((f"  LUKA MODELU: {report.skipped}", ""))
            continue
        lines.append(f"  stany Folderu okresu: {report.states}, czas: {report.seconds:.1f} s")
        excuses: dict[str, tuple[Kind, Excuse[StateShape], list[tuple[Violation, list[str]]]]] = {}
        for violation, steps in report.violations:
            found = excused(violation.rule, violation.observed, known=KNOWN_FINDINGS, accepted=ACCEPTED_RISKS)
            if found is not None:
                shown.update((found[1].name, name) for name in (report.scope.name, unit(report.scope.name, SYSTEM)))
            if found is None or strict:
                new += 1
                lines.append(f"  NARUSZENIE {violation.rule}: {violation.text}")
                lines.extend(f"    {number}. {step}" for number, step in enumerate(steps, start=1))
                continue
            excuses.setdefault(found[1].name, (found[0], found[1], []))[2].append((violation, steps))
        for name, (kind, entry, items) in excuses.items():
            counted[name] = kind
            lines.append(f"  {excuse_line(kind, entry)}")
            lines.append(f"    stany Folderu okresu: {len({violation.observed.state for violation, _ in items})}; pierwszy z nich:")
            lines.extend(f"    {number}. {step}" for number, step in enumerate(items[0][1], start=1))
        lines.append("")
    finished = [name for report in reports if not report.skipped for name in (report.scope.name, unit(report.scope.name, SYSTEM))]
    disappeared = gone_lines(finished, shown, known=KNOWN_FINDINGS, accepted=ACCEPTED_RISKS)
    lines.extend(disappeared)
    verdict_line, code = verdict(
        VERDICT,
        new=new,
        gone=len(disappeared),
        known=sum(kind == "known" for kind in counted.values()),
        accepted=sum(kind == "accepted" for kind in counted.values()),
        # A gap in one scope does not hide a new violation in another: the gap stays printed in its scope.
        gaps=0 if new else gaps,
        gap_reason=GAP_REASON,
    )
    lines.append(verdict_line)
    return Outcome(lines, code)


def run(scopes: Sequence[Scope], *, strict: bool = False) -> Outcome:
    can_take_access = access_can_be_taken()
    with tempfile.TemporaryDirectory(prefix="status-okresu-") as directory:
        root = Path(directory)
        inputs = make_inputs(root / "wejscie")
        return summarize([explore(scope, inputs, root, can_take_access=can_take_access) for scope in scopes], strict=strict)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exhaustive check that every consumer reads the same Status okresu.")
    parser.add_argument("--scope", choices=sorted(SCOPES), action="append", help="one scope; default: all")
    parser.add_argument("--strict", action="store_true", help="report known findings and accepted risks as violations too")
    arguments = parser.parse_args(argv)
    drift = rozjazd_modelu.rozjazd(Path(__file__).resolve().parents[1], REPO_ROOT)
    outcome = run([SCOPES[name] for name in (arguments.scope or SCOPES)], strict=arguments.strict)
    if drift is not None:
        print(f"UWAGA: {drift}\n")
    print("\n".join(outcome.lines))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
