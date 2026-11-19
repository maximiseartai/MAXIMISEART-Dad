import { defineRule, eslintCompatPlugin } from "@oxlint/plugins";

import type { Comment } from "@oxlint/plugins";

const ALLOWED_LINE_COMMENT =
  /^ (?:SAFETY: \S.*|@ts-expect-error \S.*|oxlint-disable-next-line [@a-z][\w/-]*(?:, [@a-z][\w/-]*)* -- \S.*|ZEWNĘTRZNE: \S.* \(\S(?:[^()]*\S)?\))$/u;

const ISSUE_LINK = /#\d|maximiseart-?ai\//iu;

const NODE_SHEBANG = "/usr/bin/env node";

function allowed(comment: Comment): boolean {
  if (comment.type === "Shebang") return comment.value === NODE_SHEBANG;

  return comment.type === "Line" && ALLOWED_LINE_COMMENT.test(comment.value) && !ISSUE_LINK.test(comment.value);
}

const noCommentsRule = defineRule({
  meta: {
    type: "problem",
    docs: { description: "Disallow comments except the directives, the shebang and the outside-world form the repository accepts." },
    messages: {
      comment:
        "komentarz we frontendzie: to, co mówi, wyraź nazwą, typem albo testem, który pada bez tego kodu, decyzję zapisz w ADR, motywację domenową w GLOSSARY.md, a historię zmiany w opisie PR; zostaje tylko komentarz liniowy, który w całości ma jedną z postaci: „// SAFETY: powód” nad rzutowaniem typu, „// @ts-expect-error powód”, „// oxlint-disable-next-line reguła -- powód” albo „// ZEWNĘTRZNE: fakt (źródło)”, bez numeru issue („#” i cyfra) i adresu repozytorium maximiseartai/ albo MAXIMISEART-AI/, oraz „#!/usr/bin/env node” w pierwszej linii",
    },
  },
  createOnce(context) {
    return {
      Program() {
        for (const comment of context.sourceCode.getAllComments()) {
          if (allowed(comment)) continue;
          context.report({
            loc: {
              start: context.sourceCode.getLocFromIndex(comment.start),
              end: context.sourceCode.getLocFromIndex(comment.end),
            },
            messageId: "comment",
          });
        }
      },
    };
  },
});

export default eslintCompatPlugin({ meta: { name: "repo" }, rules: { "no-comments": noCommentsRule } });
