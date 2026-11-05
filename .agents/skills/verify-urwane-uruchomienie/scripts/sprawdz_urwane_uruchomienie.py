"""Sprawdza model TLA+ Dziennika Wyceny w efenix i Logów Urwanego Uruchomienia przy każdej kolejności zgaśnięć i awarii.

Uruchamia TLC na każdej konfiguracji z ``model/*.cfg``, porównuje wynik z ``model/oczekiwane.json`` i opowiada każdy
kontrprzykład krokami kodu. Javę i ``tla2tools.jar`` bierze z narzędzi skilla ``verify-aktualizacja-narzedzia``
(``sprawdz_aktualizacje.py``: przypięte ``jdk4py`` i jar w jego katalogu podręcznym), a zmienne ``TLC_JAVA`` i
``TLC_JAR`` je zastępują: kopia checkoutu mutacji nie ma ignorowanego katalogu podręcznego. Na końcu ostrzega, gdy
któraś definicja z ``model/definicje.json`` zmieniła się od Sync commit z ``SKILL.md``; rozjazd rozstrzyga
``tools/lib/rozjazd_modelu.py``. W CI (``GITHUB_ACTIONS=true``) rozjazd kończy się od razu linią
``URWANE URUCHOMIENIE: ROZJAZD MODELU Z KODEM`` i kodem 1, bez TLC.

    .venv/bin/python .agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py
    py -3 .agents\\skills\\verify-urwane-uruchomienie\\scripts\\sprawdz_urwane_uruchomienie.py
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

import rozjazd_modelu

SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[2]
MODEL = SKILL / "model"
SPEC = "UrwaneUruchomienie.tla"
TOOLS = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"

PASSES, VIOLATES = "przechodzi", "narusza"
VERDICT = "URWANE URUCHOMIENIE"
DRIFT = f"{VERDICT}: ROZJAZD MODELU Z KODEM"
LIVENESS = "Zbieganie"
# Obietnice, każda z wariantem ``…PozaZnanymi`` i stałą ``Wybaczone…`` w modelu, i ich zdanie dla czytelnika.
PROMISES = {
    "DziennikPoKolejce": "dziennik Urwanego Uruchomienia zniknął, a jego Logi nie są najnowszą wersją, którą przyjęła "
    "Kolejka wysyłki, więc do Skrzynki nie dojdą.",
    "BezUrwanychPoWyniku": "Wycena, która doszła do wyniku, dostała Logi Urwanego Uruchomienia.",
    "TeSameZnaki": "Logi Urwanego Uruchomienia poszły do kolejki z innymi znakami, niż ma plik Logów na dysku.",
    "PrzezStraznika": "Logi Urwanego Uruchomienia poszły do kolejki bez strażnika reguły danych.",
    "NicPrzedWznowieniem": "wysyłka poszła do kolejki, zanim praca Centrum wywołała Outbox.resume.",
    "ZaczeteWLogach": "zlecenie, które Urwana Wycena zmieniła w efenix, nie jest w jej Logach.",
    "WersjaKoncowa": "dziennik Wyceny, która mogła wysłać postęp, zniknął, a najnowsza wersja jej komentarza Uruchomienia w "
    "Kolejce wysyłki nie jest końcowa, więc w Skrzynce zostaje postęp „Uruchomienie trwa”.",
    "LogiZostaja": "nowsza wersja komentarza Uruchomienia zastąpiła w kolejce Logi (z wynikiem albo Urwanego Uruchomienia) "
    "postępem albo wersją bez Logów, a Logi z wynikiem także Logami Urwanego Uruchomienia.",
}
LIVENESS_SAID = "awarie się skończyły, tata otwiera i zamyka Centrum, a dziennik zostaje na dysku bez końca."
# Zmienna historii każdej obietnicy: zbiór przyczyn w chwili każdego zdarzenia, które ją łamie.
_EVENTS = {
    "DziennikPoKolejce": "zgubiony",
    "BezUrwanychPoWyniku": "poWyniku",
    "TeSameZnaki": "inneZnaki",
    "PrzezStraznika": "bezStrazy",
    "NicPrzedWznowieniem": "przedWznowieniem",
    "ZaczeteWLogach": "bezZlecenia",
    "WersjaKoncowa": "bezWersji",
    "LogiZostaja": "wyparty",
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
    drift = rozjazd_modelu.rozjazd(SKILL, ROOT)
    if drift is not None and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"UWAGA: {drift}\n\n{DRIFT}")
        return 1
    expected = json.loads((MODEL / "oczekiwane.json").read_text(encoding="utf-8"))
    names = args.config or sorted(path.stem for path in MODEL.glob("*.cfg"))
    java = os.environ.get("TLC_JAVA") or tools._java()
    jar = Path(os.environ.get("TLC_JAR") or tools._tla_tools())

    new, gone, known, broken = [], [], [], []
    for name in names:
        findings = expected.get(name, {}).get("znane", [])
        print(f"\n== {name}: {_description(name)}")
        # TLC kończy na pierwszym kontrprzykładzie, więc każde znane znalezisko ma swój przebieg bez pozostałych
        # znanych tej konfiguracji (czy ono dalej jest), a konfiguracja jeden przebieg bez wszystkich swoich znanych (czy
        # nic poza nimi). Wybaczenie dotyczy tylko znalezisk, które ``model/oczekiwane.json`` podaje dla tej
        # konfiguracji, tylko ich obietnicy i tylko zdarzenia, w którego chwili była ich przyczyna.
        config_known = frozenset((finding["obietnica"], finding["przyczyna"]) for finding in findings)
        for finding in findings:
            promise, cause = finding["obietnica"], finding["przyczyna"]
            print(f"   znane znalezisko „{cause}”, {promise}: {finding['znalezisko']}")
            own = _run(java, jar, name, config_known - {(promise, cause)})
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
            print("   reszta przebiegów, bez wszystkich znanych znalezisk tej konfiguracji:")
        rest = _run(java, jar, name, config_known)
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
    """``sprawdz_aktualizacje.py``: Java, ``tla2tools.jar`` i TLC we własnym katalogu."""

    spec = importlib.util.spec_from_file_location("sprawdz_aktualizacje", TOOLS)
    if spec is None or spec.loader is None:
        sys.exit(f"BŁĄD: nie da się wczytać {TOOLS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Verdict(NamedTuple):
    """Werdykt TLC: naruszona obietnica (``None``, gdy przechodzi) i przyczyny w chwilach jej zdarzeń."""

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
    ``Zbieganie`` nie ma znanych znalezisk.
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
    if "Temporal properties were violated" in output:
        print(f"   naruszone {LIVENESS}: {LIVENESS_SAID}")
        _tell(_trace(output))
        return Verdict(LIVENESS)
    found = re.search(r"Invariant (\w+) is violated", output)
    if found is None:
        print("   BŁĄD MODELU: TLC nie dał werdyktu.\n" + output)
        return None
    promise = found.group(1).removesuffix("PozaZnanymi")
    trace = _trace(output)
    if promise not in PROMISES:
        print(f"   BŁĄD MODELU: naruszony {promise}, czyli model wyszedł poza swoje wartości.")
        _tell(trace)
        return None
    print(f"   naruszone {promise}: {PROMISES[promise]}")
    _tell(trace)
    return Verdict(promise, frozenset(re.findall(r'"([\w-]+)"', trace[-1].get(_EVENTS[promise], ""))))


def _trace(output: str) -> list[dict[str, str]]:
    """Stany kontrprzykładu z nazwą akcji, która do nich prowadzi; wartość na kilku liniach skleja w jedną.

    Przebieg bez końca kończy się stanem, którego akcja mówi, co się powtarza.
    """

    states: list[dict[str, str]] = []
    variable = ""
    for line in output.splitlines():
        if _STUTTERING.match(line):
            states.append(states[-1] | {"_akcja": "(dalej nic się nie dzieje)"})
            variable = ""
        elif back := _BACK.match(line):
            again = int(back.group(1)) - 1
            states.append(states[-1] | {"_akcja": f"(stąd znów krok {again} i tak bez końca)"})
            variable = ""
        elif _STATE.match(line):
            action = re.search(r"<(\w+)", line)
            states.append({"_akcja": action.group(1) if action and action.group(1) != "Initial" else "Init"})
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
    "Start": "tata otwiera Centrum: port, create_app, InterruptedPricings.close czyta dzienniki",
    "ZapiszLogi": "close zapisuje plik Logów Wyceny {k} po strażniku (RunLogs.close)",
    "UsunDziennik": "close usuwa dziennik Wyceny {k} (_remove)",
    "Wznow": "lifespan: Outbox.resume",
    "PierwszeZapytanie": "pierwsze zapytanie API: send_interrupted bierze wersje zastępcze z _pending",
    "Wyslij": "send: Outbox.post wersji zastępczej ({h}) Wyceny {w}, Rank.STAND_IN",
    "UsunPoWysylce": "send usuwa dziennik Wyceny {w} po przyjęciu przez kolejkę",
    "StartWyceny": "tata uruchamia Wycenę {b2} (PricingJournal.run_started)",
    "ZapiszStart": "run_started zapisuje pierwszą linię dziennika Wyceny {b} (_append_locked)",
    "Postep": "budzik postępu: RunLogs.progress, kolejka przyjmuje postęp Wyceny {b} z dziennika, Rank.DRAFT",
    "WpisZaczete": "Wycena {b} pisze „zaczynam zlecenie” {z}",
    "ZmianaWEfenix": "okno efenix zmienia zlecenie {z} Wyceny {b}",
    "WpisSkonczone": "Wycena {b} pisze „zlecenie skończone” {z}",
    "Zatrzymanie": "Wycena {b} staje przy zleceniu {z} (Zatrzymanie): bez „zlecenie skończone” do wyniku",
    "Wynik": "run_process Wyceny {b} wraca z wynikiem (rekord metryk, wiersz Historii, zapisany albo nie)",
    "WpisKonca": "PricingJournal.run_ended: Wycena {b} pisze „koniec Uruchomienia”, zanim powstaną jej Logi",
    "LogiWyniku": "RunLogs._keep zapisuje plik Logów z wynikiem Wyceny {b}",
    "WyslijWynik": "RunLogs._keep: Outbox.post Logów z wynikiem Wyceny {b}, Rank.OWN",
    "UsunPoLogach": "JournalAfterLogs: dziennik Wyceny {b} znika, gdy kolejka przyjęła jej Logi z wynikiem",
    "KoniecUruchomienia": "reszta działań po wyniku Wyceny {b}, koniec Uruchomienia",
    "Zgasniecie": "Centrum gaśnie (brak prądu, zabity proces)",
    "Zamkniecie": "tata zamyka Centrum",
}


def _step(action: str, before: dict[str, str], after: dict[str, str]) -> str:
    """Krok kontrprzykładu w słowach kodu; awaria w kroku to zmiana jej licznika."""

    if action == "Czytaj":
        return _read(before, after)
    first = _first_record(before.get("doWyslania", ""))
    run = re.search(r"bieg \|-> (\d+)", first)
    kind = re.search(r'rodzaj \|-> "(\w+)"', first)
    fields = {
        "k": before.get("kursor", "?"),
        "w": run.group(1) if run else "?",
        "h": _KINDS.get(kind.group(1), "?") if kind else "?",
        "b": before.get("bieg", "?"),
        "b2": after.get("bieg", "?"),
        "z": before.get("zlecenie", "?"),
    }
    said = _STEPS.get(action, action).format(**fields)
    if action == "Start" and after.get("cofniecia") != before.get("cofniecia"):
        said += ", a zegar komputera cofnął się, gdy Centrum było zamknięte"
    if action in ("Wyslij", "Postep", "WyslijWynik") and after.get("najnowsza") == before.get("najnowsza"):
        said += " (kolejka ma nowszą wersję, więc ta niczego nie zmienia)"
    if action == "WpisKonca" and before.get("naglowekCzeka") == "TRUE":
        kept = "_remove usuwa dziennik" if after.get("dziennik") != before.get("dziennik") else "bez wpisu końca"
        said = f"PricingJournal.run_ended: żaden wpis Wyceny {fields['b']} się nie zapisał (_header), {kept}"
    # Nieudany wpis, po którym dziennik powstał: write położył całą pierwszą linię, a flush albo fsync rzucił.
    left_start = action != "WpisKonca" and after.get("dziennik") != before.get("dziennik")
    failed = [
        what
        for counter, what in (
            ("awarieWpisu", "wpis rzuca OSError po całej pierwszej linii na dysku" if left_start else "wpis rzuca OSError"),
            ("awarieLogow", "zapis pliku Logów rzuca OSError"),
            ("awarieKolejki", "Outbox.post zwraca False"),
            ("awarieUsuniecia", "unlink rzuca OSError"),
        )
        if after.get(counter) != before.get(counter)
    ]
    return said + (f": {', '.join(failed)}" if failed else "")


def _first_record(value: str) -> str:
    """Pierwszy rekord ``[...]`` ciągu TLC, z rekordami zagnieżdżonymi; TLC wypisuje pola w swojej kolejności."""

    start = value.find("[")
    depth = 0
    for index in range(max(start, 0), len(value)):
        depth += {"[": 1, "]": -1}.get(value[index], 0)
        if depth == 0 and start >= 0:
            return value[start : index + 1]
    return ""


def _read(before: dict[str, str], after: dict[str, str]) -> str:
    """Co ``close`` postanowił o dzienniku na pozycji ``kursor``."""

    k = before.get("kursor", "?")
    if after.get("awarieOdczytu") != before.get("awarieOdczytu"):
        return f"close: odczyt dziennika Wyceny {k} rzuca OSError, dziennik zostaje następnemu startowi"
    if after.get("krokZamykania") == "usun":
        journals = re.findall(r'"(\w+)"', before.get("dziennik", ""))
        index = int(k) - 1 if k.isdigit() else -1
        why = "bez pierwszej linii" if 0 <= index < len(journals) and journals[index] == "bezStartu" else "bez wysyłki"
        return f"close: dziennik Wyceny {k} do usunięcia, {why}"
    if after.get("krokZamykania") == "zapisz":
        files = re.findall(r'rodzaj \|-> "(\w+)", tresc', before.get("logi", ""))
        index = int(k) - 1 if k.isdigit() else -1
        if 0 <= index < len(files) and files[index] != "brak":
            return f"close: {_KINDS[files[index]]} Wyceny {k} z pliku Logów, po strażniku (guard)"
        return f"close: Logi Urwanego Uruchomienia Wyceny {k} z dziennika, po strażniku (guard)"
    if after.get("oczekujace") != before.get("oczekujace"):
        return f"close: wynik bez Logów Wyceny {k} (wpis końca bez pliku Logów, ResultWithoutLogs)"
    return f"close: dziennika Wyceny {k} nie ma"


def _tell(trace: list[dict[str, str]]) -> None:
    for number, (before, state) in enumerate(itertools.pairwise(trace), start=1):
        print(f"   {number}. {_step(state['_akcja'], before, state)}")
    last = trace[-1] if trace else {}
    print(
        f"   na koniec: dzienniki {_brief(last.get('dziennik', '?'))}, Logi {_logs(last.get('logi', ''))}, "
        f"z wynikiem {_brief(last.get('wynik', '?'))}, "
        f"kolejka {_queue(last.get('kolejka', ''))}, najnowsza wersja w kolejce {_newest(last.get('najnowsza', ''))}"
    )


def _brief(value: str) -> str:
    return " ".join(value.split())


def _logs(value: str) -> str:
    """Rodzaj pliku Logów każdej Wyceny, a Logów Urwanego Uruchomienia także to, czy mają maskę strażnika."""

    found = re.findall(r'rodzaj \|-> "(\w+)", tresc \|-> \[[^\]]*tekst \|-> "(\w+)"', value)
    return "<<" + ", ".join(kind if kind != "urwane" else f"urwane {text}" for kind, text in found) + ">>"


def _queue(value: str) -> str:
    """Wersje końcowe, które Kolejka przyjęła: rodzaj i Wycena."""

    found = re.findall(r'rodzaj \|-> "(\w+)".*?bieg \|-> (\d+)', value)
    return "{" + ", ".join(f"{kind} Wyceny {run}" for kind, run in found) + "}"


def _newest(value: str) -> str:
    """Najnowsza wersja komentarza Uruchomienia każdej Wyceny w kolejce: rodzaj i stopień."""

    found = re.findall(r'rodzaj \|-> "(\w+)", stopien \|-> (\d)', value)
    return "<<" + ", ".join(f"{kind} {rank}" for kind, rank in found) + ">>"


# Rodzaj wersji z dziennika w słowach kontrprzykładu.
_KINDS = {"wynik": "Logi z wynikiem z pliku", "urwane": "Logi Urwanego Uruchomienia", "bezLogow": "wynik bez Logów"}


def _description(name: str) -> str:
    first = (MODEL / f"{name}.cfg").read_text(encoding="utf-8").splitlines()[0]
    return first.removeprefix("\\*").strip()


if __name__ == "__main__":
    raise SystemExit(main())
