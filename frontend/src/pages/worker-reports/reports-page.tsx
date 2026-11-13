import * as React from "react"
import { BellOffIcon, FileSpreadsheetIcon, MailCheckIcon, SearchIcon } from "lucide-react"

import { getReportsView, keepManualValue, type ReportsView } from "@/api/centrum"
import { LoadFailure } from "@/components/load-failure"
import { PageHeader } from "@/components/page-header"
import { SettingPath } from "@/components/setting-path"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useAction } from "@/lib/action"
import { href, settingsHref, usePagePath } from "@/lib/address"
import { useContentEntrance } from "@/lib/content-entrance"
import { dateTime, plural } from "@/lib/format"
import { useResource } from "@/lib/use-resource"
import { REMINDERS_SECTION } from "@/pages/settings/reminders-section"
import { type DayState, dayState, hasStatus, type Status } from "@/pages/worker-reports/day-state"
import type { Keep } from "@/pages/worker-reports/day-details"
import { type DayRange, rangeFromPath } from "@/pages/worker-reports/days"
import { type HeatRow, HeatMap } from "@/pages/worker-reports/heat-map"
import { RangeBar } from "@/pages/worker-reports/range-bar"
import { EnteringNotes, EnterReportsButton, useReportEntering } from "@/pages/worker-reports/report-entering"
import { StatusFilter } from "@/pages/worker-reports/status-filter"
import { UnknownSenders } from "@/pages/worker-reports/unknown-senders"

/**
 * Raporty: wynik ostatniego kliknięcia „Wpisz raporty z maili” jako Mapa cieplna Wykonawców i dni (#1319). Serwer
 * oddaje całe okno z pliku wyniku, nie ze skrzynki; zakres dni z adresu `#/raporty/<od>/<do>` (bez zakresu:
 * poniedziałek poprzedniego tygodnia do niedzieli bieżącego, przycięte do dni okna), stan dnia, wyszukiwarkę i filtr
 * Status liczy przeglądarka. „Zostaw moją” zastępuje widok odpowiedzią serwera, a koniec Wpisania czyta go od nowa.
 */
export function ReportsPage() {
  const path = usePagePath()
  const { resource: view, reload, replace } = useResource(getReportsView, [], { fromDadFiles: false })
  const entrance = useContentEntrance(view.state === "loading")
  const entering = useReportEntering(reload)
  const ready = view.state === "ready" && view.data.clicked_at !== null ? view.data : null
  const days = React.useMemo(() => ready?.days.map((found) => found.day) ?? [], [ready])
  const range = ready === null ? null : rangeFromPath(path, days, ready.today)

  const { running, run } = useAction(
    async (cell: Keep) => replace({ state: "ready", data: await keepManualValue(cell) }),
    "Nie udało się zostawić Twojej wartości"
  )

  return (
    <>
      <PageHeader
        action={
          <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
            {ready === null || range === null ? null : (
              <RangeBar days={days} today={ready.today} range={range} onRange={showRange} />
            )}
            <EnterReportsButton entering={entering} />
          </div>
        }
      />
      <EnteringNotes entering={entering} />
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-muted-foreground">
        {ready?.clicked_at == null ? null : (
          <p className="tabular-nums">
            {ready.workers.length} {plural(ready.workers.length, { one: "Wykonawca", few: "Wykonawcy", many: "Wykonawców" })}
            {" · "}ostatnie kliknięcie {dateTime(ready.clicked_at)}
          </p>
        )}
        <div className="ml-auto min-w-0">
          <SettingPath label="INTERMAX" icon={<FileSpreadsheetIcon />} path="order_register" />
        </div>
      </div>
      {view.state === "ready" && view.data.reminders_without_footer ? <WithoutFooter /> : null}
      {view.state === "loading" ? <Skeleton className="h-64 w-full" aria-label="Wczytywanie Raportów" /> : null}
      {view.state === "failed" ? <LoadFailure what="Raportów" message={view.message} reload={reload} /> : null}
      {view.state === "ready" && ready === null ? <NoReports className={entrance} /> : null}
      {ready === null || range === null ? null : (
        <ReportsMap
          view={ready}
          range={range}
          keeping={running?.[0] ?? null}
          onKeep={run}
          className={entrance}
        />
      )}
    </>
  )
}

