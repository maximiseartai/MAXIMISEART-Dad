"""Sprawdza model TLA+ wznowienia Wyceny w efenix przy każdej kolejności Zatrzymań, zgaśnięć, zapisów śladu i zmian taty.

Uruchamia TLC na każdej konfiguracji z ``model/*.cfg``, porównuje wynik z ``model/oczekiwane.json`` i opowiada każdy
kontrprzykład krokami kodu. Javę i ``tla2tools.jar`` bierze z narzędzi skilla ``verify-aktualizacja-narzedzia``
(``sprawdz_aktualizacje.py``: przypięte ``jdk4py`` i jar w jego katalogu podręcznym), a zmienne ``TLC_JAVA`` i
``TLC_JAR`` je zastępują: kopia checkoutu mutacji nie ma ignorowanego katalogu podręcznego. Na końcu ostrzega, gdy
któraś definicja z ``DEFINITIONS`` zmieniła się od commitu synchronizacji z ``SKILL.md``. W CI (``GITHUB_ACTIONS=true``)
rozjazd kończy się od razu linią ``WZNOWIENIE WYCENY: ROZJAZD MODELU Z KODEM`` i kodem 1, bez TLC.

    .venv/bin/python .agents/skills/verify-wznowienie-wyceny-efenix/scripts/sprawdz_wznowienie_wyceny.py
    py -3 .agents\\skills\\verify-wznowienie-wyceny-efenix\\scripts\\sprawdz_wznowienie_wyceny.py
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import NamedTuple

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[2]
MODEL = SKILL / "model"
SPEC = "WznowienieWyceny.tla"
TOOLS = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"

PASSES, VIOLATES = "przechodzi", "narusza"
VERDICT = "WZNOWIENIE WYCENY"
DRIFT = f"{VERDICT}: ROZJAZD MODELU Z KODEM"
# Obietnice, każda z wariantem ``…PozaZnanymi`` i stałą ``Wybaczone…`` w modelu, i ich zdanie dla czytelnika.
PROMISES = {
    "NieCzysciWycenyTaty": "narzędzie ładuje Wycenę Emmetta do zlecenia, które ma już ilości, i czyści je.",
    "ZmianaTatyZostaje": "narzędzie wpisuje ilość do zlecenia z wyceną, które tata sam zmienił (także dopisuje z powrotem ilość, którą usunął).",
    "ZnacznikTylkoNaWycenionym": "Znacznik efenix staje przy zleceniu, którego wycena w efenix różni się od pliku.",
    "BladTylkoPoZmianieTaty": "tata dostaje błąd „wycena już jest i się różni” przy zleceniu, którego sam nie zmieniał.",
}
# Kod, który opisują akcje modelu (tabela w SKILL.md): rozjazd liczą tylko te definicje, nie całe pliki, bo
# ``efenix_pricing.py`` zmienia się często obok przebiegu zlecenia (Sprawdzanie, Odczyt danych, Logi).
DEFINITIONS = {
    "src/rozliczenia/efenix_pricing.py": ("save", "_mark", "_efenix_stops", "_priced", "_outcome", "_after_emmett", "_entered"),
    "src/rozliczenia/efenix_emmett_trace.py": ("EmmettTrace", "_replace", "_read_secret", "_read", "_is_entry"),
    "src/rozliczenia/efenix_positions.py": ("as_left_after_emmett", "to_enter", "priced_differently", "same_amount", "emmett_conflicts"),
    # Okno efenix: kiedy efenix zapisał Wycenę Emmetta i ilość, a kiedy okno zgłasza ``LoggedOut`` bez zapisu ilości.
    "src/rozliczenia/efenix_browser.py": ("load_emmett", "enter_quantity"),
}
# Dopobranie historii płytkiego klonu CI nie czeka do limitu czasu runnera.
FETCH_TIMEOUT_S = 300
_STATE = re.compile(r"^State \d+: ")
_STUTTERING = re.compile(r"^State \d+: Stuttering")
_VARIABLE = re.compile(r"^/\\ (\w+) = (.*)$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--config", action="append", help="Tylko ta konfiguracja (nazwa pliku .cfg bez rozszerzenia).")
    parser.add_argument("--strict", action="store_true", help="Znane znaleziska też kończą się kodem 1.")
    args = parser.parse_args(argv)

    tools = _tools()
    drift = _drift(tools, ROOT, (SKILL / "SKILL.md").read_text(encoding="utf-8"))
    if drift is not None and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"UWAGA: {drift}\n\n{DRIFT}")
        return 1
    expected = json.loads((MODEL / "oczekiwane.json").read_text(encoding="utf-8"))
    names = args.config or sorted(path.stem for path in MODEL.glob("*.cfg"))
    java = os.environ.get("TLC_JAVA") or tools._java()
    jar = Path(os.environ.get("TLC_JAR") or tools._tla_tools())

    all_known = frozenset(
        (finding["obietnica"], finding["przyczyna"]) for entry in expected.values() for finding in entry.get("znane", ())
    )
    new, gone, known, broken = [], [], [], []
    for name in names:
        findings = expected.get(name, {}).get("znane", [])
        print(f"\n== {name}: {_description(name)}")
        # TLC kończy na pierwszym kontrprzykładzie, więc każde znane znalezisko ma swój przebieg bez pozostałych
        # znanych (czy ono dalej jest), a konfiguracja jeden przebieg bez wszystkich znanych (czy nic poza nimi).
        # Wybaczenie dotyczy tylko obietnicy znaleziska i zdarzenia, przed którym zdarzyła się jego przyczyna.
        for finding in findings:
            promise, cause = finding["obietnica"], finding["przyczyna"]
            print(f"   znane znalezisko „{cause}”, {promise}: {finding['znalezisko']}")
            own = _run(java, jar, name, all_known - {(promise, cause)})
            print(f"   wynik: {_said(own)}, oczekiwany: {VIOLATES} {promise} po „{cause}”")
            if own is None:
                broken.append(name)
            elif own.violated is None:
                gone.append(name)
                print("   znalezisko zniknęło: opisz zmianę w SKILL.md i usuń je z model/oczekiwane.json.")
            elif own.violated != promise or cause not in own.causes:
                new.append(name)
                print(f"   to nie jest znane znalezisko: przebieg łamie {own.violated} po {sorted(own.causes)}.")
            else:
                known.append(name)
        if findings:
            print("   reszta przebiegów, bez wszystkich znanych znalezisk:")
        rest = _run(java, jar, name, all_known if findings else frozenset())
        print(f"   wynik: {_said(rest)}, oczekiwany: {PASSES}")
        if rest is None:
            broken.append(name)
        elif rest.violated is not None:
            new.append(name)

    if drift is not None:
        print(f"\nUWAGA: {drift}")
    print()
    if broken:
        print(f"{VERDICT}: BŁĄD MODELU ({len(broken)})")
        return 2
    if new or gone:
        parts = [f"NOWE NARUSZENIE ({len(new)})" if new else "", f"ZNALEZISKO ZNIKNĘŁO ({len(gone)})" if gone else ""]
        print(f"{VERDICT}: " + ", ".join(part for part in parts if part))
        return 1
    if known:
        print(f"{VERDICT} OK, ZNANE ZNALEZISKA: {len(known)}")
        return 1 if args.strict else 0
    print(f"{VERDICT} OK")
    return 0


def _tools() -> ModuleType:
    """``sprawdz_aktualizacje.py``: Java, ``tla2tools.jar``, TLC we własnym katalogu i ``git``."""

    spec = importlib.util.spec_from_file_location("sprawdz_aktualizacje", TOOLS)
    if spec is None or spec.loader is None:
        sys.exit(f"BŁĄD: nie da się wczytać {TOOLS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _drift(tools: ModuleType, root: Path, skill_md: str) -> str | None:
    """Definicje z ``DEFINITIONS`` inne niż w commicie synchronizacji z ``SKILL.md`` (albo których nie ma); ``None``, gdy
    żadna. Płytki klon bez tego commitu (CI) najpierw dopobiera historię."""

    sync = re.search(r"Sync commit: `([0-9a-f]{7,40})`", skill_md)
    if sync is None:
        return "SKILL.md nie ma commitu synchronizacji."
    commit = f"{sync.group(1)}^{{commit}}"
    if tools._git(root, "cat-file", "-e", commit) is None:
        tools._git(root, "fetch", "--quiet", "--unshallow", "origin", timeout_s=FETCH_TIMEOUT_S)
    if tools._git(root, "cat-file", "-e", commit) is None:
        return f"commitu synchronizacji {sync.group(1)} nie ma w tej historii (git fetch --unshallow); porównaj kod ręcznie."
    moved = []
    for path, names in DEFINITIONS.items():
        then = tools._git(root, "show", f"{sync.group(1)}:{path}")
        now = (root / path).read_text(encoding="utf-8") if (root / path).is_file() else None
        moved += [f"{path} {name}" for name in names if (found := _definition(now, name)) is None or found != _definition(then, name)]
    if not moved:
        return None
    return f"kod opisany modelem zmienił się od {sync.group(1)}: {', '.join(moved)}. Sprawdź, czy model dalej go opisuje."


def _definition(source: str | None, name: str) -> str | None:
    """Pierwsza definicja ``name`` w ``source`` (funkcja, także zagnieżdżona, klasa albo przypisanie) bez położenia."""

    if source is None:
        return None
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return ast.dump(node)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return ast.dump(node)
    return None


class Verdict(NamedTuple):
    """Werdykt TLC: naruszona obietnica (``None``, gdy przechodzi) i przyczyny znanych znalezisk przed jej zdarzeniem."""

    violated: str | None
    causes: frozenset[str] = frozenset()


def _said(verdict: Verdict | None) -> str:
    if verdict is None:
        return "błąd modelu"
    return PASSES if verdict.violated is None else f"{VIOLATES} {verdict.violated}"


# Zmienna historii każdej obietnicy: zbiór z jednym zbiorem śladów w chwili zdarzenia, które ją łamie.
_EVENTS = {
    "NieCzysciWycenyTaty": "czysciTate",
    "ZmianaTatyZostaje": "nadpisujeTate",
    "ZnacznikTylkoNaWycenionym": "zlyZnacznik",
    "BladTylkoPoZmianieTaty": "bladBezPowodu",
}


def _run(java: str, jar: Path, name: str, forgiven: frozenset[tuple[str, str]]) -> Verdict | None:
    """Werdykt TLC dla konfiguracji ``name``, z opowiedzianym kontrprzykładem; ``None`` przy błędzie modelu.

    ``forgiven`` to pary (obietnica, przyczyna) znanych znalezisk z ``model/oczekiwane.json``; gdy są, przebieg
    sprawdza warianty ``…PozaZnanymi`` obietnic, a ``Wybaczone<obietnica>`` każdej to przyczyny jej znalezisk.
    """

    config = (MODEL / f"{name}.cfg").read_text(encoding="utf-8")
    if forgiven:
        for promise in PROMISES:
            config = re.sub(rf" {promise}\b", f" {promise}PozaZnanymi", config)
            tags = ", ".join(f'"{cause}"' for forgiven_promise, cause in sorted(forgiven) if forgiven_promise == promise)
            config = config.replace(f"Wybaczone{promise} = {{}}", f"Wybaczone{promise} = {{{tags}}}")
    output: str = _tools()._tlc(java, jar, MODEL / SPEC, name, config)
    if "No error has been found" in output:
        return Verdict(None)
    found = re.search(r"Invariant (\w+) is violated", output)
    if found is None:
        print("   BŁĄD MODELU: TLC nie dał werdyktu.\n" + output)
        return None
    promise = found.group(1).removesuffix("PozaZnanymi")
    trace = _trace(output)
    if promise not in PROMISES:
        print(f"   BŁĄD MODELU: naruszony {promise}, czyli model wyszedł poza swoje wartości.")
        return None
    print(f"   naruszone {promise}: {PROMISES[promise]}")
    _tell(trace)
    return Verdict(promise, frozenset(re.findall(r'"([\w-]+)"', trace[-1].get(_EVENTS[promise], ""))))


def _trace(output: str) -> list[dict[str, str]]:
    """Stany kontrprzykładu; wartość na kilku liniach skleja w jedną."""

    states: list[dict[str, str]] = []
    variable = ""
    for line in output.splitlines():
        if _STUTTERING.match(line):
            states.append(states[-1] | {"_akcja": "(dalej nic sie nie dzieje)"})
            variable = ""
        elif _STATE.match(line):
            action = re.search(r"<(\w+)", line)
            states.append({"_akcja": action.group(1) if action else "Init"})
            variable = ""
        elif states and (found := _VARIABLE.match(line.strip())):
            variable = found.group(1)
            states[-1][variable] = found.group(2).strip('"')
        elif states and variable and line.startswith(" "):
            states[-1][variable] += " " + line.strip()
        else:
            variable = ""
    return states


# Akcja modelu i krok kodu, który opisuje (tabela w SKILL.md), w słowach kontrprzykładu.
_STEPS = {
    "Start": "tata uruchamia Wycenę w efenix (EmmettTrace czyta ślad z dysku)",
    "Otworz": "okno otwiera zlecenie {z} i decyduje (_outcome)",
    "ZaladujEmmetta": "okno klika „Załaduj do zlecenia” w zleceniu {z}: efenix ma Wycenę Emmetta (load_emmett)",
    "OdczytPoEmmetcie": "okno czyta stronę zlecenia {z} po Emmetcie, trace.loaded zapisuje „Emmett załadowany”",
    "BrakPozycji": "strona zlecenia {z} po Emmetcie nie ma pozycji z ilością w pliku: błąd zlecenia przed trace.loaded",
    "Zapowiedz": "trace.entering zapisuje z wyprzedzeniem pozycję, którą okno zaraz wpisze w zleceniu {z} (_entered)",
    "Wpisz": "okno wpisuje ilość z pliku w zleceniu {z}, efenix ją zapisuje (enter_quantity)",
    "Odmowa": "efenix nie zapisał ilości w zleceniu {z} (LoggedOut), trace.not_entered wycofuje pozycję, Zatrzymanie",
    "Potwierdz": "efenix odpowiada kwotą w zleceniu {z}",
    "KoniecZlecenia": "zlecenie {z} ma wynik, potem trace.finished (_priced)",
    "Zatrzymanie": "okno efenix się nie dokończyło działania: Zatrzymanie (StopError) w zleceniu {z}",
    "Znaczniki": "Znaczniki efenix przy gotowych zleceniach (_mark), koniec Uruchomienia",
    "Zgasniecie": "Centrum gaśnie w zleceniu {z} (brak prądu, zabity proces)",
    "Tata": "tata sam zmienia ilość w efenix",
}


def _tell(trace: list[dict[str, str]]) -> None:
    for number, (before, state) in enumerate(itertools.pairwise(trace), start=1):
        step = _STEPS.get(state["_akcja"], state["_akcja"]).format(z=before.get("zlecenie", "?"))
        print(f"   {number}. {step}: efenix {_brief(state['efenix'])}, ślad na dysku {_entries(_brief(state['naDysku']))}")


def _brief(value: str) -> str:
    return " ".join(value.split())


# Wpis śladu modelu, np. ``[stan |-> "zaladowany", wpisuje |-> {"B"}]``, opowiedziany jako ``zaladowany {B}``.
_ENTRY = re.compile(r'\[stan \|-> "(\w+)", wpisuje \|-> \{([^}]*)\}\]')


def _entries(value: str) -> str:
    def told(entry: re.Match[str]) -> str:
        positions = entry.group(2).replace('"', "")
        return entry.group(1) + (f" {{{positions}}}" if positions else "")

    return _ENTRY.sub(told, value)


def _description(name: str) -> str:
    first = (MODEL / f"{name}.cfg").read_text(encoding="utf-8").splitlines()[0]
    return first.removeprefix("\\*").strip()


if __name__ == "__main__":
    raise SystemExit(main())
