import * as React from "react"

import { failureMessage, refusedField } from "@/api/client"
import type { ActivityLegendSaved, ActivityLegendSettings, QuantityRulesSaved, QuantityRulesSettings } from "@/api/generated"
import { useAction } from "@/lib/action"
import { useSettings } from "@/lib/settings"

type Refusal = { field: string | null; message: string }

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

export function useQuantityRulesSave(close: (saved: QuantityRulesSettings | null) => void) {
  return useFormSave(close, (result: QuantityRulesSaved) => result.quantity_rules)
}

export function useActivityLegendSave(close: (saved: ActivityLegendSettings | null) => void) {
  return useFormSave(close, (result: ActivityLegendSaved) => result.activity_legend)
}
