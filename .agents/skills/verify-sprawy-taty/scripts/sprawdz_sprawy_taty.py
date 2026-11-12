"""Sprawdza model TLA+ Spraw taty, Zgłoszenia i Uwagi taty przy każdej kolejności wątków, awarii i zgaśnięć Centrum.

Uruchamia TLC na każdej konfiguracji z ``model/konfiguracje.json``, porównuje wynik z jej znanymi znaleziskami i
opowiada każdy kontrprzykład krokami kodu. Konfiguracje, TLC, werdykt, znane znaleziska, narzędzia TLC i rozjazd modelu
z kodem z ``model/definicje.json`` ma ``tools/lib/model_tlc.py``: rozjazd skrypt tylko ostrzega linią ``UWAGA:`` nad
werdyktem, a w CI krok z rozjazdem nie biegnie (``tools/ci/wykonaj_zadanie.py``).

    .venv/bin/python .agents/skills/verify-sprawy-taty/scripts/sprawdz_sprawy_taty.py
    py -3 .agents\\skills\\verify-sprawy-taty\\scripts\\sprawdz_sprawy_taty.py
"""

from __future__ import annotations

from collections.abc import Sequence
import itertools
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import Model, Obietnica, Stan, main

# Akcja modelu i krok kodu, który opisuje (tabela w SKILL.md), w słowach kontrprzykładu.
_STEPS = {
    "Podglad": "Diagnoza na karcie Zatrzymania: ReportHandle.prepare, wątek zgloszenie-skrzynka pyta skrzynkę (_ask)",
    "Pytanie": "Reports._ask_box: skrzynka odpowiada o otwarte Zgłoszenie problemu",
    "Decyzja": "ReportHandle._ask pokazuje stan na karcie",
    "Klik": "tata klika „Wyślij do Maksa” (ReportHandle.send)",
    "Sprawdz": "Reports._queue: _pending",
    "Post": "Reports._queue: Outbox.post zapisuje plik kolejki",
    "Wycofaj": "Reports._queue, finally: DadCases.withdraw sprawy bez pliku kolejki",
    "Czekaj": "Reports._queue: Outbox.wait_delivered, potem DadCases.queued",
    "Pokaz": "ReportHandle.send pokazuje wynik wysyłki na karcie",
    "UwagaWyslij": "tata klika „Wyślij” Uwagi taty: dad_notes.send, DadCases.add sprawy bez numeru",
    "UwagaPost": "dad_notes.send: Outbox.post zapisuje plik kolejki Uwagi",
    "UwagaZapomnij": "dad_notes.send: DadCases.forget Uwagi, której kolejka nie zapisała",
    "Doreczenie": "wątek skrzynka-kolejka: _send_all doręcza najstarszy plik",
    "Uslyszane": "DadCases._tell: Reports._heard i uchwyt na karcie słyszą wynik doręczenia",
    "Oznacz": "_send_all: _first_comments, znacznik dostarczenia i usunięcie pliku kolejki",
    "Powiadomienia": "tata otwiera Powiadomienia: StateFile.retry i DadCases.ask_box",
    "MaksZamyka": "Maks zamyka issue w Skrzynce",
    "Zgasniecie": "Centrum gaśnie, a tata otwiera je znowu: DadCases._load czyta config/sprawy-taty.json",
}

# Stan karty Zatrzymania (ReportState) słowami taty.
_CARDS = {
    "gotowe": "gotowe do wysłania",
    "czekaNaNaprawe": "czeka na naprawę",
    "wKolejce": "czeka w kolejce",
    "wyslane": "wysłane",
    "odrzucone": "Skrzynka odrzuciła treść",
    "niezapisane": "nie zapisano na komputerze",
}

# Zmiana licznika awarii w kroku i jej słowa.
_FAILURES = (
    ("awarieSieci", "skrzynka nie odpowiada"),
    ("awariePlikuStanu", "zapis config/sprawy-taty.json rzuca OSError"),
    ("awarieKolejki", "Outbox.post zwraca False"),
    ("wyjatkiKolejki", "Outbox.post rzuca wyjątek"),
)


