import * as React from "react"
import { cn } from "cn"
import { SendIcon } from "lucide-react"

import { failureMessage } from "@/api/client"
import {
  draftDadNote,
  getDadNoteRuns,
  sendDadNote,
  type DadNoteDraft,
  type DadNoteRequest,
  type DadNoteState,
  type PinnableRun,
} from "@/api/centrum"
import { zDadNoteRequest } from "@/api/generated/zod.gen"
import { CaseStateLine } from "@/components/case-state"
import { DadNoteRuns } from "@/components/dad-note-runs"
import { SegmentedFilter, type FilterOption } from "@/components/segmented-filter"
import { Button } from "@/components/ui/button"
import { DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldLabel, FieldTitle } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { useAction } from "@/lib/action"
import { useResource, type Resource } from "@/lib/use-resource"

const TITLE_MAX_LENGTH = zDadNoteRequest.shape.title.toJSONSchema().maxLength

const BODY_MAX_LENGTH = zDadNoteRequest.shape.body.toJSONSchema().maxLength

// Szkic dopiero po krótkiej przerwie w pisaniu: zapytanie na każdy klawisz zapychałoby pomiar widoku.
const DRAFT_PAUSE_MS = 150

// Nieudane zapytanie o szkic wraca po tej przerwie, żeby „Wyślij” nie czekał na następny klawisz taty.
const DRAFT_RETRY_MS = 1000

type Scope = "general" | "run"

const SCOPES: ReadonlyArray<FilterOption<Scope>> = [
  { value: "general", label: "Ogólna" },
  { value: "run", label: "Do Uruchomienia" },
]

/**
 * Jedna Uwaga taty; okno montuje formularz od nowa przy każdym otwarciu. `openedFrom` to Uruchomienie, z którego
 * karty albo wiersza Historii tata otworzył okno: Uwaga jest wtedy od razu „Do Uruchomienia” z nim zaznaczonym.
 */
export function DadNoteForm({ openedFrom, close }: { openedFrom: string | null; close: () => void }) {
  const [title, setTitle] = React.useState("")
  const [body, setBody] = React.useState("")
  const [scope, setScope] = React.useState<Scope>(openedFrom === null ? "general" : "run")
  const [checked, setChecked] = React.useState(openedFrom)
  const [answer, setAnswer] = React.useState<DadNoteState | null>(null)
  const { resource: runs, reload: reloadRuns } = useResource(getDadNoteRuns, [openedFrom], { fresh: true })
  const sending = useAction((sendable: DadNoteRequest) => sendDadNote(sendable).then(setAnswer))
  const note = React.useMemo(() => noteFor(title, body, scope, runs, checked), [title, body, scope, runs, checked])

  const { shown, sendable } = useDraft(note)

  if (answer !== null) {
    return <Answer state={answer} close={close} />
  }

  const send = (event: React.FormEvent) => {
    event.preventDefault()

    if (sendable === null) {
      return
    }

    void sending.run(sendable)
  }

  return (
    <form onSubmit={send} className="flex min-h-0 flex-col gap-5">
      <DialogHeader>
        <DialogTitle>Napisz do Maksa</DialogTitle>
      </DialogHeader>
      {/* Nagłówek i „Wyślij” zostają w oknie. Między nimi wysokość oddają jak dotąd lista Uruchomień i „Maks dostanie”,
          a pola przewijają się dopiero wtedy, gdy obie są najniższe: „Dotyczy” z przełącznikiem i jednym wierszem listy
          (wyżej o zdanie nad listą), podgląd z podpisem i pierwszą linią. `-m-1 p-1` zostawia miejsce na obwódkę fokusu. */}
      <div className="-m-1 flex flex-col gap-5 overflow-y-auto p-1">
        <Field>
          <FieldLabel htmlFor="uwaga-tytul">Tytuł</FieldLabel>
          <Input
            id="uwaga-tytul"
            required
            autoFocus
            maxLength={TITLE_MAX_LENGTH}
            placeholder="Np. Brakuje kolumny z kilometrami"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="uwaga-tresc">
            Treść <span className="font-normal text-muted-foreground">(niekonieczna)</span>
          </FieldLabel>
          <Textarea
            id="uwaga-tresc"
            rows={3}
            maxLength={BODY_MAX_LENGTH}
            className="max-h-48"
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
        </Field>
        <Field className="has-data-[slot=radio-group]:min-h-32 has-[>p+[data-slot=radio-group]]:min-h-44">
          <FieldTitle>Dotyczy</FieldTitle>
          <SegmentedFilter label="Dotyczy" options={SCOPES} value={scope} onChange={setScope} />
          {scope === "run" ? (
            <DadNoteRuns
              runs={runs}
              reload={reloadRuns}
              openedFrom={openedFrom}
              checked={checked}
              onCheck={setChecked}
            />
          ) : null}
        </Field>
        <Preview shown={shown} />
      </div>
      <DialogFooter>
        <Button type="submit" disabled={title.trim() === "" || sendable === null || sending.running !== null}>
          {sending.running !== null ? <Spinner data-icon="inline-start" /> : <SendIcon data-icon="inline-start" />}
          Wyślij
        </Button>
      </DialogFooter>
    </form>
  )
}

