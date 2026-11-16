import * as React from "react"
import { CircleCheckIcon, FileSpreadsheetIcon, MailWarningIcon, SendIcon } from "lucide-react"

import { getSettlementMailing, sendSettlementMail, type SettlementMailing } from "@/api/centrum"
import type { MailingPeriod, MailingRow } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { PageHeader } from "@/components/page-header"
import { FOLDERS_SECTION } from "@/components/setting-path"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { toast } from "@/components/ui/toast"
import { showFailure, useAction } from "@/lib/action"
import { settingsHref } from "@/lib/address"
import { useContentEntrance } from "@/lib/content-entrance"
import { dateTime, plural } from "@/lib/format"
import { useReloadOnChange } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { cn } from "cn"
import { ConfirmMailing } from "@/pages/settlement-mailing/confirm-mailing"
import { MailStateBadge, MailStateNote, type ShownState } from "@/pages/settlement-mailing/mail-state"
import { initials, settlements } from "@/pages/settlement-mailing/words"

type Ready = Extract<SettlementMailing, { state: "ready" }>

/**
 * Wysyłka rozliczeń (ADR 0040): okresy z Rozliczeniami pracowników po lewej, Wykonawcy wybranego okresu po prawej.
 * Stan każdego pliku liczy serwer z folderu okresów, Listy Wykonawców i „Wysłanych” skrzynki raportów; przeglądarka
 * tylko pokazuje go i wysyła wybór taty. Domyślnie wybrany jest najnowszy okres, w którym coś czeka na wysłanie.
 */
