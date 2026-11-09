import type { FillKind, RowState } from "@/api/generated"

/** Tytuł rodzaju Ilości do uzupełnienia, ten sam w podsumowaniu i w tabeli rodzaju; podpowiedź daje serwer. */
export const KIND_TITLES: Record<FillKind, string> = {
  without_rule: "Wiersze bez reguły",
  from_description: "Wiersze z opisu",
}

/**
 * Słowo stanu wiersza z serwera. `shown`: słowo stoi na ekranie, bo szarego wiersza „bez ilości” nie odróżni się od
 * innych po samym kolorze; pozostałe czyta tylko czytnik ekranu.
 */
export const ROW_STATES: Record<RowState, { label: string; shown: boolean }> = {
  to_fill: { label: "do uzupełnienia", shown: false },
  done: { label: "zrobiony", shown: false },
  without_quantity: { label: "bez ilości", shown: true },
}
