"""Graf importów ``src/`` trzyma granice, które łamie jeden import.

Silnik nie zależy od Centrum rozliczeń (ADR 0004: Centrum to adapter Uruchomienia procesu). Moduły, z których
Centrum mówi o brakującej bibliotece, importują przy wczytaniu tylko bibliotekę standardową. Kopia opiekuna ponownego
startu (``_COPIED`` w ``restart_guardian.py``) importuje tylko bibliotekę standardową i siebie: moduł spoza kopii
kończy się ``ModuleNotFoundError``, bo pakiet ``rozliczenia`` kopii szuka modułów tylko w niej, a bibliotekę
spoza standardowej aktualizacja, którą opiekun kończy, mogła właśnie zmienić (``pip_install``). Test uruchomienia
kopii (``test_opiekun_ponownego_startu.py``) łapie brak modułu dopiero po minucie czekania na nową wersję, a
bibliotekę spoza standardowej, którą Python ma, przepuszcza.

Model efenix (``tools/lib/atrapy/model_efenix.py``) importuje tylko bibliotekę standardową, a Atrapa efenix
(``tools/lib/atrapy/atrapa_efenix.py``) tylko ją i model: z nimi testy i narzędzia porównują Wycenę w efenix, więc nie
biorą niczego z kodu pod testem (``src``). Okno w procesie (``tests/fixtures/okno_w_procesie.py``) bierze z kodu pod
testem tylko typy seamu okna efenix (klasy i aliasy typów z ``efenix_window``), a decyzje bierze
z modelu: okno, które wołałoby kod Wyceny, przestałoby być niezależną drugą stroną kontraktu z oknem przeglądarki.

Rdzeń Uruchomienia procesu i moduły, które procesy i Centrum biorą bez skoroszytu (``WITHOUT_WORKBOOK``), nie
wczytują warstwy skoroszytu (``template_file`` ani openpyxl), także przez inne moduły ``src/``, importem w funkcji i
w ``TYPE_CHECKING``: zmiana układu Wzorca albo biblioteki skoroszytu nie dotyka kodu, od którego zależy każdy proces.
Domknięcie idzie tylko po modułach ``src/``.

Katalog procesów (``centrum/catalog.py``), wpis procesu (``centrum/process_kind.py``) i wpisy w ``centrum/processes/``
nie wczytują FastAPI, gospodarza Uruchomień, Diagnozy, Konfiguracji, Tablicy okresów ani okna efenix, także przez inne
moduły ``src/``, importem w funkcji i w ``TYPE_CHECKING``: czytają je Skrypt dla maszyn, odtworzenie i wersje
komentarza bez serwera, a moduły Centrum, które pytają katalog, nie tworzą z nim cyklu. Wpisy procesów importuje tylko
katalog, a ``PreparedRun`` składa tylko ``Catalog.prepared``, także kopią (``replace`` z ``metrics=`` albo
z wyrażenia, którego tekst ma ``prepared`` bez względu na wielkość liter) i podklasą, w ``src/``, narzędziach, testach i skryptach skilli: rdzeń,
plik metryk i silnik procesu biorą się z jednego miejsca, które test podmienia (``Catalog.with_metrics``,
``Catalog.steered``, ``Catalog.with_engine``). Eksplorator Uruchomień daje swój silnik przez ``Catalog.with_engine``, więc
prawdziwe ``PreparedRun.conduct`` biegnie w każdym harmonogramie (przegląd #1127: podklasa z własnym ``conduct`` je
omijała). Konstruktor bez dowodu katalogu odrzuca też mypy, a dowód ``process_kind._CATALOG`` poza katalogiem ruff
(``TID251``), ale nie z ``# noqa: TID251``, więc konstruktor łapie ten test (przegląd #1371 r2).

Skrypt dla maszyn (``tools/uruchom_proces.py``) nie wczytuje FastAPI, starlette ani uvicorn, także przez moduły
``src/`` i importem w funkcji: Uruchomienie procesu nie potrzebuje serwera, a każdy start skryptu (w testach ok. stu)
płacił za jego import ok. 0,2 s.

Wersje komentarza Uruchomienia (``centrum/comment_versions.py``) nie robią I/O: biorą tylko typy i reguły z listy
``PURE_VERSIONS``, więc stopień wersji, los dziennika Wyceny i macierz startu Centrum (``close``) sprawdza test bez
plików i wątków.

``imaplib`` i ``smtplib`` importuje w ``src/`` tylko port Skrzynki raportów (``worker_report_inbox.py``), który
otwiera skrzynkę taty tylko do odczytu (ADR 0028) i wysyła z niej tylko Przypomnienia o raporcie (ADR 0030): inny moduł
z własnym połączeniem IMAP mógłby wysłać ``SELECT`` albo ``STORE``, a z SMTP mail z hasłem aplikacji poza portem.

Dwa sprawdzenia niżej łapią błąd kodu, który zapomniał strażnika reguły danych albo przerobił gotową wysyłkę Logów
(Logi Urwanego Uruchomienia przed 2ff78b6b3, ``replace`` w przeglądzie #1038).

- Wysyłkę Logów Uruchomienia daje tylko ``comment_versions.post_of`` jako ``LogsPost``. Jej ``replace`` i podklasę
  odrzuca typ (docstring ``comment_versions._VERSIONS``), ale nową ``Post`` złożoną z jej pól typ przepuszcza, bo
  ``Outbox.post`` bierze też gołą ``Post`` (przegląd #1371 r1). Dlatego wynik ``post_of`` idzie od razu do kolejki
  (``<kolejka>.post(post_of(wersja))``), a nazwę ``post_of`` test rozpoznaje po niej samej, z dowolną bazą i także
  jako napis, a nie po imporcie. Etykietę Logów (``comment_versions.LABEL``) kod poza ``post_of`` tylko podaje kolejce
  w pytaniu ``delivered`` albo ``rejected``, a napis ``logi-uruchomienia`` stoi tylko w ``Literal``.
- Logi i tekst po strażniku (``GuardedLogs``, ``GuardedText``) daje tylko ``guard_logs`` i ``guard_text`` z
  ``run_logs_guard``, inaczej ich typ niczego by nie dowodził. Konstruktor bez dowodu strażnika (``_MINTED``), ``replace``,
  kopię, ``pickle``, zmianę pola, podklasę i wartość innego typu (``Any``) zamyka sam typ albo jego sprawdzenie przy
  uruchomieniu (docstring ``run_logs_guard._MINTED``). Poza ``run_logs_guard`` nazwy tych typów padają tylko w adnotacjach,
  importach i ``isinstance``, a ``_MINTED`` i napis z ich nazwą w żadnej postaci, więc test łapie
  ``object.__new__(GuardedLogs)``, ``object.__setattr__`` slotu, ``cast(GuardedLogs, …)`` i ``_MINTED`` zaimportowany
  z ``# noqa: TID251``, którego ruff nie widzi (przegląd #1371 r2).

Wyrocznie skilli (``.agents/skills/*/scripts``) i narzędzia (``tools/``) biorą z ``src`` tylko publiczne nazwy
(docs/agents/skille.md, „Co wyrocznia bierze z src”): mechanikę przez publiczny punkt obserwacji, a dane o świecie
zewnętrznym przez celową kopię. Do 8.11.2026 cztery wyrocznie sięgały do prywatnych nazw i globali modułów, eksplorator
kolejki budował swój stan z prywatnych pól ``Outbox`` i ``KeyedBox``, a eksplorator Uruchomień z prywatnych pól
``RunHost`` (spis N13).

Kod spoza ``tests/`` (``src/``, ``tools/`` z bibliotekami, skryptami CI i hookami, skrypty skilli i pliki Pythona w
korzeniu) nie importuje pakietu ``tests``: narzędzia i skille zmieniają się rzadko, a pliki testów najczęściej, więc
atrapy świata zewnętrznego i syntetyczne pliki taty wspólne z testami leżą w ``tools/lib/atrapy/``, a ``tests/fixtures``
trzyma tylko pomocniki testów. Sprawdzenie nie ma wyjątków i łapie dokładnie postacie wyliczone w docstringu
``_tests_imports``; uruchomienie testu po ścieżce (``pytest.main([".../tests/test_x.py::test"])``) nie jest importem i
przechodzi.

Test czyta AST importów, także względnych, importów w funkcji i pakietów nad modułem. Nowy moduł bez zależności
trafia do ``STDLIB_ONLY`` z powodem. Granice czytania importów, Skryptu dla maszyn, strażnika Logów i wysyłki Logów
pokazują próbki ``ZNANE_LUKI_GRAFU``, ``ZNANE_LUKI_SKRYPTU``, ``ZNANE_LUKI_STRAZNIKA`` i ``ZNANE_LUKI_WYSYLKI`` przy
ich testach, każda za klasą nazwaną w swojej nazwie (``tests/fixtures/znane_luki.py``). Granica składania
``PreparedRun``, którą łapie tylko przegląd: ``PreparedRun`` wołany pod nazwą przypisaną poza importem, pod nazwą z
napisu sklejonego z części (``getattr``) albo jako ``type(prepared)`` oraz kopia ``PreparedRun`` przez ``replace``
przypisane innej nazwie poza importem albo z wyrażenia bez ``prepared`` w tekście z każdym polem poza ``metrics=``
(``kind=``, ``engine=``…).
"""

from __future__ import annotations

import ast
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
import importlib
from pathlib import Path, PureWindowsPath
import sys
import typing

import pytest

from tests.fixtures.skladnia import drzewo, pamiec_drzew, raz_na_drzewo, wezly
from tests.fixtures.znane_luki import assert_znane_luki, ruff, ruff_i_mypy, wymaga_ruff, wymaga_ruff_i_mypy, zapisz

SRC = Path(__file__).resolve().parents[1] / "src"
GUARDIAN = SRC / "rozliczenia" / "centrum" / "restart_guardian.py"
ROOT = SRC.parent
# Wyrocznia Wyceny w efenix i moduły spoza biblioteki standardowej, które wolno jej importować.
EFENIX_ORACLE = {
    ROOT / "tools" / "lib" / "atrapy" / "model_efenix.py": frozenset[str](),
    ROOT / "tools" / "lib" / "atrapy" / "atrapa_efenix.py": frozenset({"atrapy.model_efenix"}),
}
# Okno w procesie i moduły kodu pod testem, z których bierze tylko typy.
WINDOW_IN_PROCESS = ROOT / "tests" / "fixtures" / "okno_w_procesie.py"
WINDOW_SEAM = frozenset({"rozliczenia.efenix_window"})
# Wersje komentarza Uruchomienia i jedyne, co biorą przy wczytaniu spoza biblioteki standardowej bez I/O: nazwy z modułu.
COMMENT_VERSIONS = "rozliczenia/centrum/comment_versions.py"
PURE_STDLIB = frozenset({"__future__", "collections", "collections.abc", "dataclasses", "typing"})
PURE_VERSIONS = {
    "rozliczenia.centrum.contract": frozenset({"runs"}),
    "rozliczenia.centrum.catalog": frozenset({"declaration_of"}),
    "rozliczenia.centrum.outbox": frozenset({"ArchiveFile", "PeriodThread", "Post", "Rank", "Target"}),
    "rozliczenia.centrum.report_box": frozenset({"Label"}),
    "rozliczenia.centrum.version": frozenset({"short_commit"}),
    "rozliczenia.centrum.run_logs": frozenset({"LoggedDiagnosis", "LoggedMessage", "RunLog", "StartFacts"}),
    "rozliczenia.centrum.pricing_progress": frozenset({"PricingProgress"}),
    # strażnik reguły danych: liczy na pamięci ForbiddenValues, bez plików
    "rozliczenia.centrum.run_logs_guard": frozenset({"GuardedLogs", "GuardedText", "guard_logs", "guard_text"}),
    # odczyt dysku, który start Centrum podaje macierzy close, jako wartość: typy bez metod, które czytają pliki, i nazwa
    # pliku Logów w Archiwum Logów okresu (name_of liczy ją z faktów startu, bez plików)
    "rozliczenia.centrum.logs_disk": frozenset(
        {"Found", "JournalRead", "LeftJournal", "Missing", "Refused", "Unreadable", "name_of"}
    ),
    # pamięć strażnika do adnotacji, tekst narzędzia do wysyłki (nagłówek issue Logów, komentarz po strażniku) i metaklasa
    # typów-dowodów bez podklas, bez plików
    "rozliczenia.client_data": frozenset({"ForbiddenValues", "WithoutSubclasses", "tool"}),
    "rozliczenia.process_run": frozenset({"RunResult"}),
}
RUN_LOGS_GUARD = "rozliczenia/centrum/run_logs_guard.py"
# Moduły Logów Uruchomienia, które czytają karta z Logów, plik Logów i odtworzenie, i moduły, których nie wczytują:
# gospodarz Uruchomień i Diagnoza zmieniają się z procesami, a Logi z nich składa tylko logs_of_run.
RUN_LOGS_FORMAT = (
    "rozliczenia/centrum/run_logs.py",
    "rozliczenia/centrum/run_logs_guard.py",
    "rozliczenia/centrum/pricing_progress.py",
)
RUN_HOST = frozenset({"rozliczenia.centrum.runs", "rozliczenia.centrum.diagnosis"})
RUN_LOGS_LABEL = "logi-uruchomienia"
# Katalog procesów i wpisy procesów: moduły, których nie wczytują, i jedyny moduł, który czyta wpisy i składa Uruchomienie
# gotowe do startu.
CATALOG_MODULES = (
    "rozliczenia/centrum/catalog.py",
    "rozliczenia/centrum/process_kind.py",
    *sorted(path.relative_to(SRC).as_posix() for path in (SRC / "rozliczenia" / "centrum" / "processes").glob("*.py")),
)
NOT_IN_CATALOG = frozenset(
    {
        "rozliczenia.centrum.runs",
        "rozliczenia.centrum.diagnosis",
        "rozliczenia.centrum.configuration",
        "rozliczenia.centrum.period_board",
        "rozliczenia.efenix_browser",
    }
)
SERVER_LIBRARIES = frozenset({"fastapi", "starlette", "uvicorn"})
PROCESS_KINDS = "rozliczenia.centrum.processes"
CATALOG = SRC / "rozliczenia" / "centrum" / "catalog.py"
MACHINE_SCRIPT = ROOT / "tools" / "uruchom_proces.py"
VERSIONS = "rozliczenia.centrum.comment_versions"
# Pytania kolejki, czy wysyłka doszła albo została odrzucona: jedyne, czemu kod poza post_of podaje etykietę Logów.
QUEUE_QUESTIONS = frozenset({"delivered", "rejected"})
# Typy po strażniku reguły danych i ten plik, który je nazywa w swoich regułach.
GUARDED = frozenset({"GuardedLogs", "GuardedText"})
GUARD_CHECK = ROOT / "tests" / "test_granice_importow.py"
STDLIB_ONLY = {
    "rozliczenia/__init__.py": "pakiet, który wczytuje każdy moduł poniżej",
    "rozliczenia/centrum/__init__.py": "pakiet, który wczytuje każdy moduł Centrum",
    "rozliczenia/message.py": "Komunikat startu o brakującej bibliotece musi działać bez zależności",
    "rozliczenia/file_state.py": "opiekun ponownego startu i Aktualizacja narzędzia pytają przez niego o stan pliku",
    "rozliczenia/decision.py": "moduły procesu biorą z niego rozmowę bez zależności od rdzenia Uruchomienia",
    "rozliczenia/tool_files.py": "układ plików narzędzia czytają launcher przed FastAPI i opiekun ponownego startu",
    "rozliczenia/centrum/version.py": "launcher pyta o wersję, zanim wczyta FastAPI",
    "rozliczenia/centrum/opener.py": "launcher pyta health przez jego otwieracz, zanim wczyta FastAPI",
    "rozliczenia/wall_clock.py": "Aktualizacja narzędzia i opiekun ponownego startu biorą z niego termin dzierżawy",
    "rozliczenia/centrum/log.py": "dziennik Centrum zapisuje błąd startu, gdy brakuje zależności",
    "rozliczenia/centrum/platform.py": "okienko z Komunikatem startu pokazuje też brak zależności",
    "rozliczenia/centrum/tool_update.py": "launcher kończy przerwaną Aktualizację narzędzia, zanim wczyta FastAPI",
    "rozliczenia/centrum/start_problems.py": "jeden z Komunikatów startu mówi o brakujących zależnościach",
    "rozliczenia/centrum/launcher.py": "brak FastAPI albo uvicorn staje się Komunikatem startu; resztę wczytuje w funkcji",
    "rozliczenia/efenix_window.py": "seam okna efenix: okno w procesie bierze z niego typy bez kodu Wyceny, a okna i Wycena nie tworzą cyklu",
    "rozliczenia/text.py": "reguła danych i warstwa skoroszytu normalizują tekst bez zależności od Konfiguracji wykonawców",
    "rozliczenia/register_columns.py": "Przebieg, Wycena i reguła danych biorą kolumny Rejestru bez czytnika Przygotowania",
    "rozliczenia/row_positions.py": "uchwyt plików taty i Kopia wejścia biorą położenie wiersza bez reguł Surowych zleceń INTERMAX",
    "rozliczenia/worker_reports/__init__.py": "rdzeń raportów przejdzie bez zmian do Centrum w chmurze (ADR 0028, #1161)",
    "rozliczenia/worker_reports/_model.py": "typy rdzenia raportów (ADR 0028, #1161)",
    "rozliczenia/worker_reports/_subject.py": "temat Raportu wykonawcy w rdzeniu raportów (ADR 0028, #1161)",
    "rozliczenia/worker_reports/_entries.py": "Wpisy raportu w rdzeniu raportów (ADR 0028, #1161)",
    "rozliczenia/worker_reports/_matching.py": "dopasowanie Wpisów do zleceń w rdzeniu raportów (ADR 0028, #1161)",
    "rozliczenia/worker_reports/_cells.py": "Nienadpisywanie komórek w rdzeniu raportów (ADR 0028, #1161)",
    "rozliczenia/worker_reports/_corrections.py": "poprawione maile w rdzeniu raportów (ADR 0028, #1161)",
    "rozliczenia/worker_reports/_figures.py": "liczby widoku Raporty w rdzeniu raportów (ADR 0028, #1161)",
    "rozliczenia/worker_reports/_moves.py": "Przeniesienia zleceń w rdzeniu raportów (ADR 0029, #1161)",
    "rozliczenia/worker_reports/_canonical.py": "postać kanoniczna maila w rdzeniu raportów (ADR 0028, #1161)",
    "rozliczenia/worker_reports/_reminders.py": "Przypomnienia o raporcie w rdzeniu raportów (ADR 0030, #1161)",
    "rozliczenia/worker_reports/reasons.py": "zdania o problemach rdzenia raportów (ADR 0028, #1161)",
    "rozliczenia/report_cells.py": "rdzeń raportów zwraca zmiany komórek bez Excela (ADR 0028, #1161)",
    "rozliczenia/settlement_period.py": "rdzeń raportów liczy dni okresów zamkniętych bez zależności (ADR 0028, #1161)",
}
# Jedyny moduł src, który rozmawia z serwerem IMAP: Skrzynka raportów otwiera skrzynkę tylko do odczytu (ADR 0028).
IMAP_PORT = "rozliczenia/worker_report_inbox.py"
WITHOUT_WORKBOOK = {
    "rozliczenia/domain.py": "protokół postępu, który zna każdy proces, Centrum i Skrypt dla maszyn",
    "rozliczenia/telemetry.py": "rekord metryk Uruchomienia wspólny dla wszystkich procesów",
    "rozliczenia/process_run.py": "rdzeń Uruchomienia procesu wspólny dla Centrum i Skryptu dla maszyn",
    "rozliczenia/phase_runner.py": "kolejność i czas faz każdego procesu",
    "rozliczenia/write_routes.py": "drogi zapisu, które telemetria liczy bez kodu zapisu Wzorca",
    "rozliczenia/text.py": "reguły tekstu dla taty wspólne dla wszystkich procesów",
    "rozliczenia/register_columns.py": "kolumny Rejestru, które biorą Przebieg, Wycena i reguła danych",
    "rozliczenia/report_cells.py": "zmiany komórek, które rdzeń Wpisania raportów zwraca bez Excela (#1226, #1161)",
    "rozliczenia/tool_files.py": "układ plików narzędzia, który znają wszystkie procesy, Centrum i launcher",
}
WORKBOOK_LAYER = "rozliczenia.template_file"
WORKBOOK_LIBRARY = "openpyxl"