export function MailingPage() {
  const { resource, reload } = useResource(getSettlementMailing, [])

  useReloadOnChange(reload)

  const entrance = useContentEntrance(resource.state === "loading")

  return (
    <>
      <PageHeader />
      {resource.state === "loading" ? <Skeleton className="h-80 w-full" aria-label="Wczytywanie Wysyłki rozliczeń" /> : null}
      {resource.state === "failed" ? (
        <LoadFailure what="Wysyłki rozliczeń" message={resource.message} reload={reload} />
      ) : null}
      {resource.state === "ready" && resource.data.state === "not_set" ? (
        <NotSet message={resource.data.message} className={entrance} />
      ) : null}
      {resource.state === "ready" && resource.data.state === "ready" ? (
        <Mailing view={resource.data} reload={reload} className={entrance} />
      ) : null}
    </>
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

function Mailing({ view, reload, className }: { view: Ready; reload: () => Promise<void>; className: string | undefined }) {
  const [chosen, setChosen] = React.useState<string | null>(null)

  const period =
    view.periods.find((found) => found.token === chosen) ??
    view.periods.find((found) => found.to_send > 0) ??
    view.periods[0]

  if (period === undefined) {
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

  const readable = view.mailbox.state === "ready"

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      {view.mailbox.state === "unreadable" ? (
        <Alert role="status">
          <MailWarningIcon />
          <AlertDescription>{view.mailbox.message}</AlertDescription>
        </Alert>
      ) : null}
      <div className="grid items-start gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <PeriodList periods={view.periods} chosen={period.token} readable={readable} onChoose={setChosen} />
        <PeriodMailing key={period.token} period={period} readable={readable} reload={reload} />
      </div>
    </div>
  )
}

/** Okresy od najnowszego: liczba do wysłania albo „wysłane” i pasek „Wysłane X z Y”. */
function PeriodList({
  periods,
  chosen,
  readable,
  onChoose,
}: {
  periods: MailingPeriod[]
  chosen: string
  readable: boolean
  onChoose: (token: string) => void
}) {
  return (
    <Card className="gap-1 p-2" aria-label="Okresy">
      {periods.map((period) => {
        const done = readable && period.to_send === 0 && period.counted > 0 && period.sent === period.counted
        const active = period.token === chosen

        return (
          <button
            key={period.token}
            type="button"
            aria-current={active ? "true" : undefined}
            onClick={() => onChoose(period.token)}
            className={cn(
              "flex flex-col gap-2 rounded-lg px-3 py-2.5 text-left outline-none transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
              active && "bg-muted"
            )}
          >
            <span className="flex items-start justify-between gap-2">
              <span className="font-medium text-pretty">{period.label}</span>
              {readable && period.to_send > 0 ? (
                <Badge variant="outline" className="tabular-nums">
                  {period.to_send} do wysłania
                </Badge>
              ) : null}
              {done ? (
                <Badge variant="secondary">
                  <CircleCheckIcon data-icon="inline-start" className="text-success" />
                  wysłane
                </Badge>
              ) : null}
            </span>
            {readable ? (
              <Progress value={period.counted === 0 ? 0 : (period.sent / period.counted) * 100} aria-label={`Wysłane w okresie ${period.label}`} />
            ) : null}
            <span className="text-xs text-muted-foreground tabular-nums">
              {readable ? `Wysłane ${period.sent} z ${period.counted}` : settlements(period.rows.length)}
              {period.without_orders > 0 ? ` · ${period.without_orders} bez zleceń` : ""}
            </span>
          </button>
        )
      })}
    </Card>
  )
}

/**
 * Wykonawcy okresu: zaznaczone na start są pliki do wysłania i te, których wysyłka nie wyszła. „Wyślij” otwiera okno z
 * podglądem maili, a po potwierdzeniu każdy mail idzie osobnym zapytaniem, po kolei; odznaka wiersza zmienia się,
 * gdy jego mail wychodzi, a na końcu powiadomienie mówi, ile poszło.
 */
function PeriodMailing({ period, readable, reload }: { period: MailingPeriod; readable: boolean; reload: () => Promise<void> }) {
  const [ticked, setTicked] = React.useState<ReadonlySet<string>>(
    () => new Set(period.rows.filter((row) => row.preselected).map((row) => row.worker))
  )

  const [shown, setShown] = React.useState<Readonly<Record<string, ShownState>>>({})
  const [shownFor, setShownFor] = React.useState(period)
  const [confirming, setConfirming] = React.useState<string[] | null>(null)

  const { running, run } = useAction(async (workers: string[]) => {
    await mailEach(period, workers, (worker, state) => setShown((current) => ({ ...current, [worker]: state })))
    await reload()
  }, "Nie udało się wysłać rozliczeń")

  const sending = running !== null

  // Nowy odczyt strony zna już stan po wysyłce, więc stany z odpowiedzi wysyłki ustępują mu, gdy nic nie wychodzi.
  if (shownFor !== period && !sending) {
    setShownFor(period)
    setShown({})
  }

  const sendable = period.rows.filter((row) => row.sendable && readable)
  const chosen = sendable.filter((row) => ticked.has(row.worker)).map((row) => row.worker)
  const all = sendable.length > 0 && chosen.length === sendable.length

  const tick = (worker: string, on: boolean) =>
    setTicked((current) => {
      const next = new Set(current)

      if (on) {
        next.add(worker)
      } else {
        next.delete(worker)
      }

      return next
    })

  return (
    <Card className="gap-0 overflow-hidden p-0">
      <div className="flex flex-col gap-0.5 border-b px-4 py-3">
        <h2 className="text-lg font-semibold">{period.label}</h2>
        {period.settled_at === null ? null : (
          <p className="text-sm text-muted-foreground tabular-nums">
            Rozliczenia pracowników gotowe {dateTime(period.settled_at)}
          </p>
        )}
      </div>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-10 pl-4">
              <Checkbox
                aria-label="Zaznacz wszystkie do wysłania"
                checked={all}
                indeterminate={chosen.length > 0 && !all}
                disabled={sendable.length === 0 || sending}
                onCheckedChange={(on) => setTicked(new Set(on ? sendable.map((row) => row.worker) : []))}
              />
            </TableHead>
            <TableHead>Wykonawca</TableHead>
            <TableHead className="hidden md:table-cell">Plik</TableHead>
            <TableHead>Stan</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {period.rows.map((row) => (
            <WorkerRow
              key={row.worker}
              row={row}
              state={shown[row.worker] ?? row.state}
              checked={chosen.includes(row.worker)}
              disabled={!row.sendable || !readable || sending}
              onTick={(on) => tick(row.worker, on)}
            />
          ))}
        </TableBody>
      </Table>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/30 px-4 py-3">
        <p className="text-sm text-muted-foreground tabular-nums">
          {sendable.length === 0 && readable ? "Nic z tego okresu nie czeka na wysłanie." : `Zaznaczone: ${chosen.length}`}
        </p>
        <Button disabled={chosen.length === 0 || sending} onClick={() => setConfirming(chosen)}>
          {sending ? <Spinner data-icon="inline-start" /> : <SendIcon data-icon="inline-start" />}
          {chosen.length === 0 ? "Wyślij rozliczenia" : `Wyślij ${settlements(chosen.length)}`}
        </Button>
      </div>
      {confirming === null ? null : (
        <ConfirmMailing
          token={period.token}
          label={period.label}
          workers={confirming}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            setConfirming(null)
            void run(confirming)
          }}
        />
      )}
    </Card>
  )
}

