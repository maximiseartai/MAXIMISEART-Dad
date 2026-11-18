"""Fakty schematu JSON Logów Uruchomienia, które decydują, czy plik Logów starszego Wydania przechodzi dzisiejszy schemat.

Fakt to ścieżka pola od korzenia Logów (``dad_actions.entries[action=widok].page``) z tym, co schemat przyjmuje: przy
obiekcie jego pola i pola wymagane, przy polu zbiór wartości zamkniętej listy albo stałej (``enum``, ``const``, pusty:
pole bez zamkniętej listy). Ścieżka idzie przez pola, a nie przez nazwy klas, więc zmiana nazwy modelu faktów nie
zmienia, a wariant unii z polem rozróżniającym ma w ścieżce jego wartość. Zapis faktów każdego Wydania i dzisiejszego
schematu to ``schemat_logow_wydan.json`` obok; dopisuje go ``python -m tests.fixtures.schemat_logow --zapisz`` z katalogu
repozytorium, które łączy zapis z dzisiejszym schematem i niczego z niego nie usuwa.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
from typing import Any, Final

WYDANIA: Final = Path(__file__).with_name("schemat_logow_wydan.json")


@dataclass
class Fakt:
    """Co schemat przyjmuje w jednej ścieżce: pola i pola wymagane obiektu, wartości zamkniętej listy pola."""

    pola: set[str] = field(default_factory=set)
    wymagane: set[str] = field(default_factory=set)
    wartosci: set[str] = field(default_factory=set)
    otwarte: bool = False
    """Pole przyjmuje też wartość spoza zamkniętej listy (tekst, liczba albo obiekt obok stałej)."""


Fakty = dict[str, Fakt]


def fakty(schemat: Mapping[str, Any]) -> Fakty:
    """Fakty schematu JSON modelu (``model_json_schema()``), ścieżka po ścieżce od korzenia."""

    definicje = schemat.get("$defs", {})
    zebrane: Fakty = {}

    def rozwin(wezel: Mapping[str, Any]) -> Mapping[str, Any]:
        while "$ref" in wezel:
            wezel = definicje[wezel["$ref"].rsplit("/", 1)[-1]]
        return wezel

    def warianty(wezel: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        wezel = rozwin(wezel)
        for klucz in ("anyOf", "oneOf"):
            if klucz in wezel:
                return [wariant for czesc in wezel[klucz] for wariant in warianty(czesc)]
        return [wezel]

    def odwiedz(wezel: Mapping[str, Any], sciezka: str, glebokosc: int) -> None:
        assert glebokosc < 40, f"schemat Logów zapętla się w {sciezka}"
        fakt = zebrane.setdefault(sciezka, Fakt())
        for wariant in warianty(wezel):
            if "enum" in wariant:
                fakt.wartosci |= {json.dumps(wartosc, ensure_ascii=False) for wartosc in wariant["enum"]}
            elif "const" in wariant:
                fakt.wartosci.add(json.dumps(wariant["const"], ensure_ascii=False))
            elif wariant.get("type") == "array":
                fakt.otwarte = True
                odwiedz(wariant.get("items", {}), f"{sciezka}[]", glebokosc + 1)
            elif "properties" in wariant:
                fakt.otwarte = True
                obiekt = zebrane.setdefault(sciezka + _rozroznienie(wariant), Fakt())
                obiekt.pola |= set(wariant["properties"])
                obiekt.wymagane |= set(wariant.get("required", ()))
                for pole, podwezel in wariant["properties"].items():
                    odwiedz(podwezel, f"{sciezka}{_rozroznienie(wariant)}.{pole}", glebokosc + 1)
            elif isinstance(wariant.get("additionalProperties"), Mapping):
                fakt.otwarte = True
                odwiedz(wariant["additionalProperties"], f"{sciezka}{{}}", glebokosc + 1)
            elif wariant.get("type") != "null":
                fakt.otwarte = True

    odwiedz(schemat, "", 0)
    return {sciezka: fakt for sciezka, fakt in zebrane.items() if fakt.pola or fakt.wartosci}


def _rozroznienie(obiekt: Mapping[str, Any]) -> str:
    """``[pole=wartość]`` wariantu unii z polem, które ma w nim stałą wartość (pole rozróżniające), a bez niego pusty
    napis."""

    for pole, wezel in obiekt.get("properties", {}).items():
        if "const" in wezel and isinstance(wezel["const"], str):
            return f"[{pole}={wezel['const']}]"
    return ""


def zwezenia(dawne: Fakty, teraz: Fakty) -> list[str]:
    """Każda zmiana, po której plik zgodny z ``dawne`` nie przechodzi ``teraz``: usunięta wartość zamkniętej listy,
    usunięte pole obiektu (Logi nie przyjmują pól spoza schematu), nowe pole wymagane i ścieżka, której już nie ma."""

    znalezione: list[str] = []
    for sciezka, fakt in sorted(dawne.items()):
        obecny = teraz.get(sciezka)
        if obecny is None:
            znalezione.append(f"{sciezka or 'Logi'}: tej ścieżki dzisiejszy schemat nie ma")
            continue
        if fakt.wartosci and not obecny.otwarte and (utracone := fakt.wartosci - obecny.wartosci):
            znalezione.append(f"{sciezka}: schemat nie przyjmuje już {', '.join(sorted(utracone))}")
        if utracone_pola := fakt.pola - obecny.pola:
            znalezione.append(f"{sciezka or 'Logi'}: nie ma już pól {', '.join(sorted(utracone_pola))}")
        if nowe := obecny.wymagane - fakt.wymagane:
            znalezione.append(f"{sciezka or 'Logi'}: nowe pola wymagane {', '.join(sorted(nowe))}")
    return znalezione


def niezapisane(zapis: Fakty, teraz: Fakty) -> list[str]:
    """Fakty dzisiejszego schematu, których zapis Wydań nie ma: bez nich zapis nie wie, co przyjmuje następne Wydanie."""

    braki: list[str] = []
    for sciezka, fakt in sorted(teraz.items()):
        dawny = zapis.get(sciezka, Fakt())
        if brak := (fakt.wartosci - dawny.wartosci) | (fakt.pola - dawny.pola):
            braki.append(f"{sciezka or 'Logi'}: {', '.join(sorted(brak))}")
    return braki


def wczytaj(sciezka: Path = WYDANIA) -> Fakty:
    zapis = json.loads(sciezka.read_text(encoding="utf-8"))
    return {
        klucz: Fakt(set(wartosc["pola"]), set(wartosc["wymagane"]), set(wartosc["wartosci"]), wartosc["otwarte"])
        for klucz, wartosc in zapis.items()
    }


def polacz(zapis: Fakty, teraz: Fakty) -> Fakty:
    """Zapis Wydań z dzisiejszym schematem: wartości i pola obu, pola wymagane tylko te, które wymagał już zapis, i
    otwarte, gdy któreś było otwarte."""

    wynik: Fakty = {}
    for sciezka in zapis.keys() | teraz.keys():
        dawny, obecny = zapis.get(sciezka), teraz.get(sciezka)
        if dawny is None or obecny is None:
            wynik[sciezka] = dawny or obecny or Fakt()
            continue
        wynik[sciezka] = Fakt(
            dawny.pola | obecny.pola,
            dawny.wymagane & obecny.wymagane,
            dawny.wartosci | obecny.wartosci,
            dawny.otwarte or obecny.otwarte,
        )
    return wynik


def zapisz(fakty_: Fakty, sciezka: Path = WYDANIA) -> None:
    tresc = {
        klucz: {
            "pola": sorted(fakt.pola),
            "wymagane": sorted(fakt.wymagane),
            "wartosci": sorted(fakt.wartosci),
            "otwarte": fakt.otwarte,
        }
        for klucz, fakt in sorted(fakty_.items())
    }
    sciezka.write_text(json.dumps(tresc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def _dzisiejsze() -> Fakty:
    from rozliczenia.centrum.run_logs import RunLog

    return fakty(RunLog.model_json_schema())


if __name__ == "__main__":
    if sys.argv[1:] != ["--zapisz"]:
        raise SystemExit("użycie: python -m tests.fixtures.schemat_logow --zapisz")
    zapisz(polacz(wczytaj() if WYDANIA.is_file() else {}, _dzisiejsze()))
