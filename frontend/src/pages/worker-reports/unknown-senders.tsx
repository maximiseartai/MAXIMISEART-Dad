import { CircleCheckIcon, MailQuestionIcon } from "lucide-react"

import type { UnknownReportSender } from "@/api/generated"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { assignHref } from "@/pages/settings/workers-section"

/**
 * Raporty wykonawcy z dni zakresu z adresów spoza listy adresów Wykonawców, pod Mapą cieplną: adres widać tylko tutaj.
 * „Przypisz do Wykonawcy…” otwiera okno Ustawień na sekcji Wykonawcy z wyborem Wykonawcy dla tego adresu; adres, który
 * tata już przypisał, ma login Wykonawcy, a jego raport wpisze następne kliknięcie.
 */
export function UnknownSenders({ senders }: { senders: ReadonlyArray<UnknownReportSender> }) {
  if (senders.length === 0) {
    return null
  }

  return (
    <Card role="region" aria-label="Spoza listy adresów" className="gap-0 py-0">
      <ul className="flex flex-col [&>li+li]:border-t">
        {senders.map((sender) => (
          <li
            key={JSON.stringify([sender.day, sender.sender, sender.reason])}
            className="flex flex-wrap items-start gap-x-3 gap-y-2 px-5 py-3.5 text-sm"
          >
            {sender.worker === null ? (
              <MailQuestionIcon className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
            ) : (
              <CircleCheckIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
            )}
            <span className="flex min-w-0 flex-1 basis-56 flex-col gap-0.5">
              <span className="font-medium break-all">Raport spoza listy adresów · {sender.sender}</span>
              <span className="text-muted-foreground">
                {sender.worker === null
                  ? sender.reason
                  : `Przypisany do ${sender.worker}. Raport wpisze się przy następnym kliknięciu „Wpisz raporty z maili”.`}
              </span>
            </span>
            {sender.worker === null ? (
              <Button variant="outline" size="sm" nativeButton={false} render={<a href={assignHref(sender.sender)} />}>
                Przypisz do Wykonawcy…
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  )
}
