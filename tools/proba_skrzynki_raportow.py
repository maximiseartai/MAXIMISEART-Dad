"""Sprawdza port IMAP na prawdziwej skrzynce raportów taty tylko do odczytu, wynik jedną linią; uruchom przed Wydaniem z Wpisaniem raportów.

Narzędzie dla Maksa, poza CI (Granica 4 speca #1224, ADR 0028). Port IMAP Skrzynki raportów
(``rozliczenia.worker_report_inbox.ImapInbox``) CI sprawdza tylko na ``AtrapaImap``, więc prawdziwego Gmaila sprawdza
ta próba: tym samym portem, z tym samym plikiem dostępu ``config/skrzynka-raportow.txt`` (linia 1 adres skrzynki,
linia 2 hasło aplikacji Google) i Listą Wykonawców ``config/wykonawcy.yaml``, co Wpisanie raportów.
Po kolei:

1. czyta adresy z Listy Wykonawców przez Ustawienia Centrum bez zapisu (``read_snapshot``), jak Wpisanie raportów:
   przy złym pliku ostatnia dobra lista, a bez niej albo bez żadnego adresu próba nie przechodzi;
2. czyta flagi IMAP każdego maila z dni od dnia przed ``--od`` w folderze, który czyta port (``\\All``, a bez niego
   ``INBOX``), i liczy maile ze słowem ``raport`` w temacie w tym folderze i w ``INBOX`` (``ImapInbox.survey``);
3. czyta Raporty wykonawców od ``--od`` portem (``mails_since``) i przepuszcza je przez rdzeń raportów
   (``enter_reports``) bez zleceń INTERMAX, więc każdy Wpis raportu z rozpoznanego Raportu to problem nieznanego numeru;
4. czyta flagi jeszcze raz i porównuje je z pierwszym odczytem: mail, którego flagi są inne albo którego nie ma w
   drugim odczycie, to mail ze zmienionymi flagami. Port oddaje flagi każdego wyszukanego maila albo błąd
   ``UnexpectedReply``, a próba sprawdza jeszcze, że w każdym odczycie liczba maili z flagami równa się liczbie
   wyszukanych. Port oddaje UID tylko w odczycie flag, więc mail, który przyszedł po pierwszym odczycie flag, próba
   poznaje po liczbie: przeczytanych i pominiętych maili jest więcej niż maili ze słowem ``raport`` w temacie w
   pierwszym odczycie, a flag takiego maila nikt nie porównał.

Skrzynki nie zmienia: port otwiera folder przez ``EXAMINE`` i pobiera tematy, treści i flagi przez ``BODY.PEEK`` i
``FETCH (FLAGS)``, bez ``SELECT`` i ``STORE``.

Wynik (stdout) to same liczby, bez treści maili, tematów, adresów, loginów i numerów zleceń, i same znaki ASCII (polskie
słowa bez polskich liter), bo konsola Windows przy przekierowaniu wyjścia koduje w cp1252, który nie ma ``ł`` ani ``ż``:

    SKRZYNKA | folder_wszystkich=<n> | odebrane=<n> | poza_odebranymi=<n>
    MAILE | przeczytane=<n> | pominiete=<n> | raporty=<n> | wpisy=<n> | polskie_znaki=<n> | zepsute_znaki=<n>
    PROBLEMY | <rodzaj problemu>=<n> | …      (albo PROBLEMY | brak)
    FLAGI | sprawdzone=<n> | zmienione=<n>
    PROBA IMAP OK | maile=<n> | flagi bez zmian

``SKRZYNKA`` liczy maile ze słowem ``raport`` w temacie: ``poza_odebranymi`` to ile ich więcej jest w folderze, który
czyta port, niż w ``INBOX``. ``MAILE``: ``przeczytane`` to maile, które oddał port, ``pominiete`` te, których nie umiał
rozebrać, ``raporty`` maile z tematem ``Raport dd.mm.rrrr`` z dniem od ``--od``, ``wpisy`` ich Wpisy raportu,
``polskie_znaki`` maile z polską literą w temacie albo treści, a ``zepsute_znaki`` maile ze znakiem zastępczym U+FFFD
albo literą ``Ã``, ``Ä``, ``Å``, ``Ă``, ``Ĺ``, którą daje polska litera z UTF-8 przeczytana w zestawie jednobajtowym.
``PROBLEMY`` liczy problemy rdzenia według rodzaju (nazwa typu z ``rozliczenia.worker_reports``).

Ostatnia linia to ``PROBA IMAP OK | …`` (kod 0) tylko wtedy, gdy rdzeń rozpoznał co najmniej jeden Raport wykonawcy od
adresu z pliku adresów z Wpisem raportu z ``tak`` albo ``nie``, a inaczej ``PROBA IMAP FAIL | <powód>`` (kod 1): brak
albo zła treść pliku dostępu, pliku adresów albo Konfiguracji wykonawców, odrzucone hasło, skrzynka niedostępna (nazwa
typu błędu), brak rozpoznanego Raportu wykonawcy, zepsute znaki, flagi nieodczytane dla części wyszukanych maili, mail,
który przyszedł w trakcie próby, albo flagi, które zmieniły się między odczytami. Powód ``brak rozpoznanego Raportu wykonawcy`` niesie liczby: maile ze
słowem ``raport`` w temacie (``maile_z_raport``), Raporty od adresów spoza pliku adresów (``nieznani_nadawcy``), maile,
których temat nie jest ``Raport dd.mm.rrrr`` z dniem od ``--od`` (``nierozpoznane_tematy``), Raporty od Wykonawców bez
Wpisu (``raporty_bez_wpisow``) i Wpisy bez ``tak`` ani ``nie`` (``wpisy_bez_tak_nie``). Zepsute znaki daje też
zagraniczne nazwisko z ``Å`` albo ``Ä`` w mailu ze słowem ``raport``: wtedy Maks sprawdza te maile ręcznie. Hasła nie ma
w wyniku, wyjątkach ani żadnym pliku: zna je tylko port.

Uruchomienie u taty, w klonie narzędzia z plikami w ``config/`` (Windows: ``py -3``), a ostatnią linię Maks wpisuje w
komentarzu #1234:

    .venv/bin/python tools/proba_skrzynki_raportow.py [--od RRRR-MM-DD] [--config <folder config>]
        [--przeglad <plik> [--nadpisz]]

Przegląd Wpisów (``--przeglad PLIK``, ścieżka prawdziwej skrzynki skilla ``verify-centrum-rozliczen``, funkcja
``wpisanie-raportow``): stdout zostaje ten sam, a ``PLIK`` dostaje dla każdego przeczytanego Raportu wykonawcy od
Wykonawcy z pliku adresów i każdego jego maila z nierozpoznanym tematem chwilę przyjścia, Wykonawcę jako alias
(``Wykonawca A``, ``B``, … w kolejności pierwszego maila w pliku, bez loginu i adresu), temat, dzień z tematu albo
powód tematu, treść tak, jak ją oddał port (końce linii jako ``\n``), i Wpisy raportu z rdzenia: numer, ``tak``/``nie``
albo powód braku i czynności. Raport z dniem spoza okna próby (od ``--od`` do dziś), który rdzeń pomija, plik pokazuje
z Wpisami i dopiskiem, a Raporty od adresów spoza pliku adresów liczy tylko stdout. Na końcu plik zbiera numery, które
mają kilka Wpisów jednego Wykonawcy z jednego dnia. Plik powstaje zaraz po odczycie maili, także gdy próba potem nie
przechodzi.

**Plik przeglądu zawiera prawdziwe maile Wykonawców taty** (nazwiska, adresy i numery zleceń klientów w treści).
Trzymaj go w ``~/.t3/notes/<run>/`` na maszynie z plikiem dostępu, nie w repozytorium i nie w ``/tmp``. Jego treść nie
trafia do czatu, issue ani PR: wolno z niego wypisać tylko zbiorcze wnioski i liczby, a każdy znaleziony błąd dostaje
test z syntetyczną postacią. Narzędzie tworzy plik z prawami ``0600``, odmawia ścieżki w repozytorium Git, także w
klonie narzędzia (folder pliku albo folder nad nim ma ``.git``, po dowiązaniach) i istniejącego pliku bez
``--nadpisz``: odmowa to ``PROBA IMAP FAIL | <powód>`` bez łączenia ze skrzynką.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import imaplib
import os
from pathlib import Path
import re
import sys
from typing import Final, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rozliczenia import tool_files
from rozliczenia.centrum.settings.files import usable
from rozliczenia.centrum.settings.owner import read_snapshot
from rozliczenia.worker_report_inbox import (
    INBOX_ACCESS_FILE,
    ImapInbox,
    InboxSurvey,
    InboxUnreachable,
    PasswordRejected,
)
from rozliczenia.worker_reports import (
    Login,
    OrderNumber,
    OwnEntries,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    ReportEntry,
    ReportInputs,
    ReportMail,
    ReportsOutcome,
    Verdict,
    VerdictFault,
    Window,
    WorkerAddresses,
    enter_reports,
)

DAYS_BACK: Final = 14
"""Domyślne ``--od``: tyle dni przed dziś, żeby w skrzynce były Raporty z kilku dni roboczych."""
OK: Final = "PROBA IMAP OK"
FAIL: Final = "PROBA IMAP FAIL"
_POLISH: Final = re.compile("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
_BROKEN: Final = re.compile("[\ufffdÃÄÅĂĹ]")


class ProbeFailed(Exception):
    """Próba nie przeszła; ``reason`` to powód z ostatniej linii, bez hasła, adresu i treści maila."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


