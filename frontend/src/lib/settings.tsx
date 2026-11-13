import * as React from "react"

import {
  changeFolders,
  changeTheme,
  chooseOrderRegister,
  choosePeriodsDirectory,
  getSettings,
  undoSettingsChange,
  type PathSetting,
  type Theme,
} from "@/api/centrum"
import { failureMessage, refusedField } from "@/api/client"
import type { Choice, FoldersChange, Settings } from "@/api/generated"
import { toast } from "@/components/ui/toast"
import { showFailure, useAction } from "@/lib/action"
import { rememberTheme, showTheme } from "@/lib/theme"
import { DadFilesVersion, useResource, type Resource } from "@/lib/use-resource"

/** Plik taty wskazywany natywnym oknem wyboru: pole Ustawień Centrum, które jest ścieżką. */
export type PickedPath = { [Key in keyof Settings]: Settings[Key] extends PathSetting ? Key : never }[keyof Settings]

/** Odmowa zapisu z polem pliku Ustawień (`rejestr_zlecen`, `folder_okresow`) i jednym zdaniem dla taty. */
export type FieldRefusal = { field: string; message: string }

type SettingsContextValue = {
  settings: Resource<Settings>
  reload: () => Promise<void>
  theme: Theme
  /** Plik, którego okno wyboru jest teraz otwarte; dopóki jest, żaden przycisk nie otwiera drugiego. */
  picker: PickedPath | null
  choose: (path: PickedPath) => void
  chooseTheme: (theme: Theme) => void
  /**
   * Zapis ścieżki wpisanej przez tatę: `true`, gdy się zapisała. Pusta czyści ustawienie, a druga ścieżka sekcji
   * Foldery zostaje bez zmiany.
   */
  typePath: (path: PickedPath, value: string) => Promise<boolean>
  /** Ostatnia odmowa zapisu Folderów z polem; jej zdanie stoi przy tym polu do następnego zapisu albo `dismiss`. */
  refusal: FieldRefusal | null
  dismiss: () => void
  /** Ustawienia po cofnięciu zmiany z Historii Ustawień. */
  undone: (choice: Choice) => void
  /** Ustawienia po zapisie sekretu (hasło skrzynki): bez „Zapisano · Cofnij”, bo sekretu nie da się cofnąć. */
  secretSaved: (choice: Choice) => void
  /** Numer przyjętych zmian Ustawień: Historia Ustawień czyta się od nowa przy każdej. */
  changes: number
}

/** Pole pliku Ustawień każdej ścieżki, jak w odmowie serwera i w `folders_problem`. */
export const PATH_FIELDS: Record<PickedPath, string> = {
  order_register: "rejestr_zlecen",
  periods_directory: "folder_okresow",
}

/** Pole motywu w pliku Ustawień, jak w `folders_problem`. */
export const THEME_FIELD = "motyw"

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

/** Tożsamość plików taty, z których serwer czyta strony; inna tożsamość to nowy odczyt stron (`DadFilesVersion`). */
function files(settings: Resource<Settings>): string | null {
  return settings.state === "ready" ? JSON.stringify([settings.data.periods_directory, settings.data.order_register]) : null
}

/** Zapamiętana ścieżka pola; niewskazana i nieczytelna to `null`. */
function remembered(setting: PathSetting): string | null {
  return "path" in setting ? setting.path : null
}

