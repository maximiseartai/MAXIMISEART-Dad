import * as React from "react"
import { PencilIcon, PlusIcon, XIcon } from "lucide-react"

import { addDevice, changeDevice, getDeviceSuggestions, removeDevice } from "@/api/centrum"
import type { ComponentForm, DeviceComponent, DeviceSuggestion, QuantityRulesSettings } from "@/api/generated"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { plural } from "@/lib/format"
import { useReloadOnChange } from "@/lib/settings"
import { useResource } from "@/lib/use-resource"
import { useUnsavedForm } from "@/lib/unsaved"
import { Choice, type Option } from "@/pages/settings/quantity-rule-editor"
import { useQuantityRulesSave } from "@/pages/settings/quantity-rules-save"
import { Problem, WithQuantityRules } from "@/pages/settings/quantity-rules-section"
import { FieldSentence, SettingsPanel } from "@/pages/settings/setting-row"

type Group = NonNullable<DeviceComponent["group"]>

const GROUP_NAMES: Record<Group, string> = { router: "Router", tv: "TV", extender: "Extender" }

const GROUPS: ReadonlyArray<Option<Group | "none">> = [
  { value: "none", label: "Bez grupy" },
  { value: "router", label: "Router" },
  { value: "tv", label: "TV" },
  { value: "extender", label: "Extender" },
]

/** Wybór „Dodaj do” przy podpowiedzi: nowy składnik albo id składnika z listy. */
const NEW = "nowy"

/**
 * Składnik w formularzu: `id` `null` to nowy składnik; `suggestion`: zapis z podpowiedzi, przy której stoi formularz.
 */
type Editing = { id: string | null; form: ComponentForm; suggestion: string | null }

function formOf(device: DeviceComponent): ComponentForm {
  return { name: device.name, other_spellings: device.other_spellings, group: device.group }
}

/**
 * Lista Urządzeń: składniki URZĄDZENIA, które znają Reguły ilości, z innymi zapisami i grupą. Ołówek przy składniku i
 * „Dodaj składnik” otwierają formularz w miejscu wiersza; pod listą zapisy z ostatnich okresów, których lista nie zna,
 * z „Dodaj” jako nowy składnik albo inny zapis istniejącego.
 */
export function DevicesSection() {
  const [editing, setEditing] = React.useState<Editing | null>(null)

  return (
    <WithQuantityRules>
      {(settings, saved) => {
        const close = (next: QuantityRulesSettings | null) => {
          if (next !== null) {
            saved(next)
          }

          setEditing(null)
        }

        const editor = (shown: Editing) => (
          <DeviceEditor
            key={`${shown.suggestion ?? ""}:${shown.id ?? NEW}`}
            editing={shown}
            devices={settings.devices}
            retarget={setEditing}
            close={close}
          />
        )

        return (
          <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <p className="min-w-0 flex-1 basis-64 text-sm text-pretty text-muted-foreground">
                Nowy zapis z INTERMAX dopisz do składnika ołówkiem. Działa od następnego Przygotowania pliku zbiorczego.
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setEditing({ id: null, form: { name: "", other_spellings: [], group: null }, suggestion: null })}
              >
                <PlusIcon data-icon="inline-start" />
                Dodaj składnik
              </Button>
            </div>
            <Problem problem={settings.devices_problem} />
            <SettingsPanel label="Lista Urządzeń">
              {settings.devices.map((device) =>
                editing !== null && editing.suggestion === null && editing.id === device.id ? (
                  editor(editing)
                ) : (
                  <DeviceRow
                    key={device.id}
                    device={device}
                    edit={() => setEditing({ id: device.id, form: formOf(device), suggestion: null })}
                  />
                )
              )}
              {editing !== null && editing.suggestion === null && editing.id === null ? editor(editing) : null}
            </SettingsPanel>
            <Suggestions
              editing={editing?.suggestion ?? null}
              editor={editing === null ? null : editor(editing)}
              add={(spelling) => setEditing({ id: null, form: { name: spelling, other_spellings: [], group: null }, suggestion: spelling })}
            />
          </div>
        )
      }}
    </WithQuantityRules>
  )
}

function DeviceRow({ device, edit }: { device: DeviceComponent; edit: () => void }) {
  return (
    <div role="listitem" aria-label={device.name} className="flex items-center gap-4 px-4 py-3">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-sm font-medium">{device.name}</span>
        {device.other_spellings.length === 0 ? null : (
          <span className="text-sm text-pretty text-muted-foreground">Też: {device.other_spellings.join(", ")}</span>
        )}
      </div>
      {device.group === null ? null : <Badge variant="outline">{GROUP_NAMES[device.group]}</Badge>}
      <Button variant="ghost" size="icon-sm" className="shrink-0 text-muted-foreground" aria-label={`Zmień ${device.name}`} onClick={edit}>
        <PencilIcon />
      </Button>
    </div>
  )
}

/**
 * Formularz składnika: nazwa, inne zapisy i grupa. Zapisuje się dopiero przyciskiem „Zapisz”; zła wartość to jedno
 * zdanie przy polu, a odmowa usunięcia mówi, która reguła potrzebuje składnika. Przy podpowiedzi tata wybiera, czy
 * zapis to nowy składnik, czy inny zapis składnika z listy.
 */
