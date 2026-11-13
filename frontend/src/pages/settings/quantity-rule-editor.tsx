import * as React from "react"
import { ArrowLeftIcon, PlusIcon, XIcon } from "lucide-react"

import { addQuantityRule, changeQuantityRule, removeQuantityRule } from "@/api/centrum"
import type { QuantityRulesSettings, RuleForm, RuleWrite } from "@/api/generated"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Spinner } from "@/components/ui/spinner"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useUnsavedForm } from "@/lib/unsaved"
import { RulePreview } from "@/pages/settings/quantity-rule-preview"
import { useQuantityRulesSave } from "@/pages/settings/quantity-rules-save"
import { columnLabel } from "@/pages/settings/rule-sentence"
import { FieldSentence, SettingsPanel } from "@/pages/settings/setting-row"

type Condition = RuleForm["conditions"][number]

type Action = NonNullable<RuleForm["action"]>

export type Option<T extends string> = { value: T; label: string }

const SCOPES: ReadonlyArray<Option<RuleForm["scope"]>> = [
  { value: "known", label: "Gdy Lista Urządzeń zna każdy składnik" },
  { value: "unknown", label: "Gdy jest składnik spoza listy" },
  { value: "every", label: "Każde zlecenie" },
]

const CONDITIONS: ReadonlyArray<Option<Condition["kind"]>> = [
  { value: "component", label: "URZĄDZENIA zawierają składnik" },
  { value: "devices", label: "URZĄDZENIA" },
  { value: "activities", label: "CZYNNOŚCI zawierają" },
  { value: "contract", label: "UMOWA zaczyna się od słowa" },
  { value: "date", label: "DATA" },
  { value: "group", label: "Zlecenie ma urządzenie z grupy" },
]

const NEGATED: ReadonlyArray<Option<"held" | "negated">> = [
  { value: "held", label: "Gdy" },
  { value: "negated", label: "Ale nie gdy" },
]

const DEVICES_MODES: ReadonlyArray<Option<Extract<Condition, { kind: "devices" }>["mode"]>> = [
  { value: "contains", label: "zawierają tekst" },
  { value: "exactly", label: "to dokładnie" },
  { value: "empty", label: "są puste" },
]

const GROUPS: ReadonlyArray<Option<Extract<Condition, { kind: "group" }>["group"]>> = [
  { value: "router", label: "router" },
  { value: "tv", label: "TV" },
  { value: "extender", label: "extender" },
]

const DAYS = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"] as const

const ACTIONS: ReadonlyArray<Option<Action["kind"]>> = [
  { value: "fill", label: "Wpisz w kolumnę" },
  { value: "nothing", label: "Nic nie wpisuj w tym zleceniu" },
  { value: "leave_empty", label: "Zostaw kolumnę pustą w Rozliczeniu pracownika" },
]

const MULTIPLIERS: ReadonlyArray<Option<RuleWrite["multiplier"]>> = [
  { value: "once", label: "raz na zlecenie" },
  { value: "component", label: "razy liczba składnika" },
  { value: "pieces", label: "razy „N szt” z CZYNNOŚCI" },
]

/** Miejsce zdania odmowy w formularzu: warunek, kolumna działania, samo działanie albo nad formularzem. */
type Place = { kind: "condition"; index: number } | { kind: "write"; index: number } | { kind: "action" } | { kind: "form" }

/** Miejsce pola odmowy serwera (`jesli[0].tekst`, `to.wpisy[1].kolumna`, `to`); bez pola zdanie stoi nad formularzem. */
function placeOf(field: string | null): Place {
  const condition = field?.match(/^jesli\[(\d+)\]/)
  const write = field?.match(/^to\.wpisy\[(\d+)\]/)

  if (condition) {
    return { kind: "condition", index: Number(condition[1]) }
  }

  if (write) {
    return { kind: "write", index: Number(write[1]) }
  }

  return field?.startsWith("to") === true ? { kind: "action" } : { kind: "form" }
}

/**
 * Edytor jednej Reguły ilości w miejscu listy: zakres, warunki („Gdy” albo „Ale nie gdy”), działanie z kolumną po
 * nazwie z cennika i podgląd skutku na ostatnich Plikach zbiorczych. Zapisuje się dopiero przyciskiem „Zapisz”, także
 * przy różnicach z tatą; zła reguła to jedno zdanie przy polu. Okno pyta przed zamknięciem z niezapisaną zmianą, a
 * formularz z różnicy (`prefilled`) jest niezapisany od początku.
 */
