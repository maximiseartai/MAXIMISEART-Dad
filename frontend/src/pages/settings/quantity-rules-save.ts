import * as React from "react"

import { failureMessage, refusedField } from "@/api/client"
import type { ActivityLegendSaved, ActivityLegendSettings, QuantityRulesSaved, QuantityRulesSettings } from "@/api/generated"
import { useAction } from "@/lib/action"
import { useSettings } from "@/lib/settings"

/** Odmowa zapisu formularza: pole z serwera (`jesli[0].tekst`, `zapisy[1]`) albo `null` i jedno zdanie. */
type Refusal = { field: string | null; message: string }

/**
 * Zapis formularza sekcji Ustawień: po zapisie „Zapisano · Cofnij” i dane sekcji z odpowiedzi (`close`), a odmowa
 * zostaje w formularzu jako pole i zdanie.
 */
function useFormSave<Saved extends { change: string | null }, Data>(close: (saved: Data | null) => void, data: (saved: Saved) => Data) {
  const { changed } = useSettings()
  const [refusal, setRefusal] = React.useState<Refusal | null>(null)

  const saving = useAction(async (request: () => Promise<Saved>) => {
    setRefusal(null)

    await request().then(
      (result) => {
        changed(result.change)
        close(data(result))
      },
      (failure: Error) => setRefusal({ field: refusedField(failure), message: failureMessage(failure) })
    )
  })

  return { saving, refusal, setRefusal }
}

/** Zapis formularza sekcji Reguły ilości albo Urządzenia. */
export function useQuantityRulesSave(close: (saved: QuantityRulesSettings | null) => void) {
  return useFormSave(close, (result: QuantityRulesSaved) => result.quantity_rules)
}

/** Zapis formularza Kodu czynności w sekcji Legenda czynności. */
export function useActivityLegendSave(close: (saved: ActivityLegendSettings | null) => void) {
  return useFormSave(close, (result: ActivityLegendSaved) => result.activity_legend)
}
