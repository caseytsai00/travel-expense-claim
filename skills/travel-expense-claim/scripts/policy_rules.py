"""Pure business-rule functions from POL-2026.2 (artifacts/runs/<run>/sources/policy.md).

Every constant below cites the exact policy sentence it encodes. These are
POLICY constants (apply to every case), not case-specific hard-coded answers —
per-claim numbers (caps, FX rates, amounts) always come from the retained
workbook/PDFs via parse_sources.py, never from here.
"""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
import calendar

# "A director additionally reviews amounts strictly above EUR 1,000.00
#  ... Exactly EUR 1,000.00 does not require a director."
DIRECTOR_THRESHOLD_EUR_CENTS = 100_000

# "The latest ordinary filing date is two calendar months after trip end,
#  inclusive, with a nonexistent day clamped to month end."
FILING_WINDOW_MONTHS = 2

# Roles required for every claim AND every international-trip permit review,
# before any director trigger:
# "Permit administration, budget owner and supervisor review the trip
#  estimate. Claim administration, budget owner and supervisor separately
#  review actual reimbursement."
BASE_REQUIRED_ROLES = ("administration", "budget_owner", "supervisor")

# POL-2026.2 defines cost-treatment formulas for exactly these 5 categories
# (see "Category: <transport|conference|lodging|meals|personal>" in
# references/data-shapes.md). Policy's own text already covers anything
# outside this set: "An unknown category ... is unresolved, never an
# assumed zero" -- so engine.resolve_claim_line holds it unresolved rather
# than falling through to transport/conference's no-cap formula or any
# other category's cap lookup by accident.
KNOWN_RECEIPT_CATEGORIES = frozenset({"transport", "conference", "lodging", "meals", "personal"})


def parse_date(s):
    if not s:
        return None
    if isinstance(s, (date, datetime)):
        return s.date() if isinstance(s, datetime) else s
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def add_months_clamped(d, months):
    """Nonexistent day clamped to month end (trip ends 31 Aug -> deadline 31 Oct)."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def filing_deadline(trip_end_date):
    return add_months_clamped(trip_end_date, FILING_WINDOW_MONTHS)


def is_late_filing(submitted_date, trip_end_date):
    return submitted_date > filing_deadline(trip_end_date)


def director_required(allowed_total_eur_cents):
    """'strictly above' -- exactly at threshold does NOT require a director."""
    return (
        allowed_total_eur_cents is not None
        and allowed_total_eur_cents > DIRECTOR_THRESHOLD_EUR_CENTS
    )


def required_roles(allowed_total_eur_cents):
    roles = set(BASE_REQUIRED_ROLES)
    if director_required(allowed_total_eur_cents):
        roles.add("director")
    return roles


def satisfied_roles(role_field_values):
    """review_ledger 'Review roles' values are either a single role or a
    newline-joined combo like 'budget_owner\\nsupervisor' when budget owner
    and supervisor are 'the same stable person' -- 'one response with both
    roles satisfies those two positions for that subject/version.'"""
    out = set()
    for v in role_field_values:
        for part in str(v).split("\n"):
            part = part.strip()
            if part:
                out.add(part)
    return out


def round_half_up_cents(amount_decimal):
    """Round each converted line to EUR cents using decimal half-up."""
    d = Decimal(str(amount_decimal)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))


def lookup_fx_rate(fx_rows, currency, on_date):
    """Apply Finance's exact payment-date EUR-per-currency-unit rate; EUR uses 1.
    fx_rows: list of {'Currency':..., 'Rate date':..., 'EUR per currency unit':...}
    Returns (rate, fx_row_source_ref) or (None, None) if no rate covers the date."""
    if currency == "EUR":
        return Decimal("1"), None
    candidates = [r for r in fx_rows if r["Currency"] == currency]
    if not candidates:
        return None, None
    # This dataset supplies one rate per currency (no date range); if multiple
    # existed we'd need an exact/most-recent-<=on_date match -- handle both.
    exact = [r for r in candidates if parse_date(r["Rate date"]) == on_date]
    chosen = exact[0] if exact else max(
        (r for r in candidates if parse_date(r["Rate date"]) <= on_date),
        key=lambda r: parse_date(r["Rate date"]),
        default=None,
    )
    if chosen is None:
        return None, None
    return Decimal(str(chosen["EUR per currency unit"])), chosen["Rate reference"]


def lookup_cap(caps_rows, destination, category, on_date):
    """Caps.csv: 'Original currency per night/day. Dates inclusive.'
    Transport/conference have no cap by design (policy: 'no category cap')."""
    if category in ("transport", "conference"):
        return None
    for r in caps_rows:
        if r["Destination"] != destination or r["Category"] != category:
            continue
        eff_from = parse_date(r["Effective from"])
        eff_to = parse_date(r["Effective to"])
        if eff_from <= on_date <= eff_to:
            return {
                "amount_per_unit": Decimal(str(r["Amount per unit"])),
                "currency": r["Currency"],
                "cap_reference": r["Cap reference"],
            }
    return None


def compute_line_allowed_original(category, supported_gross_amount, documented_units, cap):
    """allowed_original = min(supported_gross, cap*units) for lodging/meals;
    transport/conference use supported gross amount directly (no cap)."""
    gross = Decimal(str(supported_gross_amount))
    if category in ("transport", "conference"):
        return gross
    if cap is None or documented_units is None:
        return None  # missing applicable cap or units -> unresolved, caller handles
    return min(gross, cap["amount_per_unit"] * documented_units)
