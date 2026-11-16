import { getActivityLegend } from "@/api/centrum"
import type { ActivityLegendSettings } from "@/api/generated"
import { Problem } from "@/pages/settings/quantity-rules-section"
import { Sentence } from "@/pages/settings/rule-sentence"
import { SettingsPanel } from "@/pages/settings/setting-row"
import { WithSettingsRead } from "@/pages/settings/settings-read"

/**
 * Legenda czynności: każdy Kod czynności jednym zdaniem, w kolejności z pliku; kolumna ma nazwę pozycji cennika z
 * Wzorca. Zła legenda pokazuje swoje zdanie nad legendą, którą Centrum liczy mimo to.
 */
export function ActivityLegendSection() {
  return (
    <WithSettingsRead read={getActivityLegend} what="Legendy czynności">
      {(legend) => <CodeList legend={legend} />}
    </WithSettingsRead>
  )
}

function CodeList({ legend }: { legend: ActivityLegendSettings }) {
  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-pretty text-muted-foreground">
        Kody z opisu technika działają przy następnym Przygotowaniu pliku zbiorczego. Gotowe Pliki zbiorcze się nie
        zmieniają. # w kodzie to dowolna liczba, np. inst20m.
      </p>
      <Problem problem={legend.problem} />
      <SettingsPanel label="Kody czynności">
        {legend.codes.map((code) => (
          <div key={code.id} role="listitem" className="px-4 py-3">
            <p className="min-w-0 text-sm leading-7 text-pretty">
              <Sentence parts={code.sentence} />
            </p>
          </div>
        ))}
      </SettingsPanel>
    </div>
  )
}
