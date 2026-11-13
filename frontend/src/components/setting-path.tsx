import type * as React from "react"
import { cn } from "cn"
import { TriangleAlertIcon } from "lucide-react"

import type { PathSetting } from "@/api/centrum"
import { buttonVariants } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { settingsHref } from "@/lib/address"
import { useSettings, type PickedPath } from "@/lib/settings"

/** Sekcja okna Ustawień, w której tata wskazuje Rejestr zleceń i folder okresów (ADR 0032: jedyne miejsce wyboru). */
export const FOLDERS_SECTION = "foldery"

/** Link do sekcji Foldery okna Ustawień, w miejscu dawnego wyboru pliku na stronie; `primary` w pustym stanie strony. */
export function SetInSettings({ className, primary = false }: { className?: string; primary?: boolean }) {
  return (
    <a
      href={settingsHref(FOLDERS_SECTION)}
      className={cn(
        buttonVariants({ variant: primary ? "default" : "link", size: "sm" }),
        primary ? null : "h-auto px-0",
        className
      )}
    >
      Ustaw w Ustawieniach
    </a>
  )
}

function PathName({ className, hint, children }: { className?: string; hint: React.ReactNode; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span tabIndex={0} className={cn(className, "rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50")} />}
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  )
}

/**
 * Plik taty w jednym wierszu z ikoną: nazwa z pełną ścieżką w podpowiedzi. Wybór jest tylko w oknie Ustawień, więc
 * plik, którego nie da się użyć (niewskazany, nie ma go, niedostępny), ma tu link „Ustaw w Ustawieniach”.
 */
export function SettingPath({ label, icon, path }: { label: string; icon: React.ReactNode; path: PickedPath }) {
  const { settings } = useSettings()
  const setting = settings.state === "ready" ? settings.data[path] : null

  if (setting === null) {
    return null
  }

  return (
    <div className="flex items-center gap-2 text-sm" role="group" aria-label={label}>
      <span className="text-muted-foreground [&_svg]:size-4" aria-hidden>
        {icon}
      </span>
      {setting.state === "not_set" || setting.state === "unreadable" ? (
        <span className="text-muted-foreground">
          {label}: {setting.state === "not_set" ? "nie wskazano" : "nie da się teraz odczytać"}
        </span>
      ) : (
        <PathName className="truncate" hint={<>{label}: {setting.path}</>}>
          {pathText(setting)}
        </PathName>
      )}
      {setting.state === "ready" ? null : <SetInSettings className="ml-auto" />}
    </div>
  )
}

type ChosenPath = Extract<PathSetting, { path: string }>

function pathText(setting: ChosenPath) {
  switch (setting.state) {
    case "missing":
      return `Nie ma już: ${setting.name}`
    case "inaccessible":
      return `Nie da się teraz odczytać: ${setting.name}`
    case "ready":
      return setting.name
    default: {
      const unhandled: never = setting

      return unhandled
    }
  }
}

/** Stan pliku taty pod jego nazwą w sekcji Foldery: nazwa, a brakujący albo niedostępny z ostrzeżeniem. */
export function PathDescription({ setting }: { setting: PathSetting }) {
  switch (setting.state) {
    case "not_set":
      return <span>Nie wskazano</span>
    case "unreadable":
      return <span>Nie da się teraz odczytać Ustawień Centrum</span>
    case "missing":
    case "inaccessible":
      return (
        <PathName
          className="inline-flex items-center gap-1.5 text-foreground"
          hint={setting.state === "missing" ? <>Brak pod ścieżką: {setting.path}</> : setting.path}
        >
          <TriangleAlertIcon className="size-4 text-warning" aria-hidden />
          {pathText(setting)}
        </PathName>
      )
    case "ready":
      return <PathName hint={setting.path}>{setting.name}</PathName>
    default: {
      const unhandled: never = setting

      return unhandled
    }
  }
}
