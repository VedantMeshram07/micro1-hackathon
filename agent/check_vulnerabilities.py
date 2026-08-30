"""
Queries OSV.dev (Google's free, no-auth vulnerability database) for every
declared dependency. Exact-pinned deps get queried by exact version
(precise); unpinned deps get queried by name only (broader — flags if the
package has EVER had a known vulnerability, not necessarily in the
installed version — labeled as such in output, since precision matters
for an evidence-based report).
"""

import json
import os

import requests

ECOSYSTEM_MAP = {"python": "PyPI", "javascript/typescript": "npm"}


def _post_with_retry(url: str, payload: dict, retries: int = 3, timeout: int = 20):
    """OSV.dev documents no hard rate limit, but a transient 403 was
    observed during real testing tonight — brief backoff-and-retry covers
    that without adding real complexity."""
    import time
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))  # 2s, 4s
    raise last_err


def check_vulnerabilities(repo_path: str, languages: list) -> dict:
    ecosystem = None
    for lang, _ in languages:
        if lang in ECOSYSTEM_MAP:
            ecosystem = ECOSYSTEM_MAP[lang]
            break
    if not ecosystem:
        return {"attempted": False, "reason": "No supported ecosystem (Python/npm) detected"}

    deps = _parse_deps_for_osv(repo_path, ecosystem)
    if not deps:
        return {"attempted": True, "packages_checked": 0, "vulnerable": [], "note": "No dependencies to check"}

    queries = []
    for name, version in deps:
        q = {"package": {"name": name, "ecosystem": ecosystem}}
        if version:
            q["version"] = version
        queries.append(q)

    try:
        resp = _post_with_retry(
            "https://api.osv.dev/v1/querybatch",
            {"queries": queries},
        )
        results = resp.json().get("results", [])
    except requests.RequestException as e:
        return {"attempted": True, "error": f"OSV.dev API call failed: {e}"}

    vulnerable = []
    for (name, version), result in zip(deps, results):
        vulns = result.get("vulns", [])
        if vulns:
            vulnerable.append({
                "package": name,
                "version_checked": version or "(unpinned — checked by name only)",
                "vuln_ids": [v["id"] for v in vulns][:5],
                "count": len(vulns),
            })

    return {
        "attempted": True,
        "packages_checked": len(deps),
        "vulnerable": vulnerable,
        "vulnerable_count": len(vulnerable),
    }


def _parse_deps_for_osv(repo_path: str, ecosystem: str) -> list:
    deps = []
    if ecosystem == "PyPI":
        req_path = os.path.join(repo_path, "requirements.txt")
        if os.path.exists(req_path):
            with open(req_path, "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "==" in line:
                        name, version = line.split("==", 1)
                        deps.append((name.strip(), version.strip()))
                    else:
                        name = line.split(">=")[0].split("<")[0].split("~=")[0].strip()
                        if name:
                            deps.append((name, None))
    elif ecosystem == "npm":
        pkg_path = os.path.join(repo_path, "package.json")
        if os.path.exists(pkg_path):
            with open(pkg_path, "r", errors="replace") as f:
                data = json.load(f)
            all_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for name, version_spec in all_deps.items():
                clean_version = version_spec.lstrip("^~=")
                is_exact = version_spec[0] not in "^~>=<"
                deps.append((name, clean_version if is_exact else None))
    return deps
