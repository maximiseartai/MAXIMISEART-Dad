import * as React from "react"
import { PencilIcon, PlusIcon, XIcon } from "lucide-react"

import { addActivityCode, changeActivityCode, getActivityLegend, removeActivityCode } from "@/api/centrum"
import type { ActivityCodeForm, ActivityCodeSentence, ActivityLegendSettings, FillForm, RangeForm } from "@/api/generated"
import { zFillForm } from "@/api/generated/zod.gen"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useUnsavedForm } from "@/lib/unsaved"
import { LegendPreview } from "@/pages/settings/activity-legend-preview"
import { Choice, type Option } from "@/pages/settings/quantity-rule-editor"
import { useActivityLegendSave } from "@/pages/settings/quantity-rules-save"
import { Problem } from "@/pages/settings/quantity-rules-section"
import { columnLabel, Sentence } from "@/pages/settings/rule-sentence"
import { FieldSentence, FormActions, FormRow, SettingsPanel } from "@/pages/settings/setting-row"
import { WithSettingsRead } from "@/pages/settings/settings-read"

type ColumnKind = "none" | "fixed" | "ranges"

const COLUMN_KINDS: ReadonlyArray<Option<ColumnKind>> = [
  { value: "none", label: "Bez kolumny" },
  { value: "fixed", label: "W jedną kolumnę, liczba bez znaczenia" },
  { value: "ranges", label: "Kolumna według liczby w kodzie" },
]

const COLOURS: ReadonlyArray<Option<FillForm["colour"]>> = zFillForm.shape.colour.options.map((colour) => ({ value: colour, label: colour }))

const NEW_CODE: ActivityCodeForm = { spellings: [""], column: null, value: 1, amount: null, fills: [] }

/** Kod w formularzu: `id` `null` to nowy kod. */
type Editing = { id: string | null; form: ActivityCodeForm }

/**
 * Legenda czynności: każdy Kod czynności jednym zdaniem, w kolejności z pliku; kolumna ma nazwę pozycji cennika z
 * Wzorca. Ołówek przy kodzie i „Dodaj kod” otwierają formularz w miejscu wiersza. Zła legenda pokazuje swoje zdanie nad
 * legendą, którą Centrum liczy mimo to.
 */
export function ActivityLegendSection() {
  const [editing, setEditing] = React.useState<Editing | null>(null)

  return (
    <WithSettingsRead read={getActivityLegend} what="Legendy czynności">
      {(legend, saved) => {
        const close = (next: ActivityLegendSettings | null) => {
          if (next !== null) {
            saved(next)
          }

          setEditing(null)
        }

        const editor = (shown: Editing) => <CodeEditor key={shown.id ?? "nowy"} editing={shown} legend={legend} close={close} />

        return (
          <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <p className="min-w-0 flex-1 basis-64 text-sm text-pretty text-muted-foreground">
                Kody z opisu technika działają przy następnym Przygotowaniu pliku zbiorczego. Gotowe Pliki zbiorcze się nie
                zmieniają. # w kodzie to dowolna liczba, np. inst20m.
              </p>
              <Button variant="outline" size="sm" onClick={() => setEditing({ id: null, form: NEW_CODE })}>
                <PlusIcon data-icon="inline-start" />
                Dodaj kod
              </Button>
            </div>
            <Problem problem={legend.problem} />
            <SettingsPanel label="Kody czynności">
              {legend.codes.map((code) =>
                editing !== null && editing.id === code.id ? (
                  editor(editing)
                ) : (
                  <CodeRow key={code.id} code={code} edit={() => setEditing({ id: code.id, form: code.code })} />
                )
              )}
              {editing !== null && editing.id === null ? editor(editing) : null}
            </SettingsPanel>
          </div>
        )
      }}
    </WithSettingsRead>
  )
}

function CodeRow({ code, edit }: { code: ActivityCodeSentence; edit: () => void }) {
  return (
    <div role="listitem" aria-label={code.spellings} className="flex items-start gap-3 px-4 py-3">
      <p className="min-w-0 flex-1 text-sm leading-7 text-pretty">
        <span className="font-mono font-medium">{code.spellings}</span>
        {": "}
        <Sentence parts={code.sentence} />
      </p>
      <Button
        variant="ghost"
        size="icon-sm"
        className="mt-0.5 shrink-0 text-muted-foreground"
        aria-label={`Zmień ${code.spellings}`}
        onClick={edit}
      >
        <PencilIcon />
      </Button>
    </div>
  )
}

