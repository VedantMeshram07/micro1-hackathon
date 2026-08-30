"""
The agent checking its own honesty. Every other module in this pipeline
finds risk IN the code being audited. This one finds risk in the AUDIT
ITSELF — whether evidence the pipeline gathered actually made it into the
human-readable report, or got silently dropped during synthesis.

This isn't hypothetical: tonight's actual build history includes a real
case of this exact failure — a synthesis pass that found a genuine GPL
license conflict, included it in raw_evidence, and then never mentioned
it anywhere in the risks list. The fix that caught it was a manual
`findstr` check run by a human. This module is that check, automated,
so it runs on every report instead of only the ones someone happens to
audit by hand.

Deterministic, no LLM call — the check itself must be trustworthy
independent of the model that might be the one making the mistake.
"""


def check_report_integrity(evidence: dict, report: dict) -> list[str]:
    """Returns a list of human-readable violation descriptions. Empty
    list means every hard-citation requirement was actually satisfied."""
    violations = []
    risks_text = " ".join(
        f"{r.get('point', '')} {r.get('evidence', '')}"
        for r in report.get("risks", [])
    )
    summary_text = report.get("summary", "")
    full_text = risks_text + " " + summary_text

    secrets = evidence.get("secrets", {})
    for finding in secrets.get("findings", []):
        if not finding.get("in_test_dir") and finding.get("file") not in full_text:
            violations.append(
                f"Secret finding in '{finding.get('file')}' is in raw_evidence "
                f"but not cited anywhere in the report's risks or summary."
            )

    vulns = evidence.get("vulnerabilities", {})
    if vulns.get("attempted"):
        for v in vulns.get("vulnerable", []):
            pkg = v.get("package", "")
            if pkg and pkg not in full_text:
                violations.append(
                    f"Vulnerable package '{pkg}' is in raw_evidence but not "
                    f"cited anywhere in the report's risks or summary."
                )

    license_check = evidence.get("license_check", {})
    conflicts = license_check.get("dependency_licenses", {}).get("conflicts", [])
    for c in conflicts:
        pkg = c.get("package", "")
        if pkg and pkg not in full_text:
            violations.append(
                f"License conflict for '{pkg}' is in raw_evidence but not "
                f"cited anywhere in the report's risks or summary."
            )

    ownership = evidence.get("ownership_risk", {})
    if ownership.get("bus_factor_flag"):
        share = str(ownership.get("top_contributor_share_pct", ""))
        days = str(ownership.get("days_since_last_push", ""))
        if share not in full_text or days not in full_text:
            violations.append(
                f"Bus-factor risk was flagged (share={share}%, days={days}) "
                f"but the exact figures are not cited anywhere in the report."
            )

    remediation = evidence.get("remediation_estimate", {})
    total_hours = remediation.get("total_hours_estimate")
    if total_hours is not None and str(total_hours) not in summary_text:
        violations.append(
            f"Remediation estimate ({total_hours}h total) exists but is not "
            f"stated in the report's summary field."
        )

    return violations