def probe(inbox: ImapInbox, config: Path, since: date, today: date, review: ReviewFile | None = None) -> list[str]:
    """Linie wyniku próby z ostatnią ``PROBA IMAP OK`` albo ``PROBA IMAP FAIL``; ``ProbeFailed``, gdy próba nie doszła
    do liczb. ``review`` dostaje przeczytane maile zaraz po ich odczycie."""

    match inbox.access():
        case "missing":
            raise ProbeFailed(f"brak pliku dostepu config/{INBOX_ACCESS_FILE} albo jego adresu lub hasla")
        case "unreadable":
            raise ProbeFailed(f"nieczytelny plik dostepu config/{INBOX_ACCESS_FILE}")
        case "ready":
            pass
    workers = usable(read_snapshot(config).workers)
    if workers is None:
        raise ProbeFailed("Lista Wykonawcow ma zle ustawienie albo nie da sie jej teraz odczytac")
    addresses = workers.addresses()
    if not addresses.logins:
        raise ProbeFailed("na Liscie Wykonawcow nikt nie ma adresu")

    before = _survey(inbox, since, "pierwszym odczycie flag")
    read = inbox.mails_since(since)
    if isinstance(read, (PasswordRejected, InboxUnreachable)):
        raise ProbeFailed(_unreachable(read, "odczycie maili"))
    mails = read.mails
    window = Window.of(today, since)
    outcome = enter_reports(ReportInputs(mails, addresses, (), window, OwnEntries.EMPTY, frozenset(), ()))
    if review is not None:
        review.write(mails, addresses, window)
    after = _survey(inbox, since, "drugim odczycie flag")
    changed = sum(1 for uid, flags in before.flags.items() if after.flags.get(uid) != flags)
    unread = sum(1 for survey in (before, after) if len(survey.flags) != survey.searched)
    arrived = len(mails) + read.skipped - before.in_folder

    lines = [
        f"SKRZYNKA | folder_wszystkich={before.in_folder} | odebrane={before.in_inbox}"
        f" | poza_odebranymi={before.in_folder - before.in_inbox}",
        _mail_line(mails, read.skipped, outcome),
        _problem_line(outcome),
        f"FLAGI | sprawdzone={len(before.flags)} | zmienione={changed}",
    ]
    reasons = [
        *([] if _recognised(outcome) else [_no_report(mails, outcome, since)]),
        *([f"zepsute polskie znaki w {broken} mailach"] if (broken := _count(mails, _BROKEN)) else []),
        *([f"flagi nie kazdego wyszukanego maila w {unread} z 2 odczytow"] if unread else []),
        *(
            [f"{arrived} maili przyszlo w trakcie proby bez pierwszego odczytu flag, uruchom ponownie"]
            if arrived > 0
            else []
        ),
        *([f"flagi zmienione w {changed} mailach"] if changed else []),
    ]
    last = f"{FAIL} | {'; '.join(reasons)}" if reasons else f"{OK} | maile={len(mails)} | flagi bez zmian"
    return [*lines, last]


