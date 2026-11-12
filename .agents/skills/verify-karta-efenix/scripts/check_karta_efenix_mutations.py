"""Show that explore_karta_efenix.py fails on broken variants of the window, the pace and the pricing, that its known
finding disappears when the window checks the order of its tab, and for each part of the known finding's shape a
broken variant just outside it (``BOUNDARIES``).

Each mutation runs on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must end the checker's report
with the expected line. A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to
the new code.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from silnik_mutacji import Edit, Mutation, check_all

BROWSER = Path("src/rozliczenia/efenix_browser.py")
PACE = Path("src/rozliczenia/efenix_pace.py")
PRICING = Path("src/rozliczenia/efenix_pricing.py")
ATRAPA = Path("tools/lib/atrapy/atrapa_efenix.py")
EXPLORER = (".agents/skills/verify-karta-efenix/scripts/explore_karta_efenix.py",)
NEW = "KARTA EFENIX: NOWE NARUSZENIE"

GUARD_WITHOUT_ORDER = Mutation(
    "strażnik zmiany statusu bez porównania order_id z _order_id",
    (
        Edit(
            BROWSER,
            "        if self._order_id is None or _field(request, ORDER_PARAM) != [self._order_id]:\n"
            "            return StatusChangeBlocked.OTHER_ORDER\n",
            "",
        ),
    ),
    EXPLORER,
    "tata otwiera w karcie zlecenie B przed Przekazaniem, a zielony „Zapisz” przekazuje do akceptacji zlecenie B",
    NEW,
)

QUANTITY_ELSEWHERE = Mutation(
    "skrypt strony Atrapy wysyła ilość z identyfikatorem zlecenia, którego nie ma na stronie",
    (
        Edit(
            ATRAPA,
            "post('action_save_index.php', {order_id: field.getAttribute('order_id'),",
            "post('action_save_index.php', {order_id: 'x' + field.getAttribute('order_id'),",
        ),
    ),
    EXPLORER,
    "ilość trafia w zlecenie, którego proces nie przeczytał, a tata nie otworzył",
    NEW,
)

BOUNDARIES: Final[Mapping[str, Mapping[str, tuple[Mutation, ...]]]] = {
    "zapis-w-zleceniu-z-karty": {
        # The same stray write, but Przekazanie do akceptacji, which the window's guard keeps today.
        "writes": (GUARD_WITHOUT_ORDER,),
        # The same stray write, but into an order Dad did not open in the tab.
        "targets": (QUANTITY_ELSEWHERE,),
    },
}
"""Broken variants just outside each part of the shape of the known finding (``StrayShape``), by its name and part:
the same harm, with that one part other than its story says, so each must give a new violation (#920).
``tests/test_mutacje_skilli.py`` reds an entry of ``KNOWN_FINDINGS`` with a part without one here."""

SAME_ORDER = (
    "    def _same_order(self, part: PagePart) -> None:\n"
    "        if parse_qs(urlparse(self._page.url).query).get(\"id\") != [self._order_id]:\n"
    "            raise WindowStop.of(part, OtherShape(Shape.LOGIN_FORM))\n\n"
)

MUTATIONS = (
    Mutation(
        "okno sprawdza zlecenie karty przed datą, Emmettem, po przeładowaniu i przed ilością",
        (
            Edit(BROWSER, "    def _read_order(self, response: Response | None) -> OrderPricing:\n", SAME_ORDER + "    def _read_order(self, response: Response | None) -> OrderPricing:\n"),
            Edit(
                BROWSER,
                "        self._click(self._element(Element.DATE_BUTTON, PagePart.DATE))\n",
                "        self._same_order(PagePart.DATE)\n        self._click(self._element(Element.DATE_BUTTON, PagePart.DATE))\n",
            ),
            Edit(
                BROWSER,
                "        button = self._element(Element.EMMETT_BUTTON, PagePart.EMMETT)\n",
                "        self._same_order(PagePart.EMMETT)\n        button = self._element(Element.EMMETT_BUTTON, PagePart.EMMETT)\n",
            ),
            Edit(
                BROWSER,
                "        loaded = self._read_order(reload.value)\n",
                "        self._same_order(PagePart.EMMETT)\n        loaded = self._read_order(reload.value)\n",
            ),
            Edit(
                BROWSER,
                "        field_id = self._positions.get(position)\n",
                "        self._same_order(PagePart.QUANTITY)\n        field_id = self._positions.get(position)\n",
            ),
        ),
        EXPLORER,
        "po poprawce zapisy po otwarciu przez tatę innego zlecenia kończą się Zatrzymaniem, więc znane ustalenie znika",
        "KARTA EFENIX: ZNALEZISKO ZNIKNĘŁO",
    ),
    Mutation(
        "ilość zapisywana bez przerwy przed nią",
        (Edit(PACE, "        if action.writes:\n", "        if action.writes and action is not WindowAction.QUANTITY:\n"),),
        EXPLORER,
        "tata nie ma punktu przed zapisem ilości, więc sprawdzenie nie mówi nic o nim",
        "KARTA EFENIX: LUKA MODELU",
    ),
    Mutation(
        "okno rzuca zwykły RuntimeError zamiast UnexpectedPage przy złej liczbie elementów",
        (Edit(BROWSER, "            raise WindowStop.of(part, ElementCount(element.selector, count))\n", "            raise RuntimeError(element.selector)\n"),),
        EXPLORER,
        "tata wraca na listę, okno nie znajduje elementu zlecenia i Uruchomienie kończy się EFENIX_BLAD_NIEOCZEKIWANY",
        NEW,
    ),
    Mutation(
        "Wycena bez wpisywania ilości z pliku",
        (Edit(PRICING, "    for position, quantity in plan.to_enter.items():\n        amount = efenix.enter_quantity(position, quantity)\n", ""),),
        EXPLORER,
        "przebieg bez taty nie dochodzi do zapisu ilości, więc punkty przed ilościami nie istnieją",
        NEW,
    ),
    *dict.fromkeys(mutation for parts in BOUNDARIES.values() for mutations in parts.values() for mutation in mutations),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
