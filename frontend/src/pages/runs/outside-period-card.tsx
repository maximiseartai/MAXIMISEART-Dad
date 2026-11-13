import { FileSpreadsheetIcon, HistoryIcon, InfoIcon } from "lucide-react"
import type { ReactNode } from "react"

import type { IntermaxSetup } from "@/api/centrum"
import type { RunRestored } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { SettingPath } from "@/components/setting-path"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { WarningSentences } from "@/components/warning-sentences"
import { dateTime } from "@/lib/format"
import { type RunStart, useRuns } from "@/lib/runs"
import { useResource } from "@/lib/use-resource"
import { RestoredCardButton } from "@/pages/runs/run-card-sheet"

type OutsidePeriodCardProps = {
  read: () => Promise<IntermaxSetup>
  /** Nazwa procesu w dopełniaczu, do szkieletu i błędu odczytu („Wczytywanie Uporządkowania INTERMAX”). */
  what: string
  /** Napis przycisku i nazwa karty dla czytnika ekranu. */
  label: string
  description: string
  icon: ReactNode
  request: RunStart
  skeleton: string
  /** Treść pod INTERMAX z Ustawień Centrum, gdy serwer nie podaje blokady (np. dni INTERMAX). */
  unblocked?: ReactNode
  /** Dopisek linii „Ostatnio …” o ostatnim Uruchomieniu, np. liczba uporządkowanych zleceń. */
  lastDetail: (last: RunRestored) => string | undefined
}

/**
 * Karta procesu bez okresu w Uruchomieniach (Uporządkowanie INTERMAX; Wpisanie raportów ma przycisk na ekranie Raporty):
 * proces bierze INTERMAX z Ustawień Centrum, więc karta ma tylko jeden przycisk, zablokowany, gdy serwer podaje blokadę
 * albo INTERMAX otwarty w Excelu.
 */
export function OutsidePeriodCard(props: OutsidePeriodCardProps) {
  const { resource: setup, reload } = useResource(props.read, [])

  switch (setup.state) {
    case "loading":
      return <Skeleton className={`${props.skeleton} w-full`} aria-label={`Wczytywanie ${props.what}`} />
    case "failed":
      return <LoadFailure what={props.what} message={setup.message} reload={reload} />
    case "ready":
      return <SetupCard {...props} setup={setup.data} />
    default: {
      const unhandled: never = setup

      return unhandled
    }
  }
}

function SetupCard({
  setup,
  label,
  description,
  icon,
  request,
  unblocked,
  lastDetail,
}: OutsidePeriodCardProps & { setup: IntermaxSetup }) {
  const { starting, start } = useRuns()
  const blocked = setup.blocker !== null || setup.open_in_excel.length > 0
  const notes = setup.blocker === null ? setup.open_in_excel : [setup.blocker, ...setup.open_in_excel]

  return (
    <Card role="region" aria-label={label}>
      <CardHeader>
        <CardTitle className="text-lg">{setup.title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <SettingPath label="INTERMAX" icon={<FileSpreadsheetIcon />} path="order_register" />
        {setup.blocker === null ? unblocked : null}
        <WarningSentences sentences={notes} />
        {setup.last === null ? null : <LastRun last={setup.last} detail={lastDetail(setup.last)} />}
      </CardContent>
      <CardFooter className="gap-2">
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          <InfoIcon className="size-4" aria-hidden />
          {setup.reminder}
        </span>
        <Button size="lg" className="ml-auto h-11 px-5 text-base" disabled={blocked || starting} onClick={() => start(request)}>
          {icon}
          {label}
        </Button>
      </CardFooter>
    </Card>
  )
}

function LastRun({ last, detail }: { last: RunRestored; detail: string | undefined }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
      <HistoryIcon className="size-4 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">
        Ostatnio {dateTime(last.started_at)} · {last.result.headline}
        {detail === undefined ? null : ` · ${detail}`}
      </span>
      <span className="ml-auto">
        <RestoredCardButton card={last} />
      </span>
    </div>
  )
}