_WHOLE_TIME: Final = Window(date.max, date.min, frozenset())
"""Okno, które otwiera każdy dzień: przegląd czyta nim także Raport z dniem spoza okna próby, który rdzeń pomija."""
_REVIEW_HEAD: Final = """PRZEGLĄD WPISÓW Z PRAWDZIWEJ SKRZYNKI RAPORTÓW (tools/proba_skrzynki_raportow.py --przeglad)
Ten plik zawiera prawdziwe maile Wykonawców taty. Trzymaj go w ~/.t3/notes/<run>/, nie w repozytorium i nie w /tmp.
Jego treść nie trafia do czatu, issue ani PR: wolno wypisać tylko zbiorcze wnioski i liczby, a każdy błąd dostaje test
z syntetyczną postacią.
Próba nie zna zleceń INTERMAX, więc numerem Wpisu jest tu liczba o dowolnej liczbie cyfr; Wpisanie raportów u taty
uznaje za numer tylko liczbę co najmniej tak długą jak najkrótszy NUMER ZL. dni otwartych, a krótszą wpisuje do opisu.
"""


@dataclass(frozen=True)
class ReviewFile:
    """Plik przeglądu Wpisów (``--przeglad``): ``path`` po dowiązaniach, ``replace`` z ``--nadpisz``."""

    path: Path
    replace: bool

    @classmethod
    def of(cls, path: Path, replace: bool) -> ReviewFile:
        return cls(path.expanduser().resolve(), replace)

    def refusal(self) -> str | None:
        """Powód odmowy pliku przed łączeniem ze skrzynką, bez ścieżki; ``None``, gdy plik wolno zapisać."""

        if any((folder / ".git").exists() for folder in self.path.parents):
            return "plik przegladu w repozytorium Git, a ma prawdziwe maile: podaj sciezke w ~/.t3/notes/<run>/"
        if self.path.is_dir():
            return "plik przegladu to folder: podaj sciezke pliku"
        if self.path.exists() and not self.replace:
            return "plik przegladu juz istnieje: podaj nowa sciezke albo --nadpisz"
        if not self.path.parent.is_dir():
            return "brak folderu pliku przegladu"
        return None

    def write(self, mails: Sequence[ReportMail], addresses: WorkerAddresses, window: Window) -> None:
        """Zapisuje przegląd do nowego pliku, który od utworzenia ma prawa ``0600``; ``ProbeFailed``, gdy zapis się
        nie udał.

        Z ``--nadpisz`` przegląd powstaje obok i podmienia stary plik przez ``os.replace``, więc deskryptor otwarty na
        starym pliku (z dawnymi prawami) nigdy nie widzi prawdziwych maili; bez ``--nadpisz`` ``O_EXCL`` nie nadpisze
        pliku, który powstał po ``refusal``."""

        target = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp") if self.replace else self.path
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as out:
                    _write_review(out, mails, addresses, window)
                if self.replace:
                    os.replace(target, self.path)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        except OSError as error:
            raise ProbeFailed(f"nie zapisano pliku przegladu: {type(error).__name__}") from None


