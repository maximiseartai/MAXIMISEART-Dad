"""Sprawdza model TLA+ Kolejki Skrzynki Zgłoszeń przy każdej kolejności awarii i przeplotów (TLC).

Uruchamia TLC na każdej konfiguracji z ``model/konfiguracje.json``, porównuje wynik z jej znanymi znaleziskami i
opowiada każdy kontrprzykład krokami kodu. Konfiguracje, TLC, werdykt, znane znaleziska, narzędzia TLC i rozjazd modelu
z kodem z ``model/definicje.json`` ma ``tools/lib/model_tlc.py``: rozjazd skrypt tylko
ostrzega linią ``UWAGA:`` nad werdyktem, a w CI krok z rozjazdem nie biegnie (``tools/ci/wykonaj_zadanie.py``).

    .venv/bin/python .agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_model_kolejki.py
    py -3 .agents\\skills\\verify-kolejka-skrzynki\\scripts\\sprawdz_model_kolejki.py
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import Model, Obietnica, Stan, main


def _tell(states: Sequence[Stan]) -> None:
    for number, state in enumerate(states[1:], start=1):
        print(f"   {number}. {state.petla or state.zmienne['krok']}")
    last = states[-1].zmienne
    print(f"   na koniec: pliki kolejki {last['plik']}, Skrzynka {' '.join(last['issues'].split())}")


MODEL = Model(
    werdykt="MODEL KOLEJKI",
    skill=Path(__file__).resolve().parents[1],
    specyfikacja="KolejkaSkrzynki.tla",
    obietnice={
        "JednoIssue": Obietnica("okres, problem Zgłoszenia albo Uwaga taty ma drugie issue."),
        "DokladnieRaz": Obietnica(
            "plik kolejki zniknął albo ma znacznik, a Skrzynka nie ma którejś jego części, albo ma część dwa razy."
        ),
        "CzesciWKolejnosci": Obietnica("część k stoi w issue przed częścią k-1 tej samej wysyłki."),
        "Zbieganie": Obietnica("awarie się skończyły, a plik wysyłki bez znacznika zostaje w kolejce.", czasowa=True),
    },
    opowiedz=_tell,
    zakleszczenie=False,
)


if __name__ == "__main__":
    raise SystemExit(main(MODEL, opis=__doc__.splitlines()[0] if __doc__ else None))
