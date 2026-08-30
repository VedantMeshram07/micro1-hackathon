"""
Ownership & bus-factor risk — the gap every security/CI scanner leaves open.
They tell a buyer WHAT's broken. This tells them whether anyone is left who
could fix it: a codebase with 24 known CVEs and an active team is a very
different acquisition than the same 24 CVEs with one departed maintainer.

Reuses the exact GitHub REST API pattern _mine_github_activity already uses
successfully — no new provider, no new LLM dependency, no new toolchain.
Two calls: repo metadata (for pushed_at) and /contributors (for bus factor).
Degrades gracefully on any failure, same as the rest of this pipeline —
missing evidence, not a crashed run.
"""

import datetime

import requests


def check_ownership_risk(github_url: str, github_token: str | None) -> dict:
    if not github_url:
        return {"attempted": False, "reason": "No GitHub URL provided"}

    owner_repo = github_url.rstrip("/").replace("https://github.com/", "").replace(".git", "")
    headers = {"Authorization": f"token {github_token}"} if github_token else {}
    result = {"attempted": True, "error": None}

    try:
        repo_resp = requests.get(
            f"https://api.github.com/repos/{owner_repo}",
            headers=headers, timeout=15,
        )
        repo_resp.raise_for_status()
        repo_data = repo_resp.json()
        pushed_at = repo_data.get("pushed_at")
        if pushed_at:
            pushed_dt = datetime.datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            days_since_push = (datetime.datetime.now(datetime.timezone.utc) - pushed_dt).days
            result["days_since_last_push"] = days_since_push
        else:
            result["days_since_last_push"] = None

        contrib_resp = requests.get(
            f"https://api.github.com/repos/{owner_repo}/contributors",
            params={"per_page": 100}, headers=headers, timeout=15,
        )
        contrib_resp.raise_for_status()
        contributors = contrib_resp.json()

        if isinstance(contributors, list) and contributors:
            total = sum(c.get("contributions", 0) for c in contributors)
            top = contributors[0].get("contributions", 0)
            result["contributor_count"] = len(contributors)
            result["top_contributor_share_pct"] = round((top / total) * 100, 1) if total else None
        else:
            result["contributor_count"] = 0
            result["top_contributor_share_pct"] = None

    except requests.RequestException as e:
        result["error"] = f"GitHub API call failed: {e}"
        return result

    # Both signals bad together = the finding that actually matters.
    # Neither alone is damning (a stable single-maintainer library can be
    # fine; a young multi-contributor repo pushed yesterday is fine too).
    days = result.get("days_since_last_push")
    share = result.get("top_contributor_share_pct")
    result["bus_factor_flag"] = bool(
        days is not None and share is not None
        and days > 180 and share > 80
    )

    return result
