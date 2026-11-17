import * as React from "react"
import { CheckIcon, MinusIcon, RotateCwIcon, SendIcon, UserXIcon } from "lucide-react"

import type { MailingPeriod, MailingRow } from "@/api/generated"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { settingsHref } from "@/lib/address"
import { useChangeEntrance } from "@/lib/content-entrance"
import { dateTime, plural } from "@/lib/format"
import { WORKERS_SECTION } from "@/pages/settings/workers-section"
import { ConfirmMailing } from "@/pages/settlement-mailing/confirm-mailing"
import { MailingBar, RollingNumber, StatusRing, type Ring } from "@/pages/settlement-mailing/marks"
import { stateWords, WorkerAvatar } from "@/pages/settlement-mailing/mail-state"
import { counted, delivered, tally, type ShownState } from "@/pages/settlement-mailing/periods"
import type { PeriodMailing } from "@/pages/settlement-mailing/use-period-mailing"
import { settlements } from "@/pages/settlement-mailing/words"
import { cn } from "cn"

/** Co mówi przycisk karty: wysyłka trwa, wszystko poszło, część nie wyszła, albo czeka na wybór taty. */
type Action =
  | { kind: "sending"; at: number; of: number }
  | { kind: "complete" }
  | { kind: "retry"; workers: string[] }
  | { kind: "send"; workers: string[] }

/**
 * Karta okresu z plikami do wysłania (Progress Tracker): pasek „X z Y wysłane”, Wykonawcy z pierścieniem stanu i
 * przycisk wysyłki. Zaznaczone na start są pliki do wysłania i te, których wysyłka nie wyszła; zmienione po wysłaniu
 * tata zaznacza sam. „Wyślij N rozliczeń” otwiera okno z podglądem maili, a po potwierdzeniu maile idą po kolei, każdy
 * wiersz odhacza się, gdy jego mail wychodzi, a pasek rośnie. Pliki bez maila (bez adresu, bez zleceń, spoza Listy)
 * stoją pod Wykonawcami jednym zdaniem.
 */
export function PeriodTracker({
  period,
  mailing,
  complete,
  leaving,
}: {
  period: MailingPeriod
  mailing: PeriodMailing
  complete: boolean
  leaving: boolean
}) {
  const { visit, busy, state, send } = mailing

  const [ticked, setTicked] = React.useState<ReadonlySet<string>>(
    () => new Set(period.rows.filter((row) => row.preselected).map((row) => row.worker))
  )

  const [confirming, setConfirming] = React.useState<string[] | null>(null)

  const titleId = React.useId()

  const tracked = period.rows.filter((row) => counted(state(row)))
  const aside = period.rows.filter((row) => !counted(state(row)))
  const shown = tally(tracked.map(state))
  const choosable = tracked.filter((row) => row.sendable)
  const chosen = choosable.filter((row) => ticked.has(row.worker)).map((row) => row.worker)
  const failed = tracked.filter((row) => visit.failed.has(row.worker) && state(row).state === "not_sent").map((row) => row.worker)

  const action: Action =
    visit.round !== null
      ? { kind: "sending", at: visit.round.at + 1, of: visit.round.of }
      : complete
        ? { kind: "complete" }
        : failed.length > 0
          ? { kind: "retry", workers: failed }
          : { kind: "send", workers: chosen }

  const tick = (worker: string, on: boolean) =>
    setTicked((current) => new Set(on ? [...current, worker] : [...current].filter((found) => found !== worker)))

  return (
    <Card
      role="region"
      aria-labelledby={titleId}
      className={cn("gap-0 p-0 transition-opacity duration-150 ease-out", leaving && "opacity-0")}
    >
      <div className="flex items-end justify-between gap-4 px-5 pt-5">
        <div className="flex min-w-0 flex-col gap-0.5">
          <Kicker period={period} complete={complete} failed={visit.round === null ? failed.length : 0} />
          <h2 id={titleId} className="text-lg font-semibold tracking-tight">
            {period.label}
          </h2>
        </div>
        <p className="shrink-0 text-muted-foreground tabular-nums">
          <b className="font-semibold text-foreground">
            <RollingNumber value={shown.sent} />
          </b>{" "}
          z {shown.of} wysłane
        </p>
      </div>
      <div className="px-5 pt-4 pb-3">
        <MailingBar tally={shown} live={visit.round !== null} glow={visit.glows} label={`Wysłane: ${period.label}`} />
      </div>
      <ul aria-label={`Wykonawcy: ${period.label}`} className="flex flex-col gap-0.5 px-3">
        {tracked.map((row) => (
          <WorkerLine
            key={row.worker}
            row={row}
            state={state(row)}
            ticked={ticked.has(row.worker)}
            fresh={visit.sent.has(row.worker)}
            locked={!row.sendable || busy}
            onTick={(on) => tick(row.worker, on)}
            onRetry={() => void send([row.worker])}
          />
        ))}
      </ul>
      {aside.length === 0 ? null : (
        <div className="mx-5 mt-2 flex flex-col gap-1.5 border-t border-dashed pt-3 text-sm text-muted-foreground">
          {aside.map((row) => (
            <AsideLine key={row.worker} row={row} />
          ))}
        </div>
      )}
      <div className="mt-4 flex items-center gap-3 border-t bg-muted/40 px-5 py-3">
        <label className="flex items-center gap-2.5 text-sm">
          <Checkbox
            checked={choosable.length > 0 && chosen.length === choosable.length}
            indeterminate={chosen.length > 0 && chosen.length < choosable.length}
            disabled={choosable.length === 0 || busy}
            onCheckedChange={(on) => setTicked(new Set(on ? choosable.map((row) => row.worker) : []))}
          />
          Wszyscy
        </label>
        <ActionButton
          action={action}
          onSend={(workers) => setConfirming(workers)}
          onRetry={(workers) => void send(workers)}
        />
      </div>
      {confirming === null ? null : (
        <ConfirmMailing
          token={period.token}
          label={period.label}
          workers={confirming}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            setConfirming(null)
            void send(confirming)
          }}
        />
      )}
    </Card>
  )
}