@pytest.fixture(autouse=True, scope="module")
def drzewa_raz_na_modul() -> Iterator[None]:
    with pamiec_drzew():
        yield


@dataclass(frozen=True)
class Import:
    file: str
    line: int
    code: str
    module: str
    nested: bool

    def __str__(self) -> str:
        return f"src/{self.file}:{self.line}: {self.code}"


def _module_name(file: str) -> str:
    parts = file.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _file_of(module: str, root: Path = SRC) -> str | None:
    base = module.replace(".", "/")
    for file in (f"{base}.py", f"{base}/__init__.py"):
        if (root / file).is_file():
            return file
    return None


def _modules_loaded(module: str) -> Iterator[str]:
    """``module`` i pakiety nad nim: import modułu wczytuje każdy z nich."""

    parts = module.split(".")
    for end in range(1, len(parts) + 1):
        yield ".".join(parts[:end])


def _from_module(node: ast.ImportFrom, file: str) -> str:
    """Moduł importu ``from … import`` w pliku ``file`` (``rozliczenia/…``), także względnego."""

    base = node.module or ""
    if not node.level:
        return base
    package = _module_name(file) if file.endswith("__init__.py") else _module_name(file).rpartition(".")[0]
    anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
    return ".".join([*anchor, *([base] if base else [])])


