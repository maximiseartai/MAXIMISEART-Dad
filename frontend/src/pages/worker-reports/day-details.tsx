import { ArrowLeftRightIcon, BellIcon } from "lucide-react"
import { cn } from "cn"

import type { KeptCell, ReportsNote, ReportsOrder, ReportsProblem } from "@/api/generated"
import { Button } from "@/components/ui/button"
import { dayMonth, hourMinute, plural } from "@/lib/format"
import type { DayState, Status } from "@/pages/worker-reports/day-state"
import { shortDay } from "@/pages/worker-reports/days"
import { look, StatusBadge } from "@/pages/worker-reports/status"

/** Komórka różnicy z ręczną wartością, przy której tata klika „Zostaw moją”. */
export type Keep = KeptCell

type Keeping = { keeping: Keep | null; onKeep: (cell: Keep) => void }

/** Inicjały Wykonawcy do kółka przy nazwie: `Marcin Górski` → `MG`, `wykonawca.a` → `WA`. */
function initials(worker: string): string {
  return worker
    .split(/[\s._-]+/)
    .filter((part) => part.length > 0)
    .slice(0, 2)
    .map((part) => part.charAt(0).toLocaleUpperCase("pl"))
    .join("")
}

export function WorkerAvatar({ worker }: { worker: string }) {
  return (
    <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-[0.66rem] font-semibold" aria-hidden>
      {initials(worker)}
    </span>
  )
}

/**
 * Popover kafelka: Wykonawca, dzień i stan, liczby dnia, pasek wpisanych w kolorze stanu i zlecenia dnia z INTERMAX
 * (`orders_detail`) z problemami, „Zostaw moją” i spokojnymi informacjami o Przeniesieniach zleceń (`notes`). Wynik
 * kliknięcia sprzed listy zleceń (`orders_detail` `null`) pokazuje zamiast niej numery bez raportu i problemy. Pod listą
 * pory Przypomnień o raporcie za ten dzień (`reminders`).
 */
export function DayDetails({
  worker,
  state,
  keeping,
  onKeep,
}: { worker: string; state: Extract<DayState, { kind: Status }> } & Keeping) {
  const { day } = state
  const ratio = day.orders === 0 ? 1 : day.entered / day.orders

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2.5 px-3.5 pt-3.5 pb-2.5">
        <WorkerAvatar worker={worker} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold">{worker}</p>
          <p className="text-muted-foreground tabular-nums">{shortDay(day.day)}</p>
        </div>
        <StatusBadge status={state.kind} />
      </div>
      <dl className="grid grid-cols-3 gap-2 px-3.5 pb-2.5">
        <Figure label="Zlecenia" value={day.orders} />
        <Figure label="Wpisane" value={day.entered} />
        <Figure label="Maile" value={day.mails} />
      </dl>
      <div className="mx-3.5 mb-2 h-1 overflow-hidden rounded-full bg-muted" aria-hidden>
        <div className="h-full rounded-full" style={{ width: `${Math.round(ratio * 100)}%`, background: look(state.kind).color }} />
      </div>
      {day.orders_detail === null ? (
        <Fallback state={state} keeping={keeping} onKeep={onKeep} />
      ) : (
        <Orders orders={day.orders_detail} state={state} keeping={keeping} onKeep={onKeep} />
      )}
      <Reminders moments={day.reminders} />
    </div>
  )
}

/** Pory Przypomnień o raporcie za ten dzień do tego Wykonawcy, w czasie komputera taty: „10.11 08:00, 10.11 18:00”. */
function Reminders({ moments }: { moments: ReadonlyArray<string> }) {
  if (moments.length === 0) {
    return null
  }

  return (
    <p className="flex items-start gap-1.5 border-t px-3.5 py-2.5 text-xs text-muted-foreground tabular-nums">
      <BellIcon className="mt-px size-3 shrink-0" aria-hidden />
      <span>
        {plural(moments.length, { one: "Przypomnienie", few: "Przypomnienia", many: "Przypomnień" })}{" "}
        {moments.map((moment) => `${dayMonth(moment)} ${hourMinute(moment)}`).join(", ")}
      </span>
    </p>
  )
}

function Figure({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col text-xs text-muted-foreground" aria-label={`${label} ${value}`}>
      <dt>{label}</dt>
      <dd className="text-base font-semibold text-foreground tabular-nums">{value}</dd>
    </div>
  )
}

const LIST = "flex flex-col border-t py-1 [&>li+li]:border-t [&>li+li]:border-border/60"

const ROW = "grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-2.5 gap-y-1 px-3.5 py-2"

/**
 * Zlecenia dnia w kolejności z INTERMAX, a po nich problemy bez zlecenia tego dnia (np. numer spoza zleceń) i
 * informacje o zleceniach, których dzień już nie ma (np. „przekazane …”).
 */
