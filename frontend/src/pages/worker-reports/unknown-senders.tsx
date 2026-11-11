import { MailQuestionIcon } from "lucide-react"

import type { UnknownReportSender } from "@/api/generated"
import { Card } from "@/components/ui/card"

/** Raporty wykonawcy z dni zakresu z adresów spoza listy adresów Wykonawców, pod Mapą cieplną: adres widać tylko tutaj. */
export function UnknownSenders({ senders }: { senders: ReadonlyArray<UnknownReportSender> }) {
  if (senders.length === 0) {
    return null
  }

  return (
    <Card role="region" aria-label="Spoza listy adresów" className="gap-0 py-0">
      <ul className="flex flex-col [&>li+li]:border-t">
        {senders.map((sender) => (
          <li key={JSON.stringify([sender.day, sender.sender, sender.reason])} className="flex items-start gap-3 px-5 py-3.5 text-sm">
            <MailQuestionIcon className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="font-medium break-all">Raport spoza listy adresów · {sender.sender}</span>
              <span className="text-muted-foreground">{sender.reason}</span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}
