# Policy formulas -- index into `scripts/policy_rules.py`

Every constant/function below implements one sentence of
`artifacts/runs/<run-id>/sources/policy.md` (POL-2026.2). These are policy
business rules (apply to every case), never case-specific answers.

| Function / constant | Policy sentence it encodes |
|---|---|
| `DIRECTOR_THRESHOLD_EUR_CENTS = 100_000` | "A director additionally reviews amounts strictly above EUR 1,000.00 ... Exactly EUR 1,000.00 does not require a director." |
| `FILING_WINDOW_MONTHS = 2`, `filing_deadline`, `add_months_clamped` | "The latest ordinary filing date is two calendar months after trip end, inclusive, with a nonexistent day clamped to month end. For a trip ending 31 August, the deadline is 31 October." |
| `BASE_REQUIRED_ROLES` | "Permit administration, budget owner and supervisor review the trip estimate. Claim administration, budget owner and supervisor separately review actual reimbursement." |
| `satisfied_roles` (role-collapse handling) | "When budget owner and supervisor are the same stable person, one response with both roles satisfies those two positions for that subject/version." |
| `round_half_up_cents` | "Round each converted line to EUR cents using decimal half-up; sum rounded line amounts." |
| `lookup_fx_rate` | "Apply Finance's exact payment-date EUR-per-currency-unit rate; EUR uses 1." |
| `lookup_cap` | "Lodging uses the supplied cap per night; meals use the supplied cap per day. ... Caps are in the expense currency for the destination and employee-payment date." |
| `compute_line_allowed_original` | "Transport and conference have no category cap. ... allowed original amount = min(supported gross amount, applicable cap x documented units); transport/conference use supported gross amount." |
| (engine.py) personal-purchase exclusion | "Personal purchases have zero entitlement." |
| (engine.py) missing-evidence -> unresolved, never zero | "An unknown category, missing evidence, missing rate or missing applicable cap is unresolved, never an assumed zero." |
| (engine.py) exception cannot waive receipt/payment proof | Interview transcript: "Finance exception mechanism CANNOT waive receipt or settled-payment-proof requirements." (Not restated verbatim in POL-2026.2's own text, but consistent with "No exception makes an unpaid cost paid" -- see `findings.md` for the interview citation.) |
| (engine.py) exception `covered_issues` gating | "That list may explicitly resolve late_filing, late_permit, permit_unapproved or travel_cancellation for reimbursement eligibility only; an amount-only exception uses an empty list." |
| (engine.py) domestic vs. international permit requirement | "Domestic trips do not need a permit. An international trip needs its own approved permit before the first arrangement/payment commitment." |
| (engine.py) late permit doesn't retroactively authorize | "A late permit does not retroactively authorize travel arrangements; Finance may explicitly resolve reimbursement eligibility while the permit exception remains recorded." |
| (build_run.py) corrections retain original submission date | "Corrections retain the initial submission date for unchanged costs; newly added costs use their own first submission date." |

Not yet exercised by this run's retained sources (documented, not
hard-coded around): a claim/permit whose computed entitlement/estimate lands
at exactly EUR 1,000.00 (boundary case for the director trigger); a
multi-currency FX rate table with more than one dated rate per currency
(current `lookup_fx_rate` supports it via date-matching, but the retained FX
tab only ever supplies one rate per currency).
