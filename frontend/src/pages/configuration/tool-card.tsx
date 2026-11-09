import * as React from "react"
import { CircleArrowUpIcon, CircleCheckIcon, CircleDashedIcon } from "lucide-react"

import type { Configuration } from "@/api/generated"
import { ToolUpdateButton, ToolUpdateStatus } from "@/components/tool-update"
import { Badge } from "@/components/ui/badge"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { fullDate } from "@/lib/format"
import { useToolUpdate } from "@/lib/tool-update"

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
 * (`offered`: tylko przy nowszym Wydaniu, regułę ma serwer). Po aktualizacji strona czyta Konfigurację od nowa
 * (`onFinished`), więc wersja i Aktualność pochodzą z serwera, nie z wyniku.
 */
export function ToolCard({
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
    <Card role="region" aria-labelledby="narzedzie" className="@4xl/main:col-span-2">
      <CardHeader>
        <CardTitle id="narzedzie">Narzędzie</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-x-2 gap-y-1 tabular-nums">
          <span>{versionLabel(version)}</span>
          <Badge variant="outline" className="ml-1">
            {FRESHNESS[freshness].icon}
            {FRESHNESS[freshness].label}
          </Badge>
        </CardDescription>
        {offered ? (
          <CardAction>
            <ToolUpdateButton primary />
          </CardAction>
        ) : null}
      </CardHeader>
      {/* Bez stanu aktualizacji (np. przed kliknięciem) karta nie ma treści pod nagłówkiem. */}
      <CardContent className="empty:hidden">
        <ToolUpdateStatus />
      </CardContent>
    </Card>
  )
}

/** `Wersja 1a2b3c4 od 20.10.2026`: skrót commitu, po którym Maks znajdzie wersję, i dzień, od którego działa. */
function versionLabel(version: Configuration["version"]) {
  if (version === null) {
    return "Wersja nieznana"
  }

  return version.since === null ? `Wersja ${version.commit}` : `Wersja ${version.commit} od ${fullDate(version.since)}`
}