function DeviceEditor({
  editing,
  devices,
  retarget,
  close,
}: {
  editing: Editing
  devices: ReadonlyArray<DeviceComponent>
  retarget: (editing: Editing) => void
  close: (saved: QuantityRulesSettings | null) => void
}) {
  const [form, setForm] = React.useState<ComponentForm>(editing.form)
  const { saving, refusal, setRefusal } = useQuantityRulesSave(close)
  const { id, suggestion } = editing
  const dirty = suggestion !== null || JSON.stringify(form) !== JSON.stringify(editing.form)

  useUnsavedForm(dirty)

  const update = (next: ComponentForm) => {
    setForm(next)
    setRefusal(null)
  }

  const sentenceAt = (field: string | null) =>
    refusal !== null && refusal.field === field ? <FieldSentence>{refusal.message}</FieldSentence> : null

  const targets: ReadonlyArray<Option<string>> = [
    { value: NEW, label: "Nowy składnik" },
    ...devices.map((device) => ({ value: device.id, label: `Inny zapis: ${device.name}` })),
  ]

  const target = (value: string) => {
    const device = devices.find((found) => found.id === value)

    retarget(
      device === undefined || suggestion === null
        ? { id: null, form: { name: suggestion ?? "", other_spellings: [], group: null }, suggestion }
        : { id: device.id, form: { ...formOf(device), other_spellings: [...device.other_spellings, suggestion] }, suggestion }
    )
  }

  return (
    <div role="listitem" aria-label={id === null ? "Nowy składnik" : `Zmiana ${editing.form.name}`} className="flex flex-col gap-3 px-4 py-3.5">
      {sentenceAt(null)}
      {suggestion === null ? null : (
        <Row label="Dodaj jako">
          <Choice label="Dodaj jako" value={id ?? NEW} options={targets} onChange={target} />
        </Row>
      )}
      <Row label="Nazwa">
        <Input aria-label="Nazwa" value={form.name} onChange={(event) => update({ ...form, name: event.target.value })} />
      </Row>
      {sentenceAt("nazwa")}
      {form.other_spellings.map((spelling, index) => (
        <React.Fragment key={index}>
          <Row label={index === 0 ? "Inne zapisy" : ""}>
            <div className="flex w-full items-center gap-1">
              <Input
                aria-label={`Inny zapis ${index + 1}`}
                value={spelling}
                onChange={(event) =>
                  update({ ...form, other_spellings: form.other_spellings.map((old, at) => (at === index ? event.target.value : old)) })
                }
              />
              <Button
                variant="ghost"
                size="icon-sm"
                className="text-muted-foreground"
                aria-label={`Usuń zapis ${index + 1}`}
                onClick={() => update({ ...form, other_spellings: form.other_spellings.filter((_, at) => at !== index) })}
              >
                <XIcon />
              </Button>
            </div>
          </Row>
          {sentenceAt(`zapisy[${index}]`)}
        </React.Fragment>
      ))}
      <Row label={form.other_spellings.length === 0 ? "Inne zapisy" : ""}>
        <Button variant="ghost" size="sm" onClick={() => update({ ...form, other_spellings: [...form.other_spellings, ""] })}>
          <PlusIcon data-icon="inline-start" />
          Dodaj zapis
        </Button>
      </Row>
      <Row label="Grupa">
        <Choice label="Grupa" value={form.group ?? "none"} options={GROUPS} onChange={(group) => update({ ...form, group: group === "none" ? null : group })} />
      </Row>
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {id === null || suggestion !== null ? null : (
          <Button variant="ghost" className="text-destructive" disabled={saving.running !== null} onClick={() => void saving.run(() => removeDevice(id))}>
            Usuń składnik
          </Button>
        )}
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => close(null)}>
            Anuluj
          </Button>
          <Button disabled={!dirty || saving.running !== null} onClick={() => void saving.run(() => (id === null ? addDevice(form) : changeDevice(id, form)))}>
            {saving.running === null ? null : <Spinner data-icon="inline-start" />}
            Zapisz
          </Button>
        </div>
      </div>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1.5">
      <span aria-hidden className="min-w-0 basis-28 text-sm text-muted-foreground">
        {label}
      </span>
      <div className="flex min-w-0 flex-1 basis-56 items-center">{children}</div>
    </div>
  )
}

/**
 * Zapisy z URZĄDZENIA zleceń bez reguły w ostatnich okresach, których Lista Urządzeń nie zna; po dodaniu znikają, bo
 * każda przyjęta zmiana Ustawień czyta je od nowa. Bez podpowiedzi sekcja ich nie pokazuje.
 */
function Suggestions({
  editing,
  editor,
  add,
}: {
  editing: string | null
  editor: React.ReactNode
  add: (spelling: string) => void
}) {
  const { resource, reload } = useResource(getDeviceSuggestions, [])

  useReloadOnChange(reload)

  if (resource.state !== "ready" || resource.data.suggestions.length === 0) {
    return null
  }

  return (
    <section aria-label="Z ostatnich okresów" className="flex flex-col gap-2">
      <p aria-hidden className="px-1 text-xs font-medium text-muted-foreground">
        Z ostatnich okresów, spoza listy
      </p>
      <SettingsPanel label="Z ostatnich okresów">
        {resource.data.suggestions.map((suggestion) =>
          editing === suggestion.spelling ? (
            <React.Fragment key={suggestion.spelling}>{editor}</React.Fragment>
          ) : (
            <SuggestionRow key={suggestion.spelling} suggestion={suggestion} add={() => add(suggestion.spelling)} />
          )
        )}
      </SettingsPanel>
    </section>
  )
}

function SuggestionRow({ suggestion, add }: { suggestion: DeviceSuggestion; add: () => void }) {
  return (
    <div role="listitem" aria-label={suggestion.spelling} className="flex items-center gap-4 px-4 py-3">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-sm font-medium">{suggestion.spelling}</span>
        <span className="text-sm text-muted-foreground">
          {suggestion.orders} {plural(suggestion.orders, { one: "zlecenie", few: "zlecenia", many: "zleceń" })} bez reguły
        </span>
      </div>
      <Button variant="outline" size="sm" onClick={add}>
        Dodaj
      </Button>
    </div>
  )
}
