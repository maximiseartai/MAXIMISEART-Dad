"""Show that the replay of ``verify-github-skrzynki`` fails on broken variants of the GitHub clients and test fakes.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) and must end the replay (``github_skrzynki.py
odtworz``, offline, on the committed recordings) with ``VERIFY FAIL``. A mutation whose anchor text is no longer in its
file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

BOX = Path("src/rozliczenia/centrum/report_box.py")
KEYED = Path("src/rozliczenia/centrum/keyed_box.py")
FRESHNESS = Path("src/rozliczenia/centrum/tool_freshness.py")
BOX_TESTS = Path("tests/test_skrzynka_zgloszen_github.py")
REPLAY = ".agents/skills/verify-github-skrzynki/scripts/github_skrzynki.py"
FAIL = "VERIFY FAIL"
REFUSALS = "_REFUSALS: Final = frozenset({401, 403, 404})"
REJECTIONS = "_REJECTIONS: Final = frozenset({400, 413, 422})"


def _replay(feature: str) -> tuple[str, ...]:
    return (REPLAY, "odtworz", "--feature", feature)


MUTATIONS = (
    Mutation(
        "401 to odmowa treści (Rejected) zamiast odmowy klucza (Refused)",
        (
            Edit(BOX, REFUSALS, "_REFUSALS: Final = frozenset({403, 404})"),
            Edit(BOX, REJECTIONS, "_REJECTIONS: Final = frozenset({400, 401, 413, 422})"),
        ),
        _replay("skrzynka"),
        "zły klucz taty wygląda jak zła treść: kolejka odrzuca wysyłkę zamiast czekać na nowy klucz",
        FAIL,
    ),
    Mutation(
        "404 (usunięte issue) to brak sieci zamiast odmowy",
        (Edit(BOX, REFUSALS, "_REFUSALS: Final = frozenset({401, 403})"),),
        _replay("skrzynka"),
        "komentarz do issue, które Maks usunął, czeka w kolejce bez końca",
        FAIL,
    ),
    Mutation(
        "422 nie jest odmową treści",
        (Edit(BOX, REJECTIONS, "_REJECTIONS: Final = frozenset({400, 413})"),),
        _replay("skrzynka"),
        "za długie Zgłoszenie i Archiwum w pustym repozytorium wyglądają jak brak sieci",
        FAIL,
    ),
    Mutation(
        "zgubiona druga strona listy",
        (
            Edit(
                BOX,
                "            if len(entries) < _PAGE_SIZE:\n                break\n",
                "            break\n",
            ),
        ),
        _replay("skrzynka"),
        "Centrum nie widzi issue i komentarzy poza pierwszą setką",
        FAIL,
    ),
    Mutation(
        "include_closed pominięte",
        (Edit(BOX, 'state = "all" if include_closed else "open"', 'state = "open"'),),
        _replay("skrzynka"),
        "Powiadomienia nie widzą spraw zamkniętych przez Maksa",
        FAIL,
    ),
    Mutation(
        "powód zamknięcia z pola state",
        (
            Edit(
                BOX,
                'close_reason(entry.get("state_reason"))',
                'close_reason(entry.get("state"))',
            ),
        ),
        _replay("skrzynka"),
        "sprawa zamknięta przez Maksa nie ma powodu",
        FAIL,
    ),
    Mutation(
        "odmowa przy liście nie odrzuca klucza",
        (
            Edit(
                KEYED,
                "_Verdict(digest, isinstance(outcome, Refused), asked_at)",
                "_Verdict(digest, False, asked_at)",
            ),
        ),
        _replay("skrzynka"),
        "Konfiguracja mówi „gotowe” przy kluczu, którego GitHub nie przyjmuje",
        FAIL,
    ),
    Mutation(
        "nagłówek Link bez następnej strony",
        (Edit(FRESHNESS, "return None if found is None else found[1]", "return None"),),
        _replay("aktualnosc"),
        "Aktualność nie widzi Wydań z dalszych stron tagów",
        FAIL,
    ),
    Mutation(
        "404 porównania to brak odpowiedzi zamiast commitu, którego nie ma",
        (
            Edit(
                FRESHNESS,
                "raise (_NotFound if failure.code == 404 else _NoAnswer) from failure",
                "raise _NoAnswer from failure",
            ),
        ),
        _replay("aktualnosc"),
        "Wydanie wypchnięte wprost na `main` daje „nie sprawdzono” zamiast aktualności",
        FAIL,
    ),
    Mutation(
        "każdy scalony PR czyni commit czubkiem `main`",
        (
            Edit(
                FRESHNESS,
                'and pull.get("merge_commit_sha") == commit',
                'and pull.get("merge_commit_sha") != commit',
            ),
        ),
        _replay("aktualnosc"),
        "tag z gałęzi wciągniętej merge'em liczy się jako Wydanie na `main`",
        FAIL,
    ),
    Mutation(
        "atrapa usuniętego issue odpowiada 410 zamiast 404, którym odpowiada GitHub",
        (
            Edit(
                BOX_TESTS,
                '((lambda: HttpResponse(404, b\'{"message": "Not Found"}\'),), Refused()),',
                '((lambda: HttpResponse(410, b\'{"message": "Not Found"}\'),), Unreachable()),',
            ),
        ),
        _replay("wiernosc-atrap"),
        "test przechodzi na odpowiedzi, której GitHub nie daje",
        FAIL,
    ),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