/** Uwaga do szkicu i do wysłania; `null`, gdy przy „Do Uruchomienia” nie jest zaznaczone Uruchomienie z listy. */
function noteFor(
  title: string,
  body: string,
  scope: Scope,
  runs: Resource<ReadonlyArray<PinnableRun>>,
  checked: string | null
): DadNoteRequest | null {
  if (scope === "general") {
    return { title, body, run_id: null }
  }

  const pinned = runs.state === "ready" ? runs.data.find((run) => run.run_id === checked) : undefined

  return pinned === undefined ? null : { title, body, run_id: pinned.run_id }
}

type Shown = { kind: "draft"; draft: DadNoteDraft } | { kind: "failure"; message: string }

type Drafted = { note: DadNoteRequest; shown: Shown }

function sameNote(left: DadNoteRequest, right: DadNoteRequest): boolean {
  return left.title === right.title && left.body === right.body && left.run_id === right.run_id
}

/**
 * Szkic issue od serwera dla tego, co tata właśnie napisał i wybrał. Poprzedni szkic zostaje na ekranie, dopóki nie
 * przyjdzie nowszy, a odpowiedź na Uwagę, którą tata już zmienił, przepada. `sendable` to Uwaga, której szkic jest
 * na ekranie, tylko gdy to dokładnie ta, którą wyśle „Wyślij”: tata nigdy nie wyśle czegoś innego, niż widzi.
 * Nieudane zapytanie zostawia powód w „Maks dostanie” i wraca samo, bez Komunikatu.
 */
function useDraft(note: DadNoteRequest | null) {
  const [drafted, setDrafted] = React.useState<Drafted | null>(null)

  React.useEffect(() => {
    if (note === null) {
      return
    }

    let wanted = true
    let pause: number | undefined

    const ask = (after: number) => {
      pause = window.setTimeout(() => {
        draftDadNote(note).then(
          (draft) => {
            if (wanted) {
              setDrafted({ note, shown: { kind: "draft", draft } })
            }
          },
          (failure: Error) => {
            if (wanted) {
              setDrafted({ note, shown: { kind: "failure", message: failureMessage(failure) } })
              ask(DRAFT_RETRY_MS)
            }
          }
        )
      }, after)
    }

    ask(DRAFT_PAUSE_MS)

    return () => {
      wanted = false
      window.clearTimeout(pause)
    }
  }, [note])

  if (note === null || drafted === null) {
    return { shown: null, sendable: null }
  }

  const current = sameNote(drafted.note, note) && drafted.shown.kind === "draft"

  return { shown: drafted.shown, sendable: current ? note : null }
}

/**
 * „Maks dostanie”: tytuł i treść issue tak, jak złożył i pokazuje je serwer, albo powód, dla którego ich nie ma.
 */
function Preview({ shown }: { shown: Shown | null }) {
  const title = shown?.kind === "draft" ? shown.draft.title : ""

  return (
    <figure aria-label="Co dostanie Maks" className="flex min-h-16 flex-col gap-1 overflow-y-auto rounded-lg bg-muted/50 p-3 text-sm">
      <figcaption className="text-xs text-muted-foreground">Maks dostanie</figcaption>
      <p className={cn("font-medium break-words", title === "" && "text-muted-foreground/60")}>
        {title === "" ? "Tytuł" : title}
      </p>
      {shown === null ? null : (
        <p
          className={cn(
            "max-h-48 overflow-y-auto break-words whitespace-pre-wrap",
            shown.kind === "draft" ? "text-muted-foreground" : "text-destructive"
          )}
        >
          {shown.kind === "draft" ? shown.draft.shown_body : shown.message}
        </p>
      )}
    </figure>
  )
}

function Answer({ state, close }: { state: DadNoteState; close: () => void }) {
  return (
    <>
      <DialogTitle className="sr-only">Napisz do Maksa</DialogTitle>
      <div className="wejscie flex flex-col items-center gap-3 py-6 text-center">
        <CaseStateLine
          role="status"
          state={state}
          kind="uwaga"
          className="flex-col gap-3 text-base font-medium"
          iconClassName="size-8"
        />
        <Button variant="outline" className="mt-2" onClick={close}>
          Zamknij
        </Button>
      </div>
    </>
  )
}
