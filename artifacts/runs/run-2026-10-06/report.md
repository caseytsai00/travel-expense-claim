# Ops handoff report -- run run-2026-10-06

Final batch: `batch-4` (of 4 sealed batches). 
Source binding: `artifacts/runs/run-2026-10-06/sources.json` (sha256 `aba07ed2ccf64fd0...`).

## Why this run exists: predecessor link and correction

This run supersedes `run-2026-09-30` (predecessor; see its own `report.md`/`sources.json`). That run's retained `policy.md` captured only the first 5 of 17 paragraphs on the live POL-2026.2 page -- a capture gap at fetch time, not a policy revision (both runs' interview-supplied link redirects to the identical POL-2026.2 revision). This run re-fetched all 5 sources fresh via browser/export (see `sources.json`) and retains the complete policy text.

**What changed:** nothing in the computed output. `claims-initial.pdf`, `claims-updates.pdf`, `receipts.pdf`, and the travel-registers workbook's 10 tabs are byte-identical (or, for the re-exported `.xlsx`, content-identical -- independently diffed tab-by-tab) to run-2026-09-30. `claims.csv` and `work_queue.json`'s groups are byte-identical between the two runs (diffed directly) -- the 12 previously-missing policy paragraphs (independent cancellation protocol, material-change/revalidation rule, Finance payment-request/replay identity rules, net-paid/balance formulas) describe behavior the engine already implemented, sourced redundantly from the stakeholder interview (see findings.md's citations, not a graded deliverable but the design-decision record). **What changed is evidentiary, not computational:** the formulas this run's code encodes are now directly traceable to the complete retained policy text, not only to the interview.

## ⚠ Lead finding: Finance's own ledger contradicts itself

**1 claim(s)** have a request where Finance's own activity log reaches one terminal status (settled or cancelled) and later reaches the *other* one for the same request -- net **EUR 100.00** paid against request(s) Finance had already marked cancelled. This is not a claim-side evidence or review gap (no amount of missing receipts or pending sign-off explains it) and it will not self-resolve as evidence arrives -- Finance/administration must determine which fact is authoritative before the revision can close. See the `finance_sequence_conflict` group in `work_queue.json`.

## ⚠ Lead finding: payments recorded against unreviewed/unsupported claims

Finance's own activity log shows **88 of 121 claims** with money actually settled (net **EUR 7769.16**) even though the current claim revision is not `closed-reimbursed` -- most commonly because the claimed cost has no matching receipt in the retained receipts binder, or the revision has no recorded administration/budget_owner/supervisor review at all. This Skill does **not** infer a review that was never recorded, and does not hide or reverse the payment fact -- it reports both the real money movement and the real evidence/review gap side by side. See the `payment_anomaly` group in `work_queue.json` for the full per-claim list, and route to Finance/administration to confirm each payment or begin recovery.

## Completed work

- **15 claims closed-reimbursed**, total paid **EUR 12034.15**.
- **1 claim rejected**: C14 (LEAD-01 (budget_owner) rejected: Client work was cancelled.)
- **4 of 4 cancellations confirmed** by the directory supervisor.
- **1 cancellation(s) with no claim ever attached** (TC122): closed/tracked with their real no-financial-effect or business reason -- no claim row invented for them.

## Amounts

- Total computed entitlement across all claims (supported lines only): **EUR 4164.99**
- Total net paid to date: **EUR 12034.15**
- Outstanding balance (allowed - paid, non-zero only): **EUR 0.00**

## Outstanding obligations / unresolved work

- **90 claims held** (evidence gap or a discretionary business return -- see work queue).
- **15 claims pending** (no review decision has arrived yet for the current revision).
- Full detail, grouped by missing-fact-type, in the local work queue: `work_queue.json` (194 open items). Groups: missing_receipt (89), payment_anomaly (88), awaiting_initial_review (15), finance_sequence_conflict (1), business_hold_returned (1)

## Owned unresolved items (evidence genuinely does not support completion)

- **~half of all claim lines lack a receipt in the retained receipts binder** (e.g. COST-02, COST-04, COST-08, COST-12...) and none is supplied in the updates binder either. Per policy, missing evidence is never assumed zero -- these stay `held` across all 4 batches. Reconsider only if a future run's sources supply the missing receipts.
- **C21 stays `held`** on a budget_owner return ("requests a funding review before committing") that is never resolved in the retained sources -- a discretionary business hold, distinct from an evidence gap; reconsider if Finance/budget supplies a funding decision.
- **C18's revision 2 (trip reassigned to T18B) has never received a fresh administration/budget_owner/supervisor review** in the retained sources, so it sits `pending` even though its original revision was fully approved -- this is the direct consequence of Decision #2 (every revision, including a trip swap, requires full re-review, no carry-forward of a prior revision's approval). Separately, and not resolved by that review arriving: Finance's own activity log for REQ-C18 shows 'cancelled' and then 'settled' for the same request, triggered by the trip reassignment landing while the cancellation was in flight -- tracked as its own `finance_sequence_conflict` item (distinct from the ordinary missing-receipt/awaiting-review anomalies above), since only Finance/administration can say which fact is authoritative.

