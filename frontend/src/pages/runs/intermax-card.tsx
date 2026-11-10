import { cn } from "cn"
import { CheckIcon, ListOrderedIcon } from "lucide-react"

import { getIntermaxDays, getIntermaxSetup, type IntermaxDays } from "@/api/centrum"
import { LoadFailure } from "@/components/load-failure"
import { ThreePartMessage } from "@/components/three-part-message"
import { Skeleton } from "@/components/ui/skeleton"
import { useResource } from "@/lib/use-resource"
import { OutsidePeriodCard } from "@/pages/runs/outside-period-card"

/**
 * Karta „Uporządkuj INTERMAX” poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty, tu pod nazwą, którą zna tata.
 */
export function IntermaxCard() {
  return (
    <OutsidePeriodCard
      read={getIntermaxSetup}
      what="Uporządkowania INTERMAX"
      label="Uporządkuj INTERMAX"
      description="Zlecenia dnia wklejone na dół INTERMAX."
      icon={<ListOrderedIcon data-icon="inline-start" />}
      request={{ process: "intermax" }}
      skeleton="h-44"
      unblocked={<RegisterDays />}
      lastDetail={(last) => last.result.summary?.counts?.counts[0]?.label}
    />
  )
}

/**
 * Dni INTERMAX w rzędzie, jak kroki Drogi okresu: Dzień uporządkowany ma znak, nieuporządkowany pusty krąg, a dziś
 * obwódkę. Serwer czyta INTERMAX tylko po jego zmianie, więc odczyt przy każdym wejściu i powrocie do okna jest tani.
 */
function RegisterDays() {
  const { resource: days, reload } = useResource(getIntermaxDays, [])

  switch (days.state) {
    case "loading":
      return <Skeleton className="h-6 w-full" aria-label="Wczytywanie dni INTERMAX" />
    case "failed":
      return <LoadFailure what="dni INTERMAX" message={days.message} reload={reload} />
    case "ready":
      return <DayRow days={days.data} />
    default: {
      const unhandled: never = days

      return unhandled
    }
  }
}

function DayRow({ days }: { days: IntermaxDays }) {
  if (days.problem !== null) {
    return <ThreePartMessage message={days.problem} kind="notice" />
  }

  return (
    <ol className="flex flex-wrap items-center gap-x-4 gap-y-2" aria-label="Dni INTERMAX">
      {days.days.map((day) => (
        <li
          key={day.day}
          className="flex items-center gap-1.5 text-sm tabular-nums"
          aria-label={`${day.label}: ${day.ordered ? "uporządkowany" : "nieuporządkowany"}`}
          aria-current={day.today ? "date" : undefined}
        >
          <span
            data-ordered={day.ordered}
            className={cn(
              "flex size-5 shrink-0 items-center justify-center rounded-full border data-[ordered=true]:border-transparent data-[ordered=true]:bg-secondary",
              day.today && "border-foreground data-[ordered=true]:border-foreground"
            )}
          >
            {day.ordered ? <CheckIcon className="size-3 text-success" aria-hidden /> : null}
          </span>
          <span className={day.ordered ? undefined : "text-muted-foreground"}>{day.label}</span>
        </li>
      ))}
    </ol>
  )
}
