import { CircleCheckIcon, TriangleAlertIcon } from "lucide-react"

import type { Configuration } from "@/api/generated"
import { Badge } from "@/components/ui/badge"
import { WithConfiguration } from "@/pages/settings/configuration"
import { SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

/** Czy na tym komputerze jest Token do Zgłoszeń i czy Skrzynka go przyjmuje; wartości tokenu serwer nigdy nie wysyła. */
const REPORT_KEY_LABELS: Record<Configuration["reports"], string> = {
  ready: "Gotowe",
  missing_key: "Brak tokenu",
  refused_key: "Token odrzucony",
}

/** Stan połączenia ze Skrzynką Zgłoszeń, tylko do wglądu: Token do Zgłoszeń ustawia Maks (ADR 0032). */
export function ReportsSection() {
  return (
    <WithConfiguration>
      {({ reports }) => (
        <SettingsPanel label="Zgłoszenia">
          <SettingRow title="Skrzynka Zgłoszeń" description="Połączenie ustawia Maks.">
            <Badge variant="outline">
              {reports === "ready" ? (
                <CircleCheckIcon data-icon="inline-start" className="text-success" />
              ) : (
                <TriangleAlertIcon data-icon="inline-start" className="text-warning" />
              )}
              {REPORT_KEY_LABELS[reports]}
            </Badge>
          </SettingRow>
        </SettingsPanel>
      )}
    </WithConfiguration>
  )
}
