"""Sprawdza model TLA+ Aktualizacji narzędzia przy każdej kolejności awarii (TLC).

Uruchamia TLC na każdej konfiguracji z ``model/*.cfg``, porównuje wynik z
``model/oczekiwane.json`` i opowiada każdy kontrprzykład krokami kodu. Javy nie
trzeba mieć w systemie: przypięte ``jdk4py`` i ``tla2tools.jar`` trafiają raz do
``.verification/formal-aktualizacja`` (ignorowanego przez Gita); wersje i pobieranie
z ponowieniem ma ``tools/lib/narzedzia_tlc.py``. Na końcu
ostrzega, gdy kod z ``model/definicje.json`` zmienił się od Sync commit z
``SKILL.md`` (rozjazd rozstrzyga ``tools/lib/rozjazd_modelu.py``). Płytki klon
bez tego commitu (CI) najpierw dopobiera historię. W CI (``GITHUB_ACTIONS=true``)
rozjazd kończy się od razu linią ``AKTUALIZACJA: ROZJAZD MODELU Z KODEM`` i
kodem 1, bez TLC.

    .venv/bin/python .agents/skills/verify-aktualizacja-narzedzia/scripts/sprawdz_aktualizacje.py
    py -3 .agents\\skills\\verify-aktualizacja-narzedzia\\scripts\\sprawdz_aktualizacje.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from narzedzia_tlc import JDK4PY, TLA_SHA256, TLA_URL, TLA_WERSJA, ChwilowaAwaria, pobierz, z_ponowieniem
import rozjazd_modelu

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[2]
MODEL = SKILL / "model"
SPEC = "AktualizacjaNarzedzia.tla"
CACHE = ROOT / ".verification" / "formal-aktualizacja"

PASSES, VIOLATES = "przechodzi", "narusza"
DRIFT = "AKTUALIZACJA: ROZJAZD MODELU Z KODEM"
# Niezmienniki obietnicy, każdy z wariantem ``…PozaZnanymi`` w modelu, i ich zdanie dla czytelnika.
PROMISES = {
    "TataMaDzialajacaWersje": "tata zostaje bez wersji, która startuje, albo bez swojego pliku w config/.",
    "OpiekunCofaTylkoNieudana": "opiekun cofa nową wersję, która by wystartowała.",
    "OkienkoTylkoGdyNicNieDziala": "opiekun pokazuje okienko „nie wystartowało”, choć Centrum działa.",
    "TataNieZostajeBezOdpowiedzi": "nic nie działa, a tata nie dostaje okienka, tylko martwą kartę.",
    "KartaNieKlamie": "karta mówi „Narzędzie zaktualizowane”, choć nowa wersja nie działa.",
    "KartaNieStraszy": "karta nowej, działającej wersji mówi o porażce aktualizacji.",
}
_STATE = re.compile(r"^State \d+: ")
_STUTTERING = re.compile(r"^State \d+: Stuttering")
_BACK = re.compile(r"^Back to state (\d+): ")
_VARIABLE = re.compile(r"^/\\ (\w+) = (.*)$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None
    )
    parser.add_argument(
        "--config",
        action="append",
        help="Tylko ta konfiguracja (nazwa pliku .cfg bez rozszerzenia).",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Znane znaleziska też kończą się kodem 1."
    )
    args = parser.parse_args(argv)

    drift = rozjazd_modelu.rozjazd(SKILL, ROOT)
    if drift is not None and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"UWAGA: {drift}\n\n{DRIFT}")
        return 1
    expected = json.loads((MODEL / "oczekiwane.json").read_text(encoding="utf-8"))
    names = args.config or sorted(path.stem for path in MODEL.glob("*.cfg"))
    java, jar = _java(), _tla_tools()

    all_known = frozenset(
        entry["wybacz"] for entry in expected.values() if "wybacz" in entry
    )
    new, gone, known, broken = [], [], [], []
    for name in names:
        want = expected.get(name, {})
        print(f"\n== {name}: {_description(name)}")
        if want.get("wynik") != VIOLATES:
            verdict = _run(java, jar, name, frozenset())
            print(f"   wynik: {verdict}, oczekiwany: {PASSES}")
            if verdict is None:
                broken.append(name)
            elif verdict == VIOLATES:
                new.append(name)
            continue
        # TLC kończy na pierwszym kontrprzykładzie, więc każde znane znalezisko ma dwa przebiegi:
        # bez pozostałych znanych (czy ono dalej jest) i bez wszystkich znanych (czy nic poza nimi).
        finding = want["wybacz"]
        print(f"   znane znalezisko „{finding}”: {want['znalezisko']}")
        own = _run(java, jar, name, all_known - {finding})
        print(f"   wynik: {own}, oczekiwany: {VIOLATES}")
        if own is None:
            broken.append(name)
            continue
        if own == PASSES:
            gone.append(name)
            print(
                "   znalezisko zniknęło: opisz zmianę w SKILL.md i zmień „wynik” w model/oczekiwane.json."
            )
        print("   reszta przebiegów, bez wszystkich znanych znalezisk:")
        rest = _run(java, jar, name, all_known)
        print(f"   wynik: {rest}, oczekiwany: {PASSES}")
        if rest is None:
            broken.append(name)
        elif rest == VIOLATES:
            new.append(name)
        elif own == VIOLATES:
            known.append(name)

    if drift is not None:
        print(f"\nUWAGA: {drift}")
    print()
    if broken:
        print(f"AKTUALIZACJA: BŁĄD MODELU ({len(broken)})")
        return 2
    if new or gone:
        parts = [
            f"NOWE NARUSZENIE ({len(new)})" if new else "",
            f"ZNALEZISKO ZNIKNĘŁO ({len(gone)})" if gone else "",
        ]
        print("AKTUALIZACJA: " + ", ".join(part for part in parts if part))
        return 1
    if known:
        print(f"AKTUALIZACJA OK, ZNANE ZNALEZISKA: {len(known)}")
        return 1 if args.strict else 0
    print("AKTUALIZACJA OK")
    return 0


def _java() -> str:
    """Java z przypiętego ``jdk4py`` w katalogu podręcznym; instaluje je za pierwszym razem."""

    target = CACHE / "jdk"
    if not (target / "jdk4py").is_dir():
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--quiet",
        ]
        if (
            subprocess.run(
                [sys.executable, "-m", "pip", "--version"], capture_output=True, check=False
            ).returncode
            != 0
        ):
            uv = shutil.which("uv")
            if uv is None:
                sys.exit(
                    "BŁĄD: ten Python nie ma pip, a uv nie jest dostępne; nie da się zainstalować jdk4py."
                )
            command = [uv, "pip", "install", "--python", sys.executable, "--quiet"]

        def install() -> None:
            shutil.rmtree(target, ignore_errors=True)
            done = subprocess.run([*command, "--target", str(target), JDK4PY], check=False)
            if done.returncode != 0:
                raise ChwilowaAwaria(f"instalacja skończyła się kodem {done.returncode}")

        z_ponowieniem(JDK4PY, install)
    found = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys; sys.path.insert(0, {str(target)!r}); import jdk4py; print(jdk4py.JAVA)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return found.stdout.strip()


def _tla_tools() -> Path:
    """``tla2tools.jar`` w przypiętej wersji, sprawdzony sumą SHA-256."""

    jar = CACHE / f"tla2tools-{TLA_WERSJA}.jar"
    if not jar.is_file() or _sha256(jar) != TLA_SHA256:
        CACHE.mkdir(parents=True, exist_ok=True)
        partial = jar.with_suffix(".part")
        pobierz(TLA_URL, partial)
        if _sha256(partial) != TLA_SHA256:
            partial.unlink()
            sys.exit(f"BŁĄD: {TLA_URL} ma inną sumę SHA-256 niż przypięta.")
        os.replace(partial, jar)
    return jar


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(java: str, jar: Path, name: str, forgiven: frozenset[str]) -> str | None:
    """Werdykt TLC dla konfiguracji ``name``, z opowiedzianym kontrprzykładem; ``None`` przy błędzie modelu.

    ``forgiven`` to znane znaleziska z ``model/oczekiwane.json``; gdy są, przebieg
    sprawdza warianty ``…PozaZnanymi`` każdej obietnicy z ``PROMISES`` i
    ``PostepPozaZnanymi`` z ``Wybaczone`` równym im.
    """

    config = (MODEL / f"{name}.cfg").read_text(encoding="utf-8")
    if forgiven:
        tags = ", ".join(f'"{tag}"' for tag in sorted(forgiven))
        for promise in PROMISES:
            config = re.sub(rf" {promise}\b", f" {promise}PozaZnanymi", config)
        config = config.replace(" Postep\n", " PostepPozaZnanymi\n")
        config = config.replace("Wybaczone = {}", f"Wybaczone = {{{tags}}}")
    output = _tlc(java, jar, MODEL / SPEC, name, config)
    if "No error has been found" in output:
        return PASSES
    invariant = _violated(output)
    if invariant is None:
        print("   BŁĄD MODELU: TLC nie dał werdyktu.\n" + output)
        return None
    if invariant == _LIVENESS:
        print("   naruszony Postep: dziennik „Aktualizacja w toku” zostaje na zawsze.")
    elif (promise := invariant.removesuffix("PozaZnanymi")) in PROMISES:
        print(f"   naruszone {promise}: {PROMISES[promise]}")
    _tell(_trace(output))
    if invariant == "TypeOK":
        print(
            "   BŁĄD MODELU: naruszony TypeOK, czyli model wyszedł poza swoje wartości."
        )
        return None
    return VIOLATES


def _tlc(java: str, jar: Path, spec: Path, name: str, config: str) -> str:
    """Wyjście TLC dla specyfikacji ``spec`` z konfiguracją ``config`` (treść pliku ``name.cfg``).

    TLC zapisuje ślady i stany obok specyfikacji, a moduły standardowe (``Naturals.tla``) rozpakowuje pod stałą nazwą
    do ``java.io.tmpdir`` i usuwa przy wyjściu, więc każdy przebieg ma własny katalog tymczasowy i w nim swój
    ``java.io.tmpdir``. Ze wspólnym przebiegi naraz (mutacje skilla) czytają moduł, który inny przebieg właśnie
    nadpisał albo usunął, i TLC kończy się błędem parsowania zamiast werdyktu.
    """

    with tempfile.TemporaryDirectory(prefix="tlc-") as work:
        shutil.copy2(spec, work)
        Path(work, f"{name}.cfg").write_text(config, encoding="utf-8")
        result = subprocess.run(
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
            cwd=work,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    return result.stdout + result.stderr


_LIVENESS = "Postep"


def _violated(output: str) -> str | None:
    """Naruszony niezmiennik albo ``Postep``, gdy TLC znalazł przebieg bez końca, w którym dziennik nie znika."""

    if "Temporal properties were violated" in output:
        return _LIVENESS
    found = re.search(r"Invariant (\w+) is violated", output)
    return found.group(1) if found else None


def _trace(output: str) -> list[dict[str, str]]:
    """Stany kontrprzykładu; przebieg bez końca kończy się stanem, którego ``krok`` mówi, co się powtarza."""

    states: list[dict[str, str]] = []
    for line in output.splitlines():
        if _STUTTERING.match(line):
            states.append(states[-1] | {"krok": "(dalej nic sie nie dzieje)"})
        elif back := _BACK.match(line):
            again = int(back.group(1)) - 1
            states.append(states[-1] | {"krok": f"(stad znow krok {again} i tak bez konca)"})
        elif _STATE.match(line):
            states.append({})
        elif states and (variable := _VARIABLE.match(line.strip())):
            states[-1][variable.group(1)] = variable.group(2).strip('"')
    return states


def _tell(trace: list[dict[str, str]]) -> None:
    first, last = trace[0], trace[-1]
    yes = {"TRUE": "tak", "FALSE": "nie"}
    print(
        "   nowa wersja: usuwa plik taty z config/: {}, zmienia requirements.txt: {}, startuje: {}".format(
            yes[first["nowaUsuwaPlikTaty"]],
            yes[first["nowaZmieniaWymagania"]],
            yes[first["nowaStartuje"]],
        )
    )
    for number, state in enumerate(trace[1:], start=1):
        print(f"   {number}. {state['krok']}")
    print(
        f"   na koniec: klon na wersji {last['head']}, plik taty: {last['plikTaty']}, "
        f"biblioteki: {last['biblioteki']}, Centrum: {last['centrum']}, dziennik: {last['dziennik']}"
    )


def _description(name: str) -> str:
    first = (MODEL / f"{name}.cfg").read_text(encoding="utf-8").splitlines()[0]
    return first.removeprefix("\\*").strip()


if __name__ == "__main__":
    raise SystemExit(main())
