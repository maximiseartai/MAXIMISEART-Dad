import * as React from "react"
import { cn } from "cn"
import { ChartColumnIcon, GaugeIcon, ListChecksIcon, TimerIcon } from "lucide-react"

import { getMetrics, type Metrics, type Process } from "@/api/centrum"
import { PageHeader } from "@/components/page-header"
import { otherResults } from "@/components/run-result-badge"
import { LoadFailure } from "@/components/load-failure"
import { SegmentedFilter } from "@/components/segmented-filter"
import { StatStrip } from "@/components/stat-strip"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { useContentEntrance } from "@/lib/content-entrance"
import { seconds } from "@/lib/format"
import { useResource } from "@/lib/use-resource"
import { InterruptedRunsCard } from "@/pages/metrics/interrupted-runs-card"
import { MODE_OPTIONS, processOptions, type Mode } from "@/pages/metrics/process-runs"
import { RunHistoryCard } from "@/pages/metrics/run-history-card"
import { StageTimesCard } from "@/pages/metrics/stage-times-card"

export function MetricsPage() {
  const { resource: metrics, reload } = useResource(getMetrics, [])
  const [chosen, setProcess] = React.useState<Process | null>(null)
  const [mode, setMode] = React.useState<Mode>("RUN")
  const hasRuns = metrics.state === "ready" && metrics.data.runs.length > 0
  const processes = metrics.state === "ready" ? processOptions(metrics.data.processes) : []
  // Dopóki tata nie wybierze, filtr stoi na pierwszym procesie z serwera.
  const process = chosen ?? processes[0]?.value ?? null
  const entrance = useContentEntrance(metrics.state === "loading")

  // Tryby procesu mówi serwer: ma statystyki tylko w trybach procesu (Uporządkowanie INTERMAX nie ma DRY-RUN).
  const modes =
    metrics.state === "ready"
      ? MODE_OPTIONS.filter((option) =>
          metrics.data.statistics.some((entry) => entry.process === process && entry.mode === option.value)
        )
      : MODE_OPTIONS

  const shownMode = modes.some((option) => option.value === mode) ? mode : (modes[0]?.value ?? mode)

  // Jeden filtr w nagłówku steruje statystykami i wykresem; historia ma własne filtry.
  const filters = hasRuns && process !== null ? (
    <>
      <SegmentedFilter label="Proces" options={processes} value={process} onChange={setProcess} />
      <SegmentedFilter label="Tryb" options={modes} value={shownMode} onChange={setMode} />
    </>
  ) : undefined

  return (
    <>
      <PageHeader action={filters} />
      {metrics.state === "loading" ? <MetricsSkeleton /> : null}
      {metrics.state === "failed" ? <LoadFailure what="metryk" message={metrics.message} reload={reload} /> : null}
      {metrics.state === "ready" && !hasRuns ? <NoMetrics /> : null}
      {metrics.state === "ready" && hasRuns && process !== null ? (
        <MetricsContent metrics={metrics.data} process={process} mode={shownMode} className={entrance} />
      ) : null}
    </>
  )
}

function MetricsContent({
  metrics,
  process,
  mode,
  className,
}: {
  metrics: Metrics
  process: Process
  mode: Mode
  className: string | undefined
}) {
  const runs = metrics.runs.filter((run) => run.process === process && run.mode === mode)
  const statistics = metrics.statistics.find((entry) => entry.process === process && entry.mode === mode)
  const percentiles = statistics?.percentiles ?? undefined
  const tooFew = `od ${metrics.minimum_completed_runs} ukończonych (jest ${statistics?.completed_runs ?? 0})`

  return (
    <div className={cn(className, "flex flex-col gap-6")}>
      <StatStrip
        label="Statystyki"
        stats={[
          {
            label: "P50",
            icon: <TimerIcon aria-hidden />,
            value: percentiles === undefined ? "–" : seconds(percentiles.p50_ms),
            note: percentiles === undefined ? tooFew : "typowy czas",
          },
          {
            label: "P95",
            icon: <GaugeIcon aria-hidden />,
            value: percentiles === undefined ? "–" : seconds(percentiles.p95_ms),
            note: percentiles === undefined ? tooFew : "najdłuższy zwykły czas",
          },
          {
            label: "Wyniki",
            icon: <ListChecksIcon aria-hidden />,
            value: `${statistics?.results.ok ?? 0} OK`,
            note: statistics === undefined ? undefined : otherResults(statistics.results),
          },
        ]}
      />
      <StageTimesCard phases={metrics.phases} runs={runs} percentiles={percentiles} />
      <InterruptedRunsCard phases={metrics.phases} runs={metrics.runs} />
      <RunHistoryCard runs={metrics.runs} processes={metrics.processes} />
    </div>
  )
}

function NoMetrics() {
  return (
    <Card>
      <CardContent>
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ChartColumnIcon />
            </EmptyMedia>
            <EmptyTitle>Jeszcze nie ma metryk</EmptyTitle>
            <EmptyDescription>
              Pojawią się po pierwszym Uruchomieniu procesu, z Centrum albo z launchera .cmd.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </CardContent>
    </Card>
  )
}

function MetricsSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Wczytywanie metryk">
      <Skeleton className="h-28 w-full rounded-xl" />
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-36" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-72 w-full" />
        </CardContent>
      </Card>
    </div>
  )
}
