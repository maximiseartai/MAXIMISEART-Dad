import { changeSettlementMail, previewSettlementMail } from "@/api/centrum"
import type { SettlementMailForm, SettlementMailSetting } from "@/api/generated"
import { settingsHref } from "@/lib/address"
import { REMINDERS_SECTION } from "@/pages/settings/reminders-section"
import { MailPreview, SaveButtons, SettingFormSection, TextRow, useSettingForm } from "@/pages/settings/setting-form"
import { SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

export const SETTLEMENT_MAIL_SECTION = "wysylka-rozliczen"

const FORM_ROWS = ["temat", "tresc"] as const

export function SettlementMailSection() {
  return (
    <SettingFormSection setting={(settings) => settings.settlement_mail} rows={FORM_ROWS} formOf={formOf}>
      {(saved, problem) => <Form saved={saved} problem={problem} />}
    </SettingFormSection>
  )
}

function formOf(setting: SettlementMailSetting): SettlementMailForm {
  return { subject: setting.subject, text: setting.text }
}

function Form({ saved, problem }: { saved: SettlementMailForm; problem: SettlementMailSetting["problem"] }) {
  const editor = useSettingForm({ saved, problem, rows: FORM_ROWS, save: changeSettlementMail })
  const { form, edit } = editor

  return (
    <form className="flex flex-col gap-4" onSubmit={editor.submit}>
      <SettingsPanel label="Temat i treść">
        <TextRow
          editor={editor}
          row="temat"
          title="Temat"
          description="Bez słowa „raport”; {okres} to dni okresu, {wykonawca} to nazwa Wykonawcy."
          label="Temat maila z rozliczeniem"
          value={form.subject}
          onChange={(subject) => edit({ subject })}
          singleLine
        />
        <TextRow
          editor={editor}
          row="tresc"
          title="Treść"
          description="Nad stopką; te same pola co w temacie."
          label="Treść maila z rozliczeniem"
          value={form.text}
          onChange={(text) => edit({ text })}
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
      <SaveButtons editor={editor} label="Zapisz wysyłkę rozliczeń" />
      <MailPreview form={form} preview={previewSettlementMail} label="Podgląd maila z rozliczeniem" skeleton="h-32">
        {(preview) => (
          <>
            <span className="font-medium">{preview.subject}</span>
            <pre className="font-sans whitespace-pre-wrap text-pretty">{preview.text}</pre>
          </>
        )}
      </MailPreview>
    </form>
  )
}
