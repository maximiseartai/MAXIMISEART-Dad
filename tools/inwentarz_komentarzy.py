from __future__ import annotations

import argparse
import ast
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
import configparser
from dataclasses import dataclass, replace
import io
import json
from pathlib import Path, PurePath, PurePosixPath
import re
import shutil
import subprocess
import sys
import sysconfig
import time
import tokenize
import tomllib
from typing import Final

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

from kroki_lokalne import OUTPUT_ON_FAILURE, environment, pytest_step
from kroki_skilli import Step
import odpalenia_ast_grep
import potomne
import repo
import rozjazd_modelu
from wplyw_zmiany import changed_since
from zakres_runu import Zdarzenie, ZakresRunu, zakresy

OPIS = """Wypisuje komentarze i docstringi z plikiem, linią, formą i węzłem, a z --dowod-fali sprawdza falę zakresem runu CI; użyj do pliku dowodu fali.

Inwentarz czyta pliki śledzone przez gita (całe repozytorium albo podane ścieżki) i wypisuje każdy komentarz i każdą
instrukcję z samego napisu w formach z listy niżej. Nie mówi, kto wpis czyta, i nie dzieli wpisów na czytane przez
program i przez człowieka. Program, który czyta wpis, widać dopiero w jego biegu: bieg tych, które CI uruchamia dla
zmiany fali, pokazują Required CI jej PR, ``--dowod-fali`` (niżej) i CI ``main`` po merge'u, a czytelnika, którego CI
nie uruchamia, nie widać ani w inwentarzu, ani w dowodzie fali.

Formy wpisu:

- ``komentarz``: komentarz ``#`` w Pythonie (``tokenize``), także w pliku bez rozszerzenia z shebangiem Pythona;
- ``docstring``: napis pierwszej instrukcji modułu, klasy albo funkcji (``ast``), a ``docstring-jedyna-instrukcja``
  taki napis, który jest całym ciałem klasy albo funkcji, więc bez niego ciało nie istnieje;
- ``napis``: inna instrukcja z samego napisu, np. napis pod przypisaniem, którego węzeł to nazwa przypisana nad nim;
- ``ts``, ``css``, ``html``, ``yaml``, ``powłoka``: komentarz w drzewie składni ast-grep (TS, TSX, JS, CSS, HTML,
  YAML, skrypt ``.sh``); ``#`` w napisie YAML albo w skrypcie ``run: |`` workflowu jest napisem, nie komentarzem YAML;
- ``toml``, ``ini``: ``#`` (w ``ini`` także ``;``), bez którego ``tomllib`` albo ``configparser`` czyta ten sam plik;
- ``gitignore`` (``.gitignore``, ``.gitattributes``, ``.ignore``) i ``requirements`` (``requirements*.txt``).

Pliku innego formatu (np. Markdown, model TLA+, ``.jsonc``), pliku z atrybutem ``merge=wygenerowane``
(``.gitattributes``) i pliku frontendu z ``ignorePatterns`` w ``frontend/.oxlintrc.json`` inwentarz nie czyta, a ostatnia
linia liczy je z przyczyną. Kolejne komentarze całych linii o tym samym wcięciu, oba bez znacznika, to jeden wpis.
Węzeł to definicja albo klucz, który komentarz opisuje: ta, która zaczyna się w pierwszej linii kodu pod komentarzem
(w linii komentarza na jej końcu), a bez niej najwęższa, która tę linię obejmuje; ``moduł`` albo ``plik`` poza nimi.

Znacznik komentarza mówi o kształcie jego tekstu: ``shebang`` (pierwsza linia ``#!`` pliku Pythona albo powłoki),
``kodowanie`` (linia kodowania Pythona z PEP 263 w pierwszej albo drugiej linii) albo ``kształt dyrektywy``: linia treści
zaczyna się słowem z dwukropkiem albo ``@słowem`` (``# noqa: KOD - powód``, ``# type: ignore[kod]``, ``// SAFETY:
powód``, ``// @ts-expect-error``, ``# ZEWNĘTRZNE: fakt (źródło)``, ale też proza ``# Uwaga: …``) albo tekst ma słowo
``noqa`` w dowolnej wielkości liter. Dyrektywa bez tego kształtu (``// oxlint-disable-next-line reguła -- powód``,
``// eslint-disable``, ``# shellcheck disable=``, ``/// <reference``) znacznika nie ma. Znacznik to tylko kształt: ani nie
dowodzi, że wpis czyta program, ani jego brak, że nie czyta.

Linia wpisu: ``plik:linia[-koniec] | forma | węzeł | znacznik | pierwsza linia tekstu``, ze znacznikiem ``-``, gdy go nie
ma; z ``--json`` linia JSON z pełnym tekstem. Ostatnia linia: ``INWENTARZ OK | plików N | wpisów W (linii L) | ze
znacznikiem Z | nieczytane K: <przyczyna> <liczba>, …``; kod 1 i ``INWENTARZ FAIL`` znaczą plik, którego parser nie
przeczytał, albo brak ast-grep (pliki spoza Pythona).

``--dowod-fali [BAZA]`` (domyślnie ``origin/main``) zamiast inwentarza sprawdza zmianę fali zakresem runu CI. Zmiana to
pliki, którymi checkout, razem z niezacommitowanymi i nieśledzonymi, różni się od ``merge-base`` HEAD z bazą
(``changed_since`` z ``tools/lib/wplyw_zmiany.py``, jak w ``tools/szybko.py``), a zakres runu to praca, którą
``tools/lib/zakres_runu.py`` daje tej zmianie na pull request, na pushu do ``main`` i nocą. Pracę pull requestu liczy
Required CI jego PR, więc tryb jej nie uruchamia i podaje ją jedną linią ``PR``. Z pracy, którą push do ``main`` dokłada
do pull requestu, tryb uruchamia na tym checkoucie, Pythonem narzędzia, pliki testów spoza wyboru pull requestu
(``pytest -n auto``, jak ``tools/ci_lokalnie.py``), a przed każdą podstawą ``ci:`` skilla z modelem kodu
(``model/definicje.json``) zadaje pytanie, które zadaje przed nią wykonanie zadania na ``main``:
``rozjazd_modelu.rozjazd``. Rozjazd skilla, którego plików modelu ani pliku definicji zmiana nie dotyka, jest już na bazie,
więc tryb go wypisuje, ale nie liczy jako porażki fali. Kroków CI spoza pytest (E2E, straż czasu), samych podstaw i
pracy nocy tryb nie uruchamia, tylko wymienia każdą ich jednostkę z wynikiem ``po merge'u``: E2E i straży czasu nie
uruchamia lokalnie ``tools/ci_lokalnie.py``, a podstaw spoza pull requestu i kroków nocy agent
(``tools/skille_dla_zmiany.py``, linie ``LICZY MAIN`` i ``LICZY NOC``). FAIL znalezienia kroku skilla z zakresu to
porażka. Linia jednostki: ``MAIN|NOC | rodzaj | nazwa | wynik``.
Ostatnia linia: ``DOWÓD FALI OK|FAIL | baza SHA | zmiana N plików | lokalnie: pytest P plików, rozjazd modelu R skilli |
po merge'u: kroki CI C, podstawy B, noc Q``, z porażkami po ``FAIL |``; kod 1 to porażka, brak zmiany albo nieznana baza.

    .venv/bin/python tools/inwentarz_komentarzy.py tools/hooks tools/lib/atrapy      # wpisy fali
    .venv/bin/python tools/inwentarz_komentarzy.py --json .github                     # pełny tekst
    .venv/bin/python tools/inwentarz_komentarzy.py --dowod-fali                       # dowód fali, przez boatbox job
"""

