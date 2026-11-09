import * as React from "react"

import { takeRequestsSince } from "@/api/client"
import { recordViewTiming } from "@/api/centrum"
import type { ViewTiming } from "@/api/generated"
import { zViewTiming } from "@/api/generated/zod.gen"
import type { Page } from "@/pages"

type ViewStart = { kind: ViewTiming["kind"]; at: number }

// Zimny start liczy się od początku ładowania karty, przejście w menu od zmiany adresu `#/<id>`.
let viewStart: ViewStart = { kind: "cold_start", at: 0 }

window.addEventListener("hashchange", () => {
  viewStart = { kind: "navigation", at: performance.now() }
})

const LOADING = "[data-slot=skeleton], [aria-busy=true]"

/**
 * Czas, przez który szkielet był widoczny. Szkielet jest w DOM od pierwszego renderu, ale pokazuje się
 * dopiero, gdy zaczyna się jego animacja (index.css opóźnia ją o ok. 120 ms), więc widoczny jest od
 * pierwszego `animationstart` elementu odczytu do chwili, gdy żadnego takiego elementu już nie ma.
 */
function visibleSkeleton() {
  const shown = new Set<Element>()
  let since: number | null = null
  let total = 0

  const track = (now: number) => {
    for (const element of shown) {
      if (!element.isConnected || !element.matches(LOADING)) {
        shown.delete(element)
      }
    }

    if (shown.size > 0 && since === null) {
      since = now
    } else if (shown.size === 0 && since !== null) {
      total += now - since
      since = null
    }
  }

  const reveal = (event: AnimationEvent) => {
    if (event.target instanceof Element && event.target.matches(LOADING)) {
      shown.add(event.target)
      track(performance.now())
    }
  }

  document.addEventListener("animationstart", reveal, true)

  return {
    track,
    ms: (now: number) => Math.round(total + (since === null ? 0 : now - since)),
    stop: () => document.removeEventListener("animationstart", reveal, true),
  }
}

function isReady(page: Page): boolean {
  return document.querySelector(`h1[data-page="${page.id}"]`) !== null && document.querySelector(LOADING) === null
}

// Chromium podaje FCP dopiero po wyświetleniu klatki, czasem później niż gotowa treść.
const FCP_WAIT_MS = 2000

/** FCP karty w milisekundach od początku ładowania; `null`, gdy przeglądarka go nie poda. */
function firstContentfulPaint(): Promise<number | null> {
  return new Promise((resolve) => {
    const observer = new PerformanceObserver((entries) => {
      const paint = entries.getEntriesByName("first-contentful-paint")[0]

      if (paint !== undefined) {
        observer.disconnect()
        resolve(Math.round(paint.startTime))
      }
    })

    observer.observe({ type: "paint", buffered: true })
    setTimeout(() => {
      observer.disconnect()
      resolve(null)
    }, FCP_WAIT_MS)
  })
}

/**
 * Po cichu mierzy każdy gotowy widok (zimny start strony, przejście w menu) i wysyła pomiar do
 * dziennika Centrum: czas do gotowej treści, FCP przy zimnym starcie, czas widocznego szkieletu i zapytania API
 * z czasem serwera. Pomiar niczego nie pokazuje tacie; pomiar, którego kontrakt nie przyjmie, przepada.
 */
export function useViewTiming(page: Page) {
  React.useEffect(() => {
    const start = viewStart
    const skeleton = visibleSkeleton()
    let sent = false

    const measure = () => {
      const now = performance.now()

      skeleton.track(now)

      if (sent || !isReady(page)) {
        return
      }

      sent = true
      observer.disconnect()
      skeleton.stop()

      const skeletonMs = skeleton.ms(now)

      const requests = takeRequestsSince(start.at, now)
      const fcp = start.kind === "cold_start" ? firstContentfulPaint() : Promise.resolve(null)

      void fcp.then((fcpMs) => {
        const timing = zViewTiming.safeParse({
          kind: start.kind,
          page: page.id,
          ready_ms: Math.round(now - start.at),
          fcp_ms: fcpMs,
          skeleton_ms: skeletonMs,
          requests: requests.map(({ operation, browser_ms, server_ms }) => ({ operation, browser_ms, server_ms })),
        })

        if (timing.success && document.visibilityState === "visible") {
          recordViewTiming(timing.data)
        }
      })
    }

    const observer = new MutationObserver(measure)

    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributeFilter: ["aria-busy", "data-slot"],
    })
    measure()

    return () => {
      observer.disconnect()
      skeleton.stop()
    }
  }, [page])
}
