import { cn } from "cn"
import { CheckIcon, FileSpreadsheetIcon, HistoryIcon, InfoIcon, ListOrderedIcon } from "lucide-react"

import {
  getIntermaxDays,
  getIntermaxSetup,
  type IntermaxDays,
  type IntermaxSetup,
  type RunRestored,
} from "@/api/centrum"
import { LoadFailure } from "@/components/load-failure"
import { SettingPath } from "@/components/setting-path"
import { ThreePartMessage } from "@/components/three-part-message"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { WarningSentences } from "@/components/warning-sentences"
import { dateTime } from "@/lib/format"
import { useRuns } from "@/lib/runs"
import { useResource } from "@/lib/use-resource"
import { RestoredCardButton } from "@/pages/runs/run-card-sheet"

/**
 * Karta „Uporządkuj INTERMAX” poza okresami: INTERMAX to Rejestr zleceń z Ustawień taty, tu pod nazwą, którą zna tata,
 * więc jest tylko jeden przycisk. INTERMAX otwarty w Excelu albo niewskazany wyłącza go, a zdanie nad nim mówi, co zrobić. Pod plikiem
 * stoi 7 ostatnich dni INTERMAX i późniejsze Dni uporządkowane z ikoną Dnia uporządkowanego, a pod nimi ostatnie Uporządkowanie z Logów
 * Uruchomienia, którego pełna karta otwiera się z boku.
 */
export function IntermaxCard() {
  const { resource: setup, reload } = useResource(getIntermaxSetup, [])

  switch (setup.state) {
    case "loading":
      return <Skeleton className="h-44 w-full" aria-label="Wczytywanie Uporządkowania INTERMAX" />
    case "failed":
      return <LoadFailure what="Uporządkowania INTERMAX" message={setup.message} reload={reload} />
    case "ready":
      return <IntermaxSetupCard setup={setup.data} />
    default: {
      const unhandled: never = setup

      return unhandled
    }
  }
}

function IntermaxSetupCard({ setup }: { setup: IntermaxSetup }) {
  const { starting, start } = useRuns()
  const blocked = setup.blocker !== null || setup.open_in_excel.length > 0
  const notes = setup.blocker === null ? setup.open_in_excel : [setup.blocker, ...setup.open_in_excel]

  return (
    <Card role="region" aria-label="Uporządkuj INTERMAX">
      <CardHeader>
        <CardTitle className="text-lg">{setup.title}</CardTitle>
        <CardDescription>Zlecenia dnia wklejone na dół INTERMAX.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <SettingPath label="INTERMAX" icon={<FileSpreadsheetIcon />} path="order_register" />
        {setup.blocker === null ? <RegisterDays /> : null}
        <WarningSentences sentences={notes} />
        {setup.last === null ? null : <LastOrdering last={setup.last} />}
      </CardContent>
      <CardFooter className="gap-2">
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          <InfoIcon className="size-4" aria-hidden />
          {setup.reminder}
        </span>
        <Button
          size="lg"
          className="ml-auto h-11 px-5 text-base"
          disabled={blocked || starting}
          onClick={() => start({ process: "intermax" })}
        >
          <ListOrderedIcon data-icon="inline-start" />
          Uporządkuj INTERMAX
        </Button>
      </CardFooter>
    </Card>
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

/** Ostatnie Uporządkowanie INTERMAX jednym cichym zdaniem: kiedy, wynik i uporządkowany dzień. */
function LastOrdering({ last }: { last: RunRestored }) {
  const day = last.result.summary?.counts?.counts[0]?.label

  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
      <HistoryIcon className="size-4 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">
        Ostatnio {dateTime(last.started_at)} · {last.result.headline}
        {day === undefined ? null : ` · ${day}`}
      </span>
      <span className="ml-auto">
        <RestoredCardButton card={last} />
      </span>
    </div>
  )
}
