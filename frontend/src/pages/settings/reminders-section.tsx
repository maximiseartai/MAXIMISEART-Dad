import * as React from "react"

import { changeReminders, changeRemindersEnabled, previewReminder } from "@/api/centrum"
import { failureMessage, refusedField } from "@/api/client"
import type { ReminderPreview, RemindersForm, RemindersSetting } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { fullDate } from "@/lib/format"
import { useSettings, type FieldRefusal } from "@/lib/settings"
import { FieldSentence, SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

/** Sekcja okna Ustawień z Przypomnieniami o raporcie: tu tata wpisuje też stopkę. */
export const REMINDERS_SECTION = "przypomnienia"

const REMINDERS = "Przypomnienia o raporcie"

/** Wiersze formularza, pod którymi stoi zdanie odmowy albo złego pliku: pierwszy człon pola z serwera. */
const FORM_ROWS = ["pora_poranna", "pora_wieczorna", "pierwsze_przypomnienie", "tresc", "stopka"] as const

type FormRow = (typeof FORM_ROWS)[number]

/** Wiersz pola z serwera (`pora_wieczorna.od` → `pora_wieczorna`); pole spoza formularza to `null`. */
function rowOf(field: string | null): FormRow | null {
  const head = (field ?? "").split(".")[0]

  return FORM_ROWS.find((row) => row === head) ?? null
}

/**
 * Przypomnienia o raporcie (ADR 0032): przełącznik zapisuje się od razu, a pory, godzina pierwszego przypomnienia,
 * pierwsze zdanie i stopka dopiero przyciskiem „Zapisz”. Podgląd pokazuje mail za wczoraj tak, jak dostanie go
 * Wykonawca, ze stałym tematem, bez zapisu i bez wysyłki. Zmiana działa od następnego sprawdzenia przypomnień.
 */
export function RemindersSection() {
  const { settings, reload } = useSettings()

  switch (settings.state) {
    case "loading":
      return <Skeleton className="h-72 w-full rounded-xl" aria-label="Wczytywanie ustawień" />
    case "failed":
      return <LoadFailure what="ustawień" message={settings.message} reload={reload} />
    case "ready": {
      const setting = settings.data.reminders
      const saved = formOf(setting)

      return (
        <div className="flex flex-col gap-4">
          {setting.problem !== null && rowOf(setting.problem.field) === null ? (
            <FieldSentence>{setting.problem.message}</FieldSentence>
          ) : null}
          <Switched setting={setting} />
          {/* Formularz zaczyna od zapisanych wartości po każdym zapisie i cofnięciu. */}
          <Form key={JSON.stringify(saved)} saved={saved} problem={setting.problem} />
        </div>
      )
    }

    default: {
      const unhandled: never = settings

      return unhandled
    }
  }
}

function formOf(setting: RemindersSetting): RemindersForm {
  const { morning, evening, first, text, footer } = setting

  return { morning, evening, first, text, footer }
}

/** Przełącznik: do odpowiedzi serwera stoi w wybranym położeniu, a drugie kliknięcie niczego nie wysyła. */
function Switched({ setting }: { setting: RemindersSetting }) {
  const { sectionSaved, saveFailed } = useSettings()
  const [pending, setPending] = React.useState<boolean | null>(null)
  const enabled = pending ?? setting.enabled

  return (
    <SettingsPanel label={REMINDERS}>
      <SettingRow
        title={REMINDERS}
        description={
          setting.enabled && setting.since !== null
            ? `Idą od ${fullDate(setting.since)} do Wykonawców, którzy nie przysłali raportu za dzień.`
            : "Mail do Wykonawcy, który nie przysłał raportu za dzień."
        }
      >
        <Switch
          aria-label={REMINDERS}
          checked={enabled}
          disabled={pending !== null}
          onCheckedChange={(next) => {
            setPending(next)
            changeRemindersEnabled(next)
              .then(sectionSaved, saveFailed)
              .finally(() => setPending(null))
          }}
        />
      </SettingRow>
    </SettingsPanel>
  )
}

function Form({ saved, problem }: { saved: RemindersForm; problem: RemindersSetting["problem"] }) {
  const { sectionSaved, saveFailed } = useSettings()
  const [form, setForm] = React.useState(saved)
  const [saving, setSaving] = React.useState(false)
  const [refusal, setRefusal] = React.useState<FieldRefusal | null>(null)
  const changed = JSON.stringify(form) !== JSON.stringify(saved)

  // Odmowa stoi przy swoim wierszu do następnej zmiany tego formularza; zły plik, dopóki tata go nie zapisze.
  const shown = refusal ?? (problem === null ? null : { field: problem.field ?? "", message: problem.message })
  const sentence = (row: FormRow) => (shown !== null && rowOf(shown.field) === row ? shown.message : null)
  const invalid = (field: string) => (refusal?.field === field ? true : undefined)

  const edit = (next: Partial<RemindersForm>) => {
    setRefusal(null)
    setForm((current) => ({ ...current, ...next }))
  }

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        setSaving(true)
        changeReminders(form).then(
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
      }}
    >
      <SettingsPanel label="Pory i treść">
        <SettingRow
          title="Pora poranna"
          description="Najwyżej jedno przypomnienie w porze."
          below={<Sentence>{sentence("pora_poranna")}</Sentence>}
        >
          <Range
            label="Pora poranna"
            field="pora_poranna"
            value={form.morning}
            invalid={invalid}
            onChange={(morning) => edit({ morning })}
          />
        </SettingRow>
        <SettingRow
          title="Pora wieczorna"
          description="Zaczyna się nie wcześniej, niż kończy się poranna."
          below={<Sentence>{sentence("pora_wieczorna")}</Sentence>}
        >
          <Range
            label="Pora wieczorna"
            field="pora_wieczorna"
            value={form.evening}
            invalid={invalid}
            onChange={(evening) => edit({ evening })}
          />
        </SettingRow>
        <SettingRow
          title="Pierwsze przypomnienie"
          description="Za dzień zleceń, od tej godziny następnego dnia."
          below={<Sentence>{sentence("pierwsze_przypomnienie")}</Sentence>}
        >
          <TimeInput
            label="Pierwsze przypomnienie"
            value={form.first}
            invalid={invalid("pierwsze_przypomnienie")}
            onChange={(first) => edit({ first })}
          />
        </SettingRow>
        <SettingRow
          title="Treść"
          description="Pierwsze zdanie maila; {dzień} to dzień raportu."
          below={
            <>
              <Textarea
                aria-label="Treść przypomnienia"
                aria-invalid={invalid("tresc")}
                value={form.text}
                onChange={(event) => edit({ text: event.target.value })}
              />
              <Sentence>{sentence("tresc")}</Sentence>
            </>
          }
        />
        <SettingRow
          title="Stopka"
          description="Na końcu maila, np. podpis i telefon."
          below={
            <>
              <Textarea
                aria-label="Stopka przypomnienia"
                aria-invalid={invalid("stopka")}
                value={form.footer}
                onChange={(event) => edit({ footer: event.target.value })}
              />
              <Sentence>{sentence("stopka")}</Sentence>
            </>
          }
        />
      </SettingsPanel>
      <div className="flex justify-end gap-2">
        {changed ? (
          <Button type="button" variant="ghost" size="sm" onClick={() => edit(saved)}>
            Anuluj
          </Button>
        ) : null}
        <Button type="submit" size="sm" disabled={!changed || saving} aria-label="Zapisz przypomnienia">
          {saving ? <Spinner data-icon="inline-start" /> : null}
          Zapisz
        </Button>
      </div>
      <Preview form={form} />
    </form>
  )
}

