import * as React from "react"
import { cn } from "cn"
import { MailCheckIcon, TriangleAlertIcon } from "lucide-react"

import { getReportEnteringSetup, type ReportEnteringSetup, type RunView } from "@/api/centrum"
import { LoadFailure } from "@/components/load-failure"
import { Alert, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { WarningSentences } from "@/components/warning-sentences"
import { href } from "@/lib/address"
import { isActive, runOf, useRuns } from "@/lib/runs"
import { type Resource, useResource } from "@/lib/use-resource"

const REQUEST = { process: "report_entering" } as const

/** Napis głównego przycisku ekranu Raporty; Komunikaty Wpisania raportów cytują go w „…”. */
const LABEL = "Wpisz raporty z maili"

type ReportEntering = {
  setup: Resource<ReportEnteringSetup>
  reload: () => Promise<void>
  /** Wpisanie raportów ze strumienia, trwające albo zakończone w tej pracy Centrum. */
  run: Exclude<RunView, { state: "idle" }> | null
}

/**
 * Wpisanie raportów na ekranie Raporty (ADR 0028): stan przed kliknięciem z serwera i to Uruchomienie ze strumienia.
 * Gdy Wpisanie, które tata widział na żywo albo zastał trwające, się kończy, `onEnd` czyta widok Raporty od nowa, a
 * stan przed kliknięciem czyta się sam, bo po zapisie obok INTERMAX może leżeć kopia konfliktu OneDrive.
 */
export function useReportEntering(onEnd: () => void): ReportEntering {
  const { resource: setup, reload } = useResource(getReportEnteringSetup, [])
  const { view } = useRuns()
  const run = runOf(view, REQUEST.process)
  const ended = run?.state === "finished" ? run.run.id : null
  // Wpisanie zakończone przed wejściem na ekran zna już odczyt przy montowaniu.
  const readAfter = React.useRef(ended)

  React.useEffect(() => {
    if (ended !== null && ended !== readAfter.current) {
      readAfter.current = ended
      reload()
      onEnd()
    }
  }, [ended, reload, onEnd])

  return { setup, reload, run }
}

/**
 * „Wpisz raporty z maili”, jedyny główny przycisk ekranu. Wyłączony przy blokadzie z serwera, INTERMAX otwartym w
 * Excelu i w czasie każdego Uruchomienia; w czasie Wpisania raportów pokazuje, że trwa. Oba napisy stoją w jednej
 * komórce siatki, więc przycisk nie zmienia szerokości, a nagłówek nie skacze.
 */
export function EnterReportsButton({ entering }: { entering: ReportEntering }) {
  const { view, starting, start } = useRuns()
  const setup = entering.setup.state === "ready" ? entering.setup.data : null
  const working = starting || isActive(entering.run)
  const disabled = setup === null || blocked(setup) || starting || isActive(view)

  return (
    <Tooltip>
      <TooltipTrigger
        render={<Button size="lg" className="h-11 px-5 text-base" disabled={disabled} onClick={() => start(REQUEST)} />}
      >
        <span className="grid *:col-start-1 *:row-start-1">
          <Label shown={!working}>
            <MailCheckIcon data-icon="inline-start" />
            {LABEL}
          </Label>
          <Label shown={working}>
            {/* Ukryty spinner kręciłby się bez końca, więc do czasu Wpisania stoi puste miejsce jego rozmiaru. */}
            {working ? <Spinner data-icon="inline-start" aria-hidden /> : <span className="size-4" />}
            Wpisuję raporty…
          </Label>
        </span>
      </TooltipTrigger>
      {setup === null ? null : <TooltipContent>{setup.reminder}</TooltipContent>}
    </Tooltip>
  )
}

function Label({ shown, children }: { shown: boolean; children: React.ReactNode }) {
  return (
    <span
      aria-hidden={!shown}
      className={cn(
        "flex items-center justify-center gap-2 transition-[opacity,filter] duration-150 ease-out",
        !shown && "opacity-0 blur-[2px]"
      )}
    >
      {children}
    </span>
  )
}

function blocked(setup: ReportEnteringSetup): boolean {
  return setup.blocker !== null || setup.open_in_excel.length > 0
}

/**
 * Zdania pod nagłówkiem: czemu przycisk jest wyłączony (z serwera) i Zatrzymanie Wpisania raportów z tej pracy
 * Centrum, którego Komunikat stoi w Uruchomieniach. Bez blokady i bez Zatrzymania nic tu nie stoi.
 */
export function EnteringNotes({ entering }: { entering: ReportEntering }) {
  const { setup, reload, run } = entering

  return (
    <>
      {setup.state === "failed" ? <LoadFailure what="Wpisania raportów" message={setup.message} reload={reload} /> : null}
      {setup.state === "ready" ? (
        <WarningSentences
          sentences={setup.data.blocker === null ? setup.data.open_in_excel : [setup.data.blocker, ...setup.data.open_in_excel]}
        />
      ) : null}
      {run?.state === "finished" && run.result.ending !== "finished" ? <Stopped headline={run.result.headline} /> : null}
    </>
  )
}

function Stopped({ headline }: { headline: string }) {
  return (
    <Alert className="wejscie" role="region" aria-label="Zatrzymanie Wpisania raportów">
      <TriangleAlertIcon className="text-warning!" />
      <AlertTitle className="font-normal">
        {headline}. Komunikat jest w{" "}
        <a className="font-medium underline underline-offset-4" href={href("uruchomienia")}>
          Uruchomieniach
        </a>
        .
      </AlertTitle>
    </Alert>
  )
}
