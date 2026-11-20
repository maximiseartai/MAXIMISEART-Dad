import * as React from "react"

import { changeReminders, changeRemindersEnabled, previewReminder } from "@/api/centrum"
import type { RemindersForm, RemindersSetting } from "@/api/generated"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { fullDate } from "@/lib/format"
import { useSettings } from "@/lib/settings"
import {
  MailPreview,
  SaveButtons,
  Sentence,
  SettingFormSection,
  TextRow,
  useSettingForm,
} from "@/pages/settings/setting-form"
import { SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

export const REMINDERS_SECTION = "przypomnienia"

const REMINDERS = "Przypomnienia o raporcie"

const FORM_ROWS = ["pora_poranna", "pora_wieczorna", "pierwsze_przypomnienie", "tresc", "stopka"] as const

type FormRow = (typeof FORM_ROWS)[number]

export function RemindersSection() {
  return (
    <SettingFormSection
      setting={(settings) => settings.reminders}
      rows={FORM_ROWS}
      formOf={formOf}
      above={Switched}
    >
      {(saved, problem) => <Form saved={saved} problem={problem} />}
    </SettingFormSection>
  )
}

function formOf(setting: RemindersSetting): RemindersForm {
  const { morning, evening, first, text, footer } = setting

  return { morning, evening, first, text, footer }
}

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
  const editor = useSettingForm({ saved, problem, rows: FORM_ROWS, save: changeReminders })
  const { form, edit, sentence, invalid } = editor

  return (
    <form className="flex flex-col gap-4" onSubmit={editor.submit}>
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
        <TextRow
          editor={editor}
          row="tresc"
          title="Treść"
          description="Pierwsze zdanie maila; {dzień} to dzień raportu."
          label="Treść przypomnienia"
          value={form.text}
          onChange={(text) => edit({ text })}
        />
        <TextRow
          editor={editor}
          row="stopka"
          title="Stopka"
          description="Na końcu maila, np. podpis i telefon."
          label="Stopka przypomnienia"
          value={form.footer}
          onChange={(footer) => edit({ footer })}
        />
      </SettingsPanel>
      <SaveButtons editor={editor} label="Zapisz przypomnienia" />
      <Preview form={form} />
    </form>
  )
}

function Range({
  label,
  field,
  value,
  invalid,
  onChange,
}: {
  label: string
  field: "pora_poranna" | "pora_wieczorna"
  value: RemindersForm["morning"]
  invalid: (field: `${FormRow}.${string}`) => true | undefined
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
    // Tekst `GG:MM`, a nie pole czasu przeglądarki: to w angielskim systemie pokazuje 12-godzinny zegar z AM/PM.
    <Input
      inputMode="numeric"
      autoComplete="off"
      maxLength={5}
      placeholder="GG:MM"
      aria-label={label}
      aria-invalid={invalid}
      className="w-[4.75rem] text-center tabular-nums"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function Preview({ form }: { form: RemindersForm }) {
  return (
    <MailPreview form={form} preview={previewReminder} label="Podgląd przypomnienia" skeleton="h-40">
      {(preview) => (
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
    </MailPreview>
  )
}
