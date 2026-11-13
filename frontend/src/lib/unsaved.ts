import * as React from "react"

// Formularze z niezapisaną zmianą, które są teraz na stronie; okno Ustawień pyta o nie przed zamknięciem (US 15).
const unsaved = new Set<symbol>()

/** Czy któryś formularz na stronie ma zmianę, której tata nie zapisał. */
export function hasUnsavedForm(): boolean {
  return unsaved.size > 0
}

function warnOnLeave(event: BeforeUnloadEvent) {
  event.preventDefault()
}

/**
 * Formularz z przyciskiem „Zapisz” mówi, że ma niezapisaną zmianę (`dirty`): okno Ustawień pyta wtedy przed zamknięciem
 * i zmianą sekcji, a przeglądarka przed zamknięciem karty.
 */
export function useUnsavedForm(dirty: boolean) {
  React.useEffect(() => {
    if (!dirty) {
      return
    }

    const form = Symbol("formularz")

    unsaved.add(form)
    window.addEventListener("beforeunload", warnOnLeave)

    return () => {
      unsaved.delete(form)

      if (unsaved.size === 0) {
        window.removeEventListener("beforeunload", warnOnLeave)
      }
    }
  }, [dirty])
}
