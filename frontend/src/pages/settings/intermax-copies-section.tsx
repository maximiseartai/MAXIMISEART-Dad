import * as React from "react"
import { ArchiveRestoreIcon, CircleCheckIcon, HistoryIcon } from "lucide-react"

import { getIntermaxCopies, restoreIntermaxCopy, type IntermaxRestore } from "@/api/centrum"
import type { IntermaxCopy } from "@/api/generated"
import { failureMessage } from "@/api/client"
import { LoadFailure } from "@/components/load-failure"
import { ThreePartMessage } from "@/components/three-part-message"
import { Alert, AlertTitle } from "@/components/ui/alert"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from "@/components/ui/item"
import { Skeleton } from "@/components/ui/skeleton"
import { dateTime, hourMinute } from "@/lib/format"
import { useResource } from "@/lib/use-resource"

/** Wynik ostatniego „Przywróć tę kopię” na karcie albo odmowa serwera, gdy coś innego trwa. */
type Outcome = IntermaxRestore | { state: "failed"; message: string }

/**
 * Kopie INTERMAX od najnowszej z datą i godziną z nazwy; każdą tata przywraca po jednym zdaniu ostrzeżenia, że
 * zmiany po jej godzinie znikną. Wynik (przywrócona albo Komunikat odmowy) stoi nad listą, a lista czyta się od
 * nowa, bo stan sprzed przywrócenia jest teraz nową Kopią.
 */
export function IntermaxCopiesSection() {
  const { resource: copies, reload } = useResource(getIntermaxCopies, [])
  const [chosen, setChosen] = React.useState<IntermaxCopy | null>(null)
  const [restoring, setRestoring] = React.useState(false)
  const [outcome, setOutcome] = React.useState<Outcome | null>(null)

  function restore(copy: IntermaxCopy) {
    setRestoring(true)
    setOutcome(null)
    restoreIntermaxCopy(copy.name)
      .then(setOutcome, (failure: Error) => setOutcome({ state: "failed", message: failureMessage(failure) }))
      .finally(() => {
        setRestoring(false)
        void reload()
      })
  }

  return (
    <div role="region" aria-label="Kopie INTERMAX" className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">Stan INTERMAX sprzed każdej zmiany przez narzędzie.</p>
        {outcome === null ? null : <RestoreOutcome outcome={outcome} />}
        {copies.state === "loading" ? <Skeleton className="h-32 w-full" aria-label="Wczytywanie Kopii INTERMAX" /> : null}
        {copies.state === "failed" ? (
          <LoadFailure what="Kopii INTERMAX" message={copies.message} reload={reload} />
        ) : null}
        {copies.state === "ready" && copies.data.problem !== null ? (
          <ThreePartMessage message={copies.data.problem} kind="notice" />
        ) : null}
        {copies.state === "ready" && copies.data.problem === null && copies.data.copies.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <HistoryIcon className="size-4" aria-hidden />
            Kopia powstaje przy każdym Uporządkowaniu INTERMAX.
          </p>
        ) : null}
        {copies.state === "ready" && copies.data.copies.length > 0 ? (
          <ul aria-label="Kopie INTERMAX" className="flex flex-col gap-2">
            {copies.data.copies.map((copy) => (
              <li key={copy.name}>
                <Item variant="muted" size="sm" role="group" aria-label={`Kopia z ${dateTime(copy.taken_at)}`}>
                  <ItemContent>
                    <ItemTitle className="tabular-nums">{dateTime(copy.taken_at)}</ItemTitle>
                    <ItemDescription>{copy.before_label}</ItemDescription>
                  </ItemContent>
                  <ItemActions>
                    <Button
                      variant="outline"
                      className="h-11 px-4"
                      disabled={restoring}
                      onClick={() => setChosen(copy)}
                    >
                      <ArchiveRestoreIcon data-icon="inline-start" />
                      Przywróć
                    </Button>
                  </ItemActions>
                </Item>
              </li>
            ))}
          </ul>
        ) : null}
      <ConfirmRestoreDialog
        copy={chosen}
        onOpenChange={(open) => (open ? null : setChosen(null))}
        onConfirm={restore}
      />
    </div>
  )
}

function ConfirmRestoreDialog({
  copy,
  onOpenChange,
  onConfirm,
}: {
  copy: IntermaxCopy | null
  onOpenChange: (open: boolean) => void
  onConfirm: (copy: IntermaxCopy) => void
}) {
  // Okno zamyka się z animacją, więc pamięta ostatnią Kopię, zamiast znikać z pustą treścią.
  const [shown, setShown] = React.useState(copy)

  if (copy !== null && copy !== shown) {
    setShown(copy)
  }

  return (
    <AlertDialog open={copy !== null} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogMedia>
            <ArchiveRestoreIcon />
          </AlertDialogMedia>
          <AlertDialogTitle className="tabular-nums">
            Przywrócić kopię z {shown === null ? "" : dateTime(shown.taken_at)}?
          </AlertDialogTitle>
          <AlertDialogDescription className="tabular-nums">
            Zmiany w INTERMAX wprowadzone po {shown === null ? "" : hourMinute(shown.taken_at)} znikną.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel className="h-11">Anuluj</AlertDialogCancel>
          <AlertDialogAction
            className="h-11"
            onClick={() => {
              if (copy !== null) {
                onOpenChange(false)
                onConfirm(copy)
              }
            }}
          >
            Przywróć tę kopię
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function RestoreOutcome({ outcome }: { outcome: Outcome }) {
  switch (outcome.state) {
    case "restored":
      return (
        <div className="flex flex-col gap-2">
          <Alert>
            <CircleCheckIcon className="text-success!" />
            <AlertTitle className="tabular-nums">
              Przywrócono kopię z {dateTime(outcome.restored.taken_at)}
            </AlertTitle>
          </Alert>
          {outcome.warnings.map((warning) => (
            <ThreePartMessage key={warning.what} message={warning} kind="warning" />
          ))}
        </div>
      )
    case "refused":
      return <ThreePartMessage message={outcome.message} kind="warning" />
    case "failed":
      return (
        <Alert>
          <AlertTitle>{outcome.message}</AlertTitle>
        </Alert>
      )
    default: {
      const unhandled: never = outcome

      return unhandled
    }
  }
}
