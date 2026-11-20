import * as React from "react"

import { failureMessage, refusedField } from "@/api/client"
import type { Choice, SettingProblem, Settings } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { useSettings, type FieldRefusal } from "@/lib/settings"
import { FieldSentence, SettingRow } from "@/pages/settings/setting-row"

type RowField<Row extends string> = Row | `${Row}.${string}`

function rowOf<Row extends string>(rows: readonly Row[], field: string | null): Row | null {
  const head = (field ?? "").split(".")[0]

  return rows.find((row) => row === head) ?? null
}

export function SettingFormSection<Setting extends { problem: SettingProblem | null }, Form>({
  setting: select,
  rows,
  formOf,
  above: Above,
  children,
}: {
  setting: (settings: Settings) => Setting
  rows: readonly string[]
  formOf: (setting: Setting) => Form
  above?: React.ComponentType<{ setting: Setting }>
  children: (saved: Form, problem: SettingProblem | null) => React.ReactNode
}) {
  const { settings, reload } = useSettings()

  switch (settings.state) {
    case "loading":
      return <Skeleton className="h-72 w-full rounded-xl" aria-label="Wczytywanie ustawień" />
    case "failed":
      return <LoadFailure what="ustawień" message={settings.message} reload={reload} />
    case "ready": {
      const setting = select(settings.data)
      const saved = formOf(setting)

      return (
        <div className="flex flex-col gap-4">
          {setting.problem !== null && rowOf(rows, setting.problem.field) === null ? (
            <FieldSentence>{setting.problem.message}</FieldSentence>
          ) : null}
          {Above === undefined ? null : <Above setting={setting} />}
          <React.Fragment key={JSON.stringify(saved)}>{children(saved, setting.problem)}</React.Fragment>
        </div>
      )
    }

    default: {
      const unhandled: never = settings

      return unhandled
    }
  }
}

type RowSentences<Row extends string> = {
  sentence: (row: Row) => string | null
  invalid: (field: RowField<Row>) => true | undefined
}

type SettingForm<Form, Row extends string> = RowSentences<Row> & {
  form: Form
  edit: (next: Partial<Form>) => void
  cancel: () => void
  changed: boolean
  saving: boolean
  submit: (event: React.FormEvent<HTMLFormElement>) => void
}

export function useSettingForm<Form extends object, Row extends string>({
  saved,
  problem,
  rows,
  save,
}: {
  saved: Form
  problem: SettingProblem | null
  rows: readonly Row[]
  save: (form: Form) => Promise<Choice>
}): SettingForm<Form, Row> {
  const { sectionSaved, saveFailed } = useSettings()
  const [form, setForm] = React.useState(saved)
  const [saving, setSaving] = React.useState(false)
  const [refusal, setRefusal] = React.useState<FieldRefusal | null>(null)

  const shown = refusal ?? (problem === null ? null : { field: problem.field ?? "", message: problem.message })

  const edit = (next: Partial<Form>) => {
    setRefusal(null)
    setForm((current) => ({ ...current, ...next }))
  }

  return {
    form,
    edit,
    cancel: () => edit(saved),
    changed: JSON.stringify(form) !== JSON.stringify(saved),
    saving,
    sentence: (row) => (shown !== null && rowOf(rows, shown.field) === row ? shown.message : null),
    invalid: (field) => (refusal?.field === field ? true : undefined),
    submit: (event) => {
      event.preventDefault()
      setSaving(true)
      save(form).then(
        (choice) => {
          setSaving(false)
          sectionSaved(choice)
        },
        (failure: Error) => {
          setSaving(false)
          const field = refusedField(failure)

          if (field === null) {
            saveFailed(failure)
          } else {
            setRefusal({ field, message: failureMessage(failure) })
          }
        }
      )
    },
  }
}

export function SaveButtons({
  editor,
  label,
}: {
  editor: Pick<SettingForm<object, string>, "changed" | "saving" | "cancel">
  label: string
}) {
  return (
    <div className="flex justify-end gap-2">
      {editor.changed ? (
        <Button type="button" variant="ghost" size="sm" onClick={editor.cancel}>
          Anuluj
        </Button>
      ) : null}
      <Button type="submit" size="sm" disabled={!editor.changed || editor.saving} aria-label={label}>
        {editor.saving ? <Spinner data-icon="inline-start" /> : null}
        Zapisz
      </Button>
    </div>
  )
}

export function Sentence({ children }: { children: string | null }) {
  return children === null ? null : <FieldSentence>{children}</FieldSentence>
}

export function TextRow<Row extends string>({
  editor,
  row,
  title,
  description,
  label,
  value,
  onChange,
  singleLine = false,
}: {
  editor: RowSentences<Row>
  row: Row
  title: string
  description: string
  label: string
  value: string
  onChange: (value: string) => void
  singleLine?: boolean
}) {
  const Field = singleLine ? Input : Textarea

  return (
    <SettingRow
      title={title}
      description={description}
      below={
        <>
          <Field
            aria-label={label}
            aria-invalid={editor.invalid(row)}
            value={value}
            onChange={(event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value)}
          />
          <Sentence>{editor.sentence(row)}</Sentence>
        </>
      }
    />
  )
}

/** Czas od ostatniej zmiany formularza do podglądu: pisanie nie pyta serwera przy każdej literze. */
const PREVIEW_AFTER_MS = 250

export function MailPreview<Form, Shown>({
  form,
  preview,
  label,
  skeleton,
  children,
}: {
  form: Form
  preview: (form: Form) => Promise<Shown>
  label: string
  /** Wysokość szkieletu przed pierwszym podglądem, mniej więcej taka jak podgląd. */
  skeleton: string
  children: (shown: Shown) => React.ReactNode
}) {
  const [shown, setShown] = React.useState<Shown | null>(null)

  React.useEffect(() => {
    let current = true

    const timer = window.setTimeout(() => {
      preview(form).then(
        (next) => {
          if (current) {
            setShown(next)
          }
        },
        () => undefined
      )
    }, PREVIEW_AFTER_MS)

    return () => {
      current = false
      window.clearTimeout(timer)
    }
  }, [form, preview])

  return (
    <section aria-label={label} className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">Podgląd</h3>
      <div className="flex flex-col gap-3 rounded-xl border bg-muted/30 px-4 py-3.5 text-sm">
        {shown === null ? (
          <Skeleton className={`${skeleton} w-full`} aria-label="Wczytywanie podglądu" />
        ) : (
          children(shown)
        )}
      </div>
    </section>
  )
}