def _imports(file: str, root: Path = SRC) -> Iterator[Import]:
    """Importy pliku z modułami, które wczytują; ``nested`` dla importu w funkcji."""

    for node, code, nested in _import_statements(drzewo(root / file)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            base = _from_module(node, file)
            names = [base, *(f"{base}.{alias.name}" for alias in node.names if _file_of(f"{base}.{alias.name}", root))]
        for name in names:
            for module in _modules_loaded(name):
                yield Import(file, node.lineno, code, module, nested)


@raz_na_drzewo
def _import_statements(tree: ast.Module) -> tuple[tuple[ast.Import | ast.ImportFrom, str, bool], ...]:
    """Instrukcje importu drzewa z tekstem i ``nested``, raz na drzewo: ``_chains`` wraca do tych samych modułów
    z każdego modułu startowego."""

    in_function = {
        node
        for function in wezly(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
    }
    return tuple(
        (node, ast.unparse(node), node in in_function)
        for node in wezly(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )


def _is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


def _copied() -> tuple[str, ...]:
    for node in drzewo(GUARDIAN).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "_COPIED":
            assert node.value is not None
            copied = ast.literal_eval(node.value)
            assert isinstance(copied, tuple)
            return copied
    raise AssertionError(f"{GUARDIAN.relative_to(SRC.parent)}: brak listy _COPIED, którą czyta ten test")


def test_silnik_nie_importuje_centrum_rozliczen() -> None:
    found = {
        str(found)
        for path in sorted((SRC / "rozliczenia").glob("*.py"))
        for found in _imports(path.relative_to(SRC).as_posix())
        if found.module == "rozliczenia.centrum"
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Silnik (src/rozliczenia/*.py) nie zależy od Centrum rozliczeń, adaptera Uruchomienia procesu (ADR 0004): "
            "przenieś potrzebny kod do silnika, a Centrum niech importuje go stamtąd.",
        ]
    )


def test_moduly_bez_zaleznosci_wczytuja_tylko_biblioteke_standardowa() -> None:
    allowed = {_module_name(file) for file in STDLIB_ONLY}
    found = {
        f"{found}  ({reason})"
        for file, reason in STDLIB_ONLY.items()
        for found in _imports(file)
        if not found.nested and not _is_stdlib(found.module) and found.module not in allowed
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Moduły z STDLIB_ONLY (tests/test_granice_importow.py, powód przy każdym) przy wczytaniu importują tylko "
            "bibliotekę standardową i siebie nawzajem. Przenieś import do funkcji, która go używa, albo dopisz "
            "moduł bez zależności do STDLIB_ONLY z powodem.",
        ]
    )


def test_imap_i_smtp_importuje_tylko_port_skrzynki_raportow() -> None:
    found = {
        str(found)
        for path in sorted((SRC / "rozliczenia").rglob("*.py"))
        if path.relative_to(SRC).as_posix() != IMAP_PORT
        for found in _imports(path.relative_to(SRC).as_posix())
        if found.module in ("imaplib", "smtplib")
    }

    assert (SRC / IMAP_PORT).is_file()
    assert not found, "\n".join(
        [
            *sorted(found),
            f"Skrzynkę raportów czyta tylko {IMAP_PORT}, który otwiera ją tylko do odczytu (ADR 0028): "
            "weź z niego ImapInbox, WorkerReportInbox albo ReminderMailbox zamiast imaplib i smtplib.",
        ]
    )


# Rdzeń raportów przejdzie bez zmian do Centrum w chmurze (ADR 0028, #1161): spoza biblioteki standardowej bierze tylko
# te moduły silnika, a jego moduły prywatne ``_*.py`` importuje tylko on sam.
REPORT_CORE: typing.Final = "rozliczenia/worker_reports"
REPORT_CORE_PACKAGE: typing.Final = "rozliczenia.worker_reports"
REPORT_CORE_ENGINE: typing.Final = frozenset(
    {"rozliczenia", "rozliczenia.report_cells", "rozliczenia.settlement_period", "rozliczenia.text"}
)
# Kod, który mógłby sięgnąć do modułów prywatnych rdzenia raportów, i po jednym jego pliku z każdej części.
REPORT_CORE_READERS: typing.Final = ("src/**/*.py", "tools/**/*.py", "tests/**/*.py", ".agents/skills/*/scripts/**/*.py")
REPORT_CORE_READ_PARTS: typing.Final = (
    "src/rozliczenia/worker_report_inbox.py",
    "tools/uruchom_proces.py",
    "tests/test_rdzen_raportow.py",
    ".agents/skills/verify-rozliczenia/scripts/doctor.py",
)


def _in_report_core(module: str) -> bool:
    return module == REPORT_CORE_PACKAGE or module.startswith(f"{REPORT_CORE_PACKAGE}.")


def _report_core_private(tree: ast.Module, file: str | None) -> list[tuple[int, str]]:
    """Moduły prywatne rdzenia raportów (``rozliczenia.worker_reports._…``), których sięga plik ``file`` (``rozliczenia/…``
    w ``src``, ``None`` poza nim): ``import`` (też ``as``), ``from … import`` z modułu prywatnego albo jego nazwy z
    pakietu, w ``src`` także względny, oba także w funkcji, i atrybut ``_…`` nazwy ``worker_reports``
    (``worker_reports._cells``, ``rozliczenia.worker_reports._cells``).

    Granica (tylko przegląd): import względny poza ``src``, nazwa złożona w trakcie działania (``importlib`` z napisem,
    ``getattr``) i pakiet przypisany innej nazwie."""

    found = []
    for node in wezly(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names if alias.name.startswith(f"{REPORT_CORE_PACKAGE}._")]
        elif isinstance(node, ast.ImportFrom) and (file is not None or not node.level):
            base = _from_module(node, file) if file is not None else node.module or ""
            if base.startswith(f"{REPORT_CORE_PACKAGE}._"):
                found.append((node.lineno, base))
            elif base == REPORT_CORE_PACKAGE:
                found += [(node.lineno, f"{base}.{alias.name}") for alias in node.names if alias.name.startswith("_")]
        elif (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("_")
            and ast.unparse(node.value).rpartition(".")[2] == "worker_reports"
        ):
            found.append((node.lineno, f"{REPORT_CORE_PACKAGE}.{node.attr}"))
    return sorted(set(found))


def test_rdzen_raportow_bierze_spoza_biblioteki_standardowej_tylko_komorki_okres_i_tekst() -> None:
    files = sorted(path.relative_to(SRC).as_posix() for path in (SRC / REPORT_CORE).rglob("*.py"))
    found = {
        str(found)
        for file in files
        for found in _imports(file)
        if not (_is_stdlib(found.module) or found.module in REPORT_CORE_ENGINE or _in_report_core(found.module))
    }

    assert {f"{REPORT_CORE}/__init__.py", f"{REPORT_CORE}/reasons.py"} <= set(files)
    assert not found, "\n".join(
        [
            *sorted(found),
            f"Rdzeń raportów ({REPORT_CORE}) przejdzie bez zmian do Centrum w chmurze (ADR 0028, #1161), więc bierze "
            "spoza biblioteki standardowej tylko report_cells, settlement_period i text, także w funkcji: plik, Excel "
            "i IMAP zostają w procesie (report_entering), który podaje rdzeniowi gotowe dane.",
        ]
    )


def test_moduly_prywatne_rdzenia_raportow_importuje_tylko_jego_pakiet() -> None:
    paths = sorted({path for pattern in REPORT_CORE_READERS for path in ROOT.glob(pattern) if path.is_file()})
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {module}"
        for path in paths
        if not path.is_relative_to(SRC / REPORT_CORE)
        for line, module in _report_core_private(
            drzewo(path),
            path.relative_to(SRC).as_posix() if path.is_relative_to(SRC) else None,
        )
    ]

    assert {path.relative_to(ROOT).as_posix() for path in paths} >= set(REPORT_CORE_READ_PARTS)
    assert found == [], "\n".join(
        [
            *found,
            f"Moduły {REPORT_CORE}/_*.py importuje tylko pakiet rdzenia raportów: weź enter_reports i typy z "
            f"{REPORT_CORE_PACKAGE}, a zdanie o problemie z {REPORT_CORE_PACKAGE}.reasons.",
        ]
    )


# Każda postać sięgnięcia do modułu prywatnego rdzenia raportów, którą zna sprawdzenie: kod, plik w src (None poza nim)
# i moduł, który z niej czyta.
REPORT_CORE_PRIVATE: typing.Final = {
    "import": ("import rozliczenia.worker_reports._cells", None, "rozliczenia.worker_reports._cells"),
    "import-as": ("import rozliczenia.worker_reports._cells as cells", None, "rozliczenia.worker_reports._cells"),
    "from-modulu": ("from rozliczenia.worker_reports._cells import reconcile", None, "rozliczenia.worker_reports._cells"),
    "from-pakietu": ("from rozliczenia.worker_reports import enter_reports, _cells", None, "rozliczenia.worker_reports._cells"),
    "wzgledny-z-silnika": ("from .worker_reports import _cells", "rozliczenia/report_entering.py", "rozliczenia.worker_reports._cells"),
    "wzgledny-modul": ("from .worker_reports._matching import match", "rozliczenia/report_entering.py", "rozliczenia.worker_reports._matching"),
    "wzgledny-z-centrum": ("from ..worker_reports import _figures", "rozliczenia/centrum/report_entering_run.py", "rozliczenia.worker_reports._figures"),
    "w-funkcji": ("def f() -> None:\n    from rozliczenia.worker_reports import _subject", None, "rozliczenia.worker_reports._subject"),
    "atrybut": ("from rozliczenia import worker_reports\nworker_reports._cells.reconcile", None, "rozliczenia.worker_reports._cells"),
    "atrybut-pelnej-sciezki": ("import rozliczenia.worker_reports\nrozliczenia.worker_reports._entries", None, "rozliczenia.worker_reports._entries"),
}


@pytest.mark.parametrize(("code", "file", "module"), REPORT_CORE_PRIVATE.values(), ids=REPORT_CORE_PRIVATE.keys())
def test_sprawdzenie_rdzenia_raportow_lapie_kazda_wyliczona_postac_siegniecia_do_modulu_prywatnego(
    code: str, file: str | None, module: str
) -> None:
    assert [found for _, found in _report_core_private(ast.parse(code), file)] == [module]


def test_sprawdzenie_rdzenia_raportow_przepuszcza_publiczne_nazwy_pakietu_i_prywatne_moduly_spoza_niego() -> None:
    code = (
        "import rozliczenia.report_cells\n"
        "from rozliczenia import worker_reports\n"
        "from rozliczenia.worker_reports import ReportInputs, enter_reports\n"
        "from rozliczenia.worker_reports.reasons import reason\n"
        "from rozliczenia.centrum import _private\n"
        "from ._cells import reconcile\n"
        "outcome = worker_reports.enter_reports(inputs)\n"
        "value = other._cells\n"
    )

    assert _report_core_private(ast.parse(code), "rozliczenia/report_entering.py") == []
    assert _report_core_private(ast.parse("from ._cells import reconcile"), None) == []


def _is_workbook(module: str) -> bool:
    return module == WORKBOOK_LAYER or module.split(".")[0] == WORKBOOK_LIBRARY


def _workbook_chains(file: str, root: Path = SRC) -> set[str]:
    """Łańcuchy importów od pliku ``file`` do warstwy skoroszytu (``_chains``)."""

    return _chains(file, _is_workbook, root)


def _chains(file: str, target: Callable[[str], bool], root: Path = SRC) -> set[str]:
    """Łańcuchy importów od pliku ``file`` do modułu, który spełnia ``target``, każdy import z plikiem i linią.

    Idzie wszerz po modułach ``src/`` (``root``), także po importach w funkcji, więc łańcuch jest najkrótszy do
    każdego modułu po drodze. Moduł spoza ``src/`` (biblioteka) kończy drogę.
    """

    reached: dict[str, tuple[Import, ...]] = {loaded: () for loaded in _modules_loaded(_module_name(file))}
    queue = deque(reached)
    chains = set()
    while queue:
        current = _file_of(queue.popleft(), root)
        if current is None:
            continue
        for found in _imports(current, root):
            chain = (*reached[_module_name(current)], found)
            if target(found.module):
                chains.add(" → ".join(map(str, chain)))
            elif found.module not in reached:
                reached[found.module] = chain
                queue.append(found.module)
    return chains


def test_rdzen_uruchomienia_nie_wczytuje_warstwy_skoroszytu() -> None:
    found = {
        f"{chain}  ({reason})" for file, reason in WITHOUT_WORKBOOK.items() for chain in _workbook_chains(file)
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Moduły z WITHOUT_WORKBOOK (tests/test_granice_importow.py, powód przy każdym) nie wczytują template_file "
            "ani openpyxl, także przez inne moduły src i importem w funkcji. Przenieś typ albo stałą, której potrzebują, "
            "do modułu bez skoroszytu (jak write_routes, register_columns) i niech warstwa skoroszytu importuje ją stamtąd.",
        ]
    )


def test_format_logow_uruchomienia_nie_wczytuje_gospodarza_uruchomien_ani_diagnozy() -> None:
    found = {chain for file in RUN_LOGS_FORMAT for chain in _chains(file, RUN_HOST.__contains__)}

    assert not found, "\n".join(
        [
            *sorted(found),
            "Schemat Logów Uruchomienia, strażnik reguły danych i postęp Wyceny (RUN_LOGS_FORMAT w "
            "tests/test_granice_importow.py) nie wczytują gospodarza Uruchomień (runs) ani Diagnozy (diagnosis), także "
            "przez inne moduły src i importem w funkcji: Logi z nich składa src/rozliczenia/centrum/logs_of_run.py.",
        ]
    )


def _is_outside_catalog(module: str) -> bool:
    return module in NOT_IN_CATALOG or module.split(".")[0] in SERVER_LIBRARIES


def test_katalog_procesow_nie_wczytuje_serwera_okna_efenix_ani_modulow_centrum_ktore_go_czytaja() -> None:
    found = {chain for file in CATALOG_MODULES for chain in _chains(file, _is_outside_catalog)}

    assert not found, "\n".join(
        [
            *sorted(found),
            "Katalog procesów, wpis procesu i wpisy w centrum/processes (CATALOG_MODULES w tests/test_granice_importow.py) "
            "nie wczytują FastAPI, runs, diagnosis, configuration, period_board ani efenix_browser, także przez inne "
            "moduły src i importem w funkcji: czytają je Skrypt dla maszyn, odtworzenie i wersje komentarza bez serwera. "
            "Przenieś typ, którego potrzebują, do modułu bez tych zależności (jak Settings w centrum/settings.py).",
        ]
    )


def _is_server(module: str) -> bool:
    return module.split(".")[0] in SERVER_LIBRARIES


def test_skrypt_dla_maszyn_nie_wczytuje_serwera() -> None:
    script = MACHINE_SCRIPT.relative_to(ROOT).as_posix()
    found = set()
    for line, module in _imported_modules(MACHINE_SCRIPT):
        if _is_server(module):
            found.add(f"{script}:{line}: {module}")
        elif (file := _file_of(module)) is not None:
            found |= {f"{script}:{line}: {module} → {chain}" for chain in _chains(file, _is_server)}

    assert not found, "\n".join(
        [
            *sorted(found),
            f"Skrypt dla maszyn ({script}) nie wczytuje FastAPI, starlette ani uvicorn, także przez moduły src i "
            "importem w funkcji: Uruchomienie procesu nie potrzebuje serwera. Przenieś to, czego skrypt potrzebuje, "
            "z modułu z routerem do modułu bez niego (jak ConfigurationFiles w centrum/configuration.py, a router "
            "w centrum/configuration_router.py).",
        ]
    )


# Znane luki strażnika Skryptu dla maszyn (tests/fixtures/znane_luki.py): „klasa: postać” → Skrypt dla maszyn, który
# wczytuje serwer (moduł ``serwer_atrapy`` w ``tools/lib`` drzewa próbek wczytuje FastAPI), a mimo to przechodzi przez
# ruff w ``tools/`` i przez ``test_skrypt_dla_maszyn_nie_wczytuje_serwera``.
ZNANE_LUKI_SKRYPTU: typing.Final = {
    "tylko moduły src: moduł tools/lib, który wczytuje serwer": "import serwer_atrapy\n\nSERWER = serwer_atrapy\n",
    "tylko instrukcja import: importlib.import_module": 'import importlib\n\nSERWER = importlib.import_module("fastapi")\n',
    "tylko instrukcja import: __import__": 'SERWER = __import__("uvicorn")\n',
}


def _zgloszenia_skryptu(skrypt: Path) -> list[str]:
    """Zgłoszenie ``test_skrypt_dla_maszyn_nie_wczytuje_serwera`` dla Skryptu dla maszyn ``skrypt`` w miejscu
    ``tools/uruchom_proces.py``, z ``src`` repozytorium."""

    with pytest.MonkeyPatch.context() as podmiana:
        podmiana.setattr(sys.modules[__name__], "MACHINE_SCRIPT", skrypt)
        podmiana.setattr(sys.modules[__name__], "ROOT", skrypt.parents[1])
        try:
            test_skrypt_dla_maszyn_nie_wczytuje_serwera()
        except AssertionError as blad:
            return [str(blad)]
    return []


@wymaga_ruff
def test_znane_luki_skryptu_dla_maszyn_przechodza_przez_ruff_i_straznika(tmp_path: Path) -> None:
    (tmp_path / "tools" / "lib").mkdir(parents=True)
    (tmp_path / "tools" / "lib" / "serwer_atrapy.py").write_text("import fastapi\n\nAPI = fastapi.FastAPI()\n", encoding="utf-8")
    pliki = zapisz(ZNANE_LUKI_SKRYPTU, tmp_path / "tools")

    zgloszenia = ruff(pliki, sonda=ROOT / "tools" / "sonda_luki.py")
    for opis, plik in pliki.items():
        zgloszenia[opis] += _zgloszenia_skryptu(plik)

    assert_znane_luki(zgloszenia, "tests/test_granice_importow.py (ZNANE_LUKI_SKRYPTU)")


def _imported_modules(path: Path) -> Iterator[tuple[int, str]]:
    """Moduły, które importuje plik ``path``, z linią; ``from a import b`` daje ``a`` i ``a.b``, a import względny
    w ``src`` moduł, który wskazuje."""

    tree = drzewo(path)
    for node in wezly(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level and not path.is_relative_to(SRC):
                continue
            base = _from_module(node, path.relative_to(SRC).as_posix()) if node.level else node.module or ""
            yield node.lineno, base
            for alias in node.names:
                yield node.lineno, f"{base}.{alias.name}"


def test_wpisy_procesow_czyta_tylko_katalog_procesow() -> None:
    found = {
        f"{path.relative_to(ROOT).as_posix()}:{line}: {module}"
        for path in _python_files()
        if path != CATALOG and not path.is_relative_to(SRC / "rozliczenia" / "centrum" / "processes")
        for line, module in _imported_modules(path)
        if module == PROCESS_KINDS or module.startswith(f"{PROCESS_KINDS}.")
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Wpis procesu (centrum/processes/<proces>.py) importuje tylko src/rozliczenia/centrum/catalog.py: Centrum, "
            "narzędzia, testy i skrypty skilli biorą wpis z katalogu (catalog.declaration_of, Catalog.kind), rdzeń "
            "i plik metryk z Catalog, a podpowiedź podglądu z ProcessKind.preview_hint.",
        ]
    )


# Moduły z funkcją ``replace``, która kopiuje dataclassę z podmienionymi polami.
_COPYING_MODULES: typing.Final = frozenset({"dataclasses", "copy"})


def _prepared_run_builds(tree: ast.AST) -> list[tuple[int, str]]:
    """Miejsca w ``tree``, które składają ``PreparedRun`` obok ``Catalog.prepared``: jego konstruktor (nazwa albo
    atrybut ``PreparedRun``), podklasa (składa się sama, ``cls(...)``) i kopia przez ``replace`` z ``dataclasses`` albo
    ``copy`` albo przez ``__replace__``, z innym plikiem metryk (``metrics=``) albo z wyrażenia, którego tekst ma
    ``prepared`` bez względu na wielkość liter (``self._prepared``, ``PREPARED``). Konstruktor, podklasę i ``replace`` test rozpoznaje także pod nazwą z importu (``import … as``).

    Kopię z każdym polem poza ``metrics=`` (``kind=``, ``engine=``…) test rozpoznaje tylko po tekście kopiowanego
    wyrażenia, bo te pola mają też inne dataclassy (``stops.StoppedRun``).
    """

    builds = {"PreparedRun"}
    copies = {"replace", *(f"{module}.replace" for module in _COPYING_MODULES)}
    for node in wezly(tree):
        if isinstance(node, ast.ImportFrom):
            builds |= {alias.asname for alias in node.names if alias.name == "PreparedRun" and alias.asname}
            if node.module in _COPYING_MODULES:
                copies |= {alias.asname or alias.name for alias in node.names if alias.name == "replace"}
        elif isinstance(node, ast.Import):
            copies |= {f"{alias.asname}.replace" for alias in node.names if alias.name in _COPYING_MODULES and alias.asname}
    found: list[tuple[int, str]] = []
    for node in wezly(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                named = base.value if isinstance(base, ast.Subscript) else base
                if (named.id if isinstance(named, ast.Name) else getattr(named, "attr", None)) in builds:
                    found.append((node.lineno, f"class {node.name}({ast.unparse(base)})"))
            continue
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)) in builds:
            found.append((node.lineno, f"{ast.unparse(func)}("))
            continue
        if isinstance(func, ast.Attribute) and func.attr == "__replace__":
            copied = ast.unparse(func.value)
        elif ast.unparse(func) in copies:
            copied = ast.unparse(node.args[0]) if node.args else ""
        else:
            continue
        if "prepared" in copied.lower() or any(keyword.arg == "metrics" for keyword in node.keywords):
            found.append((node.lineno, ast.unparse(node)))
    return found


def test_uruchomienie_gotowe_do_startu_sklada_tylko_katalog_procesow() -> None:
    found = {
        f"{path.relative_to(ROOT).as_posix()}:{line}: {call}"
        for path in _python_files()
        if path != CATALOG
        for line, call in _prepared_run_builds(drzewo(path))
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "PreparedRun składa tylko Catalog.prepared (src/rozliczenia/centrum/catalog.py), także kopią "
            "(dataclasses.replace z metrics= albo z wartości prepared) i podklasą: rdzeń, historia metryk i silnik "
            "procesu pochodzą z katalogu, więc Centrum, Skrypt dla maszyn, odtworzenie, testy i skrypty skilli "
            "podmieniają je tylko przez Catalog.with_metrics, Catalog.steered i Catalog.with_engine.",
        ]
    )


# Złożenie PreparedRun obok Catalog.prepared (kopie i nazwy z importu: przegląd #1122, runda 1).
PREPARED_RUN_BUILDS: typing.Final = {
    "konstruktor": "run = PreparedRun(kind, period, inputs, context, metrics)",
    "konstruktor-z-modulu": "run = process_kind.PreparedRun(kind, period, inputs, context, metrics)",
    "konstruktor-pod-nazwa-z-importu": "from rozliczenia.centrum.process_kind import PreparedRun as _G\nrun = _G(1, 2)",
    "replace-z-plikiem-metryk": "run = replace(run, metrics=MetricsStore(path, ()))",
    "dataclasses-replace-uruchomienia": "run = dataclasses.replace(prepared, kind=other)",
    "copy-replace-z-atrybutu": "run = copy.replace(self.prepared, period=period)",
    "dunder-replace": "run = PREPARED.__replace__(kind=other)",
    "replace-pod-nazwa-z-importu": "from dataclasses import replace as _r\nrun = _r(run, metrics=None)",
    "modul-pod-nazwa-z-importu": "import dataclasses as dc\nrun = dc.replace(run, metrics=store)",
    # Przegląd #1127, runda 1: podklasa z własnym conduct składała się przez cls(**pola).
    "podklasa-z-modulu": "class Modelled(process_kind.PreparedRun[Any, Any]):\n    pass",
    "podklasa-pod-nazwa-z-importu": "from rozliczenia.centrum.process_kind import PreparedRun as _G\nclass M(_G):\n    pass",
}
# Kopie innych wartości, napisy i nazwy typu, które sprawdzenie przepuszcza.
PREPARED_RUN_ALLOWED: typing.Final = {
    "pole-kind-innej-dataclassy": "shown = replace(named, kind=kind, offer=offer)",
    "replace-napisu": 'line = text.replace("PREPARED", "")',
    "replace-bez-wartosci-w-argumencie": "copy = replace(**changes)",
    "replace-innej-funkcji-pod-ta-nazwa": "from os import replace as swap\nswap(prepared, target)",
    "adnotacja-i-isinstance": "def f(run: PreparedRun) -> bool:\n    return isinstance(run, PreparedRun)\n",
    "podklasa-innej-klasy-generycznej": "class Shown(Generic[SummaryT]):\n    pass",
}


@pytest.mark.parametrize("code", PREPARED_RUN_BUILDS.values(), ids=PREPARED_RUN_BUILDS.keys())
def test_sprawdzenie_katalogu_lapie_zlozenie_uruchomienia_obok_catalog_prepared(code: str) -> None:
    assert _prepared_run_builds(ast.parse(code))


@pytest.mark.parametrize("code", PREPARED_RUN_ALLOWED.values(), ids=PREPARED_RUN_ALLOWED.keys())
def test_sprawdzenie_katalogu_przepuszcza_kopie_innych_wartosci(code: str) -> None:
    assert _prepared_run_builds(ast.parse(code)) == []


# Drzewa src z modułem rdzenia a.py i drogą do warstwy skoroszytu, którą sprawdzenie łapie.
WORKBOOK_ROUTES: typing.Final = {
    "import-wprost": {"a.py": "import openpyxl\n"},
    "podmodul-biblioteki": {"a.py": "from openpyxl.styles import Font\n"},
    "przez-inny-modul": {"a.py": "from . import b\n", "b.py": "from .c import X\n", "c.py": "import openpyxl\n"},
    "w-funkcji": {"a.py": "def f():\n    from .b import X\n", "b.py": "from .template_file import Y\n"},
    "w-type-checking": {
        "a.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .template_file import Y\n"
    },
    "modul-z-from-import": {"a.py": "from . import template_file\n"},
    "przez-pakiet": {"a.py": "x = 1\n", "__init__.py": "import openpyxl\n"},
    "pelna-sciezka": {"a.py": "import rozliczenia.b\n", "b.py": "import rozliczenia.template_file\n"},
}


def _source_tree(root: Path, files: dict[str, str]) -> None:
    package = root / "rozliczenia"
    package.mkdir()
    for name, code in {"__init__.py": "", "template_file.py": "import openpyxl\n", **files}.items():
        (package / name).write_text(code, encoding="utf-8")


@pytest.mark.parametrize("files", WORKBOOK_ROUTES.values(), ids=WORKBOOK_ROUTES.keys())
def test_sprawdzenie_rdzenia_lapie_kazda_droge_do_warstwy_skoroszytu(tmp_path: Path, files: dict[str, str]) -> None:
    _source_tree(tmp_path, files)

    assert _workbook_chains("rozliczenia/a.py", tmp_path)


def test_sprawdzenie_rdzenia_przepuszcza_biblioteke_standardowa_i_moduly_bez_skoroszytu(tmp_path: Path) -> None:
    _source_tree(
        tmp_path,
        {
            "a.py": "import json\nfrom . import b, template_files\ndef f():\n    from .c import Y\n",
            "b.py": "from collections.abc import Mapping\nX = 1\n",
            "c.py": "from .b import X\nY = X\n",
            "template_files.py": "NAME = 'template_file'\n",
        },
    )

    assert _workbook_chains("rozliczenia/a.py", tmp_path) == set()


# Znane luki czytania importów (tests/fixtures/znane_luki.py), na którym stoją strażnicy grafu importów: „klasa: postać” →
# moduł rdzenia drzewa ``_source_tree``, który wczytuje skoroszyt, a mimo to przechodzi przez ruff w ``src/``,
# domknięcie ``_workbook_chains`` i ``_imported_modules``.
ZNANE_LUKI_GRAFU: typing.Final = {
    "tylko instrukcja import: importlib.import_module": 'import importlib\n\nSKOROSZYT = importlib.import_module("openpyxl")\n',
    "tylko instrukcja import: __import__": 'SKOROSZYT = __import__("openpyxl")\n',
    "tylko instrukcja import: nazwa modułu src złożona w trakcie działania": 'import importlib\n\nWZORZEC = importlib.import_module("rozliczenia." + "template_file")\n',
    "tylko moduły src: biblioteka spoza src, która sama wczytuje openpyxl": "import pandas\n\nARKUSZ = pandas.read_excel\n",
    "tylko openpyxl i template_file: skoroszyt czytany bez openpyxl": """\
import zipfile


def arkusz(plik: str) -> bytes:
    with zipfile.ZipFile(plik) as skoroszyt:
        return skoroszyt.read("xl/worksheets/sheet1.xml")
""",
}


@wymaga_ruff
def test_znane_luki_grafu_importow_przechodza_przez_ruff_i_czytanie_importow(tmp_path: Path) -> None:
    _source_tree(tmp_path, {})
    pliki = zapisz(ZNANE_LUKI_GRAFU, tmp_path / "rozliczenia")

    zgloszenia = ruff(pliki, sonda=SRC / "rozliczenia" / "sonda_luki.py")
    for opis, plik in pliki.items():
        zgloszenia[opis] += [*_workbook_chains(f"rozliczenia/{plik.name}", tmp_path)]
        zgloszenia[opis] += [f"{line}: {module}" for line, module in _imported_modules(plik) if _is_workbook(module)]

    assert_znane_luki(zgloszenia, "tests/test_granice_importow.py (ZNANE_LUKI_GRAFU)")


def test_kopia_opiekuna_ponownego_startu_importuje_tylko_biblioteke_standardowa_i_siebie() -> None:
    copied = _copied()
    allowed = {_module_name(file) for file in copied}
    found = {
        str(found)
        for file in copied
        for found in _imports(file)
        if not _is_stdlib(found.module) and found.module not in allowed
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Opiekun ponownego startu działa z kopii _COPIED (src/rozliczenia/centrum/restart_guardian.py) bez "
            "bibliotek narzędzia. Dopisz moduł bez zależności do _COPIED albo przenieś kod, który go potrzebuje, "
            "poza moduły kopii.",
        ]
    )


