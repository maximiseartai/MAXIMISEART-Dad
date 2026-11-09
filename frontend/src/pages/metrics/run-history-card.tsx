import * as React from "react"
import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon, EyeIcon, HistoryIcon } from "lucide-react"

import type { Metrics, Process, ProcessRun } from "@/api/centrum"
import { RunResultBadge } from "@/components/run-result-badge"
import { SegmentedFilter, type FilterOption } from "@/components/segmented-filter"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { WriteAboutRun } from "@/components/write-to-maks"
import { dateTime, seconds } from "@/lib/format"
import { MODE_OPTIONS, processOptions, type Mode } from "@/pages/metrics/process-runs"
import { RunCardButton } from "@/pages/runs/run-card-sheet"

const PAGE = 10

type SortKey = "started_at" | "total_duration_ms"

type Sort = { key: SortKey; descending: boolean }

const ALL = { value: "all", label: "Wszystkie" } as const

const MODE_FILTER: ReadonlyArray<FilterOption<Mode | "all">> = [ALL, ...MODE_OPTIONS]

/** Historia Uruchomień procesu wszystkich procesów, także z launcherów `.cmd`. */
export function RunHistoryCard({ runs, processes }: { runs: ReadonlyArray<ProcessRun>; processes: Metrics["processes"] }) {
  const processFilter: ReadonlyArray<FilterOption<Process | "all">> = [ALL, ...processOptions(processes)]
  const [process, setProcess] = React.useState<Process | "all">("all")
  const [mode, setMode] = React.useState<Mode | "all">("all")
  const [sort, setSort] = React.useState<Sort>({ key: "started_at", descending: true })
  const [shown, setShown] = React.useState(PAGE)

  const filtered = runs
    .filter((run) => (process === "all" || run.process === process) && (mode === "all" || run.mode === mode))
    .toSorted((left, right) => compare(left, right, sort))

  const visible = filtered.slice(0, shown)

  const sortBy = (key: SortKey) =>
    setSort((current) => ({ key, descending: current.key === key ? !current.descending : true }))

  return (
    <Card role="region" aria-labelledby="historia-uruchomien">
      <CardHeader>
        <CardTitle id="historia-uruchomien">Historia Uruchomień procesu</CardTitle>
        <CardAction className="flex gap-2">
          <SegmentedFilter label="Proces w historii" options={processFilter} value={process} onChange={setProcess} />
          <SegmentedFilter label="Tryb w historii" options={MODE_FILTER} value={mode} onChange={setMode} />
        </CardAction>
      </CardHeader>
      <CardContent>
        {filtered.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <HistoryIcon />
              </EmptyMedia>
              <EmptyTitle>Brak Uruchomień procesu dla tych filtrów</EmptyTitle>
            </EmptyHeader>
          </Empty>
        ) : (
          <Table aria-labelledby="historia-uruchomien">
            <TableHeader>
              <TableRow>
                <SortableHead label="Data" sortKey="started_at" sort={sort} onSort={sortBy} />
                <TableHead>Proces</TableHead>
                <TableHead>Okres</TableHead>
                <TableHead>Wynik</TableHead>
                <SortableHead label="Czas" sortKey="total_duration_ms" sort={sort} onSort={sortBy} end />
                <TableHead className="w-20">
                  <span className="sr-only">Karta Uruchomienia i Uwaga</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((run) => (
                <RunRow key={`${run.process}-${run.started_at}`} run={run} />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      {filtered.length > shown ? (
        <CardFooter className="justify-center">
          <Button variant="ghost" onClick={() => setShown((current) => current + PAGE)}>
            Pokaż starsze
          </Button>
        </CardFooter>
      ) : null}
    </Card>
  )
}

function compare(left: ProcessRun, right: ProcessRun, sort: Sort): number {
  const order =
    sort.key === "started_at"
      ? Date.parse(left.started_at) - Date.parse(right.started_at)
      : left.total_duration_ms - right.total_duration_ms

  return sort.descending ? -order : order
}

function SortableHead({
  label,
  sortKey,
  sort,
  onSort,
  end = false,
}: {
  label: string
  sortKey: SortKey
  sort: Sort
  onSort: (key: SortKey) => void
  end?: boolean
}) {
  const active = sort.key === sortKey
  const Icon = active ? (sort.descending ? ArrowDownIcon : ArrowUpIcon) : ArrowUpDownIcon
  let ariaSort: "descending" | "ascending" | "none" = "none"

  if (active) {
    ariaSort = sort.descending ? "descending" : "ascending"
  }

  return (
    <TableHead aria-sort={ariaSort} className={end ? "text-right" : undefined}>
      <Button variant="ghost" size="sm" className="-mx-2" onClick={() => onSort(sortKey)}>
        {label}
        <Icon data-icon="inline-end" aria-hidden />
      </Button>
    </TableHead>
  )
}

function RunRow({ run }: { run: ProcessRun }) {
  return (
    <TableRow>
      <TableCell className="tabular-nums">{dateTime(run.started_at)}</TableCell>
      <TableCell>
        <span className="flex items-center gap-2">
          {run.process_label}
          {run.mode === "DRY-RUN" ? (
            <Tooltip>
              <TooltipTrigger
                render={
                  <span
                    tabIndex={0}
                    className="inline-flex rounded-md text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&_svg]:size-4"
                  />
                }
              >
                <EyeIcon aria-hidden />
                <span className="sr-only">DRY-RUN</span>
              </TooltipTrigger>
              <TooltipContent>DRY-RUN: podgląd bez zapisu</TooltipContent>
            </Tooltip>
          ) : null}
          {run.origin === "cmd" ? (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Badge
                    variant="ghost"
                    tabIndex={0}
                    className="text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  />
                }
              >
                .cmd
              </TooltipTrigger>
              <TooltipContent>Uruchomione launcherem .cmd</TooltipContent>
            </Tooltip>
          ) : null}
        </span>
      </TableCell>
      <TableCell className="tabular-nums">{run.period}</TableCell>
      <TableCell>
        <RunResultBadge run={run} />
      </TableCell>
      <TableCell className="text-right tabular-nums">{seconds(run.total_duration_ms)}</TableCell>
      <TableCell className="py-0">
        <span className="flex justify-end">
          <RunCardButton run={run} />
          {run.run_id === null ? null : <WriteAboutRun runId={run.run_id} className="text-muted-foreground" />}
        </span>
      </TableCell>
    </TableRow>
  )
}
