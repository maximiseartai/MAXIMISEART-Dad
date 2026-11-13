import type { SentenceColumn, SentenceText } from "@/api/generated"
import { Badge } from "@/components/ui/badge"

/** Zdanie Reguły ilości „jeśli … to …” z serwera: tekst i kolumny, każda z nazwą pozycji cennika obok litery. */
export function Sentence({ parts }: { parts: ReadonlyArray<SentenceText | SentenceColumn> }) {
  return parts.map((part, index) =>
    part.kind === "text" ? (
      <span key={index}>{part.text}</span>
    ) : (
      <span key={index} className="whitespace-nowrap">
        {part.name === null ? null : <span className="font-medium">{part.name} </span>}
        <Badge variant="secondary" className="font-mono" aria-label={`kolumna ${part.letter}`}>
          {part.letter}
        </Badge>
      </span>
    )
  )
}

/** Nazwa kolumny dla taty: nazwa pozycji cennika z literą albo sama litera. */
export function columnLabel(column: { letter: string; name: string | null }): string {
  return column.name === null ? column.letter : `${column.name} (${column.letter})`
}
