import * as React from "react"
import { ChevronLeftIcon, ChevronRightIcon, FileSpreadsheetIcon, SendIcon } from "lucide-react"

import { previewSettlementMails } from "@/api/centrum"
import type { MailPreview } from "@/api/generated"
import { failureMessage } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { settingsHref } from "@/lib/address"
import { SETTLEMENT_MAIL_SECTION } from "@/pages/settings/settlement-mail-section"
import { settlements } from "@/pages/settlement-mailing/words"

type Previews = { state: "loading" } | { state: "ready"; mails: MailPreview[] } | { state: "failed"; message: string }

/**
 * Okno „Wysłać N rozliczeń?”: podgląd każdego maila tak, jak go dostanie Wykonawca (1 z N, poprzedni i następny), z
 * linkiem do tematu i treści w Ustawieniach. Podgląd składa serwer z bieżących Ustawień, więc okno pokazuje dokładnie
 * to, co pójdzie; „Wyślij” jest dostępne dopiero, gdy podgląd przyszedł. `again`: jeden plik zmieniony po wysłaniu idzie
 * jeszcze raz, więc okno pyta o poprawione rozliczenie.
 */
export function ConfirmMailing({
  token,
  label,
  workers,
  again = false,
  onCancel,
  onConfirm,
}: {
  token: string
  label: string
  workers: string[]
  again?: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const [previews, setPreviews] = React.useState<Previews>({ state: "loading" })
  const [shown, setShown] = React.useState(0)

  React.useEffect(() => {
    let current = true

    previewSettlementMails(token, workers).then(
      ({ mails }) => {
        if (current) {
          setPreviews({ state: "ready", mails })
        }
      },
      (failure: Error) => {
        if (current) {
          setPreviews({ state: "failed", message: failureMessage(failure) })
        }
      }
    )

    return () => {
      current = false
    }
  }, [token, workers])

  const count = previews.state === "ready" ? previews.mails.length : workers.length
  const mail = previews.state === "ready" ? previews.mails[Math.min(shown, previews.mails.length - 1)] : undefined

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onCancel())}>
      <DialogContent className="gap-5 sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{again ? "Wysłać poprawione rozliczenie?" : `Wysłać ${settlements(count)}?`}</DialogTitle>
          <p className="text-sm text-muted-foreground">
            Każdy Wykonawca dostanie osobny mail ze swoim plikiem, ze skrzynki raportów. Okres: {label}.
          </p>
        </DialogHeader>
        {previews.state === "failed" ? <p className="text-sm text-destructive">{previews.message}</p> : null}
        {previews.state === "loading" ? <Skeleton className="h-64 w-full" aria-label="Wczytywanie podglądu" /> : null}
        {mail === undefined ? null : (
          <section aria-label="Podgląd maila" className="flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span className="tabular-nums">
                Podgląd maila {Math.min(shown, count - 1) + 1} z {count}
              </span>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Poprzedni mail"
                  disabled={shown === 0}
                  onClick={() => setShown((index) => index - 1)}
                >
                  <ChevronLeftIcon />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Następny mail"
                  disabled={shown >= count - 1}
                  onClick={() => setShown((index) => index + 1)}
                >
                  <ChevronRightIcon />
                </Button>
              </div>
            </div>
            <MailCard mail={mail} />
          </section>
        )}
        <DialogFooter className="items-center sm:justify-between">
          <a
            href={settingsHref(SETTLEMENT_MAIL_SECTION)}
            className="text-sm underline underline-offset-4 hover:text-foreground"
          >
            Zmień temat i treść w Ustawieniach
          </a>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onCancel}>
              Anuluj
            </Button>
            <Button disabled={previews.state !== "ready" || count === 0} onClick={onConfirm}>
              <SendIcon data-icon="inline-start" />
              {again ? "Wyślij poprawione" : `Wyślij ${count}`}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function MailCard({ mail }: { mail: MailPreview }) {
  return (
    <div className="overflow-hidden rounded-lg border text-sm">
      <dl className="grid grid-cols-[6rem_1fr] [&>*]:border-b [&>*]:px-3 [&>*]:py-2">
        <dt className="text-muted-foreground">Do</dt>
        <dd className="min-w-0 break-words">
          {mail.worker} &lt;{mail.to.join(", ")}&gt;
        </dd>
        <dt className="text-muted-foreground">Temat</dt>
        <dd className="min-w-0 break-words">{mail.subject}</dd>
        <dt className="text-muted-foreground">Załącznik</dt>
        <dd className="min-w-0">
          <span className="inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs">
            <FileSpreadsheetIcon className="size-3.5 shrink-0 text-success" aria-hidden />
            <span className="truncate">{mail.attachment}</span>
          </span>
        </dd>
      </dl>
      <pre className="max-h-56 overflow-y-auto bg-muted/30 px-3 py-3 font-sans whitespace-pre-wrap text-pretty">
        {mail.text}
      </pre>
    </div>
  )
}
