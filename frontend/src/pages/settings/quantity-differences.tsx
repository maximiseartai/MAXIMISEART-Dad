import * as React from "react"

import { getQuantityDifferences, markQuantityException } from "@/api/centrum"
import type { DifferencesReady, GetQuantityDifferencesResponse, QuantityDifference, RuleForm } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { useAction } from "@/lib/action"
import { plural } from "@/lib/format"
import { useReloadOnChange, useSettings } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { columnLabel } from "@/pages/settings/rule-sentence"
import { FieldSentence, SettingsPanel } from "@/pages/settings/setting-row"

/** Tyle różnic widać od razu; resztę rozwija „Pokaż wszystkie”. */
const FIRST = 5

const DIFFERENCES = { one: "różnica", few: "różnice", many: "różnic" }

const TITLE = "Tu wpisałeś inaczej niż reguła"

/**
 * Różnice z Kontroli ilości ostatnich okresów, liczone przez serwer tym samym rachunkiem co Kontrola ilości: kolumna,
 * ilość z reguł, wpis taty i wiersz bez adresu i numerów. „Popraw regułę” otwiera edytor z formularzem z serwera
 * (`fix`), „To był wyjątek” zapisuje wyjątek z „Zapisano · Cofnij”. Bez różnic lista się nie pokazuje.
 */
export function QuantityDifferences({ fix }: { fix: (draft: RuleForm) => void }) {
  const { resource, reload, replace } = useResource(getQuantityDifferences, [])

  useReloadOnChange(reload)

  switch (resource.state) {
    case "loading":
      return null
    case "failed":
      return <LoadFailure what="różnic z Kontroli ilości" message={resource.message} reload={reload} />
    case "ready":
      return (
        <Found found={resource.data} fix={fix} marked={(next) => replace({ state: "ready", data: next })} reload={reload} />
      )
    default: {
      const unhandled: never = resource

      return unhandled
    }
  }
}

/** Złe ustawienie pliku wyjątków i lista; bez różnic i bez nieczytelnego pliku sama lista się nie pokazuje. */
function Found({
  found,
  fix,
  marked,
  reload,
}: {
  found: GetQuantityDifferencesResponse
  fix: (draft: RuleForm) => void
  marked: (next: GetQuantityDifferencesResponse) => void
  reload: () => Promise<void>
}) {
  const problem = found.exceptions_problem === null ? null : <FieldSentence>{found.exceptions_problem.message}</FieldSentence>

  if (found.state !== "ready" || (found.differences.length === 0 && found.unread.length === 0)) {
    return problem
  }

  return (
    <>
      {problem}
      <List found={found} fix={fix} marked={marked} reload={reload} />
    </>
  )
}

function List({
  found,
  fix,
  marked,
  reload,
}: {
  found: DifferencesReady
  fix: (draft: RuleForm) => void
  marked: (next: GetQuantityDifferencesResponse) => void
  reload: () => Promise<void>
}) {
  const [all, setAll] = React.useState(false)
  const { changed } = useSettings()
  const total = found.differences.length + found.more
  const shown = all ? found.differences : found.differences.slice(0, FIRST)
  const hidden = found.differences.length - shown.length

  const marking = useAction(async (id: string) => {
    await markQuantityException(id).then(
      (saved) => {
        changed(saved.change)
        marked(saved.differences)
      },
      (failure: Error) => {
        void reload()
        throw failure
      }
    )
  }, "Nie udało się zapisać wyjątku")

  return (
    <section aria-label={TITLE} className="flex flex-col gap-2">
      <p aria-hidden className="flex items-baseline gap-2 px-1 text-xs font-medium text-muted-foreground">
        {TITLE}
        <span className="tabular-nums">{total}</span>
      </p>
      <SettingsPanel label={TITLE}>
        {shown.map((difference) => (
          <Item
            key={difference.id}
            difference={difference}
            fix={() => fix(difference.draft)}
            mark={() => void marking.run(difference.id)}
            marking={marking.running?.[0] === difference.id}
          />
        ))}
        {hidden === 0 ? null : (
          <div role="listitem" className="px-2 py-1.5">
            <Button variant="ghost" size="sm" onClick={() => setAll(true)}>
              Pokaż wszystkie ({found.differences.length})
            </Button>
          </div>
        )}
        {all && found.more > 0 ? (
          <Note>
            I jeszcze {found.more} {plural(found.more, DIFFERENCES)}.
          </Note>
        ) : null}
        {found.unread.length === 0 ? null : (
          <Note>Nie dało się przeczytać Pliku zbiorczego okresu {found.unread.join(", ")}.</Note>
        )}
        {found.exceptions === 0 ? null : (
          <Note>
            Oznaczone jako wyjątek: {found.exceptions}. Cofniesz je w Historii.
          </Note>
        )}
      </SettingsPanel>
    </section>
  )
}

function Item({
  difference,
  fix,
  mark,
  marking,
}: {
  difference: QuantityDifference
  fix: () => void
  mark: () => void
  marking: boolean
}) {
  const column = columnLabel({ letter: difference.column, name: difference.name })

  return (
    <div role="listitem" aria-label={`${column}, wiersz ${difference.row}`} className="flex flex-col gap-2 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 tabular-nums">
        {difference.name === null ? null : <span className="font-medium">{difference.name}</span>}
        <Badge variant="secondary" className="font-mono" aria-label={`kolumna ${difference.column}`}>
          {difference.column}
        </Badge>
        <span>
          reguła {difference.rule} · wpisałeś {difference.tata}
        </span>
      </div>
      <p className="text-pretty text-muted-foreground">
        {difference.devices === "" ? "(puste)" : difference.devices}
        {difference.activities === "" ? null : ` · ${difference.activities}`}
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="min-w-0 flex-1 basis-40 text-muted-foreground tabular-nums">
          {difference.period} · wiersz {difference.row} · {difference.when}
        </span>
        <div className="flex shrink-0 gap-2">
          <Button variant="ghost" size="sm" disabled={marking} onClick={mark}>
            {marking ? <Spinner data-icon="inline-start" /> : null}
            To był wyjątek
          </Button>
          <Button variant="outline" size="sm" onClick={fix}>
            Popraw regułę
          </Button>
        </div>
      </div>
    </div>
  )
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p role="listitem" className="px-4 py-3 text-sm text-pretty text-muted-foreground">
      {children}
    </p>
  )
}
