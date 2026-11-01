"""Zakres runu CI: co CI uruchamia dla zdarzenia (push, pull request, noc) i zmiany, każda praca z powodem i poleceniem.

Jedyne miejsce polityki „co biegnie” (ADR 0020, ADR 0021); plan runu (``tools/plan_ci.py``) tylko wycenia i pakuje
wynik, ``tools/skille_dla_zmiany.py`` drukuje z niego linie ``LICZY CI`` i ``LICZY NOC``, a
``tools/ci/mutacje_skilli.py`` uruchamia kroki skilli pushu:

    praca = zakres(Zdarzenie.PULL_REQUEST, changed_since(ROOT, "origin/main"), ROOT)
    praca.tory, praca.pliki, praca.zrodlo        # pytest: tory z krokami CI i pliki testów
    praca.przegladarka                           # pliki testów, którym zadanie pytest instaluje Chromium
    praca.wybrane, praca.pominiete, praca.bledy  # kroki skilli z powodem i FAIL-e ich znalezienia
    praca.polecenia(skill)                       # polecenia skilla, które CI liczy w tym runie

Pytest. Na pushu to pełne CI ``main``: trzy tory (``TORY``: Windows 3.11, Windows 3.14, Linux 3.14), na każdym każdy plik
testów ``tests/``, oraz kroki CI (``KROKI``) na swoich torach: E2E na obu Windows, straż czasu na Windows 3.14. Na pull
request to bramka PR: tory Windows 3.11 (minimum u taty) i Linux 3.14, na każdym pliki z wyboru wpływu zmiany
(``tools/lib/wplyw_zmiany.py``) i testy ``STRUCTURE`` (węzeł ``plik::test`` biegnie sam, gdy jego pliku nie ma w
wyborze). Zmiana ścieżki, która w tabeli reguł wpływu uruchamia wszystko w bramce PR (``Context.PR_GATE``), wybiera
wszystkie pliki, E2E i straż czasu. Inaczej na Windows 3.11 E2E biegnie przy zmianie pod ``src/``, a straż czasu przy
zmianie w domknięciu jej skryptów (``STRAZ``). Noc (workflow ``mutacje-nocne.yml``) nie ma pytest. Plik testów, który
sięga ``PRZEGLADARKA`` (Atrapa efenix, z którą rozmawia tylko przeglądarka: Chromium testu albo Skryptu dla maszyn),
potrzebuje Chromium, więc zadanie pytest z nim je instaluje.

Kroki skilli (``tools/lib/kroki_skilli.py``). Na pushu biegnie każdy. Na pull request biegnie podstawa ``ci:``, gdy
zmieniony jest plik z ``pilnuje`` albo plik w folderze skilla, i skrypt mutacji modelu TLA+ (``model_watched``: każda
jego mutacja psuje plik w folderze ``model/`` skilla), gdy zmieniony jest plik w tym folderze, sam skrypt albo
sprawdzenie, które uruchamiają jego mutacje; inne skrypty mutacji biegną nocą (ADR 0021). Nocą biegnie skrypt mutacji,
gdy zmieniony jest plik w folderze skilla, runner mutacji (``RUNNER``) albo sprawdzenie, które uruchamiają jego mutacje,
i podstawa z ``ci-czesci`` przy tej samej zmianie co na pull request, każdą częścią każdej liczby części od 1 do
``ci-czesci`` (``KrokSkilla.czesci``), bo pull request uruchamia części jednej liczby, którą plan wybiera z celu ściany.
Zmiana ścieżki z ``Context.SKILL_STEPS`` uruchamia każdy krok swojego rodzaju, a skill bez klucza ``pilnuje`` albo z
kluczem, którego nie da się odczytać, biegnie zawsze. Importów ani plików, które krok czyta, wybór nie liczy: każdy krok
uruchamia pełne CI ``main``. Podstawa, którą wybrany skrypt mutacji jej skilla i tak uruchamia bez mutacji (podstawa
``check_all``), nie biegnie drugi raz.

Polecenia skilla, które CI liczy, to wybrane kroki skilla i wywołania jego skryptów w krokach CI torów runu; nic więcej
w ``ci.yml`` nie wywołuje skryptu skilla (``tests/test_zakres_runu.py``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
import enum
from pathlib import Path, PurePosixPath

from kroki_skilli import Step, hits, model_watched, repeats, watched, znajdz
from wplyw_zmiany import Context, Repository, run_all, with_structure

__all__ = [
    "E2E", "KROKI", "MUTACJE", "PRZEGLADARKA", "STRAZ", "TIMING", "TORY", "Krok", "KrokSkilla", "Tor", "ZakresRunu", "Zdarzenie", "pliki_testow", "zakres",
]

ROOT = Path(__file__).resolve().parents[2]
# Domyślne python_files pytest: pyproject.toml go nie zmienia.
PLIKI_TESTOW = ("test_*.py", "*_test.py")
# Powody pominięcia kroku skilla, który biegnie przy innym zdarzeniu.
NIGHTLY = "skrypt mutacji biegnie nocą na main (mutacje-nocne.yml, ADR 0021)"
ON_PULL_REQUEST = "podstawa biegnie na pull request, nie nocą"
MODEL_UNTOUCHED = "skrypt mutacji modelu biegnie na pull request tylko przy zmianie modelu, skryptu albo sprawdzeń jego mutacji, a poza tym nocą"


class Zdarzenie(enum.StrEnum):
    """Zdarzenie runu: ``github.event_name`` workflow ``ci.yml`` albo ``noc`` (``mutacje-nocne.yml``); wartość stoi w planie."""

    PULL_REQUEST = "pull_request"
    PUSH = "push"
    NOC = "noc"


@dataclass(frozen=True)
class Krok:
    """Krok CI spoza pytest: polecenia po kolei, każde z limitem; ``{python}``, ``{temp}``, ``{podsumowanie}``.

    Polecenie to jeden napis z argumentami po spacji; jego słowa to argumenty procesu (``tools/plan_ci.py``).
    """

    nazwa: str
    polecenia: tuple[str, ...]
    limity_s: tuple[float, ...]
    domyslnie_s: float

    def wywolania(self, skill: str) -> list[tuple[str, ...]]:
        """Wywołania skryptów skilla ``skill`` (``.agents/skills/<skill>/scripts/``): nazwa skryptu i jego argumenty."""

        found = []
        for polecenie in self.polecenia:
            words = polecenie.split()
            for number, word in enumerate(words):
                if PurePosixPath(word).parts[:4] == (".agents", "skills", skill, "scripts") and word.endswith(".py"):
                    found.append((PurePosixPath(word).name, *words[number + 1 :]))
                    break
        return found


E2E = Krok("e2e", ("{python} .agents/skills/verify-rozliczenia/scripts/run_verification.py --variant all",), (15 * 60,), 60.0)
# Straż czasu Przebiegu rozliczeń (spec #141, #145): benchmark „typowy tydzień” na syntetycznych Wzorcach kształtu
# Wzorców taty (tools/syntetyczne_wzorce.py), bo prawdziwych nie ma w repozytorium. Budżet 180 000 ms to mediana
# czasu ściany typowego tygodnia na runnerze; krok pada tylko powyżej niego. Docelowo 3 × cel twardy po przeliczeniu
# na runner: 3 × 18 s (Mac M4 Max) × ~3,3 ≈ 180 000 ms (Mac → komputer taty, i7-10875H; windows-latest ma podobną
# wydajność jednego rdzenia). Po #147 (ADR 0008) Przebieg trwa ~3 s na Macu, czyli ~10 s na runnerze: budżet
# przepuszcza szum współdzielonych runnerów, a łapie powrót do pełnego zapisu przez openpyxl (~240 s). To jedyne
# miejsce budżetu. Najdłuższy pomiar trwał 13 min (CI 20.10–25.10), mediana 1 min.
TIMING = Krok(
    "timing",
    (
        "{python} tools/syntetyczne_wzorce.py {temp}/syntetyczne-wzorce",
        "{python} tools/benchmark_przebiegu.py measure --scenario typowy-tydzien --templates-dir {temp}/syntetyczne-wzorce"
        " --config {temp}/syntetyczne-wzorce/worker_mapping.yaml --mirror-dir {temp}/lustro --journal {temp}/przebieg.jsonl"
        " --machine github-windows-latest",
        "{python} tools/benchmark_przebiegu.py guard --journal {temp}/przebieg.jsonl --budget-ms 180000 --summary {podsumowanie}",
    ),
    (10 * 60, 30 * 60, 10 * 60),
    25.0,
)
KROKI = {krok.nazwa: krok for krok in (E2E, TIMING)}
# Skrypty straży czasu: na pull request biegnie, gdy zmiana sięga ich wykonania (import, czytany plik).
STRAZ = ("tools/syntetyczne_wzorce.py", "tools/benchmark_przebiegu.py")
# Atrapa efenix odpowiada tylko przeglądarce: plik testów, który sięga jej modułu, prowadzi Chromium sam albo przez
# Skrypt dla maszyn.
PRZEGLADARKA = "tests/fixtures/atrapa_efenix.py"


@dataclass(frozen=True)
class Tor:
    nazwa: str  # początek id zadań toru
    szablon: str  # zadanie ci.yml, którego macierz to zadania toru
    pomiary: str  # tor czasów w czasy-ci: system i Python runnera
    os: str
    python: str
    kroki: tuple[str, ...]
    zadanie: str  # nazwa zadania w runie, jak przed planem: "pytest (Python 3.14, Linux, 1/3)"


TORY = (
    Tor("windows-3.11", "pytest", "windows-3.11", "windows-latest", "3.11", ("e2e",), "pytest (Python 3.11, {numer}/{liczba})"),
    Tor("windows-3.14", "pytest", "windows-3.14", "windows-latest", "3.14", ("e2e", "timing"), "pytest (Python 3.14, {numer}/{liczba})"),
    Tor("linux-3.14", "pytest", "linux-3.14", "ubuntu-latest", "3.14", (), "pytest (Python 3.14, Linux, {numer}/{liczba})"),
)
# Drive Centrum potrzebuje Windows (#409: tzdata, strefa, stare Centrum po aktualizacji); skille niezależne od systemu
# przejdą na Linuksa po jednym, każdy z dowodem, że jego mutacje dalej są wykrywane.
MUTACJE = Tor("mutacje", "mutations", "windows-3.14", "windows-latest", "3.14", (), "Mutation checks ({numer}/{liczba})")


def pliki_testow(root: Path = ROOT) -> list[str]:
    return sorted({sciezka.relative_to(root).as_posix() for wzorzec in PLIKI_TESTOW for sciezka in (root / "tests").rglob(wzorzec)})


@dataclass(frozen=True)
class KrokSkilla:
    """Wybrany krok skilla z powodem (na pushu pusty); ``czesci`` to części ``(k, n)``, które biegną, gdy ustala je
    zakres (nocą każda część każdego n podstawy z ``ci-czesci``), a puste: plan dzieli krok sam do ``Step.parts``."""

    krok: Step
    powod: str
    czesci: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class ZakresRunu:
    """Praca runu: tory pytest z krokami CI, pliki testów (albo węzły ``plik::test``) i skąd są, kroki skilli wybrane i
    pominięte z powodem oraz FAIL-e znalezienia kroków (posortowane)."""

    zdarzenie: Zdarzenie
    tory: tuple[Tor, ...]
    pliki: tuple[str, ...]
    zrodlo: str  # do linii PLAN CI: ``wszystkie pliki``, ``wybór <n> plików``, ``FULL (<pliki>)``, ``bez pytest``
    wybrane: tuple[KrokSkilla, ...]
    pominiete: tuple[tuple[Step, str], ...]
    bledy: tuple[tuple[str, str], ...]
    przegladarka: frozenset[str] = frozenset()  # pliki z ``pliki``, które sięgają ``PRZEGLADARKA``

    def kroki_skilla(self, skill: Path) -> list[Step]:
        """Wybrane kroki skilla ``skill`` (folder), w kolejności wyboru."""

        return [wybrany.krok for wybrany in self.wybrane if wybrany.krok.skill == skill]

    def polecenia(self, skill: Path) -> list[tuple[str, ...]]:
        """Polecenia skilla (nazwa skryptu z argumentami), które CI liczy w tym runie: jego wybrane kroki i wywołania
        jego skryptów w krokach CI torów runu, bez powtórzeń."""

        runs = [(Path(step.command[0]).name, *step.command[1:]) for step in self.kroki_skilla(skill)]
        for nazwa in sorted({nazwa for tor in self.tory for nazwa in tor.kroki}):
            runs += KROKI[nazwa].wywolania(skill.name)
        return list(dict.fromkeys(runs))


def zakres(zdarzenie: Zdarzenie, zmiana: frozenset[str], root: Path = ROOT) -> ZakresRunu:
    """Zakres runu ``zdarzenie`` dla zmiany ``zmiana`` (ścieżki od bazy; push jej nie czyta) w checkoucie ``root``."""

    tory, pliki, zrodlo = _pytest(zdarzenie, zmiana, root)
    found, failed = znajdz()
    why = {step: _dlaczego(step, zdarzenie, zmiana) for step in found}
    running = [step for step in found if why[step][0]]
    wybrane = tuple(
        KrokSkilla(step, why[step][1], _czesci(step, zdarzenie)) for step in running if step.verdict or not repeats(step, running)
    )
    pominiete = tuple((step, why[step][1]) for step in found if not why[step][0])
    przegladarka = Repository.scan(root).reaching(PRZEGLADARKA) & {plik.partition("::")[0] for plik in pliki} if pliki else frozenset()
    return ZakresRunu(zdarzenie, tory, pliki, zrodlo, wybrane, pominiete, tuple(sorted(failed.items())), przegladarka)


def _pytest(zdarzenie: Zdarzenie, zmiana: frozenset[str], root: Path) -> tuple[tuple[Tor, ...], tuple[str, ...], str]:
    match zdarzenie:
        case Zdarzenie.NOC:
            return (), (), "bez pytest"
        case Zdarzenie.PUSH:
            return TORY, tuple(pliki_testow(root)), "wszystkie pliki"
        case Zdarzenie.PULL_REQUEST:
            windows, linux = (tor for tor in TORY if tor.nazwa in ("windows-3.11", "linux-3.14"))
            if full := run_all(zmiana, Context.PR_GATE):
                return (replace(windows, kroki=("e2e", "timing")), linux), tuple(pliki_testow(root)), f"FULL ({', '.join(full)})"
            wybor = Repository.scan(root).impact(zmiana)
            kroki = ("e2e",) * any(sciezka.startswith("src/") for sciezka in zmiana) + ("timing",) * any(skrypt in wybor.distances for skrypt in STRAZ)
            return (replace(windows, kroki=kroki), linux), with_structure(wybor.tests), f"wybór {len(wybor.tests)} plików"


def _czesci(step: Step, zdarzenie: Zdarzenie) -> tuple[tuple[int, int], ...]:
    """Nocą podstawa z ``ci-czesci: n`` biegnie każdą częścią ``k/m`` każdego m od 1 do n (ADR 0021)."""

    if zdarzenie is Zdarzenie.NOC and step.verdict is None and step.parts > 1:
        return tuple((k, n) for n in range(1, step.parts + 1) for k in range(1, n + 1))
    return ()


def _dlaczego(step: Step, zdarzenie: Zdarzenie, zmiana: frozenset[str]) -> tuple[bool, str]:
    """Czy krok skilla biegnie w runie ``zdarzenie`` przy zmianie ``zmiana``, i dlaczego."""

    match zdarzenie:
        case Zdarzenie.PUSH:
            return True, ""
        case Zdarzenie.PULL_REQUEST:
            return _podstawa(step, zmiana) if step.verdict is None else _skrypt_modelu(step, zmiana)
        case Zdarzenie.NOC:
            if step.verdict is not None:
                return _skrypt(step, zmiana)
            return _podstawa(step, zmiana) if step.parts > 1 else (False, ON_PULL_REQUEST)


def _zawsze(step: Step, zmiana: frozenset[str]) -> str | None:
    """Powód, z którego krok biegnie przy każdej zmianie: skill bez czytelnego ``pilnuje`` albo zmiana z ``SKILL_STEPS``."""

    if always := hits(step.skill, zmiana).always:
        return always
    if infrastructure := run_all(zmiana, Context.SKILL_STEPS):
        return _changes(infrastructure)
    return None


def _podstawa(step: Step, zmiana: frozenset[str]) -> tuple[bool, str]:
    if reason := _zawsze(step, zmiana):
        return True, reason
    if found := hits(step.skill, zmiana).files:
        return True, _changes(found)
    return False, "zmiany nie trafiają w pilnuje ani w folder skilla"


def _skrypt(step: Step, zmiana: frozenset[str]) -> tuple[bool, str]:
    if reason := _zawsze(step, zmiana):
        return True, reason
    try:
        paths = watched(step)
    except Exception as error:  # noqa: BLE001 - skrypt, którego tabeli nie da się wczytać, biegnie i pokazuje swój błąd
        return True, f"nie da się wczytać tabeli mutacji: {error}"
    if touched := _touched(zmiana, paths):
        return True, _changes(touched)
    return False, "zmiany nie dotykają folderu skilla, runnera mutacji ani sprawdzeń, które uruchamiają mutacje skryptu"


def _skrypt_modelu(step: Step, zmiana: frozenset[str]) -> tuple[bool, str]:
    """Na pull request biegnie tylko skrypt mutacji modelu, przy zmianie ścieżki z ``model_watched``."""

    try:
        paths = model_watched(step)
    except Exception as error:  # noqa: BLE001 - zmieniony skrypt, którego tabeli nie da się wczytać, biegnie i pokazuje swój błąd
        return (True, f"nie da się wczytać tabeli mutacji: {error}") if step.command[0] in zmiana else (False, NIGHTLY)
    if paths is None:
        return False, NIGHTLY
    if touched := _touched(zmiana, paths):
        return True, _changes(touched)
    return False, MODEL_UNTOUCHED


def _touched(zmiana: frozenset[str], paths: tuple[str, ...]) -> set[str]:
    """Zmienione ścieżki pod folderem ``paths[0]`` albo równe jednej z reszty ``paths``."""

    return {name for name in zmiana if name.startswith(paths[0]) or name in paths[1:]}


def _changes(names: Iterable[str]) -> str:
    names = sorted(names)
    return f"zmienione: {', '.join(names[:3])}" + (f" i {len(names) - 3} innych" if len(names) > 3 else "")
