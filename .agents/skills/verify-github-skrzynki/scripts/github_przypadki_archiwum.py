"""Przypadki Archiwum Logów okresu: ``archive``, ``open_archive``, ``upload``, ``remove`` i ``archive_url`` na
repozytorium próbnym z commitem (``TRIAL_ARCHIVE``).

Oczekiwany wynik każdego przypadku pochodzi z domeny (``GLOSSARY.md``: Archiwum Logów okresu, ADR 0015 z dopiskiem
#844, docstringi ``report_box`` i ``outbox._deliver_archive``), nie z przebiegu kodu. Przypadki biegną po kolei:
późniejszy bierze identyfikatory Archiwów i plików z wcześniejszych (``earlier``), a w odtwarzaniu z faktów swojego
nagrania. Plik leży w Archiwum pod nazwą ``packed_name`` z etykietą ``<nazwa> (wersja <wersja>)`` jak u Kolejki
wysyłki, a jego bajty to treść ``ArchiveFile.packed`` po rozpakowaniu w gzipie o tych samych bajtach na każdej maszynie
(``archived``), bo nagranie trzyma skrót ciała wysyłki.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
from typing import Final, cast
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from rozliczenia.centrum.outbox import ArchiveFile
from rozliczenia.centrum.report_box import (
    Archive,
    Asset,
    GitHubReportBox,
    Refused,
    Rejected,
    Removed,
)
from rozliczenia.client_data import logs_text

from github_przypadki_skrzynki import BAD_KEY, Client, archive_tag, marker
from github_wymiana import (
    CAUGHT_UP,
    TRIAL_ARCHIVE,
    Admin,
    Case,
    Facts,
    LiveTransport,
    from_trial_web,
)

PAGE: Final = 100
SETTLE_S: Final = 90.0
# Tekst pliku Logów przed spakowaniem (wersja przed Diagnozą i po niej, jak w ``GLOSSARY.md``: „Diagnoza podmienia
# plik swojego Uruchomienia”), bez danych taty.
BEFORE_DIAGNOSIS: Final = '{"diagnosis": null, "run": "%s"}\n'
AFTER_DIAGNOSIS: Final = '{"diagnosis": "BRAK_WZORCA", "run": "%s"}\n'
# Nagłówek gzip (RFC 1952) bez nazwy i chwili spakowania, z systemem „nieznany” (255), i największy blok bez kompresji.
_GZIP_HEADER: Final = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
_STORED_BLOCK: Final = 0xFFFF


def portable_gzip(content: bytes) -> bytes:
    """Plik gzip z ``content`` w blokach deflate bez kompresji: te same bajty na każdym Pythonie, systemie i zlib.

    Bajty ``gzip.compress(..., mtime=0)`` zależą od maszyny: Python 3.12 wpisuje do nagłówka system, dla którego
    zbudowano zlib (19 na macOS, 3 na Linuksie), Python 3.13 i nowszy zawsze 255, a zlib-ng, z którym Python 3.14 na
    Windows pakuje, koduje deflate po swojemu. Nagranie trzyma skrót ciała wysyłki, więc nagranie z Maca nie
    odtwarzało się na Windows w CI (run 41959078147, Mutation checks). Bloki bez kompresji (RFC 1951, 3.2.4) i CRC-32
    nie zależą od biblioteki.
    """

    blocks = [content[start : start + _STORED_BLOCK] for start in range(0, len(content), _STORED_BLOCK)] or [b""]
    deflate = b"".join(
        struct.pack("<BHH", index == len(blocks) - 1, len(block), len(block) ^ 0xFFFF) + block
        for index, block in enumerate(blocks)
    )
    return _GZIP_HEADER + deflate + struct.pack("<II", zlib.crc32(content), len(content) & 0xFFFFFFFF)


def archived(file: ArchiveFile) -> bytes:
    """Bajty pliku ``file`` w Archiwum przebiegu: plik Logów, który daje ``ArchiveFile.packed`` Kolejki wysyłki po
    rozpakowaniu, w ``portable_gzip``."""

    return portable_gzip(gzip.decompress(file.packed()))


@dataclass
class ArchiwumLive:
    """Przebieg na żywo: run, klucz klienta, klient bez nagrywania (przygotowanie), harness i rejestr założonego."""

    run: str
    key: str
    setup: GitHubReportBox
    setup_transport: LiveTransport
    admin: Admin
    ledger: Path
    earlier: dict[str, tuple[Facts, object]] = field(default_factory=dict)

    @property
    def marker(self) -> str:
        return marker(self.run)

    def note(self, entry: Facts) -> None:
        with self.ledger.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")

    def opened(self, case: str) -> Archive:
        """Archiwum założone w przypadku ``case`` (pierwszy element jego wyniku)."""

        _, outcome = self.earlier.get(case, ({}, None))
        found = outcome[0] if isinstance(outcome, tuple) and outcome else outcome
        if not isinstance(found, Archive):
            raise RuntimeError(f"brak warunku: przypadek {case} nie założył Archiwum ({outcome})")
        return found

    def sent(self, case: str) -> Asset:
        """Plik wysłany w przypadku ``case`` (pierwszy plik w jego wyniku)."""

        _, outcome = self.earlier.get(case, ({}, None))
        found = (
            next((item for item in outcome if isinstance(item, Asset)), None) if isinstance(outcome, tuple) else None
        )
        if found is None:
            raise RuntimeError(f"brak warunku: przypadek {case} nie wysłał pliku ({outcome})")
        return found

    def upload(self, archive_id: int, name: str, label: str, data: bytes) -> Asset:
        """Plik wysłany klientem (bez nagrania) jako warunek przypadku; inny wynik niż ``Asset`` przerywa przypadek."""

        outcome = self.setup.upload(archive_id, name, label, data, key=self.key)
        if not isinstance(outcome, Asset):
            raise RuntimeError(f"wysyłka pliku {name} dała {outcome} ({self.setup_transport.last})")
        return outcome

    def settle_releases(self, ids: set[int]) -> float:
        """Czeka, aż lista Release'ów GitHuba pokaże ``ids``, i zwraca, po ilu sekundach (lista issue nadąża po
        kilku sekundach, pomiar 5.11.2026)."""

        started = time.monotonic()
        while True:
            listed = {
                entry["id"]
                for entry in self.admin.pages(f"/repos/{TRIAL_ARCHIVE}/releases?")
                if isinstance(entry, dict)
            }
            if ids <= listed:
                return round(time.monotonic() - started, 1)
            if time.monotonic() - started > SETTLE_S:
                raise RuntimeError(f"lista Release'ów po {SETTLE_S:.0f} s: {len(listed & ids)} z {len(ids)}")
            time.sleep(2)


def second_tag(run: str) -> str:
    """Tag drugiego Archiwum runu (drugi okres): jego pliki przekraczają stronę listy."""

    return f"{archive_tag(run)}-strony"


def packed_name(run: str, index: int) -> str:
    """Nazwa pliku Logów runu z ``.gz`` w kształcie nazwy pliku Logów (``<chwila>-settlement-<Uruchomienie>.json.gz``),
    z identyfikatorem runu, po którym sprząta."""

    return f"{run}-settlement-{index:032x}.json.gz"


def _file(facts: Facts, text_key: str) -> ArchiveFile:
    return ArchiveFile(
        str(facts["tag"]),
        str(facts["tytul"]),
        str(facts["opis"]),
        str(facts["nazwa"]).removesuffix(".gz"),
        logs_text(str(facts[text_key])),
    )


def _label(name: str, version: str) -> str:
    """Etykieta pliku w Archiwum, jak ``outbox._asset_label``: nazwa i wersja wysyłki."""

    return f"{name} (wersja {version})"


def _asset_of(facts: Facts, name: str) -> Asset:
    found = cast(list[object], facts[name])
    return Asset(int(cast(int, found[0])), str(found[1]), str(found[2]), True)


def _as_facts(asset: Asset) -> list[object]:
    return [asset.id, asset.name, asset.label]


def _expect(outcome: object, expected: object) -> list[str]:
    return [] if outcome == expected else [f"wynik {describe(outcome)}, oczekiwane {describe(expected)}"]


def _by_id(archive: object) -> object:
    """Archiwum z plikami po kolei według identyfikatora: kolejność listy plików GitHuba domena nie ustala."""

    if not isinstance(archive, Archive):
        return archive
    return Archive(archive.id, tuple(sorted(archive.assets, key=lambda asset: asset.id)))


def _base(live: ArchiwumLive) -> Facts:
    return {
        "tag": archive_tag(live.run),
        "tytul": f"verify-github-skrzynki {live.run}: Archiwum",
        "opis": f"{live.marker}\n\nArchiwum Logów okresu w repozytorium próbnym z commitem.\n",
        "nazwa": packed_name(live.run, 1),
    }


# --- Archiwum ------------------------------------------------------------------------------------------------------


def _prepare_absent(live: ArchiwumLive, earlier: Facts) -> Facts:
    status, releases = live.admin.request("GET", f"/repos/{TRIAL_ARCHIVE}/releases?per_page=100")
    if status != 200 or releases != []:
        raise RuntimeError(f"brak warunku: repozytorium próbne Archiwum ma Release albo lista dała {status}")
    status, commits = live.admin.request("GET", f"/repos/{TRIAL_ARCHIVE}/commits?per_page=1")
    if status != 200 or not commits:
        raise RuntimeError(f"brak warunku: repozytorium próbne Archiwum nie ma commitu (lista commitów {status})")
    return _base(live)


def _archive(client: Client, facts: Facts) -> object:
    return client.box.archive(str(facts["tag"]), key=client.key)


def _open(client: Client, facts: Facts) -> object:
    return client.box.open_archive(str(facts["tag"]), str(facts["tytul"]), str(facts["opis"]), key=client.key)


def _judge_open(facts: Facts, outcome: object) -> list[str]:
    if not isinstance(outcome, Archive) or outcome.id <= 0 or outcome.assets:
        return [f"wynik {describe(outcome)}, oczekiwane Archive z identyfikatorem, bez plików"]
    return []


def _prepare_reopen(live: ArchiwumLive, earlier: Facts) -> Facts:
    """Fakty: po ilu sekundach lista Release'ów pokazała nowe Archiwum (pomiar 5.11.2026: lista zaraz po 201 była
    pusta) i co GitHub podaje jako najnowszy Release repozytorium, choć klient prosi ``make_latest: false``."""

    opened = live.opened("zalozenie")
    waited = live.settle_releases({opened.id})
    status, latest = live.admin.request("GET", f"/repos/{TRIAL_ARCHIVE}/releases/latest")
    return {
        **_base(live),
        "archiwum": opened.id,
        CAUGHT_UP: waited,
        "najnowsze_status": status,
        "najnowsze_id": latest.get("id") if isinstance(latest, dict) else None,
    }


def _reopen(client: Client, facts: Facts) -> object:
    return (_open(client, facts), client.box.archive(str(facts["tag"]), key=client.key))


def _judge_reopen(facts: Facts, outcome: object) -> list[str]:
    return _expect(outcome, (Rejected(), Archive(int(cast(int, facts["archiwum"])), ())))


def _prepare_find(live: ArchiwumLive, earlier: Facts) -> Facts:
    first = live.opened("zalozenie")
    tag = second_tag(live.run)
    other = live.setup.open_archive(
        tag,
        f"verify-github-skrzynki {live.run}: drugie Archiwum",
        live.marker,
        key=live.key,
    )
    if not isinstance(other, Archive):
        raise RuntimeError(f"założenie drugiego Archiwum dało {other} ({live.setup_transport.last})")
    live.note({"release": other.id, "tag": tag})
    return {
        "tag": archive_tag(live.run),
        "archiwum": first.id,
        "tag_drugiego": tag,
        "drugie": other.id,
        CAUGHT_UP: live.settle_releases({first.id, other.id}),
    }


def _find(client: Client, facts: Facts) -> object:
    box = client.box
    return (
        box.archive(str(facts["tag"]), key=client.key),
        box.archive(str(facts["tag_drugiego"]), key=client.key),
    )


def _judge_find(facts: Facts, outcome: object) -> list[str]:
    return _expect(
        outcome,
        (
            Archive(int(cast(int, facts["archiwum"])), ()),
            Archive(int(cast(int, facts["drugie"])), ()),
        ),
    )


# --- pliki ---------------------------------------------------------------------------------------------------------


def _prepare_upload(live: ArchiwumLive, earlier: Facts) -> Facts:
    base = _base(live)
    return {
        **base,
        "archiwum": live.opened("zalozenie").id,
        "tekst": BEFORE_DIAGNOSIS % live.run,
        "etykieta": _label(str(base["nazwa"]), f"{live.run}-0001"),
    }


def _send(client: Client, facts: Facts, text_key: str, label_key: str) -> tuple[object, object]:
    packed = archived(_file(facts, text_key))
    archive_id = int(cast(int, facts["archiwum"]))
    sent = client.box.upload(archive_id, str(facts["nazwa"]), str(facts[label_key]), packed, key=client.key)
    return (sent, client.box.archive(str(facts["tag"]), key=client.key))


def _upload(text_key: str, label_key: str) -> Callable[[Client, Facts], object]:
    return lambda client, facts: _send(client, facts, text_key, label_key)


def _judge_upload(facts: Facts, outcome: object) -> list[str]:
    sent, found = cast(tuple[object, object], outcome)
    expected = Asset(
        sent.id if isinstance(sent, Asset) else 0,
        str(facts["nazwa"]),
        str(facts["etykieta"]),
        True,
    )
    if sent != expected or expected.id <= 0:
        return [
            f"wynik {describe(sent)}, oczekiwane Asset z identyfikatorem, nazwą {facts['nazwa']} i etykietą, doszedł"
        ]
    return _expect(found, Archive(int(cast(int, facts["archiwum"])), (expected,)))


def _prepare_same_name(live: ArchiwumLive, earlier: Facts) -> Facts:
    base = _base(live)
    return {
        **base,
        "archiwum": live.opened("zalozenie").id,
        "plik": _as_facts(live.sent("wysylka-pliku")),
        "tekst_po_diagnozie": AFTER_DIAGNOSIS % live.run,
        "etykieta_po_diagnozie": _label(str(base["nazwa"]), f"{live.run}-0002"),
    }


def _judge_same_name(facts: Facts, outcome: object) -> list[str]:
    return _expect(
        outcome,
        (
            Rejected(),
            Archive(int(cast(int, facts["archiwum"])), (_asset_of(facts, "plik"),)),
        ),
    )


def _prepare_pages(live: ArchiwumLive, earlier: Facts) -> Facts:
    archive_id = int(cast(int, live.earlier["znalezienie-po-tagu"][0]["drugie"]))
    files = [
        live.upload(
            archive_id,
            packed_name(live.run, 100 + index),
            _label(packed_name(live.run, 100 + index), f"{live.run}-{index:04d}"),
            portable_gzip(f"{live.marker} {index}\n".encode()),
        )
        for index in range(1, PAGE + 2)
    ]
    return {
        "tag": second_tag(live.run),
        "archiwum": archive_id,
        "pliki": [_as_facts(asset) for asset in files],
    }


def _judge_pages(facts: Facts, outcome: object) -> list[str]:
    expected = Archive(
        int(cast(int, facts["archiwum"])),
        tuple(
            sorted(
                (
                    Asset(int(cast(int, i)), str(n), str(label), True)
                    for i, n, label in cast(list[list[object]], facts["pliki"])
                ),
                key=lambda a: a.id,
            )
        ),
    )
    if _by_id(outcome) == expected:
        return []
    found = len(outcome.assets) if isinstance(outcome, Archive) else outcome
    return [f"plików {found}, oczekiwane dokładnie {len(expected.assets)} wysłanych (doszłych, z nazwą i etykietą)"]


def _prepare_replace(live: ArchiwumLive, earlier: Facts) -> Facts:
    archive_id = live.opened("zalozenie").id
    other = live.upload(
        archive_id,
        packed_name(live.run, 2),
        _label(packed_name(live.run, 2), f"{live.run}-0001"),
        portable_gzip((BEFORE_DIAGNOSIS % live.run).encode()),
    )
    same, _ = live.earlier["plik-tej-samej-nazwy"]
    return {**same, "inny": _as_facts(other)}


def _replace(client: Client, facts: Facts) -> object:
    """Jak ``outbox._deliver_archive`` przy pliku starszej wersji: usunięcie, które ustępuje nowszemu, i wysyłka."""

    box, tag = client.box, str(facts["tag"])
    removed = box.remove(_asset_of(facts, "plik").id, key=client.key)
    after_remove = box.archive(tag, key=client.key)
    sent, after = _send(client, facts, "tekst_po_diagnozie", "etykieta_po_diagnozie")
    return (sent, removed, after_remove, after)


def _judge_replace(facts: Facts, outcome: object) -> list[str]:
    sent, removed, after_remove, after = cast(tuple[object, object, object, object], outcome)
    archive_id, other = int(cast(int, facts["archiwum"])), _asset_of(facts, "inny")
    problems = _expect(removed, Removed()) + _expect(_by_id(after_remove), Archive(archive_id, (other,)))
    new = Asset(
        sent.id if isinstance(sent, Asset) else 0,
        str(facts["nazwa"]),
        str(facts["etykieta_po_diagnozie"]),
        True,
    )
    if sent != new or new.id <= 0:
        return [
            *problems,
            f"wysyłka nowszego pliku: {describe(sent)}, oczekiwane Asset z etykietą nowszej wersji",
        ]
    return problems + _expect(_by_id(after), _by_id(Archive(archive_id, (other, new))))


def _prepare_link(live: ArchiwumLive, earlier: Facts) -> Facts:
    newest = live.sent("podmiana-pliku")
    status, entry = live.admin.request("GET", f"/repos/{TRIAL_ARCHIVE}/releases/assets/{newest.id}")
    address = entry.get("browser_download_url") if isinstance(entry, dict) else None
    if status != 200 or not isinstance(address, str):
        raise RuntimeError(f"przygotowanie: plik {newest.id} z Archiwum dał {status}")
    data = live.admin.download(newest.id)
    same, _ = live.earlier["plik-tej-samej-nazwy"]
    return {
        **{name: same[name] for name in ("tag", "tytul", "opis", "nazwa", "tekst_po_diagnozie")},
        "adres_pobrania": from_trial_web(address),
        "pobrane_sha256": hashlib.sha256(data).hexdigest(),
        "pobrane_dlugosc": len(data),
        "pobrane_rozpakowane": gzip.decompress(data).decode("utf-8"),
        "strona_z_kluczem_status": live.admin.web_status(address),
    }


def _link(client: Client, facts: Facts) -> object:
    archived_file = _file(facts, "tekst_po_diagnozie")
    return (archived_file.link, hashlib.sha256(archived(archived_file)).hexdigest())


def _judge_link(facts: Facts, outcome: object) -> list[str]:
    link, digest = cast(tuple[str, str], outcome)
    problems = (
        [] if link == facts["adres_pobrania"] else [f"odnośnik {link}, a GitHub podaje {facts['adres_pobrania']}"]
    )
    if digest != facts["pobrane_sha256"]:
        problems.append(f"pobrany plik ({facts['pobrane_dlugosc']} bajtów) nie jest bajt w bajt plikiem wysłanym")
    if facts["pobrane_rozpakowane"] != facts["tekst_po_diagnozie"]:
        problems.append("pobrany plik po rozpakowaniu nie jest plikiem Logów")
    return problems


def _prepare_bad_key(live: ArchiwumLive, earlier: Facts) -> Facts:
    return {
        "tag": archive_tag(live.run),
        "archiwum": live.opened("zalozenie").id,
        "inny": live.earlier["podmiana-pliku"][0]["inny"],
        "tag_nowego": f"{archive_tag(live.run)}-zly-klucz",
        "nazwa": packed_name(live.run, 3),
    }


def _bad_key(client: Client, facts: Facts) -> object:
    box, tag, archive_id = (
        client.box,
        str(facts["tag"]),
        int(cast(int, facts["archiwum"])),
    )
    name = str(facts["nazwa"])
    return {
        "archive": box.archive(tag, key=BAD_KEY),
        "open_archive": box.open_archive(str(facts["tag_nowego"]), "zły klucz", "zły klucz", key=BAD_KEY),
        "upload": box.upload(archive_id, name, name, portable_gzip(b"{}\n"), key=BAD_KEY),
        "remove": box.remove(_asset_of(facts, "inny").id, key=BAD_KEY),
        "archive kluczem klienta": _by_id(box.archive(tag, key=client.key)),
    }


def _judge_bad_key(facts: Facts, outcome: object) -> list[str]:
    found = cast(dict[str, object], outcome)
    problems = [
        f"{name}: wynik {describe(found.get(name))}, oczekiwane Refused()"
        for name in ("archive", "open_archive", "upload", "remove")
        if found.get(name) != Refused()
    ]
    after = found.get("archive kluczem klienta")
    other = _asset_of(facts, "inny")
    if not isinstance(after, Archive) or other not in after.assets or len(after.assets) != 2:
        problems.append(
            f"po złym kluczu Archiwum to {describe(after)}, oczekiwane dalej oba pliki z plikiem {other.id}"
        )
    return problems


def _is(expected: object) -> Callable[[Facts, object], list[str]]:
    return lambda facts, outcome: _expect(outcome, expected)


ARCHIVE_SOURCE: Final = (
    "GLOSSARY: Archiwum Logów okresu (Release z tagiem logi-<okres>, jeden plik .gz na Uruchomienie)"
)

CASES: Final[tuple[Case[ArchiwumLive, Client], ...]] = (
    Case(
        "archiwum-brak",
        "None: Archiwum z tym tagiem jeszcze nie ma",
        "report_box: „archive znajduje je po tagu z jego plikami … albo daje None”",
        _prepare_absent,
        _archive,
        _is(None),
    ),
    Case(
        "zalozenie",
        "Archive z identyfikatorem, bez plików",
        "report_box: „open_archive zakłada je bez plików”; " + ARCHIVE_SOURCE,
        _prepare_absent,
        _open,
        _judge_open,
    ),
    Case(
        "zalozenie-tego-samego-tagu",
        "Rejected, a archive po tagu daje to jedno Archiwum bez plików",
        "report_box.open_archive: „na tag, który już ma Release, 422 … to Rejected”",
        _prepare_reopen,
        _reopen,
        _judge_reopen,
    ),
    Case(
        "znalezienie-po-tagu",
        "każde z dwóch Archiwów po swoim tagu",
        "report_box.archive: „Release z tagiem tag z listy Release'ów”",
        _prepare_find,
        _find,
        _judge_find,
    ),
    Case(
        "wysylka-pliku",
        "Asset z nazwą i etykietą, doszedł; Archiwum ma ten jeden plik",
        "report_box: „upload wysyła plik”, Asset: nazwa, etykieta i czy plik doszedł w całości",
        _prepare_upload,
        _upload("tekst", "etykieta"),
        _judge_upload,
    ),
    Case(
        "plik-tej-samej-nazwy",
        "Rejected, a w Archiwum zostaje plik pierwszej wersji",
        "report_box.upload: „Plik o tej nazwie, który już jest w Archiwum, to Rejected”",
        _prepare_same_name,
        _upload("tekst_po_diagnozie", "etykieta_po_diagnozie"),
        _judge_same_name,
    ),
    Case(
        "pliki-strony",
        f"dokładnie {PAGE + 1} wysłanych plików z dwóch stron listy",
        "report_box.archive: „jego pliki, oba strona po stronie”",
        _prepare_pages,
        _archive,
        _judge_pages,
    ),
    Case(
        "podmiana-pliku",
        "remove: Removed i zostaje tylko inny plik; potem nowsza wersja pod tą samą nazwą obok niego",
        "outbox._deliver_archive: „plik starszej wersji … ustępuje (remove), a potem idzie ten (upload)”; GLOSSARY: "
        "„plik nowszej wersji podmienia plik starszej”",
        _prepare_replace,
        _replace,
        _judge_replace,
    ),
    Case(
        "adres-pobrania",
        "archive_url to adres pobrania pliku od GitHuba, a pobrany plik jest bajt w bajt wysłanym i po rozpakowaniu "
        "plikiem Logów",
        "report_box.archive_url; GLOSSARY: plik .gz „po rozpakowaniu jest bajt w bajt plikiem Logów”",
        _prepare_link,
        _link,
        _judge_link,
    ),
    Case(
        "zly-klucz",
        "Refused w każdym kroku Archiwum, a pliki zostają",
        "report_box.Refused: klucz nieważny; „jego brak to Refused z kroków Archiwum”",
        _prepare_bad_key,
        _bad_key,
        _judge_bad_key,
    ),
)

# Czego przebieg nie sprawdza i dlaczego; zawsze w wyniku jako NIESPRAWDZONE.
UNCHECKED: Final = (
    (
        "bez-uprawnienia-tresci",
        "klucz bez uprawnienia Contents (403 przy Release'ach): Maks nie ma klucza repozytorium próbnego bez niego; "
        "sprawdzony jest tylko zły klucz (401)",
    ),
    (
        "urwany-plik",
        "plik urwany w trakcie wysyłki (state inny niż uploaded): przebieg nie umie przerwać wysyłki w połowie",
    ),
    (
        "lista-zaraz-po-zalozeniu",
        "klient, który pyta o listę Release'ów zaraz po założeniu Archiwum (jak Kolejka przy drugim pliku Logów nowego "
        "okresu w tym samym przejściu): przypadki czekają, aż lista pokaże Archiwum, a 422 na open_archive tego samego "
        "tagu nagrano dopiero po tym",
    ),
    (
        "odnosnik-w-przegladarce",
        "odnośnik otwarty w przeglądarce Maksa zalogowanej do GitHuba: przebieg porównuje go z browser_download_url "
        "pliku i pobiera plik przez API",
    ),
)


def describe(outcome: object) -> str:
    if isinstance(outcome, Archive) and len(outcome.assets) > 3:
        return f"Archive({outcome.id}, {len(outcome.assets)} plików)"
    if isinstance(outcome, Archive):
        return (
            f"Archive({outcome.id}, ("
            + ", ".join(f"Asset({a.id}, {a.name}, {a.uploaded})" for a in outcome.assets)
            + "))"
        )
    if isinstance(outcome, tuple):
        return "(" + ", ".join(describe(item) for item in outcome) + ")"
    if isinstance(outcome, dict):
        return "{" + ", ".join(f"{name}: {describe(value)}" for name, value in outcome.items()) + "}"
    return repr(outcome)


def created(outcome: object) -> list[int]:
    """Identyfikatory Archiwów, które wynik mówi, że są w repozytorium (do rejestru sprzątania)."""

    if isinstance(outcome, Archive):
        return [outcome.id]
    if isinstance(outcome, tuple | list):
        return [number for item in outcome for number in created(item)]
    if isinstance(outcome, dict):
        return [number for item in outcome.values() for number in created(item)]
    return []
