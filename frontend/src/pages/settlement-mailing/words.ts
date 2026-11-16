import { plural } from "@/lib/format"

/** `1 rozliczenie`, `3 rozliczenia`, `5 rozliczeń` */
export function settlements(count: number): string {
  return `${count} ${plural(count, { one: "rozliczenie", few: "rozliczenia", many: "rozliczeń" })}`
}

/** Inicjały Wykonawcy do awatara: pierwsze litery dwóch pierwszych słów nazwy. */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter((word) => word !== "")
    .slice(0, 2)
    .map((word) => word[0]?.toLocaleUpperCase("pl-PL") ?? "")
    .join("")
}
