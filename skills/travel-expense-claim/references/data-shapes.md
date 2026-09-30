# Source data shapes

Exact column/field layout the parser (`scripts/parse_sources.py`) depends on.
If a future run's sources deviate from this shape, the parser will raise or
silently miss fields -- check this file first when debugging a parse gap.

## Source 1: policy (Notion page, retained as `sources/policy.md`)

Free text, not machine-parsed. Its business rules are hand-encoded as cited
constants/functions in `scripts/policy_rules.py` -- see
`references/policy-formulas.md`.

## Source 2 + 3: claim binders (PDF, one claim revision per page)

Each page is plain extracted text in this field order:

```
Claim reference: <claim_id>
Revision: <int>
Arrival batch: <int>
Employee: <employee_id>
Trip reference: <trip_id>
Trip revision: <int>
Submitted date: <YYYY-MM-DD>
Status: <submitted|...>
Claim reason: <free text>
Related earlier claims: <None | comma-separated claim ids>
Expense details
Line / Expense reference / Receipt reference / First submitted date / Original amount / Currency
<repeated rows, one per cost line>
Finance exception: Not supplied
```
or, when an exception applies, in place of the last line:
```
Finance exception
Authorizing Finance officer: <id>
Applies to claim: <claim_id>
Applies to revision: <int>
Expense reference: <cost_id>
Allowed original amount: <decimal>
Covered issues: <None | comma-separated: late filing, late permit, permit unapproved, travel cancellation>
Travel cancellation reference: <cancellation_id>   [only when covered_issues includes travel_cancellation]
Exception reason: <free text, may span multiple lines>
```

## Source 4: receipts (PDF, one receipt per page)

```
Receipt reference: <receipt_id>
Expense reference: <cost_id>
Employee: <employee_id>
Trip reference: <trip_id>
Category: <transport|conference|lodging|meals|personal>
Currency: <ISO 4217>
Gross amount: <decimal>
Documented units: <int, only meaningful for lodging/meals>
Description: <free text>
Issued date: <YYYY-MM-DD>
```

## Source 5: travel-registers workbook (xlsx, 10 tabs)

Every tab: row 1 = title, row 2 = "Synthetic business records. SRC-D-3.",
row 3 = a free-text note, row 4 = blank, row 5 = header, rows 6+ = data.
`parse_sources._sheet_to_dicts` assumes exactly this 5-row preamble.

| Tab | Key columns |
|---|---|
| People | Employee ID, Department, Project, Budget period, Payee ID, Administration reviewer, Budget owner, Supervisor, Director, Finance officer |
| Trips | Trip reference, Employee ID, Destination, International, Start date, End date, First commitment date, Estimate (EUR), Business purpose, Client, Schedule coverage, Alternatives considered, Permit reference, Trip revision, Permit revision |
| Merchant payments | Transaction reference, Expense reference, Employee ID, Trip reference, Currency, Gross amount, Paid date, Payment status, Receipt reference |
| FX | Rate reference, Rate date, Currency, EUR per currency unit |
| Caps | Cap reference, Destination, Category, Currency, Effective from, Effective to, Amount per unit |
| Budget | Ledger reference, Department, Project, Budget period, Entry type, Obligation reference, Allocation or commitment (EUR), Settled (EUR), Refunded (EUR) |
| Review ledger | Decision reference, Arrival batch, Subject type (claim/permit), Subject reference, Revision, Review roles (single role or `role1\nrole2` when collapsed), Reviewer, Outcome (approve/reject/return), Reason, Repair requested, Source revisions, Affected fields, Decision time (UTC) |
| Review packets | Decision reference, Employee ID, Trip reference, ..., Reviewed estimate (EUR) [permit-only, blank for claim decisions], Budget owner position, Trip revision, Permit revision, Travel cancellation references |
| Finance activity | Activity reference, Arrival batch, Activity type (accepted/settled/failed/retry_authorized/cancellation_requested/cancelled/adjustment/refund/resolution), Request reference, Claim reference, Finance officer, Payee ID, Currency, Amount (EUR), Original activity reference, Obligation (EUR), Reason, Activity time (UTC) |
| Travel cancellations | Cancellation activity reference, Cancellation reference, Action (requested/confirmed), Cancelled subject (trip/permit), Trip reference, Trip revision, Permit reference, Permit revision, Initiation activity reference, Acting employee or supervisor, Activity time (UTC), Effective time (UTC), Arrival batch, Business reason |

**Known intentional data quirks** (not parser bugs -- verified in this run):

- `Merchant_payments`/`Finance_activity`/`Travel_cancellations` can redeliver
  the exact same reference (`Activity reference` / `Cancellation activity
  reference`) at a later `Arrival batch`, byte-identical -- an idempotency
  test. Admit each distinct reference once.
- `Review ledger`'s "Source revisions" column is a constant 3-part citation
  (`DW-D-2` / policy revision / binder revision) on every row -- informational,
  not a per-row signal.
- Roughly half of all claim-line `cost_id`s never get a matching receipt in
  the receipts binder, even after the updates binder arrives -- this is the
  dominant "unresolved" scenario in the dataset, not a parse failure.
