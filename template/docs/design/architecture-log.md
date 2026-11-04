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

The gates read this file: `tests/support/deviations.py` collects the `- Exempts:` tokens of approved entries under `## Entries` (code fences and `<!--` lines are skipped). The tokens are:

| Token | Opens | Gate |
| --- | --- | --- |
| `mypy:<module pattern>` | a `[[tool.mypy.overrides]]` with `disallow_any_expr = false` for that module | `tests/gates/test_config.py` |
| `eager:<module>` | a top-level import of that module without `lazy` | `tests/gates/test_style.py` |
| `suppress:<file path>` | `cast(...)`, `# type: ignore[...]` or `# noqa` in that file | `tests/gates/test_deviations.py` |

No other token exists. Loosening another setting of `pyproject.toml` or editing `tests/gates/` is never a project deviation. A malformed entry (unknown `Status`, approval without date and quoted words, unknown token) fails `test_architecture_log_is_well_formed`.

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
- Exempts: `mypy:<module>`, `eager:<module>`, `suppress:<file>` (only for deviations).
- Measured cost of following the rule: errors, files, lines; alternatives tried.
- Observation and source: what was seen, where (file:line, source, test).
- State: absent / rehearsed / implemented / integrated / verified.
- Diagnosis: (1) / (2) / (3) and why.
- Decision and reason: what changes in the code; alternatives discarded.
- Evidence needed: what will prove it, and what it will NOT prove.
- Later result: filled in afterwards, with evidence.
```

## Example (delete when recording the first real entry)

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

## Entries

<!-- The project's first real entry goes here. -->