function Orders({
  orders,
  state,
  keeping,
  onKeep,
}: { orders: ReadonlyArray<ReportsOrder>; state: Extract<DayState, { kind: Status }> } & Keeping) {
  const numbers = new Set(orders.map((order) => order.number))
  const loose = state.day.problems.filter((problem) => problem.number === null || !numbers.has(problem.number))
  const handed = state.day.notes.filter((note) => !numbers.has(note.number))

  return (
    <ul className={LIST} aria-label="Zlecenia dnia">
      {orders.map((order) => (
        <li key={order.number} className={ROW}>
          <OrderNumber number={order.number} />
          <OrderLine order={order} />
          <StatusBadge
            status={orderStatus(order, state.kind)}
            label={order.state === "entered" ? "Wpisane" : undefined}
          />
          {state.day.problems
            .filter((problem) => problem.number === order.number)
            .map((problem) => (
              <ProblemReason key={problemKey(problem)} problem={problem} keeping={keeping} onKeep={onKeep} />
            ))}
          {state.day.notes
            .filter((note) => note.number === order.number)
            .map((note) => (
              <NoteLine key={note.text} note={note} />
            ))}
        </li>
      ))}
      {handed.map((note) => (
        <li key={`${note.number} ${note.text}`} className={ROW}>
          <OrderNumber number={note.number} />
          <NoteLine note={note} />
        </li>
      ))}
      {loose.map((problem) => (
        <li key={problemKey(problem)} className={ROW}>
          <OrderNumber number={problem.number} />
          <span className="font-medium">Problem bez zlecenia tego dnia</span>
          <StatusBadge status="problem" />
          <ProblemReason problem={problem} keeping={keeping} onKeep={onKeep} />
        </li>
      ))}
    </ul>
  )
}

function orderStatus(order: ReportsOrder, day: Status): Status {
  switch (order.state) {
    case "entered":
      return "complete"
    case "problem":
      return "problem"
    case "without_report":
      return day === "waiting" ? "waiting" : "without_report"
    default: {
      const unhandled: never = order.state

      return unhandled
    }
  }
}

function OrderLine({ order }: { order: ReportsOrder }) {
  if (order.state === "without_report") {
    return <span className="text-muted-foreground">Brak Wpisu w raporcie</span>
  }

  return (
    <span className="min-w-0 break-words">
      {order.successful === null ? null : (
        <span className={cn("mr-1 font-semibold", order.successful === "tak" ? "text-success-tile-foreground" : "text-muted-foreground")}>
          {order.successful}
        </span>
      )}
      {order.activities}
    </span>
  )
}

/** Wynik kliknięcia sprzed listy zleceń: numery bez raportu i problemy, bez treści zleceń. */
function Fallback({ state, keeping, onKeep }: { state: Extract<DayState, { kind: Status }> } & Keeping) {
  const { day } = state

  return (
    <ul className={LIST} aria-label="Zlecenia dnia">
      {day.without_report.map((number) => (
        <li key={number} className={ROW}>
          <OrderNumber number={number} />
          <span className="text-muted-foreground">Brak Wpisu w raporcie</span>
          <StatusBadge status={state.kind === "waiting" ? "waiting" : "without_report"} />
        </li>
      ))}
      {day.problems.map((problem) => (
        <li key={problemKey(problem)} className={ROW}>
          <OrderNumber number={problem.number} />
          <span className="font-medium">Problem</span>
          <StatusBadge status="problem" />
          <ProblemReason problem={problem} keeping={keeping} onKeep={onKeep} />
        </li>
      ))}
    </ul>
  )
}

/** Informacja o zmianie, którą Centrum zrobiło w INTERMAX: spokojna, wyciszona, bez znaczka problemu. */
function NoteLine({ note }: { note: ReportsNote }) {
  return (
    <span className="col-start-2 col-end-4 flex items-center gap-1.5 text-xs text-muted-foreground">
      <ArrowLeftRightIcon className="size-3 shrink-0" aria-hidden />
      {note.text}
    </span>
  )
}

function OrderNumber({ number }: { number: string | null }) {
  return <span className="pt-0.5 text-xs text-muted-foreground tabular-nums">{number ?? "—"}</span>
}

function ProblemReason({ problem, keeping, onKeep }: { problem: ReportsProblem } & Keeping) {
  const keep = problem.keep

  return (
    <>
      <span className="col-start-2 col-end-4 text-xs leading-relaxed text-muted-foreground">{problem.reason}</span>
      {keep === null ? null : (
        <span className="col-start-2 col-end-4">
          <Button
            size="sm"
            variant="outline"
            title={`Wpis raportu: ${keep.reported}`}
            disabled={keeping !== null}
            onClick={() => onKeep(keep)}
          >
            Zostaw moją
          </Button>
        </span>
      )}
    </>
  )
}

function problemKey(problem: ReportsProblem): string {
  return JSON.stringify([problem.number, problem.reason, problem.keep])
}
