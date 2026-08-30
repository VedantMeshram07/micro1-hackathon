"""
The real agent: reads a repo the way a careful reviewer would, not just the
README. Every step is logged as a trajectory entry. Build/test failures and
unsupported languages are treated as *findings*, not crashes — the whole
pipeline is designed to always produce a report, even a partial one, because
a report that silently dies on a weird repo is worse than one that's honest
about what it couldn't check.
"""

import json
import os
import shutil
import subprocess

import requests

from agent.scan_secrets import scan_for_secrets
from agent.check_vulnerabilities import check_vulnerabilities
from agent.check_license import detect_project_license, check_dependency_licenses
from agent.remediation_estimate import estimate_remediation_cost
from ingest.ingest import IngestResult
from agent.trajectory_logger import TrajectoryLogger
from llm.client import LLMClient, parse_json_response

BUILD_TIMEOUT_SEC = 120

# Files worth reading in full for the sampled code review, in priority order.
ENTRY_POINT_HINTS = [
    "main.py", "app.py", "index.js", "index.ts", "server.js", "server.ts",
    "src/index.ts", "src/main.py", "src/app.py",
]
SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cpp", ".c"}


def audit_repo(repo_name: str, ingest_result: IngestResult, client: LLMClient,
                logger: TrajectoryLogger, github_url: str | None = None,
                github_token: str | None = None) -> dict:
    evidence = {"repo": repo_name}

    evidence["build_test"] = _run_build_and_tests(ingest_result, logger)
    evidence["dependencies"] = _check_dependencies(ingest_result, logger)
    evidence["docker"] = _check_docker(ingest_result, logger)
    evidence["secrets"] = scan_for_secrets(ingest_result.local_path)
    evidence["vulnerabilities"] = check_vulnerabilities(ingest_result.local_path, ingest_result.languages)
    evidence["license_check"] = {
        "project_license": detect_project_license(ingest_result.local_path),
        "dependency_licenses": check_dependency_licenses(ingest_result.local_path, ingest_result.languages),
    }
    evidence["code_review"] = _sample_code_review(ingest_result, client, logger)
    evidence["activity"] = _mine_github_activity(github_url, github_token, logger) if github_url else None
    evidence["remediation_estimate"] = estimate_remediation_cost(evidence)

    logger.log_step(
        step_type="scan_secrets_and_vulnerabilities",
        instruction="Run deterministic secret scan and OSV.dev dependency vulnerability check",
        tool_input={"repo": ingest_result.local_path},
        tool_output=json.dumps({"secrets": evidence["secrets"], "vulnerabilities": evidence["vulnerabilities"]})[:2000],
        decision="Feed into synthesis as hard, evidence-backed risk signals",
    )

    logger.log_step(
        step_type="check_license_and_estimate_remediation",
        instruction="Check project/dependency license conflicts and estimate remediation cost from all gathered evidence",
        tool_input={"repo": ingest_result.local_path},
        tool_output=json.dumps({"license_check": evidence["license_check"], "remediation_estimate": evidence["remediation_estimate"]})[:2000],
        decision="Feed into synthesis; remediation estimate also surfaced at top level of the final report",
    )

    report = _synthesize_report(repo_name, ingest_result, evidence, client, logger)
    report["method"] = "agent"
    report["remediation_estimate"] = evidence["remediation_estimate"]
    return report


# ---------------------------------------------------------------------------
# Step: build & test execution
# ---------------------------------------------------------------------------

def _run_build_and_tests(ingest_result: IngestResult, logger: TrajectoryLogger) -> dict:
    langs = {lang for lang, _ in ingest_result.languages}
    path = ingest_result.local_path

    if "python" in langs:
        result = _try_python(path)
    elif "javascript/typescript" in langs:
        result = _try_node(path)
    else:
        result = {
            "attempted": False,
            "reason": f"No deep build/test support yet for detected language(s): "
                      f"{sorted(langs) or ['unknown']}. Static/dependency/activity checks still ran.",
        }

    logger.log_step(
        step_type="run_build_and_tests",
        instruction="Attempt install + test run for the detected language, sandboxed with a timeout",
        tool_input={"languages": sorted(langs)},
        tool_output=json.dumps(result)[:2000],
        decision="Recorded as a finding either way — a failed or skipped build is evidence, not an error to hide",
    )
    return result


