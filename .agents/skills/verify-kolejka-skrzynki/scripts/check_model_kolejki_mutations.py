"""Show that sprawdz_model_kolejki.py fails when the TLA+ model of the Kolejka Skrzynki loses a guard the code has.

Each mutation removes from ``model/KolejkaSkrzynki.tla`` one guard or step whose counterpart in
``src/rozliczenia/centrum/outbox.py`` the mutation names, runs on its own copy of the checkout (``tools/mutacje.py``)
and must end TLC's report with the expected line. A mutation whose anchor text is no longer in the model is reported
as NIEAKTUALNA: update it to the new model.

The copy of the checkout has no ignored TLC cache, so this script hands Java and ``tla2tools.jar`` of this checkout
to every command through ``TLC_JAVA`` and ``TLC_JAR``.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

ROOT = Path(__file__).resolve().parents[4]
MODEL = Path(".agents/skills/verify-kolejka-skrzynki/model/KolejkaSkrzynki.tla")
CHECK = ".agents/skills/verify-kolejka-skrzynki/scripts/sprawdz_model_kolejki.py"
NEW = "MODEL KOLEJKI: NOWE NARUSZENIE"


def _check(config: str) -> tuple[str, ...]:
    return (CHECK, "--config", config)


MUTATIONS = (
    Mutation(
        "issue okresu zakładane bez szukania (_deliver_to_period: if found is None)",
        (Edit(MODEL, "          /\\ IF Najnowsze = 0\n             THEN /\\ UNCHANGED <<nr, kom>>\n                  /\\ Idz(q, \"zaloz\", \"find_issue",
              "          /\\ IF TRUE\n             THEN /\\ UNCHANGED <<nr, kom>>\n                  /\\ Idz(q, \"zaloz\", \"find_issue"),),
        _check("okres"),
        "druga Kontrola ilości okresu zakłada drugie issue",
        NEW,
    ),
    Mutation(
        "Zgłoszenie zakładane bez szukania (_deliver_report: if found is not None)",
        (Edit(MODEL, "          /\\ IF Najnowsze = 0\n             THEN /\\ UNCHANGED <<nr, kom>>\n                  /\\ Idz(q, \"zaloz\", \"labelled_issues",
              "          /\\ IF TRUE\n             THEN /\\ UNCHANGED <<nr, kom>>\n                  /\\ Idz(q, \"zaloz\", \"labelled_issues"),),
        _check("zgloszenie"),
        "drugie Zgłoszenie tego problemu zakłada drugie issue",
        NEW,
    ),
    Mutation(
        "Zgłoszenie, które wróciło, przejęte bez komentarza (_deliver_report: issue.body == body)",
        (Edit(MODEL, "             ELSE IF issues[Najnowsze].tresc[1] = Cialo(biez[q])\n", "             ELSE IF TRUE\n"),),
        _check("zgloszenie"),
        "drugie Zgłoszenie tego problemu dostaje znacznik, choć Skrzynka go nie ma",
        NEW,
    ),

    Mutation(
        "_claimed zawsze pozwala wysyłać, a blokada folderu jest zawsze wolna (_drain bez _claimed i _folder_lock)",
        (
            Edit(MODEL, '    /\\ IF passes[Proc(q)] = "wolny"\n', "    /\\ IF TRUE\n"),
            Edit(MODEL, "            /\\ IF blokada = 0\n", "            /\\ IF TRUE\n"),
        ),
        _check("dwie-kolejki"),
        "dwie kolejki jednego folderu wysyłają naraz i zakładają dwa issue okresu",
        NEW,
    ),
    Mutation(
        "przejście bez blokady folderu (_drain bez _folder_lock)",
        (Edit(MODEL, "            /\\ IF blokada = 0\n", "            /\\ IF TRUE\n"),),
        _check("dwa-procesy"),
        "stare Centrum po zwolnieniu portu i nowe wysyłają z jednego folderu naraz i zakładają dwa issue okresu",
        NEW,
    ),
    Mutation(
        "blokada u innego procesu nie nastawia budzenia RETRY_S (_drain: _locked_out)",
        (Edit(MODEL, "armed[q] \\/ stopped[q] \\/ nieczytany[q] \\/ bezBlokady[q])\n", "armed[q] \\/ stopped[q] \\/ nieczytany[q])\n"),),
        _check("dwa-procesy"),
        "Kontrola ilości, której wysyłkę przerwał koniec starego Centrum, czeka w kolejce nowego do następnej wysyłki",
        NEW,
    ),
    Mutation(
        "Uwaga taty zakłada dwa issue (_deliver_new_issue)",
        (Edit(MODEL, "    /\\ \\/ /\\ issues' = nowe\n",
              "    /\\ \\/ /\\ issues' = Append(nowe, [klucz |-> Klucz, tresc |-> <<Cialo(w)>>])\n"),),
        _check("nowe"),
        "każda Uwaga taty ma dwa issue, także bez awarii",
        NEW,
    ),
    Mutation(
        "bez znacznika dostarczenia (replace_atomically w _send_all)",
        (Edit(MODEL, '          /\\ plik\' = [plik EXCEPT ![w] = "oznaczony"]\n', "          /\\ UNCHANGED plik\n"),),
        _check("nowe"),
        "plik, którego Windows nie dał usunąć, idzie po następnym starcie drugi raz i zakłada drugie issue Uwagi",
        NEW,
    ),
    Mutation(
        "plik z _undeleted wysyłany drugi raz w tej samej pracy Centrum",
        (Edit(MODEL, "            /\\ CASE w \\in undeleted[q] ->\n", "            /\\ CASE FALSE ->\n"),),
        _check("nowe"),
        "wysłana Uwaga bez znacznika, której pliku nie dało się usunąć, zakłada drugie issue przy następnym przejściu",
        NEW,
    ),
    Mutation(
        "bez wyjątku ryzyka z ADR 0015 (model: ryzyko jest osiągalne)",
        (Edit(MODEL, "            \\/ slady \\cap Ryzyka /= {}\n", "            \\/ FALSE\n"),),
        _check("nowe"),
        "zerwane połączenie po założeniu issue daje Uwadze taty drugie issue, co ADR 0015 przyjmuje",
        NEW,
    ),
    Mutation(
        "nieudany komentarz pominięty zamiast końca wysyłki (_comment_all)",
        (
            Edit(
                MODEL,
                '          /\\ Stop(q, "comment: Unreachable przed skutkiem, przejscie staje")\n'
                "          /\\ UNCHANGED <<issues, kom, rejected, zgubione, odmowy, odrzucone>>\n",
                "          /\\ kom' = Ustaw(kom, q, Tail(kom[q])) /\\ UNCHANGED <<stopped, nieczytany>>\n"
                '          /\\ Idz(q, IF Tail(kom[q]) = <<>> THEN "dostarczona" ELSE "komentuj", "comment: pominiety")\n'
                "          /\\ UNCHANGED <<issues, rejected, zgubione, odmowy, odrzucone>>\n",
            ),
        ),
        _check("okres"),
        "plik znika z kolejki, choć Skrzynka nie przyjęła części",
        NEW,
    ),
    Mutation(
        "odrzucony komentarz usuwa plik zamiast _rejected (_send_all: _remove po _listener.rejected)",
        (
            Edit(
                MODEL,
                '          /\\ IF Cel = "nowe" /\\ numer[w] = 0\n'
                "             THEN /\\ UNCHANGED rejected\n"
                '                  /\\ Idz(q, "zapisz_numer", "comment: Rejected po open_issue, Opened: plik zapamieta numer issue")\n'
                '             ELSE Odrzuc(q, w, "comment: Rejected, plik czeka do nastepnego startu")\n'
                "          /\\ UNCHANGED <<issues, kom, stopped, nieczytany, sieci, zgubione, slady>>\n",
                '          /\\ Idz(q, "usun", "comment: Rejected, _remove")\n'
                "          /\\ UNCHANGED <<issues, kom, stopped, nieczytany, rejected, sieci, zgubione, slady>>\n",
            ),
        ),
        _check("odmowa-tresci"),
        "Uwaga taty, której komentarz Skrzynka odrzuciła, znika z kolejki bez części 2",
        NEW,
    ),
    Mutation(
        "odrzucony komentarz po założeniu issue Uwagi nie zapisuje numeru (_send_all: replace_atomically po Opened)",
        (Edit(MODEL, '          /\\ IF Cel = "nowe" /\\ numer[w] = 0\n             THEN /\\ UNCHANGED rejected\n',
              "          /\\ IF FALSE\n             THEN /\\ UNCHANGED rejected\n"),),
        _check("odmowa-tresci"),
        "następny start zakłada drugie issue z tą samą Uwagą taty",
        NEW,
    ),
    Mutation(
        "plik z numerem issue zakłada nowe issue (_deliver: if opened is not None)",
        (Edit(MODEL, '                         /\\ IF Cel = "nowe" /\\ numer[w] = 0\n',
              '                         /\\ IF Cel = "nowe"\n'),),
        _check("odmowa-tresci"),
        "Uwaga taty, której plik zapamiętał numer issue, dostaje przy następnym starcie drugie issue",
        NEW,
    ),
    Mutation(
        "nieczytelny plik kolejki usunięty zamiast pominięty (_skip_unreadable: _remove)",
        (Edit(MODEL, '/\\ Idz(q, "plik", "_queued: read_text rzuca OSError, _read_failed, _skip_unreadable pomija plik")\n',
              '/\\ Idz(q, "usun", "_queued: read_text rzuca OSError, _remove")\n'),),
        _check("odczyt"),
        "Kontrola ilości, której pliku raz nie dało się odczytać, znika bez wysyłki",
        NEW,
    ),
    Mutation(
        "części komentowane od końca (_comment_all: reversed(comments))",
        (Edit(MODEL, "Od(a) == [i \\in 1..(Czesci - a + 1) |-> a + i - 1]\n",
              "Od(a) == [i \\in 1..(Czesci - a + 1) |-> Czesci - i + 1]\n"),),
        _check("okres"),
        "issue okresu ma część 2 przed częścią 1 drugiej Kontroli ilości",
        NEW,
    ),
    Mutation(
        "brak sieci pomija plik do następnego startu (_waiting: brak-sieci daje next)",
        (
            Edit(
                MODEL,
                '          /\\ Stop(q, "labelled_issues: Unreachable (brak sieci), przejscie staje")\n',
                '          /\\ Odrzuc(q, biez[q], "labelled_issues: Unreachable, plik do nastepnego startu")\n'
                "          /\\ UNCHANGED <<stopped, nieczytany>>\n",
            ),
            Edit(
                MODEL,
                "    /\\ UNCHANGED <<dysk, issues, zyje, draining, again, armed, undeleted, rejected, lista, biez, "
                "bezZnacznika, bezOchrony,\n                   passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, "
                "odmowy, bledyPliku, wylaczenia>>\n",
                "    /\\ UNCHANGED <<dysk, issues, zyje, draining, again, armed, undeleted, lista, biez, "
                "bezZnacznika, bezOchrony,\n                   passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, "
                "odmowy, bledyPliku, wylaczenia>>\n"
                '    /\\ pc\'[q] = "plik" \\/ UNCHANGED rejected\n',
            ),
        ),
        _check("okres"),
        "Kontrola ilości czeka do następnego startu Centrum, choć sieć wróciła",
        NEW,
    ),
    Mutation(
        "przejście, które stanęło, nie zapisuje _stopped_on",
        (Edit(MODEL, "    /\\ stopped' = Ustaw(stopped, q, TRUE)\n    /\\ UNCHANGED nieczytany\n",
              "    /\\ UNCHANGED <<stopped, nieczytany>>\n"),),
        _check("okres"),
        "po braku sieci nic nie nastawia budzenia i wysyłka czeka do następnego startu",
        NEW,
    ),
    Mutation(
        "brak budzenia RETRY_S (_drain: clock.after)",
        (Edit(MODEL, "            /\\ armed' = Ustaw(armed, q, armed[q] \\/ stopped[q] \\/ nieczytany[q] \\/ bezBlokady[q])\n",
              "            /\\ UNCHANGED armed\n"),),
        _check("okres"),
        "po braku sieci wysyłka czeka do następnego startu albo następnej wysyłki",
        NEW,
    ),
    Mutation(
        "nieczytelny plik nie nastawia budzenia RETRY_S (_drain: _read_failed)",
        (Edit(MODEL, "armed[q] \\/ stopped[q] \\/ nieczytany[q] \\/ bezBlokady[q])\n", "armed[q] \\/ stopped[q] \\/ bezBlokady[q])\n"),),
        _check("odczyt"),
        "Kontrola ilości, której pliku raz nie dało się odczytać, czeka do następnej wysyłki albo startu, choć sieć działa",
        NEW,
    ),
    Mutation(
        "budzenie RETRY_S nie prosi o przejście (_woken)",
        (Edit(MODEL, "    /\\ Budz(q)\n    /\\ krok' = \"_woken", "    /\\ UNCHANGED <<draining, again, pc>>\n    /\\ krok' = \"_woken"),),
        _check("okres"),
        "budzenie po braku sieci nic nie wysyła",
        NEW,
    ),
    Mutation(
        "post nie budzi wysyłki (send_in_background w post)",
        (Edit(MODEL, "          /\\ Budz(przez[w])\n", "          /\\ UNCHANGED <<draining, again, pc>>\n"),),
        _check("okres"),
        "Kontrola ilości czeka w kolejce do następnego startu Centrum",
        NEW,
    ),
    Mutation(
        "_again nie daje następnego przejścia (_drain)",
        (Edit(MODEL, "    /\\ IF again[q]\n", "    /\\ IF FALSE\n"),),
        _check("okres"),
        "wysyłka zapisana w trakcie przejścia czeka do następnego startu",
        NEW,
    ),
    Mutation(
        "przejście nie zeruje _draining",
        (Edit(MODEL, "       ELSE /\\ draining' = Ustaw(draining, q, FALSE)\n", "       ELSE /\\ UNCHANGED draining\n"),),
        _check("okres"),
        "po pierwszym przejściu każda prośba tylko ustawia _again, a kolejka stoi do restartu",
        NEW,
    ),
    Mutation(
        "resume nie wysyła (send_in_background w resume)",
        (Edit(MODEL, "    /\\ draining' = Ustaw(draining, q, TRUE)\n    /\\ pc' = Ustaw(pc, q, \"petla\")\n",
              "    /\\ UNCHANGED <<draining, pc>>\n"),),
        _check("okres"),
        "wysyłka z kolejki poprzedniej pracy Centrum czeka na następną wysyłkę",
        NEW,
    ),
    Mutation(
        "post zwraca True mimo OSError z os.replace (post: except OSError: return False)",
        (Edit(MODEL, "                /\\ UNCHANGED zakolejkowane\n"
              "                /\\ krok' = \"post: os.replace rzuca OSError, post zwraca False\"",
              "                /\\ zakolejkowane' = zakolejkowane \\cup {w}\n"
              "                /\\ krok' = \"post: os.replace rzuca OSError, post zwraca False\""),),
        _check("okres"),
        "Kontrola ilości, której pliku kolejki nie dało się zapisać, uchodzi za przyjętą i nie dociera do Skrzynki",
        NEW,
    ),
    Mutation(
        "post zwraca True, choć pliku .json.tmp już nie ma (post: except OSError: return False)",
        (Edit(MODEL, "                /\\ UNCHANGED <<zakolejkowane, bledyPliku>>\n"
              "                /\\ krok' = \"post: pliku .json.tmp",
              "                /\\ zakolejkowane' = zakolejkowane \\cup {w}\n"
              "                /\\ UNCHANGED bledyPliku\n"
              "                /\\ krok' = \"post: pliku .json.tmp"),),
        _check("dwa-procesy"),
        "Kontrola ilości, której plik .json.tmp usunął resume nowego Centrum, uchodzi za przyjętą i nie dociera do Skrzynki",
        NEW,
    ),
)


def _tlc_from_checkout() -> None:
    """Java i ``tla2tools.jar`` tego checkoutu (narzędzia ``sprawdz_aktualizacje.py``) dla poleceń w kopiach."""

    tools = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"
    spec = importlib.util.spec_from_file_location("sprawdz_aktualizacje", tools)
    if spec is None or spec.loader is None:
        sys.exit(f"BŁĄD: nie da się wczytać {tools}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.environ.setdefault("TLC_JAVA", module._java())
    os.environ.setdefault("TLC_JAR", str(module._tla_tools()))


if __name__ == "__main__":
    _tlc_from_checkout()
    raise SystemExit(check_all(MUTATIONS))
