"""Interfejs HTTP otwarcia Rejestru zleceń z Ustawień Centrum i z Zatrzymania: Rejestr wskazany w Ustawieniach otwiera
się programem systemu. Rejestr niewybrany to 409, niedostępny (system nie odpowiada o pliku, np. OneDrive nie działa)
to 409, a brakujący to 404. Plik Folderów, którego system nie daje teraz czytać, to 409 o tym pliku, nie „najpierw
wybierz”.

Trasa tylko czyta Ustawienia (``settings_reads.readable_folders``) i niczego w nich nie zapisuje, więc jej odmowy
dotyczą pliku taty, nie zmiany Ustawień.
"""

from __future__ import annotations

from fastapi import APIRouter

from rozliczenia.centrum import refusal
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.centrum.settings_reads import readable_folders
from rozliczenia.file_state import file_state


def order_register_router(settings: CentrumSettings, platform: Platform) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    @router.post("/register/open", operation_id="openRegister", responses=NOT_FOUND_OR_CONFLICT)
    def open_register() -> common_contract.Opened:
        register = readable_folders(settings).register
        if register is None:
            raise refusal.register_not_chosen()
        match file_state(register):
            case "inaccessible":
                raise refusal.register_unavailable(register.name)
            case "missing":
                raise refusal.register_missing(register.name)
            case "file":
                pass
        platform.open_path(register)
        return common_contract.Opened(name=register.name)

    return router