def _try_python(path: str) -> dict:
    try:
        if os.path.exists(os.path.join(path, "requirements.txt")):
            install = _run(["pip", "install", "-r", "requirements.txt", "--quiet"], cwd=path)
        elif os.path.exists(os.path.join(path, "pyproject.toml")):
            # No requirements.txt — install the package itself (editable) plus
            # pytest as a safety net, since test-runner presence isn't a
            # judgment on the project if it's just missing from our sandbox.
            install = _run(["pip", "install", "-e", ".", "--quiet"], cwd=path)
            _run(["pip", "install", "pytest", "--quiet"], cwd=path)
        else:
            return {"attempted": False, "reason": "No requirements.txt or pyproject.toml found — can't determine how to install."}

        test = _run(["python", "-m", "pytest", "--tb=no", "-q"], cwd=path)
        return {
            "attempted": True,
            "install_ok": install["ok"],
            "tests_ran": test["ok"] or "collected" in test["stdout"].lower(),
            "test_summary": test["stdout"][-1000:] or test["stderr"][-1000:],
        }
    except FileNotFoundError as e:
        return {"attempted": True, "install_ok": False, "tests_ran": False, "error": str(e)}


def _try_node(path: str) -> dict:
    try:
        install = _run(["npm", "install", "--no-audit", "--no-fund"], cwd=path)
        test = _run(["npm", "test", "--if-present"], cwd=path)
        return {
            "attempted": True,
            "install_ok": install["ok"],
            "tests_ran": test["ok"],
            "test_summary": test["stdout"][-1000:] or test["stderr"][-1000:],
        }
    except FileNotFoundError as e:
        return {"attempted": True, "install_ok": False, "tests_ran": False, "error": str(e)}


def _run(cmd: list, cwd: str) -> dict:
    resolved = shutil.which(cmd[0])
    if resolved is None:
        return {"ok": False, "stdout": "", "stderr": f"Command not found on PATH: {cmd[0]}"}
    cmd = [resolved] + cmd[1:]
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=BUILD_TIMEOUT_SEC,
        )
        return {"ok": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Timed out after {BUILD_TIMEOUT_SEC}s"}


# ---------------------------------------------------------------------------
# Step: dependency freshness (lightweight heuristic, not a CVE scan)
# ---------------------------------------------------------------------------

def _check_dependencies(ingest_result: IngestResult, logger: TrajectoryLogger) -> dict:
    path = ingest_result.local_path
    findings = {"unpinned_count": 0, "total_declared": 0, "manifest_found": False, "manifest_type": None}

    req_path = os.path.join(path, "requirements.txt")
    pkg_path = os.path.join(path, "package.json")
    pyproject_path = os.path.join(path, "pyproject.toml")

    if os.path.exists(req_path):
        findings["manifest_found"] = True
        findings["manifest_type"] = "requirements.txt"
        with open(req_path, "r", errors="replace") as fh:
            lines = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
        findings["total_declared"] = len(lines)
        findings["unpinned_count"] = sum(1 for l in lines if "==" not in l)

    elif os.path.exists(pkg_path):
        findings["manifest_found"] = True
        findings["manifest_type"] = "package.json"
        with open(pkg_path, "r", errors="replace") as fh:
            data = json.load(fh)
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        findings["total_declared"] = len(deps)
        findings["unpinned_count"] = sum(1 for v in deps.values() if v.startswith("^") or v.startswith("~"))

    elif os.path.exists(pyproject_path):
        findings["manifest_found"] = True
        findings["manifest_type"] = "pyproject.toml"
        try:
            import tomllib
            with open(pyproject_path, "rb") as fh:
                data = tomllib.load(fh)

            # PEP 621 standard format: [project] dependencies = ["pkg>=1.0", ...]
            pep621_deps = data.get("project", {}).get("dependencies", [])
            # Poetry-style: [tool.poetry.dependencies] pkg = "^1.0"
            poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})

            if pep621_deps:
                findings["total_declared"] = len(pep621_deps)
                findings["unpinned_count"] = sum(1 for d in pep621_deps if "==" not in d)
            elif poetry_deps:
                real_deps = {k: v for k, v in poetry_deps.items() if k.lower() != "python"}
                findings["total_declared"] = len(real_deps)
                findings["unpinned_count"] = sum(
                    1 for v in real_deps.values()
                    if not (isinstance(v, str) and v.startswith("=="))
                )
        except Exception as e:
            # Don't let a parsing quirk crash the whole audit — record it as
            # a finding instead (manifest presence is still correctly noted).
            findings["parse_error"] = str(e)

    logger.log_step(
        step_type="check_dependencies",
        instruction="Check declared dependencies for version pinning as a lightweight maintenance-risk signal",
        tool_input={"manifest_checked": findings.get("manifest_type")},
        tool_output=json.dumps(findings),
        decision="Flag as a risk factor if a large share of deps are unpinned, not a hard fail",
    )
    return findings


