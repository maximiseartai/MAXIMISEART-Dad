import * as React from "react"
import { CircleArrowUpIcon, CircleCheckIcon, CircleDashedIcon } from "lucide-react"

import type { Configuration } from "@/api/generated"
import { ToolUpdateAfterRestart, ToolUpdateButton, ToolUpdateStatus } from "@/components/tool-update"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { fullDate } from "@/lib/format"
import { useSettings } from "@/lib/settings"
import { useToolUpdate } from "@/lib/tool-update"
import { WithConfiguration } from "@/pages/settings/configuration"
import { SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

type Freshness = Configuration["freshness"]

const FRESHNESS: Record<Freshness, { label: string; icon: React.ReactNode }> = {
  current: { label: "Aktualna", icon: <CircleCheckIcon data-icon="inline-start" className="text-success" /> },
  newer: { label: "Jest nowsza wersja", icon: <CircleArrowUpIcon data-icon="inline-start" className="text-warning" /> },
  not_checked: {
    label: "Nie sprawdzono",
    icon: <CircleDashedIcon data-icon="inline-start" className="text-muted-foreground" />,
  },
}

/**
 * Wersja narzędzia z Aktualnością i przyciskiem `Zaktualizuj narzędzie`, gdy Konfiguracja proponuje aktualizację
 * (`update_offered`: tylko przy nowszym Wydaniu, regułę ma serwer). Po aktualizacji okno czyta Konfigurację od nowa,
 * więc wersja i Aktualność pochodzą z serwera, nie z wyniku.
 */
export function ToolSection() {
  return (
    <>
      <WithConfiguration>
        {(configuration, reload) => (
          <Tool
            version={configuration.version}
            freshness={configuration.freshness}
            offered={configuration.update_offered}
            onFinished={reload}
          />
        )}
      </WithConfiguration>
      <Autostart />
    </>
  )
}

const AUTOSTART = "Uruchamiaj Centrum razem z Windows"

/**
 * Start Centrum razem z Windows: przełącznik zakłada albo usuwa skrót w folderze Autostart, a jego położenie to stan
 * skrótu z serwera. Gdy przełącznika nie da się zmienić (komputer bez Windows, folder Autostart nieczytelny), jest
 * nieaktywny, a zdanie dlaczego podaje serwer.
 */
function Autostart() {
  const { settings, switchAutostart, autostartPending } = useSettings()

  if (settings.state !== "ready") {
    return null
  }

  const { state, reason } = settings.data.autostart

  return (
    <SettingsPanel label="Start">
      <SettingRow title={AUTOSTART} description={reason ?? "Po zalogowaniu Centrum działa w tle, bez otwierania karty."}>
        <Switch
          aria-label={AUTOSTART}
          checked={autostartPending ?? state === "on"}
          disabled={reason !== null}
          onCheckedChange={switchAutostart}
        />
      </SettingRow>
    </SettingsPanel>
  )
}

function Tool({
  version,
  freshness,
  offered,
  onFinished,
}: {
  version: Configuration["version"]
  freshness: Freshness
  offered: Configuration["update_offered"]
  onFinished: () => void
}) {
  const { update } = useToolUpdate()
  const watched = React.useRef(false)

  React.useEffect(() => {
    if (update?.state === "running") {
      watched.current = true
    } else if (watched.current) {
      watched.current = false
      onFinished()
    }
  }, [update, onFinished])

  return (
    <SettingsPanel label="Narzędzie">
      <SettingRow
        title="Wersja narzędzia"
        description={<span className="tabular-nums">{versionLabel(version)}</span>}
        below={
          <>
            <ToolUpdateStatus />
            {/* Porażka ponownego startu stoi pod tytułem strony, a ta jest za oknem, gdy karta wraca na `#/ustawienia/narzedzie`. */}
            <ToolUpdateAfterRestart />
          </>
        }
      >
        <Badge variant="outline">
          {FRESHNESS[freshness].icon}
          {FRESHNESS[freshness].label}
        </Badge>
        {offered ? <ToolUpdateButton primary /> : null}
      </SettingRow>
    </SettingsPanel>
  )
}

/** `1a2b3c4 od 20.10.2026`: skrót commitu, po którym Maks znajdzie wersję, i dzień, od którego działa. */
function versionLabel(version: Configuration["version"]) {
  if (version === null) {
    return "Nieznana"
  }

  return version.since === null ? version.commit : `${version.commit} od ${fullDate(version.since)}`
}