function WorkerRow({
  row,
  state,
  checked,
  disabled,
  onTick,
}: {
  row: MailingRow
  state: ShownState
  checked: boolean
  disabled: boolean
  onTick: (on: boolean) => void
}) {
  const without = row.state.state === "without_orders"

  return (
    <TableRow data-state={checked ? "selected" : undefined}>
      <TableCell className="pl-4">
        <Checkbox aria-label={`Wyślij ${row.worker}`} checked={checked} disabled={disabled} onCheckedChange={onTick} />
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-3">
          <Avatar size="sm">
            <AvatarFallback className="text-[0.65rem]">{initials(row.worker)}</AvatarFallback>
          </Avatar>
          <div className="flex min-w-0 flex-col">
            <span className="font-medium">{row.worker}</span>
            <span className="truncate text-xs text-muted-foreground">
              {row.addresses.length === 0 ? "brak adresu" : row.addresses.join(", ")}
            </span>
          </div>
        </div>
      </TableCell>
      <TableCell className={cn("hidden max-w-64 md:table-cell", without && "text-muted-foreground")}>
        <span className="flex items-center gap-1.5 text-xs" title={row.file}>
          <FileSpreadsheetIcon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate">{without ? "pusty Szablon, nie idzie" : row.file}</span>
        </span>
      </TableCell>
      <TableCell>
        <div className="flex flex-col items-start gap-1">
          <span key={state.state} className="podmiana inline-flex">
            <MailStateBadge state={state} />
          </span>
          <MailStateNote state={state} />
        </div>
      </TableCell>
    </TableRow>
  )
}

/**
 * Maile zaznaczonych Wykonawców po kolei, jedno zapytanie na mail: częściowa porażka nie psuje reszty, a podwójne
 * kliknięcie odrzuca serwer, który zna „Wysłane”. Zapytanie, które nie doszło do Centrum, kończy wysyłkę
 * powiadomieniem o porażce.
 */
async function mailEach(period: MailingPeriod, workers: string[], show: (worker: string, state: ShownState) => void) {
  let sent = 0
  let failed = 0

  for (const worker of workers) {
    const row = period.rows.find((found) => found.worker === worker)

    if (row === undefined) {
      continue
    }

    show(worker, { state: "sending" })

    try {
      const result = await sendSettlementMail(period.token, worker, row.resend)

      show(worker, result.row.state)
      sent += result.sent_now ? 1 : 0
      failed += result.row.state.state === "not_sent" ? 1 : 0
    } catch (failure) {
      show(worker, row.state)
      showFailure(failure instanceof Error ? failure : new Error(String(failure)), "Nie udało się wysłać rozliczenia")

      return
    }
  }

  toast.add({
    title: `Wysłano ${settlements(sent)} ze skrzynki raportów.`,
    description:
      failed === 0 ? undefined : `${failed} ${plural(failed, { one: "nie wyszło", few: "nie wyszły", many: "nie wyszło" })}: powód stoi przy Wykonawcy.`,
    type: failed === 0 ? "success" : "error",
  })
}