def _write_review(out: TextIO, mails: Sequence[ReportMail], addresses: WorkerAddresses, window: Window) -> None:
    """Każdy mail osobno przez rdzeń: Wpisy jednego maila nie zależą od innych maili, gdy próba nie ma zleceń."""

    aliases: dict[Login, str] = {}
    entries: dict[tuple[str, date, OrderNumber], list[tuple[datetime, ReportEntry]]] = {}
    out.write(_REVIEW_HEAD)
    for mail, found in sorted(_worker_reads(mails, addresses), key=lambda pair: pair[0].arrived):
        alias = aliases.setdefault(found.worker, _alias(len(aliases)))
        out.write(f"\n===== {mail.arrived:%Y-%m-%d %H:%M %z} | {alias} | temat: {mail.subject!r}")
        match found:
            case ReadReport(day=day):
                outside = "" if window.opens(day) else " | dzien spoza okna proby: rdzen pomija ten Raport"
                out.write(f" | dzien {day.isoformat()}{outside}\n")
            case ReadUnreadable(fault=fault):
                outside = "" if window.opens(mail.arrived.date()) else " | przyszedl przed oknem proby: rdzen go pomija"
                out.write(f" | temat nierozpoznany: {fault.name}{outside}\n")
        out.write("----- TRESC\n")
        out.write("".join(f"{line}\n" for line in mail.text.splitlines()))
        match found:
            case ReadReport(day=day, entries=read):
                out.write(f"----- WPISY ({len(read)})\n")
                for entry in read:
                    out.write(f"  {_entry_line(entry)}\n")
                    entries.setdefault((alias, day, entry.number), []).append((mail.arrived, entry))
            case ReadUnreadable(numbers=numbers):
                listed = ", ".join(sorted(numbers)) or "brak"
                out.write(f"----- WPISY: brak, bo temat nierozpoznany; numery dla poprawionego Raportu: {listed}\n")
    repeated = {key: same for key, same in entries.items() if len(same) > 1}
    out.write(f"\n===== NUMERY Z KILKOMA WPISAMI JEDNEGO WYKONAWCY Z JEDNEGO DNIA ({len(repeated)})\n")
    for (alias, day, number), same in sorted(repeated.items()):
        out.write(f"{alias} | dzien {day.isoformat()} | {number}\n")
        for arrived, entry in same:
            out.write(f"  {arrived:%Y-%m-%d %H:%M %z} | {_entry_line(entry)}\n")


