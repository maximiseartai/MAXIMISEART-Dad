import * as React from "react"
import { CheckIcon, EyeIcon, RefreshCwIcon } from "lucide-react"

import type { MailingPeriod, MailingRow } from "@/api/generated"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { dateTime } from "@/lib/format"
import { ConfirmMailing } from "@/pages/settlement-mailing/confirm-mailing"
import { MailingBar } from "@/pages/settlement-mailing/marks"
import { MailStateBadge, WorkerAvatar } from "@/pages/settlement-mailing/mail-state"
import { delivered, lastSent, tally, type ShownState } from "@/pages/settlement-mailing/periods"
import type { PeriodMailing } from "@/pages/settlement-mailing/use-period-mailing"
import { settlements } from "@/pages/settlement-mailing/words"

/**
 * Okres jednym wierszem osi: „X z Y · kiedy ostatni”, mały pasek, awatary Wykonawców z kropką stanu i rozwijane „kto i
 * kiedy” z odznaką każdego. Pod spodem pytanie o każde poprawione rozliczenie (`cards`), które po wysłaniu krótko
 * potwierdza i się zwija. Bez czytelnych „Wysłanych” wiersz mówi tylko, ile jest Rozliczeń pracowników.
 */
export function PeriodSummary({
  period,
  readable,
  mailing,
  cards,
  onFold,
  className,
}: {
  period: MailingPeriod
  readable: boolean
  mailing: PeriodMailing
  cards: ReadonlyArray<{ row: MailingRow; open: boolean }>
  onFold: (worker: string) => void
  className: string | undefined
}) {
  const { visit, state } = mailing
  const states = period.rows.map(state)
  const shown = tally(states)
  const last = lastSent(states)
  const titleId = React.useId()

  return (
    <section aria-labelledby={titleId} className={className}>
      <div className="flex min-h-8 flex-wrap items-center gap-x-2.5 gap-y-1">
        <h2 id={titleId} className="text-base font-semibold">
          {period.label}
        </h2>
        <span className="text-sm text-muted-foreground tabular-nums">
          {readable ? `${shown.sent} z ${shown.of}${last === null ? "" : ` · ${dateTime(last)}`}` : settlements(period.rows.length)}
        </span>
      </div>
      <Collapsible>
        <div className="mt-1.5 flex flex-wrap items-center gap-3">
          {readable ? <MailingBar tally={shown} live={visit.round !== null} glow={visit.glows} label={`Wysłane: ${period.label}`} mini /> : null}
          <ul aria-label={`Wykonawcy: ${period.label}`} className="flex gap-1">
            {period.rows
              .filter((row) => row.state.state !== "without_orders")
              .map((row) => (
                <li key={row.worker}>
                  <WorkerAvatar worker={row.worker} state={state(row)} />
                </li>
              ))}
          </ul>
          <CollapsibleTrigger className="text-sm text-muted-foreground underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
            kto i kiedy
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent>
          <ul className="flex flex-col gap-2 pt-3">
            {period.rows.map((row) => (
              <li key={row.worker} className="flex items-center gap-3 text-sm">
                <WorkerAvatar worker={row.worker} />
                <span className="w-44 truncate">{row.worker}</span>
                <MailStateBadge state={state(row)} />
              </li>
            ))}
          </ul>
        </CollapsibleContent>
      </Collapsible>
      {cards.map(({ row, open }) => (
        <FixCard key={row.worker} period={period} row={row} state={state(row)} open={open} mailing={mailing} onFold={() => onFold(row.worker)} />
      ))}
    </section>
  )
}

/**
 * Pytanie o poprawione rozliczenie (Decision Inbox): „Wyślij poprawione” i „Podgląd maila” otwierają to samo okno z
 * podglądem. Po wysłaniu linia krótko potwierdza, a potem karta się zwija.
 */
function FixCard({
  period,
  row,
  state,
  open,
  mailing,
  onFold,
}: {
  period: MailingPeriod
  row: MailingRow
  state: ShownState
  open: boolean
  mailing: PeriodMailing
  onFold: () => void
}) {
  const [asked] = React.useState(row.state)
  const [confirming, setConfirming] = React.useState<string[] | null>(null)
  const done = delivered(state)
  const fold = React.useRef(onFold)

  React.useEffect(() => {
    fold.current = onFold
  })

  React.useEffect(() => {
    if (!done) {
      return undefined
    }

    const timer = window.setTimeout(() => fold.current(), 1100)

    return () => window.clearTimeout(timer)
  }, [done])

  return (
    <Collapsible open={open}>
      <CollapsibleContent className="-m-1 p-1">
        <Card size="sm" role="region" aria-label={`Poprawione rozliczenie: ${row.worker}`} className="mt-2 gap-1 px-4">
          <p className="font-medium">{row.worker} ma poprawione rozliczenie</p>
          <p className="text-sm text-muted-foreground tabular-nums">
            {asked.state === "changed"
              ? `Mail poszedł ${dateTime(asked.at)}, a plik zmienił się potem.`
              : asked.state === "not_sent"
                ? `Poprawione rozliczenie nie wyszło: ${asked.message}`
                : "Plik zmienił się po wysłaniu."}
          </p>
          <div className="mt-2 flex min-h-7 items-center gap-2 text-sm">
            {state.state === "sending" ? (
              <span className="migotanie font-medium [--migotanie:var(--foreground)]" data-text="Wysyłam…">
                Wysyłam…
              </span>
            ) : null}
            {state.state === "sent" || state.state === "sent_by_hand" ? (
              <span className="podmiana inline-flex items-center gap-1.5 font-medium text-success-tile-foreground tabular-nums">
                <CheckIcon className="size-4" aria-hidden />
                Wysłane ponownie {dateTime(state.at)}
              </span>
            ) : null}
            {state.state === "sending" || done ? null : (
              <>
                {state.state === "not_sent" ? <span className="text-destructive">{state.message}</span> : null}
                <Button size="sm" disabled={mailing.busy} onClick={() => setConfirming([row.worker])}>
                  <RefreshCwIcon data-icon="inline-start" />
                  Wyślij poprawione
                </Button>
                <Button size="sm" variant="outline" disabled={mailing.busy} onClick={() => setConfirming([row.worker])}>
                  <EyeIcon data-icon="inline-start" />
                  Podgląd maila
                </Button>
              </>
            )}
          </div>
        </Card>
      </CollapsibleContent>
      {confirming === null ? null : (
        <ConfirmMailing
          token={period.token}
          label={period.label}
          workers={confirming}
          again
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            setConfirming(null)
            void mailing.send(confirming)
          }}
        />
      )}
    </Collapsible>
  )
}
