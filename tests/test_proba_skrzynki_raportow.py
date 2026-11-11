"""Próba IMAP (#1234): narzędzie Maksa sprawdza port Skrzynki raportów na skrzynce taty tylko do odczytu.

Narzędzie rozmawia prawdziwym ``imaplib`` portu z lokalną ``AtrapaImap`` (``tools/lib/atrapy/skrzynka_raportow.py``),
bez sieci i bez Gmaila. Test czyta to, co widzi Maks: linie na stdout i kod wyjścia, oraz polecenia, które dostał
serwer. Maile, adresy i numery są syntetyczne.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import email.policy
import imaplib
import os
from pathlib import Path
import stat
import sys
from typing import Any, Literal

import pytest
import proba_skrzynki_raportow

from rozliczenia import tool_files
from rozliczenia.worker_addresses import WORKER_ADDRESSES_FILE
from rozliczenia.worker_report_inbox import FETCH_BATCH, INBOX_ACCESS_FILE

from atrapy.skrzynka_raportow import AtrapaImap, AtrapaMail

SKRZYNKA = "raporty.taty@przyklad.invalid"
HASLO = "abcdefghijklmnop"
WYKONAWCA = "jan.testowy@przyklad.invalid"
OBCY = "obcy.nadawca@przyklad.invalid"
DRUGI = "anna.probna@przyklad.invalid"
TATA = timezone(timedelta(hours=1))
WRITES = {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND"}
# Wszystko, co mail niesie, a czego wynik próby nie może pokazać.
TRESCI = [
    SKRZYNKA,
    HASLO,
    WYKONAWCA,
    OBCY,
    "jan.testowy",
    DRUGI,
    "anna.probna",
    "Raport 08.11.2026",
    "Raport 09.11.2026",
    "Raport bez daty",
    "Re: Raport",
    "Faktura",
    "40000001",
    "40000003",
    "40000004",
    "gniazdka",
    "odmówił",
    "zleceń",
]


def mail(
    uid: int,
    *,
    temat: str,
    tresc: str = "40000001 tak wymiana gniazdka, usunięto awarię",
    od: str | None = f"Jan Testowy <{WYKONAWCA}>",
    charset: str = "utf-8",
    flagi: tuple[str, ...] = (),
    w_odebranych: bool = True,
    przyszedl: datetime = datetime(2026, 11, 9, 18, 5, tzinfo=TATA),
) -> AtrapaMail:
    message = EmailMessage(policy=email.policy.SMTP)
    if od is not None:
        message["From"] = od
    message["To"] = SKRZYNKA
    message["Subject"] = temat
    message["Message-ID"] = f"<{uid}@przyklad.invalid>"
    message.set_content(tresc, charset=charset)
    return AtrapaMail(uid, przyszedl, message.as_bytes(), flagi, w_odebranych)


def skrzynka_z_raportami() -> list[AtrapaMail]:
    """Siedem maili z dni okna: dwa Raporty Wykonawcy z Wpisem (jeden tylko w folderze wszystkich maili) i jeden bez
    Wpisu, Raport obcego nadawcy, odpowiedź na Raport, mail ze słowem ``raport`` bez nadawcy i faktura bez tego
    słowa."""

    return [
        mail(1, temat="Raport 08.11.2026", flagi=("\\Seen",)),
        mail(2, temat="Raport 09.11.2026", tresc="40000003 tak", od=f"<{OBCY}>"),
        mail(3, temat="Re: Raport 08.11.2026", tresc="40000001 tak"),
        mail(4, temat="Faktura", tresc="do zapłaty", flagi=("\\Seen", "$Etykieta")),
        mail(5, temat="Raport 09.11.2026", tresc="40000004 nie klient odmówił", charset="iso-8859-2", w_odebranych=False),
        mail(6, temat="Raport 09.11.2026", od=None),
        mail(7, temat="Raport 09.11.2026", tresc="dzień bez zleceń"),
    ]


def config(folder: Path, *, adresy: bool = True) -> Path:
    (folder / INBOX_ACCESS_FILE).write_text(f"{SKRZYNKA}\nabcd efgh ijkl mnop\n", encoding="utf-8")
    (folder / tool_files.WORKER_CONFIG.name).write_text(
        "schema_version: 1\nworkers:\n  jan.testowy: Jan Testowy\n  anna.probna: Anna Próbna\n", encoding="utf-8"
    )
    if adresy:
        (folder / WORKER_ADDRESSES_FILE).write_text(
            f"schema_version: 1\nwykonawcy:\n  jan.testowy: [{WYKONAWCA}]\n  anna.probna: [{DRUGI}]\n", encoding="utf-8"
        )
    return folder


def lokalnie(port: int) -> Callable[[], imaplib.IMAP4]:
    return lambda: imaplib.IMAP4("127.0.0.1", port)


def proba(
    capsys: pytest.CaptureFixture[str], folder: Path, connect: Callable[[], imaplib.IMAP4], *opcje: str
) -> tuple[int, list[str]]:
    code = proba_skrzynki_raportow.main(["--config", str(folder), "--od", "2026-11-01", *opcje], connect=connect)
    out, err = capsys.readouterr()
    assert not err
    assert out.isascii()
    for tresc in [*TRESCI, *opcje]:
        assert tresc not in out
    return code, out.splitlines()


def test_proba_na_skrzynce_z_raportami_drukuje_same_liczby_i_ostatnia_linie_ok_bez_zmiany_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami()) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines == [
        "SKRZYNKA | folder_wszystkich=6 | odebrane=5 | poza_odebranymi=1",
        "MAILE | przeczytane=5 | pominiete=1 | raporty=4 | wpisy=2 | polskie_znaki=3 | zepsute_znaki=0",
        "PROBLEMY | UnknownNumber=2 | UnknownSender=1",
        "FLAGI | sprawdzone=7 | zmienione=0",
        "PROBA IMAP OK | maile=5 | flagi bez zmian",
    ]
    assert code == 0
    names = {command.split(" ")[0] if not command.startswith("UID ") else command.split(" ")[1] for command in atrapa.commands}
    assert not WRITES & names
    assert 'EXAMINE "INBOX"' in atrapa.commands
    assert any(command.startswith("UID FETCH") and command.endswith("(UID FLAGS)") for command in atrapa.commands)
    assert atrapa.flags == {mail.uid: set(mail.flags) for mail in skrzynka_z_raportami()}


def test_proba_zglasza_flage_zmieniona_miedzy_odczytami(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami(), marks_seen=True) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[-2:] == [
        "FLAGI | sprawdzone=7 | zmienione=5",
        "PROBA IMAP FAIL | flagi zmienione w 5 mailach",
    ]
    assert code == 1


def test_proba_liczy_mail_znikniety_przed_drugim_odczytem_jako_zmieniony(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    maile = [mail(1, temat="Raport 08.11.2026"), mail(4, temat="Faktura", tresc="do zapłaty")]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=maile, deletes_read=True) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert atrapa.deleted == {1}
    assert lines[-2:] == [
        "FLAGI | sprawdzone=2 | zmienione=1",
        "PROBA IMAP FAIL | flagi zmienione w 1 mailach",
    ]
    assert code == 1


@pytest.mark.parametrize("odpowiedz", ["without_fetch", "unsolicited"])
def test_proba_nie_przechodzi_gdy_serwer_nie_oddal_samych_flag_kazdego_wyszukanego_maila(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], odpowiedz: Literal["without_fetch", "unsolicited"]
) -> None:
    with AtrapaImap(
        address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami(), marks_seen=True, flags_reply=odpowiedz
    ) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert (code, lines) == (1, ["PROBA IMAP FAIL | skrzynka niedostepna przy pierwszym odczycie flag: UnexpectedReply"])


class WyszukiwanieZPowtorzonymUid(imaplib.IMAP4):
    """Serwer, który w wyniku ``UID SEARCH`` podaje pierwszy UID dwa razy: flagi ma wtedy mniej maili, niż wyszukano."""

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        status, data = super().uid(command, *args)
        if command == "SEARCH" and data and isinstance(data[0], bytes) and data[0]:
            data = [data[0] + b" " + data[0].split()[0]]
        return status, data


def test_proba_nie_przechodzi_gdy_flagi_ma_mniej_maili_niz_wyszukano(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")]) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lambda: WyszukiwanieZPowtorzonymUid("127.0.0.1", atrapa.port))

    assert lines[-2:] == [
        "FLAGI | sprawdzone=1 | zmienione=0",
        "PROBA IMAP FAIL | flagi nie kazdego wyszukanego maila w 2 z 2 odczytow",
    ]
    assert code == 1


class _PierwszaSesjaBezUid1(imaplib.IMAP4):
    """Pierwsza sesja próby, która nie widzi maila UID 1 w ``UID SEARCH``, bo przyszedł tuż po niej."""

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        status, data = super().uid(command, *args)
        if command == "SEARCH" and data and isinstance(data[0], bytes):
            data = [b" ".join(uid for uid in data[0].split() if uid != b"1")]
        return status, data


def test_proba_nie_przechodzi_gdy_raport_przyszedl_po_pierwszym_odczycie_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Raport, którego pierwszy odczyt flag nie widział, port przeczytał i oznaczył: jego flag nikt nie porównał, więc
    próba nie przechodzi, zamiast dać OK z flagami bez zmian."""

    sesje: list[imaplib.IMAP4] = []

    def connect(port: int) -> imaplib.IMAP4:
        sesje.append(_PierwszaSesjaBezUid1("127.0.0.1", port) if not sesje else imaplib.IMAP4("127.0.0.1", port))
        return sesje[-1]

    maile = [mail(1, temat="Raport 08.11.2026")]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=maile, marks_seen=True) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lambda: connect(atrapa.port))

    assert atrapa.flags == {1: {"\\Seen"}}
    assert lines[-2:] == [
        "FLAGI | sprawdzone=0 | zmienione=0",
        "PROBA IMAP FAIL | 1 maili przyszlo w trakcie proby bez pierwszego odczytu flag, uruchom ponownie",
    ]
    assert code == 1


