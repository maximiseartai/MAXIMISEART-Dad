import { CircleHelpIcon, RefreshCwIcon } from "lucide-react"

import type { ListedWorker, WorkerListSetting } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useSettings } from "@/lib/settings"
import { FieldSentence, SettingsPanel } from "@/pages/settings/setting-row"

type Unresolved = WorkerListSetting["unresolved"][number]

/**
 * Lista Wykonawców (ADR 0032) tylko do odczytu: aktywni na górze, każdy z nazwą, loginami i adresami. Nad listą jednym
 * zdaniem to, czego przeniesienie starych plików nie rozstrzygnęło. Zły plik ma zdanie o problemie i ostatnią dobrą
 * listę, a bez niej samo zdanie: pusta lista znaczy tylko, że Wykonawców naprawdę nie ma.
 */
export function WorkersSection() {
  const { settings, reload } = useSettings()

  switch (settings.state) {
    case "loading":
      return <Skeleton className="h-40 w-full rounded-xl" aria-label="Wczytywanie ustawień" />
    case "failed":
      return <LoadFailure what="ustawień" message={settings.message} reload={reload} />
    case "ready":
      return <WorkerList setting={settings.data.workers} reload={reload} />
    default: {
      const unhandled: never = settings

      return unhandled
    }
  }
}

function WorkerList({ setting, reload }: { setting: WorkerListSetting; reload: () => Promise<void> }) {
  if (setting.state === "unreadable") {
    return (
      <div className="flex flex-col items-start gap-3">
        {setting.problem === null ? null : <FieldSentence>{setting.problem.message}</FieldSentence>}
        <Button variant="outline" size="sm" onClick={() => void reload()}>
          <RefreshCwIcon aria-hidden />
          Spróbuj ponownie
        </Button>
      </div>
    )
  }

  const workers = setting.workers.toSorted((first, second) => Number(second.active) - Number(first.active))

  return (
    <div className="flex flex-col gap-3">
      {setting.problem === null ? null : <FieldSentence>{setting.problem.message}</FieldSentence>}
      {setting.unresolved.length === 0 ? null : (
        <ul aria-label="Do rozstrzygnięcia" className="flex flex-col gap-1.5">
          {setting.unresolved.map((item) => (
            <li key={unresolvedKey(item)} className="flex items-start gap-2 text-sm text-pretty">
              <CircleHelpIcon className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
              <span>{unresolvedSentence(item)}</span>
            </li>
          ))}
        </ul>
      )}
      {workers.length > 0 ? (
        <SettingsPanel label="Wykonawcy">
          {workers.map((worker) => (
            <WorkerRow key={worker.logins[0]} worker={worker} />
          ))}
        </SettingsPanel>
      ) : setting.state === "good" ? (
        <p className="text-sm text-muted-foreground">Na liście nie ma jeszcze Wykonawców.</p>
      ) : null}
    </div>
  )
}

function WorkerRow({ worker }: { worker: ListedWorker }) {
  return (
    <div role="listitem" aria-label={worker.name} className="flex flex-col gap-1 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={worker.active ? "text-sm font-medium" : "text-sm font-medium text-muted-foreground"}>
          {worker.name}
        </span>
        {worker.active ? null : <Badge variant="outline">Nieaktywny</Badge>}
        {worker.active && !worker.reminders ? <Badge variant="outline">Bez przypomnień</Badge> : null}
      </div>
      <span className="text-sm break-words text-muted-foreground">
        {[...worker.logins, ...worker.addresses].join(" · ")}
      </span>
    </div>
  )
}

function unresolvedKey(item: Unresolved): string {
  return item.reason === "login_bez_wykonawcy" ? item.login : item.message
}

/** Jedno zdanie o sprawie po przeniesieniu starych plików; rozstrzyga ją tata, gdy sekcja pozwoli edytować listę. */
function unresolvedSentence(item: Unresolved): string {
  switch (item.reason) {
    case "login_bez_wykonawcy":
      return `Adresy ${item.addresses.join(", ")} należą do loginu ${item.login}, którego nie ma u żadnego Wykonawcy.`
    case "adresy_nieprzeniesione":
      return item.message
    default: {
      const unhandled: never = item

      return unhandled
    }
  }
}
