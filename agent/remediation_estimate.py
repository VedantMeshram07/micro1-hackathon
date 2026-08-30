"""
Translates already-gathered evidence into a transparent, disclosed
remediation-cost estimate — turns "24 known vulnerabilities" into "~X
engineer-hours before this is acquisition-ready," a number a non-technical
buyer can actually act on. This is the business-framing layer the tool's
intended user (a technical buyer doing due diligence) actually needs —
a score alone doesn't tell them what fixing it costs.

Every multiplier is a stated, disclosed assumption, not a claimed industry
benchmark. Presented as a range, not false precision. The full itemized
breakdown is always included so the estimate is auditable, not a black box
— exactly the same "show your evidence" standard as the rest of this tool.
"""

HOURS_PER_VULNERABLE_PACKAGE = 2
HOURS_PER_SECRET_PROD = 1
HOURS_TO_STAND_UP_TEST_SUITE = 8
HOURS_PER_LICENSE_CONFLICT = 4
UNCERTAINTY_RANGE = 0.3  # +/- 30%


def estimate_remediation_cost(evidence: dict) -> dict:
    line_items = []

    vulns = evidence.get("vulnerabilities", {})
    vulnerable_count = len(vulns.get("vulnerable", [])) if vulns.get("attempted") else 0
    if vulnerable_count:
        hours = vulnerable_count * HOURS_PER_VULNERABLE_PACKAGE
        line_items.append({
            "item": f"Upgrade {vulnerable_count} vulnerable dependenc{'y' if vulnerable_count == 1 else 'ies'}",
            "hours": hours,
            "basis": f"{HOURS_PER_VULNERABLE_PACKAGE}h per package (research safe upgrade + apply + regression test)",
        })

    secrets = evidence.get("secrets", {})
    prod_secrets = [f for f in secrets.get("findings", []) if not f.get("in_test_dir")]
    if prod_secrets:
        hours = len(prod_secrets) * HOURS_PER_SECRET_PROD
        line_items.append({
            "item": f"Rotate {len(prod_secrets)} hardcoded credential(s) found in production code",
            "hours": hours,
            "basis": f"{HOURS_PER_SECRET_PROD}h per finding (rotate + remove from code + wire to secrets manager)",
        })

    build_test = evidence.get("build_test", {})
    if not build_test.get("tests_ran", False):
        line_items.append({
            "item": "Stand up a working automated test suite",
            "hours": HOURS_TO_STAND_UP_TEST_SUITE,
            "basis": "Flat estimate — tests did not run successfully during audit",
        })

    license_check = evidence.get("license_check", {})
    dep_licenses = license_check.get("dependency_licenses", {})
    conflicts = dep_licenses.get("conflicts", []) if dep_licenses.get("attempted") else []
    if conflicts:
        hours = len(conflicts) * HOURS_PER_LICENSE_CONFLICT
        line_items.append({
            "item": f"Resolve {len(conflicts)} copyleft license conflict(s)",
            "hours": hours,
            "basis": f"{HOURS_PER_LICENSE_CONFLICT}h per conflict (legal review + find/swap alternative dependency)",
        })

    total_hours = sum(item["hours"] for item in line_items)
    low = round(total_hours * (1 - UNCERTAINTY_RANGE))
    high = round(total_hours * (1 + UNCERTAINTY_RANGE))

    return {
        "line_items": line_items,
        "total_hours_estimate": total_hours,
        "range_low": low,
        "range_high": high,
        "disclosure": (
            "Heuristic estimate based on the stated per-item assumptions above, "
            "not a professional engineering quote. Presented as a range "
            f"({low}-{high}h) to avoid false precision. Does not include general "
            "code-quality improvements beyond the specific findings listed."
        ),
    }
