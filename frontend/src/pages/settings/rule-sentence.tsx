import type { SentenceColumn, SentenceText } from "@/api/generated"
import { Badge } from "@/components/ui/badge"

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

export function columnLabel(column: { letter: string; name: string | null }): string {
  return column.name === null ? column.letter : `${column.name} (${column.letter})`
}
