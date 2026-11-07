import type * as React from "react"
import { cn } from "cn"
import { TriangleAlertIcon } from "lucide-react"

import type { PathSetting } from "@/api/centrum"
import { Button } from "@/components/ui/button"
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item"
import { Spinner } from "@/components/ui/spinner"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useSettings, type PickedPath } from "@/lib/settings"

/**
 * Plik taty z Ustawień taty i jego okno wyboru. Niewskazany plik się „Wskaż”, wskazany „Zmień”; dopóki jakieś okno
 * wyboru jest otwarte, żaden przycisk nie otwiera drugiego.
 */
function useSettingPath(path: PickedPath) {
  const { settings, picker, choose } = useSettings()
  const setting = settings.state === "ready" ? settings.data[path] : null

  return {
    setting,
    verb: setting?.state === "not_set" ? "Wskaż" : "Zmień",
    choosing: picker === path,
    busy: picker !== null,
    choose: () => choose(path),
  }
}

/** Napis przycisku, który otwiera okno wyboru; dopóki to okno jest otwarte, przycisk na nie czeka. */
export function ChoosingLabel({ choosing, children }: { choosing: boolean; children: React.ReactNode }) {
  return choosing ? (
    <>
      <Spinner data-icon="inline-start" />
      Czekam na wybór…
    </>
  ) : (
    children
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

/** Plik taty w jednym wierszu z ikoną: nazwa, pełna ścieżka w podpowiedzi i „Wskaż”/„Zmień” jako link po prawej. */
export function SettingPath({ label, icon, path }: { label: string; icon: React.ReactNode; path: PickedPath }) {
  const { setting, verb, busy, choose } = useSettingPath(path)

  if (setting === null) {
    return null
  }

  return (
    <div className="flex items-center gap-2 text-sm" role="group" aria-label={label}>
      <span className="text-muted-foreground [&_svg]:size-4" aria-hidden>
        {icon}
      </span>
      {setting.state === "not_set" ? (
        <span className="text-muted-foreground">{label}: nie wskazano</span>
      ) : (
        <PathName className="truncate" hint={<>{label}: {setting.path}</>}>
          {setting.state === "missing" ? `Nie ma już: ${setting.name}` : setting.name}
        </PathName>
      )}
      <Button
        variant="link"
        size="sm"
        className="ml-auto h-auto px-0"
        disabled={busy}
        aria-label={`${verb} ${label}`}
        onClick={choose}
      >
        {verb}
      </Button>
    </div>
  )
}

/** Plik taty w Ustawieniach: tytuł, nazwa pod nim (brakujący z ostrzeżeniem) i „Wskaż”/„Zmień” jako przycisk. */
export function SettingPathItem({ label, icon, path }: { label: string; icon: React.ReactNode; path: PickedPath }) {
  const { setting, verb, choosing, busy, choose } = useSettingPath(path)

  if (setting === null) {
    return null
  }

  return (
    <Item size="sm" role="group" aria-label={label}>
      <ItemMedia variant="icon" className="text-muted-foreground">
        {icon}
      </ItemMedia>
      <ItemContent>
        <ItemTitle>{label}</ItemTitle>
        <ItemDescription>
          <PathDescription setting={setting} />
        </ItemDescription>
      </ItemContent>
      <ItemActions>
        <Button variant="outline" size="sm" disabled={busy} aria-label={`${verb} ${label}`} onClick={choose}>
          <ChoosingLabel choosing={choosing}>{verb}</ChoosingLabel>
        </Button>
      </ItemActions>
    </Item>
  )
}

function PathDescription({ setting }: { setting: PathSetting }) {
  switch (setting.state) {
    case "not_set":
      return <span>Nie wskazano</span>
    case "missing":
      return (
        <PathName className="inline-flex items-center gap-1.5 text-foreground" hint={<>Brak pod ścieżką: {setting.path}</>}>
          <TriangleAlertIcon className="size-4 text-warning" aria-hidden />
          Nie ma już: {setting.name}
        </PathName>
      )
    case "ready":
      return (
        <PathName hint={setting.path}>{setting.name}</PathName>
      )
    default: {
      const unhandled: never = setting

      return unhandled
    }
  }
}
