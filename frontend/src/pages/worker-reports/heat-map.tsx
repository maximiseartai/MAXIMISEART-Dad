import { cn } from "cn"
import { BellIcon, ClockIcon } from "lucide-react"

import type { ReportsDay } from "@/api/generated"
import { Card } from "@/components/ui/card"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { dayMonth, plural } from "@/lib/format"
import { type Choice, type DayState, hasStatus, isChosen, type Status } from "@/pages/worker-reports/day-state"
import { DayDetails, type Keep, WorkerAvatar } from "@/pages/worker-reports/day-details"
import { columnLabel, shortDay } from "@/pages/worker-reports/days"
import { look } from "@/pages/worker-reports/status"

/** Wiersz Mapy cieplnej: Wykonawca i stan dnia w każdej kolumnie zakresu. */
export type HeatRow = { worker: string; cells: ReadonlyArray<{ column: ReportsDay; state: DayState }> }

/**
 * Mapa cieplna Raportów: wiersz to Wykonawca, kolumna to dzień zakresu, kafelek „wpisane/zlecenia” w kolorze stanu z
 * popoverem dnia i znaczkiem dzwonka, gdy za ten dzień poszło Przypomnienie o raporcie, na końcu pierścień wpisanych
 * w zakresie. Kolumna Wykonawcy bierze wolne miejsce, kolumny dni mają stałą szerokość, a na wąskim ekranie tabela
 * przewija się w bok wewnątrz karty.
 * `dimmed` to filtr Status: kafelki niewybranych dni i dni przyszłe przygasają, a przy Przypomnianych linia pod
 * Wykonawcą liczy jego przypomnienia.
 */
export function HeatMap({
  columns,
  today,
  rows,
  dimmed,
  empty,
  keeping,
  onKeep,
}: {
  columns: ReadonlyArray<ReportsDay>
  today: string
  rows: ReadonlyArray<HeatRow>
  dimmed: ReadonlySet<Choice> | null
  empty: string
  keeping: Keep | null
  onKeep: (cell: Keep) => void
}) {
  return (
    <Card className="gap-0 py-0">
      <Table aria-label="Mapa Raportów" className="text-[0.82rem]">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-full min-w-60 pl-5 font-medium text-muted-foreground">Wykonawca</TableHead>
            {columns.map((column) => (
              <DayHead key={column.day} column={column} today={today} />
            ))}
            <TableHead className="w-42 min-w-42 px-5 font-medium text-muted-foreground">Wpisane</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody className="[&_tr:first-child_td[data-day]]:pt-2 [&_tr:last-child_td[data-day]]:pb-2">
          {rows.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columns.length + 2} className="py-8 text-center text-muted-foreground">
                {empty}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <WorkerRow
                key={row.worker}
                row={row}
                today={today}
                dimmed={dimmed}
                keeping={keeping}
                onKeep={onKeep}
              />
            ))
          )}
        </TableBody>
      </Table>
    </Card>
  )
}

function columnClass(column: ReportsDay, today: string): string {
  return cn(
    "w-[3.2rem] min-w-[3.2rem] px-1 text-center",
    column.holiday !== null && "bg-warning/10",
    column.holiday === null && column.day === today && "bg-muted/60"
  )
}

function DayHead({ column, today }: { column: ReportsDay; today: string }) {
  const { number, weekday } = columnLabel(column.day)
  const holiday = column.holiday !== null

  return (
    <TableHead
      className={cn(columnClass(column, today), "py-3")}
      title={holiday ? `${shortDay(column.day)} · ${column.holiday}` : shortDay(column.day)}
      aria-label={holiday ? `${shortDay(column.day)}, święto: ${column.holiday}` : shortDay(column.day)}
    >
      <span className="flex flex-col items-center gap-0.5 text-[0.66rem] font-normal text-muted-foreground tabular-nums">
        <b
          className={cn(
            "min-w-[1.6rem] text-[0.8rem] leading-5 font-semibold text-foreground",
            column.day === today && "rounded-full bg-primary px-1.5 text-primary-foreground"
          )}
        >
          {number}
        </b>
        <span className={cn(holiday && "text-warning-tile-foreground")}>{holiday ? "Św." : weekday}</span>
      </span>
    </TableHead>
  )
}

