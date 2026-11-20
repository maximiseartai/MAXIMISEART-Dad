import * as React from "react"

const unsaved = new Set<symbol>()

export function hasUnsavedForm(): boolean {
  return unsaved.size > 0
}

function warnOnLeave(event: BeforeUnloadEvent) {
  event.preventDefault()
}

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
