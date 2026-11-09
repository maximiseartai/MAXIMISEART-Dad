import * as React from "react"

import { getNotifications, markNotificationsRead, type Notifications } from "@/api/centrum"
import { showFailure } from "@/lib/action"
import { useRuns } from "@/lib/runs"
import { useResource, type Resource } from "@/lib/use-resource"

type NotificationsValue = {
  notifications: Resource<Notifications>
  /**
   * Tata zobaczył te Powiadomienia; odpowiedź serwera zastępuje listę, więc kropka na dzwonku gaśnie od razu. Odczyt
   * po niej przynosi to, co odpowiedź skrzynki mogła zmienić w międzyczasie (zastąpiony odczyt przepada).
   */
  markRead: (ids: ReadonlyArray<string>) => void
  reload: () => Promise<void>
}

const NotificationsContext = React.createContext<NotificationsValue | null>(null)

/**
 * Powiadomienia wspólne dla dzwonka w nagłówku i widoku Powiadomienia. Karta czyta je przy starcie, po powrocie
 * do karty, przy każdej zmianie strony i po końcu Uruchomienia procesu widzianego na żywo (Powiadomienie o Wycenie
 * w efenix); serwer sam decyduje, kiedy zapytać Skrzynkę Zgłoszeń (najwyżej raz na 10 minut).
 */
export function NotificationsProvider({ page, children }: { page: string; children: React.ReactNode }) {
  const { resource, reload, replace } = useResource(getNotifications, [], { fromDadFiles: false })
  const shownPage = React.useRef(page)
  const { view } = useRuns()
  const ended = view?.state === "finished" ? view.run.id : null
  const shownEnd = React.useRef(ended)

  React.useEffect(() => {
    if (shownPage.current !== page) {
      shownPage.current = page
      reload()
    }
  }, [page, reload])

  React.useEffect(() => {
    if (shownEnd.current !== ended) {
      shownEnd.current = ended

      if (ended !== null) {
        reload()
      }
    }
  }, [ended, reload])

  const markRead = React.useCallback(
    (ids: ReadonlyArray<string>) => {
      markNotificationsRead(ids).then((data) => {
        replace({ state: "ready", data })
        reload()
      }, showFailure)
    },
    [replace, reload]
  )

  const value = React.useMemo(() => ({ notifications: resource, markRead, reload }), [resource, markRead, reload])

  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
}

export function useNotifications(): NotificationsValue {
  const value = React.useContext(NotificationsContext)

  if (value === null) {
    throw new Error("useNotifications poza NotificationsProvider")
  }

  return value
}
