import * as React from "react"
import { ClockIcon, RotateCcwIcon, SendIcon } from "lucide-react"

import type { ReportDraft, RunOutcome } from "@/api/generated"
import { CaseStateLine } from "@/components/case-state"
import { Disclosure } from "@/components/disclosure"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { ThreePartMessage } from "@/components/three-part-message"
import { useAction } from "@/lib/action"

type ReportState = NonNullable<RunOutcome["report"]>

/**
 * Zgłoszenie do Maksa (przy Zatrzymaniu albo nieudanej Aktualizacji narzędzia). Stan liczy serwer, a `send` prosi go
 * o wysyłkę; `draft` przy Zatrzymaniu jest dopiero po Diagnozie, więc przed nią widać tylko stan.
 */
export function ReportToMaks({
  send: sendReport,
  report,
  draft,
  primary,
}: {
  send: () => Promise<ReportState>
  report: ReportState
  draft: ReportDraft | null
  /** „Wyślij do Maksa” jest głównym przyciskiem, gdy przyczynę usuwa Maks. */
  primary: boolean
}) {
  // Odpowiedź na kliknięcie ważna tylko do następnego stanu od serwera: kolejka może potem wysłać Zgłoszenie sama.
  const [answer, setAnswer] = React.useState<{ to: ReportState; state: ReportState } | null>(null)
  const state = answer !== null && answer.to === report ? answer.state : report

  const sendAction = useAction(() => sendReport().then((answered) => setAnswer({ to: report, state: answered })))
  const sending = sendAction.running !== null
  const send = () => void sendAction.run()

  if (state.state === "sent") {
    return <CaseStateLine role="status" className="wejscie" state={state} kind="zgloszenie" />
  }

  if (state.state === "waiting") {
    return (
      <p role="status" className="wejscie flex items-center gap-2 text-sm">
        <ClockIcon className="size-4 text-muted-foreground" aria-hidden />
        Zgłoszenie tego problemu już jest wysłane i czeka na naprawę.
      </p>
    )
  }

  if (state.state === "queued" || state.state === "rejected") {
    return (
      <div className="flex flex-col items-start gap-1">
        <CaseStateLine role="status" className="wejscie" state={state} kind="zgloszenie" />
        {draft === null ? null : <Preview draft={draft} />}
      </div>
    )
  }

  if (state.state === "not_queued") {
    return (
      <div className="flex flex-col gap-2">
        <ThreePartMessage
          message={state.message}
          kind="warning"
          action={
            <Button size="sm" variant="outline" onClick={send} disabled={sending}>
              {sending ? <Spinner data-icon="inline-start" /> : <RotateCcwIcon data-icon="inline-start" />}
              Spróbuj ponownie
            </Button>
          }
        />
        {draft === null ? null : <Preview draft={draft} />}
      </div>
    )
  }

  if (draft === null) {
    return null
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button size="sm" variant={primary ? "default" : "outline"} onClick={send} disabled={sending}>
        {sending ? <Spinner data-icon="inline-start" /> : <SendIcon data-icon="inline-start" />}
        Wyślij do Maksa
      </Button>
      <Preview draft={draft} />
    </div>
  )
}

/** Dokładna treść Zgłoszenia, zwinięta: tata widzi przed wysłaniem, co dostanie Maks. */
function Preview({ draft }: { draft: ReportDraft }) {
  return (
    <Disclosure label="Co zostanie wysłane" className="w-full">
      <figure aria-label="Treść Zgłoszenia" className="mt-1 rounded-md border bg-muted/40 p-3 text-xs">
        <figcaption className="mb-2 font-medium">{draft.title}</figcaption>
        <pre className="max-h-80 overflow-auto font-mono whitespace-pre-wrap text-muted-foreground">{draft.body}</pre>
      </figure>
    </Disclosure>
  )
}
