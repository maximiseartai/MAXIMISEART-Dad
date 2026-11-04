"""Sprawdza model TLA+ Kolejki Skrzynki Zgłoszeń przy każdej kolejności awarii i przeplotów (TLC).

Uruchamia TLC na każdej konfiguracji z ``model/*.cfg``, porównuje wynik z ``model/oczekiwane.json`` i opowiada każdy
kontrprzykład krokami kodu. Javę i ``tla2tools.jar`` bierze z narzędzi skilla ``verify-aktualizacja-narzedzia``
(``sprawdz_aktualizacje.py``: przypięte ``jdk4py`` i jar w jego katalogu podręcznym), a zmienne ``TLC_JAVA`` i
``TLC_JAR`` je zastępują: kopia checkoutu mutacji nie ma ignorowanego katalogu podręcznego. Na końcu ostrzega, gdy
pokryty kod zmienił się od commitu synchronizacji z ``SKILL.md``: pliki z tabeli pokrycia w całości, a z ``DEFINITIONS``
tylko nazwane definicje. W CI (``GITHUB_ACTIONS=true``) rozjazd kończy się od razu linią
``MODEL KOLEJKI: ROZJAZD MODELU Z KODEM`` i kodem 1, bez TLC.

    .venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_model_kolejki.py
    py -3 .agents\\skills\\verify-kolejka-skrzynki\\scripts\\sprawdz_model_kolejki.py
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
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
SPEC = "KolejkaSkrzynki.tla"
TOOLS = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"

PASSES, VIOLATES = "przechodzi", "narusza"
VERDICT = "MODEL KOLEJKI"
DRIFT = f"{VERDICT}: ROZJAZD MODELU Z KODEM"
LIVENESS = "Zbieganie"
# Obietnice, każda z wariantem ``…PozaZnanymi`` i stałą ``Wybaczone…`` w modelu, i ich zdanie dla czytelnika.
PROMISES = {
    "JednoIssue": "okres, problem Zgłoszenia albo Uwaga taty ma drugie issue.",
    "DokladnieRaz": "plik kolejki zniknął albo ma znacznik, a Skrzynka nie ma którejś jego części, albo ma część dwa razy.",
    "CzesciWKolejnosci": "część k stoi w issue przed częścią k-1 tej samej wysyłki.",
    LIVENESS: "awarie się skończyły, a plik wysyłki bez znacznika zostaje w kolejce.",
}
# Kod, na którym stoją akcje Start, Zamknij i KoniecProcesu (stare i nowe Centrum naraz), w plikach, które Centrum
# zmienia często: rozjazd liczą tylko te definicje, a nie cały plik, jak tabela pokrycia w ``SKILL.md``.
DEFINITIONS = {
    "src/rozliczenia/centrum/app.py": ("lifespan",),
    "src/rozliczenia/centrum/launcher.py": ("listen_locally", "_listen_when_released"),
    "src/rozliczenia/centrum/server.py": ("_GRACEFUL_SHUTDOWN_S", "serve", "_Server"),
}
_STATE = re.compile(r"^State \d+: ")
_STUTTERING = re.compile(r"^State \d+: Stuttering")
_BACK = re.compile(r"^Back to state (\d+): ")
_VARIABLE = re.compile(r"^/\\ (\w+) = (.*)$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--config", action="append", help="Tylko ta konfiguracja (nazwa pliku .cfg bez rozszerzenia).")
    parser.add_argument("--strict", action="store_true", help="Znane znaleziska też kończą się kodem 1.")
    args = parser.parse_args(argv)

    tools = _tools()
    skill_md = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    drift = " ".join(found for found in (tools._drift(ROOT, skill_md), _moved_definitions(tools, ROOT, skill_md)) if found) or None
    if drift is not None and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"UWAGA: {drift}\n\n{DRIFT}")
        return 1
    expected = json.loads((MODEL / "oczekiwane.json").read_text(encoding="utf-8"))
    names = args.config or sorted(path.stem for path in MODEL.glob("*.cfg"))
    java = os.environ.get("TLC_JAVA") or tools._java()
    jar = Path(os.environ.get("TLC_JAR") or tools._tla_tools())

    all_known = frozenset((entry["obietnica"], entry["przyczyna"]) for entry in expected.values() if "przyczyna" in entry)
    new, gone, known, broken = [], [], [], []
    for name in names:
        want = expected.get(name, {})
        print(f"\n== {name}: {_description(name)}")
        if want.get("wynik") != VIOLATES:
            verdict = _run(java, jar, name, frozenset())
            print(f"   wynik: {_said(verdict)}, oczekiwany: {PASSES}")
            if verdict is None:
                broken.append(name)
            elif verdict.violated is not None:
                new.append(name)
            continue
        # TLC kończy na pierwszym kontrprzykładzie, więc znane znalezisko ma dwa przebiegi: bez pozostałych
        # znanych (czy ono dalej jest) i bez wszystkich znanych (czy nic poza nim). Wybaczenie dotyczy tylko
        # obietnicy znaleziska i przebiegu, w którym zdarzyła się jego przyczyna (``slady``).
        promise, cause = want["obietnica"], want["przyczyna"]
        print(f"   znane znalezisko „{cause}”, {promise}: {want['znalezisko']}")
        own = _run(java, jar, name, all_known - {(promise, cause)})
        print(f"   wynik: {_said(own)}, oczekiwany: {VIOLATES} {promise} po „{cause}”")
        if own is None:
            broken.append(name)
            continue
        if own.violated is None:
            gone.append(name)
            print("   znalezisko zniknęło: opisz zmianę w SKILL.md i zmień „wynik” w model/oczekiwane.json.")
        elif own.violated != promise or cause not in own.causes:
            new.append(name)
            print(f"   to nie jest znane znalezisko: przebieg łamie {own.violated} po {sorted(own.causes)}.")
            continue
        print("   reszta przebiegów, bez wszystkich znanych znalezisk:")
        rest = _run(java, jar, name, all_known)
        print(f"   wynik: {_said(rest)}, oczekiwany: {PASSES}")
        if rest is None:
            broken.append(name)
        elif rest.violated is not None:
            new.append(name)
        elif own.violated is not None:
            known.append(name)

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
    """``sprawdz_aktualizacje.py``: Java, ``tla2tools.jar`` i rozjazd pokrytego kodu z commitem synchronizacji."""

    spec = importlib.util.spec_from_file_location("sprawdz_aktualizacje", TOOLS)
    if spec is None or spec.loader is None:
        sys.exit(f"BŁĄD: nie da się wczytać {TOOLS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _moved_definitions(tools: ModuleType, root: Path, skill_md: str) -> str | None:
    """Definicje z ``DEFINITIONS`` inne niż w commicie synchronizacji (albo których nie ma); ``None``, gdy żadna."""

    sync = re.search(r"Sync commit: `([0-9a-f]{7,40})`", skill_md)
    if sync is None:
        return None  # brak commitu zgłasza już _drift
    moved = []
    for path, names in DEFINITIONS.items():
        then = tools._git(root, "show", f"{sync.group(1)}:{path}")
        now = (root / path).read_text(encoding="utf-8") if (root / path).is_file() else None
        moved += [
            f"{path} {name}"
            for name in names
            if (found := _definition(now, name)) is None or found != _definition(then, name)
        ]
    if not moved:
        return None
    return f"kod procesów Centrum zmienił się od {sync.group(1)}: {', '.join(moved)}. Sprawdź Start, Zamknij i KoniecProcesu."


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
    """Werdykt TLC: naruszona obietnica (``None``, gdy przechodzi) i przyczyny w ``slady`` końca kontrprzykładu."""

    violated: str | None
    causes: frozenset[str] = frozenset()


def _said(verdict: Verdict | None) -> str:
    if verdict is None:
        return "błąd modelu"
    return PASSES if verdict.violated is None else f"{VIOLATES} {verdict.violated}"


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
    output = _tlc(java, jar, name, config)
    if "No error has been found" in output:
        return Verdict(None)
    violated = _violated(output)
    if violated is None:
        print("   BŁĄD MODELU: TLC nie dał werdyktu.\n" + output)
        return None
    promise = violated.removesuffix("PozaZnanymi")
    if promise in PROMISES:
        print(f"   naruszone {promise}: {PROMISES[promise]}")
    trace = _trace(output)
    _tell(trace)
    if violated == "TypeOK":
        print("   BŁĄD MODELU: naruszony TypeOK, czyli model wyszedł poza swoje wartości.")
        return None
    return Verdict(promise, frozenset(re.findall(r'"(\w+)"', trace[-1].get("slady", ""))))


def _tlc(java: str, jar: Path, name: str, config: str) -> str:
    """Wyjście TLC dla specyfikacji modelu z konfiguracją ``config`` (treść pliku ``name.cfg``), jak w ``_tools``."""

    output: str = _tools()._tlc(java, jar, MODEL / SPEC, name, config)
    return output


def _violated(output: str) -> str | None:
    """Naruszony niezmiennik albo ``Zbieganie``, gdy TLC znalazł przebieg bez końca, w którym kolejka nie zbiega."""

    if "Temporal properties were violated" in output:
        return LIVENESS
    found = re.search(r"Invariant (\w+) is violated", output)
    return found.group(1) if found else None


def _trace(output: str) -> list[dict[str, str]]:
    """Stany kontrprzykładu; wartość na kilku liniach (długa lista issue) skleja w jedną.

    Przebieg bez końca kończy się stanem, którego ``krok`` mówi, co się powtarza.
    """

    states: list[dict[str, str]] = []
    variable = ""
    for line in output.splitlines():
        if _STUTTERING.match(line):
            states.append(states[-1] | {"krok": "(dalej nic sie nie dzieje)"})
            variable = ""
        elif back := _BACK.match(line):
            again = int(back.group(1)) - 1
            states.append(states[-1] | {"krok": f"(stad znow krok {again} i tak bez konca)"})
            variable = ""
        elif _STATE.match(line):
            states.append({})
            variable = ""
        elif states and (found := _VARIABLE.match(line.strip())):
            variable = found.group(1)
            states[-1][variable] = found.group(2).strip('"')
        elif states and variable and line.startswith(" "):
            states[-1][variable] += " " + line.strip()
        else:
            variable = ""
    return states


def _tell(trace: list[dict[str, str]]) -> None:
    for number, state in enumerate(trace[1:], start=1):
        print(f"   {number}. {state['krok']}")
    last = trace[-1]
    print(f"   na koniec: pliki kolejki {last['plik']}, Skrzynka {' '.join(last['issues'].split())}")


def _description(name: str) -> str:
    first = (MODEL / f"{name}.cfg").read_text(encoding="utf-8").splitlines()[0]
    return first.removeprefix("\\*").strip()


if __name__ == "__main__":
    raise SystemExit(main())
