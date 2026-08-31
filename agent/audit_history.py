"""
Persists a one-row summary of every completed audit to Supabase, and reads
back recent history for the hosted app's "past audits" view. Uses
Supabase's REST API (PostgREST) directly via `requests` — no new pip
package, same pattern as every other external call tonight (GitHub,
PyPI, npm, OSV.dev). Degrades gracefully: a missing/unreachable Supabase
config never breaks an audit run, it just skips persistence.
"""

import requests


def save_audit_record(repo_name: str, github_url: str, report: dict,
                       supabase_url: str | None, supabase_key: str | None) -> dict:
    if not supabase_url or not supabase_key:
        return {"attempted": False, "reason": "Supabase not configured"}

    remediation = report.get("remediation_estimate", {})
    integrity = report.get("integrity_check", {})

    payload = {
        "repo_name": repo_name,
        "github_url": github_url,
        "score": report.get("score"),
        "remediation_hours": remediation.get("total_hours_estimate"),
        "integrity_passed": integrity.get("passed"),
    }

    try:
        resp = requests.post(
            f"{supabase_url}/rest/v1/audit_history",
            json=payload,
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return {"attempted": True, "saved": True}
    except requests.RequestException as e:
        return {"attempted": True, "saved": False, "error": str(e)}


def get_recent_audits(supabase_url: str | None, supabase_key: str | None, limit: int = 20) -> list:
    if not supabase_url or not supabase_key:
        return []
    try:
        resp = requests.get(
            f"{supabase_url}/rest/v1/audit_history",
            params={"select": "*", "order": "created_at.desc", "limit": limit},
            headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return []