function Sentence({ children }: { children: string | null }) {
  return children === null ? null : <FieldSentence>{children}</FieldSentence>
}

function Range({
  label,
  field,
  value,
  invalid,
  onChange,
}: {
  label: string
  field: string
  value: RemindersForm["morning"]
  invalid: (field: string) => true | undefined
  onChange: (value: RemindersForm["morning"]) => void
}) {
  return (
    <div className="flex items-center gap-1.5">
      <TimeInput
        label={`${label} od`}
        value={value.start}
        invalid={invalid(`${field}.od`)}
        onChange={(start) => onChange({ ...value, start })}
      />
      <span className="text-muted-foreground" aria-hidden>
        –
      </span>
      <TimeInput
        label={`${label} do`}
        value={value.end}
        invalid={invalid(`${field}.do`)}
        onChange={(end) => onChange({ ...value, end })}
      />
    </div>
  )
}

function TimeInput({
  label,
  value,
  invalid,
  onChange,
}: {
  label: string
  value: string
  invalid: true | undefined
  onChange: (value: string) => void
}) {
  return (
    <Input
      type="time"
      aria-label={label}
      aria-invalid={invalid}
      className="w-28 tabular-nums"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

/** Czas od ostatniej zmiany formularza do podglądu: pisanie w treści nie pyta serwera przy każdej literze. */
const PREVIEW_AFTER_MS = 250

/**
 * Przypomnienie z formularza za wczoraj, tak jak dostanie je Wykonawca, także przed zapisem. Formularz, którego serwer
 * nie przyjmuje, zostawia ostatni podgląd; zdanie o złej wartości daje dopiero „Zapisz”.
 */
function Preview({ form }: { form: RemindersForm }) {
  const [preview, setPreview] = React.useState<ReminderPreview | null>(null)

  React.useEffect(() => {
    let current = true

    const timer = window.setTimeout(() => {
      previewReminder(form).then(
        (shown) => {
          if (current) {
            setPreview(shown)
          }
        },
        () => undefined
      )
    }, PREVIEW_AFTER_MS)

    return () => {
      current = false
      window.clearTimeout(timer)
    }
  }, [form])

  return (
    <section aria-label="Podgląd przypomnienia" className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">Podgląd</h3>
      <div className="flex flex-col gap-3 rounded-xl border bg-muted/30 px-4 py-3.5 text-sm">
        {preview === null ? (
          <Skeleton className="h-40 w-full" aria-label="Wczytywanie podglądu" />
        ) : (
          <>
            <div className="flex flex-col gap-0.5">
              <span className="font-medium">{preview.subject}</span>
              <span className="text-muted-foreground">
                Temat jest stały: po nim Centrum poznaje odpowiedzi Wykonawców.
              </span>
            </div>
            <pre className="font-sans whitespace-pre-wrap text-pretty">{preview.text}</pre>
          </>
        )}
      </div>
    </section>
  )
}
