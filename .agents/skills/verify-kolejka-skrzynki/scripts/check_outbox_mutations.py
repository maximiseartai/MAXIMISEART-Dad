"""Show that explore_outbox.py fails on broken variants of the Kolejka Skrzynki Zgłoszeń.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) and must end the checker's report with the
expected line. A mutation whose anchor text is no longer in ``outbox.py`` is reported as NIEAKTUALNA: update it to
the new code.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

VERIFIED = Path("src/rozliczenia/centrum/outbox.py")
EXPLORER = ".agents/skills/verify-kolejka-skrzynki/scripts/explore_outbox.py"
NEW = "KOLEJKA: NOWE NARUSZENIE"

MUTATIONS = (
    Mutation(
        "nieudany komentarz pominięty zamiast końca wysyłki",
        (
            Edit(
                VERIFIED,
                "        if not isinstance(answer, Commented):\n            return answer\n",
                "        if not isinstance(answer, Commented):\n            continue\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "plik znika z kolejki, choć Skrzynka nie przyjęła części",
        NEW,
    ),
    Mutation(
        "do znalezionego issue okresu bez pierwszej części",
        (
            Edit(
                VERIFIED,
                "        number, comments = found, post.parts\n",
                "        number, comments = found, post.parts[1:]\n",
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
                "    if found is None:\n        body, comments = post.opening()\n        opened = box.open_issue(thread.label",
                "    if True:\n        body, comments = post.opening()\n        opened = box.open_issue(thread.label",
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
                "    return _comment_all(known.number, post.opening()[1], box)\n",
                "    return _comment_all(known.number, post.opening()[1][1:], box)\n",
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "komentarz z odnośnikiem do Logów nie trafia do issue Uwagi taty",
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
        "każda Uwaga taty daje dwa issue, choć ADR 0015 przyjmuje drugie tylko po zerwanym połączeniu",
        NEW,
    ),
    Mutation(
        "bez znacznika dostarczenia",
        (
            Edit(
                VERIFIED,
                "                replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts)))\n",
                "                pass\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "plik, którego nie dało się usunąć, idzie po restarcie drugi raz i zakłada drugie issue Uwagi taty",
        NEW,
    ),
    Mutation(
        "bez budzenia po RETRY_S",
        (
            Edit(
                VERIFIED,
                "                    if (self._stopped_on is not None or self._read_failed or self._locked_out) and not self._retry_armed:\n",
                "                    if False:\n",
            ),
        ),
        (EXPLORER, "--scope", "znane-issue"),
        "po zerwanej sieci wysyłka czeka do restartu Centrum albo nowej wysyłki",
        NEW,
    ),
    Mutation(
        "usunięcie pliku przed znacznikiem dostarczenia",
        (
            Edit(
                VERIFIED,
                "            with suppress(OSError):  # bez znacznika chroni już tylko _undeleted, do końca tej pracy Centrum\n                replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts)))\n            self._remove(path)\n",
                "            self._remove(path)\n            with suppress(OSError):  # bez znacznika chroni już tylko _undeleted, do końca tej pracy Centrum\n                replace_atomically(path, _queue_text(post, delivered_parts=len(post.parts)))\n",
            ),
        ),
        (EXPLORER, "--scope", "nowe-issue"),
        "proces zamknięty przy usuwaniu wysłanej Uwagi taty wysyła ją po restarcie drugi raz",
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
