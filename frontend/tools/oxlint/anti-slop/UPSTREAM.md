# anti-slop (vendored Oxlint plugin)

- Source: https://github.com/MAXIMISEART-AI/maximiseart-agent-skills, path `skills/install-anti-slop/assets/anti-slop`.
- Snapshot: the `install-anti-slop` skill bundle at tree `13b1bea990583b37dca0bb7af20c4c8252e859d3` (from the skill's `github-tree-sha` metadata), copied unchanged with `scripts/install.mjs` on 2026-10-19. The copy was byte-identical to the bundle at install time.
- Installed paths: `frontend/tools/oxlint/anti-slop/` (generic plugin `index.ts`, `rules/`, `shared/`, `vendor/`).
- Registered in `frontend/.oxlintrc.json` with every generic rule at `error` and the native companion `oxc/no-accumulating-spread`.
- Intentional deviations: the opt-in Effect plugin (`effect/`) is removed, because the frontend does not depend on `effect` and the plugin was never registered; re-copy it from the snapshot if the frontend adopts Effect. The verification paragraph of `vendor/eslint-stylistic/UPSTREAM.md` names this repository's check instead of the source repository's commands and tests. No other changes in the plugin source. Lint configuration ignores the registry-owned shadcn code (`src/components/ui/**`, `src/hooks/use-mobile.ts`) and the generated contract (`src/api/generated/**`), which are updated by their tools, not edited by hand.
- Updates follow the skill's `references/update.md` procedure (reviewed merge, not directory replacement).
