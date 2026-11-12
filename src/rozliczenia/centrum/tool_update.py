"""Aktualizacja narzędzia: przesunięcie klonu narzędzia taty na najnowsze Wydanie publicznego repozytorium.

Jedna operacja, ``ToolClone.update``, robi to, co Maks zrobiłby ręcznie
(ADR 0009): znajduje Gita for Windows także poza ``PATH``, pobiera `main` i tagi
Wydań (ADR 0014) ze stałego adresu publicznego repozytorium i przesuwa klon
tylko do przodu, na commit najnowszego Wydania, który był czubkiem `main`
(``newest_on_main``, ``_main_tips``). Lokalna gałąź klonu to dalej `main`.
Pliki taty w ``config/``, które nowa wersja usuwa albo przestaje śledzić,
zostają u niego z dokładnie tą treścią, którą miały (``_DadFiles``). Gdy nowa
wersja zmienia ``requirements.txt``, biblioteki instaluje ten sam Python, w
którym działa Centrum (``pip_install``); nieudana instalacja cofa klon do
commitu sprzed aktualizacji (``ToolClone.roll_back``). Bibliotek się nie cofa:
biblioteki, które Centrum importuje, mają w wymaganiach dolne granice wersji,
więc stara wersja dalej z nimi startuje; dokładnie przypięta jest tylko
biblioteka testów (``hypothesis``), której Centrum nie importuje. Górną granicę
ma tylko Playwright (``<1.65``, #1242): Centrum nie sprawdza wersji bibliotek
przy starcie, więc stara wersja startuje też z nowszym Playwrightem, który
zostawiłoby cofnięcie aktualizacji, która tę granicę zdjęła.
Gdy nie uda się samo cofnięcie, wynik mówi to wprost (``ROLLBACK_FAILED``).
Gdy kopia pliku taty nie wróci do przesuniętego klonu, klon też się cofa; gdy
nie wróci ostatecznie, wynikiem jest ``ROLLBACK_FAILED``, a treść taty zostaje
w kopii. Wynik to kod (``UPDATED``, ``UP_TO_DATE`` albo kod Komunikatu porażki) z
commitem przed i po; treść Komunikatów należy do Centrum
(``update_messages``).

Żadne polecenie Gita nie otwiera okna ani nie czeka na odpowiedź: bez
terminala, bez pomocnika logowania i bez okna konsoli w Windows. Każde kończy
się w swoim limicie czasu, także gdy pomocnik Gita (np. ``git-remote-https``)
zostaje po nim przy zerwanym połączeniu: wyjście idzie do plików tymczasowych,
nie do potoków, a po limicie polecenie wraca, gdy całe drzewo procesów Gita
nie żyje. Każde ufa klonowi tylko na czas wywołania (``safe.directory``), a
konfiguracja Gita taty zostaje bez zmian. Adres repozytorium wstrzykuje się
z zewnątrz; ``origin`` w klonie taty nie ma znaczenia.

Zanim aktualizacja zmieni klon, zapisuje dziennik „Aktualizacja w toku”
(``JOURNAL`` w ``config/`` klonu): commit przed i po oraz kopię plików taty.
Dziennik znika dopiero przy wyniku ostatecznym: po odmowie z plikami taty z
powrotem, po udanym cofnięciu albo gdy opiekun ponownego startu zobaczy, że
nowa wersja odpowiada. Gdy komputer zgaśnie w trakcie, skrót przy następnym
starcie zastaje dziennik i cofa klon (``ToolClone.roll_back``). Gdy w
Centrum nie uda się samo cofnięcie, następne kliknięcie najpierw kończy je z
dziennika, a potem aktualizuje jak zwykle.

Moduł używa tylko biblioteki standardowej: opiekun ponownego startu działa z
jego kopii sprzed aktualizacji, a skrót cofa przerwaną aktualizację, zanim
wczyta biblioteki nowej wersji.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import IO, Final, Literal, TypeGuard

from rozliczenia.file_state import file_state, path_taken
from rozliczenia.tool_files import REPOSITORY_URL, TOOL_ROOT, config_dir

BRANCH: Final = "main"

UPDATED: Final = "ok"
UP_TO_DATE: Final = "AKTUALNA"
# Kody Komunikatów porażek, przy których klon zostaje bez zmian.
NO_GIT: Final = "BRAK_GITA"
# Brak sieci albo GitHub nie odpowiedział w limicie czasu.
NO_CONNECTION: Final = "BRAK_POLACZENIA"
# GitHub prosi o logowanie; Git nie pyta i kończy od razu.
LOGIN: Final = "LOGOWANIE"
OTHER_BRANCH: Final = "INNA_GALAZ"
# Lokalne commity, zmienione śledzone pliki albo nieśledzony plik, który nowa wersja by nadpisała.
LOCAL_CHANGES: Final = "ZMIANY_NA_KOMPUTERZE"
# Kod Komunikatu porażki, której nikt nie przewidział (``GitFailed`` albo inny wyjątek); zamienia go Centrum.
UNEXPECTED: Final = "NIEOCZEKIWANY_BLAD"
# Kod Komunikatu: biblioteki nowej wersji się nie zainstalowały, a klon wrócił do commitu sprzed aktualizacji.
LIBRARIES_FAILED: Final = "INSTALACJA_BIBLIOTEK"
# Kod Komunikatu: nowa wersja nie odpowiedziała po ponownym starcie, więc opiekun cofnął klon i uruchomił starą.
NEW_VERSION_FAILED: Final = "NOWA_WERSJA_NIE_WYSTARTOWALA"
# Kod Komunikatu: klon miał wrócić do commitu sprzed aktualizacji, ale cofnięcie się nie udało.
ROLLBACK_FAILED: Final = "COFNIECIE_NIEUDANE"

Step = Literal["fetching", "installing"]

# Wynik aktualizacji po ponownym starcie Centrum: plik obok Ustawień taty, który zapisuje opiekun ponownego startu,
# a Centrum, które potem wystartuje, odczytuje raz i usuwa.
RESULT_FILE: Final = "centrum-aktualizacja.json"
JOURNAL: Final = "centrum-aktualizacja-w-toku"
GUARDIAN_LEASE_S: Final = 10 * 60.0
_JOURNAL_FORMAT: Final = 1

_FETCHED_MAIN: Final = f"refs/remotes/origin/{BRANCH}"
# Własna przestrzeń na tagi Wydań z GitHuba: tag usunięty albo przesunięty na GitHubie nie zostaje w klonie.
_RELEASES: Final = "refs/wydania/"
_FETCH_TIMEOUT_S: Final = 120.0
_LOCAL_TIMEOUT_S: Final = 60.0
# Logi Uruchomienia ustalają Wydanie, zanim karta pokaże wynik: Git, który nie odpowiada, opóźnia wynik najwyżej o tyle.
_TAGS_TIMEOUT_S: Final = 5.0
# Pobranie, które przez tyle sekund idzie wolniej niż tyle bajtów na sekundę, kończy sam Git: połączenie stoi.
_STALLED_BYTES_PER_S: Final = 1000
_STALLED_FOR_S: Final = 30
_REQUIREMENTS: Final = "requirements.txt"
# Pip na wolnym łączu taty pobiera i rozpakowuje koła bibliotek przez kilka minut.
_INSTALL_TIMEOUT_S: Final = 15 * 60.0
# Zmienne, którymi Git dostałby inne repozytorium albo okno z pytaniem o hasło.
_FOREIGN_VARIABLES: Final = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_ASKPASS",
    "SSH_ASKPASS",
)


_RELEASE_TAG: Final = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


@dataclass(frozen=True, order=True)
class Release:
    """Wydanie: tag ``vMAJOR.MINOR.PATCH``; nowsze to wyższy numer, nie dalszy tag w porządku alfabetycznym."""

    number: tuple[int, int, int]
    tag: str

    @classmethod
    def of_tag(cls, tag: str) -> Release | None:
        """Wydanie z nazwy tagu; ``None`` dla każdego innego tagu."""

        found = _RELEASE_TAG.fullmatch(tag)
        return None if found is None else cls((int(found[1]), int(found[2]), int(found[3])), tag)

    @property
    def version(self) -> str:
        """Numer Wydania tak, jak pokazuje go Centrum: ``0.10.0``, bez „v”."""

        return ".".join(map(str, self.number))


@dataclass(frozen=True)
class NewestRelease:
    """Commit najnowszego Wydania na `main` (``None``: takiego nie ma), tagi wyższych Wydań spoza `main` i samo Wydanie."""

    commit: str | None
    skipped: tuple[str, ...] = ()
    release: Release | None = None


def newest_on_main(commits: Mapping[str, str], on_main: Callable[[str], bool]) -> NewestRelease:
    """Najwyższe Wydanie wśród tagów ``commits`` (tag → commit), którego commit leży na `main` (``on_main``).

    Ten sam wybór robią Aktualizacja i Aktualność narzędzia. Tag, który nie jest
    Wydaniem, się nie liczy; wyższe Wydanie spoza `main` (tag założony z gałęzi
    agenta) jest pominięte i nie zatrzymuje niższego Wydania na `main`.
    """

    releases = sorted((release for tag in commits if (release := Release.of_tag(tag)) is not None), reverse=True)
    skipped: list[str] = []
    for release in releases:
        if on_main(commits[release.tag]):
            return NewestRelease(commits[release.tag], tuple(skipped), release)
        skipped.append(release.tag)
    return NewestRelease(None, tuple(skipped))


@dataclass(frozen=True)
class MainLine:
    """Pobrany `main` i tagi Wydań, tak jak widzi je Aktualizacja narzędzia.

    ``tips`` to linia pierwszych rodziców `main` od czubka, ``releases`` tagi (tag → commit).
    """

    tips: tuple[str, ...]
    releases: Mapping[str, str]

    def newest(self) -> NewestRelease:
        """Najnowsze Wydanie, którego commit był czubkiem `main` (``newest_on_main``); tak wybiera ``ToolClone.update``."""

        tips = frozenset(self.tips)
        return newest_on_main(self.releases, lambda commit: commit in tips)


def fetch_main_line(root: Path, origin: str) -> MainLine:
    """Pobiera do klonu ``root`` `main` i tagi Wydań z ``origin`` tak jak ``ToolClone.update`` i zwraca je.

    Gdy pobranie się nie uda, rzuca ``GitFailed`` z kodem porażki (``NO_GIT``, ``LOGIN`` albo ``NO_CONNECTION``).
    """

    git = find_git()
    if git is None:
        raise GitFailed(NO_GIT)
    run = _Git(git, root)
    failure = run.fetch(origin)
    if failure is not None:
        raise GitFailed(failure)
    return MainLine(_main_tips(run), _release_commits(run))


@dataclass(frozen=True)
class UpdateResult:
    """Wynik Aktualizacji narzędzia: kod, commit przed i po, czy instalowano biblioteki i pominięte Wydania spoza `main`."""

    code: str
    before: str | None
    after: str | None
    installed: bool = False
    skipped: tuple[str, ...] = ()


def write_result(path: Path, result: UpdateResult) -> None:
    """Zapisuje wynik aktualizacji w całości albo wcale."""

    record = {"wynik": result.code, "przed": result.before, "po": result.after, "biblioteki": result.installed}
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(record) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_result(path: Path) -> UpdateResult | None:
    """Wynik aktualizacji z pliku ``write_result``; ``None``, gdy pliku nie ma albo jest nieczytelny."""

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    code, before, after = record.get("wynik"), record.get("przed"), record.get("po")
    if not isinstance(code, str) or not _commit_or_none(before) or not _commit_or_none(after):
        return None
    return UpdateResult(code, before, after, record.get("biblioteki") is True)


def _commit_or_none(value: object) -> TypeGuard[str | None]:
    return value is None or isinstance(value, str)


def find_git(
    *,
    which: Callable[[str], str | None] = shutil.which,
    registry: Callable[[str], str | None] | None = None,
    environ: Mapping[str, str] = os.environ,
) -> Path | None:
    """``git.exe`` z ``PATH``, potem z katalogu Git for Windows w rejestrze, potem ze znanych miejsc instalacji."""

    found = which("git")
    if found:
        return Path(found)
    install_path = registry or _registered_git_for_windows
    candidates = [Path(path, "cmd", "git.exe") for hive in ("HKLM", "HKCU") if (path := install_path(hive))]
    for variable, folders in (
        ("ProgramFiles", ("Git",)),
        ("ProgramFiles(x86)", ("Git",)),
        ("LOCALAPPDATA", ("Programs", "Git")),
    ):
        base = environ.get(variable)
        if base:
            candidates.append(Path(base, *folders, "cmd", "git.exe"))
    return next((candidate for candidate in candidates if file_state(candidate) == "file"), None)


def _registered_git_for_windows(hive: str) -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    root = winreg.HKEY_LOCAL_MACHINE if hive == "HKLM" else winreg.HKEY_CURRENT_USER
    try:
        with winreg.OpenKey(root, r"SOFTWARE\GitForWindows", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallPath")
    except OSError:
        return None
    return value if isinstance(value, str) and value else None


def pip_install(requirements: Path) -> bool:
    """Instaluje ``requirements`` tym samym Pythonem, w którym działa Centrum; ``False``, gdy pip się nie uda.

    Bez ``--user``: pip sam przechodzi na instalację użytkownika, gdy nie może
    pisać do globalnego Pythona. Wyjście pip nie trafia nigdzie; bez okna
    konsoli i bez pytań.
    """

    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--quiet"]
    try:
        result = subprocess.run(
            [*command, "-r", str(requirements)],
            cwd=requirements.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_INSTALL_TIMEOUT_S,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


class GitFailed(Exception):
    """Polecenie Gita nie przeszło z nieprzewidzianego powodu; ``str()`` to samo polecenie, bez wyjścia Gita."""


class JournalKept(Exception):
    """Dziennik „Aktualizacja w toku” zostaje bez zmian: nie da się go bezpiecznie użyć ani zastąpić; ``str()`` mówi czemu."""


@dataclass(frozen=True)
class InterruptedUpdate:
    """Aktualizacja narzędzia z dziennika: commit przed i po, a od ponownego startu termin opiekuna (``guardian_until``)."""

    before: str
    after: str
    guardian_until: float | None = None

    def guardian_may_run(self, now: float) -> bool:
        """Czy opiekun ponownego startu może jeszcze kończyć tę aktualizację (``now`` w sekundach od epoki)."""

        return self.guardian_until is not None and now < self.guardian_until


@dataclass(frozen=True)
class ToolClone:
    """Klon narzędzia w ``root`` i adres repozytorium, z którego przychodzi nowa wersja (``origin``).

    ``install`` instaluje biblioteki z podanego pliku wymagań i mówi, czy się udało.
    """

    root: Path
    origin: str = REPOSITORY_URL
    find_git: Callable[[], Path | None] = find_git
    install: Callable[[Path], bool] = pip_install

    @classmethod
    def of_system(cls) -> ToolClone:
        """Klon, z którego działa to Centrum, i publiczne repozytorium na GitHubie (tylko w Centrum, nie u opiekuna)."""

        return cls(TOOL_ROOT)

    def update(self, on_step: Callable[[Step], None] = lambda step: None) -> UpdateResult:
        """Przesuwa klon do przodu na najnowsze Wydanie; wszystko albo nic.

        Klon, który już zawiera commit najnowszego Wydania (także na nowszym
        commicie `main` z wersji, która pobierała `main`), i GitHub bez
        Wydania na `main` to ``UP_TO_DATE``: aktualizacja nigdy nie cofa
        wersji. Wydania spoza `main` wynik wymienia w ``skipped``.

        ``on_step`` dostaje każdy krok, zanim się zacznie. Po ``UPDATED``
        dziennik „Aktualizacja w toku” zostaje, dopóki nowa wersja nie
        odpowie (``confirm_update``) albo klon się nie cofnie (``roll_back``).
        Dziennik z wcześniejszej aktualizacji, której nie kończy już opiekun
        ponownego startu, najpierw cofa klon; gdy to się nie uda, wynikiem
        jest ``ROLLBACK_FAILED``.
        """

        git = self.find_git()
        if git is None:
            return UpdateResult(NO_GIT, None, None)
        run = _Git(git, self.root)
        journal = self._journal
        interrupted = journal.read()
        if interrupted is not None and not interrupted.guardian_may_run(time.time()):
            if not _moved_back(run, journal):
                return UpdateResult(ROLLBACK_FAILED, interrupted.before, interrupted.after)
        before = run.text("rev-parse", "HEAD")
        if run.branch() != BRANCH:
            return UpdateResult(OTHER_BRANCH, before, None)
        on_step("fetching")
        fetch_failure = run.fetch(self.origin)
        if fetch_failure is not None:
            return UpdateResult(fetch_failure, before, None)
        newest = MainLine(_main_tips(run), _release_commits(run)).newest()
        after, skipped = newest.commit, newest.skipped
        if after is None or run.is_ancestor(after, before):
            return UpdateResult(UP_TO_DATE, before, before, skipped=skipped)
        dad_files = _DadFiles.leaving(run, after)
        if _has_local_commits(run, after) or _changed_tracked_files(run, keep=frozenset(dad_files.names)):
            return UpdateResult(LOCAL_CHANGES, before, None, skipped=skipped)
        journal.begin(self.root, dad_files.names, before, after)
        moved = False
        try:
            with dad_files.set_aside(run, journal.backup):
                # Git odmawia przed zmianą czegokolwiek, np. gdy nieśledzony plik zostałby nadpisany plikiem nowej wersji.
                moved = run.run("merge", "--ff-only", "--quiet", after).returncode == 0
        except _NotPutBack:
            # Wszystko albo nic: klon wraca sprzed kliknięcia, a cofnięcie jeszcze raz wgrywa pliki taty.
            if moved and _moved_back(run, journal):
                return UpdateResult(UNEXPECTED, before, after)
            return UpdateResult(ROLLBACK_FAILED, before, after if moved else None)
        except _NotSetAside:
            journal.end()
            raise
        if not moved:
            journal.end()
            return UpdateResult(LOCAL_CHANGES, before, None)
        try:
            installed = self._install_libraries(run, before, after, on_step)
        except Exception:
            if _moved_back(run, journal):
                raise
            return UpdateResult(ROLLBACK_FAILED, before, after, installed=True)
        if installed is False:
            code = LIBRARIES_FAILED if _moved_back(run, journal) else ROLLBACK_FAILED
            return UpdateResult(code, before, after, installed=True)
        return UpdateResult(UPDATED, before, after, installed=installed is True, skipped=skipped)

    def _install_libraries(self, run: _Git, before: str, after: str, on_step: Callable[[Step], None]) -> bool | None:
        """Instaluje biblioteki, gdy ``after`` zmienia wymagania: czy się udało, a ``None``, gdy nie było czego instalować."""

        if not run.changed(before, after, _REQUIREMENTS):
            return None
        on_step("installing")
        return self.install(self.root / _REQUIREMENTS)

    def roll_back(self) -> None:
        """Cofa aktualizację z dziennika „Aktualizacja w toku” do commitu przed nią, z plikami taty z jego kopii.

        Po cofnięciu dziennik znika. Każda porażka (``GitFailed`` także bez
        Gita, ``OSError``, ``JournalKept``) zostawia dziennik na następną próbę.
        """

        git = self.find_git()
        if git is None:
            raise GitFailed("brak Gita")
        _roll_back(_Git(git, self.root), self._journal)

    def interrupted_update(self) -> InterruptedUpdate | None:
        """Aktualizacja z dziennika „Aktualizacja w toku”; ``None``, gdy żadna nie trwa, ``JournalKept``, gdy jest nieczytelny."""

        return self._journal.read()

    @contextmanager
    def leased_to_guardian(self) -> Iterator[None]:
        """Na start opiekuna ponownego startu: przez ``GUARDIAN_LEASE_S`` ani skrót, ani kliknięcie nie cofają tej aktualizacji.

        Gdy blok rzuci, opiekun nie wystartował, więc termin znika.
        """

        self._journal.lease(time.time() + GUARDIAN_LEASE_S)
        try:
            yield
        except BaseException:
            self._journal.lease(None)
            raise

    def confirm_update(self) -> None:
        """Nowa wersja odpowiada: aktualizacja jest skończona, a jej dziennik znika."""

        self._journal.end()

    @property
    def _journal(self) -> _Journal:
        return _Journal(config_dir(self.root) / JOURNAL)


def _roll_back(git: _Git, journal: _Journal) -> None:
    """``git reset --keep`` do commitu przed aktualizacją z ``journal``; pliki taty z jego kopii przed nim znikają z klonu i po nim do niego wracają.

    Po przesunięciu klonu pliki taty są w nim nieśledzone, a commit przed je
    śledzi: Git odmówiłby ich nadpisania. Po cofnięciu mają treść taty, tak jak
    przed kliknięciem, a dziennik znika. Klon na innym commicie niż przed albo
    po aktualizacji to ``JournalKept``: ktoś go zmienił, więc cofnięcie mogłoby
    zgubić cudzą pracę.
    """

    update = journal.read()
    if update is None:
        raise JournalKept("brak dziennika")
    if git.text("rev-parse", "HEAD") not in (update.before, update.after):
        raise JournalKept("klon na innym commicie")
    names = [copy.relative_to(journal.backup).as_posix() for copy in journal.backup.rglob("*") if file_state(copy) == "file"]
    for name in names:
        (git.root / name).unlink(missing_ok=True)
    try:
        git.check("reset", "--keep", "--quiet", update.before)
    finally:
        _put_back(git.root, journal.backup, names)
    journal.end()


def _moved_back(git: _Git, journal: _Journal) -> bool:
    try:
        _roll_back(git, journal)
    except (GitFailed, OSError, subprocess.SubprocessError, JournalKept):
        return False
    return True


def _put_back(root: Path, backup: Path, names: Iterable[str]) -> None:
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / name, target)


def contains_commit(root: Path, ancestor: str, descendant: str) -> bool:
    """Czy commit ``descendant`` w klonie ``root`` zawiera ``ancestor``; ``False`` bez Gita i bez takiego commitu w klonie.

    Commitu Wydania, którego klon nie ma, nie zawiera żaden commit klonu.
    """

    if ancestor == descendant:
        return True
    git = find_git()
    if git is None:
        return False
    try:
        return _Git(git, root).is_ancestor(ancestor, descendant)
    except (GitFailed, OSError, subprocess.SubprocessError):
        return False


def release_at(root: Path, commit: str, *, find_git: Callable[[], Path | None] = find_git) -> Release | None:
    """Najwyższe Wydanie, którego tag w klonie ``root`` wskazuje dokładnie ``commit``; ``None`` bez Gita, przy błędzie
    Gita i bez takiego tagu.

    Liczą się tagi z instalacji (``refs/tags/``) i pobrane przez Aktualizację narzędzia (``_RELEASES``), także z
    opisem. Commit po Wydaniu nie ma Wydania. Git, który nie odpowie w ``_TAGS_TIMEOUT_S``, to błąd Gita.
    """

    git = find_git()
    if git is None:
        return None
    try:
        listed = _Git(git, root).output(
            "for-each-ref",
            f"--points-at={commit}",
            "--format=%(refname:lstrip=2)",
            _RELEASES,
            "refs/tags/",
            timeout_s=_TAGS_TIMEOUT_S,
        )
    except (GitFailed, OSError, subprocess.SubprocessError):
        return None
    return max((release for tag in listed.split() if (release := Release.of_tag(tag)) is not None), default=None)


def _main_tips(run: _Git) -> tuple[str, ...]:
    """Commity, które były czubkiem pobranego `main`: jego linia pierwszych rodziców, od czubka.

    Commit z gałęzi wciągniętej do `main` zwykłym merge'em leży na `main`, ale nigdy nie był jego czubkiem, więc
    tag Wydania na nim (założony, zanim gałąź weszła do `main`) nie jest Wydaniem z `main`.
    """

    return tuple(run.output("rev-list", "--first-parent", _FETCHED_MAIN).split())


def _release_commits(run: _Git) -> dict[str, str]:
    """Tagi pobrane z GitHuba, które wskazują commit, i te commity (tag z opisem wskazuje go przez obiekt tagu)."""

    # Bez ``tag^{commit}``: Git wołany przez plik .cmd (w testach w Windows) traci ``^``.
    listed = run.output(
        "for-each-ref", "--format=%(refname:lstrip=2) %(objecttype) %(objectname) %(*objecttype) %(*objectname)", _RELEASES
    )
    commits: dict[str, str] = {}
    for line in listed.splitlines():
        name, kind, target, *peeled = line.split()
        kind, target = (peeled[0], peeled[1]) if peeled else (kind, target)
        if kind == "commit":
            commits[name] = target
    return commits


def _has_local_commits(run: _Git, target: str) -> bool:
    """Klon ma commity, których nie ma ``target``: przesunięcie do przodu by je pominęło."""

    return run.text("rev-list", "--count", f"{target}..HEAD") != "0"


def _changed_tracked_files(run: _Git, *, keep: frozenset[str]) -> bool:
    """Śledzony plik klonu różni się od ``HEAD`` (w indeksie albo na dysku), poza plikami taty ``keep``."""

    entries = run.entries("status", "--porcelain=v1", "-z", "--untracked-files=no", "--no-renames")
    return any(entry[3:] not in keep for entry in entries)


class _NotSetAside(GitFailed):
    """``git checkout HEAD --`` nie przywrócił plikom taty treści z ``HEAD``, zanim klon się przesunął."""


class _NotPutBack(Exception):
    """Kopia pliku taty nie wróciła do klonu; jego treść jest tylko w kopii w dzienniku."""


@dataclass(frozen=True)
class _Journal:
    """Dziennik „Aktualizacja w toku” w katalogu ``directory``: ``stan.json`` i kopia plików taty (``backup``).

    ``stan.json`` to ``{"format": 1, "przed", "po", "opiekun_do"}``. Nieznany
    ``format`` albo nieczytelny plik zostaje nietknięty (``JournalKept``);
    nieznane klucze nie mają znaczenia. Kopia trafia na dysk przed
    ``stan.json``, więc dziennik nigdy nie wskazuje niepełnej kopii.
    """

    directory: Path

    @property
    def backup(self) -> Path:
        return self.directory / "pliki-taty"

    @property
    def _state(self) -> Path:
        return self.directory / "stan.json"

    def read(self) -> InterruptedUpdate | None:
        try:
            record = json.loads(self._state.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as unreadable:
            raise JournalKept("nieczytelny") from unreadable
        if not isinstance(record, dict) or record.get("format") != _JOURNAL_FORMAT:
            raise JournalKept("nieznany format")
        before, after, until = record.get("przed"), record.get("po"), record.get("opiekun_do")
        if not isinstance(before, str) or not isinstance(after, str):
            raise JournalKept("bez commitów")
        if not isinstance(until, (int, float)) or isinstance(until, bool):
            until = None
        return InterruptedUpdate(before, after, until)

    def begin(self, root: Path, names: Iterable[str], before: str, after: str) -> None:
        """Trwająca aktualizacja to ``JournalKept``."""

        if path_taken(self._state):
            raise JournalKept("poprzednia aktualizacja w toku")
        self.end()
        for name in names:
            copy = self.backup / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, copy)
            _flush_to_disk(copy)
        self._write(InterruptedUpdate(before, after))

    def lease(self, until: float | None) -> None:
        update = self.read()
        if update is None:
            raise JournalKept("brak dziennika")
        self._write(replace(update, guardian_until=until))

    def end(self) -> None:
        """Najpierw ``stan.json``: bez niego reszta katalogu nic nie znaczy i znika, jeśli się da."""

        self._state.unlink(missing_ok=True)
        shutil.rmtree(self.directory, ignore_errors=True)

    def _write(self, update: InterruptedUpdate) -> None:
        record = {"format": _JOURNAL_FORMAT, "przed": update.before, "po": update.after, "opiekun_do": update.guardian_until}
        temporary = self._state.with_name(self._state.name + ".tmp")
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(record) + "\n", encoding="utf-8")
        _flush_to_disk(temporary)
        os.replace(temporary, self._state)


def _flush_to_disk(path: Path) -> None:
    """Treść pliku na dysku, nie tylko w pamięci systemu: dziennik ma przetrwać wyłączenie komputera."""

    with path.open("r+b") as written:
        os.fsync(written.fileno())


@dataclass(frozen=True)
class _DadFiles:
    """Pliki taty w ``config/``, które przesunięcie klonu usunęłoby: nowa wersja je usuwa albo przestaje śledzić.

    Tata może je mieć zmienione (Konfiguracja wykonawców z prawdziwymi
    nazwiskami po #161); te zmiany nie zatrzymują Aktualizacji narzędzia.
    Przed przesunięciem trafiają do kopii w dzienniku „Aktualizacja w toku”
    i wracają do stanu z ``HEAD``, żeby Git nie odmówił; po przesunięciu
    (udanym albo nie) wraca ich kopia. Inne
    pliki taty (Wzorce, Ustawienia taty, klucz do Zgłoszeń, dziennik, metryki)
    Git zostawia sam, bo ich nie śledzi.
    """

    names: tuple[str, ...]

    @classmethod
    def leaving(cls, git: _Git, fetched: str) -> _DadFiles:
        """Pliki ``config/`` śledzone w ``HEAD``, których nie ma w ``fetched``, a które tata ma u siebie."""

        listed = git.output(
            "diff", "--name-only", "-z", "--no-renames", "--diff-filter=D", "HEAD", fetched, "--", "config/"
        )
        return cls(tuple(name for name in listed.split("\0") if name and file_state(git.root / name) != "missing"))

    @contextmanager
    def set_aside(self, git: _Git, backup: Path) -> Iterator[None]:
        """Przywraca plikom treść z ``HEAD``; po bloku (udanym albo nie) wgrywa z powrotem ich kopie z ``backup``.

        ``_NotPutBack``, gdy kopia nie wróci (np. plik zablokowany): treść taty jest wtedy tylko w ``backup``.
        ``_NotSetAside``, gdy Git nie przywróci treści z ``HEAD``: kopie już wróciły, a klon się nie zmienił.
        """

        try:
            restored = (f":(literal){name}" for name in self.names)
            if self.names and git.run("checkout", "HEAD", "--", *restored).returncode != 0:
                raise _NotSetAside("checkout")
            yield
        finally:
            try:
                _put_back(git.root, backup, self.names)
            except OSError as failure:
                raise _NotPutBack from failure


@dataclass(frozen=True)
class _Git:
    """Polecenia Gita w klonie ``root``: bez okien i pytań, z zaufaniem do klonu tylko na to wywołanie."""

    executable: Path
    root: Path

    def run(self, *args: str, timeout_s: float = _LOCAL_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
        """Polecenie Gita z wyjściem i błędami jako tekst; po ``timeout_s`` ``subprocess.TimeoutExpired``, gdy jego drzewo
        już nie żyje, albo ``OSError``, gdy przeżyje ``_KILL_TIMEOUT_S``.

        Wyjście idzie do plików tymczasowych: potok, który pomocnik Gita trzyma
        otwarty po końcu Gita, wstrzymałby odczyt, a w Windows także po limicie czasu.
        """

        command = [
            str(self.executable),
            "-c",
            f"safe.directory={self.root.as_posix()}",
            "-c",
            "credential.helper=",
            "-c",
            "core.askPass=",
            "-C",
            str(self.root),
            *args,
        ]
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            returncode = _run_tree(command, env=_quiet_environment(), stdout=output, stderr=errors, timeout_s=timeout_s)
            return subprocess.CompletedProcess(command, returncode, _text_of(output), _text_of(errors))

    def check(self, *args: str) -> None:
        if self.run(*args).returncode != 0:
            raise GitFailed(args[0])

    def text(self, *args: str) -> str:
        return self.output(*args).strip()

    def entries(self, *args: str) -> list[str]:
        return [entry for entry in self.output(*args).split("\0") if entry]

    def branch(self) -> str | None:
        """Gałąź, na której stoi klon; ``None``, gdy stoi na commicie bez gałęzi."""

        result = self.run("symbolic-ref", "--quiet", "--short", "HEAD")
        return result.stdout.strip() if result.returncode == 0 else None

    def output(self, *args: str, timeout_s: float = _LOCAL_TIMEOUT_S) -> str:
        result = self.run(*args, timeout_s=timeout_s)
        if result.returncode != 0:
            raise GitFailed(args[0])
        return result.stdout

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Czy ``ancestor`` to ``descendant`` albo jego przodek."""

        result = self.run("merge-base", "--is-ancestor", ancestor, descendant)
        if result.returncode not in (0, 1):
            raise GitFailed("merge-base")
        return result.returncode == 0

    def changed(self, before: str, after: str, name: str) -> bool:
        """Czy ``after`` dodaje albo zmienia plik ``name`` względem ``before``."""

        result = self.run("diff", "--quiet", "--no-renames", "--diff-filter=AM", before, after, "--", f":(literal){name}")
        if result.returncode not in (0, 1):
            raise GitFailed("diff")
        return result.returncode == 1

    def fetch(self, origin: str) -> str | None:
        """Pobiera `main` i tagi Wydań z ``origin``; ``None``, gdy się udało, inaczej kod porażki (logowanie albo brak sieci).

        Adres jest stały, więc każda inna porażka pobrania to brak połączenia z GitHubem.
        """

        try:
            result = self.run(
                "-c",
                "http.proxy=",
                "-c",
                f"http.lowSpeedLimit={_STALLED_BYTES_PER_S}",
                "-c",
                f"http.lowSpeedTime={_STALLED_FOR_S}",
                "fetch",
                "--quiet",
                "--no-tags",
                "--prune",
                origin,
                # Z „+”: po force-pushu `main` na GitHubie pobranie dalej się udaje; klon taty i tak idzie tylko do przodu.
                f"+refs/heads/{BRANCH}:{_FETCHED_MAIN}",
                f"+refs/tags/v*:{_RELEASES}v*",
                timeout_s=_FETCH_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return NO_CONNECTION
        if result.returncode == 0:
            return None
        asked_for_login = any(sign in result.stderr.lower() for sign in _LOGIN_SIGNS)
        return LOGIN if asked_for_login else NO_CONNECTION


# Git bez pytań kończy tak, gdy serwer prosi o logowanie (GitHub także przy repozytorium, którego nie widzi).
_LOGIN_SIGNS: Final = ("terminal prompts disabled", "could not read username", "could not read password", "authentication failed")

# Pod pythonw każde polecenie konsolowe otworzyłoby w Windows własne okno konsoli.
_NO_WINDOW: Final = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _text_of(file: IO[bytes]) -> str:
    file.seek(0)
    return file.read().decode("utf-8", errors="replace")


# Tyle czeka zabijanie drzewa procesów Gita po limicie czasu.
_KILL_TIMEOUT_S: Final = 10.0

# ``_run_tree`` uruchamia polecenie bez okna i bez stdin i oddaje jego kod wyjścia. Po ``timeout_s`` zabija całe
# drzewo jego procesów i rzuca ``subprocess.TimeoutExpired`` dopiero wtedy, gdy żaden z nich już nie żyje.
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _ProcessIds(ctypes.Structure):
        """JOBOBJECT_BASIC_PROCESS_ID_LIST."""

        _fields_ = [
            ("NumberOfAssignedProcesses", wintypes.DWORD),
            ("NumberOfProcessIdsInList", wintypes.DWORD),
            ("ProcessIdList", ctypes.c_size_t * 64),
        ]

    _CREATE_SUSPENDED: Final = 0x0004
    _PROCESS_ID_LIST: Final = 3
    _ERROR_MORE_DATA: Final = 234
    _SYNCHRONIZE: Final = 0x00100000
    _TERMINATE_SET_QUOTA_AND_RESUME: Final = 0x0901
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.restype = _kernel32.OpenProcess.restype = wintypes.HANDLE

    def _run_tree(
        command: list[str], *, env: Mapping[str, str], stdout: IO[bytes], stderr: IO[bytes], timeout_s: float
    ) -> int:
        """Drzewo to zadanie (Job Object); ``OSError``, gdy zadanie nie powstanie albo przeżyje ``_KILL_TIMEOUT_S``."""

        job = wintypes.HANDLE(_kernel32.CreateJobObjectW(None, None))
        if not job.value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            # Wstrzymany do przypisania: inaczej Git zdąży uruchomić pomocnika poza zadaniem.
            process = subprocess.Popen(
                command,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=_NO_WINDOW | _CREATE_SUSPENDED,
            )
            try:
                _join(job, process.pid)
            except BaseException:
                process.kill()
                process.wait()
                raise
            try:
                return process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                # Proces znika z zadania, zanim Windows uzna go za zakończony i puści jego uchwyty (I/O w toku),
                # więc czekamy na uchwyty członków zadania otwarte przed zabiciem.
                deadline = time.monotonic() + _KILL_TIMEOUT_S
                while members := _members(job):
                    if time.monotonic() >= deadline:
                        raise OSError("drzewo procesów Gita przeżyło zabicie") from None
                    opened = (wintypes.HANDLE(_kernel32.OpenProcess(_SYNCHRONIZE, False, pid)) for pid in members)
                    handles = [handle for handle in opened if handle.value]  # bez uchwytu: już się zakończył
                    try:
                        if not _kernel32.TerminateJobObject(job, 1):
                            raise ctypes.WinError(ctypes.get_last_error()) from None
                        for handle in handles:
                            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                            if _kernel32.WaitForSingleObject(handle, remaining_ms) != 0:
                                raise OSError("drzewo procesów Gita przeżyło zabicie") from None
                    finally:
                        for handle in handles:
                            _kernel32.CloseHandle(handle)
                process.wait()
                raise
        finally:
            _kernel32.CloseHandle(job)

    def _join(job: wintypes.HANDLE, pid: int) -> None:
        handle = wintypes.HANDLE(_kernel32.OpenProcess(_TERMINATE_SET_QUOTA_AND_RESUME, False, pid))
        if not handle.value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not _kernel32.AssignProcessToJobObject(job, handle):
                raise ctypes.WinError(ctypes.get_last_error())
            # Popen zamyka uchwyt głównego wątku, więc zamiast ResumeThread wznawia cały proces.
            status = ctypes.WinDLL("ntdll").NtResumeProcess(handle)
            if status != 0:
                raise OSError(f"NtResumeProcess: NTSTATUS 0x{status & 0xFFFFFFFF:08X}")
        finally:
            _kernel32.CloseHandle(handle)

    def _members(job: wintypes.HANDLE) -> list[int]:
        """PID-y procesów zadania ``job``, najwyżej 64 (Git ma ich kilka)."""

        ids = _ProcessIds()
        if not _kernel32.QueryInformationJobObject(job, _PROCESS_ID_LIST, ctypes.byref(ids), ctypes.sizeof(ids), None):
            error = ctypes.get_last_error()
            if error != _ERROR_MORE_DATA:
                raise ctypes.WinError(error)
        return list(ids.ProcessIdList[: ids.NumberOfProcessIdsInList])

else:

    def _run_tree(
        command: list[str], *, env: Mapping[str, str], stdout: IO[bytes], stderr: IO[bytes], timeout_s: float
    ) -> int:
        """Drzewo to sesja Gita."""

        process = subprocess.Popen(
            command, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True
        )
        try:
            return process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            with suppress(OSError):  # Git i jego pomocnicy już się zakończyli
                os.killpg(process.pid, signal.SIGKILL)
            process.kill()
            process.wait()
            raise


def _quiet_environment() -> dict[str, str]:
    """Środowisko Gita bez pytań i okien, z komunikatami po angielsku i bez serwera proxy."""

    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in _FOREIGN_VARIABLES and not name.lower().endswith("_proxy")
    }
    return environment | {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "LC_ALL": "C", "LANGUAGE": "C"}