def test_proba_porownuje_flagi_maili_z_kazdej_paczki_odczytu_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Flagi czyta się w paczkach po ``FETCH_BATCH`` maili: Raport w drugiej paczce, który port oznaczył jako
    przeczytany, to zmiana flag, a każdy mail ma flagi z obu odczytów."""

    ostatni = FETCH_BATCH + 50
    maile = [*(mail(uid, temat="Faktura", tresc="do zapłaty") for uid in range(1, ostatni)), mail(ostatni, temat="Raport 08.11.2026")]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=maile, marks_seen=True) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[-2:] == [f"FLAGI | sprawdzone={ostatni} | zmienione=1", "PROBA IMAP FAIL | flagi zmienione w 1 mailach"]
    assert code == 1


@pytest.mark.parametrize(
    ("maile", "liczby"),
    [
        pytest.param(
            [mail(4, temat="Faktura")],
            "maile_z_raport=0, nieznani_nadawcy=0, nierozpoznane_tematy=0, raporty_bez_wpisow=0, wpisy_bez_tak_nie=0",
            id="bez-maila-ze-slowem-raport",
        ),
        pytest.param(
            [mail(3, temat="Raport bez daty")],
            "maile_z_raport=1, nieznani_nadawcy=0, nierozpoznane_tematy=1, raporty_bez_wpisow=0, wpisy_bez_tak_nie=0",
            id="temat-bez-dnia-od-wykonawcy",
        ),
        pytest.param(
            [mail(2, temat="Raport 09.11.2026", tresc="40000003 tak", od=f"<{OBCY}>")],
            "maile_z_raport=1, nieznani_nadawcy=1, nierozpoznane_tematy=0, raporty_bez_wpisow=0, wpisy_bez_tak_nie=0",
            id="adres-spoza-pliku-adresow",
        ),
        pytest.param(
            [mail(7, temat="Raport 09.11.2026", tresc="dzień bez zleceń")],
            "maile_z_raport=1, nieznani_nadawcy=0, nierozpoznane_tematy=0, raporty_bez_wpisow=1, wpisy_bez_tak_nie=0",
            id="raport-wykonawcy-bez-wpisu",
        ),
        pytest.param(
            [mail(1, temat="Raport 08.11.2026", tresc="40000001 t wymiana")],
            "maile_z_raport=1, nieznani_nadawcy=0, nierozpoznane_tematy=0, raporty_bez_wpisow=0, wpisy_bez_tak_nie=1",
            id="wpis-z-litera-t-zamiast-tak",
        ),
    ],
)
def test_proba_bez_rozpoznanego_raportu_wykonawcy_nie_przechodzi_i_mowi_dlaczego_liczbami(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], maile: list[AtrapaMail], liczby: str
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=maile) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[-1] == f"PROBA IMAP FAIL | brak rozpoznanego Raportu wykonawcy od 2026-11-01 ({liczby})"
    assert code == 1


def test_proba_z_jednym_raportem_wykonawcy_z_wpisem_przechodzi(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")]) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert (code, lines[-1]) == (0, "PROBA IMAP OK | maile=1 | flagi bez zmian")


@pytest.mark.parametrize(
    ("tresc", "zapisany", "podany", "znak"),
    [
        pytest.param("usunięto awarię", "utf-8", "iso-8859-2", "Ä", id="utf-8-jako-iso-8859-2-Ä"),
        pytest.param("próba", "utf-8", "iso-8859-2", "Ă", id="utf-8-jako-iso-8859-2-Ă"),
        pytest.param("wyświetlacz", "utf-8", "cp1250", "Ĺ", id="utf-8-jako-cp1250-Ĺ"),
        pytest.param("próba", "utf-8", "iso-8859-1", "Ã", id="utf-8-jako-latin-1-Ã"),
        pytest.param("wyświetlacz", "utf-8", "iso-8859-1", "Å", id="utf-8-jako-latin-1-Å"),
        pytest.param("wymiana złącza", "iso-8859-2", "utf-8", "\ufffd", id="iso-8859-2-jako-utf-8-znak-zastepczy"),
    ],
)
def test_proba_zglasza_polskie_litery_zepsute_przez_zly_zestaw_znakow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tresc: str, zapisany: str, podany: str, znak: str
) -> None:
    # Nadawca zapisał treść w jednym zestawie znaków, a w nagłówku podał inny: polska litera to wtedy ``znak``.
    assert tresc.encode(zapisany).decode(podany, errors="replace").count(znak) >= 1
    zapisany_mail = mail(1, temat="Raport 08.11.2026", tresc=f"40000001 tak {tresc}", charset=zapisany)
    raw = zapisany_mail.raw.replace(f'charset="{zapisany}"'.encode(), f'charset="{podany}"'.encode())
    assert raw != zapisany_mail.raw
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[AtrapaMail(1, zapisany_mail.arrived, raw)]) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[1].endswith("| zepsute_znaki=1")
    assert lines[-1] == "PROBA IMAP FAIL | zepsute polskie znaki w 1 mailach"
    assert code == 1


def test_proba_z_odrzuconym_haslem_albo_bez_sieci_konczy_sie_linia_fail_z_powodem_bez_hasla(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = config(tmp_path)
    with AtrapaImap(address=SKRZYNKA, password="inne-haslo", mails=skrzynka_z_raportami()) as atrapa:
        odrzucone = proba(capsys, folder, lokalnie(atrapa.port))

    def bez_sieci_do_gmaila() -> imaplib.IMAP4:
        raise ConnectionRefusedError(f"brak sieci przy {SKRZYNKA}")

    bez_sieci = proba(capsys, folder, bez_sieci_do_gmaila)

    assert odrzucone == (1, ["PROBA IMAP FAIL | Gmail odrzucil haslo aplikacji przy pierwszym odczycie flag"])
    assert bez_sieci == (1, ["PROBA IMAP FAIL | skrzynka niedostepna przy pierwszym odczycie flag: ConnectionRefusedError"])
    assert "LOGIN" in atrapa.commands
    assert "abcd efgh ijkl mnop" not in "".join(atrapa.commands)


def test_proba_bez_pliku_adresow_nie_laczy_sie_ze_skrzynka(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami()) as atrapa:
        code, lines = proba(capsys, config(tmp_path, adresy=False), lokalnie(atrapa.port))

    assert (code, lines) == (1, ["PROBA IMAP FAIL | plik adresow Wykonawcow: missing"])
    assert atrapa.commands == []


# Przegląd Wpisów (``--przeglad``): plik z prawdziwymi mailami do przeglądu Maksa, a stdout bez zmian.


def chwila(przyszedl: datetime) -> str:
    """Chwila przyjścia w pliku przeglądu: tak, jak oddaje ją port, w strefie komputera."""

    return f"{przyszedl.astimezone():%Y-%m-%d %H:%M %z}"


PRZEGLAD_SKRZYNKI = [
    mail(1, temat="Raport 08.11.2026"),
    mail(2, temat="Raport 09.11.2026", tresc="40000003 tak", od=f"<{OBCY}>"),
    mail(
        3,
        temat="Raport bez daty",
        tresc="Dzień dobry,\n\n40000006 tak\n-- \nJan",
        przyszedl=datetime(2026, 11, 9, 19, 0, tzinfo=TATA),
    ),
    mail(
        4,
        temat="Raport 09.11.2026",
        tresc="40000001 nie klient odmówił\n\n40000005 t",
        od=f"Anna Próbna <{DRUGI}>",
        przyszedl=datetime(2026, 11, 9, 20, 0, tzinfo=TATA),
    ),
    mail(5, temat="Raport 08.11.2026", tresc="40000001 nie brak dostępu", przyszedl=datetime(2026, 11, 10, 8, 0, tzinfo=TATA)),
    mail(6, temat="Raport 20.10.2026", tresc="40000007 tak montaż", przyszedl=datetime(2026, 11, 9, 21, 0, tzinfo=TATA)),
    mail(7, temat="Faktura", tresc="do zapłaty"),
    mail(8, temat="Raport z piątku", tresc="40000008 tak", przyszedl=datetime(2026, 10, 31, 12, 0, tzinfo=TATA)),
]


def test_przeglad_zapisuje_kazdy_mail_wykonawcy_z_trescia_i_wpisami_rdzenia_a_stdout_zostaje_ten_sam(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Raport wykonawcy, mail Wykonawcy z nierozpoznanym tematem oraz Raport z dniem spoza okna i mail z dnia przed
    ``--od``, które rdzeń pomija, trafiają do pliku po chwili przyjścia z aliasem Wykonawcy, a Raport obcego nadawcy i
    mail bez słowa ``raport`` nie; numer z dwoma Wpisami jednego Wykonawcy z jednego dnia stoi na końcu."""

    folder = config(tmp_path)
    plik = tmp_path / "wpisy.txt"
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=PRZEGLAD_SKRZYNKI) as atrapa:
        bez_przegladu = proba(capsys, folder, lokalnie(atrapa.port))
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=PRZEGLAD_SKRZYNKI) as atrapa:
        z_przegladem = proba(capsys, folder, lokalnie(atrapa.port), "--przeglad", str(plik))

    assert z_przegladem == bez_przegladu
    naglowek, wpisy = plik.read_text(encoding="utf-8").split("\n\n", 1)
    assert "zawiera prawdziwe maile" in naglowek
    assert "~/.t3/notes/" in naglowek
    assert wpisy == (
        f"===== {chwila(datetime(2026, 10, 31, 12, 0, tzinfo=TATA))} | Wykonawca A | temat: 'Raport z piątku'"
        " | temat nierozpoznany: NO_DATE | przyszedl przed oknem proby: rdzen go pomija\n"
        "----- TRESC\n"
        "40000008 tak\n"
        "----- WPISY: brak, bo temat nierozpoznany; numery dla poprawionego Raportu: 40000008\n"
        "\n"
        f"===== {chwila(datetime(2026, 11, 9, 18, 5, tzinfo=TATA))} | Wykonawca A | temat: 'Raport 08.11.2026'"
        " | dzien 2026-11-08\n"
        "----- TRESC\n"
        "40000001 tak wymiana gniazdka, usunięto awarię\n"
        "----- WPISY (1)\n"
        "  40000001 | tak | 'wymiana gniazdka, usunięto awarię'\n"
        "\n"
        f"===== {chwila(datetime(2026, 11, 9, 19, 0, tzinfo=TATA))} | Wykonawca A | temat: 'Raport bez daty'"
        " | temat nierozpoznany: NO_DATE\n"
        "----- TRESC\n"
        "Dzień dobry,\n"
        "\n"
        "40000006 tak\n"
        "-- \n"
        "Jan\n"
        "----- WPISY: brak, bo temat nierozpoznany; numery dla poprawionego Raportu: 40000006\n"
        "\n"
        f"===== {chwila(datetime(2026, 11, 9, 20, 0, tzinfo=TATA))} | Wykonawca B | temat: 'Raport 09.11.2026'"
        " | dzien 2026-11-09\n"
        "----- TRESC\n"
        "40000001 nie klient odmówił\n"
        "\n"
        "40000005 t\n"
        "----- WPISY (2)\n"
        "  40000001 | nie | 'klient odmówił'\n"
        "  40000005 | bez tak/nie: LETTER_YES | ''\n"
        "\n"
        f"===== {chwila(datetime(2026, 11, 9, 21, 0, tzinfo=TATA))} | Wykonawca A | temat: 'Raport 20.10.2026'"
        " | dzien 2026-10-20 | dzien spoza okna proby: rdzen pomija ten Raport\n"
        "----- TRESC\n"
        "40000007 tak montaż\n"
        "----- WPISY (1)\n"
        "  40000007 | tak | 'montaż'\n"
        "\n"
        f"===== {chwila(datetime(2026, 11, 10, 8, 0, tzinfo=TATA))} | Wykonawca A | temat: 'Raport 08.11.2026'"
        " | dzien 2026-11-08\n"
        "----- TRESC\n"
        "40000001 nie brak dostępu\n"
        "----- WPISY (1)\n"
        "  40000001 | nie | 'brak dostępu'\n"
        "\n"
        "===== NUMERY Z KILKOMA WPISAMI JEDNEGO WYKONAWCY Z JEDNEGO DNIA (1)\n"
        "Wykonawca A | dzien 2026-11-08 | 40000001\n"
        f"  {chwila(datetime(2026, 11, 9, 18, 5, tzinfo=TATA))} | 40000001 | tak | 'wymiana gniazdka, usunięto awarię'\n"
        f"  {chwila(datetime(2026, 11, 10, 8, 0, tzinfo=TATA))} | 40000001 | nie | 'brak dostępu'\n"
    )
    for dana in [SKRZYNKA, HASLO, WYKONAWCA, DRUGI, OBCY, "jan.testowy", "anna.probna", "Jan Testowy", "Anna Próbna"]:
        assert dana not in naglowek + wpisy


