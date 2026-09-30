# Ops handoff report -- run run-2026-09-30

Final batch: `batch-4` (of 4 sealed batches). 
Source binding: `artifacts/runs/run-2026-09-30/sources.json` (sha256 `9f90e73bf28db668...`).

## ⚠ Lead finding: payments recorded against unreviewed/unsupported claims

Finance's own activity log shows **89 of 121 claims** with money actually settled (net **EUR 7869.16**) even though the current claim revision is not `closed-reimbursed` -- most commonly because the claimed cost has no matching receipt in the retained receipts binder, or the revision has no recorded administration/budget_owner/supervisor review at all. This Skill does **not** infer a review that was never recorded, and does not hide or reverse the payment fact -- it reports both the real money movement and the real evidence/review gap side by side. See the `payment_anomaly` group in `work_queue.json` for the full per-claim list, and route to Finance/administration to confirm each payment or begin recovery.

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
- Full detail, grouped by missing-fact-type, in the local work queue: `work_queue.json` (194 open items). Groups: missing_receipt (89), payment_anomaly (89), awaiting_initial_review (15), business_hold_returned (1)

## Owned unresolved items (evidence genuinely does not support completion)

- **~half of all claim lines lack a receipt in the retained receipts binder** (e.g. COST-02, COST-04, COST-08, COST-12...) and none is supplied in the updates binder either. Per policy, missing evidence is never assumed zero -- these stay `held` across all 4 batches. Reconsider only if a future run's sources supply the missing receipts.
- **C21 stays `held`** on a budget_owner return ("requests a funding review before committing") that is never resolved in the retained sources -- a discretionary business hold, distinct from an evidence gap; reconsider if Finance/budget supplies a funding decision.
- **C18's revision 2 (trip reassigned to T18B) has never received a fresh administration/budget_owner/supervisor review** in the retained sources, so it sits `pending` even though its original revision was fully approved -- this is the direct consequence of Decision #2 (every revision, including a trip swap, requires full re-review, no carry-forward of a prior revision's approval).

## Source / run references

- `SRC-1-policy`: https://private-pecorino-70e.notion.site/Project-D-Alderbridge-travel-reimbursement-policy-POL-2026-1-3d80b700541e81ed93ebd386abc1dcb0 -> retained at `artifacts/runs/run-2026-09-30/sources/policy.md` (sha256 `8b120b7af432b575...`)
- `SRC-2-claims-initial`: https://drive.google.com/file/d/13sRj6s_kMeP1hsYGstWWmfkb6SCN1YOS/view -> retained at `artifacts/runs/run-2026-09-30/sources/claims-initial.pdf` (sha256 `b42a28754b187736...`)
- `SRC-3-claims-updates`: https://drive.google.com/file/d/16829RwrGrMCK9oq5TnWuytFewGk_8xQP/view -> retained at `artifacts/runs/run-2026-09-30/sources/claims-updates.pdf` (sha256 `03c15787d18e2928...`)
- `SRC-4-receipts`: https://drive.google.com/file/d/1Ynn1VLH-faRIy91xy95rOWwCBhy5mjjM/view -> retained at `artifacts/runs/run-2026-09-30/sources/receipts.pdf` (sha256 `4c3dc47f187ccc5c...`)
- `SRC-5-travel-registers`: https://docs.google.com/spreadsheets/d/1338nvKD6rgAdLgGRhYCMMlQyDNLK0sE8pvFWrZAaaxg/edit -> retained at `artifacts/runs/run-2026-09-30/sources/travel-registers.xlsx` (sha256 `f9a070080c3ef23b...`)
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