/** Ścieżka wpisana albo wklejona z Eksploratora („Kopiuj jako ścieżkę” dodaje cudzysłowy); pusta to `null`. */
function typed(value: string): string | null {
  const path = value.trim().replace(/^"(.*)"$/, "$1").trim()

  return path === "" ? null : path
}

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const { resource: settings, reload, replace } = useResource(getSettings, [], { fromDadFiles: false })
  const [firstPaintTheme] = React.useState<Theme>(currentTheme)
  const [chosenTheme, setChosenTheme] = React.useState<Theme | null>(null)
  const [filesVersion, setFilesVersion] = React.useState(0)
  const [refusal, setRefusal] = React.useState<FieldRefusal | null>(null)
  const [changes, setChanges] = React.useState(0)
  const savedTheme = settings.state === "ready" ? settings.data.theme : null
  const theme = chosenTheme ?? savedTheme ?? firstPaintTheme
  const latest = React.useRef(settings)

  React.useEffect(() => {
    latest.current = settings
  })

  React.useEffect(() => {
    if (theme !== currentTheme()) {
      applyTheme(theme)
    }
  }, [theme])

  // Jedno miejsce przyjęcia Ustawień z serwera po zapisie albo cofnięciu.
  const take = React.useCallback(
    (choice: Choice) => {
      const next: Resource<Settings> = { state: "ready", data: choice.settings }

      // Ostatnie dane stron pochodzą z poprzednich plików, więc nie mogą się pokazać jako bieżące.
      if (files(next) !== files(latest.current)) {
        setFilesVersion((version) => version + 1)
      }

      replace(next)

      if ((choice.change ?? null) !== null) {
        setChanges((count) => count + 1)
      }
    },
    [replace]
  )

  const undone = React.useCallback(
    (choice: Choice) => {
      // Cofnięty motyw pochodzi z serwera, nie z ostatniego kliknięcia.
      setChosenTheme(null)
      take(choice)
    },
    [take]
  )

  const saved = React.useCallback(
    (choice: Choice) => {
      const change = choice.change ?? null

      take(choice)

      if (change !== null) {
        announce(change, undone)
      }
    },
    [take, undone]
  )

  // Zła wartość zapisu Folderów (422 z polem) staje przy polu, a nie w powiadomieniu; inna porażka idzie dalej.
  // `true`: zapis się udał.
  const folders = React.useCallback(
    (save: () => Promise<Choice>) => {
      setRefusal(null)

      return save().then(
        (choice) => {
          saved(choice)

          return true
        },
        (failure: Error) => {
          const field = refusedField(failure)

          if (field === null) {
            throw failure
          }

          setRefusal({ field, message: failureMessage(failure) })

          return false
        }
      )
    },
    [saved]
  )

  // Jedno okno wyboru naraz, wspólne dla wszystkich stron: okno Windows pojawia się po chwili, więc drugie
  // kliknięcie (albo „Zmień” przy drugim pliku) otworzyłoby drugie okno.
  const picking = useAction(async (path: PickedPath) => {
    await folders(PICKERS[path])
  })

  // `done` dostaje wynik zapisu; akcja odrzucona jako druga naraz albo nieudana kończy się bez niego.
  const typing = useAction(async (path: PickedPath, value: string, done: (saved: boolean) => void) => {
    const current = latest.current

    if (current.state !== "ready") {
      return
    }

    const kept: FoldersChange = {
      order_register: remembered(current.data.order_register),
      periods_directory: remembered(current.data.periods_directory),
    }

    done(await folders(() => changeFolders({ ...kept, [path]: typed(value) })))
  })

  const pick = picking.run
  const type = typing.run
  const picker = picking.running?.[0] ?? null

  const value = React.useMemo<SettingsContextValue>(
    () => ({
      settings,
      reload,
      theme,
      picker,
      choose: (path) => void pick(path),
      chooseTheme: (next) => {
        setChosenTheme(next)
        changeTheme(next).then(saved, showFailure)
      },
      typePath: (path, entered) =>
        new Promise<boolean>((resolve) => {
          void type(path, entered, resolve).then(() => resolve(false))
        }),
      refusal,
      dismiss: () => setRefusal(null),
      undone,
      secretSaved: take,
      changes,
    }),
    [settings, reload, theme, picker, pick, saved, type, refusal, undone, take, changes]
  )

  return (
    <SettingsContext.Provider value={value}>
      <DadFilesVersion.Provider value={filesVersion}>{children}</DadFilesVersion.Provider>
    </SettingsContext.Provider>
  )
}

// Powiadomienie „Zapisano” ostatniej zmiany: następna zmiana je zastępuje, zamiast układać stos przy kilku kliknięciach.
let lastSaved: string | null = null

/**
 * „Zapisano · Cofnij” na chwilę po każdej zmianie Ustawień: „Cofnij” cofa ją jak wiersz Historii, a odmowa cofnięcia
 * to powiadomienie z jej zdaniem.
 */
function announce(change: string, undone: (choice: Choice) => void) {
  if (lastSaved !== null) {
    toast.close(lastSaved)
  }

  const shown = toast.add({
    title: "Zapisano",
    type: "success",
    actionProps: {
      children: "Cofnij",
      onClick: () => {
        toast.close(shown)
        undoSettingsChange(change).then(
          (choice) => {
            undone(choice)
            toast.add({ title: "Cofnięto", type: "success" })
          },
          (failure: Error) => showFailure(failure, "Nie udało się cofnąć")
        )
      },
    },
  })

  lastSaved = shown
}

export function useSettings() {
  const context = React.useContext(SettingsContext)

  if (context === null) {
    throw new Error("useSettings działa tylko wewnątrz SettingsProvider.")
  }

  return context
}
