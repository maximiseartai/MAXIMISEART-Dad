import * as React from "react"
import { CheckIcon, FileSpreadsheetIcon, MailWarningIcon, PenLineIcon, SendIcon } from "lucide-react"

import { getSettlementMailing, type SettlementMailing } from "@/api/centrum"
import type { MailingPeriod } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { PageHeader } from "@/components/page-header"
import { FOLDERS_SECTION } from "@/components/setting-path"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { settingsHref } from "@/lib/address"
import { useChangeEntrance, useContentEntrance } from "@/lib/content-entrance"
import { useReloadOnChange } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { SETTLEMENT_MAIL_SECTION } from "@/pages/settings/settlement-mail-section"
import { PeriodDot } from "@/pages/settlement-mailing/marks"
import { PeriodSummary } from "@/pages/settlement-mailing/period-summary"
import { PeriodTracker } from "@/pages/settlement-mailing/period-tracker"
import { periodKind, tally, waiting } from "@/pages/settlement-mailing/periods"
import { usePeriodMailing } from "@/pages/settlement-mailing/use-period-mailing"
import { cn } from "cn"

type Ready = Extract<SettlementMailing, { state: "ready" }>

/** Które okresy stoją na osi: tylko te, które czekają na tatę (i te, które wysłał w tej wizycie), albo wszystkie. */
type Shown = "waiting" | "all"

const SHOWN: ReadonlyArray<{ value: Shown; label: string }> = [
  { value: "waiting", label: "Do wysłania" },
  { value: "all", label: "Wszystkie okresy" },
]

/**
 * Wysyłka rozliczeń (ADR 0040): oś okresów od najnowszego. Okres z plikami do wysłania to karta z paskiem „X z Y
 * wysłane” i Wykonawcami, okres z samymi poprawionymi rozliczeniami pyta o każde, a reszta to jeden wiersz z małym
 * paskiem. Stan każdego pliku liczy serwer z folderu okresów, Listy Wykonawców i „Wysłanych” skrzynki raportów;
 * przeglądarka tylko go pokazuje i wysyła wybór taty.
 */
export function MailingPage() {
  const { resource, reload } = useResource(getSettlementMailing, [])
  const [shown, setShown] = React.useState<Shown>("waiting")

  useReloadOnChange(reload)

  const entrance = useContentEntrance(resource.state === "loading")
  const periods = resource.state === "ready" && resource.data.state === "ready" ? resource.data.periods.length : 0

  return (
    <>
      <PageHeader
        action={
          periods === 0 ? undefined : (
            <>
              <Button variant="ghost" size="sm" nativeButton={false} render={<a href={settingsHref(SETTLEMENT_MAIL_SECTION)} />}>
                <PenLineIcon data-icon="inline-start" />
                Temat i treść
              </Button>
              <ShownSwitch value={shown} onChange={setShown} />
            </>
          )
        }
      />
      {resource.state === "loading" ? <Skeleton className="h-80 w-full max-w-184" aria-label="Wczytywanie Wysyłki rozliczeń" /> : null}
      {resource.state === "failed" ? (
        <LoadFailure what="Wysyłki rozliczeń" message={resource.message} reload={reload} />
      ) : null}
      {resource.state === "ready" && resource.data.state === "not_set" ? (
        <NotSet message={resource.data.message} className={entrance} />
      ) : null}
      {resource.state === "ready" && resource.data.state === "ready" ? (
        <Mailing view={resource.data} shown={shown} reload={reload} className={entrance} />
      ) : null}
    </>
  )
}