# ---------------------------------------------------------------------------
# Step: Docker runnability (the one generic cross-language signal)
# ---------------------------------------------------------------------------

def _check_docker(ingest_result: IngestResult, logger: TrajectoryLogger) -> dict:
    path = ingest_result.local_path
    has_dockerfile = os.path.exists(os.path.join(path, "Dockerfile"))
    has_compose = os.path.exists(os.path.join(path, "docker-compose.yml")) or \
        os.path.exists(os.path.join(path, "docker-compose.yaml"))

    result = {"has_dockerfile": has_dockerfile, "has_compose": has_compose, "build_attempted": False}

    logger.log_step(
        step_type="check_docker",
        instruction="Check for containerization as a maintainability signal",
        tool_input=None,
        tool_output=json.dumps(result),
        decision="Note presence only in this MVP; live `docker build` verification is a stretch add if time allows",
    )
    return result


# ---------------------------------------------------------------------------
# Step: sampled code review (this is where real judgment happens)
# ---------------------------------------------------------------------------

def _sample_code_review(ingest_result: IngestResult, client: LLMClient,
                          logger: TrajectoryLogger, max_files: int = 5) -> list:
    candidates = _pick_files_to_review(ingest_result.file_tree, max_files)
    reviews = []

    for rel_path in candidates:
        full_path = os.path.join(ingest_result.local_path, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()[:8000]
        except OSError:
            continue

        prompt = (
            f"Review this source file from an unfamiliar repository. File: {rel_path}\n\n"
            f"```\n{content}\n```\n\n"
            "Respond ONLY with JSON: "
            '{"readability": "<1 sentence>", "error_handling": "<1 sentence>", '
            '"concerns": ["<specific, evidence-based concern>", ...], "notable_strengths": ["...", ...]}'
        )
        try:
            parsed = client.complete_json(prompt, max_tokens=900)
        except ValueError as e:
            parsed = {"error": str(e)}
        parsed["file"] = rel_path
        reviews.append(parsed)

        logger.log_step(
            step_type="llm_file_review",
            instruction=f"Review {rel_path} for readability, error handling, and concrete concerns",
            tool_input={"file": rel_path, "chars_sent": len(content), "active_model": client.get_active_model()},
            tool_output=json.dumps(parsed)[:1500],
            decision="Feed into final synthesis as one evidence source among several",
        )

    return reviews


def _pick_files_to_review(file_tree: list, max_files: int) -> list:
    picked = [f for f in ENTRY_POINT_HINTS if f in file_tree]
    source_files = [f for f in file_tree if os.path.splitext(f)[1] in SOURCE_EXTENSIONS and f not in picked]
    # Bias toward files that are likely core logic, not tests/config —
    # crude but effective: skip anything with 'test' in the path for this pass.
    source_files = [f for f in source_files if "test" not in f.lower()]
    picked.extend(source_files[: max(0, max_files - len(picked))])
    return picked[:max_files]


# ---------------------------------------------------------------------------
# Step: GitHub PR/issue activity mining
# ---------------------------------------------------------------------------

def _mine_github_activity(github_url: str, github_token: str | None, logger: TrajectoryLogger) -> dict:
    owner_repo = github_url.rstrip("/").replace("https://github.com/", "").replace(".git", "")
    headers = {"Authorization": f"token {github_token}"} if github_token else {}
    result = {"error": None}

    try:
        issues_resp = requests.get(
            f"https://api.github.com/repos/{owner_repo}/issues",
            params={"state": "open", "per_page": 30}, headers=headers, timeout=15,
        )
        issues_resp.raise_for_status()
        issues = issues_resp.json()
        result["open_issue_count_sampled"] = len(issues)

        pulls_resp = requests.get(
            f"https://api.github.com/repos/{owner_repo}/pulls",
            params={"state": "closed", "per_page": 30}, headers=headers, timeout=15,
        )
        pulls_resp.raise_for_status()
        pulls = pulls_resp.json()
        merged = [p for p in pulls if p.get("merged_at")]
        result["recent_merge_count_sampled"] = len(merged)

    except requests.RequestException as e:
        result["error"] = f"GitHub API call failed (rate limit or network): {e}"

    logger.log_step(
        step_type="mine_github_activity",
        instruction="Sample recent open issues and merged PRs as a maintenance-activity signal",
        tool_input={"repo": owner_repo},
        tool_output=json.dumps(result),
        decision="Treat API failure as missing evidence, not a pipeline crash",
    )
    return result


# ---------------------------------------------------------------------------
# Step: final synthesis — every claim ties back to something gathered above
# ---------------------------------------------------------------------------

def _synthesize_report(repo_name: str, ingest_result: IngestResult, evidence: dict,
                        client: LLMClient, logger: TrajectoryLogger) -> dict:
    prompt = (
        "You are writing an evidence-based code-quality due-diligence report. "
        "Use ONLY the evidence below — do not invent facts not supported by it. "
        "Every concern or strength must reference the specific evidence it came from.\n\n"
        f"Repository: {repo_name}\n\n"
        f"Detected languages: {ingest_result.languages}\n\n"
        f"Build/test evidence: {json.dumps(evidence['build_test'])}\n\n"
        f"Dependency evidence: {json.dumps(evidence['dependencies'])}\n\n"
        f"Docker evidence: {json.dumps(evidence['docker'])}\n\n"
        f"Secret/credential scan (regex + entropy + keyword-context, cross-checked against known cases): {json.dumps(evidence['secrets'])}\n\n"
        f"Dependency vulnerability scan (via OSV.dev, Google's vulnerability database): {json.dumps(evidence['vulnerabilities'])}\n\n"
        f"License check (project license from local LICENSE file; dependency licenses from PyPI/npm registries — note: PyPI license data is frequently missing, ~78% in calibration testing, this is a known data-source limitation not a red flag): {json.dumps(evidence['license_check'])}\n\n"
        f"Remediation cost estimate (heuristic, engineer-hours to address findings above — cite the total and range in your summary): {json.dumps(evidence['remediation_estimate'])}\n\n"
        f"Sampled file reviews: {json.dumps(evidence['code_review'])}\n\n"
        f"GitHub activity: {json.dumps(evidence['activity'])}\n\n"
        "Score anchor — commit to a band, don't default to the middle:\n"
        "9-10: Builds cleanly, real passing tests, active maintenance, no significant risks found\n"
        "7-8: Builds and mostly works, only minor gaps, no major red flags\n"
        "5-6: Some real risks present but core functionality is demonstrated\n"
        "3-4: Significant risks (failed build/tests, undefined behavior, security issues) outweigh strengths\n"
        "1-2: Fundamentally broken, unusable, or dangerous as evidenced\n"
        "Two repos with meaningfully different evidence should get meaningfully different scores — "
        "don't converge on a 'safe' middle number. HARD REQUIREMENT, not a suggestion: if "
        "evidence['secrets']['findings'] contains ANY entry with in_test_dir=false, you MUST include "
        "a corresponding entry in 'risks' naming the specific file and finding type — do not omit it, "
        "do not summarize it away. If evidence['vulnerabilities']['vulnerable'] is non-empty, you MUST "
        "include a corresponding entry in 'risks' naming the specific vulnerable package(s) and citing "
        "the vulnerability count. If evidence['license_check']['dependency_licenses']['conflicts'] is "
        "non-empty, you MUST include a risk entry naming the conflicting package(s) and their license. "
        "Your 'summary' field MUST include the remediation_estimate's total_hours_estimate and range — "
        "a report that gathers this evidence and then doesn't mention it is a failure of this task, "
        "regardless of what score you land on. Findings inside test directories "
        "(in_test_dir: true) are lower priority and may be mentioned briefly or omitted if space-constrained.\n\n"
        "Respond ONLY with JSON in exactly this shape:\n"
        '{"score": <int 1-10>, '
        '"summary": "<2-3 sentence overall verdict>", '
        '"strengths": [{"point": "...", "evidence": "..."}], '
        '"risks": [{"point": "...", "evidence": "..."}], '
        '"unverifiable": ["<anything the pipeline could not check for this repo, and why>"]}'
    )

    try:
        # Bumped from 2500: adding license-conflict and remediation-estimate
        # citation requirements grew the required response content —
        # verified truncation was the actual cause of a correlation crash
        # tonight (0.971 -> 0.152) once those requirements were added.
        report = client.complete_json(prompt, max_tokens=3500)
    except ValueError as e:
        report = {"score": None, "summary": str(e),
                   "strengths": [], "risks": [], "unverifiable": []}

    report["repo"] = repo_name
    report["raw_evidence"] = evidence

    logger.log_step(
        step_type="synthesize_report",
        instruction="Combine all gathered evidence into one scored, evidence-linked report",
        tool_input={"evidence_keys": list(evidence.keys()), "active_model": client.get_active_model()},
        tool_output=json.dumps(report)[:2000],
        decision="Final output for this run",
    )
    return report
