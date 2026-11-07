import * as React from "react"
import { PowerIcon, PowerOffIcon } from "lucide-react"

import { closeCentrum } from "@/api/centrum"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar"
import { Spinner } from "@/components/ui/spinner"
import { showFailure } from "@/lib/action"

const BACK_WITH_SHORTCUT = "Wrócisz skrótem „Centrum rozliczeń” na pulpicie."

/** Okno potwierdzenia: zamknięte, otwarte albo czekające na odpowiedź serwera (wtedy nie da się go zamknąć). */
type Dialog = "closed" | "confirming" | "closing"

/**
 * „Zamknij Centrum rozliczeń” w stopce menu. Zamknięcie karty nie wyłącza serwera, robi to tylko ten przycisk.
 * Odmowa serwera (np. w trakcie Uruchomienia procesu) wraca jako powiadomienie z jego komunikatem.
 */
export function CloseCentrumButton({ onClosed }: { onClosed: () => void }) {
  const [dialog, setDialog] = React.useState<Dialog>("closed")
  const closing = dialog === "closing"

  function close() {
    setDialog("closing")
    closeCentrum().then(onClosed, (failure: Error) => {
      setDialog("closed")
      showFailure(failure, "Nie zamknięto Centrum rozliczeń")
    })
  }

  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton tooltip="Zamknij Centrum rozliczeń" onClick={() => setDialog("confirming")}>
            <PowerIcon />
            <span>Zamknij Centrum rozliczeń</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
      <AlertDialog
        open={dialog !== "closed"}
        onOpenChange={(next) => {
          if (!closing) {
            setDialog(next ? "confirming" : "closed")
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Zamknąć Centrum rozliczeń?</AlertDialogTitle>
            <AlertDialogDescription>{BACK_WITH_SHORTCUT}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={closing}>Anuluj</AlertDialogCancel>
            <AlertDialogAction disabled={closing} onClick={close}>
              {closing ? <Spinner data-icon="inline-start" /> : null}
              Zamknij Centrum
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

/** Ekran po zamknięciu: serwer już nie działa, więc karta nie ma czego odświeżać. */
export function CentrumClosed() {
  return (
    <main className="wejscie flex min-h-svh items-center justify-center p-6">
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <PowerOffIcon />
          </EmptyMedia>
          <EmptyTitle>
            <h1>Centrum rozliczeń jest zamknięte</h1>
          </EmptyTitle>
          <EmptyDescription>Możesz zamknąć tę kartę. {BACK_WITH_SHORTCUT}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    </main>
  )
}
