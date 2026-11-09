"""Show that the drive of verify-centrum-rozliczen fails on broken variants of its `uwaga-taty` feature.

Each mutation runs the feature on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must make it fail.
A mutation whose anchor text is no longer in its file is reported as NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / ".agents/skills/verify-centrum-rozliczen/scripts"))

from cele_mutacji_centrum import BUILD, CASE_DELIVERY, DAD_CASES, UWAGA
from silnik_mutacji import Edit, Mutation, check_all

FIELDS = Edit(BUILD, "`-m-1 flex flex-col gap-5 overflow-y-auto p-1`", "`-m-1 flex min-h-0 flex-col gap-5 p-1`")
DOTYCZY = Edit(
    BUILD, "`has-data-[slot=radio-group]:min-h-32 has-[>p+[data-slot=radio-group]]:min-h-44`", "`min-h-0`"
)
PREVIEW = "`flex min-h-16 flex-col gap-1 overflow-y-auto rounded-lg bg-muted/50 p-3 text-sm`"
CSS = BUILD.with_name("index.css")
WITH_LIST = ":has([data-slot=radio-group]){min-height:calc(var(--spacing) * 32)}"
WITH_SENTENCE = ":has(>p+[data-slot=radio-group]){min-height:calc(var(--spacing) * 44)}"

MUTATIONS = (
    Mutation(
        "pola okna Uwagi się nie przewijają",
        (FIELDS,),
        UWAGA,
        "przy niskim oknie przełącznik „Dotyczy” i „Maks dostanie” leżą pod stopką i nie da się do nich przewinąć (#488)",
    ),
    Mutation(
        "okno Uwagi jak na main",
        (FIELDS, DOTYCZY, Edit(BUILD, PREVIEW, PREVIEW.replace("min-h-16", "min-h-0"))),
        UWAGA,
        "przy niskim oknie „Dotyczy” kurczy się pod przełącznik, a pola się nie przewijają (#488)",
    ),
    Mutation(
        "„Dotyczy” kurczy się pod przełącznik",
        (DOTYCZY,),
        UWAGA,
        "przy niskim oknie lista Uruchomień albo przełącznik nachodzi na „Maks dostanie” (#488)",
    ),
    Mutation(
        "„Dotyczy” z listą ma za duże minimum",
        (Edit(CSS, WITH_LIST, WITH_LIST.replace("* 32", "* 72")),),
        UWAGA,
        "przy pełnym oknie lista Uruchomień jest wyższa, a „Maks dostanie” niższe niż na main (#498)",
    ),
    Mutation(
        "„Dotyczy” z listą schodzi poniżej jednego wiersza",
        (Edit(CSS, WITH_LIST, WITH_LIST.replace("* 32", "* 28")),),
        UWAGA,
        "przy niskim oknie lista Uruchomień nie pokazuje całego wiersza i nachodzi na „Maks dostanie” (#488)",
    ),
    Mutation(
        "„Dotyczy” ze zdaniem nad listą ma minimum jak bez zdania",
        (Edit(CSS, WITH_SENTENCE, WITH_SENTENCE.replace("* 44", "* 32")),),
        UWAGA,
        "przy niskim oknie Uwagi o Uruchomieniu spoza historii lista nie pokazuje całego wiersza (#488)",
    ),
    Mutation(
        "„Maks dostanie” nie oddaje wysokości",
        (Edit(BUILD, PREVIEW, PREVIEW.replace("min-h-16", "shrink-0")),),
        UWAGA,
        "przy pełnym oknie lista Uruchomień jest niższa niż na main, bo wysokość oddaje tylko ona (#498)",
    ),
    Mutation(
        "„Maks dostanie” ma za duże minimum",
        (
            Edit(
                CSS,
                ".min-h-16{min-height:calc(var(--spacing) * 16)}",
                ".min-h-16{min-height:calc(var(--spacing) * 16)}figure.min-h-16{min-height:calc(var(--spacing) * 40)}",
            ),
        ),
        UWAGA,
        "przy niskim oknie pola przewijają się, zanim „Maks dostanie” odda wysokość do podpisu i pierwszej linii (#488)",
    ),
    Mutation(
        "„Maks dostanie” kurczy się pod podpis",
        (Edit(BUILD, PREVIEW, PREVIEW.replace("min-h-16", "min-h-10")),),
        UWAGA,
        "przy niskim oknie „Maks dostanie” nie pokazuje pierwszej linii (#488)",
    ),
    Mutation(
        "komentarz z odnośnikiem do odrzuconych Logów nie powstaje",
        (
            Edit(
                CASE_DELIVERY,
                "        return (Post(KnownIssue(NOTE.label, number), period=None, run_id=run_id, header=None, parts=(_logs_gone(run_id),)),)\n",
                "        return ()\n",
            ),
        ),
        UWAGA,
        "Maks nie dostaje odnośnika do Logów, które dotarły po Uwadze",
    ),
    Mutation(
        "komentarz po odrzuconych Logach bez odnośnika",
        (
            Edit(
                CASE_DELIVERY,
                "                return replace(post, parts=(_logs_arrived(post.run_id, address),))\n",
                "                return post\n",
            ),
        ),
        UWAGA,
        "Maks dostaje komentarz, że Logi nie dotrą, choć dotarły",
    ),
    Mutation(
        "„nie dotarły” zamienione na „w drodze”",
        (
            Edit(
                CASE_DELIVERY,
                "        return _rejected_logs_line(run_id), _LOGS_REJECTED\n",
                "        return logs_line(run_id, None), _LOGS_REJECTED\n",
            ),
        ),
        UWAGA,
        "wysłana Uwaga mówi, że Logi są w drodze, choć Skrzynka je odrzuciła",
    ),
    Mutation(
        "„nie powstały” zamienione na „nie dotarły”",
        (Edit(CASE_DELIVERY, "    if sent.rejected(run_id, RUN_LOGS_LABEL):\n", "    if True:\n"),),
        UWAGA,
        "Uwaga obiecuje odnośnik do Logów, których nie ma w kolejce",
    ),
    Mutation(
        "Uwaga bez Tokenu do Zgłoszeń czeka na internet",
        (Edit(DAD_CASES, 'waits_for="key" if refused else "internet"', 'waits_for="internet"'),),
        UWAGA,
        "bez tokenu tata czyta, że Uwaga wyjdzie, gdy będzie internet, zamiast skontaktować się z Maksem (Q17)",
    ),
    Mutation(
        "Uwaga odrzucona przez Skrzynkę czeka",
        (Edit(DAD_CASES, '            if case_id in self._rejected:\n                return common_contract.Rejected', "            if False:\n                return common_contract.Rejected"),),
        UWAGA,
        "tata czyta, że Uwaga czeka, choć Skrzynka odrzuciła jej treść (Q17)",
    ),
)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(check_all(MUTATIONS))
