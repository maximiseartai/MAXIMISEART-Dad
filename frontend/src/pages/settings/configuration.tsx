import * as React from "react"

import { getConfiguration } from "@/api/centrum"
import type { Configuration } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Skeleton } from "@/components/ui/skeleton"
import { useResource, type Resource } from "@/lib/use-resource"

type ConfigurationRead = { configuration: Resource<Configuration>; reload: () => Promise<void> }

const ConfigurationContext = React.createContext<ConfigurationRead | null>(null)

export function ConfigurationProvider({ children }: { children: React.ReactNode }) {
  const { resource: configuration, reload } = useResource(getConfiguration, [])
  const value = React.useMemo(() => ({ configuration, reload }), [configuration, reload])

  return <ConfigurationContext.Provider value={value}>{children}</ConfigurationContext.Provider>
}

export function WithConfiguration({
  children,
}: {
  children: (configuration: Configuration, reload: () => Promise<void>) => React.ReactNode
}) {
  const context = React.useContext(ConfigurationContext)

  if (context === null) {
    throw new Error("WithConfiguration działa tylko wewnątrz ConfigurationProvider.")
  }

  const { configuration, reload } = context

  switch (configuration.state) {
    case "loading":
      return <Skeleton className="h-40 w-full rounded-xl" aria-label="Wczytywanie ustawień" />
    case "failed":
      return <LoadFailure what="ustawień" message={configuration.message} reload={reload} />
    case "ready":
      return children(configuration.data, reload)
    default: {
      const unhandled: never = configuration

      return unhandled
    }
  }
}
