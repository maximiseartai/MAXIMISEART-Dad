import * as React from "react"

import {
  changeTheme,
  chooseOrderRegister,
  choosePeriodsDirectory,
  getSettings,
  type Choice,
  type PathSetting,
  type Settings,
  type Theme,
} from "@/api/centrum"
import { showFailure, useAction } from "@/lib/action"
import { rememberTheme, showTheme } from "@/lib/theme"
import { DadFilesVersion, useResource, type Resource } from "@/lib/use-resource"

/** Plik taty wskazywany natywnym oknem wyboru: pole Ustawień taty, które jest ścieżką. */
export type PickedPath = { [Key in keyof Settings]: Settings[Key] extends PathSetting ? Key : never }[keyof Settings]

type SettingsContextValue = {
  settings: Resource<Settings>
  /** Odczyt Ustawień taty od nowa, np. po „Spróbuj ponownie”. */
  reload: () => Promise<void>
  theme: Theme
  /** Plik, którego okno wyboru jest teraz otwarte; dopóki jest, żaden przycisk nie otwiera drugiego. */
  picker: PickedPath | null
  choose: (path: PickedPath) => void
  toggleTheme: () => void
}

const PICKERS: Record<PickedPath, () => Promise<Choice>> = {
  order_register: chooseOrderRegister,
  periods_directory: choosePeriodsDirectory,
}

const SettingsContext = React.createContext<SettingsContextValue | null>(null)

function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light"
}

/** Zmiana motywu jest natychmiastowa: przejścia są wyłączone na jedną klatkę, żeby nic nie mrugało. */
function applyTheme(theme: Theme) {
  const root = document.documentElement
  const freeze = document.createElement("style")

  freeze.textContent = "*,*::before,*::after{transition:none!important}"
  document.head.append(freeze)
  showTheme(theme)
  rememberTheme(theme)
  window.getComputedStyle(root).getPropertyValue("color")
  requestAnimationFrame(() => requestAnimationFrame(() => freeze.remove()))
}

/**
 * Tożsamość plików taty, z których serwer czyta strony: folder okresów i Rejestr zleceń, bez motywu.
 * Inna tożsamość to nowy odczyt stron; zmiana motywu niczego nie czyta ponownie.
 */
function files(settings: Resource<Settings>): string | null {
  return settings.state === "ready" ? JSON.stringify([settings.data.periods_directory, settings.data.order_register]) : null
}

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const { resource: settings, reload, replace } = useResource(getSettings, [], { fromDadFiles: false })
  const [firstPaintTheme] = React.useState<Theme>(currentTheme)
  const [chosenTheme, setChosenTheme] = React.useState<Theme | null>(null)
  const [filesVersion, setFilesVersion] = React.useState(0)
  const savedTheme = settings.state === "ready" ? settings.data.theme : null
  const theme = chosenTheme ?? savedTheme ?? firstPaintTheme

  React.useEffect(() => {
    if (theme !== currentTheme()) {
      applyTheme(theme)
    }
  }, [theme])

  // Jedno okno wyboru naraz, wspólne dla wszystkich stron: okno Windows pojawia się po chwili, więc drugie
  // kliknięcie (albo „Zmień” przy drugim pliku) otworzyłoby drugie okno.
  const picking = useAction((path: PickedPath) =>
    PICKERS[path]().then((choice) => {
      const chosen: Resource<Settings> = { state: "ready", data: choice.settings }

      // Ostatnie dane stron pochodzą z poprzednich plików, więc nie mogą się pokazać jako bieżące.
      if (files(chosen) !== files(settings)) {
        setFilesVersion((version) => version + 1)
      }

      replace(chosen)
    })
  )

  const pick = picking.run
  const picker = picking.running?.[0] ?? null

  const value = React.useMemo<SettingsContextValue>(
    () => ({
      settings,
      reload,
      theme,
      picker,
      choose: (path) => void pick(path),
      toggleTheme: () => {
        const next = theme === "dark" ? "light" : "dark"

        setChosenTheme(next)
        changeTheme(next).then((saved) => replace({ state: "ready", data: saved }), showFailure)
      },
    }),
    [settings, reload, theme, picker, pick, replace]
  )

  return (
    <SettingsContext.Provider value={value}>
      <DadFilesVersion.Provider value={filesVersion}>{children}</DadFilesVersion.Provider>
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  const context = React.useContext(SettingsContext)

  if (context === null) {
    throw new Error("useSettings działa tylko wewnątrz SettingsProvider.")
  }

  return context
}