def test_model_i_atrapa_efenix_nie_importuja_kodu_pod_testem() -> None:
    found = {
        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: {ast.unparse(node)}"
        for path, allowed in EFENIX_ORACLE.items()
        for node in wezly(drzewo(path))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for module in ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""])
        if (isinstance(node, ast.ImportFrom) and node.level) or not (_is_stdlib(module) or module in allowed)
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Model efenix (tools/lib/atrapy/model_efenix.py) importuje tylko bibliotekę standardową, a Atrapa efenix "
            "(tools/lib/atrapy/atrapa_efenix.py) tylko ją i model: test porównuje z nimi Wycenę w efenix, więc nie biorą "
            "niczego z kodu pod testem. Napisz potrzebny kod w modelu albo w Atrapie.",
        ]
    )


def test_okno_w_procesie_bierze_z_kodu_pod_testem_tylko_typy_seamu() -> None:
    found = []
    for node in wezly(drzewo(WINDOW_IN_PROCESS)):
        if isinstance(node, ast.Import):
            found += [ast.unparse(node) for alias in node.names if not _is_stdlib(alias.name)]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or not (_is_stdlib(module) or module == "atrapy.model_efenix" or module in WINDOW_SEAM):
                found.append(ast.unparse(node))
            elif module in WINDOW_SEAM:
                imported = importlib.import_module(module)
                found += [
                    f"{module}.{alias.name}"
                    for alias in node.names
                    if not _is_type(getattr(imported, alias.name))
                ]

    assert not found, "\n".join(
        [
            *sorted(found),
            "Okno w procesie (tests/fixtures/okno_w_procesie.py) bierze z rozliczenia tylko klasy i aliasy typów z "
            "efenix_window, a decyzje z modelu efenix (tools/lib/atrapy/model_efenix.py).",
        ]
    )


def _is_type(value: object) -> bool:
    """Klasa (także wyliczenie i wyjątek) albo alias typu (``Callable[...]``, unia)."""

    return isinstance(value, type) or typing.get_origin(value) is not None


def test_wersje_komentarza_uruchomienia_nie_robia_io_i_biora_tylko_nazwy_z_listy() -> None:
    tree = drzewo(SRC / COMMENT_VERSIONS)
    found = []
    for node in wezly(tree):
        if isinstance(node, ast.Import):
            found += [ast.unparse(node) for alias in node.names if alias.name not in PURE_STDLIB]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                found.append(ast.unparse(node))
            elif module in PURE_VERSIONS:
                found += [f"{module}.{alias.name}" for alias in node.names if alias.name not in PURE_VERSIONS[module]]
            elif module not in PURE_STDLIB:
                found.append(ast.unparse(node))

    assert not found, "\n".join(
        [
            *sorted(found),
            f"Wersje komentarza Uruchomienia (src/{COMMENT_VERSIONS}) nie robią I/O i biorą spoza biblioteki standardowej "
            "tylko nazwy z PURE_VERSIONS (tests/test_granice_importow.py). Plik, kolejkę i zegar zostaw powłoce, która "
            "woła ten moduł.",
        ]
    )


def _python_files() -> Iterator[Path]:
    for folder in (SRC, ROOT / "tools", ROOT / "tests", ROOT / ".agents" / "skills"):
        yield from sorted(folder.rglob("*.py"))


def _type_nodes(tree: ast.AST) -> set[ast.AST]:
    """Węzły adnotacji (argumentu, wyniku, zmiennej), importów, typu w ``isinstance`` i nazwy typu porównanej z
    ``type(…)``: nazwa typu niczego tam nie buduje."""

    roots: list[ast.AST] = []
    for node in wezly(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            roots.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            roots.append(node)
        elif isinstance(node, ast.Call) and ast.unparse(node.func) == "isinstance" and len(node.args) == 2:
            roots.append(node.args[1])
        elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Call) and ast.unparse(node.left.func) == "type":
            roots += [comparator for comparator in node.comparators if isinstance(comparator, (ast.Name, ast.Attribute))]
    return {node for root in roots for node in ast.walk(root)}


def _guard_bypasses(tree: ast.Module) -> list[tuple[int, str]]:
    """Miejsca, z których Logi albo tekst po strażniku mogą powstać albo się zmienić z pominięciem ``guard_logs`` i
    ``guard_text`` drogą, której nie zamyka typ ani jego sprawdzenie przy uruchomieniu (docstring ``run_logs_guard._MINTED``):
    ``_MINTED`` w każdej postaci, także napis; nazwa ``GuardedLogs`` albo ``GuardedText`` (także pod inną nazwą z
    importu i jako atrybut modułu) poza adnotacją, importem, ``isinstance`` i ``type(…) is``; napis z tą nazwą (także slot
    ``_GuardedLogs__…``) poza docstringiem. Granice tego sprawdzenia, mypy i ruff pokazują próbki
    ``ZNANE_LUKI_STRAZNIKA``, każda za klasą nazwaną w swojej nazwie."""

    names = GUARDED | {
        alias.asname
        for node in wezly(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in GUARDED and alias.asname
    }
    typed = _type_nodes(tree)
    docstrings = {
        node.value
        for node in wezly(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }
    found = []
    for node in wezly(tree):
        if (
            (isinstance(node, ast.Name) and node.id == "_MINTED")
            or (isinstance(node, ast.Attribute) and node.attr == "_MINTED")
            or (isinstance(node, ast.alias) and node.name == "_MINTED")
            or (isinstance(node, ast.Constant) and node.value == "_MINTED")
        ):
            found.append((getattr(node, "lineno", 0), "_MINTED"))
        elif node in typed:
            continue
        elif (isinstance(node, ast.Name) and node.id in names) or (
            isinstance(node, ast.Attribute) and node.attr in GUARDED
        ):
            found.append((node.lineno, ast.unparse(node)))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node not in docstrings
            and any(name in node.value for name in GUARDED)
        ):
            found.append((node.lineno, repr(node.value)))
    return found


def test_logi_i_tekst_po_strazniku_powstaja_tylko_ze_straznika() -> None:
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {code}"
        for path in _python_files()
        if path not in {SRC / RUN_LOGS_GUARD, GUARD_CHECK}
        for line, code in _guard_bypasses(drzewo(path))
    ]

    assert not found, "\n".join(
        [
            *found,
            f"Logi i tekst po strażniku reguły danych (GuardedLogs, GuardedText) daje tylko guard_logs i guard_text z "
            f"src/{RUN_LOGS_GUARD}. Poza nim te nazwy padają tylko w adnotacjach, importach, isinstance i type(…) is, a napis z nimi i "
            "dowód strażnika (_MINTED) nigdzie, bo object.__new__, object.__setattr__ i cast typ przepuszcza. Kopia, "
            "replace, zmiana pola, podklasa i wartość innego typu rzucają (docstring _MINTED).",
        ]
    )


# Drogi obok guard_logs i guard_text, których typ nie zamyka (przegląd #1038, rundy 1 i 2, i docstring
# run_logs_guard._MINTED). Podklasę zamyka też __init_subclass__, a cast(Any, …) sprawdzenie przy uruchomieniu (testy w
# tests/test_komentarz_logow_uruchomienia.py).
GUARD_BYPASSES: typing.Final = {
    "nowa-wartosc-bez-konstruktora": "logs = object.__new__(GuardedLogs)",
    "slot-istniejacej-wartosci": 'object.__setattr__(logs, "_GuardedLogs__record", record)',
    "logi-sprzed-straznika-rzutowane": "logs = cast(GuardedLogs, record)",
    "rzutowanie-napisem": 'logs = cast("GuardedLogs", record)',
    "konstruktor-z-modulu": "text = run_logs_guard.GuardedText(text, proof)",
    "nazwa-z-importu-pod-inna-nazwa": (
        "from rozliczenia.centrum.run_logs_guard import GuardedLogs as Logs\nlogs = Logs.__new__(Logs)"
    ),
    "dowod-z-importu": "from rozliczenia.centrum.run_logs_guard import _MINTED",
    "dowod-z-atrybutu-modulu": "proof = run_logs_guard._MINTED",
    "dowod-przez-getattr": 'proof = getattr(run_logs_guard, "_MINTED")',
    "dowod-ze-slownika-modulu": 'proof = vars(run_logs_guard)["_MINTED"]',
    "podklasa": "class Mine(GuardedLogs):\n    pass\n",
    "konstruktor-czesciowy": "make = functools.partial(GuardedLogs)",
    # przegląd #1038, runda 3: isinstance zwalnia tylko typ w drugim argumencie, nie wartość w pierwszym
    "w-isinstance": "ok = isinstance(object.__new__(GuardedLogs), GuardedLogs)",
    # dokładny typ zwalnia tylko typ po ``is``, nie wartość w ``type(…)`` ani typ w wywołaniu po ``is``
    "w-type-is": "ok = type(object.__new__(GuardedLogs)) is GuardedLogs",
    "w-type-is-wywolanie": "ok = type(logs) is make(GuardedLogs)",
}


