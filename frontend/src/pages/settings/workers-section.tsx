import { UserIcon } from "lucide-react"

import { ThreePartMessage } from "@/components/three-part-message"
import { WithConfiguration } from "@/pages/settings/configuration"

/** Wykonawcy z Konfiguracji wykonawców, w jej kolejności; zły plik zastępuje listę Komunikatem. */
export function WorkersSection() {
  return (
    <WithConfiguration>
      {({ workers }) =>
        workers.state === "ready" ? (
          <ul aria-label="Wykonawcy" className="flex flex-col divide-y overflow-hidden rounded-xl border bg-card">
            {workers.names.map((name) => (
              <li key={name} className="flex items-center gap-3 px-4 py-3 text-sm">
                <UserIcon className="size-4 text-muted-foreground" aria-hidden />
                {name}
              </li>
            ))}
          </ul>
        ) : (
          <ThreePartMessage message={workers.message} kind="stop" />
        )
      }
    </WithConfiguration>
  )
}
