import { PencilLineIcon, SaveIcon, type LucideIcon } from "lucide-react"

import type { Pricing } from "@/api/centrum"

/**
 * Tryb Wyceny w efenix słowami taty: „zapis” to zielony „Zapisz” w efenix, czyli Przekazanie do akceptacji
 * (GLOSSARY).
 */
export const PRICING: Record<Pricing, { label: string; question: string; hint: string; badge: string; icon: LucideIcon }> =
  {
    "bez Przekazania": {
      label: "Uzupełnij bez zapisu",
      question: "Uzupełnić bez zapisu?",
      hint: "Zielony „Zapisz” w efenix klikasz sam",
      badge: "Bez zapisu",
      icon: PencilLineIcon,
    },
    "z Przekazaniem": {
      label: "Uzupełnij i zapisz",
      question: "Uzupełnić i zapisać?",
      hint: "Zielony „Zapisz” przy gotowych klika Centrum",
      badge: "Z zapisem",
      icon: SaveIcon,
    },
  }