/**
 * Formularz Kodu czynności: zapisy, kolumna Ilości usług (stała albo przedziałami liczby z kodu) z wartością, kwota w AS
 * i kolory kolumn. Kolumny wybiera się tylko z tych, w które legenda może pisać, po nazwie z cennika. Każda zmiana, także
 * „Usuń kod”, który przełącza formularz w pytanie „Usunąć kod?”, pokazuje podgląd skutku tej samej zmiany, którą zapisuje
 * dopiero „Zapisz” albo „Usuń”; zła wartość to jedno zdanie przy polu, a problem całego kodu nad formularzem.
 */
function CodeEditor({
  editing,
  legend,
  close,
}: {
  editing: Editing
  legend: ActivityLegendSettings
  close: (saved: ActivityLegendSettings | null) => void
}) {
  const [form, setForm] = React.useState<ActivityCodeForm>(editing.form)
  const [removing, setRemoving] = React.useState(false)
  const { saving, refusal, setRefusal } = useActivityLegendSave(close)
  const { id } = editing
  const dirty = removing || JSON.stringify(form) !== JSON.stringify(editing.form)
  const shownSpelling = editing.form.spellings[0] ?? ""
  const columns = legend.columns.map((column) => ({ value: column.letter, label: columnLabel(column) }))
  const fillColumns = legend.fill_columns.map((column) => ({ value: column.letter, label: columnLabel(column) }))

  useUnsavedForm(dirty)

  const edit =
    removing && id !== null
      ? ({ kind: "remove", code_id: id } as const)
      : id === null
        ? ({ kind: "add", code: form } as const)
        : ({ kind: "change", code_id: id, code: form } as const)

  const request = () =>
    edit.kind === "remove" ? removeActivityCode(edit.code_id) : edit.kind === "add" ? addActivityCode(edit.code) : changeActivityCode(edit.code_id, edit.code)

  const update = (next: ActivityCodeForm) => {
    setForm(next)
    setRefusal(null)
  }

  const sentenceAt = (field: string | null) =>
    refusal !== null && refusal.field === field ? <FieldSentence>{refusal.message}</FieldSentence> : null

  const column = form.column
  const firstColumn = legend.columns[0]?.letter ?? ""

  const kind = (next: ColumnKind) =>
    update({
      ...form,
      column:
        next === "none"
          ? null
          : next === "fixed"
            ? { kind: "fixed", column: firstColumn }
            : { kind: "ranges", ranges: [{ low: 1, high: 15, column: firstColumn }] },
    })

  const replaceRange = (index: number, range: RangeForm) =>
    column?.kind === "ranges" && update({ ...form, column: { ...column, ranges: column.ranges.map((old, at) => (at === index ? range : old)) } })

  const replaceFill = (index: number, fill: FillForm) => update({ ...form, fills: form.fills.map((old, at) => (at === index ? fill : old)) })

  return (
    <div role="listitem" aria-label={id === null ? "Nowy kod" : `Zmiana ${shownSpelling}`} className="flex flex-col gap-3 px-4 py-3.5">
      {sentenceAt(null)}
      {removing ? (
        <p className="text-sm font-medium">
          Usunąć kod <span className="font-mono">{shownSpelling}</span>?
        </p>
      ) : (
        <>
          {form.spellings.map((spelling, index) => (
            <React.Fragment key={index}>
              <FormRow label={index === 0 ? "Zapisy" : ""}>
                <div className="flex w-full items-center gap-1">
                  <Input
                    aria-label={`Zapis ${index + 1}`}
                    className="font-mono"
                    placeholder={index === 0 ? "np. inst#m" : undefined}
                    value={spelling}
                    onChange={(event) => update({ ...form, spellings: form.spellings.map((old, at) => (at === index ? event.target.value : old)) })}
                  />
                  {form.spellings.length === 1 ? null : (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="text-muted-foreground"
                      aria-label={`Usuń zapis ${index + 1}`}
                      onClick={() => update({ ...form, spellings: form.spellings.filter((_, at) => at !== index) })}
                    >
                      <XIcon />
                    </Button>
                  )}
                </div>
              </FormRow>
              {sentenceAt(`zapisy[${index}]`)}
            </React.Fragment>
          ))}
          <FormRow label="">
            <Button variant="ghost" size="sm" onClick={() => update({ ...form, spellings: [...form.spellings, ""] })}>
              <PlusIcon data-icon="inline-start" />
              Dodaj zapis
            </Button>
          </FormRow>
          <FormRow label="Ilość usług">
            <Choice label="Ilość usług" value={column?.kind ?? "none"} options={COLUMN_KINDS} onChange={kind} />
          </FormRow>
          {column?.kind === "fixed" ? (
            <>
              <FormRow label="Kolumna">
                <Choice label="Kolumna" value={column.column} options={columns} onChange={(letter) => update({ ...form, column: { ...column, column: letter } })} />
              </FormRow>
              {sentenceAt("kolumna")}
            </>
          ) : null}
          {column?.kind === "ranges" ? (
            <>
              {column.ranges.map((range, index) => (
                <React.Fragment key={index}>
                  <FormRow label={index === 0 ? "Przedziały" : ""}>
                    <div className="flex w-full flex-wrap items-center gap-2">
                      <span className="text-sm text-muted-foreground">#</span>
                      <NumberField label={`Od ${index + 1}`} value={range.low} change={(low) => replaceRange(index, { ...range, low: low ?? 0 })} />
                      <span className="text-sm text-muted-foreground">do</span>
                      <NumberField label={`Do ${index + 1}`} value={range.high} change={(high) => replaceRange(index, { ...range, high: high ?? 0 })} />
                      <span className="text-sm text-muted-foreground">→</span>
                      <Choice label={`Kolumna przedziału ${index + 1}`} value={range.column} options={columns} onChange={(letter) => replaceRange(index, { ...range, column: letter })} />
                      {column.ranges.length === 1 ? null : (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          className="ml-auto text-muted-foreground"
                          aria-label={`Usuń przedział ${index + 1}`}
                          onClick={() => update({ ...form, column: { ...column, ranges: column.ranges.filter((_, at) => at !== index) } })}
                        >
                          <XIcon />
                        </Button>
                      )}
                    </div>
                  </FormRow>
                  {sentenceAt(`przedzialy[${index}]`)}
                  {sentenceAt(`przedzialy[${index}].kolumna`)}
                </React.Fragment>
              ))}
              <FormRow label="">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    const last = column.ranges.at(-1)
                    const low = last === undefined ? 1 : last.high + 1

                    update({ ...form, column: { ...column, ranges: [...column.ranges, { low, high: low, column: firstColumn }] } })
                  }}
                >
                  <PlusIcon data-icon="inline-start" />
                  Dodaj przedział
                </Button>
              </FormRow>
              {sentenceAt("przedzialy")}
            </>
          ) : null}
          {column === null ? null : (
            <>
              <FormRow label="Wartość">
                <NumberField label="Wartość" value={form.value} change={(value) => update({ ...form, value: value ?? 0 })} />
              </FormRow>
              {sentenceAt("wartosc")}
            </>
          )}
          <FormRow label={columnLabel(legend.amount_column)}>
            <NumberField label="Kwota w AS" value={form.amount} change={(amount) => update({ ...form, amount })} />
          </FormRow>
          {sentenceAt("kwota")}
          {form.fills.map((fill, index) => (
            <React.Fragment key={index}>
              <FormRow label={index === 0 ? "Kolory" : ""}>
                <div className="flex w-full flex-wrap items-center gap-2">
                  <Choice label={`Kolumna koloru ${index + 1}`} value={fill.column} options={fillColumns} onChange={(letter) => replaceFill(index, { ...fill, column: letter })} />
                  <Choice label={`Kolor ${index + 1}`} value={fill.colour} options={COLOURS} onChange={(colour) => replaceFill(index, { ...fill, colour })} />
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="ml-auto text-muted-foreground"
                    aria-label={`Usuń kolor ${index + 1}`}
                    onClick={() => update({ ...form, fills: form.fills.filter((_, at) => at !== index) })}
                  >
                    <XIcon />
                  </Button>
                </div>
              </FormRow>
              {sentenceAt(`wypelnienia[${index}]`)}
            </React.Fragment>
          ))}
          <FormRow label={form.fills.length === 0 ? "Kolory" : ""}>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => update({ ...form, fills: [...form.fills, { column: legend.fill_columns[0]?.letter ?? "", colour: "zielony" }] })}
            >
              <PlusIcon data-icon="inline-start" />
              Dodaj kolor
            </Button>
          </FormRow>
        </>
      )}
      {dirty ? <LegendPreview edit={edit} /> : null}
      <FormActions
        cancel={() => (removing ? setRemoving(false) : close(null))}
        save={() => void saving.run(request)}
        dirty={dirty}
        saving={saving.running !== null}
        removing={removing}
      >
        {id === null || removing ? null : (
          <Button variant="ghost" className="text-destructive" disabled={saving.running !== null} onClick={() => setRemoving(true)}>
            Usuń kod
          </Button>
        )}
      </FormActions>
    </div>
  )
}

function NumberField({ label, value, change }: { label: string; value: number | null; change: (value: number | null) => void }) {
  return (
    <Input
      type="number"
      min={1}
      aria-label={label}
      className="h-8 w-20 tabular-nums"
      value={value ?? ""}
      onChange={(event) => {
        const typed = Number.parseInt(event.target.value, 10)

        change(Number.isNaN(typed) ? null : typed)
      }}
    />
  )
}
