import { cn } from "cn"
import { FolderSearchIcon, FolderXIcon } from "lucide-react"

import { getMetrics, getPeriodBoard, type PeriodBoard } from "@/api/centrum"
import type { Metrics } from "@/api/generated"
import { PageHeader } from "@/components/page-header"
import { LoadFailure } from "@/components/load-failure"
import { SetInSettings } from "@/components/setting-path"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { useContentEntrance } from "@/lib/content-entrance"
import { useSettings } from "@/lib/settings"
import { useResource, type Resource } from "@/lib/use-resource"
import { NextStepCard } from "@/pages/periods/next-step-card"
import { PeriodBoardTable } from "@/pages/periods/period-board-table"
import { PeriodStats } from "@/pages/periods/period-stats"

export function PeriodsPage() {
  return (
    <>
      <PageHeader />
      <PeriodsContent />
    </>
  )
}

/**
 * Tablica okresów i metryki czytają się od razu, razem z Ustawieniami taty, a nie po kolei po nich.
 * Każdy nieudany odczyt strony pokazuje jeden Komunikat, a jego „Spróbuj ponownie” czyta od nowa wszystkie,
 * które się nie udały: jedno kliknięcie przywraca całą stronę.
 */
function PeriodsContent() {
  const { settings, reload: reloadSettings } = useSettings()
  const { resource: board, reload: reloadBoard } = useResource(getPeriodBoard, [])
  const { resource: metrics, reload: reloadMetrics } = useResource(getMetrics, [])
  const entrance = useContentEntrance(settings.state === "loading")

  const failures = [
    { what: "okresów", resource: settings, reload: reloadSettings },
    { what: "okresów", resource: board, reload: reloadBoard },
    { what: "najważniejszych liczb", resource: metrics, reload: reloadMetrics },
  ].flatMap(({ what, resource, reload }) =>
    resource.state === "failed" ? [{ what, message: resource.message, reload }] : []
  )

  const [first] = failures
  const retry = () => Promise.all(failures.map((failure) => failure.reload())).then(() => undefined)

  return (
    <>
      {first === undefined ? null : <LoadFailure what={first.what} message={first.message} reload={retry} />}
      {settings.state === "loading" ? <PeriodsSkeleton /> : null}
      {settings.state === "ready" ? (
        <div className={cn(entrance, "flex flex-col gap-6")}>
          <PeriodBoardSection board={board} metrics={metrics} reload={reloadBoard} />
        </div>
      ) : null}
    </>
  )
}

/** Nieudany odczyt Tablicy okresów pokazuje Komunikat strony nad nią, więc tu nie ma nic. */
function PeriodBoardSection({
  board,
  metrics,
  reload,
}: {
  board: Resource<PeriodBoard>
  metrics: Resource<Metrics>
  reload: () => void
}) {
  switch (board.state) {
    case "loading":
      return <PeriodsSkeleton />
    case "failed":
      return null
    case "ready":
      return <BoardContent board={board.data} metrics={metrics} reload={reload} />
    default: {
      const unhandled: never = board

      return unhandled
    }
  }
}

function BoardContent({
  board,
  metrics,
  reload,
}: {
  board: PeriodBoard
  metrics: Resource<Metrics>
  reload: () => void
}) {
  switch (board.state) {
    case "not_set":
      return (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FolderSearchIcon />
            </EmptyMedia>
            <EmptyTitle>Wskaż folder okresów</EmptyTitle>
            <EmptyDescription>Centrum znajdzie w nim Foldery okresu.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <SetInSettings primary />
          </EmptyContent>
        </Empty>
      )
    case "missing":
      return (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FolderXIcon />
            </EmptyMedia>
            <EmptyTitle>Nie ma folderu okresów {board.name}</EmptyTitle>
            <EmptyDescription>Mógł zostać przeniesiony albo przemianowany.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <SetInSettings primary />
          </EmptyContent>
        </Empty>
      )
    case "ready": {
      const lastComplete = board.periods.find((period) => period.last_complete)

      return (
        <>
          {lastComplete === undefined ? null : <NextStepCard period={lastComplete} />}
          <PeriodStats periods={board.periods} lastPrepared={board.last_prepared_period} metrics={metrics} />
          <PeriodBoardTable periods={board.periods} onStale={reload} />
        </>
      )
    }

    default: {
      const unhandled: never = board

      return unhandled
    }
  }
}

function PeriodsSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Wczytywanie okresów">
      <Card>
        <CardContent className="flex flex-col gap-4 py-2">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-9 w-96" />
          <Skeleton className="h-4 w-72" />
          <Skeleton className="h-6 w-[30rem]" />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-36" />
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {[0, 1, 2, 3, 4].map((row) => (
            <Skeleton key={row} className="h-10 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