def test_przeglad_powstaje_takze_gdy_proba_potem_nie_przechodzi(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plik = tmp_path / "wpisy.txt"
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")], marks_seen=True) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port), "--przeglad", str(plik))

    assert (code, lines[-1]) == (1, "PROBA IMAP FAIL | flagi zmienione w 1 mailach")
    assert "  40000001 | tak | 'wymiana gniazdka, usunięto awarię'\n" in plik.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="prawa 0600 to prawa POSIX, których Windows nie ma")
@pytest.mark.parametrize("nadpisany", [False, True], ids=["nowy-plik", "nadpisany-plik-z-prawami-0644"])
def test_plik_przegladu_czyta_tylko_jego_wlasciciel(tmp_path: Path, capsys: pytest.CaptureFixture[str], nadpisany: bool) -> None:
    plik = tmp_path / "wpisy.txt"
    if nadpisany:
        plik.write_text("stary przegląd\n", encoding="utf-8")
        plik.chmod(0o644)
    nadpisz = ["--nadpisz"] if nadpisany else []
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")]) as atrapa:
        code, _ = proba(capsys, config(tmp_path), lokalnie(atrapa.port), "--przeglad", str(plik), *nadpisz)

    assert code == 0
    assert stat.S_IMODE(plik.stat().st_mode) == 0o600
    assert "stary przegląd" not in plik.read_text(encoding="utf-8")
    assert sorted(path.name for path in tmp_path.iterdir() if path.name.startswith(".wpisy")) == []


