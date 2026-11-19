"""Operacja Wpisania raportów na wejściu odczytu okna (``ReportInputs``), które buduje pamięć Wpisania
(``_memory.EnteringMemory``)."""

from __future__ import annotations

from . import _cells, _figures, _moves, _reading
from ._model import OrderDetail, OrderKey, ReportInputs, ReportsOutcome, note_order, problem_order


def enter_reports(inputs: ReportInputs) -> ReportsOutcome:
    """Operacja Wpisania raportów: ten sam wynik dla tych samych wejść, w dowolnej kolejności maili.

    Które maile są Raportami wykonawców i za które dni, mówi odczyt okna (``_reading.read_window``), ten sam co w
    Przypomnieniach o raporcie: mail od Wykonawcy bez żadnego Wpisu nie jest raportem (ADR 0041), Raport z dniem w
    okresie z Plikiem zbiorczym albo spoza okna daje tylko niezgodne Wpisy, a raport z błędem tematu (temat Raportu
    wykonawcy bez dnia zleceń wprost, z Wpisami, od Wykonawcy w dniu otwartym) niczego nie wpisuje i daje
    ``UnreadableSubject`` przy każdym dniu otwartym, za który się liczy (``_reading.read_window``), a bez niego bez dnia.
    Liczba Raportów wykonawców dnia w widoku Raporty liczy Raport za każdy dzień, za który jest przysłany, także z
    błędem tematu (``WindowRead.reported``), a dzień, za który liczy się raport z pomylonym tematem, ma jego dzień z
    tematu (``WindowRead.mistaken``). Które numery są w INTERMAX i ile mają
    zleceń, mówi każde odczytane zlecenie (``inputs.orders``, także z dni zamkniętych i po dziś), a okno mówi tylko, do
    których wolno pisać; Wpis zaczyna więc numer z co najmniej tyloma cyframi, ile ma najkrótszy numer odczytanego
    zlecenia (``_entries.entries``). Wpis trafia do zlecenia nadawcy z dnia z tematu, a bez niego do jedynego zlecenia tego
    numeru u innego Wykonawcy w tym dniu albo do jedynego zlecenia tego numeru z innego dnia: Przeniesienie zlecenia do
    nadawcy i na dzień z tematu albo, przy pomylonym temacie, do nadawcy w dniu zlecenia (ADR 0029,
    ``_matching.Board``, ``_moves.moved``), z informacją dla taty. Zlecenia numeru, który stoi w kilku przeczytanych
    wierszach (``inputs.present``, także w wierszu bez zlecenia), Wpis nie przenosi. Numer, którego INTERMAX nie ma w żadnym przeczytanym
    wierszu (``inputs.present``, jedyna odpowiedź na pytanie, czy INTERMAX ma numer), w postaci numeru z aplikacji
    firmowej (``ADDED_DIGITS`` cyfr), to Zlecenie dopisane z raportu pod zleceniami nadawcy w dniu z tematu, gdy ten
    jest Dniem uporządkowanym, a temat nie jest pomylony (inaczej, także dla numeru z wiersza bez zlecenia,
    ``UnknownNumber`` z powodem ``AddBar``), a jego Raportu wykonawcy nie poprawił późniejszy mail
    (``_corrections.uncorrected``); jego ``SKUTECZNE`` i ``CZYNNOŚCI ZREALIZOWANE`` trafiają do pamięci jak własne
    wpisy. Przy kilku Wpisach jednego zlecenia decyduje najpóźniejszy mail, także od innego Wykonawcy; mail z tą samą
    chwilą przyjścia i tym samym Message-ID rozstrzyga treść odczytu. Wpis zmienia pustą komórkę albo własny wpis z
    ``inputs.memory``, którego nikt od tamtej pory nie zmienił, a inna wartość komórki jest ręczna i zostaje z
    ``ManualDifference`` (``_cells.reconcile``); własny wpis pamięć ma tylko przy jedynym zleceniu numeru
    (``_moves._carried``). Wpis ``tak`` z Błędem opisu (Legenda czynności ``inputs.legend``) wpisuje się jak każdy, bo
    bez ``SKUTECZNE`` Przygotowanie pliku zbiorczego się zatrzymuje, a tata widzi przy nim problem
    ``FaultyDescription``, dopóki zlecenie nie dostanie poprawnego Wpisu (ADR 0039, ``_descriptions.entered``). Problem
    z błędu Wykonawcy znika, gdy Wykonawca przyśle poprawiony mail (``_corrections.standing``). Decyzja taty Wpisu na
    życzenie (``inputs.requested``) wpisuje Wpis ze znakiem zamiast ``tak``/``nie`` jak Wpis z chwilą kliknięcia
    (``_matching.Board.match``), a Wpis raportu z błędem tematu jak Wpis Raportu wykonawcy z dniem zlecenia w temacie
    (``WindowRead.matched``); zlecenie z Wpisem raportu z błędem tematu ma Wpis na życzenie, gdy Centrum wie, co
    wpisać (``WindowRead.offers``), a raport z błędem tematu, z którego nie ma już czego wpisać, jest informacją przy
    swoim dniu, nie problemem (``WindowRead.overtaken``).
    """

    window = inputs.window
    orders = tuple(inputs.orders)
    read = _reading.read_window(inputs)
    mails, matched, additions = read.mails, read.matched, read.additions
    moved = _moves.moved(matched.accepted, additions, orders, inputs.memory, window)
    after = {order.row: order for order in moved.orders}
    targets = {key: (after[order.row], entry) for key, (order, entry) in matched.targets.items()}
    changes, differences, memory = _cells.reconcile(targets, moved.orders, moved.memory, inputs.kept)
    added = {OrderKey(found.number, found.day, found.worker): found for found in additions}
    memory = _cells.with_added(memory, ((key, found.verdict, found.activities) for key, found in added.items()))
    problems_found = tuple(sorted({*read.standing, *differences}, key=problem_order))
    said = frozenset(key for key in read.said if window.opens(key.day))
    reported = [(day, worker) for worker, day in read.reported if window.opens(day)]
    details = [
        (key, OrderDetail(found.number, found.verdict.value, found.activities or None, True))
        for key, found in added.items()
    ]
    opened = [order for order in moved.orders if window.opens(order.key.day)]
    figures = _figures.worker_days(
        opened,
        said,
        reported,
        problems_found,
        changes,
        moved.rows,
        frozenset(targets),
        details,
        inputs.legend,
        read.mistaken,
        read.faulty_entries,
        read.offers,
        read.overtaken,
    )
    notes = tuple(sorted((*moved.notes, *matched.lost), key=note_order))
    return ReportsOutcome(changes, problems_found, figures, mails, memory, moved.moves, notes, moved.added, read.said)

