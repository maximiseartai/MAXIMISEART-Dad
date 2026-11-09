import { TimerOffIcon } from "lucide-react"

import type { Percentiles, ProcessRun } from "@/api/generated"
import { isFailure } from "@/components/run-result-badge"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { dateTime, seconds } from "@/lib/format"
import { isStopped, measuredPhases, phaseDuration, stopWord } from "@/pages/metrics/process-runs"
import { StageTimesChart } from "@/pages/metrics/stage-times-chart"

// Ostatnie Uruchomienia procesu na wykresie; starsze są w historii.
const CHART_RUNS = 12

export function StageTimesCard({
  phases,
  runs,
  percentiles,
}: {
  phases: ReadonlyArray<string>
  runs: ReadonlyArray<ProcessRun>
  percentiles: Percentiles | undefined
}) {
  const recent = runs.slice(0, CHART_RUNS).toReversed()
  const shown = measuredPhases(phases, recent)

  return (
    <Card>
      <Tabs defaultValue="wykres" className="gap-4">
        <CardHeader>
          <CardTitle id="czasy-etapow">Czasy etapów</CardTitle>
          <CardAction>
            <TabsList>
              <TabsTrigger value="wykres">Wykres</TabsTrigger>
              <TabsTrigger value="tabela">Tabela</TabsTrigger>
            </TabsList>
          </CardAction>
        </CardHeader>
        <CardContent>
          {recent.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <TimerOffIcon />
                </EmptyMedia>
                <EmptyTitle>Ten proces nie był jeszcze uruchomiony w tym trybie</EmptyTitle>
              </EmptyHeader>
            </Empty>
          ) : (
            <>
              <TabsContent value="wykres">
                <StageTimesChart phases={phases} shown={shown} runs={recent} />
              </TabsContent>
              <TabsContent value="tabela">
                <StageTimesTable phases={shown} runs={recent.toReversed()} percentiles={percentiles} />
              </TabsContent>
            </>
          )}
        </CardContent>
      </Tabs>
    </Card>
  )
}

function StageTimesTable({
  phases,
  runs,
  percentiles,
}: {
  phases: ReadonlyArray<string>
  runs: ReadonlyArray<ProcessRun>
  percentiles: Percentiles | undefined
}) {
  const phaseRange = (phase: string) => percentiles?.phases.find((entry) => entry.phase === phase)

  return (
    <Table aria-labelledby="czasy-etapow">
      <TableHeader>
        <TableRow>
          <TableHead>Data</TableHead>
          <TableHead>Okres</TableHead>
          {phases.map((phase) => (
            <TableHead key={phase} className="text-right">
              {phase}
            </TableHead>
          ))}
          <TableHead className="text-right">Całość</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.started_at}>
            <TableCell className="tabular-nums">
              {dateTime(run.started_at)}
              {isStopped(run) ? (
                <span className={isFailure(run) ? "text-destructive" : "text-muted-foreground"}> ✕ {stopWord(run)}</span>
              ) : null}
            </TableCell>
            <TableCell className="tabular-nums">{run.period}</TableCell>
            {phases.map((phase) => (
              <TableCell key={phase} className="text-right tabular-nums">
                {phaseDuration(run, phase) > 0 ? seconds(phaseDuration(run, phase)) : "–"}
              </TableCell>
            ))}
            <TableCell className="text-right tabular-nums">{seconds(run.total_duration_ms)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
      {percentiles === undefined ? null : (
        <TableFooter>
          {(["p50_ms", "p95_ms"] as const).map((key) => (
            <TableRow key={key}>
              <TableCell colSpan={2} className="font-medium">
                {key === "p50_ms" ? "P50" : "P95"}
              </TableCell>
              {phases.map((phase) => {
                const range = phaseRange(phase)

                return (
                  <TableCell key={phase} className="text-right tabular-nums">
                    {range === undefined ? "–" : seconds(range[key])}
                  </TableCell>
                )
              })}
              <TableCell className="text-right tabular-nums">{seconds(percentiles[key])}</TableCell>
            </TableRow>
          ))}
        </TableFooter>
      )}
    </Table>
  )
}
