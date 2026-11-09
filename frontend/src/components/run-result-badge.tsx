import { CircleCheckIcon, CircleStopIcon, OctagonXIcon, TriangleAlertIcon } from "lucide-react"

import type { ProcessRun, ResultCounts } from "@/api/generated"
import { Badge } from "@/components/ui/badge"
import { plural } from "@/lib/format"

// Wynik Uruchomienia procesu zawsze z ikoną i słowem, nigdy samym kolorem; ton wyniku podaje serwer.
export function RunResultBadge({ run }: { run: Pick<ProcessRun, "tone"> }) {
  switch (run.tone) {
    case "ok":
      return (
        <Badge variant="secondary">
          <CircleCheckIcon data-icon="inline-start" className="text-success" />
          OK
        </Badge>
      )
    case "needs_review":
      return (
        <Badge variant="outline">
          <TriangleAlertIcon data-icon="inline-start" className="text-warning" />
          Do sprawdzenia
        </Badge>
      )
    case "failed":
      return (
        <Badge variant="destructive">
          <OctagonXIcon data-icon="inline-start" />
          Błąd
        </Badge>
      )
    case "stopped":
      return (
        <Badge variant="outline">
          <CircleStopIcon data-icon="inline-start" className="text-muted-foreground" />
          Zatrzymano
        </Badge>
      )
    default: {
      const unhandled: never = run.tone

      return unhandled
    }
  }
}

/** `3 do sprawdzenia · 2 zatrzymane · 1 błąd`: dopisek pod liczbą wyników OK. */
export function otherResults(results: ResultCounts): string {
  const failed = plural(results.failed, { one: "błąd", few: "błędy", many: "błędów" })

  return `${results.needs_review} do sprawdzenia · ${results.stopped} zatrzymane · ${results.failed} ${failed}`
}
