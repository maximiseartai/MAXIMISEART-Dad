"""Jedna droga sprawdzenia modelu TLA+ skilla ``verify-*`` w TLC: konfiguracje, werdykt, znane znaleziska i rozjazd.

Skrypt modelu skilla podaje tylko to, co jest jego: ``Model`` z obietnicami (zdanie dla czytelnika i zmienna historii
z przyczynami znanych znalezisk) i opowieść kontrprzykładu krokami kodu. Resztę robi ``main``:

- Konfiguracje leżą w ``model/konfiguracje.json`` skilla (nazwa → ``opis``, ``stale``, opcjonalnie ``znane``), a ``.cfg``
  dla TLC powstaje z nich (``cfg``): ``INVARIANTS`` to ``TypeOK`` i każda obietnica, ``PROPERTIES`` obietnica czasowa,
  więc żadna konfiguracja nie pomija obietnicy. Sprawdzenie biegnie po konfiguracjach z tego pliku, nie po plikach.
- Rozjazd modelu z kodem (``tools/lib/rozjazd_modelu.py``) sprawdzenie tylko ostrzega linią ``UWAGA:`` nad werdyktem; w CI
  krok skilla z rozjazdem nie biegnie, bo kończy go porażką wykonanie zadania (``tools/ci/wykonaj_zadanie.py``).
- Javę i ``tla2tools.jar`` daje ``tools/lib/narzedzia_tlc.py``, a zmienne ``TLC_JAVA`` i ``TLC_JAR`` je zastępują, bo
  kopia checkoutu mutacji nie ma ignorowanego katalogu podręcznego (``narzedzia_dla_kopii``).
- Liveness TLC sprawdza raz, na pełnym grafie stanów (``-lncheck final``): sprawdzenie pośrednie co minutę BFS nie
  zmienia werdyktu modelu, który przechodzi, a na dużej przestrzeni stanów przechodzi drugi raz dużą część grafu. W
  kopii mutacji (``TLC_MUTACJA``) TLC sprawdza liveness także w trakcie, bo mutant, który łamie obietnicę czasową,
  wychodzi wtedy po pierwszym sprawdzeniu, a nie po całym BFS.
- Znane znalezisko wybacza tylko w swojej konfiguracji, tylko swoją obietnicę i tylko przebieg, w którym zdarzyła się
  jego przyczyna. TLC kończy na pierwszym kontrprzykładzie, więc każde znane znalezisko ma swój przebieg bez pozostałych
  znanych tej konfiguracji (czy dalej jest), a konfiguracja jeden przebieg bez wszystkich swoich znanych (czy nic poza
  nimi). Wybaczony przebieg sprawdza warianty ``…PozaZnanymi`` obietnic, a stała ``Wybaczone<obietnica>`` każdej to
  przyczyny jej znalezisk.
- Werdykt to ostatnia linia: ``<werdykt> OK`` albo ``<werdykt> OK, ZNANE ZNALEZISKA: n`` (kod 0, z ``--strict`` 1),
  ``NOWE NARUSZENIE`` i ``ZNALEZISKO ZNIKNĘŁO`` (kod 1), ``BŁĄD MODELU`` (kod 2: TLC bez werdyktu, niezmiennik
  spoza obietnic, na przykład ``TypeOK``, albo konfiguracje w innej postaci) albo ``ZAWIESZENIE TLC`` (kod 2).
- Przebieg TLC bez wyniku w swoim limicie (``LIMIT_MUTANTA_S`` w kopii mutacji, ``LIMIT_SPRAWDZENIA_S`` poza nią) to
  zawieszenie: ``jcmd`` obok Javy zapisuje zrzut wątków JVM tego przebiegu, po ``ZRZUT_S`` drzewo TLC ginie, a
  sprawdzenie kończy się od razu werdyktem ``ZAWIESZENIE TLC`` ze zrzutem, zamiast czekać na limit polecenia mutacji
  albo zadania CI (zawieszenia w runach 42335147260 i 42393988844, #1040).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from typing import NamedTuple

import narzedzia_tlc
import potomne
import rozjazd_modelu

__all__ = [
    "JAR",
    "JAVA",
    "KONFIGURACJE",
    "LIMIT_MUTANTA_S",
    "LIMIT_SPRAWDZENIA_S",
    "MUTACJA",
    "NARUSZA",
    "PRZECHODZI",
    "ZAWIESZENIE",
    "ZRZUT_S",
    "Konfiguracja",
    "Model",
    "Obietnica",
    "Stan",
    "Werdykt",
    "Zawieszenie",
    "Znalezisko",
    "akcje_next",
    "cfg",
    "konfiguracje",
    "main",
    "narzedzia_dla_kopii",
    "slad",
    "sprawdz",
    "tlc",
    "werdykt",
]

PRZECHODZI, NARUSZA = "przechodzi", "narusza"
KONFIGURACJE = "model/konfiguracje.json"
JAVA, JAR, MUTACJA = "TLC_JAVA", "TLC_JAR", "TLC_MUTACJA"
ZAWIESZENIE = "ZAWIESZENIE TLC"
# Limit jednego przebiegu TLC w kopii mutacji. Najdłuższe polecenie skryptu mutacji modelu w CI, całe, z kilkoma
# przebiegami TLC, trwało 184 s (Mutation checks na windows-latest w nocach runów 43183893292, 43392201527 i
# 43572533066, 12–14.11.2026), więc 300 s go nie skraca, a razem z ``ZRZUT_S`` mieści się w limicie polecenia mutacji
# silnika (600 s, ``silnik_mutacji.TIMEOUT``), po którym zawieszony mutant dawał PRZEKROCZONY CZAS bez zrzutu.
LIMIT_MUTANTA_S = 300.0
# Limit jednego przebiegu TLC pełnego sprawdzenia modelu. Najdłuższy cały skrypt sprawdzenia modelu w części zadania
# CI, ze wszystkimi konfiguracjami i przebiegami, trwał 553 s (run 43183893292, windows-latest), a 1200 s to ponad dwa razy tyle.
LIMIT_SPRAWDZENIA_S = 1200.0
# Czas na zrzut wątków JVM po limicie przebiegu: ``jcmd -l`` i ``jcmd <pid> Thread.print`` mają po połowie, a po nim
# drzewo TLC ginie, więc zrzut, który sam się zawiesi, nie przedłuża przebiegu.
ZRZUT_S = 30.0
_POZA_ZNANYMI = "PozaZnanymi"
_STATE = re.compile(r"^State \d+: ")
_STUTTERING = re.compile(r"^State \d+: Stuttering")
_BACK = re.compile(r"^Back to state (\d+): ")
_VARIABLE = re.compile(r"^/\\ (\w+) = (.*)\r?$")
_CAUSE = re.compile(r'"([\w-]+)"')


@dataclass(frozen=True)
class Obietnica:
    """Obietnica modelu: ``zdanie`` dla czytelnika i ``zdarzenia``, zmienna historii, której wartość w ostatnim stanie
    kontrprzykładu niesie przyczyny znanych znalezisk; bez niej (``None``) obietnica nie ma znanych znalezisk ani stałej
    ``Wybaczone…``. ``czasowa`` to właściwość czasowa (``PROPERTIES``), a nie niezmiennik."""

    zdanie: str
    zdarzenia: str | None = "slady"
    czasowa: bool = False


class Stan(NamedTuple):
    """Stan kontrprzykładu: akcja, która do niego prowadzi (``Init`` dla początkowego), i wartości zmiennych.

    Przebieg bez końca kończy się stanem z wartościami poprzedniego i ``petla``, słowami tego, co się powtarza."""

    akcja: str
    zmienne: dict[str, str]
    petla: str | None = None


class Werdykt(NamedTuple):
    """Werdykt TLC: naruszona obietnica (``None``, gdy przechodzi) i przyczyny w jej zmiennej historii."""

    naruszona: str | None
    przyczyny: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Znalezisko:
    """Znane znalezisko konfiguracji: obietnica, którą łamie, i przyczyna, po której wolno jej to zrobić."""

    obietnica: str
    przyczyna: str
    opis: str


class Zawieszenie(Exception):
    """Przebieg TLC bez wyniku w ``limit_s``: drzewo TLC już nie żyje, ``zrzut`` to zrzut wątków JVM albo linia, czemu go
    nie ma, a ``wyjscie`` to wyjście TLC wypisane do limitu."""

    def __init__(self, limit_s: float, zrzut: str, wyjscie: str) -> None:
        super().__init__(f"przebieg TLC bez wyniku po {limit_s:g} s")
        self.limit_s, self.zrzut, self.wyjscie = limit_s, zrzut, wyjscie


@dataclass(frozen=True)
class Konfiguracja:
    nazwa: str
    opis: str
    stale: Mapping[str, int | bool | str]
    znane: tuple[Znalezisko, ...] = ()


@dataclass(frozen=True)
class Model:
    """Model TLA+ skilla: ``werdykt`` (początek linii werdyktu), folder ``skill``, plik ``specyfikacja`` w ``model/``,
    ``obietnice`` w kolejności stałych ``Wybaczone…`` i ``opowiedz``, która drukuje kontrprzykład krokami kodu.

    ``akcje`` to akcje ``Next``, które opowieść zna z nazwy: gdy są, każda akcja ``Next`` musi być wśród nich i na
    odwrót, inaczej sprawdzenie kończy się błędem modelu przed TLC. ``zakleszczenie=False`` wyłącza ``CHECK_DEADLOCK``.
    """

    werdykt: str
    skill: Path
    specyfikacja: str
    obietnice: Mapping[str, Obietnica]
    opowiedz: Callable[[Sequence[Stan]], None]
    akcje: frozenset[str] | None = None
    zakleszczenie: bool = True

    def __post_init__(self) -> None:
        temporal = [name for name, promise in self.obietnice.items() if promise.czasowa]
        if len(temporal) > 1:
            raise ValueError(f"TLC nie mówi, którą właściwość czasową złamał, a model ma ich kilka: {', '.join(temporal)}")

    @property
    def czasowa(self) -> str | None:
        """Jedyna obietnica czasowa modelu albo ``None``."""

        return next((name for name, promise in self.obietnice.items() if promise.czasowa), None)


def main(model: Model, argv: list[str] | None = None, *, opis: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=opis)
    parser.add_argument("--config", action="append", help=f"Tylko ta konfiguracja (nazwa z {KONFIGURACJE}).")
    parser.add_argument("--strict", action="store_true", help="Znane znaleziska też kończą się kodem 1.")
    args = parser.parse_args(argv)

    root = model.skill.parents[2]
    drift = rozjazd_modelu.rozjazd(model.skill, root)
    try:
        chosen = _chosen(konfiguracje(model), args.config)
        _check_actions(model)
    except ValueError as error:
        print(f"BŁĄD MODELU: {error}\n\n{model.werdykt}: BŁĄD MODELU (1)")
        return 2
    cache = root / narzedzia_tlc.KATALOG
    java = os.environ.get(JAVA) or narzedzia_tlc.java(cache)
    jar = Path(os.environ.get(JAR) or narzedzia_tlc.jar(cache))
    spec = model.skill / "model" / model.specyfikacja
    early = bool(os.environ.get(MUTACJA))
    return sprawdz(
        model, chosen, lambda name, text: tlc(java, jar, spec, name, text, w_trakcie=early), strict=args.strict, uwaga=drift
    )


def sprawdz(
    model: Model,
    chosen: Sequence[Konfiguracja],
    run_tlc: Callable[[str, str], str],
    *,
    strict: bool = False,
    uwaga: str | None = None,
) -> int:
    """Werdykt modelu na konfiguracjach ``chosen``; ``run_tlc(nazwa, treść .cfg)`` to wyjście TLC. Zwraca kod wyjścia.

    Zawieszenie przebiegu (``Zawieszenie`` z ``run_tlc``) kończy sprawdzenie od razu, bo każdy następny przebieg mógłby
    czekać tyle samo."""

    try:
        return _sprawdz(model, chosen, run_tlc, strict=strict, uwaga=uwaga)
    except Zawieszenie as hang:
        tail = "\n".join(hang.wyjscie.splitlines()[-20:])
        print(f"   {ZAWIESZENIE}: {hang}, drzewo TLC zabite. Wyjście TLC do limitu (koniec):\n{tail}")
        print(f"   Zrzut wątków JVM tego przebiegu:\n{hang.zrzut}")
        if uwaga is not None:
            print(f"\nUWAGA: {uwaga}")
        print(f"\n{model.werdykt}: {ZAWIESZENIE} (1)")
        return 2


def _sprawdz(
    model: Model,
    chosen: Sequence[Konfiguracja],
    run_tlc: Callable[[str, str], str],
    *,
    strict: bool,
    uwaga: str | None,
) -> int:
    new: list[str] = []
    gone: list[str] = []
    known: list[str] = []
    broken: list[str] = []
    for config in chosen:
        print(f"\n== {config.nazwa}: {config.opis}")
        own_known = frozenset((finding.obietnica, finding.przyczyna) for finding in config.znane)

        def run(forgiven: frozenset[tuple[str, str]], config: Konfiguracja = config) -> Werdykt | None:
            return werdykt(model, run_tlc(config.nazwa, cfg(model, config, forgiven)))

        for finding in config.znane:
            pair = (finding.obietnica, finding.przyczyna)
            print(f"   znane znalezisko „{finding.przyczyna}”, {finding.obietnica}: {finding.opis}")
            own = run(own_known - {pair})
            print(f"   wynik: {_said(own)}, oczekiwany: {NARUSZA} {finding.obietnica} po „{finding.przyczyna}”")
            if own is None:
                broken.append(config.nazwa)
            elif own.naruszona is None:
                gone.append(config.nazwa)
                print(f"   znalezisko zniknęło: opisz zmianę w SKILL.md i usuń je z {KONFIGURACJE}.")
            elif own.naruszona != finding.obietnica or finding.przyczyna not in own.przyczyny:
                new.append(config.nazwa)
                print(f"   to nie jest znane znalezisko: przebieg łamie {own.naruszona} po {sorted(own.przyczyny)}.")
            else:
                known.append(config.nazwa)
        if config.znane:
            print("   reszta przebiegów, bez wszystkich znanych znalezisk tej konfiguracji:")
        rest = run(own_known)
        print(f"   wynik: {_said(rest)}, oczekiwany: {PRZECHODZI}")
        if rest is None:
            broken.append(config.nazwa)
        elif rest.naruszona is not None:
            new.append(config.nazwa)

    if uwaga is not None:
        print(f"\nUWAGA: {uwaga}")
    print()
    if broken:
        print(f"{model.werdykt}: BŁĄD MODELU ({len(broken)})")
        return 2
    if new or gone:
        parts = [f"NOWE NARUSZENIE ({len(new)})" if new else "", f"ZNALEZISKO ZNIKNĘŁO ({len(gone)})" if gone else ""]
        print(f"{model.werdykt}: " + ", ".join(part for part in parts if part))
        return 1
    if known:
        print(f"{model.werdykt} OK, ZNANE ZNALEZISKA: {len(known)}")
        return 1 if strict else 0
    print(f"{model.werdykt} OK")
    return 0


def _said(verdict: Werdykt | None) -> str:
    if verdict is None:
        return "błąd modelu"
    return PRZECHODZI if verdict.naruszona is None else f"{NARUSZA} {verdict.naruszona}"


def werdykt(model: Model, output: str) -> Werdykt | None:
    """Werdykt z wyjścia TLC, z opowiedzianym kontrprzykładem; ``None`` (z powodem na wyjściu) przy błędzie modelu."""

    if "No error has been found" in output:
        return Werdykt(None)
    if "Temporal properties were violated" in output:
        violated = model.czasowa
    else:
        found = re.search(r"Invariant (\w+) is violated", output)
        violated = found[1].removesuffix(_POZA_ZNANYMI) if found else None
    if violated is None:
        print("   BŁĄD MODELU: TLC nie dał werdyktu.\n" + output)
        return None
    states = slad(output)
    promise = model.obietnice.get(violated)
    if promise is None:
        print(f"   BŁĄD MODELU: naruszony {violated}, czyli model wyszedł poza swoje wartości.")
        model.opowiedz(states)
        return None
    print(f"   naruszone {violated}: {promise.zdanie}")
    model.opowiedz(states)
    events = states[-1].zmienne.get(promise.zdarzenia, "") if promise.zdarzenia is not None and states else ""
    return Werdykt(violated, frozenset(_CAUSE.findall(events)))


def slad(output: str) -> list[Stan]:
    """Stany kontrprzykładu z wyjścia TLC; wartość zmiennej na kilku liniach (długa lista) skleja w jedną."""

    states: list[Stan] = []
    variable = ""
    for line in output.splitlines():
        if _STUTTERING.match(line):
            states.append(Stan("Stuttering", dict(states[-1].zmienne), "(dalej nic się nie dzieje)"))
            variable = ""
        elif back := _BACK.match(line):
            again = int(back[1]) - 1
            states.append(Stan(_action(line), dict(states[-1].zmienne), f"(stąd znów krok {again} i tak bez końca)"))
            variable = ""
        elif _STATE.match(line):
            states.append(Stan(_action(line), {}))
            variable = ""
        elif states and (found := _VARIABLE.match(line.strip())):
            variable = found[1]
            states[-1].zmienne[variable] = found[2].strip('"')
        elif states and variable and line.startswith(" "):
            states[-1].zmienne[variable] += " " + line.strip()
        else:
            variable = ""
    return states


def _action(line: str) -> str:
    found = re.search(r"<(\w+)", line)
    return found[1] if found and found[1] != "Initial" else "Init"


def cfg(model: Model, config: Konfiguracja, forgiven: frozenset[tuple[str, str]]) -> str:
    """Treść ``.cfg`` konfiguracji; ``forgiven`` to pary (obietnica, przyczyna) wybaczonych znanych znalezisk."""

    def name(promise: str) -> str:
        return f"{promise}{_POZA_ZNANYMI}" if forgiven and model.obietnice[promise].zdarzenia is not None else promise

    invariants = [name(promise) for promise, said in model.obietnice.items() if not said.czasowa]
    lines = [f"\\* {config.opis}", "SPECIFICATION Spec", " ".join(["INVARIANTS TypeOK", *invariants])]
    if model.czasowa is not None:
        lines.append(f"PROPERTIES {name(model.czasowa)}")
    if not model.zakleszczenie:
        lines.append("CHECK_DEADLOCK FALSE")
    lines.append("CONSTANTS")
    lines += [f"    {constant} = {_tla(value)}" for constant, value in config.stale.items()]
    for promise, said in model.obietnice.items():
        if said.zdarzenia is not None:
            causes = ", ".join(f'"{cause}"' for owner, cause in sorted(forgiven) if owner == promise)
            lines.append(f"    Wybaczone{promise} = {{{causes}}}")
    return "\n".join(lines) + "\n"


def _tla(value: int | bool | str) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    return f'"{value}"'


def konfiguracje(model: Model) -> list[Konfiguracja]:
    """Konfiguracje z ``model/konfiguracje.json`` skilla w kolejności pliku; inna postać to ``ValueError``."""

    path = model.skill / KONFIGURACJE
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{KONFIGURACJE} nie da się odczytać ({error})") from error
    if not isinstance(loaded, dict) or not loaded:
        raise ValueError(f"{KONFIGURACJE} to nie jest niepusty obiekt nazwa → konfiguracja")
    return [_config(model, name, entry) for name, entry in loaded.items()]


def _config(model: Model, name: str, entry: object) -> Konfiguracja:
    where = f"{KONFIGURACJE}: {name}"
    if not isinstance(entry, dict) or not {"opis", "stale"} <= entry.keys() <= {"opis", "stale", "znane"}:
        raise ValueError(f"{where} ma mieć klucze „opis”, „stale” i opcjonalnie „znane”")
    said, constants, findings = entry["opis"], entry["stale"], entry.get("znane", [])
    if not isinstance(said, str) or not said or "\n" in said:
        raise ValueError(f"{where}: „opis” to jedna niepusta linia")
    if not isinstance(constants, dict) or not constants:
        raise ValueError(f"{where}: „stale” to niepusty obiekt stała → wartość")
    for constant, value in constants.items():
        if not isinstance(value, (bool, int, str)) or (isinstance(value, str) and ('"' in value or "\\" in value)):
            raise ValueError(f"{where}: stała {constant} ma {value!r}, a nie liczbę, TRUE/FALSE albo napis")
    if not isinstance(findings, list):
        raise ValueError(f"{where}: „znane” to lista znanych znalezisk")
    return Konfiguracja(name, said, constants, tuple(_finding(model, where, each) for each in findings))


def _finding(model: Model, where: str, entry: object) -> Znalezisko:
    keys = {"obietnica", "przyczyna", "znalezisko"}
    if not isinstance(entry, dict) or entry.keys() != keys or not all(isinstance(entry[key], str) and entry[key] for key in keys):
        raise ValueError(f"{where}: znane znalezisko to obiekt z niepustymi napisami „obietnica”, „przyczyna” i „znalezisko”")
    promise = model.obietnice.get(entry["obietnica"])
    if promise is None or promise.zdarzenia is None:
        raise ValueError(f"{where}: {entry['obietnica']} to nie obietnica modelu, która może mieć znane znaleziska")
    return Znalezisko(entry["obietnica"], entry["przyczyna"], entry["znalezisko"])


def _chosen(configs: list[Konfiguracja], names: list[str] | None) -> list[Konfiguracja]:
    if not names:
        return configs
    by_name = {config.nazwa: config for config in configs}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise ValueError(f"{KONFIGURACJE} nie ma konfiguracji {', '.join(unknown)}")
    return [by_name[name] for name in names]


def _check_actions(model: Model) -> None:
    if model.akcje is None:
        return
    actions = akcje_next((model.skill / "model" / model.specyfikacja).read_text(encoding="utf-8"))
    if actions != model.akcje:
        missing, extra = sorted(actions - model.akcje), sorted(model.akcje - actions)
        raise ValueError(
            f"opowieść kontrprzykładu nie zna akcji Next: {', '.join(missing) or '-'}, a zna akcje spoza Next: {', '.join(extra) or '-'}"
        )


def akcje_next(spec: str) -> frozenset[str]:
    found = re.search(r"^Next\s*==(.*?)(?=^\S|\Z)", spec, re.DOTALL | re.MULTILINE)
    if found is None:
        raise ValueError("specyfikacja nie ma definicji „Next ==”")
    body = re.sub(r"\(\*.*?\*\)|\\\*[^\n]*|\\[EA]\s[^:]*:", " ", found[1], flags=re.DOTALL)
    defined = set(re.findall(r"^(\w+)\s*(?:\([^)]*\))?\s*==", spec, re.MULTILINE))
    return frozenset(name for name in re.findall(r"\w+", body) if name in defined)


def tlc(
    java: str,
    jar: Path,
    spec: Path,
    name: str,
    text: str,
    *,
    w_trakcie: bool = False,
    limit_s: float | None = None,
    zrzut_s: float = ZRZUT_S,
) -> str:
    """Wyjście TLC dla specyfikacji ``spec`` z konfiguracją ``text`` (treść pliku ``name.cfg``).

    Liveness TLC sprawdza na pełnym grafie stanów, a z ``w_trakcie`` (kopia mutacji) także co minutę BFS na grafie,
    który już zna.

    TLC zapisuje ślady i stany obok specyfikacji, a moduły standardowe (``Naturals.tla``) rozpakowuje pod stałą nazwą
    do ``java.io.tmpdir`` i usuwa przy wyjściu, więc każdy przebieg ma własny katalog tymczasowy i w nim swój
    ``java.io.tmpdir``. Ze wspólnym przebiegi naraz (mutacje skilla) czytają moduł, który inny przebieg właśnie
    nadpisał albo usunął, i TLC kończy się błędem parsowania zamiast werdyktu.

    Przebieg bez wyniku po ``limit_s`` (domyślnie ``LIMIT_MUTANTA_S`` z ``w_trakcie``, inaczej ``LIMIT_SPRAWDZENIA_S``)
    dostaje zrzut wątków JVM, a po kolejnych ``zrzut_s`` drzewo TLC ginie i ``tlc`` rzuca ``Zawieszenie``.
    """

    limit = limit_s if limit_s is not None else LIMIT_MUTANTA_S if w_trakcie else LIMIT_SPRAWDZENIA_S
    with tempfile.TemporaryDirectory(prefix="tlc-") as work:
        shutil.copy2(spec, work)
        Path(work, f"{name}.cfg").write_text(text, encoding="utf-8")
        metadir = Path(work, "stany")
        done = threading.Event()
        dump: list[str] = []

        def watch() -> None:
            if not done.wait(limit):
                dump.append(_thread_dump(java, metadir, zrzut_s / 2))

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            result = _run_tlc(java, jar, spec, name, metadir, w_trakcie=w_trakcie, timeout=limit + zrzut_s)
        except potomne.TimeoutExpired as expired:
            watcher.join(zrzut_s)
            said = dump[0] if dump else f"ZRZUT WĄTKÓW: jcmd nie skończył w {zrzut_s:g} s"
            raise Zawieszenie(limit, said, "".join(expired.printed)) from None
        finally:
            done.set()
            watcher.join(zrzut_s)  # zrzut przebiegu, który skończył się po limicie, nie biegnie w usuniętym katalogu
    return result.stdout + result.stderr


def _run_tlc(
    java: str, jar: Path, spec: Path, name: str, metadir: Path, *, w_trakcie: bool, timeout: float
) -> subprocess.CompletedProcess[str]:
    work = metadir.parent
    return potomne.run(
        [
            java,
            "-XX:+UseParallelGC",
            f"-Djava.io.tmpdir={work}",
            "-cp",
            str(jar),
            "tlc2.TLC",
            "-workers",
            "auto",
            "-lncheck",
            "default" if w_trakcie else "final",
            "-metadir",
            str(metadir),
            "-config",
            f"{name}.cfg",
            spec.name,
        ],
        cwd=work,
        timeout=timeout,
    )


def _thread_dump(java: str, metadir: Path, each_s: float) -> str:
    """Zrzut wątków JVM przebiegu TLC z ``-metadir metadir`` przez ``jcmd`` obok ``java`` (jdk4py ma go na Windows,
    Linuksie i macOS); JVM przebiegu wskazuje ``jcmd -l`` po katalogu ``metadir``, którego nie ma żaden inny przebieg.

    Gdy zrzutu nie da się zrobić, zwraca jedną linię z przyczyną; każde polecenie ma limit ``each_s``.
    """

    jcmd = Path(java).with_name(f"jcmd{Path(java).suffix}")
    if not jcmd.is_file():
        return f"ZRZUT WĄTKÓW: brak {jcmd.name} obok {java}"
    try:
        listed = potomne.run([str(jcmd), "-l"], cwd=metadir.parent, timeout=each_s)
        pid = next((line.split()[0] for line in listed.stdout.splitlines() if str(metadir) in line), None)
        if pid is None:
            return f"ZRZUT WĄTKÓW: {jcmd.name} -l nie zna JVM przebiegu z -metadir {metadir}"
        dumped = potomne.run([str(jcmd), pid, "Thread.print"], cwd=metadir.parent, timeout=each_s)
    except potomne.TimeoutExpired:
        return f"ZRZUT WĄTKÓW: {jcmd.name} nie odpowiedział w {each_s:g} s"
    except OSError as error:
        return f"ZRZUT WĄTKÓW: {jcmd.name} nie ruszył ({error})"
    return dumped.stdout + dumped.stderr


def narzedzia_dla_kopii(root: Path) -> None:
    """Java i ``tla2tools.jar`` checkoutu ``root`` w ``TLC_JAVA`` i ``TLC_JAR`` dla poleceń, które biegną w kopiach
    checkoutu bez katalogu podręcznego (skrypty mutacji modelu), i ``TLC_MUTACJA``, z którym sprawdzenie w kopii
    sprawdza liveness w trakcie BFS; ustawionych zmiennych nie zmienia."""

    cache = root / narzedzia_tlc.KATALOG
    os.environ.setdefault(JAVA, narzedzia_tlc.java(cache))
    os.environ.setdefault(JAR, str(narzedzia_tlc.jar(cache)))
    os.environ.setdefault(MUTACJA, "1")
