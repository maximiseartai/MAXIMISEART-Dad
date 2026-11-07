"""Jedna droga sprawdzenia modelu TLA+ skilla ``verify-*`` w TLC: konfiguracje, werdykt, znane znaleziska i rozjazd.

Skrypt modelu skilla podaje tylko to, co jest jego: ``Model`` z obietnicami (zdanie dla czytelnika i zmienna historii
z przyczynami znanych znalezisk) i opowieść kontrprzykładu krokami kodu. Resztę robi ``main``:

- Konfiguracje leżą w ``model/konfiguracje.json`` skilla (nazwa → ``opis``, ``stale``, opcjonalnie ``znane``), a ``.cfg``
  dla TLC powstaje z nich (``cfg``): ``INVARIANTS`` to ``TypeOK`` i każda obietnica, ``PROPERTIES`` obietnica czasowa,
  więc żadna konfiguracja nie pomija obietnicy. Sprawdzenie biegnie po konfiguracjach z tego pliku, nie po plikach.
- Rozjazd modelu z kodem (``tools/lib/rozjazd_modelu.py``) rozstrzyga się przed TLC: w CI (``GITHUB_ACTIONS=true``)
  kończy sprawdzenie linią ``<werdykt>: ROZJAZD MODELU Z KODEM`` i kodem 1 (``porazka_w_ci``), a poza CI ostrzega na końcu.
- Javę i ``tla2tools.jar`` daje ``tools/lib/narzedzia_tlc.py``, a zmienne ``TLC_JAVA`` i ``TLC_JAR`` je zastępują, bo
  kopia checkoutu mutacji nie ma ignorowanego katalogu podręcznego (``narzedzia_dla_kopii``).
- Znane znalezisko wybacza tylko w swojej konfiguracji, tylko swoją obietnicę i tylko przebieg, w którym zdarzyła się
  jego przyczyna. TLC kończy na pierwszym kontrprzykładzie, więc każde znane znalezisko ma swój przebieg bez pozostałych
  znanych tej konfiguracji (czy dalej jest), a konfiguracja jeden przebieg bez wszystkich swoich znanych (czy nic poza
  nimi). Wybaczony przebieg sprawdza warianty ``…PozaZnanymi`` obietnic, a stała ``Wybaczone<obietnica>`` każdej to
  przyczyny jej znalezisk.
- Werdykt to ostatnia linia: ``<werdykt> OK`` albo ``<werdykt> OK, ZNANE ZNALEZISKA: n`` (kod 0, z ``--strict`` 1),
  ``NOWE NARUSZENIE`` i ``ZNALEZISKO ZNIKNĘŁO`` (kod 1) albo ``BŁĄD MODELU`` (kod 2: TLC bez werdyktu, niezmiennik
  spoza obietnic, na przykład ``TypeOK``, albo konfiguracje w innej postaci).
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
import tempfile
from typing import NamedTuple

import narzedzia_tlc
import potomne
import rozjazd_modelu

__all__ = [
    "JAR",
    "JAVA",
    "KONFIGURACJE",
    "NARUSZA",
    "PRZECHODZI",
    "Konfiguracja",
    "Model",
    "Obietnica",
    "Stan",
    "Werdykt",
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
JAVA, JAR = "TLC_JAVA", "TLC_JAR"
_POZA_ZNANYMI = "PozaZnanymi"
_STATE = re.compile(r"^State \d+: ")
_STUTTERING = re.compile(r"^State \d+: Stuttering")
_BACK = re.compile(r"^Back to state (\d+): ")
_VARIABLE = re.compile(r"^/\\ (\w+) = (.*)$")
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
    """Sprawdzenie modelu skilla z wiersza poleceń: ``--config`` (powtarzalne) i ``--strict``."""

    parser = argparse.ArgumentParser(description=opis)
    parser.add_argument("--config", action="append", help=f"Tylko ta konfiguracja (nazwa z {KONFIGURACJE}).")
    parser.add_argument("--strict", action="store_true", help="Znane znaleziska też kończą się kodem 1.")
    args = parser.parse_args(argv)

    root = model.skill.parents[2]
    drift = rozjazd_modelu.rozjazd(model.skill, root)
    if (failure := rozjazd_modelu.porazka_w_ci(drift, model.werdykt)) is not None:
        print(failure)
        return 1
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
    return sprawdz(model, chosen, lambda name, text: tlc(java, jar, spec, name, text), strict=args.strict, uwaga=drift)


def sprawdz(
    model: Model,
    chosen: Sequence[Konfiguracja],
    run_tlc: Callable[[str, str], str],
    *,
    strict: bool = False,
    uwaga: str | None = None,
) -> int:
    """Werdykt modelu na konfiguracjach ``chosen``; ``run_tlc(nazwa, treść .cfg)`` to wyjście TLC. Zwraca kod wyjścia."""

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
    """Nazwy akcji, które ``Next ==`` specyfikacji łączy przez ``\\/`` (także pod ``\\E … :``)."""

    found = re.search(r"^Next ==\n(.*?)(?:\n\s*\n|\Z)", spec, re.DOTALL | re.MULTILINE)
    if found is None:
        raise ValueError("specyfikacja nie ma definicji „Next ==” w osobnej linii")
    return frozenset(re.findall(r"\\/\s*(?:\\E[^:]*:\s*)?(\w+)", found[1]))


def tlc(java: str, jar: Path, spec: Path, name: str, text: str) -> str:
    """Wyjście TLC dla specyfikacji ``spec`` z konfiguracją ``text`` (treść pliku ``name.cfg``).

    TLC zapisuje ślady i stany obok specyfikacji, a moduły standardowe (``Naturals.tla``) rozpakowuje pod stałą nazwą
    do ``java.io.tmpdir`` i usuwa przy wyjściu, więc każdy przebieg ma własny katalog tymczasowy i w nim swój
    ``java.io.tmpdir``. Ze wspólnym przebiegi naraz (mutacje skilla) czytają moduł, który inny przebieg właśnie
    nadpisał albo usunął, i TLC kończy się błędem parsowania zamiast werdyktu.
    """

    with tempfile.TemporaryDirectory(prefix="tlc-") as work:
        shutil.copy2(spec, work)
        Path(work, f"{name}.cfg").write_text(text, encoding="utf-8")
        result = potomne.run(
            [
                java,
                "-XX:+UseParallelGC",
                f"-Djava.io.tmpdir={work}",
                "-cp",
                str(jar),
                "tlc2.TLC",
                "-workers",
                "auto",
                "-metadir",
                str(Path(work, "stany")),
                "-config",
                f"{name}.cfg",
                spec.name,
            ],
            cwd=Path(work),
        )
    return result.stdout + result.stderr


def narzedzia_dla_kopii(root: Path) -> None:
    """Java i ``tla2tools.jar`` checkoutu ``root`` w ``TLC_JAVA`` i ``TLC_JAR`` dla poleceń, które biegną w kopiach
    checkoutu bez katalogu podręcznego (skrypty mutacji modelu); ustawionych zmiennych nie zmienia."""

    cache = root / narzedzia_tlc.KATALOG
    os.environ.setdefault(JAVA, narzedzia_tlc.java(cache))
    os.environ.setdefault(JAR, str(narzedzia_tlc.jar(cache)))
