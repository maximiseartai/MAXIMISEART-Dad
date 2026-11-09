import * as React from "react"
import { CircleCheckIcon, InfoIcon, PlayIcon, TriangleAlertIcon } from "lucide-react"

import { getWithoutQuantity, type Decision, type DecisionAnswer, type Pricing, type WithoutQuantity } from "@/api/centrum"
import { Disclosure } from "@/components/disclosure"
import { WhereAndAction } from "@/components/three-part-message"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { PRICING } from "@/lib/pricing"
import { useResource } from "@/lib/use-resource"
import { CountTiles } from "@/pages/runs/count-tiles"

/**
 * Potwierdzenie zapisu (RUN): przypomnienie o zamknięciu pliku w Excelu i, gdy w historii metryk nie ma
 * udanego podglądu bez zapisu tego okresu (serwer mówi to w wyborze okresu), bursztynowa uwaga. Bez
 * podglądu „Uruchom” jest dozwolone.
 * Gdy proces deklaruje, że „Uruchom” potwierdza Gotowość (Przebieg rozliczeń), okno to mówi i wymienia
 * wiersze Pliku zbiorczego bez ilości; to tylko informacja, „Uruchom” zostaje dozwolone.
 * Start Wyceny w efenix (`pricing`) pyta o wybrany tryb słowami jego przycisku, bo „z zapisem” znaczy tam zielony
 * „Zapisz” w efenix.
 */
export function ConfirmRunDialog({
  open,
  onOpenChange,
  title,
  period,
  reminder,
  confirmsReadiness,
  previewed,
  pricing = null,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  period: string
  reminder: string
  confirmsReadiness: boolean
  previewed: boolean
  pricing?: Pricing | null
  onConfirm: () => void
}) {
  const mode = pricing === null ? null : PRICING[pricing]

  // Czytane, gdy karta pokazuje okres, a nie dopiero po „Uruchom”: odczyt trwa u taty ponad sekundę.
  const withoutQuantity = useWithoutQuantity(confirmsReadiness ? period : null)

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogMedia>{mode === null ? <PlayIcon /> : <mode.icon />}</AlertDialogMedia>
          <AlertDialogTitle>{mode === null ? "Uruchomić z zapisem?" : mode.question}</AlertDialogTitle>
          <AlertDialogDescription className="tabular-nums">
            {title} · okres {period}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-2 text-sm">
          <span className="flex items-center gap-2">
            <InfoIcon className="size-4 text-muted-foreground" aria-hidden />
            {reminder}
          </span>
          {mode === null ? null : (
            <span className="flex items-center gap-2">
              <mode.icon className="size-4 text-muted-foreground" aria-hidden />
              {mode.hint}
            </span>
          )}
          {confirmsReadiness ? (
            <span className="flex items-center gap-2">
              <CircleCheckIcon className="size-4 text-muted-foreground" aria-hidden />
              „Uruchom” potwierdza Gotowość Pliku zbiorczego
            </span>
          ) : null}
          <WithoutQuantityLine withoutQuantity={withoutQuantity} />
          {previewed ? null : (
            <span className="flex items-center gap-2 text-warning">
              <TriangleAlertIcon className="size-4" aria-hidden />
              Nie było podglądu bez zapisu
            </span>
          )}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Anuluj</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              onOpenChange(false)
              onConfirm()
            }}
          >
            {mode === null ? "Uruchom" : mode.label}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

const UNREAD: WithoutQuantity = { state: "unread" }

function withoutQuantityOf(period: string | null): Promise<WithoutQuantity | null> {
  return period === null ? Promise.resolve(null) : getWithoutQuantity(period)
}

/**
 * Wiersze bez ilości okresu `period`, czytane od nowa po powrocie do karty (np. z Excela); `null`, dopóki nie ma
 * odpowiedzi dla tego okresu. Odczyt, który się nie udał, jest jak Plik zbiorczy bez odczytu.
 */
function useWithoutQuantity(period: string | null): WithoutQuantity | null {
  const { resource } = useResource(withoutQuantityOf, [period])

  if (resource.state === "failed") {
    return UNREAD
  }

  return resource.state === "ready" ? resource.data : null
}

/** Plik zbiorczy bez odczytu też jest wymieniony, żeby cisza nie znaczyła „nic nie zostało”. */
function WithoutQuantityLine({ withoutQuantity }: { withoutQuantity: WithoutQuantity | null }) {
  if (withoutQuantity === null || (withoutQuantity.state === "read" && withoutQuantity.sentence === null)) {
    return null
  }

  if (withoutQuantity.state === "unread") {
    return (
      <span className="flex items-center gap-2 text-muted-foreground">
        <InfoIcon className="size-4" aria-hidden />
        Nie udało się sprawdzić wierszy bez ilości
      </span>
    )
  }

  return (
    <span className="flex items-start gap-2 text-warning tabular-nums">
      <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
      {withoutQuantity.sentence}
    </span>
  )
}

/**
 * Decyzja taty, na którą czeka Uruchomienie procesu (np. niepełny okres). Okno trwa tak długo, jak
 * serwer czeka, więc wraca po odświeżeniu karty. Fokus startuje na bezpiecznej opcji „Przerwij bez zapisu”.
 * Po wysłanej decyzji przyciski czekają, aż okno zniknie (`deciding`).
 */
export function DecisionDialog({
  decision,
  deciding,
  onDecide,
}: {
  decision: Decision
  deciding: boolean
  onDecide: (answer: DecisionAnswer["answer"]) => void
}) {
  const abort = React.useRef<HTMLButtonElement>(null)
  const message = decision.message

  return (
    <AlertDialog open>
      <AlertDialogContent initialFocus={abort} className="data-[size=default]:sm:max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogMedia className="text-warning">
            <TriangleAlertIcon />
          </AlertDialogMedia>
          <AlertDialogTitle>{decision.question}</AlertDialogTitle>
          <AlertDialogDescription>{message.what}</AlertDialogDescription>
        </AlertDialogHeader>
        <CountTiles title={decision.counts.title} counts={decision.counts.counts} />
        <Disclosure label="Gdzie i co zrobić" className="text-sm">
          <div className="flex flex-col gap-1.5 pt-2 text-foreground/80">
            <WhereAndAction message={message} />
          </div>
        </Disclosure>
        <AlertDialogFooter>
          <AlertDialogCancel ref={abort} disabled={deciding} onClick={() => onDecide("abort")}>
            Przerwij bez zapisu
          </AlertDialogCancel>
          <AlertDialogAction disabled={deciding} onClick={() => onDecide("continue")}>
            Kontynuuj
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
