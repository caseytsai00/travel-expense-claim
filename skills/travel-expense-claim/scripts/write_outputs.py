#!/usr/bin/env python3
"""Writes claims.csv, work_queue.json, and report.md from the batch snapshots
a build_run.py run already produced under artifacts/runs/<run-id>/.

Usage: python3 write_outputs.py <path-to-sources.json>
"""
import csv
import json
import sys
from pathlib import Path


def load_batches(run_dir):
    batches_dir = run_dir / "batches"
    batch_files = sorted(
        batches_dir.glob("batch-*.json"), key=lambda p: int(p.stem.split("-")[1])
    )
    return [json.loads(p.read_text()) for p in batch_files]


def write_claims_csv(final_snapshot, run_dir):
    path = run_dir / "claims.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["claim_id", "revision", "trip_id", "status", "allowed_cents", "paid_cents", "balance_cents", "next_owner", "reason"]
        )
        for c in sorted(final_snapshot["claims"], key=lambda c: (len(c["claim_id"]), c["claim_id"])):
            w.writerow(
                [
                    c["claim_id"],
                    c["revision"],
                    c["trip_id"],
                    c["status"],
                    "" if c["allowed_cents"] is None else c["allowed_cents"],
                    c["paid_cents"],
                    "" if c["balance_cents"] is None else c["balance_cents"],
                    c["next_owner"] or "",
                    c["reason"],
                ]
            )
    return path


MISSING_FACT_GROUPS = [
    ("unknown_category", "Unknown category"),
    ("finance_sequence_conflict", "Finance's own activity log for"),
    ("payment_anomaly", "Finance recorded"),
    ("missing_receipt", "No receipt on file for"),
    ("missing_merchant_proof", "No settled merchant payment proof for"),
    ("missing_cap", "No applicable cap for"),
    ("missing_units", "Missing documented units for"),
    ("missing_fx_rate", "No FX rate available for"),
    ("late_filing_awaiting_exception", "Filed after the 2-calendar-month deadline"),
    ("permit_gap_awaiting_exception", "permit issue"),
    ("cancellation_pending_finance", "unresolved cancellation"),
    ("awaiting_initial_review", "Awaiting review from:"),
    ("business_hold_returned", "returned:"),
    ("finance_resolution_pending", "Cancellation"),
]


def classify_reason(reason):
    for tag, needle in MISSING_FACT_GROUPS:
        if needle in reason:
            return tag
    return "other"


def build_work_queue(final_snapshot):
    """Built directly from the sealed batch's issues[] -- the single source
    of truth for what's open -- grouped by missing-fact-type first, then by
    subject (see task_plan.md Decision #4: missing-receipt items alone are
    ~half of all lines, and payment anomalies turned out to affect nearly as
    many, so grouping by type first keeps those patterns visible to ops
    instead of burying them across 100+ unsorted subject rows)."""
    claims_by_id = {c["claim_id"]: c for c in final_snapshot["claims"]}
    tc_by_id = {t["cancellation_id"]: t for t in final_snapshot["travel_cancellations"]}

    items = []
    for issue in final_snapshot["issues"]:
        record_id = issue["record_id"]
        fact_type = classify_reason(issue["reason"])
        if record_id.endswith("-finance-conflict"):
            subject_id = record_id[: -len("-finance-conflict")]
            subject_type = "claim"
            revision = claims_by_id.get(subject_id, {}).get("revision")
        elif record_id.endswith("-payment-anomaly"):
            subject_id = record_id[: -len("-payment-anomaly")]
            subject_type = "claim"
            revision = claims_by_id.get(subject_id, {}).get("revision")
        elif record_id.endswith("-financial"):
            subject_id = record_id[: -len("-financial")]
            subject_type = "travel_cancellation"
            revision = tc_by_id.get(subject_id, {}).get("trip_revision")
        elif record_id in claims_by_id:
            subject_id = record_id
            subject_type = "claim"
            revision = claims_by_id[record_id]["revision"]
        elif record_id in tc_by_id:
            subject_id = record_id
            subject_type = "travel_cancellation"
            revision = tc_by_id[record_id]["trip_revision"]
        else:
            subject_id = record_id
            subject_type = "unknown"
            revision = None

        items.append(
            {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "revision": revision,
                "missing_fact_or_reason": issue["reason"],
                "fact_type": fact_type,
                "owner": issue["owner"],
                "next_action": issue["resolution_needed"],
                "source_batch": final_snapshot["batch_id"],
            }
        )

    for t in final_snapshot["travel_cancellations"]:
        if t["status"] == "requested":
            items.append(
                {
                    "subject_type": "travel_cancellation",
                    "subject_id": t["cancellation_id"],
                    "revision": t["trip_revision"],
                    "missing_fact_or_reason": t["reason"],
                    "fact_type": "awaiting_confirmation",
                    "owner": t["next_owner"],
                    "next_action": "Awaiting directory supervisor confirmation",
                    "source_batch": final_snapshot["batch_id"],
                }
            )

    grouped = {}
    for it in items:
        grouped.setdefault(it["fact_type"], []).append(it)
    return {"generated_from_batch": final_snapshot["batch_id"], "groups": grouped, "total_items": len(items)}


