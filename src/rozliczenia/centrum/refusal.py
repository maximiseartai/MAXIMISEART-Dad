"""Odmowa żądania API Centrum rozliczeń: kod HTTP i zdanie dla taty, które ``create_app`` oddaje jako ``Problem``.

Moduł nie wczytuje FastAPI, bo odmawiają też reguły Centrum spoza tras, także katalog procesów
(``tests/test_granice_importow.py``).
"""

from __future__ import annotations

from rozliczenia.centrum.contract.common import Problem


class Refusal(Exception):
    """Serwer odmawia żądania; ``create_app`` zamienia odmowę na odpowiedź ``Problem``."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# Odmowy akcji na zasobie w OpenAPI: brak zasobu (404) albo zły stan (409), obie jako ``Problem``.
NOT_FOUND_OR_CONFLICT: dict[int | str, dict[str, object]] = {404: {"model": Problem}, 409: {"model": Problem}}
