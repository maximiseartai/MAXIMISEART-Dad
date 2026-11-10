import { ChevronDownIcon, MailQuestionIcon } from "lucide-react"

import type { KeptCell, ReportsProblem, ReportsWorker } from "@/api/generated"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"

/** Komórka różnicy z ręczną wartością, przy której tata klika „Zostaw moją”. */
export type Keep = KeptCell

/**
 * Wykonawca dnia w jednej linii: nazwa i cztery liczby. Problemy i zlecenia bez raportu rozwijają się pod nią;
 * Wykonawca bez nich nie ma czego rozwinąć.
 */
export function WorkerRow({
  worker,
  keeping,
  onKeep,
}: {
  worker: ReportsWorker
  keeping: Keep | null
  onKeep: (cell: Keep) => void
}) {
  const details = worker.problems.length > 0 || worker.without_report.length > 0

  // Na wąskim ekranie liczby schodzą pod nazwę, w cztery równe kolumny; od `sm` stoją w jednej linii z nazwą.
  const line = (
    <>
      <span className="min-w-0 flex-1 truncate font-medium">{worker.worker}</span>
      <span className="order-last grid w-full grid-cols-4 gap-2 sm:order-none sm:flex sm:w-auto sm:gap-6">
        <Figure label="Zlecenia" value={worker.orders} />
        <Figure label="Wpisane" value={worker.entered} />
        <Figure label="Maile" value={worker.mails} />
        <Figure label="Problemy" value={worker.problems.length} warn={worker.problems.length > 0} />
      </span>
    </>
  )

  if (!details) {
    return (
      <div role="listitem" aria-label={worker.worker} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-5 py-3 last:border-b-0 sm:flex-nowrap sm:gap-6">
        {line}
        <span className="size-4 shrink-0" aria-hidden />
      </div>
    )
  }

  return (
    <Collapsible role="listitem" aria-label={worker.worker} className="border-b last:border-b-0">
      <CollapsibleTrigger className="group flex w-full flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3 text-left transition-colors hover:bg-muted/50 sm:flex-nowrap sm:gap-6">
        {line}
        <ChevronDownIcon
          className="size-4 shrink-0 text-muted-foreground transition-[rotate] duration-200 ease-out group-data-[panel-open]:rotate-180"
          aria-hidden
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex flex-col gap-4 px-5 pt-1 pb-4">
          {worker.problems.length === 0 ? null : (
            <ul className="flex flex-col gap-3" aria-label="Problemy">
              {worker.problems.map((problem) => (
                <ProblemItem key={problemKey(problem)} problem={problem} keeping={keeping} onKeep={onKeep} />
              ))}
            </ul>
          )}
          {worker.without_report.length === 0 ? null : (
            <div className="flex flex-wrap items-center gap-2 text-sm" role="group" aria-label="Bez raportu">
              <span className="text-muted-foreground">Bez raportu</span>
              {worker.without_report.map((number) => (
                <span key={number} className="rounded-md bg-secondary px-2 py-0.5 tabular-nums">
                  {number}
                </span>
              ))}
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** Raporty wykonawcy dnia z adresów spoza listy adresów Wykonawców: adres widać tylko tutaj. */
export function UnknownSenders({ problems }: { problems: ReadonlyArray<ReportsProblem> }) {
  if (problems.length === 0) {
    return null
  }

  return (
    <Card role="region" aria-label="Spoza listy adresów">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MailQuestionIcon className="size-4 text-warning" aria-hidden />
          Spoza listy adresów
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-3">
          {problems.map((problem) => (
            <li key={problemKey(problem)} className="flex flex-col gap-0.5 text-sm">
              <span className="font-medium break-all">{problem.sender}</span>
              <span className="text-muted-foreground">{problem.reason}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function Figure({ label, value, warn = false }: { label: string; value: number; warn?: boolean }) {
  return (
    <span className="flex min-w-0 flex-col sm:w-20 sm:shrink-0 sm:items-end sm:text-right" aria-label={`${label} ${value}`}>
      <span className={`text-lg font-semibold tabular-nums ${warn ? "text-warning" : ""}`}>{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </span>
  )
}

function ProblemItem({
  problem,
  keeping,
  onKeep,
}: {
  problem: ReportsProblem
  keeping: Keep | null
  onKeep: (cell: Keep) => void
}) {
  const keep = problem.keep

  return (
    <li className="flex flex-col gap-2 text-sm sm:flex-row sm:items-start sm:gap-3">
      {problem.number === null ? null : (
        <span className="w-fit shrink-0 rounded-md bg-secondary px-2 py-0.5 tabular-nums">{problem.number}</span>
      )}
      <span className="min-w-0 flex-1 text-muted-foreground">{problem.reason}</span>
      {keep === null ? null : (
        <Button
          size="sm"
          variant="outline"
          className="w-fit shrink-0"
          title={`Wpis raportu: ${keep.reported}`}
          disabled={keeping !== null}
          onClick={() => onKeep(keep)}
        >
          Zostaw moją
        </Button>
      )}
    </li>
  )
}

function problemKey(problem: ReportsProblem): string {
  return JSON.stringify([problem.number, problem.sender, problem.reason, problem.keep])
}
