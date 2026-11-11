import { ChevronLeftIcon, ChevronRightIcon, HistoryIcon, MailCheckIcon } from "lucide-react"
import type { ReactNode } from "react"

import { getReportsView, keepManualValue, type ReportsView } from "@/api/centrum"
import { LoadFailure } from "@/components/load-failure"
import { PageHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { useAction } from "@/lib/action"
import { href, usePagePath } from "@/lib/address"
import { useContentEntrance } from "@/lib/content-entrance"
import { dateTime, weekdayDate } from "@/lib/format"
import { useResource } from "@/lib/use-resource"
import { UnknownSenders, WorkerRow, type Keep } from "@/pages/worker-reports/worker-row"

/**
 * Widok Raporty z adresu `#/raporty/<dzień>`: wynik ostatniego kliknięcia „Wpisz raporty z maili” w wybranym dniu
 * (bez dnia: dziś). Serwer czyta go z pliku wyniku, nie ze skrzynki; „Zostaw moją” zastępuje widok odpowiedzią serwera.
 */
export function ReportsPage() {
  const [day = null] = usePagePath()
  const { resource: view, reload, replace } = useResource(getReportsView, [day], { fromDadFiles: false })
  const entrance = useContentEntrance(view.state === "loading")

  const { running, run } = useAction(
    async (cell: Keep) => replace({ state: "ready", data: await keepManualValue(cell) }),
    "Nie udało się zostawić Twojej wartości"
  )

  return (
    <>
      <PageHeader action={view.state === "ready" ? <DayPicker view={view.data} /> : undefined} />
      {view.state === "loading" ? <Skeleton className="h-64 w-full" aria-label="Wczytywanie Raportów" /> : null}
      {view.state === "failed" ? <LoadFailure what="Raportów" message={view.message} reload={reload} /> : null}
      {view.state === "ready" ? (
        <ReportsContent view={view.data} keeping={running?.[0] ?? null} onKeep={run} className={entrance} />
      ) : null}
    </>
  )
}

/** Dzień widoku ze strzałkami na dzień wcześniejszy i późniejszy z dni, które podaje serwer (od najnowszego). */
function DayPicker({ view }: { view: ReportsView }) {
  const at = view.days.indexOf(view.day)
  const older = at === -1 ? undefined : view.days[at + 1]
  const newer = at <= 0 ? undefined : view.days[at - 1]

  return (
    <div className="flex items-center gap-1" role="group" aria-label="Dzień">
      <DayLink day={older} label="Wcześniejszy dzień" icon={<ChevronLeftIcon />} />
      <span className="min-w-36 text-center text-sm font-medium tabular-nums" aria-live="polite">
        {weekdayDate(view.day)}
        {view.day === view.today ? <span className="font-normal text-muted-foreground"> · dziś</span> : null}
      </span>
      <DayLink day={newer} label="Późniejszy dzień" icon={<ChevronRightIcon />} />
    </div>
  )
}

function DayLink({ day, label, icon }: { day: string | undefined; label: string; icon: ReactNode }) {
  if (day === undefined) {
    return (
      <Button variant="ghost" size="icon" aria-label={label} disabled>
        {icon}
      </Button>
    )
  }

  return (
    <Button variant="ghost" size="icon" aria-label={label} nativeButton={false} render={<a href={href("raporty", day)} />}>
      {icon}
    </Button>
  )
}

function ReportsContent({
  view,
  keeping,
  onKeep,
  className,
}: {
  view: ReportsView
  keeping: Keep | null
  onKeep: (cell: Keep) => void
  className: string | undefined
}) {
  if (view.clicked_at === null) {
    return (
      <Empty className={className}>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <MailCheckIcon />
          </EmptyMedia>
          <EmptyTitle>Jeszcze nie ma Raportów</EmptyTitle>
          <EmptyDescription>Kliknij „Wpisz raporty z maili” w Uruchomieniach.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const nothing = view.workers.length === 0 && view.unknown_senders.length === 0

  return (
    <div className={`flex flex-col gap-4 ${className ?? ""}`}>
      <p className="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
        <HistoryIcon className="size-4" aria-hidden />
        Ostatnie kliknięcie {dateTime(view.clicked_at)}
      </p>
      {nothing ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">Ten dzień nie ma zleceń ani Raportów wykonawców.</CardContent>
        </Card>
      ) : null}
      {view.workers.length === 0 ? null : (
        <Card className="py-0" role="list" aria-label="Wykonawcy">
          {view.workers.map((worker) => (
            <WorkerRow key={worker.worker} worker={worker} keeping={keeping} onKeep={onKeep} />
          ))}
        </Card>
      )}
      <UnknownSenders problems={view.unknown_senders} />
    </div>
  )
}
