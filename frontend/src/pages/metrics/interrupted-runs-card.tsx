import { CircleStopIcon, OctagonXIcon } from "lucide-react"

import type { ProcessRun } from "@/api/generated"
import { Badge } from "@/components/ui/badge"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item"
import { dateTime, seconds } from "@/lib/format"
import { isStopped, measuredPhases, phaseDuration } from "@/pages/metrics/process-runs"

/** Przerwane Uruchomienia procesu wszystkich procesów z czasami etapów zmierzonymi do przerwania. */
export function InterruptedRunsCard({
  phases,
  runs,
}: {
  phases: ReadonlyArray<string>
  runs: ReadonlyArray<ProcessRun>
}) {
  const interrupted = runs.filter(isStopped)

  if (interrupted.length === 0) {
    return null
  }

  return (
    <Card role="region" aria-labelledby="przerwane">
      <CardHeader>
        <CardTitle id="przerwane">Przerwane</CardTitle>
        <CardAction>
          <Badge variant="outline" className="tabular-nums">
            {interrupted.length}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        <ItemGroup>
          {interrupted.map((run) => (
            <Item key={`${run.process}-${run.started_at}`} variant="muted" size="sm">
              <ItemMedia variant="icon">
                {run.tone === "failed" ? (
                  <OctagonXIcon className="text-destructive" />
                ) : (
                  <CircleStopIcon className="text-muted-foreground" />
                )}
              </ItemMedia>
              <ItemContent>
                <ItemTitle className="tabular-nums">
                  {run.process_label} · {run.period} · {run.mode}
                </ItemTitle>
                <ItemDescription className="tabular-nums">{dateTime(run.started_at)}</ItemDescription>
              </ItemContent>
              <ItemActions className="text-sm tabular-nums">
                <PhaseTimes phases={measuredPhases(phases, [run])} run={run} />
              </ItemActions>
            </Item>
          ))}
        </ItemGroup>
      </CardContent>
    </Card>
  )
}

function PhaseTimes({ phases, run }: { phases: ReadonlyArray<string>; run: ProcessRun }) {
  const parts = phases.map((phase) => `${phase} ${seconds(phaseDuration(run, phase))}`)

  return (
    <span>
      {parts.length === 0 ? "etapy bez zmierzonego czasu" : parts.join(" · ")}
      <span className="text-muted-foreground"> · do przerwania {seconds(run.total_duration_ms)}</span>
    </span>
  )
}
