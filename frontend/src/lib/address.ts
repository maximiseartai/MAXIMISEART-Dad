import * as React from "react"

import type { ViewTiming } from "@/api/generated"

type PageId = ViewTiming["page"]

/** Adres strony Centrum: `#/<id>`, a za nim człony strony, np. `#/uzupelnienie/<okres>`. */
export type Href = `#/${PageId}` | `#/${PageId}/${string}`

/** Okno Ustawień ma adres `#/ustawienia/<sekcja>` i otwiera się nad stroną, na której tata był (ADR 0032). */
const SETTINGS = "ustawienia" satisfies PageId

/** Dawny widok Konfiguracja: jego adres z zakładki w przeglądarce otwiera okno Ustawień. */
const OLD_CONFIGURATION = "konfiguracja"

/** Adres strony `id` z członami `path` (np. tokenem okresu); każdy człon jest kodowany osobno. */
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

/** `#/uzupelnienie/06_12_10_2026` → `["uzupelnienie", "06_12_10_2026"]` */
export function hashParts(hash: string): ReadonlyArray<string> {
  return hash.replace(/^#\/?/, "").split("/").map(decoded)
}

function isSettings(hash: string): boolean {
  return hashParts(hash)[0] === SETTINGS
}

/**
 * Adres karty rozdzielony na stronę i okno Ustawień nad nią. `page` to adres ostatniej strony tej karty (pusty przy
 * zimnym starcie na `#/ustawienia/…`: wtedy pod oknem jest strona startowa), `settings` człon sekcji albo `null`, gdy
 * okno jest zamknięte, a `fromPage` mówi, czy okno otworzyło się przejściem z tej karty (wtedy zamyka je „Wstecz”).
 */
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

/**
 * Adres strony pod spodem (`location.hash` bez okna Ustawień); zmienia się z każdym przejściem między stronami, także
 * Wstecz w przeglądarce, a otwarcie i zamknięcie okna Ustawień go nie zmienia, więc strona pod oknem zostaje.
 */
export function useHash(): string {
  return React.useSyncExternalStore(subscribe, () => current().page)
}

/** Człony adresu za identyfikatorem strony: `#/uzupelnienie/06_12_10_2026` → `["06_12_10_2026"]`. */
export function usePagePath(): ReadonlyArray<string> {
  const hash = useHash()

  return React.useMemo(() => hashParts(hash).slice(1), [hash])
}

/** Człon sekcji z adresu okna Ustawień (`""`, gdy adres jej nie ma) albo `null`, gdy okno jest zamknięte. */
export function useSettingsAddress(): string | null {
  return React.useSyncExternalStore(subscribe, () => current().settings)
}

/** Adres okna Ustawień na sekcji `section`; bez niej okno otwiera się na pierwszej sekcji. */
export function settingsHref(section?: string): Href {
  return section === undefined ? href(SETTINGS) : href(SETTINGS, section)
}

/** Inna sekcja w otwartym oknie: bez nowego wpisu w historii karty, więc „Wstecz” zamyka okno, a nie cofa sekcję. */
export function showSection(section: string) {
  window.location.replace(settingsHref(section))
}

/** Zamyka okno Ustawień i zostawia stronę pod spodem: „Wstecz”, gdy okno otwarto z tej karty, inaczej adres tej strony. */
export function closeSettings() {
  const { page, fromPage } = current()

  if (fromPage) {
    window.history.back()
  } else {
    window.location.replace(page === "" ? "#/" : page)
  }
}
