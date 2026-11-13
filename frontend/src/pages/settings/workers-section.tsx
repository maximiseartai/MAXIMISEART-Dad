import * as React from "react"
import { CircleHelpIcon, PlusIcon, RefreshCwIcon, XIcon } from "lucide-react"

import { addWorker, changeWorker, removeWorker, switchWorker } from "@/api/centrum"
import { failureMessage, refusedField } from "@/api/client"
import type { Choice, ListedWorker, WorkerListSetting } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { useSettings } from "@/lib/settings"
import { useUnsavedForm } from "@/lib/unsaved"
import { FieldSentence, SettingsPanel } from "@/pages/settings/setting-row"

type Unresolved = WorkerListSetting["unresolved"][number]

/** Otwarty formularz: zmiana Wykonawcy o loginie `login` albo nowy Wykonawca z loginem i adresami do wpisania. */
type Editing = { kind: "worker"; login: string } | { kind: "new"; login: string; addresses: ReadonlyArray<string> }

const LAST_GOOD = "Ostatnia dobra lista, której używają procesy"

/**
 * Lista Wykonawców (ADR 0032): aktywni na górze, każdy z nazwą, loginami i adresami, przełącznikiem Przypomnień o
 * raporcie zapisanym od razu i formularzem „Edytuj”, który zapisuje się dopiero przyciskiem „Zapisz”. Tata dodaje
 * Wykonawcę, zmienia nazwę i adresy, dopisuje drugi login, oznacza Nieaktywnego i usuwa Wykonawcę bez zleceń w okresach.
 * Każdą regułę sprawdza serwer: zła wartość wraca zdaniem przy polu, a odmowa usunięcia proponuje Nieaktywnego. Nad
 * listą jednym zdaniem to, czego przeniesienie starych plików nie rozstrzygnęło. Zły plik ma zdanie o problemie i
 * ostatnią dobrą listę podpisaną jako ostatnia dobra, a bez niej samo zdanie.
 */
export function WorkersSection() {
  const { settings, reload } = useSettings()

  switch (settings.state) {
    case "loading":
      return <Skeleton className="h-40 w-full rounded-xl" aria-label="Wczytywanie ustawień" />
    case "failed":
      return <LoadFailure what="ustawień" message={settings.message} reload={reload} />
    case "ready":
      return <WorkerList setting={settings.data.workers} reload={reload} />
    default: {
      const unhandled: never = settings

      return unhandled
    }
  }
}

