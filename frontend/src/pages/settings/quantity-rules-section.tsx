import type * as React from "react"

import { getQuantityRules } from "@/api/centrum"
import type { DeviceComponent, QuantityRuleSentence, QuantityRulesSettings, SettingProblem } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { useResource } from "@/lib/use-resource"
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

/** Reguły ilości jako zdania „jeśli … to …”, tylko do wglądu; kolumna ma nazwę pozycji cennika z Wzorca. */
export function QuantityRulesSection() {
  return (
    <WithQuantityRules>
      {({ rules, rules_problem }) => (
        <div className="flex flex-col gap-6">
          <p className="text-sm text-pretty text-muted-foreground">
            Reguły działają przy następnym Przygotowaniu pliku zbiorczego. Gotowe Pliki zbiorcze się nie zmieniają.
          </p>
          <Problem problem={rules_problem} />
          {SCOPES.map(({ scope, title }) => {
            const shown = rules.filter((rule) => rule.scope === scope)

            return shown.length === 0 ? null : (
              <section key={scope} aria-label={title} className="flex flex-col gap-2">
                <p aria-hidden className="px-1 text-xs font-medium text-muted-foreground">
                  {title}
                </p>
                <SettingsPanel label={title}>
                  {shown.map((rule) => (
                    <p key={rule.id} role="listitem" className="px-4 py-3 text-sm leading-7 text-pretty">
                      <Sentence parts={rule.sentence} />
                    </p>
                  ))}
                </SettingsPanel>
              </section>
            )
          })}
        </div>
      )}
    </WithQuantityRules>
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

function Sentence({ parts }: { parts: QuantityRuleSentence["sentence"] }) {
  return parts.map((part, index) =>
    part.kind === "text" ? (
      <span key={index}>{part.text}</span>
    ) : (
      <span key={index} className="whitespace-nowrap">
        {part.name === null ? null : <span className="font-medium">{part.name} </span>}
        <Badge variant="secondary" className="font-mono" aria-label={`kolumna ${part.letter}`}>
          {part.letter}
        </Badge>
      </span>
    )
  )
}

function Problem({ problem }: { problem: SettingProblem | null }) {
  return problem === null ? null : <FieldSentence>{problem.message}</FieldSentence>
}

/** Sekcja z Regułami ilości: szkielet w czasie odczytu, Komunikat z „Spróbuj ponownie” po nieudanym, potem treść. */
function WithQuantityRules({ children }: { children: (settings: QuantityRulesSettings) => React.ReactNode }) {
  const { resource, reload } = useResource(getQuantityRules, [], { fromDadFiles: false })

  switch (resource.state) {
    case "loading":
      return <Skeleton className="h-40 w-full rounded-xl" aria-label="Wczytywanie Reguł ilości" />
    case "failed":
      return <LoadFailure what="Reguł ilości" message={resource.message} reload={reload} />
    case "ready":
      return children(resource.data)
    default: {
      const unhandled: never = resource

      return unhandled
    }
  }
}
