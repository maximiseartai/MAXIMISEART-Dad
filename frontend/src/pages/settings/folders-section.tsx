import * as React from "react"
import { FolderOpenIcon } from "lucide-react"

import { PathDescription } from "@/components/setting-path"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { LoadFailure } from "@/components/load-failure"
import { PATH_FIELDS, THEME_FIELD, useSettings, type PickedPath } from "@/lib/settings"
import { openOrderRegisterAndConfirm } from "@/pages/periods/open-period-path"
import { FieldSentence, SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

/** Pola pliku Ustawień, których zdanie stoi pod własnym wierszem: obie ścieżki tu, motyw w sekcji Wygląd. */
const ROW_FIELDS = new Set([...Object.values(PATH_FIELDS), THEME_FIELD])

/**
 * Rejestr zleceń i folder okresów: jedyne miejsce, w którym tata je wskazuje (ADR 0032). „Wskaż”/„Zmień” otwiera okno
 * wyboru Windows na komputerze taty, „Wpisz” przyjmuje ścieżkę wklejoną z Eksploratora, a „Otwórz” otwiera wskazany
 * Rejestr w Excelu. Zła wartość nie zapisuje się, a jej zdanie stoi pod polem; zły plik Ustawień też.
 */
export function FoldersSection() {
  const { settings, reload } = useSettings()

  switch (settings.state) {
    case "loading":
      return <Skeleton className="h-36 w-full rounded-xl" aria-label="Wczytywanie ustawień" />
    case "failed":
      return <LoadFailure what="ustawień" message={settings.message} reload={reload} />
    case "ready": {
      const problem = settings.data.folders_problem
      // Złe ustawienie pola tej sekcji stoi pod jego wierszem, a motyw w sekcji Wygląd; reszta pliku (cały plik,
      // nieznane pole) nad listą.
      const general = problem !== null && !ROW_FIELDS.has(problem.field ?? "") ? problem.message : null

      return (
        <>
          {general === null ? null : <FieldSentence>{general}</FieldSentence>}
          <SettingsPanel label="Foldery">
            <PathRow path="order_register" title="Rejestr zleceń" description="Plik INTERMAX, z którego czytają procesy." />
            <PathRow path="periods_directory" title="Folder okresów" description="Folder, w którym Centrum szuka Folderów okresu." />
          </SettingsPanel>
        </>
      )
    }

    default: {
      const unhandled: never = settings

      return unhandled
    }
  }
}

function PathRow({ path, title, description }: { path: PickedPath; title: string; description: string }) {
  const { settings, picker, choose, refusal } = useSettings()
  const [typing, setTyping] = React.useState(false)
  const setting = settings.state === "ready" ? settings.data[path] : null

  if (setting === null || settings.state !== "ready") {
    return null
  }

  const field = PATH_FIELDS[path]
  const problem = settings.data.folders_problem
  const refused = refusal?.field === field ? refusal.message : null
  const bad = problem?.field === field ? problem.message : null
  const verb = setting.state === "not_set" ? "Wskaż" : "Zmień"
  const sentenceId = `${field}-zdanie`

  return (
    <SettingRow
      title={title}
      description={
        <span className="flex flex-col gap-0.5">
          <span>{description}</span>
          <span className="text-foreground">
            <PathDescription setting={setting} />
            {/* Korzeń układu folderów taty: Centrum widzi z niego Foldery okresu wszystkich lat (ADR 0032). */}
            {path === "periods_directory" && setting.state === "ready" && settings.data.periods_all_years ? (
              <span className="text-muted-foreground"> – wszystkie lata</span>
            ) : null}
          </span>
        </span>
      }
      below={
        typing || refused !== null || bad !== null ? (
          <>
            {typing ? (
              <TypedPath
                path={path}
                title={title}
                initial={"path" in setting ? setting.path : ""}
                invalid={refused === null ? undefined : sentenceId}
                onDone={() => setTyping(false)}
              />
            ) : null}
            {refused === null ? null : <FieldSentence id={sentenceId}>{refused}</FieldSentence>}
            {bad === null ? null : <FieldSentence>{bad}</FieldSentence>}
          </>
        ) : null
      }
    >
      {path === "order_register" && setting.state === "ready" ? (
        <Button variant="ghost" size="sm" aria-label="Otwórz Rejestr zleceń" onClick={openOrderRegisterAndConfirm}>
          <FolderOpenIcon data-icon="inline-start" />
          Otwórz
        </Button>
      ) : null}
      {typing || setting.state === "unreadable" ? null : (
        <Button variant="ghost" size="sm" aria-label={`Wpisz ${title}`} onClick={() => setTyping(true)}>
          Wpisz
        </Button>
      )}
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

/** Pełna ścieżka wpisana albo wklejona z Eksploratora; Enter i „Zapisz” zapisują, Esc i „Anuluj” wracają. */
function TypedPath({
  path,
  title,
  initial,
  invalid,
  onDone,
}: {
  path: PickedPath
  title: string
  initial: string
  invalid: string | undefined
  onDone: () => void
}) {
  const { typePath, dismiss } = useSettings()
  const [value, setValue] = React.useState(initial)
  const [saving, setSaving] = React.useState(false)

  const cancel = () => {
    dismiss()
    onDone()
  }

  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        setSaving(true)
        void typePath(path, value).then((saved) => {
          setSaving(false)

          if (saved) {
            onDone()
          }
        })
      }}
    >
      <Input
        autoFocus
        aria-label={`Ścieżka: ${title}`}
        aria-invalid={invalid === undefined ? undefined : true}
        aria-describedby={invalid}
        className="min-w-0 flex-1 basis-64 font-mono text-xs md:text-xs"
        placeholder={path === "order_register" ? "C:\\…\\ZLECENIA ….xlsx" : "C:\\…\\Załączniki"}
        spellCheck={false}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            cancel()
          }
        }}
      />
      <Button type="button" variant="ghost" size="sm" onClick={cancel}>
        Anuluj
      </Button>
      <Button type="submit" size="sm" disabled={saving} aria-label={`Zapisz ${title}`}>
        {saving ? <Spinner data-icon="inline-start" /> : null}
        Zapisz
      </Button>
    </form>
  )
}
