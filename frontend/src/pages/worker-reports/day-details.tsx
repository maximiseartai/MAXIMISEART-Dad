import { ArrowLeftRightIcon, BellIcon, CalendarIcon, CheckIcon, MailCheckIcon, MailWarningIcon, type LucideIcon } from "lucide-react"
import { cn } from "cn"

import type {
  KeptCell,
  ReportsFaultyOffer,
  ReportsFaultySubject,
  ReportsNote,
  ReportsOrder,
  ReportsProblem,
  ReportsWorkerDay,
  RequestedCell,
} from "@/api/generated"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { dayMonth, hourMinute, plural, shortDate } from "@/lib/format"
import { isActive, useRuns } from "@/lib/runs"
import type { DayState, Status } from "@/pages/worker-reports/day-state"
import { shortDay, weekdayOfDate } from "@/pages/worker-reports/days"
import { look, StatusBadge } from "@/pages/worker-reports/status"

export type Keep = KeptCell

type Keeping = { keeping: Keep | null; onKeep: (cell: Keep) => void }

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
 * (`orders_detail`) z problemami, „Zostaw moją”, Wpisem na życzenie, spokojnymi informacjami o Przeniesieniach zleceń
 * (`notes`), o raportach z pomylonym tematem (`mistaken_subjects`) i o raportach z błędem tematu, z których nie ma już czego
 * wpisać, bo każde ich zlecenie wziął późniejszy raport (`overtaken_subjects`). Raport z błędem tematu stoi jako problem z tematem
 * po strażniku reguły danych, rodzajem błędu, dniem, za który Centrum go liczy, i chwilą przyjścia maila, a jego zlecenia mają stan
 * „Błąd tematu”, nie „Bez raportu”, i Wpis na życzenie, gdy Centrum wie, co wpisać; Wpis na życzenie zlecenia, które
 * stoi w innym kafelku (Przeniesienie), problem pokazuje sam, z numerem zlecenia. Wynik kliknięcia sprzed listy zleceń (`orders_detail` `null`) pokazuje zamiast niej numery bez raportu i problemy. Nad listą
 * przebieg Przypomnień o raporcie za ten dzień (`reminders`), gdy jakieś poszło.
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
      <Reminders day={day} />
      {day.orders_detail === null ? (
        <Fallback state={state} keeping={keeping} onKeep={onKeep} />
      ) : (
        <Orders orders={day.orders_detail} worker={worker} state={state} keeping={keeping} onKeep={onKeep} />
      )}
    </div>
  )
}

function Reminders({ day }: { day: ReportsWorkerDay }) {
  if (day.reminders.length === 0) {
    return null
  }

  return (
    <ol aria-label="Przypomnienia o raporcie" className="flex flex-col border-t px-3.5 pt-3 tabular-nums">
      <Step
        icon={CalendarIcon}
        tone="bg-muted text-muted-foreground"
        label={`${day.orders} ${plural(day.orders, { one: "zlecenie", few: "zlecenia", many: "zleceń" })} w INTERMAX`}
        moment={shortDay(day.day)}
      />
      {day.reminders.map((sent, index) => (
        <Step
          key={sent}
          icon={BellIcon}
          tone="bg-reminder text-white"
          label={index === 0 ? "Przypomnienie wysłane" : "Kolejne przypomnienie"}
          moment={`${weekdayOfDate(new Date(sent))}. ${dayMonth(sent)}, ${hourMinute(sent)}`}
        />
      ))}
      {day.mails === 0 ? null : (
        <Step
          icon={CheckIcon}
          tone="bg-success-tile text-success-tile-foreground"
          label="Raport przyszedł"
          moment={`${day.mails} ${plural(day.mails, { one: "mail", few: "maile", many: "maili" })}`}
        />
      )}
    </ol>
  )
}

