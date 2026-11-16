import type * as React from "react"

import { LoadFailure } from "@/components/load-failure"
import { Skeleton } from "@/components/ui/skeleton"
import { useReloadOnChange } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"

/**
 * Sekcja Ustawień z odczytem z serwera: szkielet w czasie odczytu, Komunikat z „Spróbuj ponownie” po nieudanym, potem
 * treść. Każda przyjęta zmiana Ustawień (także „Cofnij” w powiadomieniu i w Historii) czyta od nowa, bez szkieletu;
 * `saved` pokazuje od razu dane z odpowiedzi zapisu. `what` to dopełniacz w Komunikacie i w etykiecie szkieletu.
 */
export function WithSettingsRead<T>({
  read,
  what,
  children,
}: {
  read: () => Promise<T>
  what: string
  children: (data: T, saved: (data: T) => void) => React.ReactNode
}) {
  const { resource, reload, replace } = useResource(read, [], { fromDadFiles: false })

  useReloadOnChange(reload)

  switch (resource.state) {
    case "loading":
      return <Skeleton className="h-40 w-full rounded-xl" aria-label={`Wczytywanie ${what}`} />
    case "failed":
      return <LoadFailure what={what} message={resource.message} reload={reload} />
    case "ready":
      return children(resource.data, (data) => replace({ state: "ready", data }))
    default: {
      const unhandled: never = resource

      return unhandled
    }
  }
}