## Source / run references

- `SRC-1-policy`: https://private-pecorino-70e.notion.site/Project-D-Alderbridge-travel-reimbursement-policy-POL-2026-1-3d80b700541e81ed93ebd386abc1dcb0 -> retained at `artifacts/runs/run-2026-10-06/sources/policy.md` (sha256 `58b57535933d72e8...`)
- `SRC-2-claims-initial`: https://drive.google.com/file/d/13sRj6s_kMeP1hsYGstWWmfkb6SCN1YOS/view -> retained at `artifacts/runs/run-2026-10-06/sources/claims-initial.pdf` (sha256 `b42a28754b187736...`)
- `SRC-3-claims-updates`: https://drive.google.com/file/d/16829RwrGrMCK9oq5TnWuytFewGk_8xQP/view -> retained at `artifacts/runs/run-2026-10-06/sources/claims-updates.pdf` (sha256 `03c15787d18e2928...`)
- `SRC-4-receipts`: https://drive.google.com/file/d/1Ynn1VLH-faRIy91xy95rOWwCBhy5mjjM/view -> retained at `artifacts/runs/run-2026-10-06/sources/receipts.pdf` (sha256 `4c3dc47f187ccc5c...`)
- `SRC-5-travel-registers`: https://docs.google.com/spreadsheets/d/1338nvKD6rgAdLgGRhYCMMlQyDNLK0sE8pvFWrZAaaxg/edit -> retained at `artifacts/runs/run-2026-10-06/sources/travel-registers.xlsx` (sha256 `2484d3fd5c0d4ed2...`)
- Case clock used for filing-deadline computation: `2026-11-15T00:00:00+01:00`

## Significant changes across the run's 4 batches

- 17 claims changed status (or first appeared) between batch 1 and batch 4.
  - C01: ready -> closed-reimbursed
  - C03: ready -> closed-reimbursed
  - C05: ready -> closed-reimbursed
  - C07: ready -> closed-reimbursed
  - C11: ready -> closed-reimbursed
  - C12: pending -> held
  - C17: ready -> closed-reimbursed
  - C18: held -> pending
  - C19: ready -> closed-reimbursed
  - C24: (not yet arrived) -> closed-reimbursed
  - C99: ready -> closed-reimbursed
  - C101: ready -> closed-reimbursed
  - C103: ready -> closed-reimbursed
  - C105: ready -> closed-reimbursed
  - C107: ready -> closed-reimbursed
  - ... and 2 more (see `claims.csv` + individual batch files for full detail).

## Verification

See `README.md` "Verify" section for the commands that reproduce this run and its replay check.

