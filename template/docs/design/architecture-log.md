# Architecture log

Log of the structural decisions of **this project**. It is born empty: the decisions that already come with the template, with reason and gate, are in [template-decisions.md](template-decisions.md) and are not repeated here.

## When to write an entry

- An agent needs to break a template rule (new `Any` boundary, import outside `lazy`, a `cast`/suppression comment, another top-level name): a deviation **proposal**, see below. It opens nothing until the owner approves.
- A gate is tightened (free; record why).
- A wave ends with structural absence (diagnosis 2 or 3 below) and the skeleton is readjusted.
- The owner decides something a future agent would need to know in order not to undo it.

The writer is the orchestrator model or the owner. An implementer who discovers an impossible contract **reports**; does not write here.

## Deviations: proposed by the agent, approved only by the owner

An entry that breaks a template rule is a **deviation** ([AGENTS.md → Deviations](../../AGENTS.md#deviations-owner-decision)). The agent writes it with `- Status: proposed` and stops; writing it grants nothing. Only after the owner says yes in the conversation does it become `- Status: approved`, with `- Approved by owner: YYYY-MM-DD "<the owner's words, verbatim>"`.

When the owner has delegated approvals in writing ([AGENTS.md → Deviations](../../AGENTS.md#deviations-owner-decision), item 4), the orchestrator may approve an entry the delegation covers. The entry then carries, instead of `Approved by owner`, both:

- `- Approved by delegation: YYYY-MM-DD "<the owner's delegation, verbatim>"`: the date the owner wrote the delegation, and its exact words.
- `- Critic: YYYY-MM-DD <critic> checked <what>; verdict: approve`: who reviewed it (an independent critic subagent, not the agent that wrote the proposal; name its tier, e.g. "critic subagent (intermediate model)"), what it checked, and its verdict, on or after the delegation's date. The `Critic` line must contain ` checked `, name the critic and the object with at least one letter or digit, write `verdict` exactly once and end with `; verdict: approve` or `; verdict: reject`; a rejected review never sits under `Status: approved`. After a revision, the new review replaces the `Critic` line, and the earlier verdict and findings go into `Decision and reason`: two `Critic` lines are a problem.

A delegation never covers the template's own rules: a delegated entry with a token that reaches `tests/gates/`, the template's files in `tests/support/` (`TEMPLATE_SUPPORT_FILES` in `tests/support/deviations.py`: `deviations.py`, `architecture.py`, `boundaries.py`, `declarations.py`, `tomllib.pyi`) or `pyproject.toml` (as a `suppress:` path, or a `mypy:` pattern that covers one of their modules) grants nothing. Neither does a delegated `mypy:` pattern with a glob in its first two components (`backend_logic.*`, `*.parse`): it lifts the gate for a whole tree, not one boundary module; only the owner can approve that. Nor an entry with both approval fields. A project's own helpers and stubs in `tests/support/` are delegable.

The gates read this file: `tests/support/deviations.py` collects the `- Exempts:` tokens of approved entries under `## Entries`. Write every field for that reader, which is strict on purpose (whatever it tolerated, an agent could use to hide a grant):

- `## Entries` runs to the next level-1 or level-2 heading; there is exactly one. Before it, code fences and HTML comments are read as the rendered page shows them (the entry template and the examples above are fenced). Inside it there is no code fence and no HTML comment at all, not even closed on one line: nothing in the section may be hidden from the rendered page. A `<!--` written inside backticks is text.
- An entry starts at a `###` heading. Its fields (`- Status:`, `- Approved by owner:`, `- Approved by delegation:`, `- Critic:`, `- Exempts:`) start at column 0, take one line (the reader does not join wrapped lines), are never empty and appear at most once. A `####` heading inside `## Entries` is a problem.
- Dates are ASCII `YYYY-MM-DD` and real calendar days. A quote is `YYYY-MM-DD "<words>"`: one space, one double-quoted span with at least three characters and a letter or digit, no `"` inside it (write the owner's inner quotes as single quotes) and nothing after it. Invisible characters (zero-width spaces, bidi marks, control characters) are not words.
- `- Exempts:` is `none` or backticked tokens separated by `, `, and nothing else: an explanation goes in another field.
- Any problem in an entry voids every token of that entry, whoever approved it; a problem of the section itself (markup, an unclosed fence or comment, a second `## Entries`, a field outside an entry, no visible `## Entries`) voids every entry.

The tokens are:

| Token | Opens | Gate |
| --- | --- | --- |
| `mypy:<module pattern>` | a `[[tool.mypy.overrides]]` with `disallow_any_expr = false` for that module | `tests/gates/test_config.py` |
| `eager:<module>` | a top-level import of that module without `lazy` | `tests/gates/test_style.py` |
| `suppress:<file path>` | `cast(...)`, `# type: ignore[...]` or `# noqa` in that file | `tests/gates/test_deviations.py` |

No other token exists. Loosening another setting of `pyproject.toml` or editing `tests/gates/` is never a project deviation. A malformed log fails `tests/gates/test_deviations.py::test_architecture_log_is_well_formed`: anything the list above forbids; unknown or missing `Status`; `approved` without a dated, quoted approval; a delegated approval without the owner's quoted words, without a well-formed `Critic`, with `verdict: reject`, with a review dated before the delegation, or with a token reaching the template's rules; both approval fields; an unknown token.

## Log rules

- The log points to the code; it is not a parallel tree that looks finished.
- Old entries are not rewritten to pretend past coverage: add a new entry with the result, or fill in "Later result".
- Evidence is what was run and observed, with what it does **not** prove.

States: **absent** · **rehearsed** (real run with typed fakes) · **implemented** · **integrated** (real consumers wired) · **verified** (evidence from the real component).

Absence diagnosis: **(1)** implementation error · **(2)** architectural omission · **(3)** undistributed capability. See guide §13.

## Entry template

```markdown
### YYYY-MM-DD — short title

- Status: proposed / approved / rejected (only for deviations; the agent always writes proposed).
- Approved by owner: YYYY-MM-DD "verbatim words" (only the owner's yes; never paraphrased).
- Approved by delegation: YYYY-MM-DD "the owner's delegation, verbatim" (instead of the line above, only under a written delegation).
- Critic: YYYY-MM-DD <critic> checked <what>; verdict: approve / reject (required with a delegation).
- Exempts: `mypy:<module>`, `eager:<module>`, `suppress:<file>` (only for deviations).
- Measured cost of following the rule: errors, files, lines; alternatives tried.
- Observation and source: what was seen, where (file:line, source, test).
- State: absent / rehearsed / implemented / integrated / verified.
- Diagnosis: (1) / (2) / (3) and why.
- Decision and reason: what changes in the code; alternatives discarded.
- Evidence needed: what will prove it, and what it will NOT prove.
- Exit criterion: (only for a temporary decision, such as a quarantine of imported legacy code) what ends it, and what is deleted in that same change.
- Later result: filled in afterwards, with evidence.
```

## Examples (delete when recording the first real entry)

```markdown
### 2026-11-10 — `pdfparse` enters as an `Any` boundary

- Status: approved
- Approved by owner: 2026-11-11 "approve the pdfparse boundary, only documents.parse"
- Exempts: `mypy:backend_logic.documents.parse.*`
- Measured cost of following the rule: 4 mypy errors in one module; no typed stub or typed
  alternative library exists (checked: package metadata, typeshed).
- Observation and source: `pdfparse.load()` returns `dict[str, Any]`; mypy reports 4 errors in
  `backend_logic/documents/read/pipeline.py:31` with `disallow_any_expr`.
- State: rehearsed (real run with synthetic PDF in `tests/documents/test_documents_read.py`).
- Diagnosis: (2) architectural omission — the skeleton's contract assumed a typed library.
- Decision and reason: new package `documents/parse/`, whose `pipeline.py` narrows the dict to
  `ParsedPage` with `isinstance`; only `backend_logic.documents.parse.*` is exempted in
  `pyproject.toml`. Discarded: exempting all of `documents.read` (the `Any` would leak into the steps).
- Evidence needed: clean mypy outside the exemption; `tests/gates/test_config.py` green without
  being edited (it reads the `Exempts` token above); malformed PDF becomes `ValueError`. Does NOT
  prove that the library handles encrypted PDFs.
- Later result: —
```

The same kind of entry, approved under a delegation instead of by the owner directly:

```markdown
### 2026-11-12 — `xlsxread` enters as an `Any` boundary

- Status: approved
- Approved by delegation: 2026-11-12 "port the spreadsheet import; approve the boundaries it needs yourself, each one after a critic"
- Critic: 2026-11-12 critic subagent (intermediate model, not the author) checked the 6 mypy errors, the absent typed alternatives and that only `sheets.parse` is exempted; verdict: approve
- Exempts: `mypy:backend_logic.sheets.parse.*`
- Measured cost of following the rule: 6 mypy errors in one module; no stub, no typed alternative.
- Decision and reason: as in the example above, a narrowing package `sheets/parse/`.
- Evidence needed: as above. Does NOT prove the critic was independent: that is the owner's review.
- Later result: —
```

## Entries

The project's first real entry goes here, as a `###` heading.
