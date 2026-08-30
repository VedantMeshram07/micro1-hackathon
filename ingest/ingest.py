"""
Repo ingestion: turn a GitHub URL, a local .zip, or a local folder into a
normalized local checkout, plus surface-level metadata (language/build system,
file tree, README) that both the baseline and the agent build on.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Directories we never want to walk into or count as "code"
IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".next", "target", ".idea", ".vscode",
    "vendor", ".tox",
}

# Marker file -> (language label, package manager label)
LANGUAGE_MARKERS = {
    "package.json": ("javascript/typescript", "npm"),
    "requirements.txt": ("python", "pip"),
    "pyproject.toml": ("python", "pip/poetry"),
    "setup.py": ("python", "pip"),
    "pom.xml": ("java", "maven"),
    "build.gradle": ("java", "gradle"),
    "Cargo.toml": ("rust", "cargo"),
    "go.mod": ("go", "go modules"),
    "CMakeLists.txt": ("cpp", "cmake"),
}

README_NAMES = ["README.md", "README.rst", "README.txt", "README"]


def _rmtree_force(path: str) -> None:
    """shutil.rmtree that also clears Windows read-only bits and handles transient
    Windows file locks with retries."""
    def _clear_readonly(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    for attempt in range(5):
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=_clear_readonly)
            else:
                shutil.rmtree(path, onerror=lambda f, p, ei: _clear_readonly(f, p, ei[1]))
            return
        except OSError:
            if attempt < 4:
                time.sleep(0.5 * (attempt + 1))
            else:
                raise


@dataclass
class IngestResult:
    local_path: str
    source: str  # "github" | "zip" | "local"
    languages: list = field(default_factory=list)  # [(lang, pkg_manager), ...]
    file_tree: list = field(default_factory=list)  # relative paths
    readme_text: str = ""
    truncated: bool = False  # True if file_tree hit max_files cap


def ingest(source: str, dest_root: str = "repos", pinned_commit: str | None = None,
           max_files: int = 500, max_depth: int = 6) -> IngestResult:
    """
    source: a GitHub URL, a path to a local .zip, or a path to a local directory.
    Returns an IngestResult with a normalized local checkout and surface metadata.
    """
    os.makedirs(dest_root, exist_ok=True)

    if source.startswith("http://") or source.startswith("https://"):
        local_path = _clone_github(source, dest_root, pinned_commit)
        kind = "github"
    elif source.endswith(".zip"):
        local_path = _extract_zip(source, dest_root)
        kind = "zip"
    else:
        if not os.path.isdir(source):
            raise ValueError(f"Local path does not exist or is not a directory: {source}")
        local_path = source
        kind = "local"

    languages = _detect_languages(local_path)
    file_tree, truncated = _get_file_tree(local_path, max_files=max_files, max_depth=max_depth)
    readme_text = _read_readme(local_path)

    return IngestResult(
        local_path=local_path,
        source=kind,
        languages=languages,
        file_tree=file_tree,
        readme_text=readme_text,
        truncated=truncated,
    )


def _clone_github(url: str, dest_root: str, pinned_commit: str | None) -> str:
    repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    dest = os.path.join(dest_root, repo_name)
    if os.path.exists(dest):
        _rmtree_force(dest)

    # GIT_TERMINAL_PROMPT=0 stops git from trying to show an interactive
    # credential prompt (common on Windows via Git Credential Manager, even
    # for public repos that need no auth) — without it, a prompt attempt
    # just hangs silently until the timeout, instead of failing fast with a
    # clear error.
    git_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    if pinned_commit:
        # Fetch the exact commit directly rather than shallow-cloning the
        # branch tip and hoping the pin falls within that window — a
        # --depth N clone of HEAD often won't include a pinned commit from
        # further back in an active project's history (bit us on pydantic,
        # whose pin was thousands of commits behind current HEAD).
        os.makedirs(dest, exist_ok=True)
        subprocess.run(["git", "init", "--quiet"], check=True, capture_output=True,
                        text=True, cwd=dest, timeout=30, env=git_env)
        subprocess.run(["git", "remote", "add", "origin", url], check=True,
                        capture_output=True, text=True, cwd=dest, timeout=30, env=git_env)
        fetch_res = subprocess.run(["git", "fetch", "--quiet", "--depth", "1", "origin", pinned_commit],
                        capture_output=True, text=True, cwd=dest, timeout=180, env=git_env)
        if fetch_res.returncode != 0:
            subprocess.run(["git", "fetch", "--quiet", "origin", pinned_commit],
                            check=True, capture_output=True, text=True, cwd=dest, timeout=180, env=git_env)
        subprocess.run(["git", "checkout", "--quiet", "FETCH_HEAD"], check=True,
                        capture_output=True, text=True, cwd=dest, timeout=30, env=git_env)
    else:
        # No pin given (e.g. live-ingest mode) — shallow clone of the branch
        # tip is fine since we just want "whatever's current."
        subprocess.run(
            ["git", "clone", "--depth", "50", url, dest],
            check=True, capture_output=True, text=True, timeout=180, env=git_env,
        )
    return dest


def _extract_zip(zip_path: str, dest_root: str) -> str:
    name = Path(zip_path).stem
    dest = os.path.join(dest_root, name)
    if os.path.exists(dest):
        _rmtree_force(dest)
    os.makedirs(dest, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        # Guard against zip-slip: refuse any member that would escape dest.
        for member in zf.namelist():
            target = os.path.realpath(os.path.join(dest, member))
            if not target.startswith(os.path.realpath(dest)):
                raise ValueError(f"Unsafe zip member path: {member}")
        zf.extractall(dest)

    # Many zips wrap everything in a single top-level folder — flatten it.
    entries = [e for e in os.listdir(dest) if not e.startswith("__MACOSX")]
    if len(entries) == 1 and os.path.isdir(os.path.join(dest, entries[0])):
        return os.path.join(dest, entries[0])
    return dest


def _detect_languages(repo_path: str) -> list:
    found = []
    for marker, (lang, pkg_mgr) in LANGUAGE_MARKERS.items():
        if os.path.exists(os.path.join(repo_path, marker)):
            found.append((lang, pkg_mgr))
    return found


def _get_file_tree(repo_path: str, max_files: int, max_depth: int):
    tree = []
    truncated = False
    base_depth = repo_path.rstrip(os.sep).count(os.sep)

    for root, dirs, files in os.walk(repo_path):
        depth = root.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]

        for f in files:
            rel = os.path.relpath(os.path.join(root, f), repo_path)
            tree.append(rel)
            if len(tree) >= max_files:
                truncated = True
                return sorted(tree), truncated

    return sorted(tree), truncated


def _read_readme(repo_path: str) -> str:
    for name in README_NAMES:
        p = os.path.join(repo_path, name)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    return fh.read()[:20000]  # cap so one giant README can't blow the prompt budget
            except OSError:
                continue
    return ""