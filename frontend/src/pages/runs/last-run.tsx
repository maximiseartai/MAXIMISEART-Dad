import { HistoryIcon } from "lucide-react"

import type { RunRestored } from "@/api/generated"
import { dateTime } from "@/lib/format"
import { RestoredCardButton } from "@/pages/runs/run-card-sheet"

/**
 * Linia „Ostatnio …” procesu bez okresu: chwila i nagłówek wyniku ostatniego Uruchomienia z jego Logów, opcjonalny
 * dopisek (np. liczba uporządkowanych zleceń) i przycisk jego karty.
 */
export function LastRun({ last, detail }: { last: RunRestored; detail?: string | undefined }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
      <HistoryIcon className="size-4 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">
        Ostatnio {dateTime(last.started_at)} · {last.result.headline}
        {detail === undefined ? null : ` · ${detail}`}
      </span>
      <span className="ml-auto">
        <RestoredCardButton card={last} />
      </span>
    </div>
  )
}