@pytest.mark.skipif(sys.platform == "win32", reason="prawa 0600 to prawa POSIX, których Windows nie ma")
def test_nadpisany_przeglad_nie_trafia_do_pliku_otwartego_wczesniej_z_dawnymi_prawami(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plik = tmp_path / "wpisy.txt"
    plik.write_text("stary przegląd\n", encoding="utf-8")
    plik.chmod(0o644)
    with plik.open(encoding="utf-8") as otwarty_wczesniej:
        with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")]) as atrapa:
            code, _ = proba(capsys, config(tmp_path), lokalnie(atrapa.port), "--przeglad", str(plik), "--nadpisz")
        widzi = otwarty_wczesniej.read()

    assert code == 0
    assert widzi == "stary przegląd\n"
    assert "40000001 | tak" in plik.read_text(encoding="utf-8")


def test_nieudana_podmiana_przegladu_zostawia_stary_plik_i_nie_zostawia_maili_obok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    plik = tmp_path / "wpisy.txt"
    plik.write_text("stary przegląd\n", encoding="utf-8")

    def odmowa(*_: object) -> None:
        raise PermissionError("dysk odmówił podmiany")

    monkeypatch.setattr(os, "replace", odmowa)
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")]) as atrapa:
        wynik = proba(capsys, config(tmp_path), lokalnie(atrapa.port), "--przeglad", str(plik), "--nadpisz")

    assert wynik == (1, ["PROBA IMAP FAIL | nie zapisano pliku przegladu: PermissionError"])
    assert plik.read_text(encoding="utf-8") == "stary przegląd\n"
    assert sorted(path.name for path in tmp_path.iterdir() if path.name.startswith(".wpisy")) == []


def _w_repozytorium(tmp_path: Path) -> Path:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / "notatki").mkdir()
    return tmp_path / "repo" / "notatki" / "wpisy.txt"


