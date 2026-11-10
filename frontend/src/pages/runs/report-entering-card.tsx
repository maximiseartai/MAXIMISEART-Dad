import { MailCheckIcon } from "lucide-react"

import { getReportEnteringSetup } from "@/api/centrum"
import { ReportsLink } from "@/pages/worker-reports/reports-link"
import { OutsidePeriodCard } from "@/pages/runs/outside-period-card"

/**
 * Karta „Wpisz raporty z maili” poza okresami (ADR 0028): Raporty wykonawców ze skrzynki raportów trafiają do pustych
 * komórek INTERMAX z Ustawień taty. Obok przycisku stoi link do widoku Raporty z wynikiem ostatniego kliknięcia.
 */
export function ReportEnteringCard() {
  return (
    <OutsidePeriodCard
      read={getReportEnteringSetup}
      what="Wpisania raportów"
      label="Wpisz raporty z maili"
      description="Tak/nie i czynności z maili Wykonawców do pustych komórek."
      icon={<MailCheckIcon data-icon="inline-start" />}
      request={{ process: "report_entering" }}
      skeleton="h-40"
      aside={<ReportsLink variant="outline" />}
      lastDetail={(last) => {
        const entered = last.result.summary?.figures[0]

        return entered === undefined ? undefined : `${entered.label} ${entered.value}`
      }}
    />
  )
}
