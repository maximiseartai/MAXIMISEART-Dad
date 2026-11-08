import * as React from "react"
import { cn } from "cn"
import { HistoryIcon, PlayIcon } from "lucide-react"

import { getMetrics, getRunSetup, type ProcessSetup, type RunView } from "@/api/centrum"
import { PageHeader } from "@/components/page-header"
import { LoadFailure } from "@/components/load-failure"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useChangeEntrance, useContentEntrance } from "@/lib/content-entrance"
import { isActive, useRuns } from "@/lib/runs"
import { useSettings } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { RunHistoryCard } from "@/pages/metrics/run-history-card"
import { PastRunCard, RunCard } from "@/pages/runs/run-card"
import { DecisionDialog } from "@/pages/runs/run-dialogs"
import { IntermaxCard } from "@/pages/runs/intermax-card"
import { RunSetupCard } from "@/pages/runs/run-setup-card"
import { UnreadableStream } from "@/pages/runs/unreadable-stream"

/**
 * Uruchomienia: zakładka „Uruchomienie” z nowym Uruchomieniem procesu albo podglądem na żywo bieżącego
 * (wynik, decyzja taty) i zakładka „Historia” z tą samą tabelą co w Metrykach. Stan Uruchomienia pochodzi
 * wyłącznie ze strumienia serwera, więc przetrwa odświeżenie i ponowne otwarcie karty.
 */
export function RunsPage() {
  const { settings } = useSettings()
  const { view } = useRuns()

  return (
    <Tabs defaultValue="uruchomienie" className="gap-6">
      <PageHeader
        action={
          <TabsList>
            <TabsTrigger value="uruchomienie">
              <PlayIcon data-icon="inline-start" />
              Uruchomienie
            </TabsTrigger>
            <TabsTrigger value="historia">
              <HistoryIcon data-icon="inline-start" />
              Historia
            </TabsTrigger>
          </TabsList>
        }
      />
      <TabsContent value="uruchomienie">
        {/* Treść montuje się przy gotowych Ustawieniach taty, więc start czyta raz. */}
        {settings.state === "loading" ? <RunsSkeleton /> : <RunsContent />}
      </TabsContent>
      <TabsContent value="historia">
        {/* Każde zakończone Uruchomienie to nowy odczyt historii z plików metryk. */}
        <RunHistory key={view === null || view.state === "idle" || isActive(view) ? "trwa" : view.run.id} />
      </TabsContent>
    </Tabs>
  )
}

function RunHistory() {
  const { resource: metrics, reload } = useResource(getMetrics, [])
  const entrance = useContentEntrance(metrics.state === "loading")

  switch (metrics.state) {
    case "loading":
      return <Skeleton className="h-64 w-full" aria-label="Wczytywanie historii" />
    case "failed":
      return <LoadFailure what="historii" message={metrics.message} reload={reload} />
    case "ready":
      return (
        <div className={entrance}>
          <RunHistoryCard runs={metrics.data.runs} processes={metrics.data.processes} />
        </div>
      )
    default: {
      const unhandled: never = metrics

      return unhandled
    }
  }
}

function RunsContent() {
  const { resource: setup, reload } = useResource(getRunSetup, [])
  const { view, dismissed, unreadable } = useRuns()
  const finishedRun = view?.state === "finished" ? view.run.id : null
  const entrance = useContentEntrance(view === null || setup.state === "loading")
  // Uruchomienie zakończone albo odłożone przed wejściem na stronę zna już odczyt przy montowaniu.
  const readAfter = React.useRef(finishedRun)
  const readAfterDismissed = React.useRef(dismissed)

  // Zakończone Uruchomienie zmienia Status okresu i historię podglądów, więc wybór okresu czytamy od nowa.
  React.useEffect(() => {
    if (finishedRun !== null && finishedRun !== readAfter.current) {
      readAfter.current = finishedRun
      reload()
    }
  }, [finishedRun, reload])

  // Nad wynikiem tata mógł zamknąć plik albo usunąć pozostawiony `~$` bez wyjścia z okna, więc
  // „Nowe Uruchomienie procesu” czyta pliki od nowa, tak jak powrót do okna.
  React.useEffect(() => {
    if (dismissed !== readAfterDismissed.current) {
      readAfterDismissed.current = dismissed
      reload()
    }
  }, [dismissed, reload])

  if (view === null && unreadable) {
    return <UnreadableStream />
  }

  if (view === null || setup.state === "loading") {
    return <RunsSkeleton />
  }

  if (setup.state === "failed") {
    return <LoadFailure what="Uruchomień" message={setup.message} reload={reload} />
  }

  return <RunOrSetup view={view} processes={setup.data.processes} entrance={entrance} />
}

/**
 * Karta nowego Uruchomienia procesu z kartą „Uporządkuj INTERMAX” pod nią, podgląd na żywo albo ostatnie
 * Uruchomienie sprzed startu Centrum. Zamiana
 * jednej na drugą na oczach taty (start, „Nowe Uruchomienie procesu”) wchodzi `wejscie`; karta zastana po
 * wejściu na stronę nie.
 */
function RunOrSetup({
  view,
  processes,
  entrance,
}: {
  view: RunView
  processes: ReadonlyArray<ProcessSetup>
  entrance: string | undefined
}) {
  const { dismissed, draft, deciding, decide, newRun } = useRuns()

  // Ostatnie Uruchomienie sprzed startu Centrum stoi jak zakończone: „Nowe Uruchomienie procesu” je odkłada.
  const run = view.state === "idle" ? view.previous?.run : view.run
  const ended = view.state === "idle" || view.state === "finished"
  const setupInstead = run === undefined || (ended && (run.id === dismissed || draft !== null))

  const shown = useChangeEntrance(setupInstead, "wejscie") ?? entrance

  if (setupInstead) {
    return (
      <div key="nowe" className={cn(shown, "flex flex-col gap-6")}>
        <RunSetupCard processes={processes} />
        <IntermaxCard />
      </div>
    )
  }

  const reminder = processes.find((process) => process.process === run.process)?.reminder ?? ""

  if (view.state === "idle") {
    return view.previous === null ? null : (
      <div key="ostatnie" className={shown}>
        <PastRunCard past={view.previous} reminder={reminder} onNewRun={() => newRun(run.id)} />
      </div>
    )
  }

  return (
    <div key="podglad" className={shown}>
      <RunCard view={view} reminder={reminder} onNewRun={() => newRun(run.id)} />
      {view.state === "awaiting_decision" ? (
        <DecisionDialog
          decision={view.decision}
          deciding={deciding === view.run.id}
          onDecide={(answer) => decide(view.run.id, answer)}
        />
      ) : null}
    </div>
  )
}

function RunsSkeleton() {
  return (
    <Card aria-busy="true" aria-label="Wczytywanie Uruchomień">
      <CardHeader>
        <Skeleton className="h-6 w-64" />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
        <Skeleton className="h-8 w-full" />
      </CardContent>
    </Card>
  )
}
