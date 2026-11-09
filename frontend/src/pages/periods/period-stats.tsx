import type * as React from "react"
import { ClockIcon, FileSpreadsheetIcon, ListChecksIcon } from "lucide-react"

import type { Metrics, PeriodRow } from "@/api/generated"
import { otherResults, RunResultBadge } from "@/components/run-result-badge"
import { StatStrip, type Stat } from "@/components/stat-strip"
import { Skeleton } from "@/components/ui/skeleton"
import { dateTime } from "@/lib/format"
import type { Resource } from "@/lib/use-resource"

/**
 * Najważniejsze liczby na stronie głównej: ostatni przygotowany okres (wskazany przez serwer w Tablicy
 * okresów), ostatnie Uruchomienie procesu i wyniki z ostatnich tygodni (z plików metryk). Nieudany odczyt metryk
 * ma Komunikat i „Spróbuj ponownie” strony nad Tablicą, więc tu zostaje tylko krótka notka.
 */
export function PeriodStats({
  periods,
  lastPrepared,
  metrics,
}: {
  periods: ReadonlyArray<PeriodRow>
  lastPrepared: string | null
  metrics: Resource<Metrics>
}) {
  const prepared = periods.find((period) => period.token === lastPrepared)

  const preparedStat: Stat = {
    label: "Ostatni przygotowany okres",
    icon: <FileSpreadsheetIcon aria-hidden />,
    value: prepared?.token ?? "–",
    note: prepared?.status_label ?? "jeszcze nie ma Pliku zbiorczego",
  }

  if (metrics.state !== "ready") {
    const pending: Pick<Stat, "value" | "note"> =
      metrics.state === "loading"
        ? { value: <Skeleton className="h-8 w-24" />, note: <Skeleton className="h-4 w-36" /> }
        : { value: "–", note: "nie udało się odczytać" }

    return (
      <StatStrip
        label="Najważniejsze liczby"
        stats={[
          preparedStat,
          { label: "Ostatnie uruchomienie", icon: <ClockIcon aria-hidden />, ...pending },
          // Liczbę tygodni zna tylko serwer (`recent.weeks`), więc przed odczytem metryk etykieta jej nie podaje.
          { label: "Ostatnie tygodnie", icon: <ListChecksIcon aria-hidden />, ...pending },
        ]}
      />
    )
  }

  const [latest] = metrics.data.runs
  const { recent } = metrics.data
  const latestValue: React.ReactNode = latest === undefined ? "–" : <RunResultBadge run={latest} />

  return (
    <StatStrip
      label="Najważniejsze liczby"
      stats={[
        preparedStat,
        {
          label: "Ostatnie uruchomienie",
          icon: <ClockIcon aria-hidden />,
          value: latestValue,
          note:
            latest === undefined
              ? "jeszcze nie było"
              : `${latest.process_label} · ${dateTime(latest.started_at)}`,
        },
        {
          label: `Ostatnie ${recent.weeks} tygodni`,
          icon: <ListChecksIcon aria-hidden />,
          value: `${recent.results.ok} OK`,
          note: otherResults(recent.results),
        },
      ]}
    />
  )
}