export function RuleEditor({
  id,
  initial,
  prefilled = false,
  settings,
  close,
}: {
  id: string | null
  initial: RuleForm
  prefilled?: boolean
  settings: QuantityRulesSettings
  close: (saved: QuantityRulesSettings | null) => void
}) {
  const [rule, setRule] = React.useState<RuleForm>(initial)
  const [removing, setRemoving] = React.useState(false)
  const { saving, refusal, setRefusal } = useQuantityRulesSave(close)
  const dirty = removing || prefilled || JSON.stringify(rule) !== JSON.stringify(initial)

  useUnsavedForm(dirty)

  const request = () =>
    removing && id !== null ? removeQuantityRule(id) : id === null ? addQuantityRule(rule) : changeQuantityRule(id, rule)

  const edit =
    removing && id !== null
      ? ({ kind: "remove", rule_id: id } as const)
      : id === null
        ? ({ kind: "add", rule } as const)
        : ({ kind: "change", rule_id: id, rule } as const)

  const place = placeOf(refusal?.field ?? null)

  const sentenceAt = (here: boolean) => (here && refusal !== null ? <FieldSentence>{refusal.message}</FieldSentence> : undefined)

  const update = (next: RuleForm) => {
    setRule(next)
    setRefusal(null)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon-sm" aria-label="Wróć do Reguł ilości" onClick={() => close(null)}>
          <ArrowLeftIcon />
        </Button>
        <h3 className="text-sm font-medium">{removing ? "Usunąć regułę?" : id === null ? "Nowa reguła" : "Zmiana reguły"}</h3>
      </div>
      {sentenceAt(place.kind === "form")}
      {removing ? null : (
        <>
          <SettingsPanel label="Zakres">
            <div role="listitem" className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
              <span className="min-w-0 flex-1 basis-40 text-sm font-medium">Dla zleceń</span>
              <Choice label="Zakres reguły" value={rule.scope} options={SCOPES} onChange={(scope) => update({ ...rule, scope })} />
            </div>
          </SettingsPanel>
          <Conditions
            rule={rule}
            settings={settings}
            update={update}
            sentenceAt={(index) => sentenceAt(place.kind === "condition" && place.index === index)}
          />
          <ActionPanel
            rule={rule}
            settings={settings}
            update={update}
            sentence={sentenceAt(place.kind === "action")}
            sentenceAt={(index) => sentenceAt(place.kind === "write" && place.index === index)}
          />
        </>
      )}
      <RulePreview edit={edit} />
      <div className="flex flex-wrap items-center gap-2">
        {id === null || removing ? null : (
          <Button variant="ghost" className="text-destructive" onClick={() => setRemoving(true)}>
            Usuń regułę
          </Button>
        )}
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => (removing ? setRemoving(false) : close(null))}>
            {removing ? "Nie usuwaj" : "Anuluj"}
          </Button>
          <Button
            variant={removing ? "destructive" : "default"}
            disabled={!dirty || saving.running !== null}
            onClick={() => void saving.run(request)}
          >
            {saving.running === null ? null : <Spinner data-icon="inline-start" />}
            {removing ? "Usuń" : "Zapisz"}
          </Button>
        </div>
      </div>
    </div>
  )
}

function Conditions({
  rule,
  settings,
  update,
  sentenceAt,
}: {
  rule: RuleForm
  settings: QuantityRulesSettings
  update: (rule: RuleForm) => void
  sentenceAt: (index: number) => React.ReactNode
}) {
  const replaceAt = (index: number, condition: Condition) =>
    update({ ...rule, conditions: rule.conditions.map((old, at) => (at === index ? condition : old)) })

  return (
    <section aria-label="Jeśli" className="flex flex-col gap-2">
      <p aria-hidden className="px-1 text-xs font-medium text-muted-foreground">
        Jeśli
      </p>
      <SettingsPanel label="Warunki">
        {rule.conditions.map((condition, index) => (
          <div key={index} role="listitem" aria-label={`Warunek ${index + 1}`} className="flex flex-col gap-2 px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <Choice
                label="Gdy albo ale nie gdy"
                value={condition.negated === true ? "negated" : "held"}
                options={NEGATED}
                onChange={(negated) => replaceAt(index, { ...condition, negated: negated === "negated" })}
              />
              <Choice
                label="Rodzaj warunku"
                value={condition.kind}
                options={CONDITIONS}
                onChange={(kind) => replaceAt(index, { ...conditionOf(kind, settings), negated: condition.negated })}
              />
              <ConditionFields condition={condition} settings={settings} change={(next) => replaceAt(index, next)} />
              <Button
                variant="ghost"
                size="icon-sm"
                className="ml-auto text-muted-foreground"
                aria-label={`Usuń warunek ${index + 1}`}
                onClick={() => update({ ...rule, conditions: rule.conditions.filter((_, at) => at !== index) })}
              >
                <XIcon />
              </Button>
            </div>
            {sentenceAt(index)}
          </div>
        ))}
        <div role="listitem" className="px-2 py-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => update({ ...rule, conditions: [...rule.conditions, conditionOf("component", settings)] })}
          >
            <PlusIcon data-icon="inline-start" />
            Dodaj warunek
          </Button>
        </div>
      </SettingsPanel>
    </section>
  )
}

