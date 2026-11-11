import { ChevronLeftIcon, ChevronRightIcon, FileSpreadsheetIcon, HistoryIcon, MailCheckIcon } from "lucide-react"
import type { ReactNode } from "react"

import { getReportsView, keepManualValue, type ReportsView } from "@/api/centrum"
import { LoadFailure } from "@/components/load-failure"
import { PageHeader } from "@/components/page-header"
import { SettingPath } from "@/components/setting-path"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { useAction } from "@/lib/action"
import { href, usePagePath } from "@/lib/address"
import { useContentEntrance } from "@/lib/content-entrance"
import { dateTime, weekdayDate } from "@/lib/format"
import { useResource } from "@/lib/use-resource"
import { EnteringNotes, EnterReportsButton, useReportEntering } from "@/pages/worker-reports/report-entering"
import { UnknownSenders, WorkerRow, type Keep } from "@/pages/worker-reports/worker-row"

/**
 * Widok Raporty z adresu `#/raporty/<dzień>`: wynik ostatniego kliknięcia „Wpisz raporty z maili” w wybranym dniu
 * (bez dnia: dziś). Serwer oddaje całe okno z pliku wyniku, nie ze skrzynki, a strona pokazuje z niego dzień z adresu;
 * „Zostaw moją” zastępuje widok odpowiedzią serwera.
 * Przycisk Wpisania raportów stoi w nagłówku, a koniec Wpisania czyta widok od nowa. Pod nagłówkiem jedna cicha linia
 * z chwilą ostatniego kliknięcia i INTERMAX z Ustawień taty.
 */
export function ReportsPage() {
  const [path = null] = usePagePath()
  const { resource: view, reload, replace } = useResource(getReportsView, [], { fromDadFiles: false })
  const entrance = useContentEntrance(view.state === "loading")
  const entering = useReportEntering(reload)

  const { running, run } = useAction(
    async (cell: Keep) => replace({ state: "ready", data: await keepManualValue(cell) }),
    "Nie udało się zostawić Twojej wartości"
  )

  return (
    <>
      <PageHeader
        action={
          <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
            {view.state === "ready" ? <DayPicker view={view.data} day={path ?? view.data.today} /> : null}
            <EnterReportsButton entering={entering} />
          </div>
        }
      />
      <EnteringNotes entering={entering} />
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-muted-foreground">
        {view.state === "ready" && view.data.clicked_at !== null ? (
          <p className="flex items-center gap-2 tabular-nums">
            <HistoryIcon className="size-4" aria-hidden />
            Ostatnie kliknięcie {dateTime(view.data.clicked_at)}
          </p>
        ) : null}
        <div className="ml-auto min-w-0">
          <SettingPath label="INTERMAX" icon={<FileSpreadsheetIcon />} path="order_register" />
        </div>
      </div>
      {view.state === "loading" ? <Skeleton className="h-64 w-full" aria-label="Wczytywanie Raportów" /> : null}
      {view.state === "failed" ? <LoadFailure what="Raportów" message={view.message} reload={reload} /> : null}
      {view.state === "ready" ? (
        <ReportsContent
          view={view.data}
          day={path ?? view.data.today}
          keeping={running?.[0] ?? null}
          onKeep={run}
          className={entrance}
        />
      ) : null}
    </>
  )
}

/** Dzień widoku ze strzałkami na dzień wcześniejszy i późniejszy z dni okna, które podaje serwer (od najstarszego). */
function DayPicker({ view, day }: { view: ReportsView; day: string }) {
  const days = view.days.map((found) => found.day)
  const at = days.indexOf(day)
  const older = at <= 0 ? undefined : days[at - 1]
  const newer = at === -1 ? undefined : days[at + 1]

  return (
    <div className="flex items-center gap-1" role="group" aria-label="Dzień">
      <DayLink day={older} label="Wcześniejszy dzień" icon={<ChevronLeftIcon />} />
      <span className="min-w-36 text-center text-sm font-medium whitespace-nowrap tabular-nums" aria-live="polite">
        {weekdayDate(day)}
        {day === view.today ? <span className="font-normal text-muted-foreground"> · dziś</span> : null}
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
  day,
  keeping,
  onKeep,
  className,
}: {
  view: ReportsView
  day: string
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
          <EmptyDescription>Kliknij „Wpisz raporty z maili” powyżej.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const workers = view.workers.flatMap(({ worker, days }) =>
    days.filter((found) => found.day === day).map((found) => ({ worker, day: found }))
  )

  const unknown = view.unknown_senders.filter((sender) => sender.day === day)
  const nothing = workers.length === 0 && unknown.length === 0

  return (
    <div className={`flex flex-col gap-4 ${className ?? ""}`}>
      {nothing ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">Ten dzień nie ma zleceń ani Raportów wykonawców.</CardContent>
        </Card>
      ) : null}
      {workers.length === 0 ? null : (
        <Card className="py-0" role="list" aria-label="Wykonawcy">
          {workers.map(({ worker, day: shown }) => (
            <WorkerRow key={worker} worker={worker} day={shown} keeping={keeping} onKeep={onKeep} />
          ))}
        </Card>
      )}
      <UnknownSenders senders={unknown} />
    </div>
  )
}