/** Przełącznik dwóch widoków osi: pigułka jedzie pod wybraną opcję. */
function ShownSwitch({ value, onChange }: { value: Shown; onChange: (value: Shown) => void }) {
  const chosen = SHOWN.findIndex((option) => option.value === value)

  return (
    <div role="group" aria-label="Okresy na osi" className="relative grid grid-cols-2 rounded-lg bg-muted p-0.75 text-sm">
      <span
        aria-hidden
        className="absolute inset-y-0.75 left-0.75 w-[calc(50%-0.1875rem)] rounded-md bg-background shadow-sm ring-1 ring-foreground/5 transition-transform duration-240 ease-out motion-reduce:transition-none"
        style={{ transform: `translateX(${chosen * 100}%)` }}
      />
      {SHOWN.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className="relative rounded-md px-3.5 py-1 whitespace-nowrap text-muted-foreground outline-none transition-colors duration-150 focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:font-medium aria-pressed:text-foreground"
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function NotSet({ message, className }: { message: string; className: string | undefined }) {
  return (
    <Empty className={className}>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SendIcon />
        </EmptyMedia>
        <EmptyTitle>Nie widać Rozliczeń pracowników</EmptyTitle>
        <EmptyDescription>
          {message}{" "}
          <a href={settingsHref(FOLDERS_SECTION)} className="underline underline-offset-4">
            Otwórz Ustawienia
          </a>
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

function Mailing({
  view,
  shown,
  reload,
  className,
}: {
  view: Ready
  shown: Shown
  reload: () => Promise<void>
  className: string | undefined
}) {
  const [touched, setTouched] = React.useState<ReadonlySet<string>>(new Set())
  const readable = view.mailbox.state === "ready"

  if (view.periods.length === 0) {
    return (
      <Empty className={className}>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileSpreadsheetIcon />
          </EmptyMedia>
          <EmptyTitle>Nie ma jeszcze Rozliczeń pracowników</EmptyTitle>
          <EmptyDescription>Utwórz je w Okresach, a potem wyślij je tutaj.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const visible = view.periods.map((period) => shown === "all" || touched.has(period.token) || waiting(period, readable))
  const last = visible.lastIndexOf(true)

  return (
    <div className={cn("flex w-full max-w-184 flex-col gap-4", className)}>
      {view.mailbox.state === "unreadable" ? (
        <Alert role="status">
          <MailWarningIcon />
          <AlertDescription>{view.mailbox.message}</AlertDescription>
        </Alert>
      ) : null}
      {last === -1 ? <NothingWaits /> : null}
      <ol aria-label="Okresy">
        {view.periods.map((period, index) => (
          <li key={period.token}>
            <Collapsible open={visible[index]}>
              <CollapsibleContent className="-m-1 p-1">
                <PeriodNode
                  period={period}
                  readable={readable}
                  reload={reload}
                  last={index === last}
                  onSending={() => setTouched((current) => new Set([...current, period.token]))}
                />
              </CollapsibleContent>
            </Collapsible>
          </li>
        ))}
      </ol>
    </div>
  )
}

function NothingWaits() {
  return (
    <div className="wejscie flex items-center gap-4 rounded-xl px-1 py-2">
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-success-tile text-success-tile-foreground">
        <CheckIcon className="size-5" aria-hidden />
      </span>
      <div className="flex flex-col">
        <p className="font-medium">Wszystkie rozliczenia wysłane</p>
        <p className="text-sm text-muted-foreground">Wysłane okresy są pod „Wszystkie okresy”.</p>
      </div>
    </div>
  )
}

/**
 * Co pokazuje węzeł osi: `tracker` kartę z Wykonawcami; `closing` tę kartę z wysłanym wszystkim przez chwilę, żeby
 * ostatni znacznik i poświata wybrzmiały; `leaving` jej gaśnięcie; `summary` jeden wiersz okresu.
 */
type Body = "tracker" | "closing" | "leaving" | "summary"

/** Karta po wysłaniu wszystkiego stoi tyle, zanim zamieni się w wiersz, a gaśnie tyle. */
const CLOSING_MS = 1500
const LEAVING_MS = 150

/**
 * Węzeł osi okresów: kropka na linii i treść obok. Okres z plikami do wysłania pokazuje kartę; gdy wszystko poszło,
 * kropka zielenieje, a karta po chwili płynnie zmienia wysokość w wiersz okresu w tym samym miejscu. Pytania o
 * poprawione rozliczenia (`cards`) zbierają się tylko w wierszu: poprawione w karcie idzie razem z resztą.
 */
function PeriodNode({
  period,
  readable,
  reload,
  last,
  onSending,
}: {
  period: MailingPeriod
  readable: boolean
  reload: () => Promise<void>
  last: boolean
  onSending: () => void
}) {
  const kind = periodKind(period, readable)
  const periodMailing = usePeriodMailing(period, reload)
  const { visit, busy, state } = periodMailing
  const [body, setBody] = React.useState<Body>(kind === "send" ? "tracker" : "summary")
  const [cards, setCards] = React.useState<ReadonlyArray<string>>([])
  const [folded, setFolded] = React.useState<ReadonlySet<string>>(new Set())
  const box = React.useRef<HTMLDivElement>(null)
  const from = React.useRef<number | null>(null)
  const entrance = useChangeEntrance(body, "pojawienie")

  const shown = tally(period.rows.map(state))
  const complete = visit.sent.size > 0 && shown.sent === shown.of

  if (body !== "tracker" && kind === "send") {
    setBody("tracker")
    setCards([])
  } else if (body === "tracker" && kind !== "send" && !busy) {
    setBody(visit.sent.size > 0 ? "closing" : "leaving")
  }

  const resending = period.rows.filter((row) => row.resend && !cards.includes(row.worker)).map((row) => row.worker)

  if (body === "summary" && resending.length > 0) {
    setCards([...cards, ...resending])
  }

  React.useEffect(() => {
    if (body !== "closing" && body !== "leaving") {
      return undefined
    }

    const timer = window.setTimeout(() => setBody(body === "closing" ? "leaving" : "summary"), body === "closing" ? CLOSING_MS : LEAVING_MS)

    return () => window.clearTimeout(timer)
  }, [body])

  // Karta zamienia się w wiersz: wysokość z chwili gaśnięcia karty płynie do wysokości wiersza, zanim przeglądarka
  // narysuje pierwszą klatkę wiersza, więc nic pod osią nie skacze.
  React.useLayoutEffect(() => {
    const element = box.current

    if (element === null) {
      return
    }

    if (body === "leaving") {
      from.current = element.offsetHeight

      return
    }

    const start = from.current

    from.current = null

    if (start === null || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return
    }

    element.animate(
      [
        { height: `${start}px`, overflow: "hidden" },
        { height: `${element.offsetHeight}px`, overflow: "hidden" },
      ],
      { duration: 280, easing: "cubic-bezier(0.23, 1, 0.32, 1)" }
    )
  }, [body])

  const mailing = {
    ...periodMailing,
    send: (workers: ReadonlyArray<string>) => {
      onSending()

      return periodMailing.send(workers)
    },
  }

  const open = cards.flatMap((worker) => {
    const row = period.rows.find((found) => found.worker === worker)

    return row === undefined ? [] : [{ row, open: !folded.has(worker) }]
  })

  const tone =
    body === "summary"
      ? open.some((card) => card.open)
        ? "fix"
        : shown.sent === shown.of
          ? "done"
          : "open"
      : complete
        ? "done"
        : "now"

  return (
    <div className="relative grid grid-cols-[2rem_minmax(0,1fr)] gap-x-3.5 pb-6">
      <span
        aria-hidden
        className={cn(
          "absolute top-9 bottom-1 left-[calc(1rem-1px)] w-0.5 rounded-full bg-border transition-opacity duration-200",
          last && "opacity-0"
        )}
      />
      <PeriodDot tone={tone} remaining={shown.of - shown.sent} fresh={visit.sent.size > 0} />
      <div ref={box}>
        {body === "summary" ? (
          <PeriodSummary
            period={period}
            readable={readable}
            mailing={mailing}
            cards={open}
            onFold={(worker) => setFolded((current) => new Set([...current, worker]))}
            className={entrance}
          />
        ) : (
          <PeriodTracker period={period} mailing={mailing} complete={complete} leaving={body === "leaving"} />
        )}
      </div>
    </div>
  )
}