MODUL: Final = "moduł"
PLIK: Final = "plik"
WYGENEROWANE: Final = "merge=wygenerowane"
OXLINT: Final = PurePosixPath("frontend/.oxlintrc.json")
OBCE: Final = f"ignorePatterns {OXLINT}"
BEZ_PARSERA: Final = "bez parsera"
BEZ_ZNACZNIKA: Final = "-"
SKROT: Final = 120
REGULA_KOMENTARZA: Final = "komentarz-"
REGULA_NAZWY: Final = "nazwa-"

KOMENTARZ: Final = "komentarz"
DOCSTRING: Final = "docstring"
DOCSTRING_JEDYNY: Final = "docstring-jedyna-instrukcja"
NAPIS: Final = "napis"

SHEBANG: Final = "shebang"
KODOWANIE: Final = "kodowanie"
KSZTALT_DYREKTYWY: Final = "kształt dyrektywy"
LINIA_KODOWANIA: Final = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")
DYREKTYWA: Final = re.compile(r"^[ \t]*(?:#+|//+|/\*+|\*+|<!--|;)?[ \t]*(?:@\w|[^\W\d][\w.-]*[ \t]*:)|\bnoqa\b", re.IGNORECASE | re.MULTILINE)

PYTHON: Final = frozenset({".py", ".pyi"})
DEKLARACJE_JS: Final = ("function_declaration", "class_declaration", "method_definition", "variable_declarator")
DEKLARACJE_TS: Final = (*DEKLARACJE_JS, "interface_declaration", "type_alias_declaration", "enum_declaration")
GITIGNORE: Final = frozenset({".gitignore", ".gitattributes", ".ignore"})
INI: Final = frozenset({".importlinter", ".cfg", ".ini"})
AST_GREP: Final = shutil.which("ast-grep", path=sysconfig.get_path("scripts")) or shutil.which("ast-grep")

PR: Final = "PR"
MAIN: Final = "MAIN"
NOC: Final = "NOC"
PO_MERGE: Final = "po merge'u"
NIE_MA_ZMIANY: Final = "brak zmiany od bazy"


@dataclass(frozen=True)
class Jezyk:
    nazwa: str
    forma: str
    deklaracje: tuple[str, ...] = ()


