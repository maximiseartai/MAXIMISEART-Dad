// Kopia motywu w przeglądarce tylko na pierwsze malowanie; źródłem prawdy są ustawienia na serwerze.
const THEME_KEY = "centrum-rozliczen-motyw"

/**
 * Motyw (`Theme` z kontraktu) na stronie: klasa `dark` i `color-scheme`. Moduł nie importuje niczego, bo czyta go też
 * `vite.config.ts`, a `FIRST_PAINT_SCRIPT` wkleja kod tej funkcji do `index.html`.
 */
export function showTheme(theme: string) {
  document.documentElement.classList.toggle("dark", theme === "dark")
  document.documentElement.style.colorScheme = theme
}

/** Zapamiętuje motyw na następne pierwsze malowanie; przeglądarka bez pamięci strony pokaże wtedy ciemny. */
export function rememberTheme(theme: string) {
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Pamięć strony wyłączona: motyw i tak przychodzi z ustawień na serwerze, tylko pierwsze malowanie jest ciemne.
  }
}

/**
 * Skrypt `<head>` w `index.html` (wstawia go `vite.config.ts`): motyw ciemny domyślnie, a zapamiętany jasny już przy
 * pierwszym malowaniu, zanim przyjdą ustawienia z serwera.
 */
export const FIRST_PAINT_SCRIPT = `try{if(localStorage.getItem(${JSON.stringify(THEME_KEY)})==="light"){(${showTheme.toString()})("light")}}catch{}`
