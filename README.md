# Travel expense claim

A reusable Agent Skill (`skills/travel-expense-claim/`) for Alderbridge
Consulting's travel reimbursement workflow: permission/claim handling,
monetary review, human decisions, reimbursement reconciliation and closure,
corrections, and independent trip/permit cancellations -- including
cancellations with no claim attached. Company and records are fictional.

**Current run:** `artifacts/runs/run-2026-10-06/` (supersedes
`run-2026-09-30/`, kept as its predecessor -- `run-2026-10-06/report.md`
explains why: a source-completeness correction to `policy.md`, with no
change to computed claims/obligations. See that report's "Why this run
exists" section.)

## Start

1. Read the [full Project D task](https://private-pecorino-70e.notion.site/Travel-expense-claim-Task-and-submission-3da0b700541e81249039eff895f77c98) for the scope, workflow and deliverables.
2. Use **Use this template -> Create a new repository** on [GitRollTraining/travel-expense-claim](https://github.com/GitRollTraining/travel-expense-claim), then clone your own repository and work there.

## Setup

Requires Python 3 with `openpyxl`, `PyPDF2`, and `jsonschema`:

```bash
pip3 install --user openpyxl PyPDF2 jsonschema
```

Source fetching is interactive (browser-driven, since the five sources are a
private Notion page, two Drive PDFs, a Drive PDF binder, and a Google Sheets
workbook with no public API access configured for this exercise) -- there is
no single script that performs it. See "Run" below for the exact steps.

## Run

Each run gets a fresh `run_id` and its own directory,
`artifacts/runs/<run-id>/`. A run has two phases:

**1. Fetch and retain the five sources** (repeat for every new run; do not
reuse a prior run's retained files except an explicitly-labeled offline
replay):

- Policy (Notion page): open it, extract the full page text, save as
  `artifacts/runs/<run-id>/sources/policy.md`.
- Initial claim binder, claim updates binder, receipt binder (Drive PDFs):
  download each via Drive's own download button, save under
  `artifacts/runs/<run-id>/sources/`.
- Travel-registers workbook (Google Sheets): File -> Download -> Microsoft
  Excel (.xlsx), to retain all 10 tabs in one file, save under
  `artifacts/runs/<run-id>/sources/`.

Then hash everything and write the manifest:

```bash
shasum -a 256 artifacts/runs/<run-id>/sources/*
```

Hand-write (or script) `artifacts/runs/<run-id>/sources.json` with `run_id`,
`source_version`, `case_clock` (read the policy page's own stated case
clock -- do NOT use the real fetch date for filing-deadline computation),
and one `files[]` entry per source (`source_id`, `path`, `sha256`, `status`,
`error`, `url`, `locator`, `observed_at`, `version`). A source that fails to
fetch gets `status: "unavailable"`, `error` set, and `path`/`sha256`/`version`
left `null` -- never substitute a prior run's copy silently.

**2. Parse, compute, and emit outputs:**

```bash
cd skills/travel-expense-claim/scripts
python3 build_run.py <path-to-run>/sources.json      # sealed batches
python3 write_outputs.py <path-to-run>/sources.json  # claims.csv, work_queue.json, report.md
```

`build_run.py` finds the arrival-batch numbers present in the retained
sources and emits one sealed `batches/batch-<n>.json` per batch, chained via
`predecessor` (path+sha256 of the prior batch) and bound to `sources.json`
via `source_binding`, each conforming exactly to `snapshot.schema.json`
(`travel-claim-snapshot/2`). `write_outputs.py` derives `claims.csv`,
`work_queue.json`, and `report.md` from the final batch.

### Success / partial / failure behavior

There is no run-level status field in the schema by design. Success or
partial completion is read per-record: a claim's `status` field
(`closed-reimbursed` / `closed-no-payment` / `rejected` / `held` / `pending`
/ `ready`), a cancellation's `status` + `financial_status`, and the open
items in `work_queue.json` and `report.md`'s "Outstanding obligations" /
"Owned unresolved items" sections. A hard failure (a source that never
fetched, a script exception) stops the run before any batch is sealed --
nothing partial gets written as if it were complete.

- **A source failed to fetch** (`sources.json` has any `status` other than
  `"read"`): `build_run.py` refuses to parse anything and exits non-zero
  before sealing any batch, naming the exact source(s) and recorded error.
  It never substitutes a bundled or prior-run copy silently. Verified with a
  synthetic `sources.json` (one source flipped to `unavailable`) -- not
  exercised by this run's real sources, which all fetched cleanly.
- **A receipt uses a category outside the 5 POL-2026.2 documents** (see
  `references/data-shapes.md`): policy's own text already covers this --
  "An unknown category ... is unresolved, never an assumed zero" -- so the
  line is held `unresolved` with that exact reason, same ownership as any
  other evidence-type gap, and surfaced in its own `unknown_category`
  work-queue group for visibility. Never silently defaulted to another
  category's cap formula. Verified with a synthetic receipt category -- not
  exercised by this run's real data, whose 200 claim lines are all within
  the 5 documented categories.

### Replay

Rerunning `build_run.py`/`write_outputs.py` against an unchanged
`sources.json` and its retained files reproduces byte-identical output
(verified for both `run-2026-09-30` and `run-2026-10-06` -- see "Verify"
below). If a rerun would change sealed content (new source data, a code
fix), give it a **new** `run_id` and note the link back to the prior run's
final batch in the new run's `report.md` -- never overwrite a sealed batch
in place. `run-2026-10-06` is exactly this case: see its `report.md` for the
predecessor link and what the correction did/didn't change.

## Verify

```bash
# Schema-validate every sealed batch (current run)
python3 -c "
import json, jsonschema
schema = json.load(open('snapshot.schema.json'))
for b in sorted(__import__('pathlib').Path('artifacts/runs/run-2026-10-06/batches').glob('batch-*.json'),
                 key=lambda p: int(p.stem.split('-')[1])):
    jsonschema.validate(json.load(open(b)), schema)
    print(b, 'VALID')
"

# Replay determinism: rerun and diff against the committed output
cp -r artifacts/runs/run-2026-10-06 /tmp/run-before-replay
cd skills/travel-expense-claim/scripts
python3 build_run.py ../../../artifacts/runs/run-2026-10-06/sources.json
python3 write_outputs.py ../../../artifacts/runs/run-2026-10-06/sources.json
cd ../../..
diff -rq /tmp/run-before-replay artifacts/runs/run-2026-10-06   # expect no output

# Cross-run check: run-2026-10-06's claims.csv and work_queue.json groups
# are identical to run-2026-09-30's (same obligations/money, per the rerun
# rule) even though the two runs' sources.json/policy.md differ in
# completeness -- see run-2026-10-06/report.md for the full explanation.
diff artifacts/runs/run-2026-09-30/claims.csv artifacts/runs/run-2026-10-06/claims.csv   # expect no output
```

What this run's verification actually covers (see `report.md`'s
"Verification" section and `task_plan.md`'s Phase 5 for the running log):
ordinary path (clean single-line claims settling in full), corrections
(trip-swap C09/C18, amount-only C19), Finance exception mechanics
(late-filing C12, cancellation-bound C19/C121), cross-claim duplicate-cost
exclusion (C24 vs. C03), payment failure/retry (C17), cancellation with no
claim attached (T122/TC122), cancellation with an already-dispatched request
(C18/TC018), idempotent redelivery of the same activity record at a later
batch (F-C01-1, TC122-confirmed), and replay. **Not exercised by this run's
retained sources** (documented, not hard-coded around): a claim/permit
landing at exactly the EUR 1,000.00 director-threshold boundary, a
multi-rate FX history for one currency, a source that fails to fetch, and a
receipt category outside the 5 documented in POL-2026.2 -- the last two have
dedicated code paths (see "Error / retry behavior" above) verified by
disposable synthetic inputs, since none of the 5 real sources or 200 real
claim lines ever hits them. Separately: no case anywhere in the retained
policy, interview, or workbook was found where a business rule is
genuinely undocumented by every source (the project brief's broader
"missing rules -- escalate, don't guess" standing rule) -- policy.md turns
out to define a rule for every case this data actually presents, including
the unknown-category case above. If one ever arose, the existing free-form
`issues[]`/`work_queue.json` shape (reason + owner + resolution_needed, no
fixed enum) already carries a lead/facilitator-owned entry without any
further code change.

## Handoff / support

- `report.md` under each run's directory is the primary ops handoff
  document: completed work, amounts, outstanding obligations, unresolved
  work with owners and next action, owned unresolved items, source/run
  references, and significant changes across batches.
- `work_queue.json` is the local work queue: open items grouped by
  missing-fact-type first (missing receipt / missing merchant proof /
  missing cap / late-filing-awaiting-exception /
  cancellation-pending-finance-resolution / awaiting-initial-review /
  business-hold-returned), then by subject -- each item carries its subject
  id, revision, owner, and next action.
- If a business rule or fact is genuinely undocumented in every retained
  source (including the stakeholder interview), it surfaces as an `issues[]`
  entry / work-queue item with a named owner, not a guess.
- Questions about the Skill's logic: see `skills/travel-expense-claim/SKILL.md`
  and its `references/` for the exact policy-sentence-to-code mapping.

## Before you work

No implementation or runtime is supplied; choose and document the
dependencies your Skill needs. Follow the shared [Setting Up entire.io for a Project](https://classroom.google.com/c/ODcyMjA4NTkwNDk2/m/ODc0NzI2NzQzMzQ2/details) lesson and verify actual session capture before assessed work.

Use [Project D in Work Sim](https://work-sim-alpha.catalyte.ai/s/project-d-travel-expense-claim) for your stakeholder interview and obtain relevant business source links and context there. Read native business sources during each new run and retain the content actually used as the task requires.

**Interview rule.** You conduct the stakeholder interview yourself, and the questions are yours. Do not connect a coding agent or any other AI to the interview to run, script, or automate it. The interview transcript is assessed together with the code; a project whose interview was run by an agent is not scored.

- Export your interview as the original Work Sim Markdown, save one final complete file per session under `interviews/`, and commit and push it with your code. Do not rewrite the export. If the export is unavailable, contact the facilitator.
