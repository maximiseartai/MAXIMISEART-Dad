import * as React from "react"

import { failureMessage, refusedField } from "@/api/client"
import type { QuantityRulesSaved, QuantityRulesSettings } from "@/api/generated"
import { useAction } from "@/lib/action"
import { useSettings } from "@/lib/settings"

/** Odmowa zapisu formularza: pole z serwera (`jesli[0].tekst`, `zapisy[1]`) albo `null` i jedno zdanie. */
export type Refusal = { field: string | null; message: string }

/**
 * Zapis formularza sekcji Reguły ilości albo Urządzenia: po zapisie „Zapisano · Cofnij” i reguły z odpowiedzi
 * (`close`), a odmowa zostaje w formularzu jako pole i zdanie.
 */
export function useQuantityRulesSave(close: (saved: QuantityRulesSettings | null) => void) {
  const { changed } = useSettings()
  const [refusal, setRefusal] = React.useState<Refusal | null>(null)

  const saving = useAction(async (request: () => Promise<QuantityRulesSaved>) => {
    setRefusal(null)

    await request().then(
      (result) => {
        changed(result.change)
        close(result.quantity_rules)
      },
      (failure: Error) => setRefusal({ field: refusedField(failure), message: failureMessage(failure) })
    )
  })

  return { saving, refusal, setRefusal }
}
