import * as React from "react"
import { PencilIcon, PlusIcon } from "lucide-react"

import { getQuantityRules } from "@/api/centrum"
import type { DeviceComponent, QuantityRuleSentence, QuantityRulesSettings, RuleForm, SettingProblem } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useReloadOnChange } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { QuantityDifferences } from "@/pages/settings/quantity-differences"
import { RuleEditor } from "@/pages/settings/quantity-rule-editor"
import { Sentence } from "@/pages/settings/rule-sentence"
import { FieldSentence, SettingsPanel } from "@/pages/settings/setting-row"

/** Grupy reguł według zakresu, w kolejności z ADR 0033; grupa bez reguł się nie pokazuje. */
const SCOPES: ReadonlyArray<{ scope: QuantityRuleSentence["scope"]; title: string }> = [
  { scope: "known", title: "Gdy Lista Urządzeń zna każdy składnik" },
  { scope: "unknown", title: "Gdy jest składnik spoza listy" },
  { scope: "every", title: "Każde zlecenie" },
]

const GROUPS: Record<NonNullable<DeviceComponent["group"]>, string> = {
  router: "Router",
  tv: "TV",
  extender: "Extender",
}

/** Nowa reguła zaczyna bez warunków i bez działania: działanie wybiera tata. */
const NEW_RULE: RuleForm = { scope: "known", conditions: [], action: null }

/** Reguła w edytorze: `id` `null` to nowa reguła; `prefilled`: formularz z różnicy („Popraw regułę”), jeszcze niezapisany. */
type Editing = { id: string | null; rule: RuleForm; prefilled?: boolean }

/**
 * Reguły ilości jako zdania „jeśli … to …”; kolumna ma nazwę pozycji cennika z Wzorca. „Dodaj regułę” i „Zmień”
 * otwierają edytor w miejscu listy, a po zapisie lista wraca z regułą już zapisaną.
 */
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

/** Składniki URZĄDZENIA, które znają Reguły ilości: nazwa, inne zapisy tej samej rzeczy i grupa. */
export function DevicesSection() {
  return (
    <WithQuantityRules>
      {({ devices, devices_problem }) => (
        <div className="flex flex-col gap-6">
          <Problem problem={devices_problem} />
          <SettingsPanel label="Lista Urządzeń">
            {devices.map((device) => (
              <div key={device.id} role="listitem" aria-label={device.name} className="flex items-center gap-4 px-4 py-3">
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="text-sm font-medium">{device.name}</span>
                  {device.other_spellings.length === 0 ? null : (
                    <span className="text-sm text-pretty text-muted-foreground">
                      Też: {device.other_spellings.join(", ")}
                    </span>
                  )}
                </div>
                {device.group === null ? null : <Badge variant="outline">{GROUPS[device.group]}</Badge>}
              </div>
            ))}
          </SettingsPanel>
        </div>
      )}
    </WithQuantityRules>
  )
}

function Problem({ problem }: { problem: SettingProblem | null }) {
  return problem === null ? null : <FieldSentence>{problem.message}</FieldSentence>
}

/**
 * Sekcja z Regułami ilości: szkielet w czasie odczytu, Komunikat z „Spróbuj ponownie” po nieudanym, potem treść.
 * Każda przyjęta zmiana Ustawień (także „Cofnij” w powiadomieniu i w Historii) czyta reguły od nowa, bez szkieletu;
 * `saved` pokazuje od razu reguły z odpowiedzi zapisu.
 */
function WithQuantityRules({
  children,
}: {
  children: (settings: QuantityRulesSettings, saved: (settings: QuantityRulesSettings) => void) => React.ReactNode
}) {
  const { resource, reload, replace } = useResource(getQuantityRules, [], { fromDadFiles: false })

  useReloadOnChange(reload)

  switch (resource.state) {
    case "loading":
      return <Skeleton className="h-40 w-full rounded-xl" aria-label="Wczytywanie Reguł ilości" />
    case "failed":
      return <LoadFailure what="Reguł ilości" message={resource.message} reload={reload} />
    case "ready":
      return children(resource.data, (data) => replace({ state: "ready", data }))
    default: {
      const unhandled: never = resource

      return unhandled
    }
  }
}
