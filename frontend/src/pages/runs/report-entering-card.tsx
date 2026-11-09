import { FileSpreadsheetIcon, HistoryIcon, InfoIcon, MailCheckIcon } from "lucide-react"

import { getReportEnteringSetup, type ReportEnteringSetup } from "@/api/centrum"
import type { RunRestored } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { SettingPath } from "@/components/setting-path"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { WarningSentences } from "@/components/warning-sentences"
import { dateTime } from "@/lib/format"
import { useRuns } from "@/lib/runs"
import { useResource } from "@/lib/use-resource"
import { RestoredCardButton } from "@/pages/runs/run-card-sheet"

/**
 * Karta „Wpisz raporty z maili” poza okresami (ADR 0028): Raporty wykonawców ze skrzynki raportów trafiają do pustych
 * komórek INTERMAX z Ustawień taty, więc jest tylko jeden przycisk.
 */
export function ReportEnteringCard() {
  const { resource: setup, reload } = useResource(getReportEnteringSetup, [])

  switch (setup.state) {
    case "loading":
      return <Skeleton className="h-40 w-full" aria-label="Wczytywanie Wpisania raportów" />
    case "failed":
      return <LoadFailure what="Wpisania raportów" message={setup.message} reload={reload} />
    case "ready":
      return <ReportEnteringSetupCard setup={setup.data} />
    default: {
      const unhandled: never = setup

      return unhandled
    }
  }
}

function ReportEnteringSetupCard({ setup }: { setup: ReportEnteringSetup }) {
  const { starting, start } = useRuns()
  const blocked = setup.blocker !== null || setup.open_in_excel.length > 0
  const notes = setup.blocker === null ? setup.open_in_excel : [setup.blocker, ...setup.open_in_excel]

  return (
    <Card role="region" aria-label="Wpisz raporty z maili">
      <CardHeader>
        <CardTitle className="text-lg">{setup.title}</CardTitle>
        <CardDescription>Tak/nie i czynności z maili Wykonawców do pustych komórek.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <SettingPath label="INTERMAX" icon={<FileSpreadsheetIcon />} path="order_register" />
        <WarningSentences sentences={notes} />
        {setup.last === null ? null : <LastEntering last={setup.last} />}
      </CardContent>
      <CardFooter className="gap-2">
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          <InfoIcon className="size-4" aria-hidden />
          {setup.reminder}
        </span>
        <Button
          size="lg"
          className="ml-auto h-11 px-5 text-base"
          disabled={blocked || starting}
          onClick={() => start({ process: "report_entering" })}
        >
          <MailCheckIcon data-icon="inline-start" />
          Wpisz raporty z maili
        </Button>
      </CardFooter>
    </Card>
  )
}

function LastEntering({ last }: { last: RunRestored }) {
  const entered = last.result.summary?.figures[0]

  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
      <HistoryIcon className="size-4 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">
        Ostatnio {dateTime(last.started_at)} · {last.result.headline}
        {entered === undefined ? null : ` · ${entered.label} ${entered.value}`}
      </span>
      <span className="ml-auto">
        <RestoredCardButton card={last} />
      </span>
    </div>
  )
}