JEZYKI_AST_GREP: Final = {
    ".ts": Jezyk("typescript", "ts", DEKLARACJE_TS),
    ".tsx": Jezyk("tsx", "ts", DEKLARACJE_TS),
    ".js": Jezyk("javascript", "ts", DEKLARACJE_JS),
    ".mjs": Jezyk("javascript", "ts", DEKLARACJE_JS),
    ".cjs": Jezyk("javascript", "ts", DEKLARACJE_JS),
    ".css": Jezyk("css", "css"),
    ".html": Jezyk("html", "html"),
    ".yml": Jezyk("yaml", "yaml"),
    ".yaml": Jezyk("yaml", "yaml"),
    ".sh": Jezyk("bash", "powłoka", ("function_definition",)),
}


@dataclass(frozen=True)
class Komentarz:
    linia: int
    koniec: int
    tekst: str
    na_koncu_linii: bool


@dataclass(frozen=True)
class Zakres:
    poczatek: int
    koniec: int
    nazwa: str


@dataclass(frozen=True)
class Wpis:
    sciezka: str
    linia: int
    koniec: int
    forma: str
    wezel: str
    tekst: str
    znacznik: str | None

    def linia_wyjscia(self) -> str:
        miejsce = f"{self.sciezka}:{self.linia}" + (f"-{self.koniec}" if self.koniec != self.linia else "")
        poczatek = self.tekst.strip().split("\n", 1)[0].strip()
        skrot = poczatek if len(poczatek) <= SKROT else poczatek[: SKROT - 1] + "…"
        return " | ".join([miejsce, self.forma, self.wezel, self.znacznik or BEZ_ZNACZNIKA, skrot])

    def jako_json(self) -> str:
        return json.dumps(
            {
                "plik": self.sciezka,
                "linia": self.linia,
                "koniec": self.koniec,
                "forma": self.forma,
                "wezel": self.wezel,
                "znacznik": self.znacznik,
                "tekst": self.tekst,
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class Pliki:
    czytane: list[str]
    nieczytane: Counter[str]


class NieczytelnyPlik(Exception):
    pass


Znacznik = Callable[[Komentarz, list[str]], str | None]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=OPIS, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sciezki", nargs="*", help="Pliki albo katalogi względem korzenia (domyślnie całe repozytorium).")
    parser.add_argument("--json", action="store_true", help="Wpis jako linia JSON z pełnym tekstem.")
    parser.add_argument("--root", type=Path, default=repo.ROOT, help="Korzeń repozytorium (domyślnie ten checkout).")
    parser.add_argument(
        "--dowod-fali", nargs="?", const=repo.BASE, metavar="BAZA", help=f"Zamiast inwentarza: dowód fali z zakresu runu zmiany od BAZA (domyślnie {repo.BASE})."
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.dowod_fali is not None:
        if args.sciezki:
            parser.error("--dowod-fali bierze zmianę od bazy z gita, bez ścieżek")
        return dowod_fali(root, args.dowod_fali)
    wybrane = pliki(root, args.sciezki)
    try:
        wpisy = inwentarz(root, wybrane.czytane, AST_GREP)
    except NieczytelnyPlik as blad:
        print(f"INWENTARZ FAIL | {blad}")
        return 1
    for wpis in wpisy:
        print(wpis.jako_json() if args.json else wpis.linia_wyjscia())
    linii = sum(wpis.koniec - wpis.linia + 1 for wpis in wpisy)
    ze_znacznikiem = sum(wpis.znacznik is not None for wpis in wpisy)
    nieczytane = ", ".join(f"{przyczyna} {liczba}" for przyczyna, liczba in sorted(wybrane.nieczytane.items(), key=lambda para: (-para[1], para[0])))
    print(
        f"INWENTARZ OK | plików {len(wybrane.czytane)} | wpisów {len(wpisy)} (linii {linii}) | ze znacznikiem {ze_znacznikiem}"
        f" | nieczytane {wybrane.nieczytane.total()}" + (f": {nieczytane}" if nieczytane else "")
    )
    return 0


def pliki(root: Path, sciezki: Sequence[str]) -> Pliki:
    sledzone = [nazwa for nazwa in repo.git(root, "ls-files", "-z", "--", *sciezki).split("\0") if nazwa and (root / nazwa).is_file()]
    wygenerowane = set(filter(None, repo.git(root, "ls-files", "-z", "--", f":(attr:{WYGENEROWANE})").split("\0")))
    obce = _ignorowane_przez_oxlint(root)
    czytane: list[str] = []
    nieczytane: Counter[str] = Counter()
    for nazwa in sledzone:
        sciezka = PurePosixPath(nazwa)
        if nazwa in wygenerowane:
            nieczytane[WYGENEROWANE] += 1
        elif obce(sciezka):
            nieczytane[OBCE] += 1
        elif sciezka.suffix in JEZYKI_AST_GREP or _czytnik(sciezka, root / nazwa) is not None:
            czytane.append(nazwa)
        else:
            nieczytane[f"{BEZ_PARSERA} {sciezka.suffix or sciezka.name}"] += 1
    return Pliki(czytane, nieczytane)


def _ignorowane_przez_oxlint(root: Path) -> Callable[[PurePosixPath], bool]:
    konfiguracja = root / OXLINT
    wzorce = json.loads(konfiguracja.read_text(encoding="utf-8")).get("ignorePatterns", []) if konfiguracja.is_file() else []
    katalog = OXLINT.parent

    def obcy(sciezka: PurePosixPath) -> bool:
        return sciezka.is_relative_to(katalog) and any(sciezka.relative_to(katalog).full_match(wzorzec) for wzorzec in wzorce)

    return obcy


def inwentarz(root: Path, sciezki: Sequence[str], ast_grep: str | None) -> list[Wpis]:
    wpisy: list[Wpis] = []
    z_ast_grep: dict[str, Jezyk] = {}
    for sciezka in sciezki:
        nazwa = PurePosixPath(sciezka)
        if nazwa.suffix in JEZYKI_AST_GREP:
            z_ast_grep[sciezka] = JEZYKI_AST_GREP[nazwa.suffix]
            continue
        czytaj = _czytnik(nazwa, root / sciezka)
        if czytaj is not None:
            wpisy += czytaj(sciezka, _tekst(root, sciezka))
    wpisy += _z_ast_grep(root, z_ast_grep, ast_grep)
    return sorted(wpisy, key=lambda wpis: (wpis.sciezka, wpis.linia, wpis.forma))


def _czytnik(nazwa: PurePosixPath, plik: Path) -> Callable[[str, str], list[Wpis]] | None:
    if nazwa.suffix in PYTHON or (not nazwa.suffix and _shebang_pythona(plik)):
        return _python
    if nazwa.suffix == ".toml":
        return lambda sciezka, tekst: _przez_ciecie(sciezka, tekst, "toml", "#", tomllib.loads)
    if nazwa.suffix in INI or nazwa.name in INI:
        return lambda sciezka, tekst: _przez_ciecie(sciezka, tekst, "ini", "#;", _ini)
    if nazwa.name in GITIGNORE:
        return lambda sciezka, tekst: _liniowe(sciezka, tekst, "gitignore", _komentarz_gitignore)
    if nazwa.name.startswith("requirements") and nazwa.suffix == ".txt":
        return lambda sciezka, tekst: _liniowe(sciezka, tekst, "requirements", _komentarz_requirements)
    return None


def _shebang_pythona(plik: Path) -> bool:
    with plik.open("rb") as strumien:
        pierwsza = strumien.readline(200)
    return pierwsza.startswith(b"#!") and b"python" in pierwsza


def _tekst(root: Path, sciezka: str) -> str:
    try:
        return (root / sciezka).read_text(encoding="utf-8")
    except UnicodeDecodeError as blad:
        raise NieczytelnyPlik(f"{sciezka}: nie jest UTF-8 ({blad})") from blad


def _znacznik(komentarz: Komentarz, linie: list[str], *, shebang: bool = False, kodowanie: bool = False) -> str | None:
    if shebang and komentarz.linia == 1 and komentarz.tekst.startswith("#!"):
        return SHEBANG
    if kodowanie and komentarz.linia <= 2 and LINIA_KODOWANIA.match(linie[komentarz.linia - 1]):
        return KODOWANIE
    return KSZTALT_DYREKTYWY if DYREKTYWA.search(komentarz.tekst) else None


def _python(sciezka: str, tekst: str) -> list[Wpis]:
    try:
        drzewo = ast.parse(tekst, filename=sciezka)
        tokeny = list(tokenize.generate_tokens(io.StringIO(tekst).readline))
    except (SyntaxError, tokenize.TokenError) as blad:
        raise NieczytelnyPlik(f"{sciezka}: Python się nie parsuje ({blad})") from blad
    zakresy = list(_zakresy_pythona(drzewo))
    komentarze = list(_komentarze_pythona(tokeny))
    wpisy = _wpisy_komentarzy(sciezka, tekst, KOMENTARZ, komentarze, zakresy, lambda k, linie: _znacznik(k, linie, shebang=True, kodowanie=True), MODUL)
    for forma, wezel, instrukcja, napis in _napisy_pythona(drzewo):
        wpisy.append(Wpis(sciezka, instrukcja.lineno, instrukcja.end_lineno or instrukcja.lineno, forma, wezel, napis, None))
    return wpisy


def _komentarze_pythona(tokeny: list[tokenize.TokenInfo]) -> Iterator[Komentarz]:
    kod_w_linii: set[int] = set()
    for token in tokeny:
        if token.type == tokenize.COMMENT:
            yield Komentarz(token.start[0], token.end[0], token.string, token.start[0] in kod_w_linii)
        elif token.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
            kod_w_linii.update(range(token.start[0], token.end[0] + 1))


Definicja = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
DEFINICJE: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _zakresy_pythona(drzewo: ast.Module) -> Iterator[Zakres]:
    for wezel, nazwa in _definicje(drzewo, ""):
        poczatek = min([wezel.lineno, *(dekorator.lineno for dekorator in wezel.decorator_list)])
        yield Zakres(poczatek, wezel.end_lineno or wezel.lineno, nazwa)


def _definicje(wezel: ast.AST, przodek: str) -> Iterator[tuple[Definicja, str]]:
    for dziecko in ast.iter_child_nodes(wezel):
        if isinstance(dziecko, DEFINICJE):
            nazwa = f"{przodek}.{dziecko.name}" if przodek else dziecko.name
            yield dziecko, nazwa
            yield from _definicje(dziecko, nazwa)
        else:
            yield from _definicje(dziecko, przodek)


def _napisy_pythona(drzewo: ast.Module) -> Iterator[tuple[str, str, ast.stmt, str]]:
    wlasciciele: list[tuple[ast.Module | Definicja, str]] = [(drzewo, ""), *_definicje(drzewo, "")]
    for wlasciciel, nazwa in wlasciciele:
        for instrukcje in _listy_instrukcji(wlasciciel):
            for numer, instrukcja in enumerate(instrukcje):
                napis = _sam_napis(instrukcja)
                if napis is None:
                    continue
                if numer == 0 and instrukcje is wlasciciel.body:
                    jedyna = len(instrukcje) == 1 and isinstance(wlasciciel, DEFINICJE)
                    yield (DOCSTRING_JEDYNY if jedyna else DOCSTRING), nazwa or MODUL, instrukcja, napis
                else:
                    przypisane = _przypisane(instrukcje[numer - 1]) if numer else None
                    yield NAPIS, ".".join(filter(None, (nazwa, przypisane))) or MODUL, instrukcja, napis


def _sam_napis(instrukcja: ast.stmt) -> str | None:
    if isinstance(instrukcja, ast.Expr) and isinstance(instrukcja.value, ast.Constant) and isinstance(instrukcja.value.value, str):
        return instrukcja.value.value
    return None


def _listy_instrukcji(wlasciciel: ast.AST) -> Iterator[list[ast.stmt]]:
    kolejka: list[ast.AST] = [wlasciciel]
    while kolejka:
        wezel = kolejka.pop()
        for pole in ("body", "orelse", "finalbody", "handlers", "cases"):
            wartosc = getattr(wezel, pole, None)
            if not isinstance(wartosc, list):
                continue
            if wartosc and all(isinstance(element, ast.stmt) for element in wartosc):
                yield wartosc
            kolejka += [element for element in wartosc if isinstance(element, ast.AST) and not isinstance(element, DEFINICJE)]


def _przypisane(instrukcja: ast.stmt) -> str | None:
    if isinstance(instrukcja, ast.Assign):
        return ", ".join(ast.unparse(cel) for cel in instrukcja.targets)
    if isinstance(instrukcja, (ast.AnnAssign, ast.AugAssign)):
        return ast.unparse(instrukcja.target)
    return None


def _z_ast_grep(root: Path, sciezki: dict[str, Jezyk], ast_grep: str | None) -> list[Wpis]:
    if not sciezki:
        return []
    if ast_grep is None:
        raise NieczytelnyPlik(f"{min(sciezki)}: {odpalenia_ast_grep.INSTALL}")
    komentarze: dict[str, list[Komentarz]] = {sciezka: [] for sciezka in sciezki}
    nazwy: dict[str, list[tuple[int, int, str]]] = {sciezka: [] for sciezka in sciezki}
    teksty = {sciezka: _tekst(root, sciezka) for sciezka in sciezki}
    linie = {sciezka: tekst.split("\n") for sciezka, tekst in teksty.items()}
    lista = sorted(sciezki)
    for start in range(0, len(lista), odpalenia_ast_grep.PATHS_PER_SCAN):
        skan = potomne.run(
            [ast_grep, "scan", "--inline-rules", _reguly(set(sciezki.values())), "--json=stream", "--color=never", "--", *lista[start : start + odpalenia_ast_grep.PATHS_PER_SCAN]],
            cwd=root,
        )
        if skan.returncode != 0:
            raise NieczytelnyPlik(f"ast-grep scan zakończył się kodem {skan.returncode}: {skan.stderr.strip()}")
        for trafienie in odpalenia_ast_grep.json_stream(skan.stdout):
            sciezka = PurePath(trafienie["file"]).as_posix()
            poczatek, koniec = trafienie["range"]["start"]["line"] + 1, trafienie["range"]["end"]["line"] + 1
            if trafienie["ruleId"].startswith(REGULA_KOMENTARZA):
                tekst = trafienie["text"].replace("\r\n", "\n").rstrip("\r")
                na_koncu = not linie[sciezka][poczatek - 1].lstrip().startswith(tekst.split("\n", 1)[0])
                komentarze[sciezka].append(Komentarz(poczatek, koniec, tekst, na_koncu))
            elif trafienie["ruleId"].startswith(REGULA_NAZWY):
                nazwy[sciezka].append((poczatek, koniec, trafienie["metaVariables"]["single"]["NAZWA"]["text"]))
    wpisy: list[Wpis] = []
    for sciezka, jezyk in sciezki.items():
        zakresy = _yaml_zakresy(sciezka, teksty[sciezka]) if jezyk.nazwa == "yaml" else _zagniezdzone(nazwy[sciezka])
        powloka = jezyk.forma == JEZYKI_AST_GREP[".sh"].forma
        komentarze_pliku = sorted(komentarze[sciezka], key=lambda komentarz: komentarz.linia)
        wpisy += _wpisy_komentarzy(
            sciezka, teksty[sciezka], jezyk.forma, komentarze_pliku, zakresy, lambda k, linie_pliku: _znacznik(k, linie_pliku, shebang=powloka), PLIK
        )
    return wpisy


def _reguly(jezyki: Iterable[Jezyk]) -> str:
    reguly = []
    for nazwa in sorted({jezyk.nazwa for jezyk in jezyki}):
        reguly.append(f"id: {REGULA_KOMENTARZA}{nazwa}\nlanguage: {nazwa}\nrule:\n  kind: comment\n")
        deklaracje = {deklaracja for jezyk in jezyki if jezyk.nazwa == nazwa for deklaracja in jezyk.deklaracje}
        if deklaracje:
            rodzaje = "".join(f"    - kind: {rodzaj}\n" for rodzaj in sorted(deklaracje))
            reguly.append(f"id: {REGULA_NAZWY}{nazwa}\nlanguage: {nazwa}\nrule:\n  any:\n{rodzaje}  has:\n    field: name\n    pattern: $NAZWA\n")
    return "---\n".join(reguly)


def _zagniezdzone(nazwy: list[tuple[int, int, str]]) -> list[Zakres]:
    zakresy: list[Zakres] = []
    stos: list[Zakres] = []
    for poczatek, koniec, nazwa in sorted(nazwy, key=lambda trojka: (trojka[0], -trojka[1])):
        while stos and stos[-1].koniec < poczatek:
            stos.pop()
        zakres = Zakres(poczatek, koniec, f"{stos[-1].nazwa}.{nazwa}" if stos else nazwa)
        zakresy.append(zakres)
        stos.append(zakres)
    return zakresy


def _yaml_zakresy(sciezka: str, tekst: str) -> list[Zakres]:
    try:
        dokumenty = list(yaml.compose_all(tekst, Loader=yaml.SafeLoader))
    except yaml.YAMLError as blad:
        raise NieczytelnyPlik(f"{sciezka}: YAML się nie parsuje ({blad})") from blad
    zakresy: list[Zakres] = []

    def koniec(wezel: yaml.Node) -> int:
        if isinstance(wezel, yaml.MappingNode) and wezel.value:
            return max(koniec(wartosc) for _, wartosc in wezel.value)
        if isinstance(wezel, yaml.SequenceNode) and wezel.value:
            return max(koniec(element) for element in wezel.value)
        znak = wezel.end_mark
        return znak.line if znak.column == 0 and znak.line > wezel.start_mark.line else znak.line + 1

    def zbierz(wezel: yaml.Node, sciezka_wezla: str) -> None:
        if isinstance(wezel, yaml.MappingNode):
            for klucz, wartosc in wezel.value:
                nazwa = f"{sciezka_wezla}.{klucz.value}" if sciezka_wezla else str(klucz.value)
                zakresy.append(Zakres(klucz.start_mark.line + 1, koniec(wartosc), nazwa))
                zbierz(wartosc, nazwa)
        elif isinstance(wezel, yaml.SequenceNode):
            for numer, element in enumerate(wezel.value):
                nazwa = f"{sciezka_wezla}[{numer}]"
                zakresy.append(Zakres(element.start_mark.line + 1, koniec(element), nazwa))
                zbierz(element, nazwa)

    for dokument in dokumenty:
        if dokument is not None:
            zbierz(dokument, "")
    return zakresy


def _przez_ciecie(sciezka: str, tekst: str, forma: str, znaki: str, wczytaj: Callable[[str], object]) -> list[Wpis]:
    try:
        wzor = wczytaj(tekst)
    except (tomllib.TOMLDecodeError, configparser.Error) as blad:
        raise NieczytelnyPlik(f"{sciezka}: {forma} się nie parsuje ({blad})") from blad
    linie = tekst.split("\n")
    komentarze = []
    for numer, linia in enumerate(linie):
        for kolumna in (indeks for indeks, znak in enumerate(linia) if znak in znaki):
            na_koncu = bool(linia[:kolumna].strip())
            bez = [*linie[:numer], *([linia[:kolumna]] if na_koncu else []), *linie[numer + 1 :]]
            try:
                ten_sam = wczytaj("\n".join(bez)) == wzor
            except (tomllib.TOMLDecodeError, configparser.Error):
                ten_sam = False
            if ten_sam:
                komentarze.append(Komentarz(numer + 1, numer + 1, linia[kolumna:].rstrip("\r"), na_koncu))
                break
    return _wpisy_komentarzy(sciezka, tekst, forma, komentarze, [], _znacznik, PLIK)


def _ini(tekst: str) -> dict[str, dict[str, str]]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(tekst)
    return {sekcja: dict(parser[sekcja]) for sekcja in [parser.default_section, *parser.sections()]}


def _liniowe(sciezka: str, tekst: str, forma: str, komentarz: Callable[[str], int | None]) -> list[Wpis]:
    komentarze = []
    for numer, linia in enumerate(tekst.split("\n"), start=1):
        kolumna = komentarz(linia)
        if kolumna is not None:
            komentarze.append(Komentarz(numer, numer, linia[kolumna:].rstrip("\r"), bool(linia[:kolumna].strip())))
    return _wpisy_komentarzy(sciezka, tekst, forma, komentarze, [], _znacznik, PLIK)


def _komentarz_gitignore(linia: str) -> int | None:
    return 0 if linia.startswith("#") else None


def _komentarz_requirements(linia: str) -> int | None:
    trafienie = re.search(r"(?:^|\s)#", linia)
    return None if trafienie is None else trafienie.end() - 1


def _wpisy_komentarzy(
    sciezka: str, tekst: str, forma: str, komentarze: list[Komentarz], zakresy: list[Zakres], znacznik: Znacznik, poza: str
) -> list[Wpis]:
    linie = tekst.split("\n")
    w_komentarzu = {linia for komentarz in komentarze if not komentarz.na_koncu_linii for linia in range(komentarz.linia, komentarz.koniec + 1)}
    grupy: list[tuple[Komentarz, str | None]] = []
    for komentarz in komentarze:
        jego = znacznik(komentarz, linie)
        if grupy and _dolacza(grupy[-1], komentarz, jego, linie):
            poprzedni = grupy[-1][0]
            grupy[-1] = (replace(poprzedni, koniec=komentarz.koniec, tekst=f"{poprzedni.tekst}\n{komentarz.tekst}"), None)
        else:
            grupy.append((komentarz, jego))
    wpisy = []
    for komentarz, jego in grupy:
        cel = komentarz.linia if komentarz.na_koncu_linii else _nastepny_kod(linie, komentarz.koniec, w_komentarzu)
        wpisy.append(Wpis(sciezka, komentarz.linia, komentarz.koniec, forma, _wezel(zakresy, cel, poza), komentarz.tekst, jego))
    return wpisy


def _dolacza(grupa: tuple[Komentarz, str | None], komentarz: Komentarz, znacznik: str | None, linie: list[str]) -> bool:
    poprzedni, znacznik_poprzedniego = grupa
    return (
        znacznik is None
        and znacznik_poprzedniego is None
        and not poprzedni.na_koncu_linii
        and not komentarz.na_koncu_linii
        and komentarz.linia == poprzedni.koniec + 1
        and _wciecie(linie[komentarz.linia - 1]) == _wciecie(linie[poprzedni.linia - 1])
    )


def _wciecie(linia: str) -> int:
    return len(linia) - len(linia.lstrip())


def _nastepny_kod(linie: list[str], po: int, w_komentarzu: set[int]) -> int:
    for numer in range(po + 1, len(linie) + 1):
        if linie[numer - 1].strip() and numer not in w_komentarzu:
            return numer
    return po


def _wezel(zakresy: list[Zakres], cel: int, poza: str) -> str:
    od_celu = [zakres for zakres in zakresy if zakres.poczatek == cel]
    if od_celu:
        return max(od_celu, key=lambda zakres: zakres.koniec).nazwa
    obejmujace = [zakres for zakres in zakresy if zakres.poczatek <= cel <= zakres.koniec]
    return min(obejmujace, key=lambda zakres: zakres.koniec - zakres.poczatek).nazwa if obejmujace else poza


@dataclass(frozen=True)
class Jednostka:
    zdarzenie: str
    rodzaj: str
    nazwa: str
    wynik: str
    porazka: bool = False

    def linia_wyjscia(self) -> str:
        return f"{self.zdarzenie} | {self.rodzaj} | {self.nazwa} | {self.wynik}"


def dowod_fali(root: Path, baza: str) -> int:
    try:
        zmiana = changed_since(root, baza)
        poczatek = repo.merge_base(root, "HEAD", baza)
    except subprocess.CalledProcessError as blad:
        print(f"DOWÓD FALI FAIL | baza {baza}: git {blad.cmd[1]}: {(blad.stderr or '').strip() or f'kod {blad.returncode}'}")
        return 1
    if not zmiana:
        print(f"DOWÓD FALI FAIL | {NIE_MA_ZMIANY} {baza} ({poczatek[:10]})")
        return 1
    zakres = zakresy((Zdarzenie.PULL_REQUEST, Zdarzenie.PUSH, Zdarzenie.NOC), zmiana, root)
    pull_request, push, noc = zakres[Zdarzenie.PULL_REQUEST], zakres[Zdarzenie.PUSH], zakres[Zdarzenie.NOC]
    print(_praca_pull_requestu(pull_request))
    poza_wyborem = _pliki_poza_wyborem(pull_request, push)
    kroki_ci = _kroki_ci_poza_pull_requestem(pull_request, push)
    w_pull_requescie = {wybrany.krok for wybrany in pull_request.wybrane}
    podstawy = [wybrany.krok for wybrany in push.wybrane if wybrany.krok.verdict is None and wybrany.krok not in w_pull_requescie]
    nocne = [wybrany for wybrany in noc.wybrane if wybrany.krok not in w_pull_requescie]
    jednostki = [
        _pytest(root, poza_wyborem),
        *(Jednostka(MAIN, "krok CI", nazwa, PO_MERGE) for nazwa in kroki_ci),
        *(_podstawa(krok, zmiana) for krok in podstawy),
        *(Jednostka(NOC, _rodzaj(wybrany.krok), _nazwa_kroku(wybrany.krok), PO_MERGE) for wybrany in nocne),
        *(Jednostka(MAIN, "krok skilla", klucz, f"FAIL znalezienia: {blad}", porazka=True) for klucz, blad in push.bledy),
    ]
    for jednostka in jednostki:
        print(jednostka.linia_wyjscia())
    porazki = [f"{jednostka.rodzaj} {jednostka.nazwa}" for jednostka in jednostki if jednostka.porazka]
    stan = f"FAIL | {', '.join(porazki)}" if porazki else "OK"
    print(
        f"DOWÓD FALI {stan} | baza {poczatek[:10]} | zmiana {len(zmiana)} plików | lokalnie: pytest {len(poza_wyborem)} plików,"
        f" rozjazd modelu {sum(map(_ma_model, podstawy))} skilli | {PO_MERGE}: kroki CI {len(kroki_ci)}, podstawy {len(podstawy)}, noc {len(nocne)}"
    )
    return 1 if porazki else 0


def _praca_pull_requestu(pull_request: ZakresRunu) -> str:
    kroki_ci = sorted({nazwa for tor in pull_request.tory for nazwa in tor.kroki})
    kroki_skilli = ", ".join(_nazwa_kroku(wybrany.krok) for wybrany in pull_request.wybrane) or "brak"
    return (
        f"{PR} | Required CI pull requestu | {pull_request.zrodlo} | pytest {len(pull_request.pliki)} plików i węzłów,"
        f" kroki CI: {', '.join(kroki_ci) or 'brak'}, kroki skilli: {kroki_skilli}"
    )


def _pliki_poza_wyborem(pull_request: ZakresRunu, push: ZakresRunu) -> list[str]:
    wybrane = {plik for plik in pull_request.pliki if "::" not in plik}
    return [plik for plik in push.pliki if plik not in wybrane]


def _kroki_ci_poza_pull_requestem(pull_request: ZakresRunu, push: ZakresRunu) -> list[str]:
    w_pull_requescie = {(tor.nazwa, nazwa) for tor in pull_request.tory for nazwa in tor.kroki}
    return sorted({nazwa for tor in push.tory for nazwa in tor.kroki if (tor.nazwa, nazwa) not in w_pull_requescie})


def _pytest(root: Path, pliki_testow: list[str]) -> Jednostka:
    opis = f"{len(pliki_testow)} plików poza wyborem pull requestu"
    if not pliki_testow:
        return Jednostka(MAIN, "pytest", opis, "nic do uruchomienia")
    print(f"== pytest: {opis}", flush=True)
    krok = pytest_step(root, "pytest", tuple(pliki_testow))
    start = time.monotonic()
    wynik = potomne.run(krok.command, cwd=krok.cwd, env=environment(root))
    sekundy = time.monotonic() - start
    if wynik.returncode == 0:
        return Jednostka(MAIN, "pytest", opis, f"OK ({sekundy:.0f} s)")
    print("\n".join((wynik.stdout + wynik.stderr).rstrip().splitlines()[-OUTPUT_ON_FAILURE:]), flush=True)
    return Jednostka(MAIN, "pytest", opis, f"FAIL kod {wynik.returncode} ({sekundy:.0f} s)", porazka=True)


def _ma_model(krok: Step) -> bool:
    return (krok.skill / rozjazd_modelu.DEFINICJE).is_file()


def _pliki_modelu(krok: Step) -> frozenset[str]:
    definicje = f"{krok.folder}{rozjazd_modelu.DEFINICJE}"
    try:
        return frozenset({definicje, *rozjazd_modelu.definicje(krok.skill)})
    except ValueError:
        return frozenset({definicje})


def _podstawa(krok: Step, zmiana: frozenset[str]) -> Jednostka:
    nazwa = krok.skill.name
    if not _ma_model(krok):
        return Jednostka(MAIN, "podstawa", nazwa, PO_MERGE)
    rozjazd = rozjazd_modelu.rozjazd(krok.skill, krok.root)
    if rozjazd is None:
        return Jednostka(MAIN, "podstawa", nazwa, f"{PO_MERGE}, rozjazd modelu: brak")
    if zmiana & _pliki_modelu(krok):
        return Jednostka(MAIN, "podstawa", nazwa, f"{rozjazd_modelu.ROZJAZD}: {rozjazd}", porazka=True)
    return Jednostka(MAIN, "podstawa", nazwa, f"{PO_MERGE}, rozjazd modelu już na bazie, bo zmiana nie dotyka plików modelu: {rozjazd}")


def _rodzaj(krok: Step) -> str:
    return "podstawa" if krok.verdict is None else "skrypt mutacji"


def _nazwa_kroku(krok: Step) -> str:
    return f"{krok.skill.name}/{Path(krok.command[0]).name}"


if __name__ == "__main__":
    raise SystemExit(main())