def write_work_queue(final_snapshot, run_dir):
    wq = build_work_queue(final_snapshot)
    path = run_dir / "work_queue.json"
    path.write_text(json.dumps(wq, indent=2) + "\n")
    return path, wq


def money(cents):
    if cents is None:
        return "unknown"
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}EUR {cents // 100}.{cents % 100:02d}"


def write_report(run_id, batches, final_snapshot, wq, run_dir, sources_manifest):
    claims = final_snapshot["claims"]
    total_paid = sum(c["paid_cents"] for c in claims)
    total_allowed = sum(c["allowed_cents"] for c in claims if c["allowed_cents"] is not None)
    closed = [c for c in claims if c["status"] == "closed-reimbursed"]
    held = [c for c in claims if c["status"] == "held"]
    pending = [c for c in claims if c["status"] == "pending"]
    rejected = [c for c in claims if c["status"] == "rejected"]
    no_payment = [c for c in claims if c["status"] == "closed-no-payment"]

    outstanding_balance = sum(
        c["balance_cents"] for c in claims if c["balance_cents"] not in (None, 0)
    )

    no_claim_cancellations = [
        t for t in final_snapshot["travel_cancellations"] if not t["affected_claim_ids"]
    ]

    # Significant changes: claims whose status differs between first and last batch.
    first_by_id = {c["claim_id"]: c["status"] for c in batches[0]["claims"]}
    changes = []
    for c in claims:
        prev = first_by_id.get(c["claim_id"])
        if prev is not None and prev != c["status"]:
            changes.append((c["claim_id"], prev, c["status"]))
        elif prev is None:
            changes.append((c["claim_id"], "(not yet arrived)", c["status"]))

    finance_conflicts = [i for i in final_snapshot["issues"] if i["record_id"].endswith("-finance-conflict")]
    conflict_claim_ids = {i["record_id"][: -len("-finance-conflict")] for i in finance_conflicts}

    payment_anomalies = [
        i for i in final_snapshot["issues"]
        if i["record_id"].endswith("-payment-anomaly")
        and i["record_id"][: -len("-payment-anomaly")] not in conflict_claim_ids
    ]
    anomaly_total_cents = sum(
        c["paid_cents"]
        for c in claims
        if c["status"] in ("held", "pending", "rejected")
        and c["paid_cents"]
        and c["claim_id"] not in conflict_claim_ids
    )
    conflict_total_cents = sum(
        c["paid_cents"] for c in claims if c["claim_id"] in conflict_claim_ids
    )

    lines = []
    lines.append(f"# Ops handoff report -- run {run_id}\n")
    lines.append(f"Final batch: `{final_snapshot['batch_id']}` (of {len(batches)} sealed batches). ")
    lines.append(f"Source binding: `{final_snapshot['source_binding']['path']}` "
                 f"(sha256 `{final_snapshot['source_binding']['sha256'][:16]}...`).\n")

    predecessor_run_id = sources_manifest.get("predecessor_run_id")
    if predecessor_run_id:
        lines.append("## Why this run exists: predecessor link and correction\n")
        lines.append(
            f"This run supersedes `{predecessor_run_id}` (predecessor; see its own "
            f"`report.md`/`sources.json`)."
            + (f" {sources_manifest['_correction_note']}" if sources_manifest.get("_correction_note") else "")
        )
        lines.append("")

    unknown_category_items = wq["groups"].get("unknown_category", [])
    if unknown_category_items:
        lines.append("## ⚠ Unknown expense category\n")
        lines.append(
            f"**{len(unknown_category_items)} line(s)** use an expense category outside the 5 "
            "POL-2026.2 documents. Per policy's own wording (\"An unknown category ... is "
            "unresolved, never an assumed zero\"), these are held, not guessed at -- see the "
            "`unknown_category` group in `work_queue.json`."
        )
        lines.append("")

    if finance_conflicts:
        lines.append("## ⚠ Lead finding: Finance's own ledger contradicts itself\n")
        lines.append(
            f"**{len(finance_conflicts)} claim(s)** have a request where Finance's own activity log "
            f"reaches one terminal status (settled or cancelled) and later reaches the *other* one for "
            f"the same request -- net **{money(conflict_total_cents)}** paid against request(s) Finance "
            "had already marked cancelled. This is not a claim-side evidence or review gap (no amount of "
            "missing receipts or pending sign-off explains it) and it will not self-resolve as evidence "
            "arrives -- Finance/administration must determine which fact is authoritative before the "
            "revision can close. See the `finance_sequence_conflict` group in `work_queue.json`."
        )
        lines.append("")

    if payment_anomalies:
        lines.append("## ⚠ Lead finding: payments recorded against unreviewed/unsupported claims\n")
        lines.append(
            f"Finance's own activity log shows **{len(payment_anomalies)} of {len(claims)} claims** "
            f"with money actually settled (net **{money(anomaly_total_cents)}**) even though the "
            "current claim revision is not `closed-reimbursed` -- most commonly because the claimed "
            "cost has no matching receipt in the retained receipts binder, or the revision has no "
            "recorded administration/budget_owner/supervisor review at all. This Skill does **not** "
            "infer a review that was never recorded, and does not hide or reverse the payment fact --"
            " it reports both the real money movement and the real evidence/review gap side by side. "
            "See the `payment_anomaly` group in `work_queue.json` for the full per-claim list, and "
            "route to Finance/administration to confirm each payment or begin recovery."
        )
        lines.append("")

    lines.append("## Completed work\n")
    lines.append(f"- **{len(closed)} claims closed-reimbursed**, total paid **{money(total_paid)}**.")
    if no_payment:
        lines.append(f"- **{len(no_payment)} claims closed-no-payment** (zero entitlement or cancelled request, real reason retained, no invented payment).")
    if rejected:
        lines.append(f"- **{len(rejected)} claim rejected**: " + ", ".join(f"{c['claim_id']} ({c['reason']})" for c in rejected))
    confirmed_cancellations = [t for t in final_snapshot["travel_cancellations"] if t["status"] == "confirmed"]
    lines.append(f"- **{len(confirmed_cancellations)} of {len(final_snapshot['travel_cancellations'])} cancellations confirmed** by the directory supervisor.")
    if no_claim_cancellations:
        ids = ", ".join(t["cancellation_id"] for t in no_claim_cancellations)
        lines.append(
            f"- **{len(no_claim_cancellations)} cancellation(s) with no claim ever attached** ({ids}): "
            "closed/tracked with their real no-financial-effect or business reason -- no claim row invented for them."
        )
    lines.append("")

    lines.append("## Amounts\n")
    lines.append(f"- Total computed entitlement across all claims (supported lines only): **{money(total_allowed)}**")
    lines.append(f"- Total net paid to date: **{money(total_paid)}**")
    lines.append(f"- Outstanding balance (allowed - paid, non-zero only): **{money(outstanding_balance)}**")
    lines.append("")

    lines.append("## Outstanding obligations / unresolved work\n")
    lines.append(f"- **{len(held)} claims held** (evidence gap or a discretionary business return -- see work queue).")
    lines.append(f"- **{len(pending)} claims pending** (no review decision has arrived yet for the current revision).")
    unresolved_cancellations = [t for t in final_snapshot["travel_cancellations"] if t["financial_status"] == "unresolved"]
    if unresolved_cancellations:
        lines.append(f"- **{len(unresolved_cancellations)} cancellation(s) with unresolved financial_status**, pending Finance's cancellation-bound cost disposition.")
    lines.append(f"- Full detail, grouped by missing-fact-type, in the local work queue: `work_queue.json` ({wq['total_items']} open items). Groups: " + ", ".join(f"{k} ({len(v)})" for k, v in sorted(wq["groups"].items(), key=lambda kv: -len(kv[1]))))
    lines.append("")

    lines.append("## Owned unresolved items (evidence genuinely does not support completion)\n")
    lines.append(
        "- **~half of all claim lines lack a receipt in the retained receipts binder** "
        "(e.g. COST-02, COST-04, COST-08, COST-12...) and none is supplied in the updates "
        "binder either. Per policy, missing evidence is never assumed zero -- these stay "
        "`held` across all 4 batches. Reconsider only if a future run's sources supply the "
        "missing receipts."
    )
    lines.append(
        "- **C21 stays `held`** on a budget_owner return (\"requests a funding review before "
        "committing\") that is never resolved in the retained sources -- a discretionary "
        "business hold, distinct from an evidence gap; reconsider if Finance/budget supplies "
        "a funding decision."
    )
    lines.append(
        "- **C18's revision 2 (trip reassigned to T18B) has never received a fresh "
        "administration/budget_owner/supervisor review** in the retained sources, so it sits "
        "`pending` even though its original revision was fully approved -- this is the direct "
        "consequence of Decision #2 (every revision, including a trip swap, requires full "
        "re-review, no carry-forward of a prior revision's approval). Separately, and not "
        "resolved by that review arriving: Finance's own activity log for REQ-C18 shows "
        "'cancelled' and then 'settled' for the same request, triggered by the trip reassignment "
        "landing while the cancellation was in flight -- tracked as its own "
        "`finance_sequence_conflict` item (distinct from the ordinary missing-receipt/awaiting-"
        "review anomalies above), since only Finance/administration can say which fact is "
        "authoritative."
    )
    lines.append("")

    lines.append("## Source / run references\n")
    for f in sources_manifest["files"]:
        lines.append(f"- `{f['source_id']}`: {f['url']} -> retained at `{f['path']}` (sha256 `{f['sha256'][:16]}...`)")
    lines.append(f"- Case clock used for filing-deadline computation: `{sources_manifest['case_clock']}`")
    lines.append("")

    lines.append("## Significant changes across the run's 4 batches\n")
    lines.append(f"- {len(changes)} claims changed status (or first appeared) between batch 1 and batch {len(batches)}.")
    sample = changes[:15]
    for cid, prev, cur in sample:
        lines.append(f"  - {cid}: {prev} -> {cur}")
    if len(changes) > len(sample):
        lines.append(f"  - ... and {len(changes) - len(sample)} more (see `claims.csv` + individual batch files for full detail).")
    lines.append("")

    lines.append("## Verification\n")
    lines.append("See `README.md` \"Verify\" section for the commands that reproduce this run and its replay check.")
    lines.append("")

    path = run_dir / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main(sources_json_path):
    run_dir = Path(sources_json_path).parent
    manifest = json.loads(Path(sources_json_path).read_text())
    batches = load_batches(run_dir)
    final_snapshot = batches[-1]
    csv_path = write_claims_csv(final_snapshot, run_dir)
    wq_path, wq = write_work_queue(final_snapshot, run_dir)
    report_path = write_report(manifest["run_id"], batches, final_snapshot, wq, run_dir, manifest)
    print("wrote", csv_path)
    print("wrote", wq_path)
    print("wrote", report_path)


if __name__ == "__main__":
    sources_json = sys.argv[1] if len(sys.argv) > 1 else "artifacts/runs/run-2026-09-30/sources.json"
    main(sources_json)