function conditionOf(kind: Condition["kind"], settings: QuantityRulesSettings): Condition {
  switch (kind) {
    case "component":
      return { kind, component: settings.devices[0]?.id ?? "", negated: false }
    case "devices":
      return { kind, mode: "contains", text: "", negated: false }
    case "activities":
      return { kind, text: "", negated: false }
    case "contract":
      return { kind, word: "", negated: false }
    case "date":
      return { kind, days: [0, 1, 2, 3, 4], since: "17:00", negated: false }
    case "group":
      return { kind, group: "router", negated: false }
    default: {
      const unhandled: never = kind

      return unhandled
    }
  }
}

function ConditionFields({
  condition,
  settings,
  change,
}: {
  condition: Condition
  settings: QuantityRulesSettings
  change: (condition: Condition) => void
}) {
  switch (condition.kind) {
    case "component":
      return (
        <Choice
          label="Składnik"
          value={condition.component}
          options={settings.devices.map((device) => ({ value: device.id, label: device.name }))}
          onChange={(component) => change({ ...condition, component })}
        />
      )
    case "devices":
      return (
        <>
          <Choice label="Jak" value={condition.mode} options={DEVICES_MODES} onChange={(mode) => change({ ...condition, mode, text: mode === "empty" ? "" : condition.text })} />
          {condition.mode === "empty" ? null : (
            <TextField label="Tekst URZĄDZENIA" value={condition.text ?? ""} change={(text) => change({ ...condition, text })} />
          )}
        </>
      )
    case "activities":
      return <TextField label="Tekst CZYNNOŚCI" value={condition.text} change={(text) => change({ ...condition, text })} />
    case "contract":
      return <TextField label="Słowo UMOWA" value={condition.word} change={(word) => change({ ...condition, word })} />
    case "date":
      return (
        <>
          <ToggleGroup
            aria-label="Dni tygodnia"
            variant="outline"
            size="sm"
            spacing={0}
            multiple
            value={condition.days.map(String)}
            onValueChange={(days: string[]) => change({ ...condition, days: days.map(Number).toSorted((a, b) => a - b) })}
          >
            {DAYS.map((day, index) => (
              <ToggleGroupItem key={day} value={String(index)} aria-label={day} className="w-9">
                {day}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <span className="text-sm text-muted-foreground">od</span>
          <Input
            type="time"
            aria-label="Od godziny"
            className="h-8 w-28 tabular-nums"
            value={condition.since}
            onChange={(event) => change({ ...condition, since: event.target.value })}
          />
        </>
      )
    case "group":
      return <Choice label="Grupa" value={condition.group} options={GROUPS} onChange={(group) => change({ ...condition, group })} />
    default: {
      const unhandled: never = condition

      return unhandled
    }
  }
}

function ActionPanel({
  rule,
  settings,
  update,
  sentence,
  sentenceAt,
}: {
  rule: RuleForm
  settings: QuantityRulesSettings
  update: (rule: RuleForm) => void
  sentence: React.ReactNode
  sentenceAt: (index: number) => React.ReactNode
}) {
  const action = rule.action
  const writable = settings.columns.filter((column) => column.writable)
  const columns = (all: boolean) => (all ? settings.columns : writable).map((column) => ({ value: column.letter, label: columnLabel(column) }))
  const firstComponent = settings.devices[0]?.id ?? null
  const newWrite = (): RuleWrite => ({ column: writable[0]?.letter ?? "", value: 1, multiplier: "once", component: null })

  function actionOf(kind: Action["kind"]): Action {
    switch (kind) {
      case "fill":
        return { kind, writes: [newWrite()] }
      case "nothing":
        return { kind }
      case "leave_empty":
        return { kind, columns: [settings.columns[0]?.letter ?? ""] }
      default: {
        const unhandled: never = kind

        return unhandled
      }
    }
  }

  return (
    <section aria-label="To" className="flex flex-col gap-2">
      <p aria-hidden className="px-1 text-xs font-medium text-muted-foreground">
        To
      </p>
      <SettingsPanel label="Działanie">
        <div role="listitem" className="flex flex-col gap-2 px-4 py-3">
          <Choice
            label="Działanie"
            value={action?.kind ?? null}
            placeholder="Wybierz działanie"
            options={ACTIONS}
            onChange={(kind) => update({ ...rule, action: actionOf(kind) })}
          />
          {sentence}
        </div>
        {action?.kind === "fill"
          ? action.writes.map((write, index) => {
              const replaceWrite = (next: RuleWrite) =>
                update({ ...rule, action: { ...action, writes: action.writes.map((old, at) => (at === index ? next : old)) } })

              return (
                <div key={index} role="listitem" aria-label={`Kolumna ${index + 1}`} className="flex flex-col gap-2 px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Choice label="Kolumna" value={write.column} options={columns(false)} onChange={(column) => replaceWrite({ ...write, column })} />
                    <Input
                      type="number"
                      min={1}
                      aria-label="Wartość"
                      className="h-8 w-20 tabular-nums"
                      value={write.value === 0 ? "" : write.value}
                      onChange={(event) => replaceWrite({ ...write, value: Number.parseInt(event.target.value, 10) || 0 })}
                    />
                    <Choice
                      label="Ile razy"
                      value={write.multiplier}
                      options={MULTIPLIERS}
                      onChange={(multiplier) =>
                        replaceWrite({ ...write, multiplier, component: multiplier === "once" ? null : (write.component ?? firstComponent) })
                      }
                    />
                    {write.multiplier === "once" ? null : (
                      <Choice
                        label="Składnik mnożnika"
                        value={write.component ?? null}
                        options={settings.devices.map((device) => ({ value: device.id, label: device.name }))}
                        onChange={(component) => replaceWrite({ ...write, component })}
                      />
                    )}
                    {action.writes.length === 1 ? null : (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="ml-auto text-muted-foreground"
                        aria-label={`Usuń kolumnę ${index + 1}`}
                        onClick={() => update({ ...rule, action: { ...action, writes: action.writes.filter((_, at) => at !== index) } })}
                      >
                        <XIcon />
                      </Button>
                    )}
                  </div>
                  {sentenceAt(index)}
                </div>
              )
            })
          : null}
        {action?.kind === "leave_empty" ? (
          <div role="listitem" className="flex flex-wrap items-center gap-2 px-4 py-3">
            {action.columns.map((column, index) => (
              <Choice
                key={index}
                label={`Pusta kolumna ${index + 1}`}
                value={column}
                options={columns(true)}
                onChange={(next) => update({ ...rule, action: { ...action, columns: action.columns.map((old, at) => (at === index ? next : old)) } })}
              />
            ))}
          </div>
        ) : null}
        {action?.kind === "fill" || action?.kind === "leave_empty" ? (
          <div role="listitem" className="px-2 py-1.5">
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                update({
                  ...rule,
                  action:
                    action.kind === "fill"
                      ? { ...action, writes: [...action.writes, newWrite()] }
                      : { ...action, columns: [...action.columns, settings.columns[0]?.letter ?? ""] },
                })
              }
            >
              <PlusIcon data-icon="inline-start" />
              Dodaj kolumnę
            </Button>
          </div>
        ) : null}
      </SettingsPanel>
    </section>
  )
}

function TextField({ label, value, change }: { label: string; value: string; change: (value: string) => void }) {
  return <Input aria-label={label} className="h-8 w-48 min-w-0 flex-1 basis-40" value={value} onChange={(event) => change(event.target.value)} />
}

/** Wybór z listy: jedna wartość z opcji, a bez wartości napis zachęty. */
export function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
  placeholder,
}: {
  label: string
  value: T | null
  options: ReadonlyArray<Option<T>>
  onChange: (value: T) => void
  placeholder?: string
}) {
  return (
    <Select
      items={options}
      value={value}
      onValueChange={(next) => {
        const chosen = options.find((option) => option.value === next)

        if (chosen !== undefined) {
          onChange(chosen.value)
        }
      }}
    >
      <SelectTrigger aria-label={label} className="max-w-full min-w-0">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="w-auto min-w-(--anchor-width)">
        <SelectGroup>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
