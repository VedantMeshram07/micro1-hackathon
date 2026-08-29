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
import subprocess

import anthropic
import requests

from ingest.ingest import IngestResult
from agent.trajectory_logger import TrajectoryLogger

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
BUILD_TIMEOUT_SEC = 120

# Files worth reading in full for the sampled code review, in priority order.
ENTRY_POINT_HINTS = [
    "main.py", "app.py", "index.js", "index.ts", "server.js", "server.ts",
    "src/index.ts", "src/main.py", "src/app.py",
]
SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cpp", ".c"}


def audit_repo(repo_name: str, ingest_result: IngestResult, client: anthropic.Anthropic,
                logger: TrajectoryLogger, github_url: str | None = None,
                github_token: str | None = None) -> dict:
    evidence = {"repo": repo_name}

    evidence["build_test"] = _run_build_and_tests(ingest_result, logger)
    evidence["dependencies"] = _check_dependencies(ingest_result, logger)
    evidence["docker"] = _check_docker(ingest_result, logger)
    evidence["code_review"] = _sample_code_review(ingest_result, client, logger)
    evidence["activity"] = _mine_github_activity(github_url, github_token, logger) if github_url else None

    report = _synthesize_report(repo_name, ingest_result, evidence, client, logger)
    report["method"] = "agent"
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
        install = _run(["pip", "install", "-r", "requirements.txt", "--quiet"], cwd=path)
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
    findings = {"unpinned_count": 0, "total_declared": 0, "manifest_found": False}

    req_path = os.path.join(path, "requirements.txt")
    pkg_path = os.path.join(path, "package.json")

    if os.path.exists(req_path):
        findings["manifest_found"] = True
        with open(req_path, "r", errors="replace") as fh:
            lines = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
        findings["total_declared"] = len(lines)
        findings["unpinned_count"] = sum(1 for l in lines if "==" not in l)

    elif os.path.exists(pkg_path):
        findings["manifest_found"] = True
        with open(pkg_path, "r", errors="replace") as fh:
            data = json.load(fh)
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        findings["total_declared"] = len(deps)
        findings["unpinned_count"] = sum(1 for v in deps.values() if v.startswith("^") or v.startswith("~"))

    logger.log_step(
        step_type="check_dependencies",
        instruction="Check declared dependencies for version pinning as a lightweight maintenance-risk signal",
        tool_input={"manifest_checked": "requirements.txt or package.json"},
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

def _sample_code_review(ingest_result: IngestResult, client: anthropic.Anthropic,
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
        resp = client.messages.create(model=MODEL, max_tokens=500,
                                       messages=[{"role": "user", "content": prompt}])
        text = resp.content[0].text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"error": f"unparsable model output: {text[:200]}"}
        parsed["file"] = rel_path
        reviews.append(parsed)

        logger.log_step(
            step_type="llm_file_review",
            instruction=f"Review {rel_path} for readability, error handling, and concrete concerns",
            tool_input={"file": rel_path, "chars_sent": len(content)},
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
                        client: anthropic.Anthropic, logger: TrajectoryLogger) -> dict:
    prompt = (
        "You are writing an evidence-based code-quality due-diligence report. "
        "Use ONLY the evidence below — do not invent facts not supported by it. "
        "Every concern or strength must reference the specific evidence it came from.\n\n"
        f"Repository: {repo_name}\n\n"
        f"Detected languages: {ingest_result.languages}\n\n"
        f"Build/test evidence: {json.dumps(evidence['build_test'])}\n\n"
        f"Dependency evidence: {json.dumps(evidence['dependencies'])}\n\n"
        f"Docker evidence: {json.dumps(evidence['docker'])}\n\n"
        f"Sampled file reviews: {json.dumps(evidence['code_review'])}\n\n"
        f"GitHub activity: {json.dumps(evidence['activity'])}\n\n"
        "Respond ONLY with JSON in exactly this shape:\n"
        '{"score": <int 1-10>, '
        '"summary": "<2-3 sentence overall verdict>", '
        '"strengths": [{"point": "...", "evidence": "..."}], '
        '"risks": [{"point": "...", "evidence": "..."}], '
        '"unverifiable": ["<anything the pipeline could not check for this repo, and why>"]}'
    )

    resp = client.messages.create(model=MODEL, max_tokens=1200,
                                   messages=[{"role": "user", "content": prompt}])
    text = resp.content[0].text.strip()

    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        report = {"score": None, "summary": f"Could not parse synthesis output: {text[:300]}",
                   "strengths": [], "risks": [], "unverifiable": []}

    report["repo"] = repo_name
    report["raw_evidence"] = evidence

    logger.log_step(
        step_type="synthesize_report",
        instruction="Combine all gathered evidence into one scored, evidence-linked report",
        tool_input={"evidence_keys": list(evidence.keys())},
        tool_output=json.dumps(report)[:2000],
        decision="Final output for this run",
    )
    return report
