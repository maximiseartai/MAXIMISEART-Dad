import * as React from "react"
import { CircleCheckIcon, RefreshCwIcon, TriangleAlertIcon } from "lucide-react"

import { reportToolUpdate, type ToolUpdate } from "@/api/centrum"
import { ReportToMaks } from "@/components/report-to-maks"
import { ThreePartMessage } from "@/components/three-part-message"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { useToolUpdate } from "@/lib/tool-update"

type Step = Extract<ToolUpdate, { state: "running" }>["step"]

// Jeden stan w trzech krokach, bez procentów: tata widzi, że trwa, i co teraz.
const STEPS: Record<Step, string> = {
  fetching: "Pobieranie nowej wersji…",
  installing: "Instalowanie bibliotek…",
  restarting: "Ponowne uruchamianie Centrum…",
}

/**
 * Przycisk `Zaktualizuj narzędzie`, ten sam w każdym miejscu, w którym Centrum prosi o aktualizację. Aktualizacja
 * jest jedna na Centrum, więc w jej trakcie każdy taki przycisk jest wyłączony. `primary`: aktualizacja jest w tym
 * miejscu następnym krokiem taty; po porażce głównym przyciskiem jest to, co każe Komunikat.
 */
export function ToolUpdateButton({ primary, size }: { primary: boolean; size?: "sm" }) {
  const { update, busy, start } = useToolUpdate()
  const mainAction = update?.state === "failed" ? update.next_action === "retry" : primary

  return (
    // Wyłączony, ale dalej pod kursorem: drugie kliknięcie tylko trafia w przycisk, nie zaznacza tekstu strony.
    <Button
      variant={mainAction ? "default" : "outline"}
      size={size}
      disabled={busy}
      focusableWhenDisabled
      className="data-disabled:opacity-50"
      onClick={start}
    >
      {busy ? <Spinner data-icon="inline-start" aria-hidden /> : <RefreshCwIcon data-icon="inline-start" />}
      Zaktualizuj narzędzie
    </Button>
  )
}

/**
 * Stan Aktualizacji narzędzia przy przycisku: krok w trakcie, Komunikat porażki z „Wyślij do Maksa”, „Masz
 * najnowszą wersję.” albo nieudany odczyt stanu. Każde miejsce z przyciskiem ma ten stan, więc to on odczytuje aktualizację przy wejściu na
 * stronę. Udana aktualizacja kończy się przeładowaniem karty i powiadomieniem, a porażka ponownego startu
 * Komunikatem pod tytułem strony (`ToolUpdateAfterRestart`), więc tu ich nie ma.
 */
export function ToolUpdateStatus() {
  const { update, readFailure, restarted, read } = useToolUpdate()

  React.useEffect(read, [read])

  if (readFailure !== null && update?.state !== "running") {
    return (
      <p role="status" className="wejscie flex items-center gap-2 text-sm text-destructive">
        <TriangleAlertIcon className="size-4 shrink-0" aria-hidden />
        Nie udało się odczytać stanu aktualizacji. {readFailure}
      </p>
    )
  }

  if (update === null || update.state === "idle" || update.state === "updated") {
    return null
  }

  if (update.state === "failed") {
    return restarted ? null : <ToolUpdateFailure update={update} />
  }

  return (
    <p role="status" className="wejscie flex items-center gap-2 text-sm">
      {update.state === "running" ? (
        <>
          <Spinner aria-hidden className="text-muted-foreground" />
          <span className="text-muted-foreground">{STEPS[update.step]}</span>
        </>
      ) : (
        <>
          <CircleCheckIcon className="size-4 text-success" aria-hidden />
          Masz najnowszą wersję.
        </>
      )}
    </p>
  )
}

/**
 * Komunikat porażki z ponownego startu (np. nowa wersja nie wystartowała i wróciła poprzednia) pod tytułem każdej
 * strony, na której tata ląduje po przeładowaniu karty albo po starcie ze skrótu, aż znów kliknie `Zaktualizuj
 * narzędzie`.
 */
export function ToolUpdateAfterRestart() {
  const { update, restarted } = useToolUpdate()

  if (!restarted || update?.state !== "failed") {
    return null
  }

  return <ToolUpdateFailure update={update} />
}

function ToolUpdateFailure({ update }: { update: Extract<ToolUpdate, { state: "failed" }> }) {
  return (
    <div className="flex flex-col gap-3">
      <ThreePartMessage message={update.message} kind="warning" />
      <ReportToMaks
        send={reportToolUpdate}
        report={update.report}
        draft={update.draft}
        primary={update.next_action === "report"}
      />
    </div>
  )
}
