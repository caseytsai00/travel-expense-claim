"""Domain engine: turns parsed sources into per-batch snapshot state.

Human-authority boundary: this module NEVER fabricates a review outcome,
approval, or Finance decision -- it only reads already-recorded decisions
(review_ledger, finance_activity) and computes derived facts (entitlement,
evidence completeness, filing deadlines). It does not decide funding,
approve claims, or move money.
"""
from decimal import Decimal

import policy_rules as pr


def _latest_by_role(review_ledger, subject_type, subject_id, revision, as_of_batch):
    """Latest decision per role, considering only rows visible as of this batch."""
    rows = [
        r
        for r in review_ledger
        if r["Subject type"] == subject_type
        and r["Subject reference"] == subject_id
        and int(r["Revision"]) == revision
        and int(r["Arrival batch"]) <= as_of_batch
    ]
    by_role_instance = {}
    for r in rows:
        for role in str(r["Review roles"]).split("\n"):
            role = role.strip()
            key = role
            prev = by_role_instance.get(key)
            if prev is None or int(r["Arrival batch"]) >= int(prev["Arrival batch"]):
                by_role_instance[key] = r
    return by_role_instance


def _find_receipt(receipts_by_cost, cost_id):
    return receipts_by_cost.get(cost_id)


def _find_merchant_payment(payments_by_cost, cost_id):
    return payments_by_cost.get(cost_id)


def resolve_claim_line(
    line,
    claim_rec,
    trip,
    receipts_by_cost,
    payments_by_cost,
    caps_rows,
    fx_rows,
    exceptions_by_cost,
    seen_cost_owner,
    trip_late_filing,
    permit_gate,
    cancellation_gate,
):
    """Returns (status, allowed_cents, reason, source_ids)."""
    cost_id = line["cost_id"]
    claim_id = claim_rec["claim_id"]
    source_ids = [claim_rec["source_id"]]

    # Duplicate cost across DIFFERENT claims: first claimant owns it.
    owner = seen_cost_owner.get(cost_id)
    if owner is not None and owner != claim_id:
        return (
            "excluded",
            0,
            f"Cost {cost_id} already claimed under {owner}; excluded here to avoid double payment",
            source_ids,
        )
    seen_cost_owner.setdefault(cost_id, claim_id)

    receipt = _find_receipt(receipts_by_cost, cost_id)
    if receipt is None:
        return ("unresolved", None, f"No receipt on file for {cost_id}", source_ids)
    source_ids.append(receipt["source_id"])

    payment = _find_merchant_payment(payments_by_cost, cost_id)
    if payment is None or payment["Payment status"] != "settled":
        return (
            "unresolved",
            None,
            f"No settled merchant payment proof for {cost_id}",
            source_ids,
        )
    source_ids.append("SRC-5-travel-registers")

    # Identity/amount match per policy: "Match employee, trip, cost ID, currency and gross amount."
    mismatches = []
    if receipt["employee"] != claim_rec["employee"]:
        mismatches.append("employee mismatch between receipt and claim")
    if receipt["trip_id"] != claim_rec["trip_id"]:
        mismatches.append("trip mismatch between receipt and claim")
    if payment["Currency"] != line["currency"] or receipt["currency"] != line["currency"]:
        mismatches.append("currency mismatch across claim/receipt/payment")
    if float(payment["Gross amount"]) != line["original_amount"] or receipt["gross_amount"] != line["original_amount"]:
        mismatches.append("gross amount mismatch across claim/receipt/payment")
    if mismatches:
        return ("unresolved", None, "; ".join(mismatches), source_ids)

    category = receipt["category"]
    if category == "personal":
        return ("excluded", 0, "Personal purchase has zero entitlement", source_ids)

    exception = exceptions_by_cost.get(cost_id)
    covered = set(exception["covered_issues"]) if exception else set()

    if trip_late_filing and "late_filing" not in covered:
        return (
            "unresolved",
            None,
            f"Filed after the 2-calendar-month deadline for trip {claim_rec['trip_id']}; needs a Finance late_filing exception",
            source_ids,
        )

    if permit_gate and permit_gate not in covered:
        return (
            "unresolved",
            None,
            f"International trip {claim_rec['trip_id']} permit issue ({permit_gate}); needs a Finance exception",
            source_ids,
        )

    if cancellation_gate and "travel_cancellation" not in covered:
        return (
            "unresolved",
            None,
            f"Trip/permit for {claim_rec['trip_id']} has an unresolved cancellation; needs Finance's cancellation-bound cost disposition",
            source_ids,
        )

    payment_date = pr.parse_date(payment["Paid date"])
    fx_rate, fx_ref = pr.lookup_fx_rate(fx_rows, line["currency"], payment_date)
    if fx_rate is None:
        return ("unresolved", None, f"No FX rate available for {line['currency']} on {payment_date}", source_ids)
    if fx_ref:
        source_ids.append("SRC-5-travel-registers")

    if exception is not None:
        allowed_original = Decimal(str(exception["allowed_original_amount"]))
        reason = f"Finance exception by {exception['actor']}: {exception['exception_reason']}"
        source_ids.append("SRC-3-claims-updates")
    else:
        documented_units = receipt["documented_units"]
        cap = pr.lookup_cap(caps_rows, trip["Destination"], category, payment_date)
        if category in ("lodging", "meals"):
            if cap is None:
                return (
                    "unresolved",
                    None,
                    f"No applicable cap for {category} at {trip['Destination']} on {payment_date}",
                    source_ids,
                )
            if documented_units is None:
                return ("unresolved", None, f"Missing documented units for {cost_id}", source_ids)
        allowed_original = pr.compute_line_allowed_original(
            category, payment["Gross amount"], documented_units, cap
        )
        if allowed_original is None:
            return ("unresolved", None, f"Could not compute allowed amount for {cost_id}", source_ids)
        reason = "Supported by receipt + settled merchant payment; within policy cap" if cap else "Supported by receipt + settled merchant payment"

    allowed_cents = pr.round_half_up_cents(allowed_original * fx_rate)
    return ("supported", allowed_cents, reason, source_ids)


