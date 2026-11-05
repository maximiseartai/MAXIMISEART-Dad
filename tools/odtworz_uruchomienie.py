"""Odtwarza Uruchomienie z pliku Logów (dysk albo Archiwum Logów okresu) na Macu i drukuje pierwszą różnicę; użyj, by powtórzyć run taty.

Narzędzie odtwarzania Uruchomienia procesu z Logów Uruchomienia (#847, spec #837).

Użycie (z katalogu repozytorium):

    .venv/bin/python tools/odtworz_uruchomienie.py LOGI [--konfiguracja FOLDER] [--na-tym-drzewie]
        [--efenix-dzis RRRR-MM-DD] [--zachowaj FOLDER]

``LOGI`` to plik Logów z dysku taty (``.json``) albo z Archiwum Logów okresu (``.json.gz``), albo odnośnik do pliku w
Archiwum z komentarza Logów w issue okresu (``https://github.com/<repo>/releases/download/logi-<okres>/<plik>.json.gz``),
który narzędzie pobiera przez ``gh release download`` (tylko odczyt).

Bez ``--na-tym-drzewie`` narzędzie robi odłączoną kopię commitu z Logów (``tool.commit``) w katalogu tymczasowym
(``git worktree add``, znika po końcu) i uruchamia w niej jej własne narzędzie odtwarzania interpreterem tego
checkoutu: kod procesu, Kopia wejścia i porównanie są z tego samego commitu, a biblioteki z ``.venv`` tego checkoutu.
Gdy ``requirements.txt`` commitu jest inny, raport mówi to jako granicę. Commit sprzed tego narzędzia, commit, którego
nie ma w repozytorium, i Logi bez commitu to ``NIE DA SIĘ ODTWORZYĆ`` z podpowiedzią ``--na-tym-drzewie``, które
odtwarza na kodzie tego checkoutu, np. żeby sprawdzić, czy poprawka zmienia wynik.

Odtworzenie (``tools/lib/odtworzenie.py``) buduje pliki wejścia z Kopii wejścia (w miejscu ``ADRES`` i numeru Orange
wartości syntetyczne), uruchamia ten sam proces w tym samym trybie przez ten sam rdzeń co Centrum, a Wycenę w efenix
na Atrapie efenix z odczytów stron w Logach (``tools/lib/atrapa_z_logow.py``), i porównuje Logi odtworzenia z Logami.
``--konfiguracja``: folder z ``worker_mapping.yaml`` i Wzorcami (bez parametru ``config/`` głównego checkoutu), bo
Logi ich nie niosą; potrzebują go Przygotowanie pliku zbiorczego i Przebieg rozliczeń. ``--efenix-dzis``: dzisiejszy
dzień kalendarza Atrapy (bez parametru dzień startu Uruchomienia). ``--zachowaj``: folder, w którym zostają pliki wejścia,
pliki, które zapisał proces, i ``odtworzone-logi.json``; bez niego wszystko znika po końcu.

Na stdout trafia raport: w pierwszej linii ``ODTWORZENIE ZGODNE``, ``ODTWORZENIE RÓŻNE`` albo ``NIE DA SIĘ
ODTWORZYĆ: <powód>``, potem Uruchomienie, kod, pierwsza różnica (pole Logów, wartość w Logach i w odtworzeniu),
porównane części i granice Logów, które mogą tłumaczyć różnicę. Kod wyjścia: 0 zgodne, 1 różne, 3 nie da się
odtworzyć, 2 błąd parametrów albo pliku. Narzędzie nie pisze nic do repozytorium (poza chwilową kopią commitu) ani do
Skrzynki Zgłoszeń.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import NoReturn
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import potomne

ROOT = Path(__file__).resolve().parents[1]
TOOL = Path("tools") / "odtworz_uruchomienie.py"
ARCHIVE_HOST = "github.com"
_IMPOSSIBLE = 3
_USAGE = 2


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(_USAGE, f"{self.prog}: błąd: {message}\n")


class _Failure(Exception):
    """Pliku Logów nie da się wczytać ani pobrać: kod wyjścia 2 z opisem na stderr."""


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "logi",
        help="Plik Logów (.json, .json.gz) albo odnośnik do pliku w Archiwum Logów okresu.",
    )
    parser.add_argument(
        "--konfiguracja",
        type=Path,
        default=_main_configuration(),
        help="Folder z Konfiguracją wykonawców i Wzorcami; domyślnie config/ głównego checkoutu.",
    )
    parser.add_argument(
        "--na-tym-drzewie",
        action="store_true",
        help="Odtwarza na kodzie tego checkoutu, a nie commitu z Logów.",
    )
    parser.add_argument(
        "--efenix-dzis",
        type=date.fromisoformat,
        default=None,
        help="Dzisiejszy dzień Atrapy efenix (RRRR-MM-DD).",
    )
    parser.add_argument(
        "--zachowaj",
        type=Path,
        default=None,
        help="Folder na pliki odtworzenia (musi być pusty).",
    )
    parser.add_argument("--opis-kodu", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--granica", action="append", default=[], help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="odtworzenie-") as temporary:
        try:
            logs = _logs_file(args.logi, Path(temporary))
            text = _text(logs)
        except _Failure as failure:
            print(f"BŁĄD: {failure}", file=sys.stderr)
            return _USAGE
        if args.na_tym_drzewie:
            return _here(text, args, Path(temporary))
        return _at_commit(logs, text, args)


def _logs_file(source: str, temporary: Path) -> Path:
    """Plik Logów z dysku albo pobrany z Archiwum Logów okresu (``gh release download``) do ``temporary``."""

    parts = urllib.parse.urlsplit(source)
    if parts.scheme not in ("http", "https"):
        path = Path(source)
        if not path.is_file():
            raise _Failure(f"nie ma pliku Logów {path}")
        return path
    segments = [urllib.parse.unquote(segment) for segment in parts.path.split("/")]
    if parts.netloc != ARCHIVE_HOST or len(segments) != 7 or segments[0] or segments[3:5] != ["releases", "download"]:
        raise _Failure(
            f"to nie jest odnośnik do pliku w Archiwum Logów okresu (https://{ARCHIVE_HOST}/<właściciel>/<repozytorium>"
            f"/releases/download/<tag>/<plik>): {source}"
        )
    owner, repository, tag, name = segments[1], segments[2], segments[5], segments[6]
    gh = shutil.which("gh")
    if gh is None:
        raise _Failure(
            "pobranie z Archiwum Logów okresu potrzebuje gh (GitHub CLI) zalogowanego do repozytorium Zgłoszeń"
        )
    folder = temporary / "archiwum"
    folder.mkdir()
    command = [
        gh,
        "release",
        "download",
        tag,
        "--repo",
        f"{owner}/{repository}",
        "--pattern",
        name,
        "--dir",
        str(folder),
    ]
    done = potomne.run(command, cwd=temporary, timeout=300)
    downloaded = folder / name
    if done.returncode or not downloaded.is_file():
        raise _Failure(f"gh release download nie pobrał {name} z {owner}/{repository} {tag}: {done.stderr.strip()}")
    return downloaded


def _text(path: Path) -> str:
    """Tekst pliku Logów; plik ``.gz`` z Archiwum Logów okresu po rozpakowaniu."""

    try:
        data = path.read_bytes()
        return (gzip.decompress(data) if path.suffix == ".gz" else data).decode("utf-8")
    except (OSError, EOFError, UnicodeDecodeError) as error:  # gzip.BadGzipFile to też OSError
        raise _Failure(f"nie da się odczytać pliku Logów {path.name}: {type(error).__name__}") from error


def _main_configuration() -> Path | None:
    """``config/`` głównego checkoutu (z Wzorcami Maksa), wspólnego dla każdego worktree tego repozytorium."""

    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    folder = Path(common).parent / "config"
    return folder if folder.is_dir() else None


def _commit_of(text: str) -> str | None:
    """Commit narzędzia z Logów, bez modelu Logów tego kodu: Logi mogą być z innej wersji schematu."""

    try:
        tool = json.loads(text).get("tool")
    except (json.JSONDecodeError, AttributeError):
        return None
    commit = tool.get("commit") if isinstance(tool, dict) else None
    return commit if isinstance(commit, str) and commit else None


def _impossible(reason: str) -> int:
    print(f"NIE DA SIĘ ODTWORZYĆ: {reason}")
    return _IMPOSSIBLE


def _at_commit(logs: Path, text: str, args: argparse.Namespace) -> int:
    """Odtworzenie na kopii commitu z Logów jej własnym narzędziem odtwarzania; jego raport i kod wyjścia."""

    commit = _commit_of(text)
    if commit is None:
        return _impossible("Logi nie mają commitu narzędzia; odtwórz na kodzie tego checkoutu (--na-tym-drzewie)")
    known = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if known.returncode:
        return _impossible(
            f"commitu {commit} nie ma w tym repozytorium; pobierz go (git fetch origin) albo odtwórz na kodzie tego "
            "checkoutu (--na-tym-drzewie)"
        )
    with potomne.commit_copy(ROOT, commit) as tree:
        if not (tree / TOOL).is_file():
            return _impossible(
                f"commit {commit} jest sprzed narzędzia odtwarzania (#847); odtwórz na kodzie tego checkoutu "
                "(--na-tym-drzewie)"
            )
        command = [
            sys.executable,
            str(tree / TOOL),
            str(logs.resolve()),
            "--na-tym-drzewie",
            "--opis-kodu",
            f"commit {commit} z Logów, w osobnym drzewie",
        ]
        if args.konfiguracja is not None:
            command += ["--konfiguracja", str(args.konfiguracja.resolve())]
        if args.efenix_dzis is not None:
            command += ["--efenix-dzis", args.efenix_dzis.isoformat()]
        if args.zachowaj is not None:
            command += ["--zachowaj", str(args.zachowaj.resolve())]
        if (tree / "requirements.txt").read_bytes() != (ROOT / "requirements.txt").read_bytes():
            command += [
                "--granica",
                "requirements.txt commitu różni się od tego checkoutu: odtworzenie biegło bibliotekami .venv tego checkoutu",
            ]
        done = potomne.run(command, cwd=tree)
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    return done.returncode


def _here(text: str, args: argparse.Namespace, temporary: Path) -> int:
    """Odtworzenie na kodzie tego drzewa; raport na stdout i kod wyjścia wyniku."""

    import rozliczenia
    from pydantic import ValidationError

    if not Path(rozliczenia.__file__).resolve().is_relative_to(ROOT / "src"):
        print(
            f"BŁĄD: rozliczenia z {rozliczenia.__file__}, a nie z {ROOT / 'src'}",
            file=sys.stderr,
        )
        return _USAGE

    from rozliczenia.centrum.run_logs import RunLog

    import odtworzenie

    try:
        record = RunLog.model_validate_json(text)
    except ValidationError as error:
        return _impossible(
            f"plik nie jest Logami Uruchomienia w schemacie tego kodu ({error.error_count()} błędów schematu)"
        )
    work = temporary / "odtworzenie"
    if args.zachowaj is not None:
        if args.zachowaj.exists() and any(args.zachowaj.iterdir()):
            print(f"BŁĄD: folder {args.zachowaj} nie jest pusty", file=sys.stderr)
            return _USAGE
        work = args.zachowaj
    work.mkdir(parents=True, exist_ok=True)
    report = odtworzenie.replay(
        record,
        work=work,
        configuration=args.konfiguracja,
        efenix_today=args.efenix_dzis,
    )
    extra = tuple(odtworzenie.Limit(text) for text in args.granica)
    report = odtworzenie.Report(report.verdict, report.difference, report.limits + extra, report.replayed)
    if report.replayed is not None:
        (work / "odtworzone-logi.json").write_text(report.replayed.text, encoding="utf-8", newline="")
    code = args.opis_kodu or f"to drzewo ({ROOT}); Logi są z commitu {record.tool.commit or 'nieznanego'}"
    sys.stdout.write("\n".join(report.lines(record, code)) + "\n")
    return report.verdict.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