def _step(action: str, before: dict[str, str], after: dict[str, str]) -> str:
    """Krok kontrprzykładu w słowach kodu, z tym, co zmienił na karcie, w sprawach i w kolejce."""

    said = _STEPS[action]
    if action == "Doreczenie" and after.get("awarieSieci") == before.get("awarieSieci"):
        if after.get("odrzuconePliki") != before.get("odrzuconePliki"):
            said += ": Skrzynka odrzuca treść (Listener.rejected, DadCases.rejected)"
        else:
            said += ": Skrzynka przyjmuje wysyłkę (Listener.delivered, DadCases.numbered)"
    if action == "Post" and after.get("odrzucenia") != before.get("odrzucenia"):
        said += " (z treścią, którą Skrzynka odrzuci)"
    if action == "Sprawdz":
        said += ": sprawa problemu czeka, bez wysyłki" if after.get("sprawy") == before.get("sprawy") else (
            ": nie czeka, więc DadCases.add sprawy bez numeru"
        )
    failed = [what for counter, what in _FAILURES if after.get(counter) != before.get(counter)]
    if failed:
        said += f": {', '.join(failed)}"
    if after.get("karta") != before.get("karta"):
        said += f"; karta: {_CARDS.get(after.get('karta', ''), '?')}"
    return said


def _tell(states: Sequence[Stan]) -> None:
    for number, (before, state) in enumerate(itertools.pairwise(states), start=1):
        print(f"   {number}. {state.petla or _step(state.akcja, before.zmienne, state.zmienne)}")
    last = states[-1].zmienne if states else {}
    print(
        f"   na koniec: karta „{_CARDS.get(last.get('karta', ''), '?')}”, sprawy w pamięci {_cases(last.get('sprawy', ''))}, "
        f"w config/sprawy-taty.json {_cases(last.get('plikStanu', ''))}, kolejka {_queue(last.get('kolejka', ''))}"
    )


def _cases(value: str) -> str:
    """Sprawy: rodzaj, id i numer issue (bez numeru: czeka)."""

    found = re.findall(r'rodzaj \|-> "(\w+)", id \|-> (\d+), numer \|-> (\d+)', value)
    words = [f"{'Zgłoszenie' if kind == 'zgl' else f'Uwaga {case}'} {'czeka' if number == '0' else f'#{number}'}"
             for kind, case, number in found]
    return "<<" + ", ".join(words) + ">>"


def _queue(value: str) -> str:
    found = re.findall(r'rodzaj \|-> "(\w+)", id \|-> (\d+)', value)
    return "{" + ", ".join("Zgłoszenie" if kind == "zgl" else f"Uwaga {case}" for kind, case in found) + "}"


MODEL = Model(
    werdykt="SPRAWY TATY",
    skill=Path(__file__).resolve().parents[1],
    specyfikacja="SprawyTaty.tla",
    obietnice={
        "CzekaMaPlik": Obietnica(
            "sprawa czeka (bez numeru issue), a w Kolejce wysyłki nie ma jej pliku ani zapytania, które go zapisze: "
            "Maks jej nie dostanie, a Powiadomienie i karta mówią „czeka” na zawsze.",
            "bezPliku",
        ),
        "OdrzuconaNieCzeka": Obietnica(
            "karta mówi „czeka w kolejce” o Zgłoszeniu, którego treść Skrzynka odrzuciła w tej pracy Centrum, a "
            "„Wyślij do Maksa” oddaje ten stan bez wysyłki.",
            "odrzuconaCzeka",
        ),
        "Zbieganie": Obietnica(
            "awarie i zgaśnięcia się skończyły, Centrum działa, a karta dalej nie mówi tego, co wiedzą Sprawy taty, "
            "albo plik w kolejce nie dostaje ani numeru issue, ani odrzucenia.",
            None,
            czasowa=True,
        ),
    },
    opowiedz=_tell,
    akcje=frozenset(_STEPS),
    zakleszczenie=False,
)


if __name__ == "__main__":
    raise SystemExit(main(MODEL, opis=__doc__.splitlines()[0] if __doc__ else None))