function WorkerRow({
  row,
  today,
  dimmed,
  keeping,
  onKeep,
}: {
  row: HeatRow
  today: string
  dimmed: ReadonlySet<Choice> | null
  keeping: Keep | null
  onKeep: (cell: Keep) => void
}) {
  const totals = totalsOf(row.cells.map((cell) => cell.state))
  const line = dimmed?.has("reminded") ? remindersLine(totals) : summary(totals)

  return (
    <TableRow aria-label={row.worker}>
      <TableCell className="py-2 pl-5">
        <span className="flex items-center gap-2.5">
          <WorkerAvatar worker={row.worker} />
          <span className="flex min-w-0 flex-col">
            <span className="truncate font-medium">{row.worker}</span>
            <span className={cn("text-xs", line.tone)}>{line.text}</span>
          </span>
        </span>
      </TableCell>
      {row.cells.map(({ column, state }) => (
        <TableCell
          key={column.day}
          data-day={column.day}
          className={cn(columnClass(column, today), "py-1", state.kind === "sunday" && "niedziela")}
        >
          <Tile worker={row.worker} state={state} dimmed={dimmed} keeping={keeping} onKeep={onKeep} />
        </TableCell>
      ))}
      <TableCell className="px-5 py-2">
        <Ring entered={totals.entered} orders={totals.orders} />
      </TableCell>
    </TableRow>
  )
}

const TILE = "relative grid h-11 w-full place-items-center rounded-lg text-[0.72rem] font-semibold tabular-nums"

function Tile({
  worker,
  state,
  dimmed,
  keeping,
  onKeep,
}: {
  worker: string
  state: DayState
  dimmed: ReadonlySet<Choice> | null
  keeping: Keep | null
  onKeep: (cell: Keep) => void
}) {
  if (state.kind === "future") {
    return (
      <span className={cn(TILE, "font-normal text-muted-foreground", dimmed !== null && "opacity-15")}>{state.orders}</span>
    )
  }

  if (!hasStatus(state)) {
    return null
  }

  const { day } = state

  return (
    <Popover>
      <PopoverTrigger
        aria-label={tileLabel(worker, state)}
        data-status={state.kind}
        className={cn(
          TILE,
          look(state.kind).tile,
          "cursor-pointer transition-transform duration-150 ease-out outline-none hover:brightness-95 focus-visible:ring-3 focus-visible:ring-ring/50 active:scale-95 data-popup-open:ring-2 data-popup-open:ring-foreground dark:hover:brightness-115",
          dimmed !== null && !isChosen(state, dimmed) && "opacity-15"
        )}
      >
        {state.kind === "waiting" ? <ClockIcon className="size-4" aria-hidden /> : `${day.entered}/${day.orders}`}
        {day.reminders.length > 0 ? <ReminderPin /> : null}
      </PopoverTrigger>
      <PopoverContent
        aria-label={`${worker}, ${shortDay(day.day)}`}
        className="max-h-[min(32rem,var(--available-height))] w-92 gap-0 overflow-y-auto p-0 duration-150 ease-out"
      >
        <DayDetails worker={worker} state={state} keeping={keeping} onKeep={onKeep} />
      </PopoverContent>
    </Popover>
  )
}

/** Nazwa kafelka: `wykonawca.b, cz. 05.11: Bez raportu, wpisane 1 z 2`, z liczbą wysłanych Przypomnień o raporcie. */
function tileLabel(worker: string, state: Extract<DayState, { kind: Status }>): string {
  const { day } = state
  const shown = `${worker}, ${shortDay(day.day)}: ${look(state.kind).label}, wpisane ${day.entered} z ${day.orders}`
  const count = day.reminders.length

  if (count === 0) {
    return shown
  }

  return `${shown}, ${count} ${plural(count, { one: "przypomnienie wysłane", few: "przypomnienia wysłane", many: "przypomnień wysłanych" })}`
}

/** Znaczek dzwonka w rogu kafelka: za ten dzień poszło Przypomnienie o raporcie. */
function ReminderPin() {
  return (
    <span
      data-reminder-pin
      className="absolute -top-1.5 -right-1.5 grid size-4.5 place-items-center rounded-full bg-reminder text-white ring-2 ring-card"
      aria-hidden
    >
      <BellIcon className="size-2.5" strokeWidth={2.4} />
    </span>
  )
}