function Step({ icon: Icon, tone, label, moment }: { icon: LucideIcon; tone: string; label: string; moment: string }) {
  return (
    <li className="relative grid grid-cols-[1.375rem_minmax(0,1fr)_auto] items-center gap-2.5 pb-3 not-last:before:absolute not-last:before:top-5.5 not-last:before:bottom-0 not-last:before:left-[0.65rem] not-last:before:w-px not-last:before:bg-border">
      <span className={cn("grid size-5.5 place-items-center rounded-full", tone)} aria-hidden>
        <Icon className="size-3" />
      </span>
      <span className="font-medium">{label}</span>
      <span className="text-xs text-muted-foreground">{moment}</span>
    </li>
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

function Orders({
  orders,
  worker,
  state,
  keeping,
  onKeep,
}: { orders: ReadonlyArray<ReportsOrder>; worker: string; state: Extract<DayState, { kind: Status }> } & Keeping) {
  const numbers = new Set(orders.map((order) => order.number))
  const loose = state.day.problems.filter((problem) => problem.number === null || !numbers.has(problem.number))
  const handed = state.day.notes.filter((note) => !numbers.has(note.number))
  const atOrders = new Set(orders.flatMap((order) => (order.request === null ? [] : [requestKey(order.request)])))

  return (
    <ul className={LIST} aria-label="Zlecenia dnia">
      {orders.map((order) => (
        <li key={order.number} className={ROW}>
          <OrderNumber number={order.number} />
          <OrderLine order={order} />
          <StatusBadge status={orderStatus(order, state.kind)} label={ORDER_LABELS[order.state]} />
          <CodesLine order={order} />
          {order.request === null ? null : <OnRequest request={order.request} worker={worker} day={state.day.day} />}
          {state.day.problems
            .filter((problem) => problem.number === order.number)
            .map((problem) => (
              <ProblemReason key={problemKey(problem)} problem={problem} atOrders={atOrders} keeping={keeping} onKeep={onKeep} />
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
      {state.day.mistaken_subjects.map((subjectDay) => (
        <li key={subjectDay} className={ROW}>
          <OrderNumber number={null} />
          <MistakenLine subjectDay={subjectDay} />
        </li>
      ))}
      {state.day.overtaken_subjects.map((text) => (
        <li key={text} className={ROW}>
          <OrderNumber number={null} />
          <OvertakenLine text={text} />
        </li>
      ))}
      {loose.map((problem) => (
        <li key={problemKey(problem)} className={ROW}>
          <OrderNumber number={problem.number} />
          <span className="font-medium">
            {problem.faulty_subject === null ? "Problem bez zlecenia tego dnia" : "Raport z błędem tematu"}
          </span>
          <StatusBadge status="problem" />
          <ProblemReason problem={problem} atOrders={atOrders} keeping={keeping} onKeep={onKeep} />
        </li>
      ))}
    </ul>
  )
}

const ORDER_LABELS: Readonly<Record<ReportsOrder["state"], string | undefined>> = {
  entered: "Wpisane",
  faulty_subject: "Błąd tematu",
  problem: undefined,
  without_report: undefined,
}

function orderStatus(order: ReportsOrder, day: Status): Status {
  switch (order.state) {
    case "entered":
      return "complete"
    case "problem":
    case "faulty_subject":
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

  if (order.state === "faulty_subject") {
    return <span className="text-muted-foreground">Wpis w raporcie z błędem tematu, niewpisany</span>
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

function CodesLine({ order }: { order: ReportsOrder }) {
  if (order.no_code) {
    return (
      <span className="col-start-2 col-end-4 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        <Badge variant="outline" className="rounded-full">
          BRAK KODU
        </Badge>
        Legenda czynności nie znalazła w opisie żadnego kodu.
      </span>
    )
  }

  if (order.codes.length === 0) {
    return null
  }

  return (
    <span className="col-start-2 col-end-4 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
      {plural(order.codes.length, { one: "Kod", few: "Kody", many: "Kodów" })}:
      {order.codes.map((code, index) => (
        <code key={`${index} ${code}`} className="rounded bg-muted px-1 py-0.5 font-mono text-foreground">
          {code}
        </code>
      ))}
    </span>
  )
}

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

function NoteLine({ note }: { note: ReportsNote }) {
  return (
    <span className="col-start-2 col-end-4 flex items-center gap-1.5 text-xs text-muted-foreground">
      <ArrowLeftRightIcon className="size-3 shrink-0" aria-hidden />
      {note.text}
    </span>
  )
}

function MistakenLine({ subjectDay }: { subjectDay: string }) {
  return (
    <span className="col-start-2 col-end-4 flex items-center gap-1.5 text-xs text-muted-foreground">
      <ArrowLeftRightIcon className="size-3 shrink-0" aria-hidden />
      {`Pomylony temat: raport z dniem ${shortDate(subjectDay)} w temacie, Wpisy poszły do zleceń tego dnia`}
    </span>
  )
}

/** Informacja o raporcie z błędem tematu, którego każde zlecenie wziął późniejszy raport: zdanie z serwera, bez problemu. */
function OvertakenLine({ text }: { text: string }) {
  return (
    <span className="col-start-2 col-end-4 flex items-start gap-1.5 text-xs text-muted-foreground">
      <MailCheckIcon className="mt-0.5 size-3 shrink-0" aria-hidden />
      {text}
    </span>
  )
}

function FaultyFacts({ faulty }: { faulty: ReportsFaultySubject }) {
  return (
    <dl className="col-start-2 col-end-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-xs" aria-label="Błąd tematu">
      <dt className="flex items-center gap-1 text-muted-foreground">
        <MailWarningIcon className="size-3 shrink-0" aria-hidden />
        Temat
      </dt>
      <dd className="min-w-0 break-words font-medium">„{faulty.subject}”</dd>
      <dt className="text-muted-foreground">Błąd tematu</dt>
      <dd>{faulty.fault}</dd>
      <dt className="text-muted-foreground">Liczony za</dt>
      <dd className="tabular-nums">{faulty.day === null ? "żaden dzień" : shortDate(faulty.day)}</dd>
      <dt className="text-muted-foreground">Przyszedł</dt>
      <dd className="tabular-nums">{`${dayMonth(faulty.arrived)}, ${hourMinute(faulty.arrived)}`}</dd>
    </dl>
  )
}

function OrderNumber({ number }: { number: string | null }) {
  return <span className="pt-0.5 text-xs text-muted-foreground tabular-nums">{number ?? "—"}</span>
}

/**
 * Zdanie problemu z faktami raportu z błędem tematu, „Zostaw moją” i Wpisami na życzenie: przy problemie i przy
 * raporcie z błędem tematu każdy Wpis jego zlecenia, którego przycisk nie stoi już przy zleceniu tego kafelka
 * (`atOrders`, klucze `requestKey`), bo jedna decyzja ma w kafelku jeden przycisk.
 */
function ProblemReason({
  problem,
  atOrders = new Set(),
  keeping,
  onKeep,
}: { problem: ReportsProblem; atOrders?: ReadonlySet<string> } & Keeping) {
  const keep = problem.keep
  const offers = (problem.faulty_subject?.offers ?? []).filter((offer) => !atOrders.has(requestKey(offer.request)))

  return (
    <>
      {problem.faulty_subject === null ? null : <FaultyFacts faulty={problem.faulty_subject} />}
      <span className="col-start-2 col-end-4 text-xs leading-relaxed text-muted-foreground">{problem.reason}</span>
      {problem.request === null ? null : <OnRequest request={problem.request} />}
      {offers.map((offer) => (
        <FaultyOffer key={requestKey(offer.request)} offer={offer} />
      ))}
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

function FaultyOffer({ offer }: { offer: ReportsFaultyOffer }) {
  return <OnRequest request={offer.request} worker={offer.worker} day={offer.day} number={offer.request.number} />
}

function requestKey(request: RequestedCell): string {
  return JSON.stringify([request.mail, request.number, request.worker, request.day, request.order_day])
}

function whereTo(request: RequestedCell, worker: string, day: string): string {
  if (request.worker !== worker) {
    return `Wpisze się do INTERMAX, zlecenie przejdzie od ${worker} do ${request.worker} na ${shortDay(request.order_day)}:`
  }

  if (request.order_day !== day) {
    return `Wpisze się do INTERMAX, zlecenie przejdzie z ${shortDay(day)} na ${shortDay(request.order_day)}:`
  }

  return `Wpisze się do INTERMAX, zlecenie z ${shortDay(request.order_day)}:`
}

/**
 * Wpis na życzenie (ADR 0041) przy problemie albo przy zleceniu z Wpisem raportu z błędem tematu: co wpisze się do
 * INTERMAX, zanim tata kliknie, i przycisk, który startuje Wpisanie raportów z jego decyzją. Zlecenie dziś ma Wykonawca
 * `worker` w dniu `day`; gdy Wpis je przeniesie (do nadawcy raportu albo na dzień z tematu), mówi skąd i dokąd.
 * `number`: numer zlecenia nad podglądem, gdy przycisk nie stoi przy zleceniu. W czasie każdego Uruchomienia przycisk
 * czeka; odmowę serwera (INTERMAX otwarty w Excelu) pokazuje powiadomienie.
 */
function OnRequest({
  request,
  worker = request.worker,
  day = request.order_day,
  number,
}: {
  request: RequestedCell
  worker?: string
  day?: string
  number?: string
}) {
  const { view, starting, start } = useRuns()

  return (
    <span className="col-start-2 col-end-4 flex flex-col gap-2 rounded-md border border-dashed px-2.5 py-2 text-xs">
      {number === undefined ? null : <span className="font-semibold tabular-nums">{`Zlecenie ${number}`}</span>}
      <span className="text-muted-foreground">{whereTo(request, worker, day)}</span>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2.5 gap-y-0.5" aria-label="Co się wpisze">
        <dt className="text-muted-foreground">SKUTECZNE</dt>
        <dd className="font-semibold">{request.successful}</dd>
        <dt className="text-muted-foreground">CZYNNOŚCI ZREALIZOWANE</dt>
        <dd className="min-w-0 break-words">{request.activities === "" ? "—" : request.activities}</dd>
      </dl>
      <span>
        <Button
          size="sm"
          variant="outline"
          disabled={starting || isActive(view)}
          onClick={() => void start({ process: "report_entering", request })}
        >
          Wpisz do INTERMAX
        </Button>
      </span>
    </span>
  )
}

function problemKey(problem: ReportsProblem): string {
  return JSON.stringify([problem.number, problem.reason, problem.keep, problem.request])
}