FINANCE_STATUS_MAP = {
    "accepted": "accepted",
    "settled": "settled",
    "failed": "held",
    "retry_authorized": "accepted",
    "cancellation_requested": "cancel-pending",
    "cancelled": "cancelled",
    "adjustment": None,  # doesn't change request status by itself
    "refund": None,
    "resolution": "settled",
}


def derive_request(finance_rows_for_claim, as_of_batch, claim_id, currency, payee):
    candidates = sorted(
        (r for r in finance_rows_for_claim if int(r["Arrival batch"]) <= as_of_batch),
        key=lambda r: (int(r["Arrival batch"]), r["Activity time (UTC)"]),
    )
    # Same activity reference can be redelivered in a later arrival batch
    # (idempotency test, e.g. F-C01-1 at both batch 2 and batch 4, identical
    # payload) -- admit each distinct activity reference exactly once.
    rows = []
    seen_activity_refs = set()
    for r in candidates:
        ref = r["Activity reference"]
        if ref in seen_activity_refs:
            continue
        seen_activity_refs.add(ref)
        rows.append(r)
    if not rows:
        return None

    request_id = rows[0]["Request reference"]
    status = "proposed"
    obligation_cents = None
    settled_cents = 0
    refunded_cents = 0
    decision_ids = []
    for r in rows:
        decision_ids.append(r["Activity reference"])
        atype = r["Activity type"]
        mapped = FINANCE_STATUS_MAP.get(atype)
        if mapped:
            status = mapped
        if r["Obligation (EUR)"] not in (None, ""):
            obligation_cents = pr.round_half_up_cents(Decimal(str(r["Obligation (EUR)"])))
        if atype == "settled" and r["Amount (EUR)"] not in (None, ""):
            settled_cents += pr.round_half_up_cents(Decimal(str(r["Amount (EUR)"])))
        if atype == "refund" and r["Amount (EUR)"] not in (None, ""):
            refunded_cents += pr.round_half_up_cents(Decimal(str(r["Amount (EUR)"])))

    net_paid_cents = settled_cents - refunded_cents
    amount_cents = obligation_cents if obligation_cents is not None else settled_cents

    return {
        "request_id": request_id,
        "claim_id": claim_id,
        "amount_cents": amount_cents,
        "payee": payee,
        "currency": currency,
        "status": status,
        "decision_ids": decision_ids,
        "net_paid_cents": net_paid_cents,
        "activity_rows": rows,
    }
