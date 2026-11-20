"""Dokumenty z regułami łamią linie tylko na końcu zdania: zmiana jednego słowa zmienia jedną linię, nie cały akapit.

Frontmatter skilla (YAML między liniami ``---`` na początku pliku) to nie proza, więc go pomija.
``README.md`` jest jeszcze łamany twardo, więc dołączy do ``DOCUMENTS`` po przeformatowaniu.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("AGENTS.md", "CODING_STANDARDS.md", "docs/agents/pr-i-ci.md", "docs/agents/issue-tracker.md", "docs/agents/skrzynka-zgloszen.md", "docs/agents/komputer-taty.md", ".agents/skills/przeglad/SKILL.md", ".agents/skills/przeglad/recenzent.md", ".agents/skills/przeglad/autor.md", ".agents/skills/przeglad/korzen.md", ".agents/skills/przeglad/rundy.md", ".agents/skills/przeglad/porazka-adr.md", ".agents/skills/boat/SKILL.md", "docs/agents/skille.md", "GLOSSARY.md")
FENCE = "```"
NOT_PROSE = re.compile(r"\s*(?:#+\s|\||```)")
LIST_ITEM = re.compile(r"\s*(?:-|\d+\.)\s")
SENTENCE_END = re.compile(r"[.!?][)”\"*]*$")


def _prose(line: str) -> bool:
    return bool(line.strip()) and not NOT_PROSE.match(line)


def _lines_broken_mid_sentence(text: str) -> Iterator[int]:
    """Numery linii prozy, które kończą się w środku zdania, choć następna linia ciągnie ten sam akapit."""

    lines = text.splitlines()
    fenced = False
    front_matter = lines[:1] == ["---"]
    for number, (line, following) in enumerate(zip(lines, [*lines[1:], ""], strict=True), start=1):
        if front_matter:
            front_matter = number == 1 or line != "---"
        elif line.lstrip().startswith(FENCE):
            fenced = not fenced
        elif (
            not fenced
            and _prose(line)
            and _prose(following)
            and not LIST_ITEM.match(following)
            and not SENTENCE_END.search(line.rstrip())
        ):
            yield number


def test_dokument_regul_lamie_linie_tylko_na_koncu_zdania() -> None:
    broken = [
        f"{name}:{number}: linia kończy się w środku zdania, a linia {number + 1} ciągnie ten sam akapit"
        for name in DOCUMENTS
        for number in _lines_broken_mid_sentence((ROOT / name).read_text(encoding="utf-8"))
    ]

    assert not broken, "\n".join(
        [
            *broken,
            "Łam linię tylko na końcu zdania: dołącz następną linię do tej i zacznij nową linię dopiero od nowego "
            "zdania. Nowe zdanie elementu listy wcinaj o szerokość jego znacznika (dwie spacje dla „- ”).",
        ]
    )


def test_sprawdzenie_pomija_kod_tabele_i_naglowki_a_wskazuje_lamanie_w_srodku_zdania() -> None:
    document = "\n".join(
        [
            "# Nagłówek bez kropki",
            "Akapit łamany",
            "w środku zdania.",
            "Lista:",
            "- Element listy łamany",
            "  w środku zdania.",
            "  Drugie zdanie w nowej linii.",
            "- Element bez kropki",
            "1. Element numerowany bez kropki",
            "",
            "Akapit łamany przed numerem PR",
            "#285 ciągnie to samo zdanie.",
            "Uruchom:",
            "```",
            "polecenie --flaga",
            "  --druga-flaga",
            "```",
            "Tekst przed nagłówkiem",
            "## Nagłówek",
            "| kolumna | bez kropki |",
            "| --- | --- |",
            "",
            "Komunikat brzmi „Plik jest niedostępny.”",
            "(Całe zdanie w nawiasie.)",
            'Napisz "gotowe."',
            "**Pogrubione zdanie.**",
            "Zdanie z wykrzyknikiem!",
            "Zdanie z pytaniem?",
            "Ostatnia linia bez kropki",
        ]
    )

    assert list(_lines_broken_mid_sentence(document)) == [2, 5, 11]


def test_sprawdzenie_pomija_frontmatter_skilla_a_sprawdza_proze_po_nim() -> None:
    document = "\n".join(
        [
            "---",
            "name: skill",
            "description: Opis",
            "---",
            "",
            "Akapit łamany",
            "w środku zdania.",
        ]
    )

    assert list(_lines_broken_mid_sentence(document)) == [6]


BUDZET_BAJTOW = {"CODING_STANDARDS.md": 45_000, ".agents/skills/przeglad": 41_000}


def _pliki_w_repo(nazwa: str) -> list[Path]:
    listed = subprocess.run(["git", "ls-files", "-z", "--", nazwa], cwd=ROOT, capture_output=True, check=True)
    return [ROOT / plik for plik in listed.stdout.decode("utf-8").split("\0") if plik]


def _bajty(pliki: list[Path]) -> int:
    return sum(len(plik.read_bytes().replace(b"\r\n", b"\n")) for plik in pliki)


def test_reguly_mieszcza_sie_w_budzecie_bajtow() -> None:
    ponad = [
        f"{nazwa}: {rozmiar} B, budżet {budzet} B (+{rozmiar - budzet} B)"
        for nazwa, budzet in BUDZET_BAJTOW.items()
        if (rozmiar := _bajty(_pliki_w_repo(nazwa))) > budzet
    ]

    assert not ponad, "\n".join(
        [
            *ponad,
            "Każdy agent czyta te reguły przed każdą zmianą, więc nowa treść wchodzi tylko w miejsce starej: zanim dopiszesz "
            "wiersz albo zdanie, usuń wiersz tabeli reguł, którego treść mówi już komunikat strażnika (asercja testu, msg "
            "banned-api, message reguły ast-grep), albo skróć wiersz do wiedzy, której komunikat nie ma. Budżet w "
            "BUDZET_BAJTOW podnosi tylko PR, który w opisie mówi, czego nie dało się usunąć ani przenieść do komunikatu.",
        ]
    )


def test_budzet_liczy_plik_z_checkoutu_windows_tak_samo_jak_z_repo(tmp_path: Path) -> None:
    tekst = "| Rule | Guard |\n|---|---|\n| Wiersz. | test |\n"
    lf = tmp_path / "lf.md"
    crlf = tmp_path / "crlf.md"
    lf.write_bytes(tekst.encode("utf-8"))
    crlf.write_bytes(tekst.replace("\n", "\r\n").encode("utf-8"))

    assert _bajty([crlf]) == _bajty([lf])
