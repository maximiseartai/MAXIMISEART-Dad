import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

import { FIRST_PAINT_SCRIPT } from "./src/lib/theme.ts"

// Zbudowany frontend trafia do pakietu Pythona i jest commitowany: u taty nie ma Node.
const CENTRUM = "http://127.0.0.1:47811"

// Motyw na pierwsze malowanie z tego samego modułu, który zmienia go w Centrum (`src/lib/theme.ts`).
const firstPaintTheme: Plugin = {
  name: "motyw-pierwszego-malowania",
  // Przed skryptem i stylem Centrum, które Vite dopisuje do `<head>` przy budowie.
  transformIndexHtml: {
    order: "pre",
    handler: () => [{ tag: "script", children: FIRST_PAINT_SCRIPT, injectTo: "head" }],
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss(), firstPaintTheme],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    outDir: resolve(import.meta.dirname, "../src/rozliczenia/centrum/static"),
    emptyOutDir: true,
    // Serwowane z dysku taty, nie z sieci: jeden pakiet bez dzielenia jest prostszy i wystarczająco szybki.
    chunkSizeWarningLimit: 1024,
    // Stałe nazwy zamiast hasha, żeby gałęzie scalały te same pliki; świeżość u taty daje ETag (`_Frontend` w app.py).
    rolldownOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
  server: {
    // `npm run dev` obok działającego `run_centrum.py --no-browser`: API idzie do serwera Centrum,
    // który przyjmuje akcje tylko z własnym `Origin`.
    proxy: {
      "/api": {
        target: CENTRUM,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyReq", (request) => request.setHeader("origin", CENTRUM))
        },
      },
    },
  },
})