function Kicker({ period, complete, failed }: { period: MailingPeriod; complete: boolean; failed: number }) {
  if (complete) {
    return <p className="text-sm text-success-tile-foreground">Wszystkie rozliczenia wysłane</p>
  }

  if (failed > 0) {
    return (
      <p className="text-sm text-destructive">
        {failed} {plural(failed, { one: "mail nie wyszedł", few: "maile nie wyszły", many: "maili nie wyszło" })}: powód
        stoi przy Wykonawcy
      </p>
    )
  }

  return (
    <p className="text-sm text-muted-foreground tabular-nums">
      {period.settled_at === null ? "Rozliczenia pracowników" : `Rozliczenia pracowników gotowe ${dateTime(period.settled_at)}`}
    </p>
  )
}

/** Słowa i pierścień wiersza Wykonawcy. */
type Look = { words: string; ring: Ring }

/** Słowa i pierścień wiersza: stan pliku, a dla pliku, który może iść, także to, czy tata go zaznaczył. */
function look(state: ShownState, ticked: boolean): Look {
  switch (state.state) {
    case "sending":
      return { words: "Wysyłam…", ring: "sending" }
    case "not_sent":
      return { words: "Nie wyszło", ring: "failed" }
    case "to_send":
      return ticked ? { words: "Do wysłania", ring: "waiting" } : { words: "Pominięte", ring: "skipped" }
    case "changed":
      return ticked ? { words: "Wyślę poprawione", ring: "waiting" } : { words: "Zmienione po wysłaniu", ring: "skipped" }
    default:
      return { words: stateWords(state), ring: delivered(state) ? "sent" : "skipped" }
  }
}