@pytest.mark.parametrize("code", GUARD_BYPASSES.values(), ids=GUARD_BYPASSES.keys())
def test_sprawdzenie_straznika_lapie_kazda_droge_obok_niego_ktorej_typ_nie_zamyka(code: str) -> None:
    assert _guard_bypasses(ast.parse(code))


def test_sprawdzenie_straznika_przepuszcza_typy_po_strazniku_w_adnotacjach_imporcie_isinstance_dokladnym_typie_i_docstringu() -> None:
    code = (
        "from rozliczenia.centrum.run_logs_guard import GuardedLogs, GuardedText\n"
        "def keep(logs: GuardedLogs, text: 'GuardedText | None' = None) -> GuardedLogs:\n"
        '    """Logi po strażniku (``GuardedLogs``) idą dalej bez zmian."""\n'
        "    last: GuardedLogs | None = logs\n"
        "    if not isinstance(logs, GuardedLogs) or not isinstance(text, (GuardedText, type(None))):\n"
        "        raise TypeError\n"
        "    if type(logs) is not GuardedLogs or type(text) is GuardedText:\n"
        "        raise TypeError\n"
        "    return logs\n"
    )

    assert _guard_bypasses(ast.parse(code)) == []


# Znane luki strażnika Logów i tekstu po strażniku (tests/fixtures/znane_luki.py): „klasa: postać” → moduł src, który daje
# albo zmienia ``GuardedLogs`` z pominięciem ``guard_logs``, a mimo to przechodzi przez ruff, mypy i ``_guard_bypasses``.
ZNANE_LUKI_STRAZNIKA: typing.Final = {
    "tylko nazwa z importu: object.__new__(type(logs))": """\
from rozliczenia.centrum.run_logs_guard import GuardedLogs


def pusta(logs: GuardedLogs) -> GuardedLogs:
    return object.__new__(type(logs))
""",
    "refleksja po nazwie: zmiana __class__ przez object.__setattr__": """\
from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.centrum.run_logs_guard import GuardedLogs


def przebierz(record: RunLog, logs: GuardedLogs) -> None:
    object.__setattr__(record, "__class__", type(logs))
""",
    "refleksja po nazwie: zmiana __class__ przez setattr": """\
from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.centrum.run_logs_guard import GuardedLogs


def przebierz(record: RunLog, logs: GuardedLogs) -> None:
    setattr(record, "__class__", type(logs))
""",
    "tłumienie mypy: zmiana __class__ przypisaniem z type: ignore": """\
from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.centrum.run_logs_guard import GuardedLogs


def przebierz(record: RunLog, logs: GuardedLogs) -> None:
    record.__class__ = type(logs)  # type: ignore[assignment]  # próbka
""",
    "tylko stały napis: type(logs) z dowodem z napisu sklejonego": """\
from rozliczenia.centrum import run_logs_guard
from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.centrum.run_logs_guard import GuardedLogs


def podmien(logs: GuardedLogs, record: RunLog) -> GuardedLogs:
    return type(logs)(record, record, getattr(run_logs_guard, "_MIN" + "TED"))
""",
    "tylko stały napis: nazwa typu złożona w trakcie działania": """\
from rozliczenia.centrum import run_logs_guard


def zloz() -> object:
    logi = getattr(run_logs_guard, "Guarded" + "Logs")
    return object.__new__(logi)
""",
    "tylko stały napis: slot z nazwy złożonej": """\
from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.centrum.run_logs_guard import GuardedLogs


def podmien(logs: GuardedLogs, record: RunLog) -> None:
    object.__setattr__(logs, "_Guarded" + "Logs__record", record)
""",
}


@wymaga_ruff_i_mypy
def test_znane_luki_straznika_logow_przechodza_przez_ruff_mypy_i_straznika(tmp_path: Path) -> None:
    pliki = zapisz(ZNANE_LUKI_STRAZNIKA, tmp_path)

    zgloszenia = ruff_i_mypy(pliki, sonda=SRC / "rozliczenia" / "centrum" / "sonda_luki.py")
    for opis, plik in pliki.items():
        zgloszenia[opis] += [f"_guard_bypasses: {code}" for _, code in _guard_bypasses(drzewo(plik))]

    assert_znane_luki(zgloszenia, "tests/test_granice_importow.py (ZNANE_LUKI_STRAZNIKA)")


def _logs_post_breaks(tree: ast.Module, file: str) -> list[tuple[int, str]]:
    """Miejsca pliku ``file``, które mogą zbudować albo przerobić wysyłkę Logów Uruchomienia obok ``post_of``.

    ``replace`` i podklasę gotowej wysyłki (``LogsPost``) odrzuca też typ (docstring ``comment_versions._VERSIONS``),
    ale nie z ``# type: ignore[…]``. Typ przepuszcza też nową ``Post`` złożoną z pól gotowej wysyłki, bo ``Outbox.post``
    bierze też gołą ``Post`` (``Post(sent.target, …, Rank.OWN)`` i ``parts=(record.text,)``, przegląd #1371 r1).
    Dlatego sprawdzenie łapie tylko dwie rzeczy.

    ``post_of`` rozpoznaje po nazwie, a nie po imporcie: każda nazwa i atrybut ``post_of`` (z dowolną bazą) stoi tylko
    w ``<kolejka>.post(post_of(…))``, więc wynik idzie od razu do kolejki i nikt nie przeczyta jego pól. Napis
    ``"post_of"`` (``getattr``, ``vars``) i import ``post_of`` pod inną nazwą to znalezisko.

    Etykietę Logów, z którą da się złożyć nową ``Post``, rozpoznaje po pochodzeniu, bo ``LABEL`` mają też inne wysyłki
    (``quantity_check_run.LABEL``): import ``LABEL`` z ``comment_versions`` pod dowolną nazwą, także względny i przez
    ``*``, oraz atrybut ``LABEL`` i ``getattr`` z napisem ``"LABEL"`` na module ``comment_versions``, czyli na atrybucie
    ``comment_versions`` (``centrum.…``, pełna ścieżka) albo nazwie z importu tego modułu. Poza ``comment_versions`` etykietę kod tylko
    podaje kolejce w pytaniu, czy wysyłka Logów doszła albo została odrzucona (``delivered``, ``rejected``), a w
    ``comment_versions`` używa jej tylko ``post_of``. Napis ``logi-uruchomienia`` stoi poza ``comment_versions`` tylko w
    ``Literal``.

    Granice tego sprawdzenia, mypy i ruff pokazują próbki ``ZNANE_LUKI_WYSYLKI``, każda za klasą nazwaną w swojej nazwie.
    """

    own = file == COMMENT_VERSIONS
    labels = {"LABEL"} if own else set[str]()
    modules = {"comment_versions"}
    found = []
    for node in wezly(tree):
        if isinstance(node, ast.ImportFrom):
            module = _from_module(node, file)
            for alias in node.names:
                if module == VERSIONS and alias.name == "*":
                    found.append((node.lineno, ast.unparse(node)))
                elif module == VERSIONS and alias.name == "LABEL":
                    labels.add(alias.asname or alias.name)
                elif f"{module}.{alias.name}" == VERSIONS:
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            modules |= {alias.asname for alias in node.names if alias.name == VERSIONS and alias.asname}

    parents = {child: node for node in wezly(tree) for child in ast.iter_child_nodes(node)}
    in_post_of = {
        node
        for function in tree.body
        if own and isinstance(function, ast.FunctionDef) and function.name == "post_of"
        for node in ast.walk(function)
    }
    in_types = {
        node
        for subscript in wezly(tree)
        if isinstance(subscript, ast.Subscript) and ast.unparse(subscript.value) in {"Literal", "typing.Literal"}
        for node in ast.walk(subscript)
    }

    def versions_module(node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in modules) or (
            isinstance(node, ast.Attribute) and node.attr == "comment_versions"
        )

    def label(node: ast.AST) -> bool:
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "getattr" and len(node.args) >= 2:
            return versions_module(node.args[0]) and isinstance(node.args[1], ast.Constant) and node.args[1].value == "LABEL"
        return (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in labels) or (
            isinstance(node, ast.Attribute) and node.attr == "LABEL" and versions_module(node.value)
        )

    for node in wezly(tree):
        if isinstance(node, ast.alias) and node.name == "post_of" and node.asname not in {None, "post_of"}:
            found.append((node.lineno, ast.unparse(node)))
        if not isinstance(node, ast.expr):
            continue
        if label(node):
            if not (node in in_post_of if own else _asks_queue(node, parents)):
                found.append((node.lineno, ast.unparse(node)))
        elif (isinstance(node, ast.Name) and node.id == "post_of") or (
            isinstance(node, ast.Attribute) and node.attr == "post_of"
        ):
            if not _queued_at_once(node, parents):
                found.append((node.lineno, ast.unparse(parents.get(node, node))))
        elif isinstance(node, ast.Constant) and node.value == "post_of":
            found.append((node.lineno, repr(node.value)))
        elif not own and isinstance(node, ast.Constant) and node.value == RUN_LOGS_LABEL and node not in in_types:
            found.append((node.lineno, repr(node.value)))
    return found


