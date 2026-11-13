import * as React from "react"
import { CircleCheckIcon, TriangleAlertIcon } from "lucide-react"

import { changeInboxPassword } from "@/api/centrum"
import { failureMessage, refusedField } from "@/api/client"
import type { InboxPasswordSaved } from "@/api/generated"
import { LoadFailure } from "@/components/load-failure"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { showFailure } from "@/lib/action"
import { useSettings } from "@/lib/settings"
import { FieldSentence, SettingRow, SettingsPanel } from "@/pages/settings/setting-row"

type Login = InboxPasswordSaved["login"]

/** Jedno zdanie po próbie logowania: czy skrzynka przyjęła nowe hasło. */
const LOGIN_SENTENCES: Record<Login, string> = {
  accepted: "Skrzynka przyjęła hasło.",
  rejected: "Skrzynka nie przyjęła hasła. Sprawdź je i wpisz jeszcze raz.",
  no_network: "Hasło zapisane, ale skrzynka nie odpowiada. Sprawdź internet.",
}

/**
 * Skrzynka raportów: tata wpisuje nowe hasło aplikacji Google w pole, które nigdy nie pokazuje starego (serwer go nie
 * wysyła). Po zapisie Centrum raz loguje się do skrzynki i mówi, czy hasło przyjęła. Adres skrzynki wpisuje Maks.
 */
export function InboxSection() {
  const { settings, reload } = useSettings()
  const [typing, setTyping] = React.useState(false)
  const [login, setLogin] = React.useState<Login | null>(null)

  switch (settings.state) {
    case "loading":
      return <Skeleton className="h-20 w-full rounded-xl" aria-label="Wczytywanie ustawień" />
    case "failed":
      return <LoadFailure what="ustawień" message={settings.message} reload={reload} />
    case "ready": {
      const { inbox, inbox_problem: problem } = settings.data

      return (
        <SettingsPanel label="Skrzynka raportów">
          <SettingRow
            title="Hasło aplikacji"
            description={inbox.address ?? "Adres skrzynki wpisuje Maks."}
            below={
              typing || login !== null || problem !== null ? (
                <>
                  {problem === null ? null : <FieldSentence>{problem.message}</FieldSentence>}
                  {typing ? (
                    <NewPassword
                      onDone={(result) => {
                        setTyping(false)
                        setLogin(result)
                      }}
                      onCancel={() => setTyping(false)}
                    />
                  ) : null}
                  {login === null || typing ? null : <LoginSentence login={login} />}
                </>
              ) : undefined
            }
          >
            {typing ? null : (
              <Button
                variant="outline"
                size="sm"
                disabled={inbox.address === null}
                onClick={() => {
                  setLogin(null)
                  setTyping(true)
                }}
              >
                Zmień hasło
              </Button>
            )}
          </SettingRow>
        </SettingsPanel>
      )
    }

    default: {
      const unhandled: never = settings

      return unhandled
    }
  }
}

/** Nowe hasło: Enter i „Zapisz” zapisują i sprawdzają skrzynkę, Esc i „Anuluj” wracają; zła wartość stoi pod polem. */
function NewPassword({ onDone, onCancel }: { onDone: (login: Login) => void; onCancel: () => void }) {
  const { secretSaved } = useSettings()
  const [value, setValue] = React.useState("")
  const [saving, setSaving] = React.useState(false)
  const [refusal, setRefusal] = React.useState<string | null>(null)

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        setSaving(true)
        setRefusal(null)
        changeInboxPassword(value).then(
          (saved) => {
            setSaving(false)
            secretSaved(saved)
            onDone(saved.login)
          },
          (failure: Error) => {
            setSaving(false)

            if (refusedField(failure) === null) {
              showFailure(failure)
            } else {
              setRefusal(failureMessage(failure))
            }
          }
        )
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Input
          autoFocus
          type="password"
          autoComplete="new-password"
          aria-label="Nowe hasło aplikacji"
          aria-invalid={refusal === null ? undefined : true}
          aria-describedby={refusal === null ? undefined : "haslo-zdanie"}
          className="min-w-0 flex-1 basis-64"
          placeholder="Nowe hasło aplikacji"
          spellCheck={false}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              onCancel()
            }
          }}
        />
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Anuluj
        </Button>
        <Button type="submit" size="sm" disabled={saving} aria-label="Zapisz hasło">
          {saving ? (
            <>
              <Spinner data-icon="inline-start" />
              Sprawdzam…
            </>
          ) : (
            "Zapisz"
          )}
        </Button>
      </div>
      {refusal === null ? null : <FieldSentence id="haslo-zdanie">{refusal}</FieldSentence>}
    </form>
  )
}

function LoginSentence({ login }: { login: Login }) {
  if (login === "rejected") {
    return <FieldSentence>{LOGIN_SENTENCES[login]}</FieldSentence>
  }

  const Icon = login === "accepted" ? CircleCheckIcon : TriangleAlertIcon

  return (
    <p role="status" className="flex items-start gap-2 text-sm text-pretty">
      <Icon className={login === "accepted" ? "mt-0.5 size-4 shrink-0 text-success" : "mt-0.5 size-4 shrink-0 text-warning"} aria-hidden />
      <span>{LOGIN_SENTENCES[login]}</span>
    </p>
  )
}
