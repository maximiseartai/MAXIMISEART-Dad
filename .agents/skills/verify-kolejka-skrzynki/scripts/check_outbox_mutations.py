"""Show that explore_outbox.py fails on broken variants of the Kolejka Skrzynki Zgłoszeń.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) and must end the checker's report with the
expected line. A mutation whose anchor text is no longer in ``outbox.py`` (or ``report_box.py``, whose reading of
GitHub's answers the checker takes from the real adapter, or ``keyed_box.py``, whose list after its own writes covers
the lag of GitHub's issue list) is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

VERIFIED = Path("src/rozliczenia/centrum/outbox.py")
REPORT_BOX = Path("src/rozliczenia/centrum/report_box.py")
KEYED_BOX = Path("src/rozliczenia/centrum/keyed_box.py")
EXPLORER = ".agents/skills/verify-kolejka-skrzynki/scripts/explore_outbox.py"
NEW = "KOLEJKA: NOWE NARUSZENIE"

MUTATIONS = (
    Mutation(
        "nieudany komentarz nowego issue pominięty zamiast końca wysyłki (_comment_all)",
        (
            Edit(
                VERIFIED,
                "        answer = box.comment(number, comment)\n        if not isinstance(answer, Commented):\n            return answer\n",
                "        answer = box.comment(number, comment)\n        if not isinstance(answer, Commented):\n            continue\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "plik znika z kolejki, choć Skrzynka nie przyjęła części",
        NEW,
    ),
    Mutation(
        "nieudany komentarz znalezionego issue pominięty zamiast końca wysyłki (_settle)",
        (
            Edit(
                VERIFIED,
                "        answer = _put(number, seen.sent.get(part), text, version, box)\n"
                "        if not isinstance(answer, Commented):\n            return answer\n",
                "        answer = _put(number, seen.sent.get(part), text, version, box)\n"
                "        if not isinstance(answer, Commented):\n            continue\n",
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "plik znika z kolejki, choć Skrzynka nie przyjęła części odnośnika do Logów",
        NEW,
    ),
    Mutation(
        "do znalezionego issue okresu bez pierwszej części",
        (
            Edit(
                VERIFIED,
                "for part, text in enumerate(post.parts, start=1))\n",
                "for part, text in enumerate(post.parts[1:], start=2))\n",
            ),
        ),
        (EXPLORER, "--scope", "watek-okresu"),
        "druga Kontrola ilości okresu traci część 1",
        NEW,
    ),
    Mutation(
        "issue okresu zakładane bez szukania",
        (
            Edit(
                VERIFIED,
                "    if found is None:\n        step = _deliver_archive(post, version, box, archive_open=archive_open)\n",
                "    if True:\n        step = _deliver_archive(post, version, box, archive_open=archive_open)\n",
            ),
        ),
        (EXPLORER, "--scope", "watek-okresu"),
        "jeden okres dostaje dwa issue Kontroli ilości",
        NEW,
    ),
    Mutation(
        "do znanego issue bez pierwszej części",
        (
            Edit(
                VERIFIED,
                "_issue(found, known.number), _opening(post, version)[1], box)\n",
                "_issue(found, known.number), _opening(post, version)[1][1:], box)\n",
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "komentarz z odnośnikiem do Logów nie trafia do issue Uwagi taty",
        NEW,
    ),
    Mutation(
        "Zgłoszenie, które wróciło, przejmuje otwarte Zgłoszenie bez komentarza",
        (
            Edit(
                VERIFIED,
                "    return _settle(post, version, _issue(issues, found), (returned,), box)\n",
                "    return Delivered(found, ())\n",
            ),
        ),
        (EXPLORER, "--scope", "zgloszenie-wrocilo"),
        "powtórzone Zgłoszenie nie zostawia śladu w otwartym Zgłoszeniu tego odcisku",
        NEW,
    ),
    Mutation(
        "bez sprawdzenia identyfikatora przed wysyłką (_put: część, która już jest, idzie znowu)",
        (
            Edit(
                VERIFIED,
                "    if sent is None:\n        return box.comment(number, text)\n",
                "    if True:\n        return box.comment(number, text)\n",
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "część, którą Skrzynka przyjęła przed zgubioną odpowiedzią, idzie drugi raz",
        NEW,
    ),
    Mutation(
        "Diagnoza dopisuje komentarz zamiast poprawić (_put: edit_comment)",
        (
            Edit(
                VERIFIED,
                "        return box.edit_comment(comment.id, text)\n",
                "        return box.comment(number, text)\n",
            ),
        ),
        (EXPLORER, "--scope", "diagnoza"),
        "Uruchomienie po Diagnozie ma w issue okresu dwa komentarze Logów",
        NEW,
    ),
    Mutation(
        "starsza wersja po nowszej dopisuje swoją część (_deliver_to_period: seen.newest > version)",
        (
            Edit(
                VERIFIED,
                "    if seen.newest > version:\n        return _newer(post, issue.number, seen, range(",
                "    if False:\n        return _newer(post, issue.number, seen, range(",
            ),
        ),
        (EXPLORER, "--scope", "diagnoza-odczyt"),
        "Logi sprzed Diagnozy, których plik raz był nieczytelny, dopisują po niej część, której Diagnoza nie ma",
        NEW,
    ),
    Mutation(
        "część, której nowsza wersja nie ma, zostaje (_settle: _RETIRED)",
        (
            Edit(
                VERIFIED,
                "        if part not in wanted and was < version:\n",
                "        if False:\n",
            ),
        ),
        (EXPLORER, "--scope", "diagnoza"),
        "w issue okresu zostaje część Logów sprzed Diagnozy",
        NEW,
    ),
    Mutation(
        "Uwaga taty bez szukania issue po znaczniku (_deliver_new_issue: found)",
        (
            Edit(
                VERIFIED,
                "    if found is not None:\n        return _settle(post, version, found, comments, box)\n",
                "    if False:\n        return _settle(post, version, found, comments, box)\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "Uwaga, której odpowiedź na założenie issue zginęła, dostaje drugie issue",
        NEW,
    ),
    Mutation(
        "brak sieci pomija plik do następnego startu",
        (
            Edit(
                VERIFIED,
                '            return "brak-sieci", "stop"\n',
                '            return "brak-sieci", "next"\n',
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "po powrocie sieci wysyłka czeka do następnego startu Centrum",
        NEW,
    ),
    Mutation(
        "Uwaga taty zakłada issue dwa razy",
        (
            Edit(
                VERIFIED,
                "    opened = box.open_issue(issue.label, issue.title, body)\n",
                "    box.open_issue(issue.label, issue.title, body)\n    opened = box.open_issue(issue.label, issue.title, body)\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "każda Uwaga taty daje dwa issue, także bez awarii",
        NEW,
    ),
    Mutation(
        "bez budzenia po RETRY_S",
        (
            Edit(
                VERIFIED,
                "                    if (waiting or self._locked_out) and not self._retry_armed:\n",
                "                    if False:\n",
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "po zerwanej sieci wysyłka czeka do restartu Centrum albo nowej wysyłki",
        NEW,
    ),
    Mutation(
        "budzik RETRY_S nie rusza wysyłki",
        (
            Edit(
                VERIFIED,
                "            self._retry_armed = False\n        self.send_in_background()\n",
                "            self._retry_armed = False\n",
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "po zerwanej sieci budzik tylko zeruje _retry_armed, a wysyłka czeka do restartu",
        NEW,
    ),
    Mutation(
        "start Centrum nie wysyła kolejki",
        (
            Edit(
                VERIFIED,
                "                    leftover.unlink()\n        self.send_in_background()\n",
                "                    leftover.unlink()\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "po starcie wysyłki z poprzedniej pracy czekają do nowej wysyłki",
        NEW,
    ),
    Mutation(
        "nowa wysyłka nie rusza kolejki",
        (
            Edit(
                VERIFIED,
                "        self._log.box_post_queued(label=post.target.label, period=post.period)\n        self.send_in_background()\n",
                "        self._log.box_post_queued(label=post.target.label, period=post.period)\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "Uwaga taty czeka w kolejce do następnego startu Centrum",
        NEW,
    ),
    Mutation(
        "przejście nie zeruje _draining",
        (
            Edit(
                VERIFIED,
                "                    self._draining = False\n",
                "                    pass\n",
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "po pierwszym przejściu budzik i każda nowa wysyłka tylko ustawiają _again, a kolejka stoi do restartu",
        NEW,
    ),
    Mutation(
        "plik w Archiwum bez sprawdzenia wersji z etykiety: kolejka usuwa swój cały plik i wysyła go drugi raz",
        (
            Edit(
                VERIFIED,
                "        if present.uploaded and seen is not None and seen >= version:\n",
                "        if False:\n",
            ),
        ),
        (EXPLORER, "--scope", "archiwum"),
        "plik Logów, którego odpowiedź na upload zginęła, idzie do Archiwum drugi raz",
        NEW,
    ),
    Mutation(
        "plik niepełny po urwanym uploadzie uchodzi za wysłany (_deliver_archive: present.uploaded)",
        (
            Edit(
                VERIFIED,
                "        if present.uploaded and seen is not None and seen >= version:\n",
                "        if seen is not None and seen >= version:\n",
            ),
        ),
        (EXPLORER, "--scope", "archiwum"),
        "Archiwum zostaje z niepełnym plikiem Logów, a plik kolejki znika",
        NEW,
    ),
    Mutation(
        "wysyłka bez kroku Archiwum (_deliver_archive)",
        (Edit(VERIFIED, "    if archive is None:\n        return InArchive()\n", "    if True:\n        return InArchive()\n"),),
        (EXPLORER, "--scope", "archiwum"),
        "komentarz prowadzi do pliku, którego Archiwum nie ma",
        NEW,
    ),
    Mutation(
        "plik starszej wersji nie ustępuje: upload bez remove (_deliver_archive)",
        (
            Edit(
                VERIFIED,
                "        removed = box.remove(present.id)\n",
                "        removed = Removed()\n",
            ),
        ),
        (EXPLORER, "--scope", "archiwum-diagnoza"),
        "plik Logów z Diagnozą nigdy nie dochodzi, bo GitHub odrzuca drugi plik tej nazwy",
        NEW,
    ),
    Mutation(
        "starsza wersja po nowszej podmienia plik w Archiwum (_asset_version: seen >= version)",
        (
            Edit(
                VERIFIED,
                "        if present.uploaded and seen is not None and seen >= version:\n",
                "        if present.uploaded and seen is not None and seen == version:\n",
            ),
        ),
        (EXPLORER, "--scope", "archiwum-diagnoza"),
        "plik Logów sprzed Diagnozy, który dochodzi po niej, zastępuje w Archiwum plik z Diagnozą",
        NEW,
    ),
    Mutation(
        "plik, którego Archiwum nie przyjęło, dostaje pełny znacznik i znika (_send_all: archive_waits)",
        (Edit(VERIFIED, "            if outcome.archive_waits:\n", "            if False:\n"),),
        (EXPLORER, "--scope", "archiwum"),
        "plik Logów znika z kolejki, a Archiwum go nie ma",
        NEW,
    ),
    Mutation(
        "odmowa Archiwum nie nastawia budzenia RETRY_S (_drain: _archive_refused)",
        (
            Edit(
                VERIFIED,
                "                    waiting = self._stopped_on is not None or self._read_failed or self._archive_refused\n",
                "                    waiting = self._stopped_on is not None or self._read_failed\n",
            ),
        ),
        (EXPLORER, "--scope", "archiwum"),
        "plik Logów, którego Archiwum nie przyjęło, czeka do następnej wysyłki albo startu, choć uprawnienie wróciło",
        NEW,
    ),
    Mutation(
        "409 pustego repozytorium jako brak sieci (GitHubReportBox.open_archive sprzed #860 r2)",
        (Edit(REPORT_BOX, "        if answer.status == _EMPTY_REPOSITORY:\n            return Rejected()\n", ""),),
        (EXPLORER, "--scope", "archiwum-puste-repo"),
        "repozytorium Skrzynki bez commitu zatrzymuje komentarz Logów i Zgłoszenie, które czeka za nimi w kolejce",
        NEW,
    ),
    Mutation(
        "lista issue bez issue, które KeyedBox właśnie założył (#879)",
        (
            Edit(
                KEYED_BOX,
                "        return (*listed, *missing)\n",
                "        return listed\n",
            ),
        ),
        (EXPLORER, "--scope", "watek-okresu-lista"),
        "druga Kontrola ilości okresu zakłada drugie issue okresu, zanim lista pokaże pierwsze",
        NEW,
    ),
    Mutation(
        "zapis do Skrzynki bez wstrzymania po zapisie bez odpowiedzi (#879)",
        (
            Edit(
                KEYED_BOX,
                "        return 0 <= now - moment and listed_at - moment < LIST_LAG_S\n",
                "        return False\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue-lista"),
        "ponowienie albo start Centrum po zgubionej odpowiedzi zakłada drugie issue Uwagi, zanim lista pokaże pierwsze",
        NEW,
    ),
    Mutation(
        "zapisy tylko w pamięci, więc nowe Centrum ich nie zna (#879)",
        (
            Edit(
                KEYED_BOX,
                "        if self._opening is None:\n            return self._remembered.fresh(now)\n",
                "        if True:\n            return self._remembered.fresh(now)\n",
            ),
            Edit(
                KEYED_BOX,
                "        if self._opening is None:\n            self._remembered = notes\n",
                "        if True:\n            self._remembered = notes\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue-lista"),
        "start Centrum zaraz po zgubionej odpowiedzi zakłada drugie issue Uwagi, zanim lista pokaże pierwsze",
        NEW,
    ),
    Mutation(
        "nowe Centrum nie zna issue, które założyło stare, choć zapis bez odpowiedzi już go nie wstrzymuje (#879)",
        (
            Edit(
                KEYED_BOX,
                "            [(float(at), str(label), Issue(int(number), str(body))) for at, label, number, body in found[\"issue\"]],\n",
                "            [],\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue-lista"),
        "start Centrum zaraz po założeniu issue Uwagi zakłada drugie, zanim lista pokaże pierwsze",
        NEW,
    ),
    Mutation(
        "Archiwum bez Archiwum, które KeyedBox właśnie założył (#887, #879)",
        (
            Edit(
                KEYED_BOX,
                "        found = outcome if outcome is not None else None if opened is None else Archive(opened, ())\n",
                "        found = outcome\n",
            ),
        ),
        (EXPLORER, "--scope", "archiwum-lista"),
        "drugie Logi nowego okresu dostają odmowę drugiego Archiwum i komentarz z dopiskiem, że plik czeka",
        NEW,
    ),
    Mutation(
        "wysłanie pliku do Archiwum bez wstrzymania po wysłaniu bez odpowiedzi (#879)",
        (
            Edit(
                KEYED_BOX,
                "        return self._listed_write(\n"
                "            _file_kind(name),\n"
                "            lambda key: self._box.upload(archive_id, name, label, data, key=key),\n",
                "        return self._about_issue(lambda key: self._box.upload(archive_id, name, label, data, key=key))\n"
                "        return self._listed_write(\n"
                "            _file_kind(name),\n"
                "            lambda key: self._box.upload(archive_id, name, label, data, key=key),\n",
            ),
        ),
        (EXPLORER, "--scope", "archiwum-lista"),
        "ponowienie po zgubionej odpowiedzi na wysłanie pliku dostaje odmowę drugiego pliku tej nazwy i dopisek, że plik czeka",
        NEW,
    ),
    Mutation(
        "send_in_background nie uruchamia wątku",
        (
            Edit(
                VERIFIED,
                '        threading.Thread(target=self._drain, name="skrzynka-kolejka", daemon=True).start()\n',
                "        pass\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "nic nigdy nie trafia do Skrzynki",
        NEW,
    ),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