/** Nowy zakres w adresie, więc Wstecz w przeglądarce wraca do poprzedniego. */
function showRange(range: DayRange) {
  window.location.hash = href("raporty", range.from, range.to)
}

/** Spokojna informacja, że ostatnie sprawdzenie przypomnień szło bez stopki; znika po następnym ze stopką. */
function WithoutFooter() {
  return (
    <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
      <BellOffIcon className="size-3.5 shrink-0" aria-hidden />
      Przypomnienia o raporcie idą bez Twojej stopki.
      <a href={settingsHref(REMINDERS_SECTION)} className="text-foreground underline-offset-4 hover:underline">
        Wpisz ją w Ustawieniach
      </a>
    </p>
  )
}

function NoReports({ className }: { className: string | undefined }) {
  return (
    <Empty className={className}>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <MailCheckIcon />
        </EmptyMedia>
        <EmptyTitle>Jeszcze nie ma Raportów</EmptyTitle>
        <EmptyDescription>Kliknij „Wpisz raporty z maili” powyżej.</EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

const NO_STATUS: Readonly<Record<Status, number>> = { problem: 0, without_report: 0, waiting: 0, complete: 0 }

/**
 * Pasek narzędzi (wyszukiwarka, filtr Status) i Mapa cieplna dni zakresu, pod nią Raporty spoza listy adresów z tych
 * dni. Wykonawcy zawsze alfabetycznie; filtr Status zostawia tych, którzy mają w zakresie dzień wybranego stanu.
 */
function ReportsMap({
  view,
  range,
  keeping,
  onKeep,
  className,
}: {
  view: ReportsView
  range: DayRange
  keeping: Keep | null
  onKeep: (cell: Keep) => void
  className: string | undefined
}) {
  const [query, setQuery] = React.useState("")
  const [chosen, setChosen] = React.useState<ReadonlySet<Status>>(new Set())
  const columns = view.days.filter((column) => column.day >= range.from && column.day <= range.to)

  const rows: ReadonlyArray<HeatRow> = view.workers
    .toSorted((left, right) => left.worker.localeCompare(right.worker, "pl"))
    .map(({ worker, days }) => ({
      worker,
      cells: columns.map((column) => ({
        column,
        state: dayState(
          days.find((found) => found.day === column.day),
          column,
          view.today
        ),
      })),
    }))

  const counts = { ...NO_STATUS }

  for (const { state } of rows.flatMap((row) => row.cells)) {
    if (hasStatus(state)) {
      counts[state.kind] += 1
    }
  }

  const needle = query.trim().toLocaleLowerCase("pl")

  const shown = rows.filter(
    (row) =>
      row.worker.toLocaleLowerCase("pl").includes(needle) &&
      (chosen.size === 0 || row.cells.some((cell) => hasChosen(cell.state, chosen)))
  )

  const unknown = view.unknown_senders.filter((sender) => columns.some((column) => column.day === sender.day))

  return (
    <div className={`flex flex-col gap-4 ${className ?? ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            aria-label="Szukaj Wykonawcy"
            placeholder="Szukaj Wykonawcy"
            autoComplete="off"
            className="h-9 pl-8"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <StatusFilter chosen={chosen} counts={counts} onChange={setChosen} />
        {chosen.size === 0 ? null : (
          <span className="text-sm text-muted-foreground tabular-nums" aria-live="polite">
            {shown.length} z {rows.length} Wykonawców
          </span>
        )}
      </div>
      <HeatMap
        columns={columns}
        today={view.today}
        rows={shown}
        dimmed={chosen.size === 0 ? null : chosen}
        empty={chosen.size === 0 ? "Żaden Wykonawca nie pasuje do wyszukiwania." : "Nikt nie ma dni w tym stanie w wybranych dniach."}
        keeping={keeping}
        onKeep={onKeep}
      />
      <UnknownSenders senders={unknown} />
    </div>
  )
}

function hasChosen(state: DayState, chosen: ReadonlySet<Status>): boolean {
  return hasStatus(state) && chosen.has(state.kind)
}
