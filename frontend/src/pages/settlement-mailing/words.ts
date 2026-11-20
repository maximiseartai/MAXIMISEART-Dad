import { plural } from "@/lib/format"

export function settlements(count: number): string {
  return `${count} ${plural(count, { one: "rozliczenie", few: "rozliczenia", many: "rozliczeń" })}`
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter((word) => word !== "")
    .slice(0, 2)
    .map((word) => word[0]?.toLocaleUpperCase("pl-PL") ?? "")
    .join("")
}
