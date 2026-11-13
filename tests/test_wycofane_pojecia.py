"""Pojęcia wycofane przez ADR-y nie wracają do kodu, frontendu, skilli, dokumentacji ani zależności.

ADR, który wycofał pojęcie, jest zapisem historii. Linia z wycofanym pojęciem gdzie indziej zostaje tylko wtedy,
gdy plik historii (``tests/fixtures/historia_wycofanych_pojec.txt``) ma ją całą: także w starszym ADR-ze, którego
Status prowadzi odnośnikami do ADR-u, który pojęcie wycofał, bo takie ADR-y dalej się zmieniają, a nowe zdanie
opisuje to, co jest dziś. ``AGENTS.md``, ``CODING_STANDARDS.md`` i ``GLOSSARY.md`` nazywają wycofane pojęcia,
żeby ich zabronić, więc test ich nie czyta. Kod generowany z ``src`` (kontrakt, klient API, build Centrum)
sprawdza się w ``src``. CLI innego programu, nazwanego w kodzie (`` `uv` CLI``), nie jest wycofanym CLI procesów.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ADRS = ROOT / "docs" / "adr"
SCANNED = ("src", "frontend/src", ".agents/skills", "docs", "README.md", "requirements.txt", "pyproject.toml")
GENERATED = ("src/rozliczenia/centrum/static/", "frontend/src/api/generated/", "frontend/src/api/openapi.json")
TEXT = frozenset({".py", ".md", ".ts", ".tsx", ".txt", ".tla", ".cfg", ".toml"})
HISTORY = Path(__file__).resolve().parent / "fixtures" / "historia_wycofanych_pojec.txt"
OTHER_PROGRAMS = ("gh", "git", "npm", "uv")


@dataclass(frozen=True)
class Retired:
    pattern: re.Pattern[str]
    adr: str
    today: str


RETIRED = (
    Retired(
        re.compile("".join(f"(?<!`{program}` )" for program in OTHER_PROGRAMS) + r"\bCLI\b"),
        "0011",
        "procesy uruchamia Centrum rozliczeń, a testy i pomiary skrypt dla maszyn tools/uruchom_proces.py",
    ),
    Retired(
        re.compile(r"(?<![\w/-])[Tt]erminal(?!n)\w*"), "0011", "Komunikat ma trzy części i pokazuje go Centrum rozliczeń"
    ),
    Retired(
        re.compile(r"\bRich\b|^\s*(?:from|import)\s+rich\b|^\s*[\"']?rich\b"), "0011", "postęp pokazuje tylko Centrum rozliczeń"
    ),
    Retired(
        re.compile(r"(?<![\w/.-])run(?:_preparation)?\.py\b"),
        "0011",
        "procesy uruchamia Centrum rozliczeń, a testy i pomiary skrypt dla maszyn tools/uruchom_proces.py",
    ),
    Retired(
        re.compile(r"(?:Utwórz rozliczenia|Przygotuj plik zbiorczy|Centrum rozliczeń \(konsola\)|Zainstaluj skrót Centrum rozliczeń)\.cmd"),
        "0010",
        "tata pracuje tylko w Centrum rozliczeń; konsola to py -3 run_centrum.py, a skrót instaluje py -3 install_centrum_shortcut.py",
    ),
    Retired(
        re.compile(r"\b[Kk]onfiguracj\w* [Ww]ykonawc\w*"),
        "0032",
        "Lista Wykonawców w Ustawieniach Centrum (config/wykonawcy.yaml)",
    ),
    Retired(re.compile(r"\b[Uu]stawie\w* taty\b"), "0032", "Ustawienia Centrum"),
)


def _later_in_status(adr: Path) -> set[str]:
    """Późniejsze ADR-y, do których prowadzą odnośniki z sekcji Status."""

    status = adr.read_text(encoding="utf-8").split("## Status", 1)[-1].split("\n## ", 1)[0]
    return {number for number in re.findall(r"\((\d{4})-[^)]*\.md\)", status) if number > adr.name[:4]}


def _history_of(retiring: str, links: dict[str, set[str]]) -> set[str]:
    """ADR, który wycofał pojęcie, i ADR-y, których Status prowadzi do niego."""

    reaching = {retiring}
    while grown := {number for number, later in links.items() if later & reaching} - reaching:
        reaching |= grown
    return reaching


def _scanned_files() -> list[Path]:
    paths = [ROOT / name for name in SCANNED]
    return sorted(
        file
        for path in paths
        for file in (path.rglob("*") if path.is_dir() else [path])
        if file.suffix in TEXT
        and not any(part.endswith(".egg-info") or part == "__pycache__" for part in file.parts)
        and not file.relative_to(ROOT).as_posix().startswith(GENERATED)
    )


def _history() -> set[tuple[str, str]]:
    """Plik i cała linia (bez wcięcia) z każdego wiersza pliku historii."""

    entries = set()
    for row in HISTORY.read_text(encoding="utf-8").splitlines():
        if row and not row.startswith("#"):
            name, _, line = row.partition("\t")
            entries.add((name, line))
    return entries


def test_wycofane_pojecia_nie_wracaja() -> None:
    links = {adr.name[:4]: _later_in_status(adr) for adr in ADRS.glob("[0-9][0-9][0-9][0-9]-*.md")}
    history = {retired.adr: _history_of(retired.adr, links) for retired in RETIRED}
    allowed, found, used = _history(), [], set()
    for file in _scanned_files():
        name = file.relative_to(ROOT).as_posix()
        adr = file.name[:4] if file.parent == ADRS else None
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            for retired in RETIRED:
                match = retired.pattern.search(line)
                if match is None or adr == retired.adr:
                    continue
                if (name, line.strip()) in allowed and (adr is None or adr in history[retired.adr]):
                    used.add((name, line.strip()))
                else:
                    term = match.group().strip(" \"'")
                    found.append(f"{name}:{number}: „{term}” wycofał ADR {retired.adr}; dziś {retired.today}")
    found += [f"{HISTORY.name}: {name} nie ma już linii „{line}”, usuń wiersz" for name, line in sorted(allowed - used)]

    assert not found, "\n".join(
        [
            *found,
            "Opisz to, co jest dziś, także w nowym zdaniu starszego ADR-u. Linię o historii wpisz całą do "
            f"tests/fixtures/{HISTORY.name} pod jej powodem, a starszy ADR połącz w Statusie odnośnikiem z ADR-em, "
            "który wycofał pojęcie.",
        ]
    )