def _worker_reads(
    mails: Sequence[ReportMail], addresses: WorkerAddresses
) -> Iterator[tuple[ReportMail, ReadReport | ReadUnreadable]]:
    for mail in mails:
        outcome = enter_reports(ReportInputs((mail,), addresses, (), _WHOLE_TIME, OwnEntries.EMPTY, frozenset(), ()))
        for found in outcome.mails:
            if isinstance(found, (ReadReport, ReadUnreadable)):
                yield mail, found


def _alias(index: int) -> str:
    """``Wykonawca A`` … ``Z``, potem ``AA``, ``AB`` …"""

    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return f"Wykonawca {letters}"


def _entry_line(entry: ReportEntry) -> str:
    match entry:
        case ReportEntry(verdict=Verdict() as verdict):
            shown = verdict.value
        case ReportEntry(fault=VerdictFault() as fault):
            shown = f"bez tak/nie: {fault.name}"
        case _:
            shown = "bez tak/nie"
    return f"{entry.number} | {shown} | {entry.activities!r}"


def _recognised(outcome: ReportsOutcome) -> bool:
    """Rdzeń rozpoznał Raport wykonawcy od adresu z pliku adresów z Wpisem raportu, który ma ``tak`` albo ``nie``."""

    return any(entry.verdict is not None for report in _reports(outcome) for entry in report.entries)


def _no_report(mails: Sequence[ReportMail], outcome: ReportsOutcome, since: date) -> str:
    strangers = len(_strangers(outcome))
    reports = _reports(outcome)
    return (
        f"brak rozpoznanego Raportu wykonawcy od {since.isoformat()} (maile_z_raport={len(mails)}"
        f", nieznani_nadawcy={strangers}, nierozpoznane_tematy={len(mails) - len(reports) - strangers}"
        f", raporty_bez_wpisow={sum(1 for report in reports if not report.entries)}"
        f", wpisy_bez_tak_nie={sum(1 for report in reports for entry in report.entries if entry.verdict is None)})"
    )