def _dowiazanie_do_repozytorium(tmp_path: Path) -> Path:
    (tmp_path / "notatki").symlink_to(_w_repozytorium(tmp_path).parent, target_is_directory=True)
    return tmp_path / "notatki" / "wpisy.txt"


def _istniejacy(tmp_path: Path) -> Path:
    (tmp_path / "wpisy.txt").write_text("stary przegląd\n", encoding="utf-8")
    return tmp_path / "wpisy.txt"


def _folder(tmp_path: Path) -> Path:
    (tmp_path / "wpisy").mkdir()
    return tmp_path / "wpisy"


W_GIT = "plik przegladu w repozytorium Git, a ma prawdziwe maile: podaj sciezke w ~/.t3/notes/<run>/"


@pytest.mark.parametrize(
    ("sciezka", "powod"),
    [
        pytest.param(lambda _: Path(__file__).resolve().parents[1] / "wpisy-przegladu.txt", W_GIT, id="w-klonie-narzedzia"),
        pytest.param(_w_repozytorium, W_GIT, id="w-folderze-repozytorium-git"),
        pytest.param(
            _dowiazanie_do_repozytorium,
            W_GIT,
            id="dowiazanie-do-folderu-repozytorium-git",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="dowiązanie na Windows wymaga uprawnień"),
        ),
        pytest.param(_istniejacy, "plik przegladu juz istnieje: podaj nowa sciezke albo --nadpisz", id="istniejacy-bez-nadpisz"),
        pytest.param(_folder, "plik przegladu to folder: podaj sciezke pliku", id="folder"),
        pytest.param(lambda tmp: tmp / "brak" / "wpisy.txt", "brak folderu pliku przegladu", id="bez-folderu"),
    ],
)
def test_przeglad_odmawia_sciezki_w_repozytorium_albo_istniejacego_pliku_bez_laczenia_ze_skrzynka(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sciezka: Callable[[Path], Path], powod: str
) -> None:
    plik = sciezka(tmp_path)
    przed = plik.read_bytes() if plik.is_file() else None
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami()) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port), "--przeglad", str(plik))

    assert (code, lines) == (1, [f"PROBA IMAP FAIL | {powod}"])
    assert atrapa.commands == []
    assert (plik.read_bytes() if plik.is_file() else None) == przed


