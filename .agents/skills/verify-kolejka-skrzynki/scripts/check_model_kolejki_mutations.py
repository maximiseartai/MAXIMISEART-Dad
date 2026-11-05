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
        "lista issue bez issue, które KeyedBox sam założył (keyed_box.py labelled_issues: _opened, #879)",
        (Edit(MODEL, "Widoczne(q) == {i \\in 1..Len(issues) : i \\notin niewidoczne \\/ i \\in pamiec[q]}\n",
              "Widoczne(q) == {i \\in 1..Len(issues) : i \\notin niewidoczne}\n"),),
        _check("okres"),
        "druga Kontrola ilości okresu zakłada drugie issue okresu, zanim lista pokaże pierwsze",
        NEW,
    ),
    Mutation(
        "zakładanie bez wstrzymania po zakładaniu bez odpowiedzi (keyed_box.py _held, #879)",
        (Edit(MODEL, "Wstrzymane(q, r) == odczyt[q][r]\n", "Wstrzymane(q, r) == FALSE\n"),),
        _check("okres"),
        "ponowienie albo start Centrum po zgubionej odpowiedzi zakłada drugie issue okresu, zanim lista pokaże pierwsze",
        NEW,
    ),
    Mutation(
        "wstrzymanie liczone od chwili zakładania, a nie od chwili listy (keyed_box.py _held: listed_at, #879)",
        (Edit(MODEL, "Wstrzymane(q, r) == odczyt[q][r]\n", "Wstrzymane(q, r) == Swieze(q, r)\n"),),
        _check("okres"),
        "lista sprzed przedawnienia zapisu nie pokazuje issue, a zakładanie po przedawnieniu zakłada drugie",
        NEW,
    ),
    Mutation(
        "zapisy tylko w pamięci, więc nowe Centrum ich nie zna (keyed_box.py OPENING_FILE, #879)",
        (Edit(MODEL, "    /\\ UNCHANGED <<niewidoczne, zakladanie, wydanieNiewidoczne, falszywe, plik,",
              "    /\\ zakladanie' = [r \\in Rodzaje |-> \"brak\"]\n    /\\ UNCHANGED <<niewidoczne, wydanieNiewidoczne, falszywe, plik,"),),
        _check("okres"),
        "start Centrum zaraz po założeniu issue okresu zakłada drugie, zanim lista pokaże pierwsze",
        NEW,
    ),
    Mutation(
        "zakładanie Archiwum bez wstrzymania po zakładaniu bez odpowiedzi (keyed_box.py _held, #887)",
        (Edit(MODEL, "       \\/ /\\ ~Wstrzymane(q, \"archiwum\") /\\ ~PusteRepo /\\ wydania > 0\n",
              "       \\/ /\\ ~PusteRepo /\\ wydania > 0\n"),),
        _check("archiwum-lista"),
        "ponowienie po zgubionej odpowiedzi na założenie Archiwum dostaje 422 i dopisek, że plik czeka",
        NEW,
    ),
    Mutation(
        "Archiwum bez Archiwum, które KeyedBox sam założył (keyed_box.py archive: _archives, #887)",
        (Edit(MODEL, "(wydanieNiewidoczne /\\ ~pamiecWydania[q])", "wydanieNiewidoczne"),),
        _check("archiwum-lista"),
        "drugie Logi nowego okresu dostają odmowę drugiego Archiwum (422) i dopisek, że plik czeka",
        NEW,
    ),
    Mutation(
        "issue okresu zakładane bez szukania (_deliver_to_period: if found is None)",
        (Edit(MODEL, "          /\\ IF Najnowsze(q) = 0\n             THEN /\\ UNCHANGED <<nr, kom>>\n                  /\\ PoArchiwum(q, \"zaloz\", \"find_issue",
              "          /\\ IF TRUE\n             THEN /\\ UNCHANGED <<nr, kom>>\n                  /\\ PoArchiwum(q, \"zaloz\", \"find_issue"),),
        _check("okres"),
        "druga Kontrola ilości okresu zakłada drugie issue",
        NEW,
    ),
    Mutation(
        "Zgłoszenie zakładane bez szukania (_deliver_report: if found is not None)",
        (Edit(MODEL, "          /\\ IF Najnowsze(q) = 0\n             THEN /\\ UNCHANGED <<nr, kom>>\n                  /\\ Idz(q, \"zaloz\", \"labelled_issues",
              "          /\\ IF TRUE\n             THEN /\\ UNCHANGED <<nr, kom>>\n                  /\\ Idz(q, \"zaloz\", \"labelled_issues"),),
        _check("zgloszenie"),
        "drugie Zgłoszenie tego problemu zakłada drugie issue",
        NEW,
    ),
    Mutation(
        "Zgłoszenie, które wróciło, przejęte bez komentarza (_deliver_report: Delivered(found, ()) zamiast _settle)",
        (Edit(MODEL, "             ELSE /\\ nr' = Ustaw(nr, q, Najnowsze(q)) /\\ kom' = Ustaw(kom, q, Dopisz(Od(biez[q], 1)))\n"
              "                  /\\ Idz(q, \"czytaj\", \"_deliver_report:",
              "             ELSE /\\ nr' = Ustaw(nr, q, Najnowsze(q)) /\\ kom' = Ustaw(kom, q, <<>>)\n"
              "                  /\\ Idz(q, \"dostarczona\", \"_deliver_report:"),),
        _check("zgloszenie"),
        "drugie Zgłoszenie tego problemu dostaje znacznik, choć Skrzynka go nie ma",
        NEW,
    ),
    Mutation(
        "bez sprawdzenia identyfikatora przed wysyłką (_settle: każda część jako nowy komentarz)",
        (Edit(MODEL, "        plan == IF nowsza THEN <<>> ELSE Plan(nr[q], biez[q], kom[q])\n",
              "        plan == kom[q]\n"),),
        _check("okres"),
        "część, którą Skrzynka przyjęła przed zgaśnięciem Centrum, idzie po starcie drugi raz",
        NEW,
    ),
    Mutation(
        "starsza wersja po nowszej zmienia issue (_settle: newest > version)",
        (Edit(MODEL, "    LET nowsza == Nowsza(nr[q], biez[q])\n", "    LET nowsza == FALSE\n"),),
        _check("diagnoza"),
        "plik Logów sprzed Diagnozy, który dochodzi po niej, dopisuje część, której Diagnoza już nie ma",
        NEW,
    ),
    Mutation(
        "Diagnoza dopisuje komentarz zamiast poprawić (_put: edit_comment)",
        (Edit(MODEL, 'ELSE IF Wersja(i, w, k) < w THEN "popraw"\n', 'ELSE IF Wersja(i, w, k) < w THEN "dopisz"\n'),),
        _check("diagnoza"),
        "Uruchomienie po Diagnozie ma w issue okresu dwa komentarze z tą samą częścią Logów",
        NEW,
    ),
    Mutation(
        "część, której nowsza wersja nie ma, zostaje (_settle: _RETIRED)",
        (Edit(MODEL, "                  \\o Wycofaj(i, w)\n", "                  \\o <<>>\n"),),
        _check("diagnoza"),
        "w issue okresu zostaje część Logów sprzed Diagnozy, krótszej o tę część",
        NEW,
    ),
    Mutation(
        "Uwaga taty bez szukania issue po znaczniku (_deliver_new_issue: found)",
        (Edit(MODEL, "          /\\ IF Swoje(biez[q], q) = 0\n", "          /\\ IF TRUE\n"),),
        _check("nowe"),
        "Uwaga, której odpowiedź na założenie issue zginęła, dostaje drugie issue",
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
        (Edit(MODEL, "armed[q] \\/ stopped[q] \\/ nieczytany[q] \\/ odmowaArch[q] \\/ bezBlokady[q])\n",
              "armed[q] \\/ stopped[q] \\/ nieczytany[q] \\/ odmowaArch[q])\n"),),
        _check("dwa-procesy"),
        "Kontrola ilości, której wysyłkę przerwał koniec starego Centrum, czeka w kolejce nowego do następnej wysyłki",
        NEW,
    ),
    Mutation(
        "Uwaga taty zakłada dwa issue (_deliver_new_issue)",
        (Edit(MODEL, "          /\\ issues' = nowe /\\ niewidoczne' = zaLista /\\ Zapis(q, \"issue\", TRUE)\n",
              "          /\\ issues' = Append(nowe, [klucz |-> Klucz, tresc |-> <<Cialo(w)>>]) /\\ niewidoczne' = zaLista\n"
              "          /\\ Zapis(q, \"issue\", TRUE)\n"),),
        _check("nowe"),
        "każda Uwaga taty ma dwa issue, także bez awarii",
        NEW,
    ),
    Mutation(
        "nieudany komentarz pominięty zamiast końca wysyłki (_comment_all)",
        (
            Edit(
                MODEL,
                '          /\\ Stop(q, zapytanie \\o ": Unreachable przed skutkiem, przejscie staje")\n'
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
                '          /\\ Odrzuc(q, w, zapytanie \\o ": Rejected, plik czeka do nastepnego startu")\n'
                "          /\\ UNCHANGED <<issues, kom, stopped, nieczytany, sieci, zgubione>>\n",
                '          /\\ Idz(q, "usun", "comment: Rejected, _remove")\n'
                "          /\\ UNCHANGED <<issues, kom, stopped, nieczytany, rejected, sieci, zgubione>>\n",
            ),
        ),
        _check("odmowa-tresci"),
        "Uwaga taty, której komentarz Skrzynka odrzuciła, znika z kolejki bez części 2",
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
        (Edit(MODEL, "Od(w, a) == [i \\in 1..(Liczba(w) - a + 1) |-> a + i - 1]\n",
              "Od(w, a) == [i \\in 1..(Liczba(w) - a + 1) |-> Liczba(w) - i + 1]\n"),),
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
                "    /\\ UNCHANGED <<dysk, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, lista, biez, "
                "bezZnacznika,\n                   arch, odmowaArch, passes,",
                "    /\\ pc'[q] = \"plik\" \\/ UNCHANGED rejected\n"
                "    /\\ UNCHANGED <<dysk, issues, archiwa, zyje, draining, again, armed, undeleted, lista, biez, "
                "bezZnacznika,\n                   arch, odmowaArch, passes,",
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
        (Edit(MODEL, "            /\\ armed' = Ustaw(armed, q, armed[q] \\/ stopped[q] \\/ nieczytany[q] \\/ odmowaArch[q] \\/ bezBlokady[q])\n",
              "            /\\ UNCHANGED armed\n"),),
        _check("okres"),
        "po braku sieci wysyłka czeka do następnego startu albo następnej wysyłki",
        NEW,
    ),
    Mutation(
        "nieczytelny plik nie nastawia budzenia RETRY_S (_drain: _read_failed)",
        (Edit(MODEL, "armed[q] \\/ stopped[q] \\/ nieczytany[q] \\/ odmowaArch[q] \\/ bezBlokady[q])\n",
              "armed[q] \\/ stopped[q] \\/ odmowaArch[q] \\/ bezBlokady[q])\n"),),
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
        "plik w Archiwum bez sprawdzenia wersji z etykiety: kolejka usuwa swój plik i wysyła go drugi raz "
        "(_deliver_archive: seen >= version)",
        (Edit(MODEL, "                  ELSE IF \\E i \\in moje : archiwum[i] >= w\n", "                  ELSE IF FALSE\n"),),
        _check("archiwum"),
        "plik Logów, którego odpowiedź na upload zginęła, idzie do Archiwum drugi raz",
        NEW,
    ),
    Mutation(
        "Archiwum okresu zakładane bez szukania (_deliver_archive: listed is None)",
        (Edit(MODEL, "               /\\ IF wydania = 0 \\/ (wydanieNiewidoczne /\\ ~pamiecWydania[q])\n",
              "               /\\ IF TRUE\n"),),
        _check("archiwum"),
        "Diagnoza dostaje odmowę drugiego Archiwum okresu (422) i komentarz z dopiskiem, że plik czeka",
        NEW,
    ),
    Mutation(
        "plik starszej wersji nie ustępuje: upload bez remove (_deliver_archive: box.remove)",
        (Edit(MODEL, "                  ELSE IF moje /= {}\n", "                  ELSE IF FALSE\n"),),
        _check("archiwum"),
        "plik Logów z Diagnozą nigdy nie dochodzi, bo GitHub odrzuca drugi plik tej nazwy",
        NEW,
    ),
    Mutation(
        "odmowa Archiwum nie nastawia budzenia RETRY_S (_drain: _archive_refused)",
        (Edit(MODEL, "armed[q] \\/ stopped[q] \\/ nieczytany[q] \\/ odmowaArch[q] \\/ bezBlokady[q])\n",
              "armed[q] \\/ stopped[q] \\/ nieczytany[q] \\/ bezBlokady[q])\n"),),
        _check("archiwum"),
        "plik Logów, którego Archiwum nie przyjęło, czeka do następnej wysyłki albo startu, choć uprawnienie wróciło",
        NEW,
    ),
    Mutation(
        "409 pustego repozytorium jako brak sieci: przejście staje na pliku Logów (report_box.py "
        "GitHubReportBox.open_archive sprzed #860 r2)",
        (Edit(MODEL, "    /\\ UNCHANGED <<stopped, nieczytany>>\n"
              "    /\\ Czeka(q, \"open_archive: 409 Git Repository is empty, Rejected, ArchiveWaits\")\n",
              "    /\\ UNCHANGED arch\n    /\\ Stop(q, \"open_archive: 409 jako Unreachable, przejscie staje\")\n"),),
        _check("puste-repo"),
        "repozytorium Skrzynki bez commitu zatrzymuje komentarze Logów i wszystko, co czeka za nimi w kolejce",
        NEW,
    ),
    Mutation(
        "plik, którego Archiwum nie przyjęło, dostaje pełny znacznik i znika (_send_all: archive_waits)",
        (Edit(MODEL, 'IF czeka THEN "skomentowany" ELSE "oznaczony"', '"oznaczony"'),),
        _check("archiwum"),
        "plik Logów znika z kolejki, a Archiwum go nie ma",
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
