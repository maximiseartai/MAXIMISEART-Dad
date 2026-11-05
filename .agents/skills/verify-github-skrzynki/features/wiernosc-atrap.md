# Wierność atrap

The tests of both clients replace GitHub with answers their authors wrote. This feature runs the tests that model a
recorded situation and compares each fake answer with GitHub's recorded answer to the same situation, so a test cannot
keep passing on an answer GitHub does not give. It needs no network: it reads `nagrania/`.

## Sub-features

- `status`: every status GitHub gave in a situation (`MAPPING` in `github_wiernosc.py`: a case of a recording and a
  kind of request) is among the statuses of the mapped tests' fakes.
- `ksztalt`: for a 2xx answer, every field the client reads (`FIELDS`) that the fake gives has among its types the
  type GitHub gave (`null` from GitHub requires nothing; a field only the fake has, or a field the fake leaves out, is
  not a difference).
- `testy`: each mapped test exists and passes.
- `bez-atrapy`: recorded answers no row maps, listed as `BEZ ATRAPY` (information).

## How to get to it (user POV)

- No user path: it guards the tests that guard Centrum's GitHub clients.

## Driving it with the GitHub harness

Preconditions:

- `nagrania/` holds `aktualnosc.json` and at least one `skrzynka-<key>.json`.

- **Run.** `github_skrzynki.py odtworz --feature wiernosc-atrap` (a live run also ends with it).
- **Read.** `WIERNOŚĆ | <case> | <kind> | OK` per row, `RÓŻNICA | wiernosc-atrap | …` per difference.
- **Proof.** The last line `VERIFY OK`.

## Gotchas

- The mapped tests run in the script's own pytest (`pytest.main` with a plugin that wraps `ScriptedTransport`,
  `GitHubOnTransport` and the `_GitHub` handler), so a renamed test or parameter id is a difference until `MAPPING`
  follows it.
- A fake that deliberately answers in another shape (an `id` as text, a body as a number) is not compared field by
  field when it also gives the real type: those tests check that the client rejects such answers.
