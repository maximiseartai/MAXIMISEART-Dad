// Odtwarza kontrakt: OpenAPI z modeli Pydantic (tools/ci/export_openapi.py), potem typy i schematy zod
// i tablicę operacji dla `call` (scripts/operations.mjs).
// Python: zmienna PYTHON albo `python` (Windows) / `python3`; potrzebne zależności z requirements.txt.
import { spawnSync } from "node:child_process"
import { resolve } from "node:path"

import { writeOperations } from "./operations.mjs"

const python = process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3")

const steps = [
  [python, [resolve(import.meta.dirname, "../../tools/ci/export_openapi.py")]],
  ["npx", ["openapi-ts"]],
]

for (const [command, args] of steps) {
  const result = spawnSync(command, args, { stdio: "inherit", shell: process.platform === "win32" })

  if (result.status !== 0) {
    process.exit(result.status ?? 1)
  }
}

writeOperations()
