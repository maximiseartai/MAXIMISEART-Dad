import * as React from "react"
import { FileClockIcon, RotateCcwIcon } from "lucide-react"

import { failureMessage } from "@/api/client"
import { getRunCard, type RunCard, type ProcessRun, type RunRestored } from "@/api/centrum"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { HistoryRunCard } from "@/pages/runs/run-card"

const OPEN = "Karta Uruchomienia"

type Card = { state: "loading" } | { state: "failed"; message: string } | { state: "ready"; card: RunCard }

/** Przycisk wiersza Historii: karta tego Uruchomienia z jego Logów Uruchomienia w panelu z boku. */
export function RunCardButton({ run }: { run: ProcessRun }) {
  return (
    <CardSheet title={run.process_label} period={run.period}>
      <ShownCard runId={run.run_id} />
    </CardSheet>
  )
}

/** Przycisk z napisem w Powiadomieniu: karta Uruchomienia `runId` z jego Logów w tym samym panelu z boku. */
export function RunCardLink({ runId, title, period }: { runId: string; title: string; period: string }) {
  return (
    <CardSheet title={title} period={period} labelled>
      <RunCardBody runId={runId} />
    </CardSheet>
  )
}

/** Karta Uruchomienia, którą serwer już przysłał (np. ostatnie Uporządkowanie INTERMAX), w tym samym panelu z boku. */
export function RestoredCardButton({ card }: { card: RunRestored }) {
  return (
    <CardSheet title={card.run.title} period={card.run.period}>
      <HistoryRunCard card={card} />
    </CardSheet>
  )
}

/**
 * Przycisk z ikoną karty (`labelled`: z napisem) i panel z boku, który montuje treść karty tylko otwarty. Tryb
 * Uruchomienia pokazuje karta z Logów (`HistoryRunCard`).
 */
function CardSheet({
  title,
  period,
  labelled = false,
  children,
}: {
  title: string
  period: string
  labelled?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = React.useState(false)

  return (
    <>
      {labelled ? (
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          <FileClockIcon data-icon="inline-start" />
          {OPEN}
        </Button>
      ) : (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="ghost"
                size="icon-sm"
                className="text-muted-foreground"
                aria-label={OPEN}
                onClick={() => setOpen(true)}
              />
            }
          >
            <FileClockIcon />
          </TooltipTrigger>
          <TooltipContent>{OPEN}</TooltipContent>
        </Tooltip>
      )}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="gap-0 sm:max-w-3xl data-[side=right]:sm:max-w-3xl">
          <SheetHeader className="pr-12">
            <SheetTitle className="text-lg">{title}</SheetTitle>
            <SheetDescription className="tabular-nums">Okres {period}</SheetDescription>
          </SheetHeader>
          <div className="overflow-y-auto px-4 pb-6">{open ? children : null}</div>
        </SheetContent>
      </Sheet>
    </>
  )
}

/** Odczyt karty przy każdym otwarciu panelu (panel montuje treść tylko otwarty). */
function RunCardBody({ runId }: { runId: string }) {
  const [card, setCard] = React.useState<Card>({ state: "loading" })

  const fetchCard = React.useCallback(
    () =>
      getRunCard(runId).then(
        (found) => setCard({ state: "ready", card: found }),
        (failure: Error) => setCard({ state: "failed", message: failureMessage(failure) })
      ),
    [runId]
  )

  React.useEffect(() => {
    fetchCard()
  }, [fetchCard])

  const retry = () => {
    setCard({ state: "loading" })
    fetchCard()
  }

  switch (card.state) {
    case "loading":
      return <Skeleton className="h-64 w-full" aria-label="Wczytywanie karty Uruchomienia" />
    case "failed":
      return (
        <Alert variant="destructive">
          <AlertTitle>Nie udało się odczytać karty Uruchomienia</AlertTitle>
          <AlertDescription>{card.message}</AlertDescription>
          <AlertAction>
            <Button size="sm" variant="outline" onClick={retry}>
              <RotateCcwIcon data-icon="inline-start" />
              Spróbuj ponownie
            </Button>
          </AlertAction>
        </Alert>
      )
    case "ready":
      return card.card.state === "restored" ? <HistoryRunCard card={card.card} /> : <MissingCard />
    default: {
      const unhandled: never = card

      return unhandled
    }
  }
}

/** Wiersz bez identyfikatora Uruchomienia (`.cmd`) karty nie ma, więc panel nie pyta serwera. */
function ShownCard({ runId }: { runId: string | null }) {
  return runId === null ? <MissingCard /> : <RunCardBody runId={runId} />
}

function MissingCard() {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <FileClockIcon />
        </EmptyMedia>
        <EmptyTitle>Karty tego Uruchomienia nie ma</EmptyTitle>
        <EmptyDescription>Wystartowało spoza Centrum rozliczeń albo jego wynik nie został zachowany.</EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}
