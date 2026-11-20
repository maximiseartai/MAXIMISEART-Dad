import * as React from "react"
import { PencilIcon, PlusIcon } from "lucide-react"

import { getQuantityRules } from "@/api/centrum"
import type { QuantityRuleSentence, QuantityRulesSettings, RuleForm, SettingProblem } from "@/api/generated"
import { Button } from "@/components/ui/button"
import { QuantityDifferences } from "@/pages/settings/quantity-differences"
import { RuleEditor } from "@/pages/settings/quantity-rule-editor"
import { Sentence } from "@/pages/settings/rule-sentence"
import { FieldSentence, SettingsPanel } from "@/pages/settings/setting-row"
import { WithSettingsRead } from "@/pages/settings/settings-read"

const SCOPES: ReadonlyArray<{ scope: QuantityRuleSentence["scope"]; title: string }> = [
  { scope: "known", title: "Gdy Lista Urządzeń zna każdy składnik" },
  { scope: "unknown", title: "Gdy jest składnik spoza listy" },
  { scope: "every", title: "Każde zlecenie" },
]

const NEW_RULE: RuleForm = { scope: "known", conditions: [], action: null }

type Editing = { id: string | null; rule: RuleForm; prefilled?: boolean }

export function QuantityRulesSection() {
  const [editing, setEditing] = React.useState<Editing | null>(null)

  return (
    <WithQuantityRules>
      {(settings, saved) =>
        editing === null ? (
          <RuleList settings={settings} edit={setEditing} />
        ) : (
          <RuleEditor
            key={editing.id ?? "nowa"}
            id={editing.id}
            initial={editing.rule}
            prefilled={editing.prefilled === true}
            settings={settings}
            close={(next) => {
              if (next !== null) {
                saved(next)
              }

              setEditing(null)
            }}
          />
        )
      }
    </WithQuantityRules>
  )
}

function RuleList({ settings, edit }: { settings: QuantityRulesSettings; edit: (editing: Editing) => void }) {
  const { rules, rules_problem } = settings

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <p className="min-w-0 flex-1 basis-64 text-sm text-pretty text-muted-foreground">
          Reguły działają przy następnym Przygotowaniu pliku zbiorczego. Gotowe Pliki zbiorcze się nie zmieniają.
        </p>
        <Button variant="outline" size="sm" onClick={() => edit({ id: null, rule: NEW_RULE })}>
          <PlusIcon data-icon="inline-start" />
          Dodaj regułę
        </Button>
      </div>
      <Problem problem={rules_problem} />
      <QuantityDifferences fix={(draft) => edit({ id: null, rule: draft, prefilled: true })} />
      {SCOPES.map(({ scope, title }) => {
        const shown = rules.filter((rule) => rule.scope === scope)

        return shown.length === 0 ? null : (
          <section key={scope} aria-label={title} className="flex flex-col gap-2">
            <p aria-hidden className="px-1 text-xs font-medium text-muted-foreground">
              {title}
            </p>
            <SettingsPanel label={title}>
              {shown.map((rule) => (
                <div key={rule.id} role="listitem" className="group flex items-start gap-3 px-4 py-3">
                  <p className="min-w-0 flex-1 text-sm leading-7 text-pretty">
                    <Sentence parts={rule.sentence} />
                  </p>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="mt-0.5 shrink-0 text-muted-foreground"
                    aria-label="Zmień regułę"
                    onClick={() => edit({ id: rule.id, rule: rule.rule })}
                  >
                    <PencilIcon />
                  </Button>
                </div>
              ))}
            </SettingsPanel>
          </section>
        )
      })}
    </div>
  )
}

export function Problem({ problem }: { problem: SettingProblem | null }) {
  return problem === null ? null : <FieldSentence>{problem.message}</FieldSentence>
}

export function WithQuantityRules({
  children,
}: {
  children: (settings: QuantityRulesSettings, saved: (settings: QuantityRulesSettings) => void) => React.ReactNode
}) {
  return (
    <WithSettingsRead read={getQuantityRules} what="Reguł ilości">
      {children}
    </WithSettingsRead>
  )
}
