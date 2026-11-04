---
name: reverse-engineering
description: Rebuild an existing application in the cookiebook style by observing the real source, one connected segment at a time, in isolated processes, and deriving typed contracts from what was observed. Use when behavior parity with a source app is required and the destination is not a mechanical port.
---

# Reverse engineering a source application into a vertical-pipelines project

This skill comes from one reconstruction. It is a method that worked there, not a measured guarantee. Read it as a starting hypothesis and record deviations in `architecture-log.md`.

Use it when the destination must **behave like** an existing app (same effective inputs to the model, same state changes, same failures) and the source code is available. For a mechanical port of code that already follows the style, use RUNBOOK task D instead.

## Principle

The source code is the blueprint of **behavior**; the destination skeleton is derived from **observed handoffs**. Do not invent a contract so a test goes green: code and test can share the same wrong assumption (guide §12.3).

Follow the real entry in call order, **one connected segment at a time**. Do not pick modules from a disconnected list, and do not try to implement the whole flow at once. The full flow is the sum of segments that were each observed, typed and connected.

## Before anything: authorization

Running the source is a decision of the owner. Write the limits in `AGENTS.md` ("authorizations in force"). The limits used in the reconstruction this skill comes from:

- isolated processes only, synthetic fixtures, private temporary roots;
- network blocked, model providers replaced by objects that reject any request;
- no owner runtime, data, backups or credentials;
- the source is never modified, and never imported by the destination (not even as a fallback).

If any limit is missing, ask. Credentials being present is not authorization.

## Steps, per segment

1. **Find the real entry and cut a segment.** Start from the user action (a route handler, a button) and follow the calls in order. A segment is described by a start point and a **barrier**: the first instruction of the next segment, which is *not* executed. Write both as source file, line and, when needed, bytecode offset.
2. **Type the segment in the destination first** (`contracts.py`, `container.py`): what enters, what crosses the barrier, effects and failures. Reuse existing packages that already produce part of it; do not duplicate.
3. **Write an observer for the segment.** One script per segment, in the evidence folder (`.dumps/`, never in the project). It:
   - installs an audit hook **before any import**, denying network, subprocess and file access outside its temporary root;
   - uses synthetic fixtures that cover the **real branches** (empty and populated, forced and unforced, optional sections present and absent), not one happy path;
   - injects providers that count and reject any request, and asserts the count is zero;
   - captures the values that cross the barrier by tracing (`sys.settrace` matching the exact code object, caller and instruction offset), without editing the source.
4. **Run it in a clean process**, with a fresh numbered output file that cannot be overwritten:

   ```bash
   set -o noclobber
   env -i PATH=/usr/bin:/bin LANG=C.UTF-8 <dest>/.venv/bin/python -I -S -B segmentNN.py \
     > segmentNN-result-01.json 2> segmentNN-result-01.stderr
   ```

   A failed run is evidence. Keep it and number the next one; never overwrite.
5. **Make the observer reproduce the previous checkpoint.** The sealed results of earlier segments are the frozen inputs of the next. If the new run does not reproduce the previous segment's checkpoint, the harness drifted: stop and fix the harness, not the expectation.
6. **Check independently.** A separate validator (for example a `jq` filter) derives the expected output from the **previous sealed results** and compares it with the new observation. Label those expectations as predictions, not observations. The observer must not validate itself.
7. **Seal.** Record the SHA-256 of the observer, its result and the validator output. Close the task with those hashes as evidence.
8. **Rehearse in the destination.** Transcribe goldens from the sealed result into test fixtures as plain text or JSON. Tests never import, run or locate the source. Branches the source run did not exercise but the destination code has are labelled "destination-only diagnostics" and make no reachability claim.
9. **Delegate the leaf, then integrate.** Once contract, goldens and wiring exist, the method bodies follow `construction.md`. Run the four gates.

## Pitfalls seen

- **Opcode tracing leaks between cases.** On Python 3.14, `frame.f_trace_opcodes` persists per code object across calls. Set `f_trace` explicitly first, and switch opcode tracing off when a case ends. Symptom: line-event counters that match in case 1 and drift from case 2 on.
- **The highest bytecode offset is not the return.** Exception handlers sit after it. Identify the return by opname at its known offset.
- **Leak checks must target structure, not substrings.** Looking for a private marker such as a role name flagged ordinary fixture prose. Check labels and identifiers (`SPEAKER=<name>`), not any occurrence of the word.
- **Derive expectations from the real data, not from memory of the format.** A system prompt joined with `"\n"` when every line already ended in a newline produced a wrong prediction; the data said `""`.
- **Predictions and observations stay separate.** Hand-derived expectations can share the observer's wrong assumption.
- **A green harness is not parity.** Zero provider requests, hashes and passing goldens prove the segment, not the flow.

## What this does not prove

- Observed fixtures show the branches they exercised, not that others are unreachable in the source.
- Segment parity is not whole-flow parity. Run a full-flow comparison **near the end**, with the same fixtures and mocked model replies, comparing the effective requests and the resulting state and effects.
- Calls to a real model, OAuth or network still need explicit owner authorization, as in guide §11.

## Record

For each segment keep: the entry and barrier, the observer, the numbered results (including failures), the seal hashes, the independent check, and which destination tests came from observation versus prediction versus destination-only reasoning. Use the vocabulary of guide §14: absent, rehearsed, implemented, integrated, verified.
