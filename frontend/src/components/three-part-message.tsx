import type * as React from "react"
import { cn } from "cn"
import {
  CircleAlertIcon,
  CircleStopIcon,
  InfoIcon,
  MapPinIcon,
  OctagonXIcon,
  StethoscopeIcon,
  TriangleAlertIcon,
  WrenchIcon,
} from "lucide-react"

import type { Message } from "@/api/generated"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { settingsHref } from "@/lib/address"

/**
 * Rodzaj banera Komunikatu: `stop` to błąd, `to_fix` Zatrzymanie, które tata poprawia sam, `declined` jego odmowa,
 * a `notice` Komunikat o pliku poza Uruchomieniem.
 */
export type MessageKind = "stop" | "to_fix" | "declined" | "warning" | "diagnosis" | "notice"

type Look = { label: string; icon: React.ReactNode; variant: "default" | "destructive"; className?: string }

// Czerwień tylko przy błędzie. Zatrzymanie do poprawy jest żółte, ale innym znakiem niż ostrzeżenie, a odmowa taty,
// wyjaśnienie Diagnozy i Komunikat o pliku poza Uruchomieniem są spokojne.
const LOOKS: Record<MessageKind, Look> = {
  stop: { label: "Zatrzymanie", icon: <OctagonXIcon />, variant: "destructive" },
  to_fix: {
    label: "Zatrzymanie do poprawy",
    icon: <CircleAlertIcon className="text-warning!" />,
    variant: "default",
    className: "border-warning/50",
  },
  declined: {
    label: "Zatrzymanie po odmowie",
    icon: <CircleStopIcon className="text-muted-foreground!" />,
    variant: "default",
  },
  warning: { label: "Ostrzeżenie", icon: <TriangleAlertIcon className="text-warning!" />, variant: "default" },
  diagnosis: {
    label: "Wyjaśnienie Diagnozy",
    icon: <StethoscopeIcon className="text-muted-foreground!" />,
    variant: "default",
  },
  notice: { label: "Komunikat", icon: <InfoIcon className="text-muted-foreground!" />, variant: "default" },
}

/** Komunikat w trzech częściach jako baner; opis jest spokojny, nie cały czerwony. */
export function ThreePartMessage({
  message,
  kind,
  action,
}: {
  message: Message
  kind: MessageKind
  action?: React.ReactNode
}) {
  return (
    <Banner kind={kind}>
      <AlertTitle className="leading-snug data-[action=true]:pr-48" data-action={action !== undefined}>
        {message.what}
      </AlertTitle>
      <AlertDescription className="mt-2 flex flex-col gap-1.5 text-foreground/80!">
        <WhereAndAction message={message} />
      </AlertDescription>
      {action === undefined ? null : <AlertAction className="top-3 right-3">{action}</AlertAction>}
    </Banner>
  )
}

/** Zatrzymanie na karcie wyniku; akcje stoją w jednym rzędzie pod Komunikatem, bo przy pliku do otwarcia są dwie. */
export function StopMessage({
  message,
  kind,
  title,
  notes,
  actions,
}: {
  message: Message
  kind: Extract<MessageKind, "stop" | "to_fix" | "declined">
  title: string
  notes: ReadonlyArray<string>
  actions: React.ReactNode
}) {
  return (
    <Banner kind={kind}>
      <AlertTitle className="text-base leading-snug">{title}</AlertTitle>
      <AlertDescription className="mt-1 flex flex-col gap-1.5 text-foreground/80!">
        {notes.map((note) => (
          <span key={note} className="text-muted-foreground">
            {note}
          </span>
        ))}
        <span className="mt-1 font-medium text-foreground">{message.what}</span>
        <WhereAndAction message={message} />
        <span className="mt-2 flex flex-wrap gap-2">{actions}</span>
      </AlertDescription>
    </Banner>
  )
}

function Banner({ kind, children }: { kind: MessageKind; children: React.ReactNode }) {
  const look = LOOKS[kind]

  return (
    <Alert variant={look.variant} className={cn("wejscie p-4", look.className)} aria-label={look.label}>
      {look.icon}
      {children}
    </Alert>
  )
}

/** Gdzie i Co zrobić; poprawka w oknie Ustawień (`setting`) ma przy „Co zrobić” link do swojej sekcji. */
export function WhereAndAction({ message }: { message: Message }) {
  return (
    <>
      <span className="flex gap-2">
        <MapPinIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Gdzie" />
        {message.where}
      </span>
      <span className="flex gap-2">
        <WrenchIcon className="mt-1 size-3.5 shrink-0 text-muted-foreground" aria-label="Co zrobić" />
        <span>
          {message.action}
          {message.setting == null ? null : (
            <>
              {" "}
              <a
                href={settingsHref(message.setting)}
                className="font-medium whitespace-nowrap text-foreground underline underline-offset-4"
              >
                Otwórz w Ustawieniach
              </a>
            </>
          )}
        </span>
      </span>
    </>
  )
}
