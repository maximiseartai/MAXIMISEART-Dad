import { CircleCheckIcon, CircleDashedIcon, FileSpreadsheetIcon } from "lucide-react"

import type { PeriodRow } from "@/api/generated"
import { Badge } from "@/components/ui/badge"

// Status okresu zawsze z ikoną i nazwą z serwera, nigdy samym kolorem.
export function PeriodStatusBadge({ period }: { period: PeriodRow }) {
  switch (period.status) {
    case "worker_settlements_ready":
      return (
        <Badge variant="secondary">
          <CircleCheckIcon data-icon="inline-start" className="text-success" />
          {period.status_label}
        </Badge>
      )
    case "collective_file_prepared":
      return (
        <Badge variant="outline">
          <FileSpreadsheetIcon data-icon="inline-start" className="text-warning" />
          {period.status_label}
        </Badge>
      )
    case "no_period_files":
      return (
        <Badge variant="outline">
          <CircleDashedIcon data-icon="inline-start" />
          {period.status_label}
        </Badge>
      )
    default: {
      const unhandled: never = period.status

      return unhandled
    }
  }
}