function WorkerList({ setting, reload }: { setting: WorkerListSetting; reload: () => Promise<void> }) {
  const [editing, setEditing] = React.useState<Editing | null>(null)

  if (setting.state === "unreadable") {
    return (
      <div className="flex flex-col items-start gap-3">
        {setting.problem === null ? null : <FieldSentence>{setting.problem.message}</FieldSentence>}
        <Button variant="outline" size="sm" onClick={() => void reload()}>
          <RefreshCwIcon aria-hidden />
          Spróbuj ponownie
        </Button>
      </div>
    )
  }

  const workers = setting.workers.toSorted((first, second) => Number(second.active) - Number(first.active))
  const close = () => setEditing(null)

  return (
    <div className="flex flex-col gap-3">
      {setting.problem === null ? null : <FieldSentence>{setting.problem.message}</FieldSentence>}
      {setting.unresolved.length === 0 ? null : (
        <ul aria-label="Do rozstrzygnięcia" className="flex flex-col gap-1.5">
          {setting.unresolved.map((item) => (
            <li key={unresolvedKey(item)} className="flex items-start gap-2 text-sm text-pretty">
              <CircleHelpIcon className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
              <span className="min-w-0 flex-1">{unresolvedSentence(item)}</span>
              {item.reason === "login_bez_wykonawcy" ? (
                <Button
                  variant="outline"
                  size="xs"
                  onClick={() => setEditing({ kind: "new", login: item.login, addresses: item.addresses })}
                >
                  Dodaj Wykonawcę
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {workers.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          {setting.state === "bad" ? <p className="text-sm text-muted-foreground">{LAST_GOOD}</p> : null}
          <SettingsPanel label="Wykonawcy">
            {workers.map((worker) => (
              <WorkerRow
                key={firstLogin(worker)}
                worker={worker}
                editing={editing?.kind === "worker" && worker.logins.includes(editing.login)}
                onEdit={() => setEditing({ kind: "worker", login: firstLogin(worker) })}
                onClose={close}
              />
            ))}
          </SettingsPanel>
        </div>
      ) : setting.state === "good" ? (
        <p className="text-sm text-muted-foreground">Na liście nie ma jeszcze Wykonawców.</p>
      ) : null}
      {editing?.kind === "new" ? (
        <div className="rounded-xl border bg-card px-4 py-4">
          <WorkerForm key={editing.login} initial={{ logins: [editing.login], name: "", addresses: editing.addresses }} onDone={close} />
        </div>
      ) : (
        <div>
          <Button variant="outline" size="sm" onClick={() => setEditing({ kind: "new", login: "", addresses: [] })}>
            <PlusIcon aria-hidden />
            Dodaj Wykonawcę
          </Button>
        </div>
      )}
    </div>
  )
}

function WorkerRow({
  worker,
  editing,
  onEdit,
  onClose,
}: {
  worker: ListedWorker
  editing: boolean
  onEdit: () => void
  onClose: () => void
}) {
  const { sectionSaved, saveFailed } = useSettings()
  const [pending, setPending] = React.useState<boolean | null>(null)
  const login = firstLogin(worker)

  function switchReminders(reminders: boolean) {
    setPending(reminders)
    switchWorker(login, { reminders }).then(sectionSaved, saveFailed).finally(() => setPending(null))
  }

  return (
    <div role="listitem" aria-label={worker.name} className="flex flex-col gap-3 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-56 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={worker.active ? "text-sm font-medium" : "text-sm font-medium text-muted-foreground"}>
              {worker.name}
            </span>
            {worker.active ? null : <Badge variant="outline">Nieaktywny</Badge>}
          </div>
          <span className="text-sm break-words text-muted-foreground">
            {[...worker.logins, ...worker.addresses].join(" · ")}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <Label className="gap-2 text-sm font-normal text-muted-foreground">
            Przypomnienia
            <Switch
              aria-label={`Przypomnienia: ${worker.name}`}
              checked={pending ?? worker.reminders}
              disabled={pending !== null}
              onCheckedChange={switchReminders}
            />
          </Label>
          {editing ? null : (
            <Button variant="ghost" size="sm" aria-label={`Edytuj: ${worker.name}`} onClick={onEdit}>
              Edytuj
            </Button>
          )}
        </div>
      </div>
      {editing ? <WorkerForm worker={worker} initial={worker} onDone={onClose} /> : null}
    </div>
  )
}

type FormValues = { logins: ReadonlyArray<string>; name: string; addresses: ReadonlyArray<string> }

/** Odmowa przy polu formularza (`nazwa`, `adresy[1]`, `loginy[0]`) albo bez pola, pod formularzem. */
type Refusal = { field: string | null; message: string }

/**
 * Formularz Wykonawcy: zapisane loginy bez pola tekstowego, bo zapisanego loginu nie da się przepisać, tylko usunąć (×)
 * albo dopisać nowy; nazwa i adresy. „Zapisz” wysyła wszystko naraz. Zmiana nazwy przy Rozliczeniu pracownika ze starą
 * nazwą pyta najpierw o potwierdzenie zdaniem serwera; niezapisany formularz pyta przy zamknięciu okna Ustawień.
 */
function WorkerForm({ worker, initial, onDone }: { worker?: ListedWorker; initial: FormValues; onDone: () => void }) {
  const { sectionSaved } = useSettings()
  const saved = worker?.logins ?? []
  const [kept, setKept] = React.useState<ReadonlyArray<string>>(saved)
  const [added, setAdded] = React.useState<ReadonlyArray<string>>(worker === undefined ? initial.logins : [])
  const [name, setName] = React.useState(initial.name)
  const [addresses, setAddresses] = React.useState<ReadonlyArray<string>>(initial.addresses)
  const [refusal, setRefusal] = React.useState<Refusal | null>(null)
  const [warning, setWarning] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState<"save" | "remove" | "active" | null>(null)

  const logins = [...kept, ...added]

  const dirty =
    worker === undefined
      ? logins.some((login) => login.trim() !== "") || name.trim() !== "" || addresses.length > 0
      : kept.length !== saved.length || added.length > 0 || name !== initial.name || addresses.join("\n") !== initial.addresses.join("\n")

  useUnsavedForm(dirty)

  // Każda porażka zapisu stoi zdaniem przy formularzu: przy polu, gdy serwer je wskazał, inaczej pod formularzem.
  function refused(failure: Error) {
    setRefusal({ field: refusedField(failure), message: failureMessage(failure) })
  }

  function done(choice: Choice) {
    sectionSaved(choice)
    onDone()
  }

  function save(renameConfirmed: boolean) {
    setBusy("save")
    setRefusal(null)

    const form = { logins, name, addresses: [...addresses] }

    const request =
      worker === undefined
        ? addWorker(form).then(done)
        : changeWorker(firstLogin(worker), { ...form, rename_confirmed: renameConfirmed }).then((answer) => {
            if (answer.rename_warning === null || answer.rename_warning === undefined) {
              done(answer)
            } else {
              setWarning(answer.rename_warning)
            }
          })

    void request.catch(refused).finally(() => setBusy(null))
  }

  function remove(target: ListedWorker) {
    setBusy("remove")
    setRefusal(null)
    void removeWorker(firstLogin(target)).then(done, refused).finally(() => setBusy(null))
  }

  function switchActive(target: ListedWorker) {
    setBusy("active")
    setRefusal(null)
    void switchWorker(firstLogin(target), { active: !target.active })
      .then(sectionSaved, refused)
      .finally(() => setBusy(null))
  }

  const at = (field: string) => (refusal?.field === field ? refusal.message : null)
  const loginRefusal = logins.map((_, index) => at(`loginy[${index}]`)).find((message) => message !== null) ?? at("loginy")
  const general = refusal !== null && !/^(nazwa|loginy|adresy)/.test(refusal.field ?? "") ? refusal.message : null

  return (
    <form
      aria-label={worker === undefined ? "Nowy Wykonawca" : `Wykonawca ${worker.name}`}
      className="flex flex-col gap-4 border-t pt-4"
      onSubmit={(event) => {
        event.preventDefault()
        save(false)
      }}
    >
      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">{worker === undefined ? "Login z INTERMAX" : "Loginy"}</span>
        <div className="flex flex-wrap items-center gap-2">
          {kept.map((login) => (
            <Badge key={login} variant="secondary" className="gap-1 pr-1">
              {login}
              {kept.length + added.length > 1 ? (
                <button
                  type="button"
                  aria-label={`Usuń login ${login}`}
                  className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
                  onClick={() => setKept(kept.filter((other) => other !== login))}
                >
                  <XIcon className="size-3" aria-hidden />
                </button>
              ) : null}
            </Badge>
          ))}
          {added.map((login, index) => (
            <Input
              key={index}
              aria-label={worker === undefined && index === 0 ? "Login" : "Nowy login"}
              aria-invalid={at(`loginy[${kept.length + index}]`) === null ? undefined : true}
              className="h-7 w-44"
              spellCheck={false}
              value={login}
              onChange={(event) => setAdded(added.map((other, place) => (place === index ? event.target.value : other)))}
            />
          ))}
          {worker === undefined ? null : (
            <Button type="button" variant="ghost" size="xs" onClick={() => setAdded([...added, ""])}>
              <PlusIcon aria-hidden />
              Dodaj login
            </Button>
          )}
        </div>
        {loginRefusal === null ? null : <FieldSentence>{loginRefusal}</FieldSentence>}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`nazwa-${saved[0] ?? "nowy"}`}>Nazwa w Rozliczeniu pracownika</Label>
        <Input
          id={`nazwa-${saved[0] ?? "nowy"}`}
          aria-invalid={at("nazwa") === null ? undefined : true}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        {at("nazwa") === null ? null : <FieldSentence>{at("nazwa")}</FieldSentence>}
      </div>
      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">Adresy</span>
        {addresses.map((address, index) => (
          <div key={index} className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <Input
                type="email"
                aria-label={`Adres ${index + 1}`}
                aria-invalid={at(`adresy[${index}]`) === null ? undefined : true}
                spellCheck={false}
                value={address}
                onChange={(event) => setAddresses(addresses.map((other, place) => (place === index ? event.target.value : other)))}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={`Usuń adres ${index + 1}`}
                onClick={() => setAddresses(addresses.filter((_, place) => place !== index))}
              >
                <XIcon aria-hidden />
              </Button>
            </div>
            {at(`adresy[${index}]`) === null ? null : <FieldSentence>{at(`adresy[${index}]`)}</FieldSentence>}
          </div>
        ))}
        <div>
          <Button type="button" variant="ghost" size="xs" onClick={() => setAddresses([...addresses, ""])}>
            <PlusIcon aria-hidden />
            Dodaj adres
          </Button>
        </div>
      </div>
      {general === null ? null : <FieldSentence>{general}</FieldSentence>}
      <div className="flex flex-wrap items-center gap-2">
        {worker === undefined ? null : (
          <>
            <Button type="button" variant="ghost" size="sm" disabled={busy !== null} onClick={() => switchActive(worker)}>
              {busy === "active" ? <Spinner data-icon="inline-start" /> : null}
              {worker.active ? "Oznacz jako nieaktywnego" : "Oznacz jako aktywnego"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              disabled={busy !== null}
              onClick={() => remove(worker)}
            >
              {busy === "remove" ? (
                <>
                  <Spinner data-icon="inline-start" />
                  Sprawdzam okresy…
                </>
              ) : (
                "Usuń Wykonawcę"
              )}
            </Button>
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onDone}>
            Anuluj
          </Button>
          <Button type="submit" size="sm" disabled={busy !== null || !dirty} aria-label="Zapisz Wykonawcę">
            {busy === "save" ? <Spinner data-icon="inline-start" /> : null}
            Zapisz
          </Button>
        </div>
      </div>
      <AlertDialog open={warning !== null} onOpenChange={(open) => (open ? null : setWarning(null))}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Zmienić nazwę?</AlertDialogTitle>
            <AlertDialogDescription>{warning}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Wróć</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setWarning(null)
                save(true)
              }}
            >
              Zmień nazwę
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </form>
  )
}

/** Login, po którym serwer zna Wykonawcę w adresie zmiany; Lista Wykonawców ma co najmniej jeden login każdego. */
function firstLogin(worker: ListedWorker): string {
  return worker.logins[0] ?? ""
}

function unresolvedKey(item: Unresolved): string {
  return item.reason === "login_bez_wykonawcy" ? item.login : item.message
}

/** Jedno zdanie o sprawie po przeniesieniu starych plików; „login bez Wykonawcy” znika, gdy tata doda Wykonawcę z nim. */
function unresolvedSentence(item: Unresolved): string {
  switch (item.reason) {
    case "login_bez_wykonawcy":
      return `Adresy ${item.addresses.join(", ")} należą do loginu ${item.login}, którego nie ma u żadnego Wykonawcy.`
    case "adresy_nieprzeniesione":
      return item.message
    default: {
      const unhandled: never = item

      return unhandled
    }
  }
}
