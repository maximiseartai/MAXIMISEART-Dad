import { FolderOpenIcon } from "lucide-react"

import { PathDescription } from "@/components/setting-path"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { LoadFailure } from "@/components/load-failure"
import { useSettings, type PickedPath } from "@/lib/settings"
import { openOrderRegisterAndConfirm } from "@/pages/periods/open-period-path"
import { SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

/**
 * Rejestr zleceń i folder okresów: jedyne miejsce, w którym tata je wskazuje (ADR 0032). „Wskaż”/„Zmień” otwiera okno
 * wyboru Windows na komputerze taty, a „Otwórz” otwiera wskazany Rejestr w Excelu.
 */
export function FoldersSection() {
  const { settings, reload } = useSettings()

  switch (settings.state) {
    case "loading":
      return <Skeleton className="h-36 w-full rounded-xl" aria-label="Wczytywanie ustawień" />
    case "failed":
      return <LoadFailure what="ustawień" message={settings.message} reload={reload} />
    case "ready":
      return (
        <SettingsPanel label="Foldery">
          <PathRow path="order_register" title="Rejestr zleceń" description="Plik INTERMAX, z którego czytają procesy." />
          <PathRow path="periods_directory" title="Folder okresów" description="Folder, w którym Centrum szuka Folderów okresu." />
        </SettingsPanel>
      )
    default: {
      const unhandled: never = settings

      return unhandled
    }
  }
}

function PathRow({ path, title, description }: { path: PickedPath; title: string; description: string }) {
  const { settings, picker, choose } = useSettings()
  const setting = settings.state === "ready" ? settings.data[path] : null

  if (setting === null) {
    return null
  }

  const verb = setting.state === "not_set" ? "Wskaż" : "Zmień"

  return (
    <SettingRow
      title={title}
      description={
        <span className="flex flex-col gap-0.5">
          <span>{description}</span>
          <span className="text-foreground">
            <PathDescription setting={setting} />
          </span>
        </span>
      }
    >
      {path === "order_register" && setting.state === "ready" ? (
        <Button variant="ghost" size="sm" aria-label="Otwórz Rejestr zleceń" onClick={openOrderRegisterAndConfirm}>
          <FolderOpenIcon data-icon="inline-start" />
          Otwórz
        </Button>
      ) : null}
      <Button variant="outline" size="sm" disabled={picker !== null} aria-label={`${verb} ${title}`} onClick={() => choose(path)}>
        {picker === path ? (
          <>
            <Spinner data-icon="inline-start" />
            Czekam na wybór…
          </>
        ) : (
          verb
        )}
      </Button>
    </SettingRow>
  )
}