def _reports(outcome: ReportsOutcome) -> list[ReadReport]:
    return [read for read in outcome.mails if isinstance(read, ReadReport)]


def _strangers(outcome: ReportsOutcome) -> list[ReadStranger]:
    return [read for read in outcome.mails if isinstance(read, ReadStranger)]


def _survey(inbox: ImapInbox, since: date, when: str) -> InboxSurvey:
    found = inbox.survey(since)
    if isinstance(found, (PasswordRejected, InboxUnreachable)):
        raise ProbeFailed(_unreachable(found, when))
    return found


def _unreachable(found: PasswordRejected | InboxUnreachable, when: str) -> str:
    match found:
        case PasswordRejected():
            return f"Gmail odrzucil haslo aplikacji przy {when}"
        case InboxUnreachable(cause):
            return f"skrzynka niedostepna przy {when}: {cause}"


def _count(mails: Sequence[ReportMail], pattern: re.Pattern[str]) -> int:
    return sum(1 for mail in mails if pattern.search(mail.subject) or pattern.search(mail.text))


def _mail_line(mails: Sequence[ReportMail], skipped: int, outcome: ReportsOutcome) -> str:
    return (
        f"MAILE | przeczytane={len(mails)} | pominiete={skipped} | raporty={len(_reports(outcome)) + len(_strangers(outcome))}"
        f" | wpisy={sum(len(report.entries) for report in _reports(outcome))}"
        f" | polskie_znaki={_count(mails, _POLISH)} | zepsute_znaki={_count(mails, _BROKEN)}"
    )


def _problem_line(outcome: ReportsOutcome) -> str:
    kinds = Counter(type(problem).__name__ for problem in outcome.problems)
    return "PROBLEMY | " + (" | ".join(f"{kind}={kinds[kind]}" for kind in sorted(kinds)) or "brak")


def main(argv: Sequence[str] | None = None, *, connect: Callable[[], imaplib.IMAP4] | None = None) -> int:
    """``connect`` podaje test, żeby port rozmawiał z ``AtrapaImap``; bez niego port łączy się z Gmailem."""

    today = datetime.now().astimezone().date()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--od",
        type=date.fromisoformat,
        default=today - timedelta(days=DAYS_BACK),
        help=f"Pierwszy dzień Raportów, RRRR-MM-DD (domyślnie {DAYS_BACK} dni przed dziś).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=tool_files.CONFIG_DIR,
        help="Folder config z plikiem dostępu i Listą Wykonawców (domyślnie config klonu narzędzia, jak w Centrum).",
    )
    parser.add_argument(
        "--przeglad",
        type=Path,
        help="Plik przeglądu Wpisów z prawdziwymi mailami Wykonawców (prawa 0600): trzymaj go w ~/.t3/notes/<run>/, nie w"
        " repozytorium i nie w /tmp, a jego treść nie trafia do czatu, issue ani PR, tylko zbiorcze wnioski bez danych"
        " klientów. Ścieżki w repozytorium Git narzędzie odmawia bez łączenia ze skrzynką.",
    )
    parser.add_argument(
        "--nadpisz", action="store_true", help="Zastąp istniejący plik --przeglad (bez tej flagi narzędzie go odmawia)."
    )
    args = parser.parse_args(argv)
    if args.nadpisz and args.przeglad is None:
        parser.error("--nadpisz dotyczy tylko --przeglad")
    review = None if args.przeglad is None else ReviewFile.of(args.przeglad, args.nadpisz)
    inbox = ImapInbox(args.config) if connect is None else ImapInbox(args.config, connect=connect)
    try:
        if review is not None and (refusal := review.refusal()) is not None:
            raise ProbeFailed(refusal)
        lines = probe(inbox, args.config, args.od, today, review)
    except ProbeFailed as error:
        lines = [f"{FAIL} | {error.reason}"]
    print("\n".join(lines))
    return 0 if lines[-1].startswith(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