type Totals = {
  orders: number
  entered: number
  problems: number
  withoutReport: number
  waiting: boolean
  any: boolean
  reminders: string[]
}

/** Liczby Wykonawcy w zakresie: dni z wynikiem kliknięcia, bez dni przyszłych. */
function totalsOf(states: ReadonlyArray<DayState>): Totals {
  const totals: Totals = { orders: 0, entered: 0, problems: 0, withoutReport: 0, waiting: false, any: false, reminders: [] }

  for (const state of states) {
    if (!hasStatus(state)) {
      continue
    }

    totals.any = true
    totals.orders += state.day.orders
    totals.entered += state.day.entered
    totals.problems += state.day.problems.length
    totals.withoutReport += state.kind === "waiting" ? 0 : state.day.without_report.length
    totals.waiting ||= state.kind === "waiting"
    totals.reminders.push(...state.day.reminders)
  }

  return totals
}

/** Linia pod nazwą Wykonawcy przy filtrze Przypomniane: `3 przypomnienia · ost. 13.11` albo `Bez przypomnień`. */
function remindersLine(totals: Totals): Summary {
  const last = totals.reminders.toSorted((left, right) => Date.parse(left) - Date.parse(right)).at(-1)

  if (last === undefined) {
    return { text: "Bez przypomnień", tone: "text-muted-foreground" }
  }

  const count = totals.reminders.length
  const word = plural(count, { one: "przypomnienie", few: "przypomnienia", many: "przypomnień" })

  return { text: `${count} ${word} · ost. ${dayMonth(last)}`, tone: "text-reminder-tile-foreground" }
}

/** Linia pod nazwą Wykonawcy: tekst i jego kolor. */
type Summary = { text: string; tone: string }

/** Krótki stan Wykonawcy pod nazwą: `1 problem · 1 bez raportu`, `2 bez raportu`, `Czeka na raport`, `Komplet`. */
function summary(totals: Totals): Summary {
  if (totals.problems > 0) {
    const problems = `${totals.problems} ${plural(totals.problems, { one: "problem", few: "problemy", many: "problemów" })}`

    return {
      text: totals.withoutReport > 0 ? `${problems} · ${totals.withoutReport} bez raportu` : problems,
      tone: "text-destructive",
    }
  }

  if (totals.withoutReport > 0) {
    return { text: `${totals.withoutReport} bez raportu`, tone: "text-warning-tile-foreground" }
  }

  if (totals.waiting) {
    return { text: "Czeka na raport", tone: "text-muted-foreground" }
  }

  return totals.any
    ? { text: "Komplet", tone: "text-success-tile-foreground" }
    : { text: "Bez zleceń w tych dniach", tone: "text-muted-foreground" }
}

const RADIUS = 9

const CIRCUMFERENCE = 2 * Math.PI * RADIUS

/** Pierścień wpisanych zleceń w zakresie: `96%` i `50 z 52 wpisanych`; bez zleceń tylko kreska. */
function Ring({ entered, orders }: { entered: number; orders: number }) {
  if (orders === 0) {
    return <span className="text-muted-foreground">—</span>
  }

  const ratio = entered / orders
  const color = ratio >= 1 ? "var(--success)" : ratio >= 0.9 ? "var(--warning)" : "var(--destructive)"

  return (
    <span className="flex items-center gap-2.5 whitespace-nowrap" aria-label={`Wpisane ${entered} z ${orders}`}>
      <svg viewBox="0 0 24 24" className="size-7 -rotate-90" aria-hidden>
        <circle cx="12" cy="12" r={RADIUS} fill="none" stroke="var(--muted)" strokeWidth="3" />
        <circle
          cx="12"
          cy="12"
          r={RADIUS}
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={`${CIRCUMFERENCE * ratio} ${CIRCUMFERENCE}`}
        />
      </svg>
      <span className="flex flex-col">
        <b className="text-[0.82rem] font-semibold tabular-nums">{Math.floor(ratio * 100)}%</b>
        <span className="text-xs text-muted-foreground tabular-nums">
          {entered} z {orders} wpisanych
        </span>
      </span>
    </span>
  )
}
