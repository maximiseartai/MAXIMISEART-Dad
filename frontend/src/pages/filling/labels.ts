import type { FillKind, RowState } from "@/api/generated"

/** Rodzaj Ilości do uzupełnienia: tytuł i podpowiedź, te same w podsumowaniu i w tabeli rodzaju. */
export const KINDS: Record<FillKind, { title: string; hint: string }> = {
  without_rule: { title: "Wiersze bez reguły", hint: "Dopisz ilości poza V, T i N." },
  from_description: { title: "Wiersze z opisu", hint: "Wpisz ilości według opisu technika." },
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
