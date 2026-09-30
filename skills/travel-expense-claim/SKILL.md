---
name: travel-expense-claim
description: Processes Alderbridge Consulting's travel-expense workflow (permission/claim intake, monetary review, reimbursement reconciliation, corrections, and independent trip/permit cancellations) from freshly-fetched native sources into a chained, schema-sealed batch snapshot, a per-claim CSV, and an ops handoff report. Use when asked to run, replay, or verify a Project D travel-expense-claim batch.
---

# Travel expense claim

Reusable batch-processing Skill for Alderbridge Consulting's travel
reimbursement workflow: travel permission/claim handling, monetary review,
reimbursement reconciliation and closure, corrections, and independent
trip/permit cancellations (including cancellations with no claim attached).

## Human-authority boundary (hard constraint)

People retain business approval, exception, and payment authority (budget
owner, supervisor, director, Finance, the employee's directory supervisor for
cancellations). This Skill:

- **prepares local work** (parses sources, computes entitlement, evidence
  completeness, filing deadlines, cap/FX application),
- **validates and consumes already-authorized decisions** (review_ledger
  outcomes, Finance activity, cancellation confirmations) exactly as recorded,
  and
- **records effects** (sealed batch snapshots, claims.csv, the work queue,
  report.md).

It never fabricates a reply, makes an approval recommendation, sends a real
request, books travel, or moves money. Every reviewer/Finance/cancellation
decision in the output is a decision that was already recorded in a retained
source -- this Skill only reads it and derives entitlement math on top of it.
Where a business rule or fact is missing from every retained source
(including the interview), the Skill surfaces it in `issues[]` / the work
queue rather than guessing.

## Inputs

A run needs, all freshly fetched (not reused from a prior run except an
explicitly-labeled offline replay -- see README.md):

1. The travel reimbursement policy (Notion page).
2. The initial claim binder (Drive PDF, one claim revision per page).
3. The claim updates binder (Drive PDF, corrections/new claims/exceptions).
4. The receipt binder (Drive PDF, one electronic receipt per page).
5. The travel-registers workbook (Google Sheets: People, Trips, Merchant
   payments, FX, Caps, Budget, Review ledger, Review packets, Finance
   activity, Travel cancellations tabs).

The five URLs are named in the stakeholder interview transcript under
`interviews/`, not hard-coded in this Skill's code -- a new engagement with a
different interview supplies different URLs and this Skill still works
unmodified, as long as the retained content follows the same tab/field
shapes documented in `references/data-shapes.md`.

## Invocation

```bash
cd skills/travel-expense-claim/scripts
python3 build_run.py <path-to-run>/sources.json      # parse + compute + seal batches
python3 write_outputs.py <path-to-run>/sources.json  # claims.csv, work_queue.json, report.md
```

`sources.json` (retained-source manifest: run_id, source_version, case_clock,
files[] with sha256/status/url/locator/observed_at/version) is produced by
fetching the five sources fresh each run and hashing what was retained --
see README.md's "Run" section for the exact fetch-and-hash steps, since that
part is inherently interactive (browser fetch) and not scripted here.

## What it computes, and how

See `references/data-shapes.md` for the exact column layout of each source
tab/field this Skill depends on, and `references/policy-formulas.md` for a
short index into the policy constants encoded in `scripts/policy_rules.py`
(each constant cites the exact policy sentence it implements -- no
case-specific numbers are hard-coded, only the policy's own stated
thresholds: the >EUR 1,000.00 director trigger and the 2-calendar-month
filing window).

Per claim line: receipt + settled merchant-payment matching, personal-purchase
exclusion, filing-deadline / permit / cancellation gating (each liftable only
by a Finance exception whose `covered_issues` explicitly names that gate),
cap x documented-units vs. gross-amount, FX conversion at the payment date,
decimal-half-up rounding to EUR cents. A Finance exception's replacement
amount is authoritative when present, but **never waives receipt or
settled-payment-proof requirements** -- a line can carry an applicable
exception and still be `unresolved` if its receipt is missing.