def test_nadpisz_bez_pliku_przegladu_to_blad_wywolania(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as wyjscie:
        proba_skrzynki_raportow.main(["--config", str(config(tmp_path)), "--nadpisz"], connect=lokalnie(1))

    assert wyjscie.value.code == 2
    assert "--nadpisz dotyczy tylko --przeglad" in capsys.readouterr().err


def test_przeglad_rozwija_katalog_domowy_w_sciezce(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "dom").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "dom"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "dom"))
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")]) as atrapa:
        code, _ = proba(capsys, config(tmp_path), lokalnie(atrapa.port), "--przeglad", "~/wpisy.txt")

    assert code == 0
    assert "  40000001 | tak |" in (tmp_path / "dom" / "wpisy.txt").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="folder bez prawa zapisu to prawa POSIX")
def test_przeglad_ktorego_nie_da_sie_zapisac_konczy_sie_linia_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "tylko-odczyt").mkdir()
    (tmp_path / "tylko-odczyt").chmod(0o500)
    try:
        with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")]) as atrapa:
            wynik = proba(capsys, config(tmp_path), lokalnie(atrapa.port), "--przeglad", str(tmp_path / "tylko-odczyt" / "wpisy.txt"))
    finally:
        (tmp_path / "tylko-odczyt").chmod(0o700)

    assert wynik == (1, ["PROBA IMAP FAIL | nie zapisano pliku przegladu: PermissionError"])
