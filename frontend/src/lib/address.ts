import * as React from "react"

import type { ViewTiming } from "@/api/generated"

type PageId = ViewTiming["page"]

export type Href = `#/${PageId}` | `#/${PageId}/${string}`

const SETTINGS = "ustawienia" satisfies PageId

/** Dawny widok Konfiguracja: jego adres z zakładki w przeglądarce otwiera okno Ustawień. */
const OLD_CONFIGURATION = "konfiguracja"

export function href(id: PageId, ...path: ReadonlyArray<string>): Href {
  return path.length === 0 ? `#/${id}` : `#/${id}/${path.map(encodeURIComponent).join("/")}`
}

function decoded(part: string): string {
  try {
    return decodeURIComponent(part)
  } catch {
    // Adres wpisany ręcznie z pojedynczym `%`: strona dostaje człon taki, jaki jest, a serwer go odrzuci.
    return part
  }
}

export function hashParts(hash: string): ReadonlyArray<string> {
  return hash.replace(/^#\/?/, "").split("/").map(decoded)
}

function isSettings(hash: string): boolean {
  return hashParts(hash)[0] === SETTINGS
}

type Address = { page: string; settings: string | null; fromPage: boolean }

function read(previous: Address | null): Address {
  const hash = window.location.hash

  if (!isSettings(hash)) {
    return { page: hash, settings: null, fromPage: false }
  }

  return {
    page: previous?.page ?? "",
    settings: hashParts(hash)[1] ?? "",
    fromPage: previous === null ? false : previous.settings === null || previous.fromPage,
  }
}

function redirectOldConfiguration() {
  if (hashParts(window.location.hash)[0] === OLD_CONFIGURATION) {
    window.history.replaceState(null, "", href(SETTINGS))
  }
}

// Przekierowanie przed pierwszym odczytem adresu i przy każdej zmianie adresu; `replaceState` nie wywołuje
// `hashchange`, więc React czyta już adres okna.
redirectOldConfiguration()

window.addEventListener("hashchange", redirectOldConfiguration)

let seen = window.location.hash
let address = read(null)

/**
 * Adres liczony przy odczycie, gdy `location.hash` się zmienił: słuchacze `hashchange` rejestruje React, więc pomiar
 * widoku (`view-timing.ts`, słuchacz z ładowania modułu) zawsze pierwszy zapisuje start przejścia.
 */
function current(): Address {
  if (window.location.hash !== seen) {
    seen = window.location.hash
    address = read(address)
  }

  return address
}

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange)

  return () => window.removeEventListener("hashchange", onChange)
}

export function useHash(): string {
  return React.useSyncExternalStore(subscribe, () => current().page)
}

export function usePagePath(): ReadonlyArray<string> {
  const hash = useHash()

  return React.useMemo(() => hashParts(hash).slice(1), [hash])
}

export function useSettingsAddress(): string | null {
  return React.useSyncExternalStore(subscribe, () => current().settings)
}

export function settingsHref(section?: string, ...path: ReadonlyArray<string>): Href {
  return section === undefined ? href(SETTINGS) : href(SETTINGS, section, ...path)
}

function settingsHash(): string {
  return isSettings(window.location.hash) ? window.location.hash : ""
}

export function useSettingsPath(): ReadonlyArray<string> {
  const hash = React.useSyncExternalStore(subscribe, settingsHash)

  return React.useMemo(() => hashParts(hash).slice(2), [hash])
}

/** Inna sekcja w otwartym oknie: bez nowego wpisu w historii karty, więc „Wstecz” zamyka okno, a nie cofa sekcję. */
export function showSection(section: string) {
  window.location.replace(settingsHref(section))
}

export function closeSettings() {
  const { page, fromPage } = current()

  if (fromPage) {
    window.history.back()
  } else {
    window.location.replace(page === "" ? "#/" : page)
  }
}