Per claim: required review roles (administration + budget_owner + supervisor,
plus director when computed entitlement is strictly above EUR 1,000.00;
budget_owner and supervisor collapse to one satisfied pair when the same
person holds both) are read from `Review ledger`, never re-decided. A reject
outcome closes the claim `rejected`; a return holds it on the returning
role; missing decisions leave it `pending`; full approval plus fully-resolved
lines moves it through the Finance request lifecycle (`accepted` ->
`settled`/`failed`/`retry_authorized`/`cancellation_requested`/`cancelled`/
`adjustment`+`refund`+`resolution`) to `closed-reimbursed` or
`closed-no-payment`.

Per cancellation: `status` (requested/confirmed) and `financial_status`
(no-financial-effect/unresolved/resolved) are tracked as independent facts,
per `snapshot.schema.json`. `affected_claim_ids`/`original_request_ids` are
found across a claim's **full revision history**, not just its current
revision -- a correction can move a claim onto a replacement trip (e.g. trip
T18 cancelled while claim C18 corrects onto replacement trip T18B) while the
cancellation still targets the original trip/permit the claim was originally
filed under.

Redelivered activity records (the same `Cancellation activity reference` or
Finance `Activity reference` arriving again in a later batch, byte-identical)
are admitted once, by reference -- this is an intentional idempotency check
present in the source data, not an error condition.

## Outputs (per run, under `artifacts/runs/<run-id>/`)

- `sources.json` -- retained-source manifest (see Inputs).
- `sources/*` -- the actual retained content (policy.md, both claim-binder
  PDFs, the receipt-binder PDF, the travel-registers workbook).
- `batches/batch-<n>.json` -- one sealed snapshot per arrival batch found in
  the source data, chained via `predecessor` (path+sha256 of the prior
  batch), each conforming exactly to `snapshot.schema.json`
  (`travel-claim-snapshot/2`).
- `claims.csv` -- one current row per claim (from the final batch).
- `work_queue.json` -- open items grouped by missing-fact-type first, then by
  subject (claim or cancellation), each carrying subject id, revision,
  owner, and next action.
- `report.md` -- ops handoff: completed work, amounts, outstanding
  obligations, unresolved work with owners/next action, owned unresolved
  items, source/run references, and significant changes across batches.

## Error / retry behavior

- **A source fails to fetch:** record it in `sources.json` with
  `status: "unavailable"`, the attempted url/locator/time, `error` set, and
  `path`/`sha256`/`version` left `null`. Do not substitute a bundled or
  prior-run copy silently -- either retry the fetch or hand off with the gap
  explicit in `report.md`.
- **A source parses but a record is malformed** (unrecognized category,
  missing required field): the affected line/claim becomes `unresolved` with
  a reason naming the exact gap, never silently dropped or assumed zero.
- **A rerun of the same sources.json is expected to be byte-identical**
  (verified for this run -- see README.md "Verify"). If a rerun would change
  sealed batch content (new source data, a code fix), start a new `run_id`
  and link back to the prior run's final batch rather than overwriting it.
- **Scripts are idempotent per source snapshot** -- rerunning
  `build_run.py`/`write_outputs.py` against the same `sources.json` and
  retained files reproduces the same batches, claims.csv, and report.md.

## Supporting files

- `scripts/parse_sources.py` -- normalizes the five retained sources into
  in-memory records (no case-specific values).
- `scripts/policy_rules.py` -- pure policy-formula functions, each citing its
  source sentence in `policy.md`.
- `scripts/engine.py` -- per-line and per-request resolution logic.
- `scripts/build_run.py` -- orchestrates parsing + per-batch state
  computation + sealed snapshot output.
- `scripts/write_outputs.py` -- claims.csv, work_queue.json, report.md from
  the sealed batches.
- `references/data-shapes.md` -- exact source column/field layout this Skill
  depends on.
- `references/policy-formulas.md` -- index of policy constants and the
  policy sentence each one encodes.
