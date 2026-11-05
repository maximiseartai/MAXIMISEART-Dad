"""Show that explore_wycena_efenix.py fails on broken variants of the Wycena w efenix, the defects of #802, #808, #758,
#891, #895 at every „Załaduj do zlecenia”, #889 and #908, a reload waited for shorter than its answer, a closed tab not seen
in the window's action, a dziennik that names an order only after the window changed it, the completion to the file only
upwards of #960 (ADR 0026), and for each part of the shape of each accepted risk of the explorer a broken variant just
outside it (``BOUNDARIES``, none today).

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) with the axes and request roles that reach it,
one browser at a time, and must end the checker's report with the expected line. A mutation whose anchor text is no
longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

BROWSER = Path("src/rozliczenia/efenix_browser.py")
PRICING = Path("src/rozliczenia/efenix_pricing.py")
POSITIONS = Path("src/rozliczenia/efenix_positions.py")
EXPLORER = ".agents/skills/verify-wycena-efenix/scripts/explore_wycena_efenix.py"
NEW = "WYCENA EFENIX: NOWE NARUSZENIE"


def explorer(variant: str, *roles: str) -> tuple[str, ...]:
    return (EXPLORER, "--variant", variant, "--rola", *roles, "--rownolegle", "1")


BOUNDARIES: Final[Mapping[str, Mapping[str, tuple[Mutation, ...]]]] = {}
"""Broken variants just outside each part of the shape of each accepted risk and known finding of the explorer
(``RiskShape``), by its name and part: the same harm as the risk's, but with that one part other than its story says,
so each must give a new violation (#920). ``tests/test_mutacje_skilli.py`` reds an entry of ``ACCEPTED_RISKS`` or
``KNOWN_FINDINGS`` with a part without one here; a part that admits every member of its enum has none."""


MUTATIONS = (
    Mutation(
        "#808: strona błędu HTTP zamiast strony zlecenia to strona w innej budowie",
        (
            Edit(
                BROWSER,
                "            if response is not None and not response.ok:\n                raise UnexpectedPage(PagePart.ORDER, HttpStatus(",
                "            if False:\n                raise UnexpectedPage(PagePart.ORDER, HttpStatus(",
            ),
        ),
        explorer("odpowiedzi", "strona-zlecenia"),
        "Maks dostaje „efenix się zmienił” przy błędzie serwera efenix",
        NEW,
    ),
    Mutation(
        "#808: strona przeładowana po Wycenie Emmetta czytana bez jej odpowiedzi",
        (Edit(BROWSER, "        loaded = self._read_order(reload.value)\n", "        loaded = self._read_order(None)\n"),),
        explorer("odpowiedzi", "strona-po-emmetcie"),
        "błąd serwera po „Załaduj do zlecenia” wygląda jak zmieniony efenix",
        NEW,
    ),
    Mutation(
        "#808: formularz logowania pod adresem zlecenia to strona w innej budowie",
        (Edit(BROWSER, "            if self._page.locator(_LOGIN_FORM).count() > 0:\n", "            if False:\n"),),
        explorer("odpowiedzi", "strona-po-dacie"),
        "wylogowanie wygląda jak zmieniony efenix",
        NEW,
    ),
    Mutation(
        "#802: błąd przeglądarki bez nazwy działania okna",
        (
            Edit(
                BROWSER,
                "        raise UnexpectedPage(part, failed.failure) from failed.__cause__\n",
                "        raise UnexpectedPage(part, BrowserFailure(failed.failure.error_type, None)) from failed.__cause__\n",
            ),
        ),
        explorer("odciecia", "data-wykonania"),
        "Logi nie mówią, przy którym działaniu sieć zawiodła",
        NEW,
    ),
    Mutation(
        "#802: okno czeka na nagłówki odpowiedzi zamiast na całą treść",
        (
            Edit(
                BROWSER,
                "            with self._page.expect_request_finished(wanted, timeout=self._timeout_ms) as finished:\n"
                "                act()\n"
                "            response = finished.value.response()\n",
                "            with self._page.expect_response(lambda answer: wanted(answer.request), timeout=self._timeout_ms) as finished:\n"
                "                act()\n"
                "            response = finished.value\n",
            ),
        ),
        explorer("odciecia", "ilosc"),
        "odpowiedź, która stanęła w połowie, wiesza Wycenę w efenix",
        NEW,
    ),
    Mutation(
        "#758: zamknięta karta w czasie czekania na logowanie taty",
        (
            Edit(
                BROWSER,
                "                if self._page.is_closed():\n                    raise WindowClosed(PagePart.LIST, Closed.DURING_LOGIN)\n",
                "                if False:\n                    raise WindowClosed(PagePart.LIST, Closed.DURING_LOGIN)\n",
            ),
        ),
        explorer("logowanie", "lista-na-starcie"),
        "Centrum czeka 15 minut na logowanie w oknie, którego już nie ma",
        NEW,
    ),
    Mutation(
        "#891: lista ze statusem błędu po zalogowaniu taty to dalsze czekanie na logowanie",
        (
            Edit(
                BROWSER,
                "        if response.status >= 400:\n"
                "            raise UnexpectedPage(PagePart.LIST, HttpStatus(response.status))\n"
                "        location = urlparse(",
                "        location = urlparse(",
            ),
        ),
        explorer("logowanie", "lista-na-starcie"),
        "po 15 minutach Komunikat mówi, że tata się nie zalogował, choć efenix odpowiada błędem serwera",
        NEW,
    ),
    Mutation(
        "zamknięta karta w działaniu okna nie jest zamkniętym oknem",
        (
            Edit(
                BROWSER,
                "                if efenix.closed and not isinstance(error, WindowClosed):\n",
                "                if False and not isinstance(error, WindowClosed):\n",
            ),
        ),
        explorer("zamkniete-okno", "data-wykonania", "strona-zlecenia"),
        "tata zamyka okno, a dostaje „okno zatrzymane” i Maks szuka zmienionego efenix",
        NEW,
    ),
    Mutation(
        "#895: treść odpowiedzi „Załaduj do zlecenia” czytana po przeładowaniu strony przy każdym Emmetcie",
        (
            Edit(
                BROWSER,
                "                raise UnexpectedPage(PagePart.EMMETT, OtherShape(Shape.ANSWER_REDIRECT))\n        loaded = ",
                "                raise UnexpectedPage(PagePart.EMMETT, OtherShape(Shape.ANSWER_REDIRECT))\n"
                "            self._page.wait_for_timeout(1500)\n"
                "            self._text(answer)\n"
                "        loaded = ",
            ),
        ),
        explorer("odpowiedzi", "zaladuj-do-zlecenia"),
        "każda Wycena staje na pierwszym Emmetcie, choć efenix załadował Wycenę Emmetta",
        NEW,
    ),
    Mutation(
        "#889: kwota 0 po „Załaduj do zlecenia” zawsze znaczy, że Emmett nic nie zaproponował",
        (Edit(BROWSER, "        if not nothing_proposed and loaded.amount == 0:\n", "        if False and loaded.amount == 0:\n"),),
        explorer("odpowiedzi", "zaladuj-do-zlecenia"),
        "efenix odmówił Wyceny Emmetta, a okno wpisuje ilości pliku do zlecenia bez Emmetta",
        NEW,
    ),
    Mutation(
        "#908: puste okno Emmetta po padniętej propozycji znaczy, że Emmett nic nie zaproponował",
        (
            Edit(
                BROWSER,
                "        nothing_proposed = shown is False and _came_whole(asked.value)\n",
                "        nothing_proposed = shown is False\n",
            ),
        ),
        explorer("odpowiedzi", "zaladuj-do-zlecenia"),
        "propozycja Emmetta padła, efenix odmówił Wyceny Emmetta, a okno wpisuje ilości pliku do zlecenia bez Emmetta",
        NEW,
    ),
    Mutation(
        "okno czeka na przeładowanie po „Załaduj do zlecenia” o sekundę krócej niż na odpowiedź",
        (
            Edit(
                BROWSER,
                'self._page.expect_navigation(wait_until="load", timeout=self._timeout_ms) as reload:',
                'self._page.expect_navigation(wait_until="load", timeout=self._timeout_ms - 1000) as reload:',
            ),
        ),
        explorer("granica-czasu", "zaladuj-do-zlecenia"),
        "efenix odpowiada wolno, ale w czasie okna, a Wycena staje na Emmetcie",
        NEW,
    ),
    Mutation(
        "„zaczynam zlecenie” w dzienniku dopiero po działaniach okna przy zleceniu",
        (
            Edit(
                PRICING,
                "                        journal.begun(order.row, done + 1, total)\n"
                "                        window = efenix_trace.traced(efenix, order, trace, clock)\n"
                "                        outcome = _outcome(order, window if pacing is None else pacing.window(window), forbidden)\n",
                "                        window = efenix_trace.traced(efenix, order, trace, clock)\n"
                "                        outcome = _outcome(order, window if pacing is None else pacing.window(window), forbidden)\n"
                "                        journal.begun(order.row, done + 1, total)\n",
            ),
        ),
        explorer("zabity-proces", "data-wykonania"),
        "Centrum zgasło w trakcie zlecenia, a Logi Urwanego Uruchomienia nie mówią, które zlecenie zmieniło się w efenix",
        NEW,
    ),
    Mutation(
        "#960: Wycena Emmetta także do zlecenia z ilościami (_outcome: bez not any(opened.quantities.values()))",
        (Edit(PRICING, "    if not any(opened.quantities.values()):\n", "    if True:\n"),),
        explorer("zabity-proces", "ilosc"),
        "ponowne uruchomienie ładuje Emmetta do zlecenia z ilościami i czyści je",
        NEW,
    ),
    Mutation(
        "#960: wycena, która już jest, tylko porównana, a nie dokończona do pliku",
        (
            Edit(
                PRICING,
                "    if not any(opened.quantities.values()):\n",
                "    if any(opened.quantities.values()) and completion(file, opened.quantities).to_enter:\n"
                "        return OrderError(OtherAmount(opened.amount, order.amount))\n"
                "    if not any(opened.quantities.values()):\n",
            ),
        ),
        explorer("zabity-proces", "ilosc"),
        "tata dostaje błąd zlecenia, które narzędzie zaczęło, zamiast zlecenia dokończonego do pliku",
        NEW,
    ),
    Mutation(
        "#960: ilość z pliku tylko w pozycjach pustych (completion jak przed #960)",
        (Edit(POSITIONS, "if on_page.get(position, 0) < quantity}", "if on_page.get(position, 0) == 0}"),),
        explorer("zamkniete-okno", "szukanie"),
        "ilość Emmetta mniejsza niż plik (S) zostaje, a zlecenie kończy się błędem kwoty",
        NEW,
    ),
    Mutation(
        "#960: dokończenie także w dół (completion wpisuje plik w pozycji, w której efenix ma więcej)",
        (Edit(POSITIONS, "if on_page.get(position, 0) < quantity}", "if on_page.get(position, 0) != quantity}"),),
        explorer("zamkniete-okno", "szukanie"),
        "narzędzie obniża w efenix ilość większą niż w pliku",
        NEW,
    ),
    Mutation(
        "#960: bez Ostrzeżenia Emmetta (_completed: bez if plan.excess)",
        (Edit(PRICING, "    if plan.excess:\n        return EmmettWarning(plan.excess)\n", ""),),
        explorer("zamkniete-okno", "szukanie"),
        "pozycja z ilością większą niż plik daje błąd kwoty zamiast Ostrzeżenia Emmetta z pozycją",
        NEW,
    ),
    *(mutation for parts in BOUNDARIES.values() for mutations in parts.values() for mutation in mutations),
    Mutation(
        "okno klika Przekazanie do akceptacji",
        (
            Edit(
                BROWSER,
                "        button = self._only(_EMMETT_BUTTON, PagePart.EMMETT)\n",
                '        self._click(self._only("#button_forward_to_accept", PagePart.EMMETT))\n'
                "        button = self._only(_EMMETT_BUTTON, PagePart.EMMETT)\n",
            ),
        ),
        explorer("zamkniete-okno", "szukanie"),
        "okno używa przycisku, który należy do taty",
        NEW,
    ),
    Mutation(
        "Komunikat Zatrzymania zawsze mówi, że w efenix nic się nie zmieniło",
        (Edit(PRICING, "                with _efenix_stops(lambda: efenix.sent_change, stopped):\n", "                with _efenix_stops(lambda: False, stopped):\n"),),
        explorer("zamkniete-okno", "ilosc"),
        "tata myśli, że efenix jest nietknięty, a wycena jest w połowie",
        NEW,
    ),
    Mutation(
        "Zatrzymanie bez Znaczników efenix gotowych zleceń",
        (Edit(PRICING, "            _mark(source, scope, results)\n            raise\n", "            raise\n"),),
        explorer("zamkniete-okno", "strona-zlecenia"),
        "gotowe zlecenie sprzed Zatrzymania nie ma Znacznika efenix",
        NEW,
    ),
)

if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