function WorkerLine({
  row,
  state,
  ticked,
  fresh,
  locked,
  onTick,
  onRetry,
}: {
  row: MailingRow
  state: ShownState
  ticked: boolean
  fresh: boolean
  locked: boolean
  onTick: (on: boolean) => void
  onRetry: () => void
}) {
  const { words, ring } = look(state, ticked && row.sendable)
  const entrance = useChangeEntrance(words, "podmiana")

  return (
    <li
      data-ring={ring}
      className={cn(
        "grid grid-cols-[1rem_auto_minmax(0,1fr)_auto] items-center gap-3 rounded-lg px-2 py-2 transition-colors duration-150",
        !locked && "pointer-fine:hover:bg-muted/70"
      )}
    >
      <Checkbox aria-label={`Wyślij ${row.worker}`} checked={ticked && row.sendable} disabled={locked} onCheckedChange={onTick} />
      <span className={cn("transition-opacity duration-150", ring === "skipped" && "opacity-45")}>
        <WorkerAvatar worker={row.worker} size="default" />
      </span>
      <span className={cn("flex min-w-0 flex-col transition-opacity duration-150", ring === "skipped" && "opacity-45")}>
        <span className="font-medium">{row.worker}</span>
        <span
          title={state.state === "not_sent" ? state.message : undefined}
          className={cn("truncate text-xs", state.state === "not_sent" ? "text-destructive" : "text-muted-foreground")}
        >
          {state.state === "not_sent" ? state.message : row.addresses.join(", ")}
        </span>
      </span>
      <span
        className={cn(
          "flex items-center gap-2.5 text-sm whitespace-nowrap tabular-nums",
          ring === "sent" ? "text-success-tile-foreground" : ring === "failed" ? "text-destructive" : "text-muted-foreground",
          state.state === "changed" && !ticked && "text-warning-tile-foreground"
        )}
      >
        <span key={words} className={entrance}>
          {words}
          {state.state === "not_sent" ? (
            <>
              {" · "}
              <button type="button" className="underline underline-offset-4 hover:text-foreground" onClick={onRetry} disabled={locked}>
                Ponów
              </button>
            </>
          ) : null}
        </span>
        <StatusRing ring={ring} fresh={fresh} />
      </span>
    </li>
  )
}

function AsideLine({ row }: { row: MailingRow }) {
  switch (row.state.state) {
    case "no_address":
      return (
        <p className="flex items-center gap-2">
          <UserXIcon className="size-4 shrink-0" aria-hidden />
          <span>
            {row.worker} nie ma adresu w Liście Wykonawców.{" "}
            <a href={settingsHref(WORKERS_SECTION)} className="text-foreground underline underline-offset-4">
              Dodaj adres
            </a>
          </span>
        </p>
      )
    case "not_listed":
      return (
        <p className="flex items-center gap-2">
          <UserXIcon className="size-4 shrink-0" aria-hidden />
          <span>
            {row.worker} nie ma w Liście Wykonawców.{" "}
            <a href={settingsHref(WORKERS_SECTION)} className="text-foreground underline underline-offset-4">
              Dodaj Wykonawcę
            </a>
          </span>
        </p>
      )
    default:
      return (
        <p className="flex items-center gap-2">
          <MinusIcon className="size-4 shrink-0" aria-hidden />
          {row.worker}: bez zleceń w tym okresie, plik nie idzie.
        </p>
      )
  }
}

/** Przycisk stałej szerokości, więc „Wysyłam 2 z 5” i „Ponów 1” nie przesuwają stopki; napis wchodzi przy zmianie trybu. */
function ActionButton({
  action,
  onSend,
  onRetry,
}: {
  action: Action
  onSend: (workers: string[]) => void
  onRetry: (workers: string[]) => void
}) {
  const entrance = useChangeEntrance(action.kind, "podmiana")
  const sending = `Wysyłam ${action.kind === "sending" ? `${action.at} z ${action.of}` : ""}`

  return (
    <Button
      size="lg"
      className="ml-auto min-w-52 px-4"
      data-wysylam={action.kind === "sending" ? "" : undefined}
      disabled={action.kind === "sending" || action.kind === "complete" || (action.kind === "send" && action.workers.length === 0)}
      onClick={() => {
        if (action.kind === "send") {
          onSend(action.workers)
        } else if (action.kind === "retry") {
          onRetry(action.workers)
        }
      }}
    >
      <span key={action.kind} className={cn("inline-flex items-center gap-2 tabular-nums", entrance)}>
        {action.kind === "complete" ? <CheckIcon aria-hidden /> : action.kind === "retry" ? <RotateCwIcon aria-hidden /> : <SendIcon aria-hidden />}
        {action.kind === "sending" ? (
          <span className="migotanie" data-text={sending}>
            {sending}
          </span>
        ) : null}
        {action.kind === "complete" ? "Wysłane" : null}
        {action.kind === "retry" ? `Ponów ${action.workers.length}` : null}
        {action.kind === "send" ? (action.workers.length === 0 ? "Zaznacz, do kogo" : `Wyślij ${settlements(action.workers.length)}`) : null}
      </span>
    </Button>
  )
}
