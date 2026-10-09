#!/usr/bin/env python3
"""Orchestrates a full run: parse retained sources -> compute per-batch state
-> write sealed batch snapshots, claims.csv, report.md, and the local work
queue under artifacts/runs/<run-id>/.

Usage: python3 build_run.py <path-to-sources.json>
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

import parse_sources as ps
import policy_rules as pr
import engine as eng

SCRIPT_DIR = Path(__file__).resolve().parent


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def index_by(rows, key):
    return {r[key]: r for r in rows}


def build(sources_json_path):
    data = ps.load_all(sources_json_path)
    manifest = data["manifest"]
    run_id = manifest["run_id"]
    run_root = Path(sources_json_path).parent

    tabs = data["tabs"]
    people_by_emp = index_by(tabs["People"], "Employee ID")
    trips_by_id = index_by(tabs["Trips"], "Trip reference")
    receipts_by_cost = {}
    for r in data["receipts"]:
        receipts_by_cost.setdefault(r["cost_id"], r)
    payments_by_cost = {}
    for r in tabs["Merchant payments"]:
        payments_by_cost.setdefault(r["Expense reference"], r)
    caps_rows = tabs["Caps"]
    fx_rows = tabs["FX"]
    review_ledger = tabs["Review ledger"]
    finance_activity = tabs["Finance activity"]
    tc_rows = tabs["Travel cancellations"]

    claims_by_id = data["claims_by_id"]

    all_batches = set()
    for revs in claims_by_id.values():
        for r in revs:
            all_batches.add(r["arrival_batch"])
    for r in review_ledger + finance_activity + tc_rows:
        all_batches.add(int(r["Arrival batch"]))
    batch_numbers = sorted(all_batches)

    finance_by_claim = {}
    for r in finance_activity:
        finance_by_claim.setdefault(r["Claim reference"], []).append(r)

    run_dir = run_root
    batches_dir = run_dir / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)

    sources_json_sha = sha256_file(sources_json_path)
    source_binding = {"path": str(_repo_relative(sources_json_path)), "sha256": sources_json_sha}

    predecessor = None
    predecessor_path = None
    all_issues_log = []  # for report/work-queue use after the loop
    final_snapshot = None

    for batch_no in batch_numbers:
        snapshot, issues_detail = compute_batch_snapshot(
            batch_no,
            run_id,
            claims_by_id,
            people_by_emp,
            trips_by_id,
            receipts_by_cost,
            payments_by_cost,
            caps_rows,
            fx_rows,
            review_ledger,
            finance_by_claim,
            tc_rows,
            predecessor,
            source_binding,
        )
        batch_id = f"batch-{batch_no}"
        snapshot["batch_id"] = batch_id
        out_path = batches_dir / f"{batch_id}.json"
        out_path.write_text(json.dumps(snapshot, indent=2, sort_keys=False) + "\n")
        sha = sha256_file(out_path)
        predecessor = {"path": str(_repo_relative(out_path)), "sha256": sha}
        all_issues_log.append((batch_no, issues_detail))
        final_snapshot = snapshot
        print(f"wrote {out_path} ({len(snapshot['claims'])} claims, {len(snapshot['issues'])} issues)")

    return run_dir, final_snapshot, batch_numbers, all_issues_log, {
        "people_by_emp": people_by_emp,
        "trips_by_id": trips_by_id,
        "claims_by_id": claims_by_id,
    }


def _repo_relative(path):
    # Repo root relative to THIS script's fixed location
    # (skills/travel-expense-claim/scripts/), not by matching a directory
    # name in the path -- a name match breaks under any git worktree, where
    # the checkout is nested under a same-named ancestor directory.
    repo_root = SCRIPT_DIR.parent.parent.parent
    return Path(path).resolve().relative_to(repo_root)


def current_revision(revs, as_of_batch):
    applicable = [r for r in revs if r["arrival_batch"] <= as_of_batch]
    if not applicable:
        return None
    return applicable[-1]


def compute_permit_gate(trip, as_of_batch, review_ledger):
    """Returns None (no gate) or a covered_issues-style string naming the gate."""
    if str(trip.get("International")) != "True":
        return None
    permit_id = trip.get("Permit reference")
    permit_revision = trip.get("Permit revision")
    if not permit_id:
        return "permit_unapproved"
    roles = eng._latest_by_role(review_ledger, "permit", permit_id, int(permit_revision or 1), as_of_batch)
    required = {"administration", "budget_owner", "supervisor"}
    approved_roles = set()
    for role_key, row in roles.items():
        if row["Outcome"] == "approve":
            approved_roles.update(pr.satisfied_roles([role_key]))
    if not required.issubset(approved_roles):
        return "permit_unapproved"
    approval_times = [row["Decision time (UTC)"] for row in roles.values() if row["Outcome"] == "approve"]
    first_commitment = trip.get("First commitment date")
    if first_commitment and approval_times:
        latest_approval = max(approval_times)
        if str(latest_approval) > str(first_commitment):
            return "late_permit"
    return None


def compute_cancellations(tc_rows, people_by_emp, as_of_batch):
    by_cancellation = {}
    for r in tc_rows:
        if int(r["Arrival batch"]) > as_of_batch:
            continue
        cid = r["Cancellation reference"]
        by_cancellation.setdefault(cid, []).append(r)

    result = {}
    for cid, rows in by_cancellation.items():
        rows.sort(key=lambda r: (int(r["Arrival batch"]), r["Activity time (UTC)"]))
        admitted_ids = sorted({r["Cancellation activity reference"] for r in rows})
        latest = rows[-1]
        status = "confirmed" if any(r["Action"] == "confirmed" for r in rows) else "requested"
        requested_rows = [r for r in rows if r["Action"] == "requested"]
        confirmed_rows = [r for r in rows if r["Action"] == "confirmed"]
        requested_at = requested_rows[0]["Activity time (UTC)"] if requested_rows else rows[0]["Activity time (UTC)"]
        confirmed_at = confirmed_rows[0]["Effective time (UTC)"] if confirmed_rows else None
        effective_at = confirmed_rows[0]["Effective time (UTC)"] if confirmed_rows else None
        acting = latest["Acting employee or supervisor"]
        employee_row = None
        for emp, row in people_by_emp.items():
            pass
        result[cid] = {
            "cancellation_id": cid,
            "target_type": latest["Cancelled subject"],
            "trip_id": latest["Trip reference"],
            "trip_revision": int(float(latest["Trip revision"])),
            "permit_id": latest["Permit reference"] or None,
            "permit_revision": int(float(latest["Permit revision"])) if latest["Permit revision"] else None,
            "status": status,
            "admitted_cancellation_event_ids": admitted_ids,
            "requested_at": _to_iso(requested_at),
            "confirmed_at": _to_iso(confirmed_at) if confirmed_at else None,
            "effective_at": _to_iso(effective_at) if effective_at else None,
            "reason": latest["Business reason"],
            "acting_party": acting,
        }
    return result


def _to_iso(v):
    if v is None or v == "":
        return None
    s = str(v).replace(" ", "T")
    if not s.endswith("Z") and "+" not in s:
        s += "Z"
    return s


def compute_batch_snapshot(
    batch_no,
    run_id,
    claims_by_id,
    people_by_emp,
    trips_by_id,
    receipts_by_cost,
    payments_by_cost,
    caps_rows,
    fx_rows,
    review_ledger,
    finance_by_claim,
    tc_rows,
    predecessor,
    source_binding,
):
    cancellations = compute_cancellations(tc_rows, people_by_emp, batch_no)

    # index cancellations by (trip_id, trip_revision) and (permit_id, permit_revision)
    trip_cancel = {}
    permit_cancel = {}
    for c in cancellations.values():
        if c["target_type"] == "trip":
            trip_cancel[(c["trip_id"], c["trip_revision"])] = c
        else:
            permit_cancel[(c["permit_id"], c["permit_revision"])] = c

    issues = []
    claims_out = []
    requests_out = []
    admitted_event_ids = set()
    seen_cost_owner = {}

    # Process claims in a stable, deterministic order (claim_id sorted numerically).
    def claim_sort_key(cid):
        digits = "".join(ch for ch in cid if ch.isdigit())
        return (int(digits) if digits else 0, cid)

    for claim_id in sorted(claims_by_id.keys(), key=claim_sort_key):
        revs = claims_by_id[claim_id]
        rev = current_revision(revs, batch_no)
        if rev is None:
            continue  # not yet arrived as of this batch

        trip = trips_by_id.get(rev["trip_id"], {})
        employee = rev["employee"]
        person = people_by_emp.get(employee, {})

        trip_end = pr.parse_date(trip.get("End date")) if trip else None
        trip_late = False
        if trip_end is not None:
            trip_late = pr.is_late_filing(pr.parse_date(rev["submitted_date"]), trip_end)

        permit_gate = compute_permit_gate(trip, batch_no, review_ledger) if trip else None

        trip_key = (rev["trip_id"], rev.get("trip_revision") or 1)
        permit_key = (trip.get("Permit reference"), trip.get("Permit revision")) if trip else (None, None)
        active_cancel = None
        if trip_key in trip_cancel:
            active_cancel = trip_cancel[trip_key]
        elif permit_key in permit_cancel:
            active_cancel = permit_cancel[permit_key]
        cancellation_gate = bool(active_cancel and active_cancel["status"] == "confirmed")

        exceptions_by_cost = {e["cost_id"]: e for e in rev["exceptions"]}

        line_results = []
        for line in rev["lines"]:
            status, allowed_cents, reason, source_ids = eng.resolve_claim_line(
                line,
                rev,
                trip,
                receipts_by_cost,
                payments_by_cost,
                caps_rows,
                fx_rows,
                exceptions_by_cost,
                seen_cost_owner,
                trip_late,
                permit_gate,
                cancellation_gate,
            )
            line_results.append(
                {
                    "cost_id": line["cost_id"],
                    "source_ids": sorted(set(source_ids)),
                    "status": status,
                    "allowed_cents": allowed_cents,
                    "reason": reason,
                }
            )

        # Review decisions for this revision as of this batch.
        role_decisions = eng._latest_by_role(review_ledger, "claim", claim_id, rev["revision"], batch_no)
        approved_roles = set()
        rejected = None
        returned = None
        for role_key, row in role_decisions.items():
            roles_here = pr.satisfied_roles([role_key])
            if row["Outcome"] == "approve":
                approved_roles.update(roles_here)
            elif row["Outcome"] == "reject" and rejected is None:
                rejected = row
            elif row["Outcome"] == "return" and returned is None:
                returned = row

        any_unresolved = any(l["status"] == "unresolved" for l in line_results)
        total_allowed = sum(l["allowed_cents"] for l in line_results if l["allowed_cents"] is not None)
        need_director = pr.director_required(total_allowed) if not any_unresolved else False
        required = set(pr.BASE_REQUIRED_ROLES) | ({"director"} if need_director else set())

        decision_ids = sorted({row["Decision reference"] for row in role_decisions.values()})

        finance_rows = finance_by_claim.get(claim_id, [])
        request = eng.derive_request(
            finance_rows, batch_no, claim_id, "EUR",
            person.get("Payee ID", employee),
        )

        status = None
        next_owner = None
        reason = None
        allowed_cents_out = None
        # Money-movement facts are real regardless of review/evidence status
        # -- "zero is a known amount, distinct from unknown" applies here too.
        # Populate paid_cents from Finance's actual activity up front so a
        # claim stuck pending/held still truthfully reports money Finance
        # already moved against it (see the payment-anomaly issue below).
        paid_cents = request["net_paid_cents"] if request is not None else 0
        if request is not None:
            admitted_event_ids.update(request["decision_ids"])
        balance_cents = None

        if rejected is not None:
            status = "rejected"
            reason = f"{rejected['Reviewer']} ({rejected['Review roles']}) rejected: {rejected['Reason']}"
            allowed_cents_out = 0
            balance_cents = 0
            next_owner = None
        elif returned is not None:
            status = "held"
            reason = f"{returned['Reviewer']} ({returned['Review roles']}) returned: {returned['Reason']}"
            next_owner = returned["Reviewer"]
        elif not required.issubset(approved_roles):
            missing = required - approved_roles
            status = "pending"
            reason = f"Awaiting review from: {', '.join(sorted(missing))}"
            next_owner = sorted(missing)[0]
        elif any_unresolved:
            status = "held"
            unresolved_reasons = [l["reason"] for l in line_results if l["status"] == "unresolved"]
            reason = "; ".join(unresolved_reasons)
            # Policy explicitly groups "unknown category" with the other
            # evidence-type gaps ("An unknown category, missing evidence,
            # missing rate or missing applicable cap is unresolved, never
            # an assumed zero" -- policy.md) rather than singling it out, so
            # it is owned the same way: the employee, who can correct a
            # miscoded receipt or supply the missing evidence.
            next_owner = employee
        else:
            allowed_cents_out = total_allowed
            if request is None:
                status = "ready"
                reason = "Approved and entitlement computed; awaiting Finance dispatch"
                next_owner = person.get("Finance officer", "FIN-01")
            else:
                if request["status"] == "cancelled" and paid_cents == 0:
                    status = "closed-no-payment"
                    reason = "Finance cancelled the payment request; no funds moved"
                    balance_cents = 0
                    next_owner = None
                elif allowed_cents_out == 0:
                    status = "closed-no-payment"
                    reason = "Zero entitlement; no payment due"
                    balance_cents = 0
                    next_owner = None
                elif request["status"] == "settled" and paid_cents == allowed_cents_out:
                    status = "closed-reimbursed"
                    reason = "Approvals and entitlement agree with net confirmed settlement"
                    balance_cents = 0
                    next_owner = None
                else:
                    status = "ready"
                    reason = f"Finance request status: {request['status']}"
                    balance_cents = allowed_cents_out - paid_cents
                    next_owner = person.get("Finance officer", "FIN-01")

        claim_out = {
            "claim_id": claim_id,
            "revision": rev["revision"],
            "trip_id": rev["trip_id"],
            "trip_revision": rev.get("trip_revision") or 1,
            "status": status,
            "lines": line_results,
            "allowed_cents": allowed_cents_out,
            "paid_cents": paid_cents,
            "balance_cents": balance_cents,
            "decision_ids": decision_ids,
            "next_owner": next_owner,
            "reason": reason,
        }
        claims_out.append(claim_out)

        if request is not None:
            requests_out.append(
                {
                    "request_id": request["request_id"],
                    "claim_id": claim_id,
                    "revision": rev["revision"],
                    "amount_cents": request["amount_cents"],
                    "payee": request["payee"],
                    "currency": request["currency"],
                    "status": request["status"],
                    "decision_ids": request["decision_ids"],
                }
            )

        if status == "held" or status == "pending":
            issues.append(
                {
                    "record_id": claim_id,
                    "reason": reason,
                    "owner": next_owner or "unassigned",
                    "resolution_needed": reason,
                }
            )

        sequence_conflict = request["sequence_conflict"] if request is not None else None

        if sequence_conflict is not None:
            # Finance's own activity log for this request reached one terminal
            # status (e.g. cancelled) and later reached the other (e.g.
            # settled) -- a direct contradiction in Finance's own record, not
            # a claim-side evidence/review gap. No amount of evidence arriving
            # resolves this; only Finance/administration can say which fact is
            # authoritative, so it gets its own record distinct from the
            # ordinary payment-anomaly case below.
            issues.append(
                {
                    "record_id": f"{claim_id}-finance-conflict",
                    "reason": (
                        f"Finance's own activity log for {sequence_conflict['request_id']} shows "
                        f"'{sequence_conflict['from_status']}' at {sequence_conflict['from_at']} "
                        f"then '{sequence_conflict['to_status']}' at {sequence_conflict['to_at']} "
                        f"for the same request -- following claim {claim_id}'s revision {rev['revision']} "
                        f"({reason})"
                    ),
                    "owner": "FIN-01",
                    "resolution_needed": "Finance/administration must determine which fact is authoritative (e.g. void the cancellation, or reverse the settlement) before this revision can close -- this is not resolved by evidence arriving",
                }
            )
        elif status in ("held", "pending", "rejected") and paid_cents != 0:
            # Finance moved real money against a revision that is not fully
            # reviewed/resolved on the retained sources -- a compliance
            # anomaly to surface explicitly, never to smooth over by hiding
            # the payment or by inferring a review that was never recorded.
            issues.append(
                {
                    "record_id": f"{claim_id}-payment-anomaly",
                    "reason": (
                        f"Finance recorded {paid_cents} EUR-cents net paid against {claim_id} "
                        f"revision {rev['revision']}, but that revision is currently '{status}' "
                        f"(not closed-reimbursed) -- {reason}"
                    ),
                    "owner": "FIN-01",
                    "resolution_needed": "Finance/administration to confirm whether the payment is valid against this revision's actual approvals/evidence, or requires recovery/adjustment",
                }
            )

    # --- Travel cancellations output ---
    # Affected claims/requests must be found across each claim's FULL revision
    # history, not just its current revision: a correction can move a claim
    # onto a replacement trip (e.g. C18: T18 -> T18B) while the cancellation
    # still targets the OLD trip/permit the claim was originally filed under.
    def revisions_matching_target(target_type, trip_id, trip_revision, permit_id, permit_revision):
        matches = set()
        for cid_inner, revs in claims_by_id.items():
            for r in revs:
                if r["arrival_batch"] > batch_no:
                    continue
                if target_type == "trip":
                    if r["trip_id"] == trip_id and (r.get("trip_revision") or 1) == trip_revision:
                        matches.add(cid_inner)
                else:
                    trip = trips_by_id.get(r["trip_id"], {})
                    if trip.get("Permit reference") == permit_id and (
                        int(trip.get("Permit revision") or 1) == (permit_revision or 1)
                    ):
                        matches.add(cid_inner)
        return matches

    tc_out = []
    for cid, c in cancellations.items():
        affected_claims = sorted(
            revisions_matching_target(
                c["target_type"], c["trip_id"], c["trip_revision"], c["permit_id"], c["permit_revision"]
            )
        )
        original_requests = sorted(
            {
                r["Request reference"]
                for claim_id_inner in affected_claims
                for r in finance_by_claim.get(claim_id_inner, [])
                if int(r["Arrival batch"]) <= batch_no
            }
        )
        has_costs_or_requests = bool(affected_claims) or bool(original_requests)

        if c["status"] == "requested":
            employee_for_trip = None
            for cl in claims_out:
                if cl["trip_id"] == c["trip_id"]:
                    employee_for_trip = cl
                    break
            financial_status = "unresolved" if has_costs_or_requests else "no-financial-effect"
            next_owner_c = c["acting_party"]  # directory supervisor confirming
            confirmed_at = None
            effective_at = None
        else:
            if not has_costs_or_requests:
                financial_status = "no-financial-effect"
                next_owner_c = None
            else:
                cancel_finance_activity = [
                    r
                    for claim_id in affected_claims
                    for r in finance_by_claim.get(claim_id, [])
                    if int(r["Arrival batch"]) <= batch_no
                ]
                has_resolution = any(r["Activity type"] in ("resolution", "cancelled") for r in cancel_finance_activity)
                has_exception_citing = any(
                    e.get("travel_cancellation_ref") == cid
                    for revs in claims_by_id.values()
                    for r in revs
                    if r["arrival_batch"] <= batch_no
                    for e in r["exceptions"]
                )
                if has_resolution or has_exception_citing:
                    financial_status = "resolved"
                    next_owner_c = None
                else:
                    financial_status = "unresolved"
                    next_owner_c = "FIN-01"
            confirmed_at = c["confirmed_at"]
            effective_at = c["effective_at"]

        issue_ids = []
        if financial_status == "unresolved":
            issue_id = f"{cid}-financial"
            issues.append(
                {
                    "record_id": issue_id,
                    "reason": f"Cancellation {cid} confirmed but Finance has not yet resolved affected cost disposition",
                    "owner": "FIN-01",
                    "resolution_needed": "Finance cancellation-bound cost disposition + cancellation-aware claim review",
                }
            )
            issue_ids.append(issue_id)

        tc_out.append(
            {
                "cancellation_id": cid,
                "target_type": c["target_type"],
                "trip_id": c["trip_id"],
                "trip_revision": c["trip_revision"],
                "permit_id": c["permit_id"],
                "permit_revision": c["permit_revision"],
                "status": c["status"],
                "admitted_cancellation_event_ids": c["admitted_cancellation_event_ids"],
                "requested_at": c["requested_at"],
                "confirmed_at": confirmed_at,
                "effective_at": effective_at,
                "affected_claim_ids": affected_claims,
                "original_request_ids": original_requests,
                "financial_status": financial_status,
                "next_owner": next_owner_c,
                "reason": c["reason"],
                "issue_record_ids": issue_ids,
            }
        )

    snapshot = {
        "schema_version": "travel-claim-snapshot/2",
        "run_id": run_id,
        "batch_id": None,  # filled by caller
        "predecessor": predecessor,
        "source_binding": source_binding,
        "claims": claims_out,
        "requests": requests_out,
        "travel_cancellations": tc_out,
        "admitted_event_ids": sorted(admitted_event_ids),
        "issues": issues,
    }
    return snapshot, issues


if __name__ == "__main__":
    sources_json = sys.argv[1] if len(sys.argv) > 1 else "artifacts/runs/run-2026-09-30/sources.json"
    build(sources_json)
