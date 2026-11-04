# Architecture log

Log of the structural decisions of **this project**. It is born empty: the decisions that already come with the template, with reason and gate, are in [template-decisions.md](template-decisions.md) and are not repeated here.

## When to write an entry

- A template rule changes (gate relaxed or tightened, new `Any` exemption, import outside `lazy`, pydantic at the edge, another top-level name).
- A wave ends with structural absence (diagnosis 2 or 3 below) and the skeleton is readjusted.
- The owner decides something a future agent would need to know in order not to undo it.

The writer is the orchestrator model or the owner. An implementer who discovers an impossible contract **reports**; does not write here.

## Log rules

- The log points to the code; it is not a parallel tree that looks finished.
- Old entries are not rewritten to pretend past coverage: add a new entry with the result, or fill in "Later result".
- Evidence is what was run and observed, with what it does **not** prove.

States: **absent** · **rehearsed** (real run with typed fakes) · **implemented** · **integrated** (real consumers wired) · **verified** (evidence from the real component).

Absence diagnosis: **(1)** implementation error · **(2)** architectural omission · **(3)** undistributed capability. See guide §13.

## Entry template

```markdown
### YYYY-MM-DD — short title

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

- Observation and source: `pdfparse.load()` returns `dict[str, Any]`; mypy reports 4 errors in
  `backend_logic/documents/read/pipeline.py:31` with `disallow_any_expr`.
- State: rehearsed (real run with synthetic PDF in `tests/documents/test_documents_read.py`).
- Diagnosis: (2) architectural omission — the skeleton's contract assumed a typed library.
- Decision and reason: new package `documents/parse/`, whose `pipeline.py` narrows the dict to
  `ParsedPage` with `isinstance`; only `backend_logic.documents.parse.*` is exempted in
  `pyproject.toml`. Discarded: exempting all of `documents.read` (the `Any` would leak into the steps).
- Evidence needed: clean mypy outside the exemption; `tests/gates/test_config.py` updated with the new
  exemption; malformed PDF becomes `ValueError`. Does NOT prove that the library handles encrypted PDFs.
- Later result: —
```

## Entries

<!-- The project's first real entry goes here. -->