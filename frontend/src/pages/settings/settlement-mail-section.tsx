import * as React from "react"

import { changeSettlementMail, previewSettlementMail } from "@/api/centrum"
import { failureMessage, refusedField } from "@/api/client"
import type { SettlementMailForm, SettlementMailPreview, SettlementMailSetting } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { settingsHref } from "@/lib/address"
import { useSettings, type FieldRefusal } from "@/lib/settings"
import { REMINDERS_SECTION } from "@/pages/settings/reminders-section"
import { FieldSentence, SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

/** Sekcja okna Ustawień z tematem i treścią Maila z rozliczeniem (ADR 0040). */
export const SETTLEMENT_MAIL_SECTION = "wysylka-rozliczen"

/** Wiersze formularza, pod którymi stoi zdanie odmowy albo złego pliku: pole z serwera. */
const FORM_ROWS = ["temat", "tresc"] as const

type FormRow = (typeof FORM_ROWS)[number]

function rowOf(field: string | null): FormRow | null {
  return FORM_ROWS.find((row) => row === field) ?? null
}

/**
 * Temat i treść Maila z rozliczeniem: zapisują się przyciskiem „Zapisz”, a podgląd pokazuje mail pierwszego Wykonawcy
 * z Listy za ostatni pełny okres, jak go dostanie. Stopka jest wspólna z Przypomnieniami o raporcie, jeden podpis taty.
 */
export function SettlementMailSection() {
  const { settings, reload } = useSettings()

  switch (settings.state) {
    case "loading":
      return <Skeleton className="h-72 w-full rounded-xl" aria-label="Wczytywanie ustawień" />
    case "failed":
      return <LoadFailure what="ustawień" message={settings.message} reload={reload} />
    case "ready": {
      const setting = settings.data.settlement_mail
      const saved = formOf(setting)

      return (
        <div className="flex flex-col gap-4">
          {setting.problem !== null && rowOf(setting.problem.field) === null ? (
            <FieldSentence>{setting.problem.message}</FieldSentence>
          ) : null}
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

function formOf(setting: SettlementMailSetting): SettlementMailForm {
  return { subject: setting.subject, text: setting.text }
}

function Form({ saved, problem }: { saved: SettlementMailForm; problem: SettlementMailSetting["problem"] }) {
  const { sectionSaved, saveFailed } = useSettings()
  const [form, setForm] = React.useState(saved)
  const [saving, setSaving] = React.useState(false)
  const [refusal, setRefusal] = React.useState<FieldRefusal | null>(null)
  const changed = JSON.stringify(form) !== JSON.stringify(saved)

  const shown = refusal ?? (problem === null ? null : { field: problem.field ?? "", message: problem.message })
  const sentence = (row: FormRow) => (shown !== null && rowOf(shown.field) === row ? shown.message : null)
  const invalid = (field: FormRow) => (refusal?.field === field ? true : undefined)

  const edit = (next: Partial<SettlementMailForm>) => {
    setRefusal(null)
    setForm((current) => ({ ...current, ...next }))
  }

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        setSaving(true)
        changeSettlementMail(form).then(
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
      <SettingsPanel label="Temat i treść">
        <SettingRow
          title="Temat"
          description="Bez słowa „raport”; {okres} to dni okresu, {wykonawca} to nazwa Wykonawcy."
          below={
            <>
              <Input
                aria-label="Temat maila z rozliczeniem"
                aria-invalid={invalid("temat")}
                value={form.subject}
                onChange={(event) => edit({ subject: event.target.value })}
              />
              <Sentence>{sentence("temat")}</Sentence>
            </>
          }
        />
        <SettingRow
          title="Treść"
          description="Nad stopką; te same pola co w temacie."
          below={
            <>
              <Textarea
                aria-label="Treść maila z rozliczeniem"
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
          description={
            <>
              Ta sama co w Przypomnieniach o raporcie, jeden Twój podpis.{" "}
              <a href={settingsHref(REMINDERS_SECTION)} className="text-foreground underline underline-offset-4">
                Zmień ją w Przypomnieniach
              </a>
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
        <Button type="submit" size="sm" disabled={!changed || saving} aria-label="Zapisz wysyłkę rozliczeń">
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

/** Czas od ostatniej zmiany formularza do podglądu: pisanie nie pyta serwera przy każdej literze. */
const PREVIEW_AFTER_MS = 250

/** Mail z formularza, także przed zapisem; formularz, którego serwer nie przyjmuje, zostawia ostatni podgląd. */
function Preview({ form }: { form: SettlementMailForm }) {
  const [preview, setPreview] = React.useState<SettlementMailPreview | null>(null)

  React.useEffect(() => {
    let current = true

    const timer = window.setTimeout(() => {
      previewSettlementMail(form).then(
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
    <section aria-label="Podgląd maila z rozliczeniem" className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">Podgląd</h3>
      <div className="flex flex-col gap-3 rounded-xl border bg-muted/30 px-4 py-3.5 text-sm">
        {preview === null ? (
          <Skeleton className="h-32 w-full" aria-label="Wczytywanie podglądu" />
        ) : (
          <>
            <span className="font-medium">{preview.subject}</span>
            <pre className="font-sans whitespace-pre-wrap text-pretty">{preview.text}</pre>
          </>
        )}
      </div>
    </section>
  )
}
