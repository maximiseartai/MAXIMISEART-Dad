import { defineConfig } from "@hey-api/openapi-ts"

// Kontrakt serwer ↔ przeglądarka: OpenAPI z modeli Pydantic → typy i schematy zod.
// Źródło prawdy to modele w src/rozliczenia/centrum/contract/; `npm run contract` odtwarza oba pliki.
export default defineConfig({
  input: "src/api/openapi.json",
  output: { path: "src/api/generated" },
  plugins: ["@hey-api/typescript", "zod"],
})
