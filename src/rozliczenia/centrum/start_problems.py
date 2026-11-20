from __future__ import annotations

from pathlib import Path

from rozliczenia.centrum.tool_update import GUARDIAN_LEASE_S
from rozliczenia.message import Message, refer_if
from rozliczenia.tool_files import HOST, LOG_PATH, TOOL_ROOT

TITLE = "Centrum rozliczeń"
_SHORTCUT = "skrót „Centrum rozliczeń”"
_LOG_IN_EXPLORER = "\\".join(LOG_PATH.relative_to(TOOL_ROOT).parts)


def _address(port: int) -> str:
    return f"adres http://{HOST}:{port}/ na tym komputerze"


def port_taken(port: int) -> Message:
    return Message(
        code="PORT_ZAJETY",
        what=f"Centrum rozliczeń nie wystartowało, bo port {port} zajmuje inny program.",
        where=_address(port),
        action=(
            f"Uruchom ponownie komputer i kliknij {_SHORTCUT}. "
            f"{refer_if('Jeśli komunikat wraca', request='przekaż go')}"
        ),
    )


def other_version_running(port: int, version: str) -> Message:
    return Message(
        code="INNA_WERSJA_CENTRUM",
        what=f"Działa już Centrum rozliczeń w innej wersji ({version}).",
        where=_address(port),
        action=f"W karcie Centrum kliknij „Zamknij Centrum rozliczeń”, potem kliknij {_SHORTCUT} ponownie.",
    )


def missing_library(name: str) -> Message:
    return Message(
        code="BRAK_BIBLIOTEKI",
        what=f"Brakuje biblioteki potrzebnej Centrum rozliczeń ({name}).",
        where="Python na tym komputerze",
        action=(
            "W folderze narzędzia uruchom py -3 -m pip install -r requirements.txt, "
            f"potem kliknij {_SHORTCUT} ponownie."
        ),
    )


def unexpected_start_failure() -> Message:
    return Message(
        code="NIEOCZEKIWANY_BLAD_STARTU",
        what="Centrum rozliczeń nie wystartowało z nieoczekiwanego powodu.",
        where=f"dziennik Centrum {_LOG_IN_EXPLORER} w folderze narzędzia",
        action=(
            f"Kliknij {_SHORTCUT} ponownie. {refer_if('Jeśli komunikat wraca', request='przekaż dziennik')}"
        ),
    )


def unknown_workstation(file: Path) -> Message:
    return Message(
        code="NIEZNANE_STANOWISKO",
        what="Centrum rozliczeń nie wystartowało, bo nie rozpoznaje Stanowiska tego komputera.",
        where=f"plik {file.name} w folderze config narzędzia",
        action="Przekaż ten komunikat Maksowi.",
    )


def not_started_after_update() -> Message:
    return Message(
        code="NIE_WYSTARTOWALO_PO_AKTUALIZACJI",
        what="Centrum rozliczeń nie wystartowało po aktualizacji narzędzia.",
        where="narzędzie na tym komputerze",
        action="Przekaż ten komunikat Maksowi.",
    )


def update_finishing() -> Message:
    return Message(
        code="AKTUALIZACJA_SIE_KONCZY",
        what="Aktualizacja narzędzia jeszcze się kończy.",
        where="narzędzie na tym komputerze",
        action=f"Poczekaj {GUARDIAN_LEASE_S / 60:.0f} minut i kliknij {_SHORTCUT} ponownie.",
    )
