import { CircleCheckIcon, CircleStopIcon, OctagonXIcon, TriangleAlertIcon } from "lucide-react"

import type { ProcessRun, ResultCounts } from "@/api/centrum"
import { Badge } from "@/components/ui/badge"
import { plural } from "@/lib/format"

/** Zatrzymanie „do Maksa”, także nieoczekiwany wyjątek: jedyne przerwane, które Centrum pokazuje jako błąd. */
export function isFailure(run: Pick<ProcessRun, "stop_kind">): boolean {
  return run.stop_kind === "for_maks"
}

// Wynik Uruchomienia procesu zawsze z ikoną i słowem, nigdy samym kolorem. Czerwień tylko przy Zatrzymaniu „do Maksa”.
export function RunResultBadge({ run }: { run: Pick<ProcessRun, "result" | "stop_kind"> }) {
  switch (run.result) {
    case "OK":
      return (
        <Badge variant="secondary">
          <CircleCheckIcon data-icon="inline-start" className="text-success" />
          OK
        </Badge>
      )
    case "WYMAGA_SPRAWDZENIA":
      return (
        <Badge variant="outline">
          <TriangleAlertIcon data-icon="inline-start" className="text-warning" />
          Do sprawdzenia
        </Badge>
      )
    case "BLAD_KRYTYCZNY":
      return isFailure(run) ? (
        <Badge variant="destructive">
          <OctagonXIcon data-icon="inline-start" />
          Błąd
        </Badge>
      ) : (
        <Badge variant="outline">
          <CircleStopIcon data-icon="inline-start" className="text-muted-foreground" />
          Zatrzymano
        </Badge>
      )
    default: {
      const unhandled: never = run.result

      return unhandled
    }
  }
}

/** `3 do sprawdzenia · 2 zatrzymane · 1 błąd`: dopisek pod liczbą wyników OK. */
export function otherResults(results: ResultCounts): string {
  const failed = plural(results.failed, { one: "błąd", few: "błędy", many: "błędów" })

  return `${results.needs_review} do sprawdzenia · ${results.stopped} zatrzymane · ${results.failed} ${failed}`
}
