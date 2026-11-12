"""Sprawdza model TLA+ Dziennika Wyceny w efenix i Logów Urwanego Uruchomienia przy każdej kolejności zgaśnięć i awarii.

Uruchamia TLC na każdej konfiguracji z ``model/konfiguracje.json``, porównuje wynik z jej znanymi znaleziskami i
opowiada każdy kontrprzykład krokami kodu. Konfiguracje, TLC, werdykt, znane znaleziska, narzędzia TLC i rozjazd modelu
z kodem z ``model/definicje.json`` ma ``tools/lib/model_tlc.py``: rozjazd skrypt tylko
ostrzega linią ``UWAGA:`` nad werdyktem, a w CI krok z rozjazdem nie biegnie (``tools/ci/wykonaj_zadanie.py``).
W CI część ``MUTACJE_CZESC=k/n`` (``ci-czesci`` w ``SKILL.md``) sprawdza tylko swój kawałek ``UNITS``
(``skrypt_skilla.part``); jawne ``--config`` (skrypt mutacji, człowiek) bierze swoje konfiguracje bez względu na część.

    .venv/bin/python .agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py
    py -3 .agents\\skills\\verify-urwane-uruchomienie\\scripts\\sprawdz_urwane_uruchomienie.py
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import itertools
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import Model, Obietnica, Stan, main
from skrypt_skilla import part

# Jednostki części podstawy w CI: grupy konfiguracji. Przebieg ``wszystko`` to ~85% podstawy (Windows CI, 12.11, sonda
# 43305166779 z ``-lncheck final``: 245 i 239 s z 288 i 284 s), więc stoi sam, a reszta (42 i 44 s) w drugiej.
UNITS = (
    ("wszystko",),
    ("koniec", "logi-i-kolejka", "odczyt", "stare-logi", "wpisy", "zegar", "zwykle"),
)


def arguments(argv: Sequence[str], environment: Mapping[str, str] = os.environ) -> list[str]:
    """Argumenty ``main``: bez ``--config`` konfiguracje części ``MUTACJE_CZESC`` z ``UNITS`` (bez części wszystkie);
    zła część to ``ValueError``."""

    if any(argument.partition("=")[0] == "--config" for argument in argv):
        return list(argv)
    return [*argv, *(f"--config={name}" for unit in part(UNITS, environment) for name in unit)]

# Akcja modelu i krok kodu, który opisuje (tabela w SKILL.md), w słowach kontrprzykładu.
_STEPS = {
    "Start": "tata otwiera Centrum: port, create_app, RunComments.close_left_behind czyta dzienniki (LogsOnDisk.left_behind)",
    "ZapiszLogi": "close_left_behind zapisuje plik Logów Wyceny {k} po strażniku (LogsOnDisk.write)",
    "UsunDziennik": "close_left_behind usuwa dziennik Wyceny {k} (_remove)",
    "Wznow": "lifespan: Outbox.resume",
    "WysylkaStartu": "serve po wpisie start, krok AFTER_START z lifespan po Outbox.resume: send_left_behind bierze wersje zastępcze z _pending",
    "Wyslij": "send_left_behind: Outbox.post wersji zastępczej ({h}) Wyceny {w}, Rank.STAND_IN",
    "UsunPoWysylce": "send_left_behind usuwa dziennik Wyceny {w} po przyjęciu przez kolejkę",
    "StartWyceny": "tata uruchamia Wycenę {b2} (LogsOnDisk.started)",
    "ZapiszStart": "RunComments.run_started zapisuje pierwszą linię dziennika Wyceny {b} (_append_locked)",
    "Postep": "budzik postępu: RunComments._progress, kolejka przyjmuje postęp Wyceny {b} z dziennika, Rank.DRAFT",
    "WpisZaczete": "Wycena {b} pisze „zaczynam zlecenie” {z}",
    "ZmianaWEfenix": "okno efenix zmienia zlecenie {z} Wyceny {b}",
    "WpisSkonczone": "Wycena {b} pisze „zlecenie skończone” {z}",
    "Zatrzymanie": "Wycena {b} staje przy zleceniu {z} (Zatrzymanie): bez „zlecenie skończone” do wyniku",
    "Wynik": "run_process Wyceny {b} wraca z wynikiem (rekord metryk, wiersz Historii, zapisany albo nie)",
    "WpisKonca": "RunComments.run_ended, krok 1, Journal.end: Wycena {b} pisze „koniec Uruchomienia”, zanim powstaną jej Logi",
    "LogiWyniku": "RunComments._keep zapisuje plik Logów z wynikiem Wyceny {b}",
    "WyslijWynik": "RunComments._keep: Outbox.post Logów z wynikiem Wyceny {b}, Rank.OWN",
    "UsunPoLogach": "RunComments.run_ended, krok 4: dziennik Wyceny {b} znika, gdy kolejka przyjęła jej Logi z wynikiem",
    "KoniecUruchomienia": "reszta działań po wyniku Wyceny {b}, koniec Uruchomienia",
    "Zgasniecie": "Centrum gaśnie (brak prądu, zabity proces)",
    "Zamkniecie": "tata zamyka Centrum",
}


# Akcja, którą opowiada ``_read``, bo jej słowa zależą od tego, co ``close`` postanowił.
_READ = "Czytaj"


def _step(action: str, before: dict[str, str], after: dict[str, str]) -> str:
    """Krok kontrprzykładu w słowach kodu; awaria w kroku to zmiana jej licznika."""

    if action == _READ:
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
    said = _STEPS[action].format(**fields)
    if action == "Start" and after.get("cofniecia") != before.get("cofniecia"):
        said += ", a zegar komputera cofnął się, gdy Centrum było zamknięte"
    if action in ("Wyslij", "Postep", "WyslijWynik") and after.get("najnowsza") == before.get("najnowsza"):
        said += " (kolejka ma nowszą wersję, więc ta niczego nie zmienia)"
    if action == "WpisKonca" and before.get("naglowekCzeka") == "TRUE":
        kept = "_remove usuwa dziennik" if after.get("dziennik") != before.get("dziennik") else "bez wpisu końca"
        said = f"Journal.end: żaden wpis Wyceny {fields['b']} się nie zapisał (_header), {kept}"
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
            return f"close: {_KINDS[files[index]]} Wyceny {k} z pliku Logów, po strażniku (guard_logs)"
        return f"close: Logi Urwanego Uruchomienia Wyceny {k} z dziennika, po strażniku (guard_logs)"
    if after.get("oczekujace") != before.get("oczekujace"):
        return f"close: wynik bez Logów Wyceny {k} (wpis końca bez pliku Logów, ResultWithoutLogs)"
    return f"close: dziennika Wyceny {k} nie ma"


def _tell(states: Sequence[Stan]) -> None:
    for number, (before, state) in enumerate(itertools.pairwise(states), start=1):
        print(f"   {number}. {state.petla or _step(state.akcja, before.zmienne, state.zmienne)}")
    last = states[-1].zmienne if states else {}
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


MODEL = Model(
    werdykt="URWANE URUCHOMIENIE",
    skill=Path(__file__).resolve().parents[1],
    specyfikacja="UrwaneUruchomienie.tla",
    # Zmienna historii każdej obietnicy: zbiór przyczyn w chwili każdego zdarzenia, które ją łamie.
    obietnice={
        "DziennikPoKolejce": Obietnica(
            "dziennik Urwanego Uruchomienia zniknął, a jego Logi nie są najnowszą wersją, którą przyjęła Kolejka wysyłki, "
            "więc do Skrzynki nie dojdą.",
            "zgubiony",
        ),
        "BezUrwanychPoWyniku": Obietnica("Wycena, która doszła do wyniku, dostała Logi Urwanego Uruchomienia.", "poWyniku"),
        "TeSameZnaki": Obietnica(
            "Logi Urwanego Uruchomienia poszły do kolejki z innymi znakami, niż ma plik Logów na dysku.", "inneZnaki"
        ),
        "PrzezStraznika": Obietnica("Logi Urwanego Uruchomienia poszły do kolejki bez strażnika reguły danych.", "bezStrazy"),
        "NicPrzedWznowieniem": Obietnica(
            "wysyłka poszła do kolejki, zanim praca Centrum wywołała Outbox.resume.", "przedWznowieniem"
        ),
        "ZaczeteWLogach": Obietnica("zlecenie, które Urwana Wycena zmieniła w efenix, nie jest w jej Logach.", "bezZlecenia"),
        "WersjaKoncowa": Obietnica(
            "dziennik Wyceny, która mogła wysłać postęp, zniknął, a najnowsza wersja jej komentarza Uruchomienia w "
            "Kolejce wysyłki nie jest końcowa, więc w Skrzynce zostaje postęp „Uruchomienie trwa”.",
            "bezWersji",
        ),
        "LogiZostaja": Obietnica(
            "nowsza wersja komentarza Uruchomienia zastąpiła w kolejce Logi (z wynikiem albo Urwanego Uruchomienia) "
            "postępem albo wersją bez Logów, a Logi z wynikiem także Logami Urwanego Uruchomienia.",
            "wyparty",
        ),
        "Zbieganie": Obietnica(
            "awarie się skończyły, tata otwiera i zamyka Centrum, a dziennik zostaje na dysku bez końca.", None, czasowa=True
        ),
    },
    opowiedz=_tell,
    akcje=frozenset({*_STEPS, _READ}),
)


if __name__ == "__main__":
    try:
        argv = arguments(sys.argv[1:])
    except ValueError as problem:
        print(f"BŁĄD MODELU: {problem}\n\n{MODEL.werdykt}: BŁĄD MODELU (1)")
        raise SystemExit(2) from None
    raise SystemExit(main(MODEL, argv, opis=__doc__.splitlines()[0] if __doc__ else None))
