"""Sprawdza port IMAP na prawdziwej skrzynce raportów taty tylko do odczytu, wynik jedną linią; uruchom przed Wydaniem z Wpisaniem raportów.

Narzędzie dla Maksa, poza CI (Granica 4 speca #1224, ADR 0028). Port IMAP Skrzynki raportów
(``rozliczenia.worker_report_inbox.ImapInbox``) CI sprawdza tylko na ``AtrapaImap``, więc prawdziwego Gmaila sprawdza
ta próba: tym samym portem, z tym samym plikiem dostępu ``config/skrzynka-raportow.txt`` (linia 1 adres skrzynki,
linia 2 hasło aplikacji Google) i plikiem adresów Wykonawców ``config/adresy-wykonawcow.yaml``, co Wpisanie raportów.
Po kolei:

1. czyta plik adresów z Konfiguracją wykonawców (``config/worker_mapping.yaml``), jak Wpisanie raportów;
2. czyta flagi IMAP każdego maila z dni od dnia przed ``--od`` w folderze, który czyta port (``\\All``, a bez niego
   ``INBOX``), i liczy maile ze słowem ``raport`` w temacie w tym folderze i w ``INBOX`` (``ImapInbox.survey``);
3. czyta Raporty wykonawców od ``--od`` portem (``mails_since``) i przepuszcza je przez rdzeń raportów
   (``enter_reports``) bez zleceń INTERMAX, więc każdy Wpis raportu z rozpoznanego Raportu to problem nieznanego numeru;
4. czyta flagi jeszcze raz i porównuje je z pierwszym odczytem: mail, którego flagi są inne albo którego nie ma w
   drugim odczycie, to mail ze zmienionymi flagami.

Skrzynki nie zmienia: port otwiera folder przez ``EXAMINE`` i pobiera tematy, treści i flagi przez ``BODY.PEEK`` i
``FETCH (FLAGS)``, bez ``SELECT`` i ``STORE``. Mail, który przyszedł w trakcie próby, porównanie pomija, bo nie ma go
w pierwszym odczycie.

Wynik (stdout) to same liczby, bez treści maili, tematów, adresów, loginów i numerów zleceń:

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

Ostatnia linia to ``PROBA IMAP OK | …`` (kod 0) albo ``PROBA IMAP FAIL | <powód>`` (kod 1): brak albo zła treść pliku
dostępu, pliku adresów albo Konfiguracji wykonawców, odrzucone hasło, skrzynka niedostępna (nazwa typu błędu), żaden
mail z Raportem od ``--od``, zepsute znaki albo flagi, które zmieniły się między odczytami. Hasła nie ma
w wyniku, wyjątkach ani żadnym pliku: zna je tylko port.

Uruchomienie u taty, w klonie narzędzia z plikami w ``config/`` (Windows: ``py -3``), a ostatnią linię Maks wpisuje w
komentarzu #1234:

    .venv/bin/python tools/proba_skrzynki_raportow.py [--od RRRR-MM-DD] [--config <folder config>]
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
import imaplib
from pathlib import Path
import re
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rozliczenia import tool_files
from rozliczenia.worker_addresses import WORKER_ADDRESSES_FILE, AddressesError
from rozliczenia.worker_addresses import load as load_addresses
from rozliczenia.worker_config import WorkerConfigError, load_worker_mapping
from rozliczenia.worker_report_inbox import (
    INBOX_ACCESS_FILE,
    ImapInbox,
    InboxSurvey,
    InboxUnreachable,
    PasswordRejected,
)
from rozliczenia.worker_reports import (
    OwnEntries,
    ReadReport,
    ReportInputs,
    ReportMail,
    ReportsOutcome,
    Window,
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


def probe(inbox: ImapInbox, config: Path, since: date, today: date) -> list[str]:
    """Linie wyniku próby z ostatnią ``PROBA IMAP OK`` albo ``PROBA IMAP FAIL``; ``ProbeFailed``, gdy próba nie doszła
    do liczb."""

    match inbox.access():
        case "missing":
            raise ProbeFailed(f"brak pliku dostępu config/{INBOX_ACCESS_FILE} albo jego adresu lub hasła")
        case "unreadable":
            raise ProbeFailed(f"nieczytelny plik dostępu config/{INBOX_ACCESS_FILE}")
        case "ready":
            pass
    try:
        workers = load_worker_mapping(config / tool_files.WORKER_CONFIG.name)
    except WorkerConfigError as error:
        raise ProbeFailed(f"Konfiguracja wykonawców: {_problem(error.reason)}") from None
    try:
        addresses = load_addresses(config / WORKER_ADDRESSES_FILE, workers=workers)
    except AddressesError as error:
        raise ProbeFailed(f"plik adresów Wykonawców: {_problem(error.problem)}") from None

    before = _survey(inbox, since, "pierwszym odczycie flag")
    read = inbox.mails_since(since)
    if isinstance(read, (PasswordRejected, InboxUnreachable)):
        raise ProbeFailed(_unreachable(read, "odczycie maili"))
    mails = read.mails
    outcome = enter_reports(
        ReportInputs(mails, addresses, (), Window.of(today, since), OwnEntries.EMPTY, frozenset())
    )
    after = _survey(inbox, since, "drugim odczycie flag")
    changed = sum(1 for uid, flags in before.flags.items() if after.flags.get(uid) != flags)

    lines = [
        f"SKRZYNKA | folder_wszystkich={before.in_folder} | odebrane={before.in_inbox}"
        f" | poza_odebranymi={before.in_folder - before.in_inbox}",
        _mail_line(mails, read.skipped, outcome),
        _problem_line(outcome),
        f"FLAGI | sprawdzone={len(before.flags)} | zmienione={changed}",
    ]
    reasons = [
        *([f"żaden mail z Raportem od {since.isoformat()}, podaj wcześniejsze --od"] if not mails else []),
        *([f"zepsute polskie znaki w {broken} mailach"] if (broken := _count(mails, _BROKEN)) else []),
        *([f"flagi zmienione w {changed} mailach"] if changed else []),
    ]
    last = f"{FAIL} | {'; '.join(reasons)}" if reasons else f"{OK} | maile={len(mails)} | flagi bez zmian"
    return [*lines, last]


def _survey(inbox: ImapInbox, since: date, when: str) -> InboxSurvey:
    found = inbox.survey(since)
    if isinstance(found, (PasswordRejected, InboxUnreachable)):
        raise ProbeFailed(_unreachable(found, when))
    return found


def _unreachable(found: PasswordRejected | InboxUnreachable, when: str) -> str:
    match found:
        case PasswordRejected():
            return f"Gmail odrzucił hasło aplikacji przy {when}"
        case InboxUnreachable(cause):
            return f"skrzynka niedostępna przy {when}: {cause}"


def _problem(problem: object) -> str:
    """Rodzaj problemu pliku: sam napis albo nazwa typu, bez pól, w których bywa login."""

    return problem if isinstance(problem, str) else type(problem).__name__


def _count(mails: Sequence[ReportMail], pattern: re.Pattern[str]) -> int:
    return sum(1 for mail in mails if pattern.search(mail.subject) or pattern.search(mail.text))


def _mail_line(mails: Sequence[ReportMail], skipped: int, outcome: ReportsOutcome) -> str:
    reports = [read for read in outcome.mails if isinstance(read, ReadReport)]
    return (
        f"MAILE | przeczytane={len(mails)} | pominiete={skipped} | raporty={len(outcome.mails)}"
        f" | wpisy={sum(len(report.entries) for report in reports)}"
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
        help="Folder config z plikiem dostępu i plikiem adresów (domyślnie config klonu narzędzia, jak w Centrum).",
    )
    args = parser.parse_args(argv)
    inbox = ImapInbox(args.config) if connect is None else ImapInbox(args.config, connect=connect)
    try:
        lines = probe(inbox, args.config, args.od, today)
    except ProbeFailed as error:
        lines = [f"{FAIL} | {error.reason}"]
    print("\n".join(lines))
    return 0 if lines[-1].startswith(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