def _asks_queue(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Etykieta jest argumentem pytania kolejki o wysyłkę: ``….delivered(…)`` albo ``….rejected(…)``."""

    call = parents.get(node)
    if isinstance(call, ast.keyword):
        call = parents.get(call)
    return isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in QUEUE_QUESTIONS


def _queued_at_once(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """``post_of`` wołane i jego wynik jedynym argumentem ``….post(…)`` kolejki."""

    call = parents.get(node)
    queued = parents.get(call) if isinstance(call, ast.Call) and call.func is node else None
    return (
        isinstance(queued, ast.Call)
        and isinstance(queued.func, ast.Attribute)
        and queued.func.attr == "post"
        and queued.args == [call]
        and not queued.keywords
    )


def test_wysylke_logow_uruchomienia_buduje_tylko_post_of() -> None:
    found = [
        f"src/{file}:{line}: {code}"
        for path in sorted((SRC / "rozliczenia").rglob("*.py"))
        for file in [path.relative_to(SRC).as_posix()]
        for line, code in _logs_post_breaks(drzewo(path), file)
    ]

    assert not found, "\n".join(
        [
            *found,
            "Wysyłkę Logów Uruchomienia (etykieta logi-uruchomienia) buduje tylko post_of z wersji komentarza "
            f"(src/{COMMENT_VERSIONS}), która niesie tylko tekst po strażniku i wybiera stopień (rank_of), a jej wynik "
            "idzie od razu do kolejki: outbox.post(post_of(wersja)), bez replace, bez Post złożonej z jego pól, bez "
            "innej nazwy i bez getattr. Etykietę Logów (comment_versions.LABEL) kod poza post_of tylko podaje kolejce w "
            "pytaniu delivered albo rejected.",
        ]
    )


# Wysyłki Logów obok post_of (przegląd #1038, rundy 1 i 2: dwie pierwsze z replace, „pakiet” i „getattr”; przegląd
# #1371 r1: dwie następne, czyli przypadki #1038 r1 bez replace, które mypy przepuszcza). Replace gotowej wysyłki
# odrzuca też mypy (LogsPost), ale nie z # type: ignore[…], więc te próbki zostają.
LOGS_POST_BREAKS: typing.Final = {
    "zastepcza-w-stopniu-logow-z-wynikiem-przez-replace": (
        "from dataclasses import replace\n"
        "from rozliczenia.centrum.comment_versions import OwnLogs, StandInLogs, post_of\n"
        "from rozliczenia.centrum.outbox import Post, Rank\n"
        "def own_from_start(logs):\n"
        "    return replace(post_of(StandInLogs(logs)), rank=Rank.OWN)\n"
    ),
    "komentarz-sprzed-straznika-przez-replace": (
        "from dataclasses import replace\n"
        "from rozliczenia.centrum.comment_versions import OwnLogs, post_of\n"
        "def unguarded(logs, record):\n"
        "    return replace(post_of(OwnLogs(logs)), parts=(record.text + '\\n',))\n"
    ),
    "zastepcza-w-stopniu-logow-z-wynikiem": (
        "from rozliczenia.centrum.comment_versions import StandInLogs, post_of\n"
        "from rozliczenia.centrum.outbox import Post, Rank\n"
        "def own_from_start(outbox, logs):\n"
        "    sent = post_of(StandInLogs(logs))\n"
        "    return outbox.post(Post(sent.target, sent.period, sent.run_id, sent.header, sent.parts, sent.archive, Rank.OWN))\n"
    ),
    "komentarz-sprzed-straznika": (
        "from rozliczenia.centrum.comment_versions import OwnLogs, post_of\n"
        "from rozliczenia.centrum.outbox import Post\n"
        "def unguarded(outbox, logs, record):\n"
        "    sent = post_of(OwnLogs(logs))\n"
        "    return outbox.post(Post(sent.target, sent.period, sent.run_id, sent.header, (record.text + '\\n',), rank=sent.rank))\n"
    ),
    "wysylka-zatrzymana-przed-kolejka": (
        "from rozliczenia.centrum.comment_versions import post_of\n"
        "def send(outbox, version):\n"
        "    post = post_of(version)\n"
        "    outbox.post(post)\n"
    ),
    "wysylka-odlozona-przed-kolejka": (
        "from rozliczenia.centrum.comment_versions import post_of\n"
        "def hold(held, version):\n"
        "    held.append(post_of(version))\n"
    ),
    "post-of-pod-inna-nazwa":"from rozliczenia.centrum import comment_versions as cv\nmake = cv.post_of\n",
    "etykieta-w-nowej-wysylce": (
        "from rozliczenia.centrum.comment_versions import LABEL as RUN_LOGS\n"
        "thread = PeriodThread(label=RUN_LOGS, line='-', closed='reuse', title='t')\n"
    ),
    "etykieta-z-importu-wzglednego": (
        "from . import comment_versions\n"
        "thread = PeriodThread(label=comment_versions.LABEL, line='-', closed='reuse', title='t')\n"
    ),
    "sluchacz-kolejki-zmienia-wysylke-logow": (
        "from dataclasses import replace\n"
        "from rozliczenia.centrum.comment_versions import LABEL\n"
        "def prepare(post, sent):\n"
        "    return replace(post, parts=()) if post.target.label == LABEL else post\n"
    ),
    "etykieta-napisem": "thread = PeriodThread(label='logi-uruchomienia', line='-', closed='reuse', title='t')\n",
    "import-gwiazdki": "from rozliczenia.centrum.comment_versions import *\n",
    "post-of-z-getattr": (
        "from rozliczenia.centrum import comment_versions as cv\n"
        "def send(outbox, version):\n"
        "    make = getattr(cv, 'post_of')\n"
        "    outbox.post(replace(make(version), rank=Rank.OWN))\n"
    ),
    "post-of-ze-slownika-modulu": "def send(outbox, version, cv):\n    outbox.post(vars(cv)['post_of'](version))\n",
    "post-of-atrybutem-pakietu": (
        "from rozliczenia import centrum\n"
        "def send(outbox, version):\n"
        "    outbox.post(replace(centrum.comment_versions.post_of(version), rank=Rank.OWN))\n"
    ),
    "post-of-pelna-sciezka": (
        "import rozliczenia.centrum.comment_versions\n"
        "def send(outbox, version):\n"
        "    outbox.post(replace(rozliczenia.centrum.comment_versions.post_of(version), rank=Rank.OWN))\n"
    ),
    "post-of-z-pakietu-wzglednie": (
        "from .. import centrum\n"
        "def send(outbox, version):\n"
        "    outbox.post(replace(centrum.comment_versions.post_of(version), rank=Rank.OWN))\n"
    ),
    "post-of-z-importu-pod-inna-nazwa": (
        "from rozliczenia.centrum.comment_versions import post_of as make\n"
        "def send(outbox, version):\n"
        "    outbox.post(make(version))\n"
    ),
    "etykieta-atrybutem-pakietu": (
        "from rozliczenia import centrum\n"
        "thread = PeriodThread(label=centrum.comment_versions.LABEL, line='-', closed='reuse', title='t')\n"
    ),
    "etykieta-pelna-sciezka": (
        "import rozliczenia.centrum.comment_versions\n"
        "thread = PeriodThread(label=rozliczenia.centrum.comment_versions.LABEL, line='-', closed='reuse', title='t')\n"
    ),
    "etykieta-z-getattr": (
        "from rozliczenia.centrum import comment_versions as cv\n"
        "thread = PeriodThread(label=getattr(cv, 'LABEL'), line='-', closed='reuse', title='t')\n"
    ),
}


@pytest.mark.parametrize("code", LOGS_POST_BREAKS.values(), ids=LOGS_POST_BREAKS.keys())
def test_sprawdzenie_wysylki_logow_lapie_wysylke_poza_post_of(code: str) -> None:
    assert _logs_post_breaks(ast.parse(code), "rozliczenia/centrum/proba.py")


# Kod, który nie buduje wysyłki Logów (przegląd #1038, runda 1: pierwszy to fałszywy alarm recenzenta).
LOGS_POST_ALLOWED: typing.Final = {
    "etykieta-kontroli-ilosci": (
        "from rozliczenia.centrum import quantity_check_run\n"
        "from rozliczenia.centrum.outbox import PeriodThread\n"
        "def checks_thread(period: str) -> PeriodThread:\n"
        "    return PeriodThread(label=quantity_check_run.LABEL, line=f'- {period}', closed='reuse', title=period)\n"
    ),
    "wersja-od-razu-do-kolejki": (
        "from rozliczenia.centrum.comment_versions import post_of\n"
        "def keep(outbox, version):\n"
        "    return outbox.post(post_of(version))\n"
    ),
    "pytanie-kolejki-o-logi": (
        "from rozliczenia.centrum.comment_versions import LABEL as RUN_LOGS_LABEL\n"
        "def link(sent, run_id):\n"
        "    return sent.delivered(run_id, RUN_LOGS_LABEL) or sent.rejected(run_id, label=RUN_LOGS_LABEL)\n"
    ),
    "etykieta-w-typie": "from typing import Literal\nKind = Literal['logi-uruchomienia', 'kontrola-ilosci']\n",
    "etykieta-kontroli-ilosci-z-getattr": (
        "from rozliczenia.centrum import quantity_check_run\n"
        "thread = PeriodThread(label=getattr(quantity_check_run, 'LABEL'), line='-', closed='reuse', title='t')\n"
    ),
    "wersja-od-razu-do-kolejki-z-pakietu": (
        "from rozliczenia import centrum\n"
        "def keep(self, version):\n"
        "    return self._outbox.post(centrum.comment_versions.post_of(version))\n"
    ),
    "post-of-w-docstringu": 'def keep():\n    """Wysyłka z ``post_of`` idzie od razu do kolejki."""\n',
}


@pytest.mark.parametrize("code", LOGS_POST_ALLOWED.values(), ids=LOGS_POST_ALLOWED.keys())
def test_sprawdzenie_wysylki_logow_przepuszcza_kod_bez_wysylki_logow(code: str) -> None:
    assert _logs_post_breaks(ast.parse(code), "rozliczenia/centrum/proba.py") == []


# Znane luki strażnika wysyłki Logów (tests/fixtures/znane_luki.py): „klasa: postać” → moduł src, który buduje albo zmienia
# wysyłkę Logów Uruchomienia obok ``post_of``, a mimo to przechodzi przez ruff, mypy i ``_logs_post_breaks``.
ZNANE_LUKI_WYSYLKI: typing.Final = {
    "tylko post_of i LABEL: słuchacz kolejki zmienia wysyłkę Logów po run_id": """\
from dataclasses import replace

from rozliczenia.centrum.outbox import Post, Rank


def przygotuj(post: Post, run_id: str) -> Post:
    return replace(post, rank=Rank.OWN) if post.run_id == run_id else post
""",
    "tylko post_of i LABEL: etykieta wzięta z innej wysyłki": """\
from dataclasses import replace

from rozliczenia.centrum.outbox import Post


def jak_logi(logi: Post, inna: Post) -> Post:
    return replace(inna, target=logi.target)
""",
    "tylko nazwa z importu: etykieta z modułu przypisanego innej nazwie poza importem": """\
from rozliczenia.centrum import comment_versions
from rozliczenia.centrum.outbox import PeriodThread
from rozliczenia.client_data import Outgoing

WERSJE = comment_versions


def watek(wiersz: Outgoing, tytul: Outgoing) -> PeriodThread:
    return PeriodThread(label=WERSJE.LABEL, line=wiersz, closed="reuse", title=tytul)
""",
    "tylko stały napis: post_of pod nazwą złożoną w trakcie działania": """\
from rozliczenia.centrum import comment_versions
from rozliczenia.centrum.comment_versions import CommentVersion, LogsPost


def zrob(wersja: CommentVersion) -> LogsPost:
    buduj = getattr(comment_versions, "post" + "_of")
    wysylka: LogsPost = buduj(wersja)
    return wysylka
""",
    "każda metoda post: wynik post_of w metodzie post obiektu, który nie jest kolejką": """\
from rozliczenia.centrum.comment_versions import CommentVersion, LogsPost, post_of


class Schowek:
    def __init__(self) -> None:
        self.wysylki: list[LogsPost] = []

    def post(self, wysylka: LogsPost) -> bool:
        self.wysylki.append(wysylka)
        return True


def odloz(schowek: Schowek, wersja: CommentVersion) -> bool:
    return schowek.post(post_of(wersja))
""",
    "refleksja po nazwie: dowód wersji z getattr": """\
from rozliczenia.centrum import comment_versions
from rozliczenia.centrum.comment_versions import LogsPost
from rozliczenia.centrum.outbox import Post


def wysylka(post: Post) -> LogsPost:
    return LogsPost(post, getattr(comment_versions, "_VERSIONS"))
""",
    "tłumienie ruff: dowód wersji z noqa": """\
from rozliczenia.centrum.comment_versions import _VERSIONS, LogsPost  # noqa: TID251 - próbka
from rozliczenia.centrum.outbox import Post


def wysylka(post: Post) -> LogsPost:
    return LogsPost(post, _VERSIONS)
""",
    "wartość Any: dowód wersji wartością Any": """\
from typing import Any

from rozliczenia.centrum.comment_versions import LogsPost
from rozliczenia.centrum.outbox import Post


def wysylka(post: Post, dowody: dict[str, Any]) -> LogsPost:
    return LogsPost(post, dowody["wersje"])
""",
    "tłumienie mypy: dowód wersji z type: ignore": """\
from rozliczenia.centrum.comment_versions import LogsPost
from rozliczenia.centrum.outbox import Post


def wysylka(post: Post) -> LogsPost:
    return LogsPost(post, None)  # type: ignore[arg-type]  # próbka
""",
    "tłumienie mypy: podklasa gotowej wysyłki z type: ignore": """\
from rozliczenia.centrum.comment_versions import LogsPost


class Moja(LogsPost):  # type: ignore[misc]  # próbka
    pass
""",
    "refleksja po nazwie: type(gotowa) z dowodem z getattr": """\
from rozliczenia.centrum import comment_versions
from rozliczenia.centrum.comment_versions import LogsPost
from rozliczenia.centrum.outbox import Post


def wysylka(gotowa: LogsPost, post: Post) -> LogsPost:
    return type(gotowa)(post, getattr(comment_versions, "_VERSIONS"))
""",
    "refleksja po nazwie: object.__setattr__ slotu gotowej wysyłki": """\
from rozliczenia.centrum.comment_versions import LogsPost
from rozliczenia.centrum.outbox import Post


def podmien(gotowa: LogsPost, inna: Post) -> None:
    object.__setattr__(gotowa, "_LogsPost__post", inna)
""",
}


@wymaga_ruff_i_mypy
def test_znane_luki_wysylki_logow_przechodza_przez_ruff_mypy_i_straznika(tmp_path: Path) -> None:
    pliki = zapisz(ZNANE_LUKI_WYSYLKI, tmp_path)

    zgloszenia = ruff_i_mypy(pliki, sonda=SRC / "rozliczenia" / "centrum" / "sonda_luki.py")
    for opis, plik in pliki.items():
        zgloszenia[opis] += [f"_logs_post_breaks: {code}" for _, code in _logs_post_breaks(drzewo(plik), f"rozliczenia/centrum/{plik.name}")]

    assert_znane_luki(zgloszenia, "tests/test_granice_importow.py (ZNANE_LUKI_WYSYLKI)")


# Wyrocznie skilli i narzędzia, które biorą z ``src`` tylko publiczne nazwy (docs/agents/skille.md, „Co wyrocznia bierze
# z src”).
ORACLES: typing.Final = (".agents/skills/*/scripts/**/*.py", "tools/**/*.py")
SRC_PACKAGE: typing.Final = "rozliczenia"


def _private(name: str) -> bool:
    """Prywatna nazwa: ``_x`` i ``__dict__``, ale nie dunder i nie sam separator ``_``."""

    return (
        name.startswith("_") and name.strip("_") != "" and not (name.startswith("__") and name.endswith("__"))
    ) or name == "__dict__"


def _private_text(node: ast.expr) -> bool:
    """Napis stały z prywatnym członem kropkowym: ``"_x"``, ``"m._x"``, ``"._x"`` (względny import)."""

    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(part.isidentifier() and _private(part) for part in node.value.split("."))
    )


def _src_path(text: object) -> bool:
    """Napis ``rozliczenia.…``: ścieżka kropkowa modułu albo nazwy w ``src``."""

    return isinstance(text, str) and text.split(".")[0] == SRC_PACKAGE and all(
        part.isidentifier() for part in text.split(".")
    )


def _literal(node: ast.expr) -> Iterator[ast.expr]:
    """Węzeł i, gdy to krotka, lista, zbiór, słownik albo rozpakowanie, każdy jego element na dowolnej głębokości."""

    yield node
    if isinstance(node, ast.Starred):
        yield from _literal(node.value)
    elif isinstance(node, ast.Tuple | ast.List | ast.Set):
        for element in node.elts:
            yield from _literal(element)
    elif isinstance(node, ast.Dict):
        for part in (*node.keys, *node.values):
            if part is not None:
                yield from _literal(part)


def _private_in(nodes: typing.Iterable[ast.expr]) -> bool:
    return any(_private_text(part) for node in nodes for part in _literal(node))


def _bound_in_class(node: ast.ClassDef) -> Iterator[tuple[int, str]]:
    """Nazwy, które wiąże ciało klasy w swoim zasięgu, także w ``if``, ``for`` i ``try``: ``def``, ``class``, cel
    przypisania, import, ``except … as`` i przechwycenie w ``case``."""

    pending: list[ast.AST] = [*node.body]
    while pending:
        child = pending.pop()
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield child.lineno, child.name
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            yield child.lineno, child.id
        elif isinstance(child, ast.alias):
            yield child.lineno, child.asname or child.name
        elif isinstance(child, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and child.name:
            yield child.lineno, child.name
        elif isinstance(child, ast.MatchMapping) and child.rest:
            yield child.lineno, child.rest
        if not isinstance(child, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            pending.extend(ast.iter_child_nodes(child))


# Biorą nazwę napisem, a obiekt dopiero w następnym wywołaniu: ``operator.attrgetter("_x")(m)``.
GETTERS: typing.Final = frozenset({"attrgetter", "methodcaller"})
# Biorą obiekt i nazwę atrybutu, którą AST zna tylko wtedy, gdy jest napisem stałym.
BY_NAME: typing.Final = frozenset({"getattr", "setattr", "delattr"})


def _private_reaches(tree: ast.Module) -> list[tuple[int, str]]:
    """Miejsca, w których kod sięga do prywatnej nazwy ``src`` w jednej z postaci wyliczonych niżej.

    Nazwa z ``src`` to nazwa, którą wiąże import z ``rozliczenia`` (``import rozliczenia.x``, ``import … as m``,
    ``from rozliczenia… import n``) albo klasa, której baza jest z ``src`` (``class Log(CentrumLog)`` i dalsze
    podklasy), łańcuch atrybutów i indeksów od takiej nazwy (``outbox.Outbox``, ``runs.RunHost[int]``), indeks napisem
    ścieżki (``sys.modules["rozliczenia.…"]``) i napis stały ``rozliczenia.…``. Wyrażenie z nazwą z ``src`` tylko w
    indeksie (``list[CentrumLog]``, ``REGISTRY[outbox]``) nią nie jest. Prywatny napis to napis stały z członem
    kropkowym ``_x`` (``"_x"``, ``"m._x"``, ``"._x"``). Strażnik łapie dokładnie te postacie:

    1. ``from rozliczenia… import _x`` i import z prywatnego modułu (``from rozliczenia._wnetrze import x``);
    2. ``import rozliczenia…._x``, z ``as`` i bez;
    3. ``m._x`` i ``m.__dict__`` dla nazwy z ``src`` (``outbox._queued``, ``Log._write``,
       ``sys.modules["rozliczenia.…"]._x``) oraz ``vars(m)``;
    4. wywołanie dowolnej funkcji z nazwą z ``src`` w argumencie (pozycyjnym albo nazwanym, na dowolnej głębokości
       krotki, listy, zbioru i słownika) albo jako odbiorcą metody i z prywatnym napisem wśród argumentów (na dowolnej
       głębokości takiego literału) albo prywatnym argumentem nazwanym: ``getattr(m, "_x")``, ``setattr``,
       ``object.__setattr__``, ``mock.patch.object(target=m, attribute="_x")``, ``mock.patch.multiple(m, _x=…)``,
       ``m.__getattribute__("_x")``, ``__import__("rozliczenia.…", fromlist=["_x"])``,
       ``import_module("._x", "rozliczenia.…")``, ``type("X", (CentrumLog,), {"_write": f})``;
    5. prywatny argument nazwany przy wywołaniu nazwy z ``src`` (``ReadFile(…, _forbidden=…, _copy=…)``,
       ``drain(_clock=…)``);
    6. literał krotki, listy, zbioru albo słownika z nazwą z ``src`` wprost (także rozpakowaną: ``(*m.NAMES, "_x")``)
       i prywatnym napisem na dowolnej jego głębokości (``[[m, "_x"]]``, ``{m: "_x"}``,
       ``{"target": m, "attribute": "_x"}``) albo z prywatnym napisem wprost i nazwą z ``src`` na dowolnej głębokości
       (``{"_x": (m, f)}``), więc dwie pary w jednej liście (``[[hypothesis, "_x"], [m, "y"]]``) nie alarmują;
    7. ``attrgetter`` i ``methodcaller`` z prywatnym napisem, choć obiekt dostają w innym wywołaniu;
    8. napis stały ``rozliczenia…._x`` gdziekolwiek (``mock.patch("rozliczenia.centrum.outbox._queued", …)``);
    9. prywatna nazwa, którą wiąże ciało podklasy klasy z ``src``, także pod ``if``, ``for`` i ``try``: ``def``,
       ``async def``, ``class``, cel przypisania, import, ``except … as``, przechwycenie w ``case``; nadpisuje
       prywatną nazwę klasy z ``src`` albo tak wygląda, bo AST nie wie, których nazw klasa z ``src`` nie ma;
    10. ``getattr``, ``setattr`` i ``delattr`` (także ``builtins.``) z nazwą z ``src`` jako pierwszym argumentem i
        nazwą atrybutu, która nie jest napisem stałym (``setattr(preparation_files, name, value)`` w pętli po
        podmienianych nazwach), bo AST nie wie, czy nazwa w zmiennej jest prywatna.

    Każdą inną postać sięgnięcia łapie tylko przegląd, np. przez ``__globals__``, ``vars``, ``__dict__``, ``dir`` albo
    ``inspect.getmembers`` modułu wziętego inaczej niż importem, zmienną, parametr, wynik wywołania albo inne wyrażenie
    (``m = import_module(…)``, ``Base = outbox.Outbox``, ``(m := outbox)._x``, ``REGISTRY[outbox]._x``,
    ``type(x)._y``, ``class X(*[CentrumLog])``), prywatny atrybut instancji (``outbox._draining``, ``super()._write``),
    nazwę złożoną w trakcie działania (f-napis, sklejenie) poza postacią 10, wzorzec ``match`` (``case CentrumLog(_write=w)``), ``exec``
    i ``eval``, prywatny napis w innym wywołaniu niż to z nazwą z ``src`` (``f(m, g("_x"))``, ``dict(_x=…)``), literał
    bez nazwy z ``src`` i prywatnego napisu wprost (``[[m], ["_x"]]``), napis w ciele podklasy
    (``__slots__ = ("_x",)``, ``locals()["_x"] = f``) i przypisanie podklasie po jej definicji, a także to, czy kopia danych o świecie
    zewnętrznym jest celowa.

    Znane fałszywe alarmy: napis ``"_x"`` obok publicznego łańcucha od nazwy z ``src`` alarmuje
    (``Path(outbox.QUEUE_DIRECTORY, "_archiwum")``), bo AST nie odróżni publicznej wartości od klasy
    (``setattr(outbox.Outbox, "_send_all", f)``), a sam separator ``"_"`` nie jest prywatną nazwą. Nazwy z ``src`` nie
    znają zasięgu: parametr albo klasa w innej funkcji o nazwie z ``src`` liczy się jak nazwa z ``src``
    (``def f(outbox): return outbox._ids`` przy ``from rozliczenia.centrum import outbox``). Na HEAD i na commitach
    scalenia PR-ów takich trafień nie ma, a obejście to inna nazwa (``outbox as outbox_module``).
    """

    bound: set[str] = set()
    found: list[tuple[int, str]] = []
    for node in wezly(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == SRC_PACKAGE:
                    bound.add(alias.asname or SRC_PACKAGE)
                    if any(map(_private, alias.name.split("."))):
                        found.append((node.lineno, ast.unparse(node)))
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == SRC_PACKAGE:
            for alias in node.names:
                if _private(alias.name) or any(map(_private, (node.module or "").split("."))):
                    found.append((node.lineno, ast.unparse(node)))
                bound.add(alias.asname or alias.name)

    def from_src(node: ast.expr) -> bool:
        while isinstance(node, ast.Attribute):
            node = node.value
        if isinstance(node, ast.Subscript):
            return from_src(node.value) or (isinstance(node.slice, ast.Constant) and _src_path(node.slice.value))
        return (isinstance(node, ast.Name) and node.id in bound) or (
            isinstance(node, ast.Constant) and _src_path(node.value)
        )

    def src_in(nodes: typing.Iterable[ast.expr]) -> bool:
        return any(from_src(part) for node in nodes for part in _literal(node))

    subclasses = [node for node in wezly(tree) if isinstance(node, ast.ClassDef)]
    while grown := [node for node in subclasses if node.name not in bound and any(map(from_src, node.bases))]:
        bound.update(node.name for node in grown)
    for node in subclasses:
        if node.name in bound:
            found.extend((line, f"{node.name}.{name}") for line, name in _bound_in_class(node) if _private(name))

    for node in wezly(tree):
        if isinstance(node, ast.Attribute) and _private(node.attr) and from_src(node.value):
            found.append((node.lineno, ast.unparse(node)))
        elif isinstance(node, ast.Call):
            values = [*node.args, *(kw.value for kw in node.keywords)]
            called = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            receiver = [node.func.value] if isinstance(node.func, ast.Attribute) else []
            private_keyword = any(kw.arg is not None and _private(kw.arg) for kw in node.keywords)
            with_module = src_in([*values, *receiver]) and (called == "vars" or private_keyword or _private_in(values))
            by_variable = called in BY_NAME and len(node.args) > 1 and from_src(node.args[0])
            by_variable = by_variable and not isinstance(node.args[1], ast.Constant)
            if (
                with_module
                or by_variable
                or (called in GETTERS and _private_in(values))
                or (from_src(node.func) and private_keyword)
            ):
                found.append((node.lineno, ast.unparse(node)))
        elif isinstance(node, ast.Tuple | ast.List | ast.Set | ast.Dict):
            parts = [*filter(None, node.keys), *node.values] if isinstance(node, ast.Dict) else node.elts
            parts = [part.value if isinstance(part, ast.Starred) else part for part in parts]
            if (any(map(from_src, parts)) and _private_in(parts)) or (any(map(_private_text, parts)) and src_in(parts)):
                found.append((node.lineno, ast.unparse(node)))
        elif isinstance(node, ast.Constant) and _src_path(node.value) and _private_text(node):
            found.append((node.lineno, repr(node.value)))
    return sorted(set(found))


def test_wyrocznie_skilli_i_narzedzia_biora_z_src_tylko_publiczne_nazwy() -> None:
    reaches = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {code}"
        for pattern in ORACLES
        for path in sorted(ROOT.glob(pattern))
        for line, code in _private_reaches(drzewo(path))
    ]

    assert reaches == [], (
        "wyrocznia sięga do prywatnej nazwy src; mechanikę bierze przez publiczny punkt obserwacji (nazwę, metodę stanu, "
        "szew), a dane o świecie zewnętrznym kopiuje celowo (docs/agents/skille.md, „Co wyrocznia bierze z src”):\n"
        + "\n".join(reaches)
    )


# Każda droga do prywatnej nazwy src, którą zna sprawdzenie (spis N13 z 7.11.2026: explore_outbox, explore_intermax,
# explore_runs, github_przypadki_aktualnosci).
PRIVATE_REACHES: typing.Final = {
    "atrybut-modulu": "from rozliczenia.centrum import outbox as outbox_module\nv = outbox_module._version(path)",
    "atrybut-modulu-z-pakietu": "from rozliczenia import intermax_replace\nseconds = intermax_replace._RETRY_S",
    "atrybut-klasy": "from rozliczenia.centrum.keyed_box import KeyedBox\nnotes = KeyedBox._notes",
    "pelna-sciezka": "import rozliczenia.centrum.runs\nclass Mine(rozliczenia.centrum.runs._Run):\n    pass\n",
    "import-prywatnej-nazwy": "from rozliczenia.efenix_messages import _UNCHANGED",
    "slownik-modulu": 'from rozliczenia.centrum import outbox\nnames = vars(outbox)\nnames["_queued"] = read',
    "dict-modulu": "from rozliczenia.centrum import outbox\nnames = outbox.__dict__",
    "setattr-z-napisem": 'from rozliczenia import preparation_files\nsetattr(preparation_files, "_write_period_file", step)',
    "getattr-z-napisem": 'from rozliczenia.centrum import runs\nrun = getattr(runs, "_Run")',
    "krotka-podmienianych-nazw": 'from rozliczenia.centrum import runs\nPATCHED = ((runs, "threading"), (runs, "_Run"))',
    "slownik-podmienianych-nazw": 'from rozliczenia.centrum import runs\nPATCHED = {runs: "_Run"}',
    # Przegląd #1115, runda 1: podmiana globalu modułu przez dowolną funkcję, nie tylko getattr/setattr.
    "mock-patch-object": (
        "from unittest import mock\nfrom rozliczenia.centrum import outbox\n"
        'patched = mock.patch.object(outbox, "_queued", read)'
    ),
    "mock-patch-object-ze-slowem-kluczowym": (
        "from unittest import mock\nfrom rozliczenia.centrum import outbox\n"
        'patched = mock.patch.object(outbox, attribute="_queued", new=read)'
    ),
    "builtins-setattr": 'import builtins\nfrom rozliczenia.centrum import outbox\nbuiltins.setattr(outbox, "_queued", 1)',
    "object-setattr": 'from rozliczenia.centrum import outbox\nobject.__setattr__(outbox, "_queued", 1)',
    "mock-patch-sciezka": 'from unittest import mock\npatched = mock.patch("rozliczenia.centrum.outbox._queued", read)',
    "import-module-prywatnego-modulu": 'import importlib\nmodule = importlib.import_module("rozliczenia.centrum._private")',
    "sciezka-przez-prywatny-modul": 'from unittest import mock\npatched = mock.patch("rozliczenia._wnetrze.read", read)',
    # Przegląd #1115, runda 2: moduł na dowolnym miejscu wywołania, prywatna nazwa argumentu nazwanego, para w liście.
    "mock-patch-multiple": (
        "from unittest import mock\nfrom rozliczenia.centrum import outbox\n"
        "patched = mock.patch.multiple(outbox, _queued=read)"
    ),
    "mock-patch-object-wszystko-nazwane": (
        "from unittest import mock\nfrom rozliczenia.centrum import outbox\n"
        'patched = mock.patch.object(target=outbox, attribute="_queued", new=read)'
    ),
    "lista-w-liscie": 'from rozliczenia.centrum import outbox\nPATCHED = [[outbox, "_queued"]]',
    "attrgetter": 'import operator\nfrom rozliczenia.centrum import outbox\nread = operator.attrgetter("_queued")(outbox)',
    "methodcaller": 'import operator\ncall = operator.methodcaller("_remove", path)',
    "import-z-fromlist": 'module = __import__("rozliczenia.centrum.outbox", fromlist=["_queued"])',
    # Reguła ogólna (decyzja koordynatora po rundzie 2): moduł na każdym miejscu, napis na każdej głębokości literału.
    "modul-na-dalszym-miejscu": 'from rozliczenia.centrum import outbox\nswap(read, "_queued", outbox)',
    "napis-w-krotce-argumentu": 'from rozliczenia.centrum import outbox\nswap(outbox, ("threading", "_queued"))',
    "rozpakowanie-w-literale": 'from rozliczenia.centrum import outbox\nswap(outbox, ("threading", *("_queued",)))',
    "slowo-kluczowe-ze-slownika": 'from rozliczenia.centrum import outbox\nswap(outbox, **{"_queued": read})',
    "slownik-nazwanych-argumentow": (
        'from rozliczenia.centrum import outbox\nPATCH = {"target": outbox, "attribute": "_queued"}'
    ),
    "slownik-nazwa-przed-modulem": 'from rozliczenia.centrum import runs\nPATCHED = {"_Run": runs}',
    "para-gleboko-w-literale": 'from rozliczenia.centrum import runs\nPATCHED = (runs, [("_Run", "threading")])',
    "import-module-wzgledny": 'import importlib\nmodule = importlib.import_module("._wnetrze", "rozliczenia.centrum")',
    "sys-modules": 'import sys\nread = sys.modules["rozliczenia.centrum.outbox"]._queued',
    "sciezka-w-stalej": 'TARGET = "rozliczenia.centrum.outbox._queued"',
    "napis-modulu-i-nazwa": 'from unittest import mock\npatched = mock.patch.object("rozliczenia.centrum.outbox", "_queued")',
    # Przegląd #1115, runda 3: nadpisanie prywatnej nazwy klasy z src w podklasie (dawny ``_Log._write`` eksploratora
    # kolejki, explore_outbox.py:795 na #1111) i dwie linie sprawdzenia bez przypadku.
    "nadpisanie-w-podklasie": (
        "from rozliczenia.centrum.log import CentrumLog\n"
        "class Log(CentrumLog):\n    def _write(self, event, **facts):\n        return None\n"
    ),
    "nadpisanie-w-podklasie-async": (
        "from rozliczenia.centrum import outbox\nclass Box(outbox.Outbox):\n    async def _send_all(self):\n        pass\n"
    ),
    "przypisanie-w-podklasie": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Log(CentrumLog):\n    _write = staticmethod(print)\n"
    ),
    "przypisanie-z-adnotacja-w-podklasie": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Log(CentrumLog):\n    _write: object = print\n"
    ),
    "nadpisanie-pod-warunkiem-w-podklasie": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Log(CentrumLog):\n"
        "    if QUIET:\n        def _write(self, event, **facts):\n            return None\n"
    ),
    "klasa-w-podklasie": (
        "from rozliczenia.centrum import outbox\nclass Box(outbox.Outbox):\n    class _State:\n        pass\n"
    ),
    "nadpisanie-w-podklasie-podklasy": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Quiet(Log):\n    def _write(self, event, **facts):\n"
        "        return None\nclass Log(CentrumLog):\n    pass\n"
    ),
    "nadpisanie-w-podklasie-typu-ogolnego": (
        "from rozliczenia.centrum import runs\nclass Mine(runs.RunHost[int]):\n    def _note(self):\n        pass\n"
    ),
    "atrybut-podklasy": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Log(CentrumLog):\n    pass\nwrite = Log._write"
    ),
    "type-z-klasa-z-src": (
        'from rozliczenia.centrum.log import CentrumLog\nLog = type("Log", (CentrumLog,), {"_write": print})'
    ),
    "rozpakowanie-modulu-w-literale": 'from rozliczenia.centrum import outbox\nPATCHED = (*outbox.ADDRESSES_FILE, "_queued")',
    "prywatny-modul-w-stalej": 'TARGET = "rozliczenia._wnetrze"',
    # Przegląd #1123, runda 1: moduł głębiej w literale niż prywatny napis, zbiór, inne wiązania w ciele podklasy i
    # metoda modułu wywołana z napisem.
    "slownik-nazwa-do-pary": 'from rozliczenia.centrum import outbox\nPATCHES = {"_queued": (outbox, read)}',
    "lista-par-nazwa-do-pary": 'from rozliczenia.centrum import outbox\nPATCHES = [("_queued", (outbox, read))]',
    "zbior-w-literale": 'from rozliczenia.centrum import outbox\nPATCHED = {outbox, "_queued"}',
    "zbior-w-argumencie": 'from rozliczenia.centrum import outbox\nswap({outbox}, "_queued")',
    "import-w-podklasie": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Log(CentrumLog):\n    from os import devnull as _write\n"
    ),
    "except-w-podklasie": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Log(CentrumLog):\n"
        "    try:\n        pass\n    except ValueError as _write:\n        pass\n"
    ),
    "case-w-podklasie": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Log(CentrumLog):\n"
        "    match QUIET:\n        case _write:\n            pass\n"
    ),
    "gwiazdka-case-w-podklasie": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Log(CentrumLog):\n"
        "    match QUIET:\n        case [*_write]:\n            pass\n"
    ),
    "reszta-slownika-case-w-podklasie": (
        "from rozliczenia.centrum.log import CentrumLog\nclass Log(CentrumLog):\n"
        "    match QUIET:\n        case {**_write}:\n            pass\n"
    ),
    "getattribute-modulu": 'from rozliczenia.centrum import outbox\nread = outbox.__getattribute__("_queued")',
    # Przegląd #1123, runda 2: prywatny argument nazwany przy wywołaniu nazwy z src (pola ``_forbidden`` i ``_copy``
    # dataklasy ``ReadFile``, src/rozliczenia/dad_files.py) i import prywatnego modułu.
    "prywatny-argument-klasy-z-src": (
        "from rozliczenia.dad_files import ReadFile\nFILE = ReadFile(path, content, None, _forbidden=None, _copy=None)"
    ),
    "prywatny-argument-funkcji-z-src": "from rozliczenia.centrum.outbox import drain\ndrain(_clock=fake)",
    "import-prywatnego-modulu": "import rozliczenia.centrum._wnetrze",
    "import-prywatnego-modulu-jako": "import rozliczenia.centrum._wnetrze as wnetrze",
    "import-z-prywatnego-modulu": "from rozliczenia.centrum._wnetrze import read",
    # Przegląd #1123, runda 3: pętla podmian z nazwą atrybutu w zmiennej (explore_publication.py:511-520 skilla
    # verify-publikacja-plikow-okresu na #1111–#1121).
    "setattr-z-nazwa-w-zmiennej": (
        "from rozliczenia import preparation_files\n"
        "for name, value in REPLACEMENTS.items():\n    setattr(preparation_files, name, value)"
    ),
    "getattr-z-nazwa-w-zmiennej": (
        "from rozliczenia import preparation_files\n"
        "originals = {name: getattr(preparation_files, name) for name in REPLACEMENTS}"
    ),
    "delattr-z-nazwa-w-wyrazeniu": 'from rozliczenia.centrum import outbox\ndelattr(outbox, "_" + NAME)',
    "builtins-setattr-z-nazwa-w-zmiennej": (
        "import builtins\nfrom rozliczenia.centrum import outbox\nbuiltins.setattr(outbox, name, None)"
    ),
    # Przegląd #1123, runda 4: obiekt postaci 10 inny niż goła nazwa z importu.
    "setattr-z-nazwa-w-zmiennej-na-lancuchu": "from rozliczenia import centrum\nsetattr(centrum.outbox, name, None)",
    "setattr-z-nazwa-w-zmiennej-na-sys-modules": (
        "import sys\nsetattr(sys.modules['rozliczenia.centrum.outbox'], name, None)"
    ),
}


@pytest.mark.parametrize("code", PRIVATE_REACHES.values(), ids=PRIVATE_REACHES.keys())
def test_sprawdzenie_wyroczni_lapie_kazda_droge_do_prywatnej_nazwy_src(code: str) -> None:
    assert _private_reaches(ast.parse(code))


def test_sprawdzenie_wyroczni_przepuszcza_publiczne_nazwy_prywatne_pola_wlasnych_obiektow_i_prywatne_nazwy_spoza_src() -> None:
    code = (
        "from unittest import mock\n"
        "import operator\n"
        "import hypothesis\n"
        "from rozliczenia.centrum import outbox as outbox_module\n"
        "from rozliczenia.centrum.outbox import RETRY_S, Outbox\n"
        "class Box:\n"
        "    def __init__(self) -> None:\n"
        "        self._ids = 0\n"
        "def run(outbox: Outbox) -> object:\n"
        '    """Dawniej ``rozliczenia.centrum.outbox._queued``, teraz ``Outbox.state()``."""\n'
        "    names = vars(Box())\n"
        '    show(outbox_module, mock.patch.object(hypothesis, "_settings", None))\n'
        '    mock.patch.multiple(hypothesis, _settings=None)\n'
        '    mock.patch.object(target=hypothesis, attribute="_settings")\n'
        '    patched = [[hypothesis, "_settings"], [outbox_module, "threading"]]\n'
        '    module = __import__("rozliczenia.centrum.outbox", fromlist=["Outbox"])\n'
        '    read = operator.attrgetter("state")(outbox)\n'
        '    log = "rozliczenia.centrum.outbox._queued to stara nazwa"\n'
        '    print(outbox_module, "_queued zastąpiło state()")\n'
        '    setattr(outbox_module, "threading", None)\n'
        '    mock.patch.object(hypothesis, "_settings", None)\n'
        '    mock.patch("rozliczenia.centrum.outbox.LOCAL_QUEUE_DISK", None)\n'
        '    mock.patch("hypothesis._settings", None)\n'
        '    log = "rozliczenia._x to zdanie, nie ścieżka"\n'
        '    log = f"{outbox_module.__name__}._queued"\n'
        '    path = Path(outbox_module.QUEUE_DIRECTORY, "_")\n'
        '    mock.patch("tests.rozliczenia._x", None)\n'
        "    cache = REGISTRY[outbox_module]._cache\n"
        "    setattr(Box(), name, value)\n"
        "    setattr(Box(), name, outbox_module.RETRY_S)\n"
        "    version = getattr(outbox_module, \"SCHEMA_VERSION\")\n"
        '    return outbox.state(), outbox_module.SCHEMA_VERSION, RETRY_S, {outbox_module: "threading"}, getattr(Box(), "_ids")\n'
        "class TrackedRun(Outbox):\n"
        "    def __init__(self) -> None:\n"
        "        _local = 1\n"
        "        self._ids = [_n for _n in range(_local)]\n"
        "    names = {_k: 1 for _k in ()}\n"
        "    limit = _LIMIT\n"
        "    def state(self) -> object:\n"
        "        return super().state()\n"
        "class Own:\n"
        "    def _write(self) -> None:\n"
        "        pass\n"
        "class Logs(list[Outbox]):\n"
        "    def _add(self, box: Outbox) -> None:\n"
        "        self.append(box)\n"
        "def own(box: Box) -> object:\n"
        "    return Box(_ids=1), run(_ids=1), Outbox(state=1), Outbox(\"_tmp\")\n"
    )

    assert _private_reaches(ast.parse(code)) == []


# Kod spoza tests/, który nie importuje pakietu tests: src, narzędzia z bibliotekami, skryptami CI i hookami, skrypty
# skilli i pliki Pythona w korzeniu.
OUTSIDE_TESTS: typing.Final = ("*.py", "src/**/*.py", "tools/**/*.py", "tools/hooks/pre-push", ".agents/skills/*/scripts/**/*.py")
TESTS_PACKAGE: typing.Final = "tests"
_IMPORTERS: typing.Final = frozenset({"importlib.import_module", "import_module", "__import__"})
_PATH_CHANGES: typing.Final = frozenset({"sys.path.insert", "sys.path.append"})


def _of_tests(name: str) -> bool:
    return name == TESTS_PACKAGE or name.startswith(f"{TESTS_PACKAGE}.")


def _names_tests_folder(text: str) -> bool:
    return TESTS_PACKAGE in PureWindowsPath(text).parts


def _tests_imports(tree: ast.Module) -> list[tuple[int, str]]:
    """Moduły pakietu ``tests``, które plik importuje: ``import tests…`` (też ``as``), ``from tests… import …`` (moduł
    pakietu ``tests`` albo ``tests.fixtures`` z nazwy, np. ``from tests.fixtures import settlement``), oba także w funkcji
    i w ``TYPE_CHECKING``; ``importlib.import_module``, ``import_module`` i ``__import__`` ze stałym napisem ``tests…`` w
    pierwszym argumencie; i ``sys.path.insert`` albo ``sys.path.append`` ze stałym napisem, którego częścią ścieżki jest
    ``tests`` (``ROOT / "tests" / "fixtures"``), po którym ``import okno_w_procesie`` sięgnąłby ``tests/fixtures``.

    Granica (tylko przegląd): nazwa albo ścieżka złożona w trakcie działania, ``spec_from_file_location``, ``runpy``,
    ``exec``, ``sys.path`` zmienione inaczej niż ``insert`` i ``append`` oraz ``sys.modules``."""

    found = []
    for node in wezly(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names if _of_tests(alias.name)]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None and _of_tests(node.module):
            package = node.module in (TESTS_PACKAGE, f"{TESTS_PACKAGE}.fixtures")
            found += [(node.lineno, f"{node.module}.{alias.name}" if package else node.module) for alias in node.names]
        elif isinstance(node, ast.Call):
            called = ast.unparse(node.func)
            if called in _IMPORTERS and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str) and _of_tests(first.value):
                    found.append((node.lineno, first.value))
            elif called in _PATH_CHANGES:
                texts = [
                    part.value
                    for argument in node.args
                    for part in ast.walk(argument)
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                ]
                found += [(node.lineno, f"sys.path {text!r}") for text in texts if _names_tests_folder(text)]
    return sorted(set(found))


def _outside_tests() -> list[Path]:
    return sorted({path for pattern in OUTSIDE_TESTS for path in ROOT.glob(pattern) if path.is_file()})


def test_kod_spoza_testow_nie_importuje_testow() -> None:
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {module}"
        for path in _outside_tests()
        for line, module in _tests_imports(drzewo(path))
    ]

    assert found == [], "\n".join(
        [
            *found,
            "Kod spoza tests/ nie importuje tests/ (narzędzia i skille zależałyby od najczęściej zmienianych plików): "
            "atrapę wspólną z testami przenieś do tools/lib/atrapy/, a testy niech importują ją stamtąd.",
        ]
    )


# Każda postać importu tests, którą zna sprawdzenie, i moduł, który z niej czyta.
TESTS_IMPORTS: typing.Final = {
    "import": ("import tests.fixtures.settlement as s", "tests.fixtures.settlement"),
    "import-pakietu": ("import tests", "tests"),
    "from-modulu": ("from tests.fixtures.settlement import PERIOD", "tests.fixtures.settlement"),
    "from-pakietu-fixtures": ("from tests.fixtures import settlement", "tests.fixtures.settlement"),
    "from-pakietu-tests": ("from tests import test_ilosci_uslug", "tests.test_ilosci_uslug"),
    "from-modulu-poza-fixtures": ("from tests.conftest import ROOT", "tests.conftest"),
    "import-w-funkcji": ("def f() -> None:\n    from tests.fixtures.intermax import Intermax", "tests.fixtures.intermax"),
    "type-checking": (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from tests.fixtures.efenix import Order",
        "tests.fixtures.efenix",
    ),
    "importlib": ('import importlib\nm = importlib.import_module("tests.fixtures.settlement")', "tests.fixtures.settlement"),
    "import-module": ('from importlib import import_module\nm = import_module("tests.fixtures.settlement")', "tests.fixtures.settlement"),
    "dunder-import": ('m = __import__("tests.fixtures.settlement")', "tests.fixtures.settlement"),
    "sys-path-folder": ('import sys\nsys.path.insert(0, str(ROOT / "tests" / "fixtures"))', "sys.path 'tests'"),
    "sys-path-napis": ('import sys\nsys.path.append("tests/fixtures")', "sys.path 'tests/fixtures'"),
    "sys-path-windows": ('import sys\nsys.path.append("C:\\\\repo\\\\tests")', "sys.path 'C:\\\\repo\\\\tests'"),
}


@pytest.mark.parametrize(("code", "module"), TESTS_IMPORTS.values(), ids=TESTS_IMPORTS.keys())
def test_sprawdzenie_granicy_testow_lapie_kazda_wyliczona_postac_importu_testow(code: str, module: str) -> None:
    assert [found for _, found in _tests_imports(ast.parse(code))] == [module]


# Katalog każdej części kodu spoza tests/, którą sprawdzenie musi czytać, z jednym jej plikiem.
OUTSIDE_TESTS_PARTS: typing.Final = {
    ".": "run_centrum.py",
    "src/rozliczenia": "src/rozliczenia/engine.py",
    "tools": "tools/rownowaznosc.py",
    "tools/lib/atrapy": "tools/lib/atrapy/settlement.py",
    "tools/ci": "tools/ci/export_openapi.py",
    "tools/hooks": "tools/hooks/pre-push",
    ".agents/skills/verify-rozliczenia/scripts": ".agents/skills/verify-rozliczenia/scripts/doctor.py",
    ".agents/skills/verify-centrum-rozliczen/scripts/drive": ".agents/skills/verify-centrum-rozliczen/scripts/drive/common.py",
}


def test_sprawdzenie_granicy_testow_czyta_kazda_czesc_kodu_spoza_testow() -> None:
    read = {path.relative_to(ROOT).as_posix() for path in _outside_tests()}

    assert {part: file for part, file in OUTSIDE_TESTS_PARTS.items() if file in read} == OUTSIDE_TESTS_PARTS
    assert not any(path.startswith("tests/") for path in read)


def test_sprawdzenie_granicy_testow_przepuszcza_test_uruchomiony_po_sciezce_i_obce_moduly() -> None:
    code = (
        "import importlib\n"
        "import sys\n"
        "import pytest\n"
        "import testsuite\n"
        "from atrapy.atrapa_efenix import atrapa_efenix\n"
        "from .tests import x\n"
        'CONFORMANCE = ROOT / "tests" / "test_ilosci_uslug.py"\n'
        'pytest.main(["-q", f"{CONFORMANCE}::test"])\n'
        'importlib.import_module("testsuite.a")\n'
        'sys.path.insert(0, str(ROOT / "tools" / "lib"))\n'
        'sys.path.insert(0, "my_tests")\n'
        'log = "from tests.fixtures.settlement import PERIOD"\n'
    )

    assert _tests_imports(ast.parse(code)) == []
